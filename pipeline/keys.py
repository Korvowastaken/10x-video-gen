"""API keys: several per service, kept in the git-ignored .env, switched when one runs out.

The first key of a service uses the plain names (GEMINI_API_KEY); more keys add
a number (GEMINI_API_KEY_2, GEMINI_API_KEY_3). A free tier's limit belongs to
the account or project behind the key, so a key from another Google project or
Cloudflare account brings a fresh daily limit.

When a provider answers "daily limit used up", it calls `switch()`: the next
saved key that has not run out this run becomes active (config.env reads it),
and the same request is tried again at once. Only when every key has run out
does the stage see QuotaExhausted, as before. runs.jsonl records which key made
each call (a short fingerprint, never the key), so limits.py can say per key
what is left today.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx

from . import config

SERVICES: dict[str, dict[str, Any]] = {
    "gemini": {
        "label": "Gemini", "fields": ["GEMINI_API_KEY"], "aliases": {"GEMINI_API_KEY": "GOOGLE_API_KEY"},
        "names": {"GEMINI_API_KEY": "API key"}, "paid": False,
        "url": "https://aistudio.google.com/apikey",
        "for": "Writes the scenes, revises them from feedback, records the voices and listens back.",
        "limit": "Free, with a small daily limit per Google Cloud project. A key from another project has its own limit.",
    },
    "cloudflare": {
        "label": "Cloudflare", "fields": ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"],
        "names": {"CLOUDFLARE_ACCOUNT_ID": "Account ID", "CLOUDFLARE_API_TOKEN": "API token"}, "paid": False,
        "url": "https://dash.cloudflare.com/profile/api-tokens",
        "for": "Draws the character sheets, places and every still.",
        "limit": "Free up to 10,000 neurons a day per account, about 40 stills. Another account has its own allowance.",
    },
    "wavespeed": {
        "label": "WaveSpeed", "fields": ["WAVESPEED_API_KEY"], "names": {"WAVESPEED_API_KEY": "API key"},
        "paid": True, "url": "https://wavespeed.ai/accesskey",
        "for": "Makes the paid clips (about $0.05 each) and the score candidates.",
        "limit": "Paid from the account's balance. When one account's credit runs out, the next key is used.",
    },
    "kaggle": {
        "label": "Kaggle", "fields": ["KAGGLE_API_TOKEN"], "names": {"KAGGLE_API_TOKEN": "API token"},
        "paid": False, "single": True,  # the kaggle library reads its token itself, so no switching
        "url": "https://www.kaggle.com/settings",
        "for": "Optional free GPU fallback for clips and music.",
        "limit": "Free, 6 GPU hours a week per account. One token: Kaggle reads it directly.",
    },
}

_LOCK = threading.Lock()
_ACTIVE: dict[str, int] = {}  # service -> slot in use; unset means the first saved slot
_OUT: dict[str, set[tuple[int, str]]] = {}  # service -> {(slot, scope)} that ran out this run


def _name(field: str, slot: int) -> str:
    return field if slot == 1 else f"{field}_{slot}"


def _value(service: str, field: str, slot: int) -> str:
    value = os.environ.get(_name(field, slot), "").strip()
    alias = SERVICES[service].get("aliases", {}).get(field)
    if not value and slot == 1 and alias:
        value = os.environ.get(alias, "").strip()
    return value


def slots(service: str) -> list[int]:
    """Slots that have every field filled, in order."""
    found = []
    for slot in range(1, 21):
        if all(_value(service, f, slot) for f in SERVICES[service]["fields"]):
            found.append(slot)
    return found


def fingerprint(service: str, slot: int) -> str:
    joined = "|".join(_value(service, f, slot) for f in SERVICES[service]["fields"])
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:10]


def active(service: str) -> int | None:
    saved = slots(service)
    if not saved:
        return None
    slot = _ACTIVE.get(service)
    return slot if slot in saved else saved[0]


def current(field: str) -> str | None:
    """The value config.env() should use for `field`: from the active slot of its service."""
    for service, spec in SERVICES.items():
        if field in spec["fields"]:
            slot = active(service)
            return _value(service, field, slot) if slot else None
    return None


def active_fingerprint(provider: str) -> str | None:
    slot = active(provider) if provider in SERVICES else None
    return fingerprint(provider, slot) if slot else None


def use(service: str, slot: int) -> None:
    with _LOCK:
        _ACTIVE[service] = slot


def switch(service: str, scope: str = "") -> int | None:
    """The active key just ran out (for `scope`, e.g. one Gemini model). Move to the next
    saved key that has not run out for it this run; return its slot, or None if none is left."""
    with _LOCK:
        saved = slots(service)
        now = active(service)
        if now is None:
            return None
        out = _OUT.setdefault(service, set())
        out.add((now, scope))
        order = saved[saved.index(now) + 1:] + saved[:saved.index(now)]
        for slot in order:
            if (slot, scope) not in out:
                _ACTIVE[service] = slot
                print(f"    keys: {SERVICES[service]['label']} key {saved.index(now) + 1} is out of its limit; "
                      f"switching to key {saved.index(slot) + 1}")
                return slot
        return None


def mask(value: str) -> str:
    return f"…{value[-4:]}" if len(value) > 4 else "…"


def describe() -> list[dict[str, Any]]:
    """Every service with its saved keys, masked. Never returns a key itself."""
    out = []
    for service, spec in SERVICES.items():
        saved = slots(service)
        now = active(service)
        out.append({
            "id": service, "label": spec["label"], "paid": spec["paid"], "url": spec["url"],
            "single": spec.get("single", False),
            "for": spec["for"], "limit": spec["limit"],
            "fields": [{"name": f, "label": spec["names"][f]} for f in spec["fields"]],
            "keys": [{"slot": slot, "n": i + 1, "active": slot == now, "fingerprint": fingerprint(service, slot),
                      "masked": {f: mask(_value(service, f, slot)) for f in spec["fields"]}}
                     for i, slot in enumerate(saved)],
        })
    return out


# ---------------------------------------------------------------- .env

def _env_path() -> Path:
    return config.ROOT / ".env"


def _write_env(updates: dict[str, str | None]) -> None:
    """Set (or remove, for None) variables in .env, keeping every other line as it was."""
    path = _env_path()
    lines = path.read_text("utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    out = []
    for line in lines:
        match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        name = match.group(1) if match else None
        if name in updates:
            seen.add(name)
            if updates[name] is not None:
                out.append(f"{name}={updates[name]}")
            continue
        out.append(line)
    for name, value in updates.items():
        if name not in seen and value is not None:
            out.append(f"{name}={value}")
    tmp = path.with_name(".env.tmp")
    tmp.write_text("\n".join(out) + "\n", "utf-8")
    tmp.replace(path)
    for name, value in updates.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def save(service: str, values: dict[str, str]) -> int:
    """Add a key to the next free slot. Returns the slot."""
    spec = SERVICES[service]
    values = {f: (values.get(f) or "").strip() for f in spec["fields"]}
    missing = [spec["names"][f] for f, v in values.items() if not v]
    if missing:
        raise ValueError(f"fill in {', '.join(missing)}")
    if any(re.search(r"\s", v) for v in values.values()):
        raise ValueError("a key has no spaces or line breaks; check what was pasted")
    for slot in slots(service):
        if all(_value(service, f, slot) == v for f, v in values.items()):
            raise ValueError("this key is already saved")
    if spec.get("single") and slots(service):
        raise ValueError(f"{spec['label']} takes one key; remove the saved one first")
    slot = next(s for s in range(1, 21) if s not in slots(service))
    with _LOCK:
        _write_env({_name(f, slot): v for f, v in values.items()})
    return slot


def remove(service: str, slot: int) -> None:
    with _LOCK:
        _write_env({_name(f, slot): None for f in SERVICES[service]["fields"]})
        if slot == 1:
            for alias in SERVICES[service].get("aliases", {}).values():
                _write_env({alias: None})
        if _ACTIVE.get(service) == slot:
            _ACTIVE.pop(service)


def check(service: str, values: dict[str, str]) -> str | None:
    """Ask the provider whether the key works, with a request that spends no quota.
    Returns a problem in words, or None. Services without a free check return None."""
    try:
        if service == "gemini":
            r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                          headers={"x-goog-api-key": values["GEMINI_API_KEY"]}, timeout=20)
            if r.status_code in (400, 401, 403):
                return "Google did not accept this key"
        elif service == "cloudflare":
            account = values["CLOUDFLARE_ACCOUNT_ID"]
            r = httpx.get(f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/models/search?per_page=1",
                          headers={"Authorization": f"Bearer {values['CLOUDFLARE_API_TOKEN']}"}, timeout=20)
            if r.status_code in (400, 401, 403, 404):
                return "Cloudflare did not accept this account ID and token (the token needs Workers AI access)"
    except httpx.HTTPError:
        return None  # offline: save it unchecked rather than refuse it
    return None


def new_run() -> None:
    """A studio job is a new run: keys and models that ran out before get another try,
    since a daily limit may have reset or a key been added since."""
    from . import retry
    with _LOCK:
        _OUT.clear()
    retry.EXHAUSTED.clear()
