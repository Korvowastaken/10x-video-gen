"""The layout guide: one plain shape frame per scene that FLUX.2 copies the composition from.

Internal to the keyframes stage. It is not a step, nobody edits it, and it calls
no model, so it is free. The frame holds only what composition needs, so the
image model has nothing else to copy:
  - a thin grey horizon line on white;
  - one thin black outline figure per character (head, torso, arms and legs as
    simple capsules), where they stand and as tall as the shot size makes them (a
    wide shot shows small figures, a close-up crops the body);
  - each figure turned the way it faces: people in a group turn toward each
    other, shown by a narrower side-on torso, a small nose point on the head, the
    near arm reaching forward and the legs in a half step. Someone alone faces
    the camera; the foreground figure of an over-the-shoulder shot faces the rest.
No text, colours, arrows, names or grey fills: the model draws them into the
picture. Shapes are filled white only so a nearer figure hides the one behind. Tried on real scenes, solid grey figures came back as an extra grey
person; outlines did not.
Figures spread across the frame by count and shot size. An insert shot, or a
scene with nobody in it, gets no guide.

The frame has the keyframe's shape (4:7) at half its size, so it costs few input
tiles. Outputs: outputs/sketch/<shot>_layout__<key>.png
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .cache import StageCache, key_for, write_atomic
from .config import Project

RENDER_VERSION = 3
W, H = 384, 672        # half of KEYFRAME_SIZE (768x1344)
HORIZON = 0.58
# Figure height (head to feet) as a fraction of frame height, by shot size.
FIGURE_HEIGHT = {"extreme-wide": 0.15, "wide": 0.28, "medium": 0.55, "medium-close-up": 0.75,
                 "close-up": 1.1, "extreme-close-up": 1.7, "over-the-shoulder": 0.5, "insert": 0.0}
SHOULDER_HEIGHT = 1.3  # the foreground figure of an over-the-shoulder shot
HEAD = 0.13            # head radius as a fraction of figure height
PAPER, HORIZON_INK, INK = "#FFFFFF", "#999999", "#222222"
LINE = 3


def figure_height(size: str) -> float:
    return FIGURE_HEIGHT[size]


def _positions(size: str, count: int) -> list[list[float]]:
    """Where each figure's head centre sits, as fractions of the frame."""
    h = FIGURE_HEIGHT[size]
    head_y = round(max(0.74 - h + HEAD * h, 0.32), 3)  # feet on the lower-middle, big heads near the top third
    if size == "over-the-shoulder":   # first figure is the foreground shoulder, others face it
        others = [[round(0.68 + 0.2 * i / max(count - 2, 1), 3), 0.42] for i in range(count - 1)]
        return [[0.06, 0.62]] + others
    if count == 1:
        return [[0.5, head_y]]
    return [[round(0.22 + 0.56 * i / (count - 1), 3), head_y] for i in range(count)]


def _facing(size: str, positions: list[list[float]]) -> list[str]:
    """Which way each figure faces: "front", "left" or "right" (as seen in the frame)."""
    if size == "over-the-shoulder":
        return ["right"] + ["left"] * (len(positions) - 1)
    if len(positions) == 1:
        return ["front"]
    return ["right" if x < 0.45 else "left" if x > 0.55 else "front" for x, _ in positions]


def layout_spec(shot: dict[str, Any]) -> dict[str, Any] | None:
    """Everything that changes the guide's pixels, and nothing else; None when there is no guide."""
    cast = [] if shot["size"] == "insert" else shot["characters"]
    if not cast:
        return None
    heights = [FIGURE_HEIGHT[shot["size"]]] * len(cast)
    if shot["size"] == "over-the-shoulder":
        heights[0] = SHOULDER_HEIGHT
    positions = _positions(shot["size"], len(cast))
    return {"v": RENDER_VERSION, "size": [W, H],
            "figures": [{"at": at, "height": h, "facing": f}
                        for at, h, f in zip(positions, heights, _facing(shot["size"], positions))]}


Point = tuple[float, float]


def _limb(draw: ImageDraw.ImageDraw, points: list[Point], width: float) -> None:
    """An outlined capsule along `points` (shoulder, elbow, hand or hip, knee, foot)."""
    for colour, w in ((INK, width + 2 * LINE), (PAPER, width)):
        draw.line(points, fill=colour, width=max(1, round(w)), joint="curve")
        for x, y in points:
            draw.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=colour)


def _figure(draw: ImageDraw.ImageDraw, at: list[float], height: float, facing: str) -> None:
    """Head, torso, arms and legs in outline, turned the way the figure faces."""
    h = height * H
    r = HEAD * h
    cx, cy = at[0] * W, at[1] * H
    top = cy - r
    neck, hip, feet = cy + r * 1.05, top + 0.58 * h, top + h
    arm_w, leg_w = 0.065 * h, 0.085 * h
    if facing == "front":
        tw = 0.34 * h
        for s in (-1, 1):
            _limb(draw, [(cx + s * tw * 0.22, hip - 0.03 * h), (cx + s * tw * 0.26, top + 0.79 * h),
                         (cx + s * tw * 0.3, feet - leg_w / 2)], leg_w)
            _limb(draw, [(cx + s * (tw / 2 - arm_w / 2), neck + 0.05 * h), (cx + s * (tw / 2 + 0.03 * h), top + 0.45 * h),
                         (cx + s * (tw / 2 + 0.05 * h), hip + 0.04 * h)], arm_w)
        draw.rounded_rectangle((cx - tw / 2, neck, cx + tw / 2, hip), radius=tw * 0.3, fill=PAPER,
                               outline=INK, width=LINE)
    else:
        d = 1 if facing == "right" else -1
        tw = 0.24 * h
        # far side first, so the torso and near limbs cover it
        _limb(draw, [(cx - d * 0.02 * h, hip - 0.03 * h), (cx - d * 0.07 * h, top + 0.79 * h),
                     (cx - d * 0.1 * h, feet - leg_w / 2)], leg_w)
        _limb(draw, [(cx - d * 0.03 * h, neck + 0.05 * h), (cx - d * 0.06 * h, top + 0.42 * h),
                     (cx - d * 0.03 * h, hip + 0.02 * h)], arm_w)
        _limb(draw, [(cx + d * 0.02 * h, hip - 0.03 * h), (cx + d * 0.08 * h, top + 0.79 * h),
                     (cx + d * 0.11 * h, feet - leg_w / 2)], leg_w)
        draw.rounded_rectangle((cx - tw / 2, neck, cx + tw / 2, hip), radius=tw * 0.3, fill=PAPER,
                               outline=INK, width=LINE)
        _limb(draw, [(cx + d * 0.02 * h, neck + 0.05 * h), (cx + d * 0.05 * h, top + 0.4 * h),
                     (cx + d * 0.17 * h, top + 0.37 * h)], arm_w)  # near arm bent, reaching forward
        nose = [(cx + d * r * 0.8, cy - 0.25 * r), (cx + d * r * 1.35, cy + 0.1 * r), (cx + d * r * 0.8, cy + 0.3 * r)]
        draw.polygon(nose, fill=PAPER, outline=INK, width=LINE)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=PAPER, outline=INK, width=LINE)


def render(spec: dict[str, Any]) -> Image.Image:
    """The guide for a layout spec; the same spec always gives the same pixels."""
    img = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(img)
    draw.line((0, int(H * HORIZON), W, int(H * HORIZON)), fill=HORIZON_INK, width=2)
    # The tallest figure is nearest the camera: draw it last so it covers the ones behind.
    for fig in sorted(spec["figures"], key=lambda f: f["height"]):
        _figure(draw, fig["at"], fig["height"], fig["facing"])
    return img


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def layout_file(project: Project, shot: dict[str, Any]) -> Path | None:
    """The guide for one shot, drawn now if it is not on disk yet; None when the shot has no guide."""
    spec = layout_spec(shot)
    if spec is None:
        return None
    cache, item, key = StageCache(project, "sketch"), f"{shot['id']}_layout", key_for(spec)
    path = cache.hit(item, key, ".png")
    if path is None:
        path = cache.path(item, key, ".png")
        write_atomic(path, _png(render(spec)))
    cache.record(item, key, path, spec)
    return path
