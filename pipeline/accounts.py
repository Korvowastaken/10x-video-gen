"""What each kind of work runs on, which key it starts with, and what is left there.

The studio shows this on every step for the purposes that step uses (writing,
voices, pictures, clips, music). Where there is a real choice of provider (clips
and music: WaveSpeed or Kaggle), the choice lives in storyboard.json like the
command line's; which key starts is kept in .env (keys.py). What is left:

- Gemini, Cloudflare: today's free limit per key, read from runs.jsonl (limits.py).
- WaveSpeed: the account balance in USD, asked from WaveSpeed's balance API.
- Kaggle: the weekly GPU hours left, from Kaggle's quota API.

The two network answers are cached for five minutes; a failure shows as unknown.
"""
from __future__ import annotations

import re
import time
from typing import Any

import httpx

from . import keys
from .engines import MUSIC_ENGINES, VIDEO_ENGINES

LABELS = {"writing": "Writing", "voices": "Voices", "pictures": "Pictures", "clips": "Clips", "music": "Music"}
DOING = {"writing": "Drafts the storyboard in English, writes the spoken lines, revises scenes from feedback",
         "voices": "Records each line and listens back to check it",
         "pictures": "Draws the sheets, places and stills",
         "clips": "Makes the moving clips for paid scenes",
         "music": "Makes the score candidates"}
PROVIDER_LABEL = {"gemini": "Gemini", "cloudflare": "Cloudflare Workers AI", "wavespeed": "WaveSpeed", "kaggle": "Kaggle",
                  "anthropic": "Claude", "azure": "Azure Speech", "groq": "Groq", "cerebras": "Cerebras",
                  "openrouter": "OpenRouter"}
CACHE_S = 300
_CACHE: dict[str, tuple[float, Any]] = {}


def _cached(name: str, fetch: Any) -> Any:
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    value = fetch()
    _CACHE[name] = (time.time(), value)
    return value


def forget() -> None:
    """Drop cached balances, e.g. after a key was added or a paid job ran."""
    _CACHE.clear()


def wavespeed_balance(key: str) -> float | None:
    """USD balance of the account behind `key`. WaveSpeed documents two paths; try both."""
    for path in ("/api/v3/balance", "/api/v3/account/balance"):
        try:
            r = httpx.get(f"https://api.wavespeed.ai{path}", headers={"Authorization": f"Bearer {key}"}, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json().get("data", r.json())
            balance = data.get("balance") if isinstance(data, dict) else None
            if isinstance(balance, (int, float, str)):
                return round(float(balance), 3)
        except (httpx.HTTPError, ValueError):
            continue
    return None


def kaggle_hours() -> dict[str, Any] | None:
    """Weekly GPU hours left and when they refresh, or None if Kaggle does not say."""
    try:
        from .providers.kaggle_runner import api, gpu_quota
        quota = gpu_quota(api())
    except Exception:  # not set up, offline, or the package changed: show unknown
        return None
    if "error" in quota:
        return None
    left = quota.get("remaining_hours")
    if left is None and "total_seconds" in quota and "used_seconds" in quota:
        left = (quota["total_seconds"] - quota["used_seconds"]) / 3600
    if left is None and "raw" in quota:  # e.g. {"timeUsed": "17.654.0s", "totalTimeAllowed": "21600s"}
        import json
        try:
            raw = json.loads(quota["raw"])
            seconds = lambda v: float(re.sub(r"\.(?=.*\.)", "", str(v)).rstrip("s"))  # noqa: E731
            left = max(0.0, seconds(raw["totalTimeAllowed"]) - seconds(raw["timeUsed"])) / 3600
        except (ValueError, KeyError):
            left = None
    return {"hours_left": round(float(left), 1) if left is not None else None, "refresh": quota.get("refresh") or None}


def engines(purpose: str) -> list[dict[str, Any]]:
    table = VIDEO_ENGINES if purpose == "clips" else MUSIC_ENGINES
    out = []
    for name, spec in table.items():
        provider = spec["provider"]
        if purpose == "clips":
            prices = spec.get("usd") or {}
            price = f"${prices[5]:.2f} per 5 s clip" if 5 in prices else "free GPU time"
            quality = "720p" if "720p" in name else "480p" if "480p" in name else "5B model"
            label = f"{PROVIDER_LABEL[provider]} · {quality}"
        else:
            price = f"${spec['usd_per_s'] * 80:.3f} per 80 s track" if spec.get("usd_per_s") else "free GPU time"
            label = PROVIDER_LABEL[provider]
        note = "Runs as a Kaggle batch from the command line; not tried end to end yet (FAILURES F12)." \
            if provider == "kaggle" else ""
        out.append({"id": name, "label": label, "provider": provider, "price": price, "paid": provider != "kaggle",
                    "note": note})
    return out


def _key_status(purpose: str, service: str, slot: int, limits: dict[str, Any]) -> dict[str, Any]:
    fp = keys.fingerprint(service, slot)
    if service == "gemini":
        k = (limits.get(purpose) or {}).get("keys", {}).get(fp, {})
        return {"used_up": bool(k.get("used_up")), "resets_at": limits.get(purpose, {}).get("resets_at"),
                }
    if service == "cloudflare":
        k = (limits.get("pictures") or {}).get("keys", {}).get(fp, {})
        return {"used_up": bool(k.get("used_up")), "resets_at": limits.get("pictures", {}).get("resets_at"),
                "left": k.get("left")}
    if service == "wavespeed":
        balance = _cached(f"ws:{fp}", lambda: wavespeed_balance(keys.value(service, "WAVESPEED_API_KEY", slot)))
        return {"used_up": balance is not None and balance < 0.05, "balance_usd": balance}
    if service == "kaggle":
        hours = _cached("kaggle", kaggle_hours)
        return {"used_up": bool(hours and hours.get("hours_left") is not None and hours["hours_left"] <= 0),
                "hours_left": hours.get("hours_left") if hours else None,
                "resets_at": hours.get("refresh") if hours else None}
    return {"used_up": False}


CHAINS = {"writing": ("script", "lines"), "voices": ("tts", "listen"), "pictures": ("image",)}


def _services(purpose: str, models: dict[str, Any]) -> list[str] | None:
    """The services a chained purpose runs on, in the order it tries them (None: not chained)."""
    from .catalog import provider_of
    from .config import DEFAULT_MODELS
    names = CHAINS.get(purpose)
    if not names:
        return None
    chain: list[str] = []
    for name in names:
        value = models.get(name) or DEFAULT_MODELS.get(name) or []
        chain += [value] if isinstance(value, str) else list(value)
    return [s for s in dict.fromkeys(provider_of(m) for m in chain) if s in keys.SERVICES]


def _first_service(purpose: str, models: dict[str, Any], default: str) -> str:
    """Writing, voices and pictures run down a chain of providers: show the first one with a saved key."""
    found = _services(purpose, models)
    if found is None:
        return default
    from . import paused
    return next((s for s in found if keys.slots(s) and not paused.is_paused(s)), found[0] if found else default)


def _chain(purpose: str, models: dict[str, Any], service: str) -> list[dict[str, Any]]:
    """Every service this work can run on, in the order it tries them, and whether each has a key."""
    order = _services(purpose, models) or [service]
    from . import paused
    return [{"service": s, "provider": PROVIDER_LABEL[s], "connected": bool(keys.slots(s)), "paused": paused.is_paused(s)}
            for s in order]


def overview(sb: dict[str, Any] | None, limits: dict[str, Any]) -> dict[str, Any]:
    """{purpose: {...}} for the studio's "Providers and keys" panel on each step."""
    models = (sb or {}).get("models", {})
    out: dict[str, Any] = {}
    for purpose, default_service in keys.PURPOSES.items():
        choices = engines(purpose) if purpose in ("clips", "music") else []
        engine = models.get("video" if purpose == "clips" else "music") if choices else None
        chosen = next((c for c in choices if c["id"] == engine), None)
        service = chosen["provider"] if chosen else _first_service(purpose, models, default_service)
        saved = keys.slots(service)
        starts = keys.active(service, purpose)
        out[purpose] = {
            "label": LABELS[purpose], "does": DOING[purpose], "service": service,
            "provider": PROVIDER_LABEL[service], "engine": engine, "engines": choices,
            "chain": _chain(purpose, models, service) if not chosen else [
                {"service": service, "provider": PROVIDER_LABEL[service], "connected": bool(saved)}],
            "single": keys.SERVICES[service].get("single", False),
            "chosen": keys.preferred(purpose), "starts": starts,
            "keys": [{"slot": s, "n": i + 1, "masked": keys.mask(keys.value(service, keys.SERVICES[service]["fields"][-1], s)),
                      **_key_status(purpose, service, s, limits)} for i, s in enumerate(saved)],
        }
    return out
