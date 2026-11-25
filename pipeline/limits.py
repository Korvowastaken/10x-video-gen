"""How much of each free tier is left today, and when it comes back.

Free does not mean unlimited (COSTS.md): Gemini's free tier has a small daily
quota per model, and Cloudflare gives 10,000 neurons a day. Both are read back
from runs.jsonl, so the numbers are what this project actually used:

- Gemini is used up for a purpose (writing, voices) when every model in its
  fallback chain answered "quota used up" since the last reset, with no later
  success. Gemini's free quotas reset at midnight Pacific time.
- Cloudflare counts the neurons logged since 00:00 UTC, when it resets.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Project

CLOUDFLARE_NEURONS_A_DAY = 10_000
NEURONS_PER_STILL = 232  # measured: a keyframe with three references (COSTS.md)


def _pacific() -> timezone:
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Los_Angeles")  # type: ignore[return-value]
    except Exception:  # no tz database: Pacific standard time is close enough
        return timezone(timedelta(hours=-8))


def last_reset(now: datetime, tz: Any) -> datetime:
    """The most recent local midnight in `tz`, as a UTC time."""
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def next_reset(now: datetime, tz: Any) -> datetime:
    local = now.astimezone(tz)
    tomorrow = (local + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=tz).astimezone(timezone.utc)


def _rows(project: Project) -> list[dict[str, Any]]:
    if not project.runs.exists():
        return []
    rows = []
    for line in project.runs.read_text("utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _ts(row: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(row["ts"])
    except (KeyError, ValueError):
        return None


def _quota_error(row: dict[str, Any]) -> bool:
    return "QuotaExhausted" in (row.get("error") or "")


def gemini_used_up(rows: list[dict[str, Any]], models: list[str], since: datetime) -> bool:
    """True when every model in the chain ran out of quota since `since` and has not worked again."""
    if not models:
        return False
    for model in models:
        latest = None
        for row in rows:
            ts = _ts(row)
            if row.get("provider") != "gemini" or row.get("model") != model or ts is None or ts < since:
                continue
            if row.get("status") == "ok":
                latest = "ok"
            elif _quota_error(row):
                latest = "quota"
        if latest != "quota":
            return False
    return True


def cloudflare_used(rows: list[dict[str, Any]], since: datetime) -> float:
    used = 0.0
    for row in rows:
        ts = _ts(row)
        if row.get("provider") == "cloudflare" and ts is not None and ts >= since:
            used += float((row.get("cost") or {}).get("neurons") or 0)
            if _quota_error(row):
                used = max(used, CLOUDFLARE_NEURONS_A_DAY)
    return used


def _by_key(rows: list[dict[str, Any]], provider: str) -> dict[str | None, list[dict[str, Any]]]:
    """This provider's rows per saved key. Rows logged before keys were fingerprinted
    belong to the first key, which is the one .env held then."""
    from .keys import fingerprint, slots
    saved = [fingerprint(provider, s) for s in slots(provider)] or [None]
    out: dict[str | None, list[dict[str, Any]]] = {fp: [] for fp in saved}
    for row in rows:
        if row.get("provider") != provider:
            continue
        fp = row.get("key") if row.get("key") in out else (saved[0] if "key" not in row else None)
        if fp in out:
            out[fp].append(row)
    return out


def free_limits(project: Project, models: dict[str, Any], now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """{purpose: {label, used_up, resets_at, left, keys}} for the free services the studio runs.
    A purpose is used up only when every saved key for it is; `keys` says it per key fingerprint."""
    now = now or datetime.now(timezone.utc)
    rows = _rows(project)
    chain = lambda key: [models[key]] if isinstance(models.get(key), str) else list(models.get(key) or [])  # noqa: E731
    pacific = _pacific()
    gemini_since, gemini_back = last_reset(now, pacific), next_reset(now, pacific)
    cf_since, cf_back = last_reset(now, timezone.utc), next_reset(now, timezone.utc)
    gemini = _by_key(rows, "gemini")
    writing = {fp: gemini_used_up(r, chain("script"), gemini_since) for fp, r in gemini.items()}
    voices = {fp: gemini_used_up(r, chain("tts"), gemini_since) for fp, r in gemini.items()}
    pictures = {fp: int(max(0.0, CLOUDFLARE_NEURONS_A_DAY - cloudflare_used(r, cf_since)) // NEURONS_PER_STILL)
                for fp, r in _by_key(rows, "cloudflare").items()}
    stills = sum(pictures.values())
    return {
        "writing": {"label": "Gemini writing", "used_up": all(writing.values()), "resets_at": gemini_back.isoformat(),
                    "left": None, "keys": {fp: {"used_up": v} for fp, v in writing.items() if fp}},
        "voices": {"label": "Gemini voices", "used_up": all(voices.values()), "resets_at": gemini_back.isoformat(),
                   "left": None, "keys": {fp: {"used_up": v} for fp, v in voices.items() if fp}},
        "pictures": {"label": "Cloudflare pictures", "used_up": stills == 0, "resets_at": cf_back.isoformat(),
                     "left": stills, "keys": {fp: {"used_up": v == 0, "left": v} for fp, v in pictures.items() if fp}},
    }
