"""FFmpeg and WAV helpers. Assembly is deterministic: same inputs, same film."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path


class MediaError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    """FFMPEG_BIN, else ffmpeg on PATH, else the binary that imageio-ffmpeg ships."""
    configured = os.environ.get("FFMPEG_BIN", "").strip()
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
    except ImportError as exc:
        raise MediaError("FFmpeg not found: install it or run `uv sync`") from exc
    return imageio_ffmpeg.get_ffmpeg_exe()


def run_ffmpeg(args: list[str], *, cwd: Path | None = None) -> str:
    """Run ffmpeg with -y; raise MediaError with the tail of stderr on failure."""
    cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-y", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=cwd)
    if proc.returncode != 0:
        shown = " ".join(a if len(a) < 80 else a[:77] + "..." for a in args[:14])
        raise MediaError(f"ffmpeg exited {proc.returncode}: {shown}\n{proc.stderr[-2500:]}")
    return proc.stderr


def probe_duration(path: Path) -> float:
    """Duration in seconds. Exact for WAV; parsed from `ffmpeg -i` otherwise."""
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / float(wav.getframerate())
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(path)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not match:
        raise MediaError(f"could not read duration of {path}")
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def probe_video(path: Path) -> dict:
    """Width, height and fps of the first video stream, from `ffmpeg -i`."""
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-i", str(path)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    match = re.search(r"Video:.*?(\d{2,5})x(\d{2,5}).*?(\d+(?:\.\d+)?) fps", proc.stderr)
    if not match:
        raise MediaError(f"no video stream in {path}")
    return {"width": int(match.group(1)), "height": int(match.group(2)), "fps": float(match.group(3)),
            "duration": probe_duration(path)}


def write_wav(path: Path, pcm: bytes, *, rate: int = 24000, channels: int = 1, width: int = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    with wave.open(str(tmp), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(pcm)
    tmp.replace(path)


def measure_loudness(path: Path) -> dict:
    """EBU R128 integrated loudness (LUFS), true peak and range via loudnorm."""
    # Not run_ffmpeg: its -loglevel error would hide loudnorm's JSON summary.
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-i", str(path), "-af",
                           "loudnorm=print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise MediaError(f"loudness pass failed for {path}: {proc.stderr[-800:]}")
    block = proc.stderr[proc.stderr.rfind("{"):proc.stderr.rfind("}") + 1]
    try:
        data = json.loads(block)
    except json.JSONDecodeError as exc:
        raise MediaError(f"could not measure loudness of {path}") from exc
    return {k: float(v) for k, v in data.items() if k.startswith("input_") or k == "target_offset"}
