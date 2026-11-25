"""Which models can do each task, and which one each task starts with.

Every step in the studio shows a model picker for each task it runs. A task is
one entry of the storyboard's `models` block:

  script   the storyboard, in English          lines   the spoken lines
  tts      recording each line                 listen  listening back to check a take
  image    sheets, places and stills           video   paid clips (an engine)
  music    the score (an engine)
  revise   script and scene revisions from feedback    mask    finding what moves in a masked scene

Choosing a model puts it first in that task's chain; the rest stay behind it
as fallbacks, so a model that runs out still hands over. The choice is saved
in storyboard.json and in models.json next to it, so a redraft of the script
(which writes a fresh storyboard) keeps it.

The options come from the services that have a saved key. Services that can
list their own models (Claude, Gemini, Groq, Cerebras, OpenRouter) are asked,
cached for ten minutes; if asking fails, a short known list stands in.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from . import keys, paused
from .config import DEFAULT_MODELS, Project
from .engines import MUSIC_ENGINES, VIDEO_ENGINES

TASKS: dict[str, dict[str, str]] = {
    "script": {"label": "Storyboard", "purpose": "writing", "kind": "text",
               "does": "Writes the whole storyboard in English, lines included"},
    "lines": {"label": "Lines", "purpose": "writing", "kind": "text",
              "does": "Writes the spoken lines in the film's language"},
    "tts": {"label": "Voices", "purpose": "voices", "kind": "tts",
            "does": "Records each line. A new model records every line again"},
    "listen": {"label": "Listening", "purpose": "voices", "kind": "listen",
               "does": "Listens back to each take to check it"},
    "image": {"label": "Pictures", "purpose": "pictures", "kind": "image",
              "does": "Draws the sheets, places and stills. Pictures from another model show as out of date"},
    "video": {"label": "Clips", "purpose": "clips", "kind": "video",
              "does": "Makes the moving clips for paid scenes"},
    "music": {"label": "Music", "purpose": "music", "kind": "music",
              "does": "Makes the score candidates"},
    "revise": {"label": "Revisions", "purpose": "writing", "kind": "text",
               "does": "Rewrites the script or a scene from your feedback, spoken lines included"},
    "mask": {"label": "Moving part", "purpose": "writing", "kind": "vision",
             "does": "Looks at the still of a masked scene and finds the part that moves"},
}
# Tasks a storyboard may leave out: until one is chosen, it follows the writing models (derived()).
OPTIONAL = {"revise", "mask"}

# The tasks each studio step's line shows (Story and Sketch call no model). Revisions have their
# picker beside the revise buttons instead, where the feedback is written.
STEP_TASKS: dict[str, list[str]] = {
    "script": ["script", "lines"],
    "references": ["image"],
    "scenes": ["image", "tts", "listen", "video", "mask"],
    "film": ["tts", "video", "music"],
}

SERVICE_LABEL = {"gemini": "Gemini", "cloudflare": "Cloudflare", "wavespeed": "WaveSpeed", "kaggle": "Kaggle",
                 "anthropic": "Claude", "azure": "Azure Speech", "groq": "Groq", "cerebras": "Cerebras",
                 "openrouter": "OpenRouter"}

# Known models, used when a service can't be asked (offline, or it has no list API).
KNOWN: dict[str, list[str]] = {
    "anthropic": ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
    "gemini_text": ["gemini-3.5-flash", "gemini-3.7-flash", "gemini-3.8-flash"],
    "gemini_tts": ["gemini-3.8-flash-tts", "gemini-3.8-flash-lite-tts"],
    "gemini_listen": ["gemini-3.5-transcribe", "gemini-3.5-flash"],
}
IMAGE_MODELS = {
    "@cf/black-forest-labs/flux-2-klein-4b": ("FLUX.2 klein 4B", "Keeps faces from the sheets"),
    "@cf/black-forest-labs/flux-2-klein-9b": ("FLUX.2 klein 9B", "Keeps faces from the sheets; sharper, costs more neurons"),
    "@cf/black-forest-labs/flux-1-schnell": ("FLUX.1 schnell", "Takes no sheets, so faces can drift between scenes"),
}
CACHE_S = 600
_CACHE: dict[str, tuple[float, list[str]]] = {}
PICKS = "models.json"


# ---------------------------------------------------------------- what runs now

def _picks(project: Project) -> dict[str, Any]:
    path = project.root / PICKS
    try:
        data = json.loads(path.read_text("utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def chain(project: Project, task: str, sb: dict[str, Any] | None = None) -> list[str] | str:
    """What a task runs, in order. The storyboard's own block wins; models.json covers the
    time before there is a storyboard (and carries choices across a redraft)."""
    from_sb = ((sb or {}).get("models") or {}).get(task)
    if from_sb:
        return from_sb
    return _picks(project).get(task) or DEFAULT_MODELS.get(task) or derived(project, task, sb)


def _list(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


# Lighter Gemini models that can read a picture; busy less often than Flash (FAILURES F16).
VISION_FALLBACKS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]


def derived(project: Project, task: str, sb: dict[str, Any] | None) -> list[str]:
    """The chain of a task nobody has chosen a model for yet."""
    from .providers.route import provider_of as route_provider
    script = _list(chain(project, "script", sb))
    if task == "revise":  # a revision rewrites spoken lines too, so the lines writer comes first
        return list(dict.fromkeys(_list(chain(project, "lines", sb)) + script))
    if task == "mask":  # any vision model; Gemini first, since it is trained to find boxes
        gemini = [m for m in script if route_provider(m) == "gemini"]
        return list(dict.fromkeys(gemini + VISION_FALLBACKS + script))
    raise KeyError(task)


def models_block(project: Project, sb: dict[str, Any] | None = None) -> dict[str, Any]:
    """The full models block a new storyboard gets: choices made so far, else the defaults.
    Revisions and mask finding are written only once chosen, so they keep following the writers."""
    picks = _picks(project)
    from_sb = (sb or {}).get("models") or {}
    return {task: chain(project, task, sb) for task in TASKS
            if task not in OPTIONAL or task in picks or task in from_sb}


def choose(project: Project, task: str, model: str, sb: dict[str, Any] | None) -> list[str] | str:
    """Put `model` first for `task`. Returns the new value; the caller saves the storyboard."""
    if task in ("video", "music"):
        value: list[str] | str = model
    else:
        now = chain(project, task, sb)
        rest = [m for m in ([now] if isinstance(now, str) else now) if m != model]
        value = [model, *rest]
    picks = _picks(project)
    picks[task] = value
    (project.root / PICKS).write_text(json.dumps(picks, indent=2) + "\n", "utf-8")
    if sb is not None:
        sb.setdefault("models", {})[task] = value
    return value


# ---------------------------------------------------------------- what could run

def provider_of(model: str) -> str:
    if model.startswith("@cf/"):
        return "cloudflare"
    if model in VIDEO_ENGINES:
        return VIDEO_ENGINES[model]["provider"]
    if model in MUSIC_ENGINES:
        return MUSIC_ENGINES[model]["provider"]
    from .providers.route import provider_of as route_provider
    return route_provider(model)


def _cached(name: str, fetch: Any) -> list[str]:
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < CACHE_S:
        return hit[1]
    try:
        value = fetch()
    except Exception:  # offline, a rejected key, or the API changed: use the known list
        value = []
    _CACHE[name] = (time.time(), value)
    return value


def forget() -> None:
    _CACHE.clear()


def _key(service: str, field: str) -> str:
    slot = keys.active(service) or (keys.slots(service) or [1])[0]
    return keys.value(service, field, slot)


def _gemini_models() -> list[dict[str, Any]]:
    def fetch() -> list[Any]:
        r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models",
                      params={"pageSize": 1000}, headers={"x-goog-api-key": _key("gemini", "GEMINI_API_KEY")},
                      timeout=15)
        r.raise_for_status()
        return [m for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
    raw = _CACHE.get("gemini:raw")
    if not raw or time.time() - raw[0] >= CACHE_S:
        try:
            raw = (time.time(), fetch())
        except Exception:
            raw = (time.time(), [])
        _CACHE["gemini:raw"] = raw
    return raw[1]


def _gemini(kind: str) -> list[str]:
    found = [m["name"].removeprefix("models/") for m in _gemini_models()]
    # Gemini 2.x retires on 2026-12-01 (config.py); "-latest" aliases repeat a listed model.
    found = [m for m in found if m.startswith("gemini-") and not m.startswith("gemini-2.")
             and not any(s in m for s in ("preview", "exp", "latest"))]
    if kind == "tts":
        live = [m for m in found if "tts" in m]
    else:
        skip = ("tts", "image", "banana", "embedding", "live", "audio", "robotics", "computer-use")
        live = [m for m in found if not any(s in m for s in skip) and "transcribe" not in m]
        if kind == "listen":
            live = [m for m in found if "transcribe" in m] + live
        live = [m for m in live if not re.search(r"-\d{3}$", m)]  # pinned snapshots repeat their family
    return list(dict.fromkeys(live or KNOWN[f"gemini_{kind}"]))


def _anthropic() -> list[str]:
    def fetch() -> list[str]:
        import anthropic
        client = anthropic.Anthropic(api_key=_key("anthropic", "ANTHROPIC_API_KEY"), max_retries=0, timeout=15)
        return [m.id for m in client.models.list(limit=100)]
    live = [m for m in _cached("anthropic", fetch) if m.startswith("claude-") and not re.search(r"-\d{8}$", m)]
    return list(dict.fromkeys([*KNOWN["anthropic"], *live]))


def _hosted(service: str) -> list[str]:
    from .providers.openai_compat import PROVIDERS

    def fetch() -> list[str]:
        spec = PROVIDERS[service]
        r = httpx.get(f"{spec['base']}/models", headers={"Authorization": f"Bearer {_key(service, spec['key'])}"},
                      timeout=15)
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", []) if m.get("id")]
    skip = ("whisper", "guard", "tts", "orpheus", "playai", "embed", "vision-only", "compound")
    ids = [m for m in _cached(service, fetch) if not any(s in m.lower() for s in skip)]
    if service == "openrouter":
        ids = [m for m in ids if m.endswith(":free")]  # the paid catalogue runs to hundreds
    return [f"{service}/{m}" for m in sorted(ids)]


def pretty(model: str) -> str:
    """'claude-haiku-5-5' -> 'Claude Haiku 5.5'; 'gemini-3.5-flash-tts' -> 'Gemini 3.5 Flash TTS'."""
    if model in IMAGE_MODELS:
        return IMAGE_MODELS[model][0]
    if model == "azure-neural":
        return "Azure neural voices"
    if model == "azure-stt":
        return "Azure speech-to-text"
    if "/" in model:
        return model.split("/", 1)[1].removesuffix(":free")
    words = model.split("-")
    if words[0] == "claude" and len(words) >= 4 and words[-1].isdigit() and words[-2].isdigit():
        words = [*words[:-2], f"{words[-2]}.{words[-1]}"]
    caps = {"tts": "TTS", "stt": "STT"}
    return " ".join(caps.get(w, w[:1].upper() + w[1:]) for w in words)


def _price(model: str, service: str) -> tuple[str, bool]:
    if service == "anthropic":
        from .providers.anthropic_api import USD_PER_M
        rate = USD_PER_M.get(model)
        return (f"${rate[0]:g} / ${rate[1]:g} per M tokens" if rate else "Paid per token"), True
    if service == "azure":
        return "Free each month", False
    if service == "cloudflare":
        return "Free daily neurons", False
    return "Free tier", False


def _option(model: str, task: str) -> dict[str, Any]:
    service = provider_of(model)
    if task in ("video", "music"):
        from .accounts import engines
        spec = next(e for e in engines("clips" if task == "video" else "music") if e["id"] == model)
        label, price, paid, note = spec["label"], spec["price"], spec["paid"], spec["note"]
    else:
        label, (price, paid) = pretty(model), _price(model, service)
        note = IMAGE_MODELS[model][1] if model in IMAGE_MODELS else ""
    connected = bool(keys.slots(service)) if service in keys.SERVICES else True
    return {"id": model, "label": label, "service": service, "provider": SERVICE_LABEL.get(service, service),
            "connected": connected, "paused": paused.is_paused(service), "price": price, "paid": paid, "note": note}


def candidates(task: str) -> list[str]:
    """Every model that fits a task, from the services with a saved key (and the known ones)."""
    kind = TASKS[task]["kind"]
    has = lambda s: bool(keys.slots(s))  # noqa: E731
    if kind == "text":
        out = list(KNOWN["anthropic"]) if not has("anthropic") else _anthropic()
        out += _gemini("text") if has("gemini") else KNOWN["gemini_text"]
        for host in ("groq", "cerebras", "openrouter"):
            if has(host):
                out += _hosted(host)
        return out
    if kind == "tts":
        return ["azure-neural", *(_gemini("tts") if has("gemini") else KNOWN["gemini_tts"])]
    if kind == "vision":  # reads a picture: Claude and Gemini (the hosted open models are text only)
        out = list(KNOWN["anthropic"]) if not has("anthropic") else _anthropic()
        return out + (_gemini("text") if has("gemini") else KNOWN["gemini_text"]) + VISION_FALLBACKS
    if kind == "listen":
        return ["azure-stt", *(_gemini("listen") if has("gemini") else KNOWN["gemini_listen"])]
    if kind == "image":
        return list(IMAGE_MODELS)
    return list(VIDEO_ENGINES if kind == "video" else MUSIC_ENGINES)


def overview(project: Project, sb: dict[str, Any] | None) -> dict[str, Any]:
    """{task: {label, purpose, does, chain, model, options}} for the studio's pickers.
    `model` is the one that answers first: the first in the chain whose service has a key
    and is not paused. Options from services without a key come last, marked."""
    out: dict[str, Any] = {}
    for task, spec in TASKS.items():
        now = chain(project, task, sb)
        order = [now] if isinstance(now, str) else list(now)
        names = list(dict.fromkeys([*order, *candidates(task)]))
        options = [_option(m, task) for m in names]
        ready = [o for o in options if o["id"] in order and o["connected"] and not o["paused"]]
        first = ready[0]["id"] if ready else order[0]
        options.sort(key=lambda o: (not o["connected"], o["paused"]))  # stable: chain order, then the rest
        out[task] = {**spec, "chain": order, "model": first, "options": options}
    return out
