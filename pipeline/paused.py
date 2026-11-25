"""Services the maker switched off on the Connections page.

A paused service keeps its keys in .env; the provider chains skip it as if it had no key,
so writing and voices fall through to the next service. Only services that sit in such a
chain can be paused: pausing the one service that draws the pictures would just stop the step.
"""

from __future__ import annotations

import os

from . import keys

VAR = "STUDIO_PAUSED"

# Services with a fallback behind them (writing and voices chains).
PAUSABLE = {"anthropic", "azure", "gemini", "groq", "cerebras", "openrouter"}


def paused() -> set[str]:
    return {s for s in (os.environ.get(VAR) or "").split(",") if s.strip()}


def is_paused(service: str) -> bool:
    return service in paused()


def set_paused(service: str, on: bool) -> None:
    if service not in PAUSABLE:
        raise ValueError(f"{service} can't be paused: nothing takes over its work")
    now = paused()
    now = now | {service} if on else now - {service}
    keys._write_env({VAR: ",".join(sorted(now)) or None})
