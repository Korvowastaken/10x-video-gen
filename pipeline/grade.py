"""One colour grade across scenes, so the film looks like one film.

Each keyframe is drawn on its own, so one scene comes out warmer, another
greener or darker. The film's look is the median of every still's mean and
spread in CIE Lab. Each scene gets a 3D LUT that moves its own Lab mean and
spread part of the way toward that look (a partial Reinhard colour transfer:
spread ratios clamped so a flat still is not blown up, then blended by
`strength`). The LUT is written as a 33x33x33 .cube file, which FFmpeg's
`lut3d` filter applies to every frame of the scene's segment.

`distance` compares two images by their Lab histograms (Bhattacharyya per
channel, averaged: 0 is the same colours, 1 nothing in common). `measure`
reports how far neighbouring scenes are apart before and after grading.
Everything here is deterministic: same stills in, same LUTs out.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

SIZE = 33                     # LUT points per axis
RATIO = (0.7, 1.4)            # clamp on target std / image std
STRENGTH = 0.6
SAMPLE_PX = 256               # stats and histograms on a copy this wide
BINS = 32
RANGES = ((0.0, 100.0), (-128.0, 128.0), (-128.0, 128.0))



def _rgb(image: Path | str | np.ndarray) -> np.ndarray:
    if isinstance(image, np.ndarray):
        return image
    bgr = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(image)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _lab(image: Path | str | np.ndarray) -> np.ndarray:
    """Float Lab (L 0..100, a/b about -128..127) of a downscaled copy."""
    rgb = _rgb(image)
    h, w = rgb.shape[:2]
    if w > SAMPLE_PX:
        rgb = cv2.resize(rgb, (SAMPLE_PX, max(1, round(h * SAMPLE_PX / w))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab).reshape(-1, 3)


def stats(image: Path | str | np.ndarray) -> dict[str, list[float]]:
    lab = _lab(image).astype(np.float64)
    return {"mean": [round(float(v), 4) for v in lab.mean(0)], "std": [round(float(v), 4) for v in lab.std(0)]}


def target(images: list) -> dict[str, list[float]]:
    """The film's look: per-channel median of the stills' stats, so one odd scene does not drag it."""
    all_stats = [stats(p) for p in images]
    return {k: [round(float(v), 4) for v in np.median([s[k] for s in all_stats], axis=0)] for k in ("mean", "std")}


def transfer(lab: np.ndarray, image_stats: dict, look: dict, strength: float = STRENGTH) -> np.ndarray:
    """Move Lab values part of the way from image_stats toward look."""
    m_s, s_s = np.array(image_stats["mean"]), np.array(image_stats["std"])
    m_t, s_t = np.array(look["mean"]), np.array(look["std"])
    ratio = np.clip(s_t / np.maximum(s_s, 1e-6), *RATIO)
    moved = (lab - m_s) * ratio + m_t
    out = lab + strength * (moved - lab)
    out[..., 0] = np.clip(out[..., 0], 0.0, 100.0)
    return out


def lut(image_stats: dict, look: dict, strength: float = STRENGTH, size: int = SIZE) -> np.ndarray:
    """A (size, size, size, 3) RGB->RGB table in 0..1, indexed [b, g, r] like a .cube file's row order."""
    axis = np.linspace(0.0, 1.0, size, dtype=np.float32)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    grid = np.stack([r, g, b], -1).reshape(1, -1, 3)
    lab = cv2.cvtColor(grid, cv2.COLOR_RGB2Lab).astype(np.float64)
    graded = transfer(lab, image_stats, look, strength).astype(np.float32)
    rgb = cv2.cvtColor(graded, cv2.COLOR_Lab2RGB)
    return np.clip(rgb, 0.0, 1.0).reshape(size, size, size, 3)


def cube_text(table: np.ndarray, title: str = "grade") -> str:
    size = table.shape[0]
    rows = [f'TITLE "{title}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0"]
    rows += [f"{r:.6f} {g:.6f} {b:.6f}" for r, g, b in table.reshape(-1, 3)]  # red changes fastest
    return "\n".join(rows) + "\n"


def write_cube(path: Path, table: np.ndarray, title: str = "grade") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cube_text(table, title), "ascii")
    return path


def apply(image: Path | str | np.ndarray, table: np.ndarray) -> np.ndarray:
    """The LUT applied to an RGB image with trilinear interpolation (what lut3d does, near enough)."""
    rgb = _rgb(image).astype(np.float32) / 255.0
    n = table.shape[0] - 1
    pos = rgb * n
    lo = np.clip(np.floor(pos).astype(np.int32), 0, n - 1)
    f = pos - lo
    r0, g0, b0 = lo[..., 0], lo[..., 1], lo[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    out = np.zeros_like(rgb)
    for db, wb in ((0, 1 - fb), (1, fb)):
        for dg, wg in ((0, 1 - fg), (1, fg)):
            for dr, wr in ((0, 1 - fr), (1, fr)):
                out += wb * wg * wr * table[b0 + db, g0 + dg, r0 + dr]
    return np.clip(np.round(out * 255.0), 0, 255).astype(np.uint8)


def _hists(image: Path | str | np.ndarray) -> list[np.ndarray]:
    lab = _lab(image)
    out = []
    for c, (lo, hi) in enumerate(RANGES):
        h, _ = np.histogram(lab[:, c], bins=BINS, range=(lo, hi))
        out.append(h.astype(np.float64) / max(h.sum(), 1))
    return out


def distance(a: Path | str | np.ndarray, b: Path | str | np.ndarray) -> float:
    """Mean per-channel Bhattacharyya distance of Lab histograms: 0 same colours, 1 none shared."""
    ds = []
    for p, q in zip(_hists(a), _hists(b)):
        gap = 1.0 - float(np.sum(np.sqrt(p * q)))
        ds.append(np.sqrt(gap) if gap > 1e-12 else 0.0)
    return round(float(np.mean(ds)), 6)


def neighbour_distances(images: list) -> list[float]:
    return [distance(a, b) for a, b in zip(images, images[1:])]


# ---------------------------------------------------------------- measurement

def _strip(rows: list[list[np.ndarray]], out: Path, height: int = 360) -> None:
    lines = []
    for row in rows:
        tiles = [cv2.resize(im, (round(im.shape[1] * height / im.shape[0]), height), interpolation=cv2.INTER_AREA)
                 for im in row]
        lines.append(np.concatenate(tiles, 1))
    width = max(line.shape[1] for line in lines)
    lines = [np.pad(line, ((0, 6), (0, width - line.shape[1]), (0, 0))) for line in lines]
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), cv2.cvtColor(np.concatenate(lines, 0), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])


def measure(project, strength: float | None = None, strip: Path | None = None) -> dict[str, Any]:
    """Neighbouring-scene colour distance and the spread of Lab means, before and after the grade,
    on the current keyframes in storyboard order. `strip` saves a before (top) / after (bottom) image."""
    from .cache import StageCache

    sb = json.loads(project.storyboard.read_text("utf-8"))
    edit = sb.get("edit", {})
    strength = edit.get("grade_strength", STRENGTH) if strength is None else strength
    cache = StageCache(project, "keyframes")
    ids = [s["id"] for s in sb["shots"] if cache.current(s["id"])]
    before = [_rgb(cache.current(sid)) for sid in ids]
    look = edit["grade"]["target"] if isinstance(edit.get("grade"), dict) else target(before)
    after = [apply(im, lut(stats(im), look, strength)) for im in before]

    def summary(images: list[np.ndarray]) -> dict[str, Any]:
        d = neighbour_distances(images)
        means = np.array([stats(im)["mean"] for im in images])
        return {"neighbour_mean": round(float(np.mean(d)), 4), "neighbour_max": round(float(np.max(d)), 4),
                "to_target_mean": round(float(np.mean([np.abs(np.array(stats(im)["mean"]) - look["mean"]).sum()
                                                       for im in images])), 2),
                "lab_mean_std": [round(float(v), 2) for v in means.std(0)]}

    if strip:
        _strip([before, after], strip)
    return {"shots": ids, "strength": strength, "target": look, "before": summary(before), "after": summary(after)}
