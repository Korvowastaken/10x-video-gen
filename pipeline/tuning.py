"""Free voice tuning: speed, pitch and age, applied to a saved take with FFmpeg.

The TTS voice (a character's `voice.name`) decides who is speaking, gender
included. Tuning only shapes how that voice sounds in a line, so it lives in
the processed narration stage: changing it re-renders from the raw take and
never calls a TTS model.

A character's `voice.tune` is the default for every line they speak; a line's
own `tune` overrides it field by field. Neutral values are dropped, so an
untuned line keeps exactly the cache key it had before tuning existed.

Only stock FFmpeg filters are used (asetrate, aresample, atempo, EQ, vibrato),
so the same film comes out of any FFmpeg build, with or without rubberband.
"""
from __future__ import annotations

from typing import Any

TUNE_VERSION = 1            # bump when the filters below change: re-renders tuned lines only

# field: (lowest, highest, neutral, decimals)
RANGES: dict[str, tuple[float, float, float, int]] = {
    "speed": (0.75, 1.35, 1.0, 2),   # x tempo; pitch stays put
    "pitch": (-4.0, 4.0, 0.0, 1),    # semitones; length stays put
    "age": (-1.0, 1.0, 0.0, 2),      # -1 younger, brighter .. +1 older, darker with a slight tremor
}


def clamp(tune: dict[str, Any] | None) -> dict[str, float]:
    """Known fields only, each clamped to its range and rounded. Neutral values stay."""
    out: dict[str, float] = {}
    for field, (low, high, _, places) in RANGES.items():
        value = (tune or {}).get(field)
        if value is not None:
            out[field] = round(min(high, max(low, float(value))), places)
    return out


def normalise(tune: dict[str, Any] | None) -> dict[str, float]:
    """clamp(), then drop neutral fields. {} means "sounds as recorded"."""
    return {k: v for k, v in clamp(tune).items() if v != RANGES[k][2]}


def resolve(character: dict[str, Any], line: dict[str, Any]) -> dict[str, float]:
    """The tuning a line is rendered with: the character's default, then the line's own fields."""
    merged = {**clamp(character.get("voice", {}).get("tune")), **clamp(line.get("tune"))}
    return normalise(merged)


def _tempo_steps(factor: float) -> list[str]:
    """atempo takes 0.5..2 per instance on older FFmpeg builds; chain it outside that."""
    steps: list[str] = []
    while factor < 0.5:
        steps.append("atempo=0.5")
        factor /= 0.5
    while factor > 2.0:
        steps.append("atempo=2.0")
        factor /= 2.0
    if abs(factor - 1.0) > 1e-4:
        steps.append(f"atempo={factor:.5f}")
    return steps


def _age_filters(age: float) -> list[str]:
    """Older: less air and chest, a little tremor. Younger: thinner low end, brighter presence."""
    a = abs(age)
    if age > 0:
        return [f"highshelf=f=3200:g={-6 * a:.2f}", f"lowshelf=f=160:g={-2.5 * a:.2f}",
                f"equalizer=f=900:t=o:w=1.2:g={1.5 * a:.2f}", f"vibrato=f=5.5:d={0.06 * a:.3f}"]
    return [f"lowshelf=f=220:g={-6 * a:.2f}", f"equalizer=f=2800:t=o:w=1.0:g={3 * a:.2f}",
            f"highshelf=f=6000:g={2.5 * a:.2f}"]


def filters(tune: dict[str, Any] | None, rate: int) -> list[str]:
    """FFmpeg audio filters for a tuning, for input at `rate` Hz. [] for an untuned line."""
    tune = normalise(tune)
    if not tune:
        return []
    chain: list[str] = []
    speed = tune.get("speed", 1.0)
    ratio = 2 ** (tune.get("pitch", 0.0) / 12)
    if ratio != 1.0:
        # Play faster to raise the pitch, resample back, then undo the length change.
        chain += [f"asetrate={round(rate * ratio)}", f"aresample={rate}"]
        chain += _tempo_steps(speed / ratio)
    else:
        chain += _tempo_steps(speed)
    if "age" in tune:
        chain += _age_filters(tune["age"])
    return chain


def describe(tune: dict[str, Any] | None) -> str:
    """Short plain words for logs: '0.9x, -1.5 st, older 0.4'."""
    tune = normalise(tune)
    parts = []
    if "speed" in tune:
        parts.append(f"{tune['speed']:g}x")
    if "pitch" in tune:
        parts.append(f"{tune['pitch']:+g} st")
    if "age" in tune:
        parts.append(f"{'older' if tune['age'] > 0 else 'younger'} {abs(tune['age']):g}")
    return ", ".join(parts) or "as recorded"
