"""Stage: assemble. A deterministic FFmpeg edit, built entirely from storyboard.json.

Modes
  radio  the narration over placeholder music on a black screen, with captions and
         shot labels, for the first audience test (the PDF's "radio cut").
  rough  slow pans over the keyframes (clips where they exist) with the score.
  final  Wan clips where they exist, pans where they do not, the score ducked
         under the voice, loudness at -14 LUFS, captions burned in, the AI end
         card, exported 9:16 and 16:9.

Timing comes from the narration: a shot lasts at least its lead-in, its lines,
the pauses between them and a tail. Every shot is rendered to its own segment,
cached by a hash of its inputs, so changing one shot re-renders one segment.
"""
from __future__ import annotations

import array
import json
import math
import re
import shutil
import textwrap
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import grade, jobs, motion
from . import storyboard as sbmod
from .cache import StageCache, key_for, sha256_file
from .engines import FALLBACK, MODES, stretch_cap
from .config import FONTS, Project
from .media import measure_loudness, probe_duration, probe_video, run_ffmpeg

ASSEMBLE_VERSION = 5
TRIM_HEAD = 0.12          # many generated clips have a weak first frames
MIN_FILM, MAX_FILM = 60.0, 90.0
FORMATS = {"9x16": (1080, 1920), "16x9": (1920, 1080)}
CAPTION_STYLE = {  # TikTok-like: bold white, soft dark outline, top centre on vertical
    "9x16": {"size": 62, "margin_v": 300, "align": 8},
    "16x9": {"size": 50, "margin_v": 70, "align": 2},
    "radio": {"size": 46, "margin_v": 220, "align": 8},
}


@dataclass
class LineEvent:
    item: str
    speaker: str
    start: float
    end: float
    en: str
    path: Path


@dataclass
class ShotTime:
    id: str
    start: float
    duration: float
    lines: list[LineEvent] = field(default_factory=list)


# ---------------------------------------------------------------- timeline

def build_timeline(sb: dict[str, Any], project: Project) -> tuple[list[ShotTime], float]:
    edit = sbmod.edit_settings(sb)
    fps = edit["fps"]
    cache = StageCache(project, "narration")
    from .narration import line_items, spec_for  # same keys the narration stage wrote
    shots: list[ShotTime] = []
    t = 0.0
    by_shot: dict[str, list[tuple[str, dict[str, Any], Path, float]]] = {}
    for item, shot, line in line_items(sb):
        key = key_for(spec_for(sb, line))
        path = cache.hit(item, key, ".wav") or cache.current(item)
        if path is None:
            raise FileNotFoundError(f"no narration for {item}; run `make narration` first")
        by_shot.setdefault(shot["id"], []).append((item, line, path, probe_duration(path)))
    for shot in sb["shots"]:
        lines = by_shot.get(shot["id"], [])
        speech = sum(d for *_, d in lines) + edit["gap_s"] * max(0, len(lines) - 1)
        if lines:
            needed = edit["lead_s"] + speech + edit["tail_s"]
            duration = max(needed, shot["duration_s"] * 0.7, 2.5)
        else:
            duration = shot["duration_s"]
        duration = round(duration * fps) / fps
        timing = ShotTime(shot["id"], t, duration)
        cursor = t + edit["lead_s"]
        for item, line, path, d in lines:
            timing.lines.append(LineEvent(item, line["speaker"], cursor, cursor + d, line["en"], path))
            cursor += d + edit["gap_s"]
        shots.append(timing)
        t += duration
    film = t + sb["end_card"]["duration_s"]
    if film < MIN_FILM:  # stretch evenly so the film reaches the brief's minimum
        extra = (MIN_FILM + 0.5 - film) / len(shots)
        return _restretch(shots, extra, fps), MIN_FILM + 0.5 - sb["end_card"]["duration_s"]
    return shots, t


def _restretch(shots: list[ShotTime], extra: float, fps: int) -> list[ShotTime]:
    t = 0.0
    out = []
    for s in shots:
        duration = round((s.duration + extra) * fps) / fps
        shift = t - s.start
        lines = [LineEvent(l.item, l.speaker, l.start + shift, l.end + shift, l.en, l.path) for l in s.lines]
        out.append(ShotTime(s.id, t, duration, lines))
        t += duration
    return out


# ---------------------------------------------------------------- captions

def caption_chunks(text: str, width: int) -> list[str]:
    """Captions of at most two lines of `width` characters, split at punctuation where possible
    (the first version split mid-phrase: "...walking nearly three hours down the")."""
    limit = width * 2
    pieces = re.split(r"(?<=[,.;:!?])\s+", text.strip()) if len(text) > limit else [text.strip()]
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = f"{current} {piece}".strip()
        if len(candidate) <= limit or not current:
            current = candidate
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    out = []
    for chunk in chunks:
        lines = textwrap.wrap(chunk, width=width, break_long_words=False) or [chunk]
        out += ["\\N".join(lines[i:i + 2]) for i in range(0, len(lines), 2)]
    return out


def _ass_time(seconds: float) -> str:
    cs = int(round(seconds * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def caption_events(shots: list[ShotTime], width: int) -> list[tuple[float, float, str]]:
    events = []
    for shot in shots:
        for line in shot.lines:
            chunks = caption_chunks(line.en, width)
            total = sum(len(c) for c in chunks)
            t = line.start
            for chunk in chunks:
                share = (line.end - line.start) * len(chunk) / total
                events.append((t, t + share, chunk))
                t += share
    return events


def write_ass(path: Path, events: list[tuple[float, float, str]], fmt: str, *,
              labels: list[tuple[float, float, str]] | None = None) -> None:
    w, h = (720, 1280) if fmt == "radio" else FORMATS[fmt]
    style = CAPTION_STYLE[fmt]
    rows = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,Noto Sans,{style['size']},&H00FFFFFF,&H00FFFFFF,&H5A000000,&H96000000,-1,0,0,0,100,100,"
        f"0,0,1,2.6,2.2,{style['align']},70,70,{style['margin_v']},1",
        "Style: Label,Noto Sans,28,&H00B0B0B0,&H00B0B0B0,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,30,30,30,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, text in events:
        rows.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{text}")
    for start, end, text in labels or []:
        rows.append(f"Dialogue: 1,{_ass_time(start)},{_ass_time(end)},Label,,0,0,0,,{text}")
    path.write_text("\n".join(rows) + "\n", "utf-8")


def write_srt(path: Path, events: list[tuple[float, float, str]]) -> None:
    blocks = [f"{i}\n{_srt_time(s)} --> {_srt_time(e)}\n{t.replace(chr(92) + 'N', chr(10))}\n"
              for i, (s, e, t) in enumerate(events, 1)]
    path.write_text("\n".join(blocks), "utf-8")


def _fonts_dir(project: Project) -> str:
    """libass needs a font folder path without a drive colon: copy fonts next to the work files."""
    target = project.outputs / "_tmp" / "fonts"
    if not target.exists():
        shutil.copytree(FONTS, target)
    return target.relative_to(project.root).as_posix()


# ---------------------------------------------------------------- pictures

def _ease(frames: int) -> str:
    p = f"(on/{max(frames - 1, 1)})"
    return f"({p}*{p}*(3-2*{p}))"


def kenburns_filter(mode: str, frames: int, w: int, h: int, fps: int) -> str:
    e = _ease(frames)
    zoom, x, y = "1.0", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    if mode == "zoom-in":
        zoom = f"1.0+0.12*{e}"
    elif mode == "zoom-out":
        zoom = f"1.12-0.12*{e}"
    elif mode in ("pan-left", "pan-right"):
        zoom = "1.12"
        x = f"(iw-iw/zoom)*{'(1-' + e + ')' if mode == 'pan-left' else e}"
    elif mode in ("pan-up", "pan-down"):
        zoom = "1.12"
        y = f"(ih-ih/zoom)*{'(1-' + e + ')' if mode == 'pan-up' else e}"
    big_w, big_h = w * 3, h * 3  # zoom on a larger frame to avoid zoompan jitter
    return (f"scale={big_w}:{big_h}:force_original_aspect_ratio=increase:flags=lanczos,crop={big_w}:{big_h},"
            f"zoompan=z='{zoom}':x='{x}':y='{y}':d={frames}:s={w}x{h}:fps={fps},setsar=1,format=yuv420p")


def render_segment(source: dict[str, Any], duration: float, out: Path, *, w: int, h: int, fps: int,
                   interpolation: str = "rife", lut: Path | None = None) -> None:
    """One shot's picture at its exact length. Sources:
    clip      a generated clip: RIFE to 24 fps, slowed at most to its cap, then the last frame held;
    loop      a composited ping-pong cycle, retimed to 24 fps and looped to fill the shot;
    parallax  a camera move over the still from its depth map;
    image     a slow pan or zoom over the still (kenburns "still" holds it);
    black     nothing yet (the radio cut).
    `lut` is a .cube file (grade.py) applied to every frame; FFmpeg runs in its folder so the
    filter needs no drive colon."""
    kind = source["kind"]
    lut = None if kind == "black" else lut
    graded = f"lut3d={lut.name}," if lut else ""
    cwd = lut.parent if lut else None
    frames = int(round(duration * fps))
    common = ["-an", "-r", str(fps), "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast",
              "-crf", "18", "-pix_fmt", "yuv420p", str(out)]
    fit = f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1"
    if kind in ("clip", "loop"):
        src, src_fps = motion.read_frames(source["path"])
        if kind == "clip":
            src = src[int(round(TRIM_HEAD * src_fps)):] or src  # many clips start weak
        length = len(src) / src_fps
        stretch = min(source.get("cap", 1.0), duration / length) if kind == "clip" and length < duration else 1.0
        interpolator = _interpolator(src[0].shape[1], src[0].shape[0]) if interpolation == "rife" else None
        timed = out.with_name(out.stem + ".timed.mp4")
        motion.write_frames(motion.retime(src, src_fps, out_fps=fps, stretch=stretch, interpolator=interpolator),
                            timed, fps, crf=14)
        if kind == "loop":
            run_ffmpeg(["-stream_loop", "-1", "-i", str(timed), "-vf", f"{fit},{graded}format=yuv420p", *common],
                       cwd=cwd)
        else:
            run_ffmpeg(["-i", str(timed), "-vf", f"{fit},tpad=stop_mode=clone:stop_duration={duration:.3f},"
                        f"{graded}format=yuv420p", *common], cwd=cwd)
        timed.unlink(missing_ok=True)
    elif kind == "parallax":
        moved = out.with_name(out.stem + ".parallax.mp4") if lut else out
        motion.render_parallax(source["path"], source["depth"], moved, duration=frames / fps, fps=fps, size=(w, h),
                               move=source["move"], amount=source["amount"])
        if lut:  # one extra pass to grade the frames
            run_ffmpeg(["-i", str(moved), "-vf", f"{graded}format=yuv420p", *common], cwd=cwd)
            moved.unlink(missing_ok=True)
    elif kind == "image":
        run_ffmpeg(["-i", str(source["path"]), "-vf", graded +
                    kenburns_filter(source.get("kenburns", "zoom-in"), frames, w, h, fps), *common], cwd=cwd)
    else:  # black
        run_ffmpeg(["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}", *common])


_INTERPOLATORS: dict[tuple[int, int], Any] = {}


def _interpolator(width: int, height: int):
    """One RIFE instance per clip size; None (repeat frames) if RIFE cannot start here."""
    if (width, height) not in _INTERPOLATORS:
        try:
            _INTERPOLATORS[(width, height)] = motion.Interpolator(width, height)
            print(f"  RIFE {motion.RIFE_MODEL} on {_INTERPOLATORS[(width, height)].device}")
        except Exception as exc:  # keep the edit going; the clip just repeats frames
            print(f"  RIFE unavailable ({exc}); repeating frames instead")
            _INTERPOLATORS[(width, height)] = None
    return _INTERPOLATORS[(width, height)]


def end_card_image(sb: dict[str, Any], w: int, h: int, out: Path) -> None:
    palette = sb["style"].get("palette") or ["#0E1A33", "#F2A541"]
    bg, accent = palette[0], palette[1] if len(palette) > 1 else "#F2A541"
    img = Image.new("RGB", (w, h), bg)
    draw = ImageDraw.Draw(img)
    for y in range(h):  # gentle vertical gradient
        shade = int(18 * y / h)
        r, g, b = img.getpixel((0, y))
        draw.line([(0, y), (w, y)], fill=(max(0, r - shade), max(0, g - shade), max(0, b - shade)))
    scale = min(w, h) / 1080
    title_font = ImageFont.truetype(str(FONTS / "NotoSans-Bold.ttf"), int(96 * scale))
    body_font = ImageFont.truetype(str(FONTS / "NotoSans-Regular.ttf"), int(38 * scale))
    small_font = ImageFont.truetype(str(FONTS / "NotoSans-Regular.ttf"), int(30 * scale))
    cx, cy = w / 2, h / 2
    draw.text((cx, cy - 120 * scale), sb["end_card"]["title"], font=title_font, fill="#FFFFFF", anchor="mm")
    draw.rounded_rectangle([cx - 60 * scale, cy - 40 * scale, cx + 60 * scale, cy - 32 * scale],
                           radius=4, fill=accent)
    y = cy + 20 * scale
    for i, line in enumerate(sb["end_card"]["lines"]):
        font = body_font if i == 0 else small_font
        for part in textwrap.wrap(line, width=42 if w < h else 70):
            draw.text((cx, y), part, font=font, fill="#F5E6C8" if i == 0 else "#B9C3D6", anchor="mm")
            y += (54 if i == 0 else 44) * scale
        y += 18 * scale
    draw.text((cx, h - 90 * scale), sb["title"], font=small_font, fill="#7F8BA3", anchor="mm")
    img.save(out)


# ---------------------------------------------------------------- audio

def narration_bed(shots: list[ShotTime], total: float, out: Path, rate: int = 24000) -> None:
    """Place every line at its start time on one mono track (exact, no resampling drift)."""
    buf = array.array("h", bytes(2 * int(math.ceil(total * rate))))
    for shot in shots:
        for line in shot.lines:
            with wave.open(str(line.path), "rb") as wav:
                if wav.getframerate() != rate or wav.getnchannels() != 1:
                    raise ValueError(f"{line.path.name}: expected {rate} Hz mono")
                samples = array.array("h", wav.readframes(wav.getnframes()))
            offset = int(round(line.start * rate))
            end = min(len(buf), offset + len(samples))
            buf[offset:end] = samples[:end - offset]
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(buf.tobytes())


def placeholder_music(total: float) -> list[str]:
    """A quiet G-major drone with slow tremolo: a temp track for the radio cut only."""
    tones = "+".join(f"{a}*sin(2*PI*{f}*t)" for f, a in ((98.0, 0.30), (146.83, 0.22), (196.0, 0.18), (246.94, 0.10)))
    return ["-f", "lavfi", "-i", f"aevalsrc='{tones}':s=48000:d={total:.2f}"]


def mix_audio(sb: dict[str, Any], narration: Path, music: Path | None, total: float, out: Path) -> dict[str, Any]:
    duck = sbmod.ducking(sb)
    gain = sb["music"].get("gain_db", -3)
    music_args = (["-stream_loop", "-1", "-i", str(music)] if music else placeholder_music(total))
    graph = (
        f"[0:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={total:.3f},asplit=2[n1][n2];"
        f"[1:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:d=1.5,afade=t=out:st={max(0.0, total - 3.5):.3f}:d=3.5,volume={gain}dB[m];"
        f"[m][n1]sidechaincompress=threshold={duck['threshold']}:ratio={duck['ratio']}:"
        f"attack={duck['attack_ms']}:release={duck['release_ms']}[md];"
        f"[n2][md]amix=inputs=2:normalize=0:duration=first[mix]"
    )
    raw = out.with_name(out.stem + ".premaster.wav")
    run_ffmpeg(["-i", str(narration), *music_args, "-filter_complex", graph, "-map", "[mix]",
                "-t", f"{total:.3f}", "-c:a", "pcm_s16le", str(raw)])
    m = measure_loudness(raw)  # pass 1 of a two-pass loudnorm to -14 LUFS / -1.5 dBTP
    norm = (f"loudnorm=I=-14:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m.get('target_offset', 0)}:"
            "linear=true")
    run_ffmpeg(["-i", str(raw), "-af", norm, "-ar", "48000", "-c:a", "pcm_s16le", str(out)])
    raw.unlink(missing_ok=True)
    return {"premaster_lufs": m["input_i"], "ducking": duck, "music_gain_db": gain,
            "music": music.name if music else "placeholder drone"}


# ---------------------------------------------------------------- sources

def _source_for(project: Project, sb: dict[str, Any], shot: dict[str, Any], mode: str,
                keyframe: Path) -> dict[str, Any] | None:
    """What `mode` needs for this shot, or None if it is not available (then fall back)."""
    from .shots import clip_spec

    sid = shot["id"]
    motion_cfg = shot["motion"]
    if mode in ("full_i2v", "flf_inbetween", "masked_i2v", "cinemagraph"):
        end = StageCache(project, "keyframes").current(f"{sid}_end") if motion_cfg["mode"] == "flf_inbetween" else None
        if motion_cfg["mode"] == "flf_inbetween" and end is None:
            return None
        clip = StageCache(project, "shots/raw").hit(sid, key_for(clip_spec(sb, shot, keyframe, end)), ".mp4")
        if clip is None:
            return None
        if mode in ("full_i2v", "flf_inbetween"):
            return {"kind": "clip", "path": clip, "cap": stretch_cap(shot)}
        entry = StageCache(project, "shots").entry(sid) or {}
        composite = StageCache(project, "shots").current(sid)
        if composite is None or entry.get("spec", {}).get("clip") != sha256_file(clip):
            return None
        loop = motion_cfg.get("loop", "pingpong")
        return {"kind": "loop" if loop == "pingpong" else "clip", "path": composite, "cap": stretch_cap(shot)}
    if mode == "parallax":
        entry = StageCache(project, "depth").entry(sid) or {}
        depth = StageCache(project, "depth").current(sid)
        if depth is None or entry.get("spec", {}).get("keyframe") != sha256_file(keyframe):
            return None
        params = {"move": "push-in", "amount": 0.03, **motion_cfg.get("parallax", {})}
        return {"kind": "parallax", "path": keyframe, "depth": depth, **params}
    if mode == "still":
        return {"kind": "image", "path": keyframe, "kenburns": "still"}
    return {"kind": "image", "path": keyframe, "kenburns": motion_cfg.get("kenburns", "zoom-in")}


def shot_source(project: Project, sb: dict[str, Any], shot: dict[str, Any], mode: str) -> dict[str, Any]:
    """Walk the shot's fallback chain (engines.FALLBACK) and say which source it ended on.
    storyboard edit.use can swap the mode the chain starts from for this cut.
    The rough cut skips paid modes, so it shows what the film looks like for free."""
    if mode == "radio":
        return {"kind": "black", "used": "black"}
    keyframe = StageCache(project, "keyframes").current(shot["id"])
    if keyframe is None:
        print(f"  {shot['id']}: no keyframe yet, using black")
        return {"kind": "black", "used": "black"}
    wanted = sbmod.edit_settings(sb).get("use", {}).get(shot["id"]) or shot["motion"]["mode"]
    chain = [wanted] + FALLBACK[wanted]
    if mode == "rough":
        chain = [m for m in chain if not MODES[m]["paid"]]
    for candidate in chain or ["still_kenburns"]:
        source = _source_for(project, sb, shot, candidate, keyframe)
        if source is not None:
            return {**source, "used": candidate, "wanted": wanted}
    return {"kind": "image", "path": keyframe, "kenburns": "zoom-in", "used": "still_kenburns", "wanted": wanted}


def grade_luts(project: Project, sb: dict[str, Any], mode: str) -> dict[str, Path]:
    """One .cube per shot that moves its keyframe toward the film's look (grade.py), or none
    for the radio cut or edit.grade false. The look is edit.grade.target if fixed, otherwise
    the median of all current keyframes."""
    edit = sbmod.edit_settings(sb)
    setting = edit.get("grade", True)
    if mode == "radio" or setting is False:
        return {}
    cache = StageCache(project, "keyframes")
    stills = {s["id"]: cache.current(s["id"]) for s in sb["shots"]}
    stills = {sid: p for sid, p in stills.items() if p}
    if not stills:
        return {}
    look = setting["target"] if isinstance(setting, dict) and "target" in setting else grade.target(list(stills.values()))
    strength = edit.get("grade_strength", grade.STRENGTH)
    folder = project.outputs / "assemble" / "grade"
    luts = {}
    for sid, still in stills.items():
        text = grade.cube_text(grade.lut(grade.stats(still), look, strength), sid)
        path = folder / f"{sid}__{key_for({'cube': text})}.cube"
        if not path.exists():
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(text, "ascii")
        luts[sid] = path
    return luts


def chosen_music(project: Project, sb: dict[str, Any]) -> Path | None:
    cache = StageCache(project, "music")
    chosen = sb["music"].get("chosen")
    index = 0 if chosen is None else chosen
    path = cache.current(f"candidate_{index}")
    if path and chosen is None:
        print(f"  music: no candidate chosen in storyboard.json yet; using candidate_{index}")
    return path


# ---------------------------------------------------------------- run

def _concat(segments: list[Path], out: Path) -> None:
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in segments), "utf-8")
    run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])
    listing.unlink(missing_ok=True)


def run(project: Project, *, mode: str = "final") -> dict[str, Any]:
    sb = sbmod.load_valid(project)
    edit = sbmod.edit_settings(sb)
    fps = edit["fps"]
    shots, picture_len = build_timeline(sb, project)
    end_len = 0.0 if mode == "radio" else sb["end_card"]["duration_s"]
    total = picture_len + end_len
    print(f"  timeline: {len(shots)} shots, {picture_len:.1f}s + {end_len:.0f}s end card = {total:.1f}s")
    work = project.outputs / "assemble"
    work.mkdir(parents=True, exist_ok=True)
    seg_cache = StageCache(project, "assemble/segments")
    fonts = _fonts_dir(project)
    formats = ["radio"] if mode == "radio" else ["9x16", "16x9"]

    # 1. picture: one cached segment per shot, at 9:16 (radio: 720x1280 black)
    w, h = (720, 1280) if mode == "radio" else FORMATS["9x16"]
    interpolation = sb.get("video", {}).get("interpolation", "rife")
    segments, used = [], {}
    rendered = 0
    luts = grade_luts(project, sb, mode)
    for timing, shot in zip(shots, sb["shots"]):
        jobs.check()  # a stopped studio job ends here, between items
        source = shot_source(project, sb, shot, mode)
        lut = luts.get(shot["id"]) if source["kind"] != "black" else None
        used[shot["id"]] = {k: source.get(k) for k in ("used", "wanted")}
        spec = {"v": ASSEMBLE_VERSION, "kind": source["kind"],
                "src": sha256_file(source["path"]) if source.get("path") else None,
                "depth": sha256_file(source["depth"]) if source.get("depth") else None,
                "dur": timing.duration, "w": w, "h": h, "fps": fps,
                **{k: source.get(k) for k in ("kenburns", "move", "amount", "cap")},
                "interp": f"{interpolation}:{motion.RIFE_MODEL}" if source["kind"] in ("clip", "loop") else None,
                "grade": lut.stem.split("__")[1] if lut else None}
        key = key_for(spec)
        seg = seg_cache.hit(shot["id"], key, ".mp4")
        if not seg:
            seg = seg_cache.path(shot["id"], key, ".mp4")
            render_segment(source, timing.duration, seg, w=w, h=h, fps=fps, interpolation=interpolation, lut=lut)
            seg_cache.record(shot["id"], key, seg, spec)
            rendered += 1
        segments.append(seg)
    fell_back = [f"{sid} {u['wanted']}->{u['used']}" for sid, u in used.items()
                 if u.get("wanted") and u["used"] != u["wanted"]]
    print(f"  picture: {rendered} segment(s) rendered, {len(segments) - rendered} reused"
          + (f"; fell back: {', '.join(fell_back)}" if fell_back else ""))
    picture = work / f"picture_{mode}.mp4"
    _concat(segments, picture)

    # 2. sound: narration bed + music, ducked and normalised
    bed = work / f"narration_{mode}.wav"
    narration_bed(shots, total, bed)
    music = None if mode == "radio" else chosen_music(project, sb)
    mix = work / f"mix_{mode}.wav"
    mix_info = mix_audio(sb, bed, music, total, mix)

    # 3. captions and exports
    events = caption_events(shots, edit["caption_chars"])
    report: dict[str, Any] = {"mode": mode, "duration_s": round(total, 2), "shots": len(shots), **mix_info,
                              "sources": used}
    slug = "radio_cut" if mode == "radio" else ("rough_cut" if mode == "rough" else "heritage_short")
    out_dir = project.outputs / ("final" if mode == "final" else "cuts")
    out_dir.mkdir(parents=True, exist_ok=True)
    write_srt(out_dir / f"{slug}.en.srt", events)
    for fmt in formats:
        fw, fh = (720, 1280) if fmt == "radio" else FORMATS[fmt]
        ass = work / f"captions_{mode}_{fmt}.ass"
        labels = [(s.start, s.start + s.duration, s.id) for s in shots] if mode == "radio" else None
        write_ass(ass, events, fmt, labels=labels)
        full = work / f"picture_{mode}_{fmt}_full.mp4"
        if fmt == "16x9":
            wide = work / f"picture_{mode}_16x9.mp4"
            fill = ("[0:v]split[a][b];[a]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
                    "scale=96:54:flags=bilinear,scale=1920:1080:flags=bicubic,eq=brightness=-0.10:saturation=0.8[bg];"
                    "[b]scale=-2:1080:flags=lanczos[fg];[bg][fg]overlay=(W-w)/2:0,setsar=1,format=yuv420p[v]")
            run_ffmpeg(["-i", str(picture), "-filter_complex", fill, "-map", "[v]", "-r", str(fps),
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(wide)])
            base = wide
        else:
            base = picture
        if end_len:
            card_png = work / f"end_card_{fmt}.png"
            end_card_image(sb, fw, fh, card_png)
            card = work / f"end_card_{fmt}.mp4"
            render_segment({"kind": "image", "path": card_png, "kenburns": "zoom-in"}, end_len, card,
                           w=fw, h=fh, fps=fps)
            _concat([base, card], full)
        else:
            shutil.copy2(base, full)
        out = out_dir / (f"{slug}.mp4" if fmt == "radio" else f"{slug}_{fmt}.mp4")
        vf = f"subtitles={ass.relative_to(project.root).as_posix()}:fontsdir={fonts}"
        if end_len:  # fade the picture out into the end card, and the end card out at the very end
            vf += f",fade=t=out:st={total - 0.6:.3f}:d=0.6"
        run_ffmpeg(["-i", str(full), "-i", str(mix), "-vf", vf, "-map", "0:v", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(fps),
                    "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", "-shortest",
                    str(out)], cwd=project.root)
        loud = measure_loudness(out)
        report[fmt] = {"file": out.relative_to(project.root).as_posix(), "duration_s": round(probe_duration(out), 2),
                       "lufs": loud.get("input_i"), "true_peak_db": loud.get("input_tp"),
                       "size_mb": round(out.stat().st_size / 1e6, 1)}
        print(f"  {fmt}: {report[fmt]['file']}  {report[fmt]['duration_s']}s  "
              f"{report[fmt]['lufs']} LUFS  TP {report[fmt]['true_peak_db']} dB  {report[fmt]['size_mb']} MB")
    (out_dir / f"{slug}.report.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return report


# ---------------------------------------------------------------- one scene

PREVIEW_SIZE = (540, 960)


def preview(project: Project, shot_id: str) -> dict[str, Any]:
    """One scene as it would play in the final cut, small and with its voice: the studio's
    scene preview. Uses only what exists (free motion until a clip is bought), cached."""
    sb = sbmod.load_valid(project)
    shot = next(s for s in sb["shots"] if s["id"] == shot_id)
    edit = sbmod.edit_settings(sb)
    fps, (w, h) = edit["fps"], PREVIEW_SIZE
    from .narration import spec_for
    cache = StageCache(project, "narration")
    lines = []
    for n, line in enumerate(shot["lines"], 1):
        path = cache.hit(f"{shot_id}_L{n}", key_for(spec_for(sb, line)), ".wav")
        if path:
            lines.append((path, probe_duration(path), line["en"]))
    speech = sum(d for _, d, _ in lines) + edit["gap_s"] * max(0, len(lines) - 1)
    duration = max(edit["lead_s"] + speech + edit["tail_s"], shot["duration_s"] * 0.7, 2.5) if lines \
        else shot["duration_s"]
    duration = round(duration * fps) / fps
    source = shot_source(project, sb, shot, "final")
    lut = grade_luts(project, sb, "final").get(shot_id) if source["kind"] != "black" else None
    spec = {"v": ASSEMBLE_VERSION, "kind": source["kind"], "dur": duration, "w": w, "h": h,
            "src": sha256_file(source["path"]) if source.get("path") else None,
            "depth": sha256_file(source["depth"]) if source.get("depth") else None,
            **{k: source.get(k) for k in ("kenburns", "move", "amount", "cap")},
            "lines": [sha256_file(p) for p, _, _ in lines], "grade": lut.stem.split("__")[1] if lut else None}
    previews = StageCache(project, "preview")
    key = key_for(spec)
    out = previews.hit(shot_id, key, ".mp4")
    if out is None:
        out = previews.path(shot_id, key, ".mp4")
        picture = out.with_name(out.stem + ".picture.mp4")
        render_segment(source, duration, picture, w=w, h=h, fps=fps, lut=lut,
                       interpolation=sb.get("video", {}).get("interpolation", "rife"))
        timing = ShotTime(shot_id, 0.0, duration)
        cursor = edit["lead_s"]
        for path, d, en in lines:
            timing.lines.append(LineEvent(path.stem, "", cursor, cursor + d, en, path))
            cursor += d + edit["gap_s"]
        bed = out.with_suffix(".wav")
        narration_bed([timing], duration, bed)
        run_ffmpeg(["-i", str(picture), "-i", str(bed), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", str(out)])
        picture.unlink(missing_ok=True)
        bed.unlink(missing_ok=True)
        previews.record(shot_id, key, out, spec, used=source["used"])
    return {"file": out, "used": source["used"], "wanted": source.get("wanted"), "seconds": duration}
