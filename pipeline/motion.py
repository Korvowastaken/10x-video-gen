"""Free local motion: frame interpolation, depth parallax and masked compositing.

Everything here runs on the laptop, costs nothing and gives the same output for
the same inputs (research/motion-on-a-budget.md, sections 1a, 2 and 3):

  retime()            RIFE v4.25 (rife-ncnn-vulkan) resamples a clip to 24 fps and,
                      when a shot needs it, slows it down; one pass does both.
  depth_map()         Depth Anything V2 Small (ONNX, int8) estimates depth once per still.
  render_parallax()   moves a virtual camera over the still with cv2.remap: near
                      pixels move more than far ones.
  masked_composite()  pastes only a masked region of a generated clip onto the
                      full-resolution still (aligned, colour-matched, feathered), as
                      a ping-pong cycle that loops seamlessly to any length.
Model files download on first use into .models/ (git-ignored).
"""
from __future__ import annotations

import math
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Iterator

import cv2
import numpy as np

from .config import ROOT
from .media import ffmpeg_bin, probe_video

MODELS = ROOT / ".models"
RIFE_MODEL = "rife-v4.25"
RIFE_URL = "https://raw.githubusercontent.com/TNTwise/rife-ncnn-vulkan/master/models/{model}/{file}"
DEPTH_FILE = "depth-anything-v2-small-int8.onnx"
DEPTH_URL = "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model_int8.onnx"
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


# ---------------------------------------------------------------- models and video IO

def _fetch(url: str, path: Path) -> Path:
    """Download once into .models/. Written to a .part file and checked against the
    server's Content-Length before it is renamed, so an interrupted download never
    leaves a truncated model behind (one did, FAILURES.md F15)."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {path.name} (first use)")
    tmp = path.with_name(f"{path.name}.{os.getpid()}.part")  # per process: two runs must not share one file
    with urllib.request.urlopen(url, timeout=120) as response, open(tmp, "wb") as fh:
        expected = int(response.headers.get("Content-Length") or 0)
        while chunk := response.read(1 << 20):
            fh.write(chunk)
    size = tmp.stat().st_size
    if expected and size != expected:
        tmp.unlink()
        raise RuntimeError(f"{path.name}: got {size} of {expected} bytes")
    if path.exists():  # another run finished first
        tmp.unlink()
    else:
        tmp.replace(path)
    return path


def rife_model_dir(model: str = RIFE_MODEL) -> Path:
    folder = MODELS / model
    for name in ("flownet.param", "flownet.bin"):
        _fetch(RIFE_URL.format(model=model, file=name), folder / name)
    return folder


def read_frames(path: Path) -> tuple[list[np.ndarray], float]:
    """All frames as RGB uint8 arrays, plus the source frame rate."""
    info = probe_video(path)
    w, h = info["width"], info["height"]
    raw = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    count = len(raw) // (w * h * 3)
    frames = [np.frombuffer(raw, np.uint8, w * h * 3, i * w * h * 3).reshape(h, w, 3) for i in range(count)]
    return frames, info["fps"]


def write_frames(frames: Iterable[np.ndarray], out: Path, fps: float, *, crf: int = 16) -> None:
    """Encode RGB frames to H.264 (yuv420p) through an FFmpeg pipe."""
    iterator = iter(frames)
    first = next(iterator)
    h, w = first.shape[:2]
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                             "-r", f"{fps}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
                             "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    assert proc.stdin is not None
    proc.stdin.write(np.ascontiguousarray(first).tobytes())
    for frame in iterator:
        proc.stdin.write(np.ascontiguousarray(frame).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg could not write {out}")


def load_still(path: Path, size: tuple[int, int]) -> np.ndarray:
    """The still as RGB, cover-cropped and resized to size (w, h)."""
    image = cv2.cvtColor(cv2.imread(str(path), cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    return cover(image, size)


def cover(image: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    w, h = size
    ih, iw = image.shape[:2]
    scale = max(w / iw, h / ih)
    resized = cv2.resize(image, (math.ceil(iw * scale), math.ceil(ih * scale)), interpolation=cv2.INTER_LANCZOS4)
    y = (resized.shape[0] - h) // 2
    x = (resized.shape[1] - w) // 2
    return resized[y:y + h, x:x + w]


# ---------------------------------------------------------------- RIFE

def blend(a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
    """A cross-fade between two neighbouring frames: softer than RIFE on fast motion, but always a picture."""
    return cv2.addWeighted(a, 1.0 - t, b, t, 0.0)


def looks_between(out: np.ndarray | None, a: np.ndarray, b: np.ndarray) -> bool:
    """Whether an in-between frame looks like its neighbours. RIFE on some GPUs (an Intel UHD 620) runs
    without an error and returns black frames, which strobe in the film; this catches them."""
    if out is None or out.shape != a.shape:
        return False
    lo, hi = sorted((float(a.mean()), float(b.mean())))
    return lo - 16 <= float(out.mean()) <= hi + 16 and (float(out.std()) > 1.0 or float(a.std()) <= 1.0)


class Blender:
    """In-between frames as cross-fades: what the film uses when RIFE cannot be trusted here."""
    device = "blend"

    def between(self, a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
        return blend(a, b, t)


def _test_pair(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Two frames with a known picture that moves a little: what a working RIFE must put between."""
    x = np.linspace(40, 220, width, dtype=np.float32)
    y = np.linspace(0, 30, height, dtype=np.float32)[:, None]
    a = np.clip(x[None, :] + y, 0, 255).astype(np.uint8)
    a = np.ascontiguousarray(np.repeat(a[:, :, None], 3, axis=2))
    return a, np.ascontiguousarray(np.roll(a, max(1, width // 40), axis=1))


class Interpolator:
    """RIFE on the Vulkan GPU, checked before it is trusted. Only the GPU: RIFE on the CPU takes
    over a second a frame here, so a GPU that fails the check means cross-fades instead (Blender)."""

    def __init__(self, width: int, height: int, model: str = RIFE_MODEL):
        from rife_ncnn_vulkan_python import Rife

        try:
            self.rife = Rife(gpuid=0, model=str(rife_model_dir(model)), scale=1, width=width, height=height,
                             num_threads=4)
        except Exception as exc:
            raise RuntimeError(f"RIFE could not start on the GPU ({exc})") from exc
        self.device = "vulkan:0"
        a, b = _test_pair(width, height)
        if not looks_between(self._rife(a, b, 0.5), a, b):
            raise RuntimeError("RIFE on this GPU returns black or broken frames")

    def _rife(self, a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
        out = self.rife.process_cv2(cv2.cvtColor(a, cv2.COLOR_RGB2BGR), cv2.cvtColor(b, cv2.COLOR_RGB2BGR), timestep=t)
        return cv2.cvtColor(out, cv2.COLOR_BGR2RGB)

    def between(self, a: np.ndarray, b: np.ndarray, t: float) -> np.ndarray:
        out = self._rife(a, b, t)
        return out if looks_between(out, a, b) else blend(a, b, t)  # a bad frame never reaches the film


_ENGINE: str | None = None


def interpolation_engine() -> str:
    """What makes in-between frames on this computer, checked once: "rife-v4.25@vulkan" or "blend".
    Part of every segment's cache key, so frames made one way are never reused as the other."""
    global _ENGINE
    if _ENGINE is None:
        try:
            Interpolator(256, 448)
            _ENGINE = f"{RIFE_MODEL}@vulkan"
        except Exception:
            _ENGINE = "blend"
    return _ENGINE


def retime_plan(n_src: int, src_fps: float, out_fps: float, stretch: float) -> list[tuple[int, float]]:
    """For each output frame, (source index, fraction toward the next source frame)."""
    length = n_src / src_fps * stretch
    n_out = max(1, round(length * out_fps))
    plan = []
    for k in range(n_out):
        pos = k / out_fps / stretch * src_fps
        i = min(int(pos), n_src - 1)
        frac = 0.0 if i >= n_src - 1 else pos - i
        plan.append((i, round(frac, 4)))
    return plan


def needs_rife(src_fps: float, out_fps: float, stretch: float) -> bool:
    """Whether RIFE earns its time. Slowing a clip down, or raising its frame rate, needs new frames
    in between. Lowering it (30 fps clips into a 24 fps film) only drops frames, which barely shows,
    and RIFE there cost about a minute per clip."""
    return stretch > 1.02 or src_fps < out_fps - 0.5


def retime(frames: list[np.ndarray], src_fps: float, *, out_fps: float = 24, stretch: float = 1.0,
           interpolator: Interpolator | None = None) -> Iterator[np.ndarray]:
    """Resample to out_fps and slow down by `stretch`, synthesising in-between frames with RIFE.

    Without an interpolator it falls back to the nearest frame (repeats), which is
    what the first assembly did and what judders on pans (research 3c).
    """
    for i, frac in retime_plan(len(frames), src_fps, out_fps, stretch):
        if frac < 0.02 or interpolator is None:
            yield frames[i if frac < 0.5 or interpolator is not None else min(i + 1, len(frames) - 1)]
        elif frac > 0.98:
            yield frames[i + 1]
        else:
            yield interpolator.between(frames[i], frames[i + 1], frac)


# ---------------------------------------------------------------- depth and parallax

def depth_map(image_path: Path, size: tuple[int, int]) -> np.ndarray:
    """Relative depth in [0, 1] at size (w, h); 1 is nearest. One ONNX run on the CPU."""
    import onnxruntime as ort

    model = _fetch(DEPTH_URL, MODELS / DEPTH_FILE)
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    rgb = load_still(image_path, size)
    h, w = rgb.shape[:2]
    short = 518
    scale = short / min(w, h)
    tw, th = (round(w * scale / 14) * 14, round(h * scale / 14) * 14)
    x = cv2.resize(rgb, (tw, th), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
    x = ((x - IMAGENET_MEAN) / IMAGENET_STD).transpose(2, 0, 1)[None]
    name = session.get_inputs()[0].name
    depth = session.run(None, {name: x.astype(np.float32)})[0].squeeze()
    depth = cv2.resize(depth.astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
    depth = (depth - depth.min()) / max(1e-6, float(depth.max() - depth.min()))
    # Grow near regions a little and soften edges, so silhouettes move as one piece (research 2).
    depth = cv2.dilate(depth, np.ones((9, 9), np.uint8))
    return cv2.GaussianBlur(depth, (0, 0), sigmaX=max(2.0, w / 200))


def save_depth(depth: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), (np.clip(depth, 0, 1) * 65535).astype(np.uint16))


def load_depth(path: Path, size: tuple[int, int]) -> np.ndarray:
    depth = cv2.imread(str(path), cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0
    return cv2.resize(depth, size, interpolation=cv2.INTER_LINEAR)


def _ease(p: float) -> float:
    return p * p * (3 - 2 * p)


def parallax_frames(still: np.ndarray, depth: np.ndarray, *, frames: int, move: str = "push-in",
                    amount: float = 0.03) -> Iterator[np.ndarray]:
    """A small dolly over the still. amount is the largest shift as a share of the frame
    (keep it at 2-4%; bigger moves stretch edges and reveal hidden background)."""
    h, w = still.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2, (h - 1) / 2
    near = depth.astype(np.float32)
    base = 1.0 + amount  # a little zoom so moving pixels never pull in the frame edge
    for k in range(frames):
        p = _ease(k / max(1, frames - 1))
        if move in ("push-in", "pull-out"):
            q = p if move == "push-in" else 1 - p
            scale = base + amount * 2.2 * q * (0.25 + near)
            map_x = cx + (xs - cx) / scale
            map_y = cy + (ys - cy) / scale
        else:
            shift = amount * (p - 0.5) * 2 * (near - 0.35)
            map_x = cx + (xs - cx) / base
            map_y = cy + (ys - cy) / base
            if move == "slide-left":
                map_x = map_x + shift * w
            elif move == "slide-right":
                map_x = map_x - shift * w
            elif move == "rise":
                map_y = map_y + shift * h
            else:
                raise ValueError(f"unknown parallax move '{move}'")
        yield cv2.remap(still, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def render_parallax(image_path: Path, depth_path: Path, out: Path, *, duration: float, fps: int,
                    size: tuple[int, int], move: str, amount: float) -> None:
    still = load_still(image_path, size)
    depth = load_depth(depth_path, size)
    write_frames(parallax_frames(still, depth, frames=max(1, round(duration * fps)), move=move, amount=amount),
                 out, fps, crf=18)


# ---------------------------------------------------------------- masked composite

def mask_image(regions: list[dict[str, Any]], size: tuple[int, int], feather: float) -> np.ndarray:
    """Soft alpha in [0, 1] from normalised shapes {shape, x, y, w, h} (x, y = top-left)."""
    w, h = size
    alpha = np.zeros((h, w), np.float32)
    for region in regions:
        x0, y0 = region["x"] * w, region["y"] * h
        rw, rh = region["w"] * w, region["h"] * h
        if region.get("shape", "ellipse") == "rect":
            cv2.rectangle(alpha, (int(x0), int(y0)), (int(x0 + rw), int(y0 + rh)), 1.0, thickness=-1)
        else:
            cv2.ellipse(alpha, (int(x0 + rw / 2), int(y0 + rh / 2)), (max(1, int(rw / 2)), max(1, int(rh / 2))),
                        0, 0, 360, 1.0, thickness=-1)
    sigma = max(1.0, feather * h)
    return cv2.GaussianBlur(alpha, (0, 0), sigmaX=sigma)


def _align(frame: np.ndarray, reference_gray: np.ndarray) -> np.ndarray:
    """Undo a small camera drift: translation-only ECC on a downscaled copy."""
    small = 320 / reference_gray.shape[1]
    ref = cv2.resize(reference_gray, None, fx=small, fy=small)
    cur = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY), None, fx=small, fy=small)
    warp = np.eye(2, 3, dtype=np.float32)
    try:
        _, warp = cv2.findTransformECC(ref.astype(np.float32), cur.astype(np.float32), warp, cv2.MOTION_TRANSLATION,
                                       (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4), None, 5)
    except cv2.error:
        return frame
    warp[:, 2] /= small
    h, w = frame.shape[:2]
    return cv2.warpAffine(frame, warp, (w, h), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def _match_colour(frame: np.ndarray, still: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Match mean and spread per channel inside the mask, so the region sits in the still."""
    weight = alpha > 0.5
    if weight.sum() < 50:
        return frame
    out = frame.astype(np.float32)
    for c in range(3):
        src, ref = out[..., c][weight], still[..., c][weight].astype(np.float32)
        out[..., c] = (out[..., c] - src.mean()) * (ref.std() / max(1.0, src.std())) + ref.mean()
    return np.clip(out, 0, 255).astype(np.uint8)


def masked_composite(still_path: Path, clip_path: Path, out: Path, *, regions: list[dict[str, Any]],
                     feather: float = 0.012, align: bool = True, size: tuple[int, int] | None = None,
                     loop: str = "pingpong") -> dict[str, Any]:
    """Only the masked region moves. Writes one loop cycle at the clip's frame rate."""
    frames, fps = read_frames(clip_path)
    if size is None:
        sh, sw = cv2.imread(str(still_path)).shape[:2]
        size = (sw, sh)
    still = load_still(still_path, size)
    alpha = mask_image(regions, size, feather)[..., None]
    reference_gray = cv2.cvtColor(still, cv2.COLOR_RGB2GRAY)
    composed = []
    for frame in frames:
        frame = cover(frame, size)
        if align:
            frame = _align(frame, reference_gray)
        frame = _match_colour(frame, still, alpha[..., 0])
        composed.append((still * (1 - alpha) + frame * alpha).astype(np.uint8))
    cycle = composed + composed[-2:0:-1] if loop == "pingpong" and len(composed) > 2 else composed
    write_frames(cycle, out, fps, crf=16)
    return {"frames": len(cycle), "fps": fps, "loop": loop, "mask_area": round(float(alpha.mean()), 3)}
