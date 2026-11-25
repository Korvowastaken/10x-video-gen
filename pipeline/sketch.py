"""Stage: sketch. A shape storyboard: one quick frame per shot from flat geometry.

Nothing here calls a model, so it is free and takes a second. It lets a person
approve composition (who is where, how big, what moves) before any image is
generated:
  - the place is a two-band flat fill whose colours come from the location id;
  - each character is a labelled head-and-body shape in its own colour, sized by
    the shot size (a wide shot shows small figures, a close-up crops the body);
  - arrows and dashed shapes on top show the planned motion, and a "$" badge marks
    the modes that pay for a generated clip;
  - a header names the mode, a footer gives shot id, size, duration and subtitle.
A shot's optional `sketch.positions` ({character id: [x, y]}, 0..1, the centre of
the figure's head) moves a figure; otherwise figures spread across the frame.

Outputs: outputs/sketch/<shot>__<key>.png, contact_sheet.jpg and animatic.mp4
(the frames held for each shot's duration_s).
"""
from __future__ import annotations

import colorsys
import io
import math
import shutil
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import storyboard as sbmod
from .cache import StageCache, key_for, write_atomic
from .config import FONTS, Project
from .engines import MODES
from .keyframes import contact_sheet
from .media import run_ffmpeg

RENDER_VERSION = 2
W, H = 540, 960
FPS = 24
HEADER_H, FOOTER_H = 52, 190
HORIZON = 0.58
# Figure height (head to feet) as a fraction of frame height, by shot size.
FIGURE_HEIGHT = {"extreme-wide": 0.15, "wide": 0.28, "medium": 0.55, "medium-close-up": 0.75,
                 "close-up": 1.1, "extreme-close-up": 1.7, "over-the-shoulder": 0.5, "insert": 0.0}
HEAD = 0.13            # head radius as a fraction of figure height
PALETTE = ["#E4572E", "#17BEBB", "#FFC914", "#7BC043", "#9B5DE5", "#F15BB5", "#2E86DE", "#FF8C42"]
INK, MARK = "#151515", "#FFFFFF"


@lru_cache(maxsize=None)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")), size)


def figure_height(size: str) -> float:
    return FIGURE_HEIGHT[size]


def _place_colours(index: int) -> tuple[str, str]:
    """A muted sky/wall colour and a darker ground/floor colour per place. Hues step by the
    golden ratio through the places' order, so neighbouring places never look alike."""
    hue = 0.58 + index * 0.381966
    def hexed(h: float, s: float, v: float) -> str:
        return "#" + "".join(f"{round(c * 255):02X}" for c in colorsys.hsv_to_rgb(h % 1, s, v))
    return hexed(hue, 0.22, 0.80), hexed(hue + 0.08, 0.30, 0.50)


def _first_words(text: str, n: int = 6) -> str:
    words = text.split()
    return " ".join(words[:n]).rstrip(".,:;") + ("…" if len(words) > n else "")


def _default_positions(size: str, count: int) -> list[list[float]]:
    h = FIGURE_HEIGHT[size]
    head_y = round(max(0.74 - h + HEAD * h, 0.32), 3)  # feet on the lower-middle, big heads near the top third
    if size == "over-the-shoulder":   # first figure is the foreground shoulder, others face it
        others = [[round(0.68 + 0.2 * i / max(count - 2, 1), 3), 0.42] for i in range(count - 1)]
        return [[0.06, 0.62]] + others
    if count == 1:
        return [[0.5, head_y]]
    return [[round(0.22 + 0.56 * i / (count - 1), 3), head_y] for i in range(count)]


def frame_spec(sb: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    """Everything that changes a sketch frame's pixels, and nothing else."""
    order = [c["id"] for c in sb["characters"]]
    names = sbmod.characters(sb)
    location = next(loc for loc in sb["locations"] if loc["id"] == shot["location"])
    motion = shot["motion"]
    cast = [] if shot["size"] == "insert" else shot["characters"]
    defaults = _default_positions(shot["size"], len(cast))
    moved = shot.get("sketch", {}).get("positions", {})
    mode = motion["mode"]
    marks: dict[str, Any] = {"mode": mode, "paid": bool(MODES.get(mode, {}).get("paid"))}
    if mode == "parallax":
        marks["move"] = motion.get("parallax", {}).get("move", "push-in")
    elif mode == "still_kenburns":
        marks["kenburns"] = motion.get("kenburns", "zoom-in")
    elif mode in ("masked_i2v", "cinemagraph"):
        marks["target"] = _first_words(motion.get("mask", {}).get("target", ""), 5)
        marks["regions"] = motion.get("mask", {}).get("regions", [])
    spec = {
        "v": RENDER_VERSION, "id": shot["id"], "size": shot["size"], "duration_s": shot["duration_s"],
        "location": {"id": location["id"], "name": location["name"], "index": sb["locations"].index(location)},
        "characters": [{"id": cid, "name": names[cid]["name"], "colour": order.index(cid) % len(PALETTE),
                        "at": [float(v) for v in moved.get(cid, defaults[n])]} for n, cid in enumerate(cast)],
        "motion": marks,
        "text": shot["lines"][0]["en"] if shot["lines"] else shot["beat"],
    }
    if shot["size"] == "insert":
        spec["object"] = _first_words(motion.get("mask", {}).get("target") or shot["keyframe"]["prompt"])
    return spec


# ---- drawing helpers -------------------------------------------------------

def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,") + "…"
    return lines


def _line(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], width: int = 5) -> None:
    """A white stroke with a dark outline, so marks read on any background."""
    draw.line(points, fill=INK, width=width + 4, joint="curve")
    draw.line(points, fill=MARK, width=width, joint="curve")


def _arrow(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], width: int = 5, head: int = 18) -> None:
    (x0, y0), (x1, y1) = points[-2], points[-1]
    angle = math.atan2(y1 - y0, x1 - x0)
    base = (x1 - head * 0.8 * math.cos(angle), y1 - head * 0.8 * math.sin(angle))
    _line(draw, [*points[:-1], base], width)
    tip = [(x1, y1)] + [(x1 - head * math.cos(angle + s * 0.5), y1 - head * math.sin(angle + s * 0.5)) for s in (1, -1)]
    draw.polygon(tip, fill=MARK, outline=INK, width=2)


def _dashed(draw: ImageDraw.ImageDraw, points: list[tuple[float, float]], dash: float = 16) -> None:
    """A dashed polyline: every other `dash` pixels of its length is drawn."""
    run, on, segment = 0.0, True, [points[0]]
    for (x0, y0), (x1, y1) in pairwise(points):
        length = math.hypot(x1 - x0, y1 - y0)
        t = 0.0
        while t < length:
            step = min(dash - run, length - t)
            t, run = t + step, run + step
            point = (x0 + (x1 - x0) * t / length, y0 + (y1 - y0) * t / length)
            if on:
                segment.append(point)
            if run >= dash:
                if on and len(segment) > 1:
                    _line(draw, segment, 4)
                on, run, segment = not on, 0.0, [point]
    if on and len(segment) > 1:
        _line(draw, segment, 4)


def _rect(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def _label(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, size: int, anchor: str = "mm") -> None:
    draw.text(xy, text, font=_font(size, True), fill=MARK, anchor=anchor,
              stroke_width=max(2, size // 8), stroke_fill=INK)


def _figure(draw: ImageDraw.ImageDraw, at: list[float], height: float, colour: str) -> tuple[float, ...]:
    """Head circle over a rounded body; returns the head-and-body box (x0, y0, x1, y1)."""
    h = height * H
    r = HEAD * h
    cx, cy = at[0] * W, at[1] * H
    body_w = 0.38 * h
    draw.rounded_rectangle((cx - body_w / 2, cy + r * 1.05, cx + body_w / 2, cy - r + h), radius=body_w * 0.3,
                           fill=colour, outline=INK, width=3)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=colour, outline=INK, width=3)
    return cx - body_w / 2, cy - r, cx + body_w / 2, cy - r + h


def _name(draw: ImageDraw.ImageDraw, box: tuple[float, ...], name: str) -> None:
    """The name under a small figure's feet, or across a big figure's visible body."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    size = int(min(max(h * 0.05, 17), 24))
    lines = _wrap(draw, name, _font(size, True), int(max(x1 - x0, 200)), 3)
    half = max(draw.textlength(t, font=_font(size, True)) for t in lines) / 2 + 8
    lx = min(max((x0 + x1) / 2, half), W - half)  # keep the name inside the frame
    if h < 0.4 * H:
        first_y = min(y1 + size * 0.9, H - FOOTER_H - size * 1.2 * len(lines))
    else:
        first_y = (y0 + 2 * HEAD * h + min(y1, H - FOOTER_H)) / 2 - size * 0.6 * (len(lines) - 1)
    for n, text in enumerate(lines):
        _label(draw, (lx, first_y + n * size * 1.2), text, size)


def _motion_marks(draw: ImageDraw.ImageDraw, marks: dict[str, Any], boxes: list[tuple[float, ...]]) -> None:
    mode = marks["mode"]
    top, bottom = HEADER_H + 40, H - FOOTER_H - 20
    subject = boxes[0] if boxes else (W * 0.3, H * 0.4, W * 0.7, H * 0.6)
    sx0, sy0, sx1, sy1 = subject
    mid_y = min(sy0 + (min(sy1, bottom) - sy0) * 0.3, bottom - 40)  # about shoulder height
    if mode == "full_i2v":
        start = min(sx1 + 12, W - 150)
        _arrow(draw, [(start, mid_y), (start + 120, mid_y)])
    elif mode == "flf_inbetween":
        start = min(sx1 + 12, W - 150)
        curve = [(start + 130 * t, mid_y - 110 * math.sin(math.pi * t) * 0.8) for t in (i / 12 for i in range(13))]
        _arrow(draw, curve)
    elif mode == "parallax":
        move = marks["move"]
        if move in ("push-in", "pull-out"):
            for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
                cx, cy = (40 if dx > 0 else W - 40), (top if dy > 0 else bottom)
                ends = [(cx, cy), (cx + 70 * dx, cy + 70 * dy)]
                _arrow(draw, ends if move == "push-in" else ends[::-1])
        elif move in ("slide-left", "slide-right"):
            ends = [(W * 0.25, top + 30), (W * 0.75, top + 30)]
            _arrow(draw, ends if move == "slide-right" else ends[::-1])
        else:
            _arrow(draw, [(W - 50, bottom - 40), (W - 50, top + 40)])
    elif mode == "still_kenburns":
        pan = marks["kenburns"]
        w, h = W * 0.72, (bottom - top) * 0.72
        cx, cy = W / 2, (top + bottom) / 2
        shift = {"pan-left": (-1, 0), "pan-right": (1, 0), "pan-up": (0, -1), "pan-down": (0, 1)}.get(pan, (0, 0))
        ex, ey = cx + shift[0] * (W - w) / 2.3, cy + shift[1] * (bottom - top - h) / 2.3
        _dashed(draw, _rect(ex - w / 2, ey - h / 2, ex + w / 2, ey + h / 2))
        if shift != (0, 0):
            ay = top + 20 if shift[1] == 0 else cy
            _arrow(draw, [(cx - shift[0] * 60, ay - shift[1] * 60), (cx + shift[0] * 90, ay + shift[1] * 90)])
        else:
            outer, inner = (30, top - 10), (ex - w / 2 + 10, ey - h / 2 + 10)
            _arrow(draw, [outer, inner] if pan == "zoom-in" else [inner, outer])
    elif mode in ("masked_i2v", "cinemagraph"):
        if marks["regions"]:
            r = marks["regions"][0]
            x0, y0, x1, y1 = r["x"] * W, r["y"] * H, (r["x"] + r["w"]) * W, (r["y"] + r["h"]) * H
        else:
            x0, y0, x1, y1 = sx0 - 20, sy0 - 20, sx1 + 20, min(sy0 + (sy1 - sy0) * 0.4, bottom)
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
        _dashed(draw, [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in (i * math.pi / 40 for i in range(81))])
        side = cx + rx + 22 if cx + rx + 70 < W else cx - rx - 58
        for n in range(3):
            wx, wy = side + n * 16, cy + 18
            _line(draw, [(wx + 4 * math.sin(i / 2), wy - i * 3) for i in range(12)], 3)
        if marks["target"]:
            _label(draw, (W / 2, max(cy - ry - 18, top + 10)), f"moves: {marks['target']}", 18)


def render_frame(sb: dict[str, Any], shot: dict[str, Any]) -> Image.Image:
    """The sketch frame for one shot; the same spec always gives the same pixels."""
    spec = frame_spec(sb, shot)
    sky, ground = _place_colours(spec["location"]["index"])
    img = Image.new("RGB", (W, H), sky)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, int(H * HORIZON), W, H), fill=ground)

    boxes = []
    if spec["size"] == "insert":
        s = W * 0.5
        x0, y0 = (W - s) / 2, H * 0.52 - s / 2
        draw.rounded_rectangle((x0, y0, x0 + s, y0 + s), radius=28, fill="#EEE6D3", outline=INK, width=4)
        lines = _wrap(draw, spec["object"], _font(22, True), int(s - 30), 5)
        for n, text in enumerate(lines):
            ty = y0 + s / 2 + (n - (len(lines) - 1) / 2) * 30
            draw.text((W / 2, ty), text, font=_font(22, True), fill=INK, anchor="mm")
        boxes.append((x0, y0, x0 + s, y0 + s))
    else:
        cast = spec["characters"]
        heights = [FIGURE_HEIGHT[spec["size"]]] * len(cast)
        order = list(range(len(cast)))
        if spec["size"] == "over-the-shoulder" and cast:  # first figure: big foreground shoulder, drawn last
            heights[0], order = 1.3, order[1:] + order[:1]
        drawn = {n: _figure(draw, cast[n]["at"], heights[n], PALETTE[cast[n]["colour"]]) for n in order}
        for n in order:
            _name(draw, drawn[n], cast[n]["name"])
        boxes = [drawn[n] for n in range(len(cast))]
    _motion_marks(draw, spec["motion"], boxes)

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    band = ImageDraw.Draw(overlay)
    band.rectangle((0, 0, W, HEADER_H), fill=(15, 15, 15, 205))
    band.rectangle((0, H - FOOTER_H, W, H), fill=(15, 15, 15, 255))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)
    marks = spec["motion"]
    detail = marks.get("move") or marks.get("kenburns")
    draw.text((16, HEADER_H / 2), marks["mode"] + (f" · {detail}" if detail else ""), font=_font(24, True),
              fill=MARK, anchor="lm")
    if marks["paid"]:
        draw.ellipse((W - 48, 8, W - 12, 44), fill="#FFC914", outline=INK, width=2)
        draw.text((W - 30, 26), "$", font=_font(24, True), fill=INK, anchor="mm")
    _label(draw, (16, HEADER_H + 14), spec["location"]["name"], 18, anchor="lt")
    draw.text((16, H - FOOTER_H + 16), f"{spec['id']}  ·  {spec['size']}  ·  {spec['duration_s']:g} s",
              font=_font(26, True), fill=MARK)
    for n, text in enumerate(_wrap(draw, spec["text"], _font(22), W - 32, 4)):
        draw.text((16, H - FOOTER_H + 60 + n * 30), text, font=_font(22), fill="#DDDDDD")
    return img


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _animatic(cache: StageCache, shots: list[dict[str, Any]], paths: dict[str, Path]) -> Path:
    spec = {"v": RENDER_VERSION, "fps": FPS, "frames": [[paths[s["id"]].name, s["duration_s"]] for s in shots]}
    key = key_for(spec)
    path = cache.hit("animatic", key, ".mp4")
    if path is None:
        path = cache.path("animatic", key, ".mp4")
        tmp = path.with_name(f"{path.stem}.part.mp4")
        inputs = [a for s in shots for a in ("-loop", "1", "-framerate", str(FPS), "-t", f"{s['duration_s']}",
                                             "-i", paths[s["id"]].name)]
        chain = "".join(f"[{n}:v]" for n in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0,format=yuv420p[v]"
        run_ffmpeg([*inputs, "-filter_complex", chain, "-map", "[v]", "-r", str(FPS), "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "23", "-movflags", "+faststart", tmp.name], cwd=cache.dir)
        tmp.replace(path)
    cache.record("animatic", key, path, spec)
    return path


def run(project: Project, *, only: set[str] | None = None, force: bool = False) -> dict[str, Any]:
    """Draw every out-of-date frame (they are free), then the contact sheet and animatic.
    `force` redraws cached frames too, limited to the shots in `only` when given."""
    sb = sbmod.load_valid(project)
    cache = StageCache(project, "sketch")
    counts = {"drawn": 0, "cached": 0}
    paths: dict[str, Path] = {}
    for shot in sb["shots"]:
        sid, spec = shot["id"], frame_spec(sb, shot)
        key = key_for(spec)
        path = cache.path(sid, key, ".png")
        if cache.hit(sid, key, ".png") and not (force and (only is None or sid in only)):
            counts["cached"] += 1
        else:
            write_atomic(path, _png(render_frame(sb, shot)))
            counts["drawn"] += 1
        cache.record(sid, key, path, spec)
        paths[sid] = path
    contact_sheet([(sid, p) for sid, p in paths.items()], project.out("sketch", "contact_sheet.jpg"), columns=6)
    animatic = project.out("sketch", "animatic.mp4")
    shutil.copyfile(_animatic(cache, sb["shots"], paths), animatic)
    seconds = float(sum(s["duration_s"] for s in sb["shots"]))
    print(f"  sketch: {counts['drawn']} frame(s) drawn, {counts['cached']} cached; animatic {seconds:.1f} s")
    return {"frames": paths, "animatic": animatic, "seconds": seconds}


def frames(project: Project, sb: dict[str, Any]) -> dict[str, Path | None]:
    """The cached frame matching each shot's current storyboard entry, or None if it needs drawing."""
    cache = StageCache(project, "sketch")
    return {s["id"]: cache.hit(s["id"], key_for(frame_spec(sb, s)), ".png") for s in sb["shots"]}
