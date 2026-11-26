"""The studio job running on this thread: its log, and the way to stop it.

A job runs in a thread, and Python cannot stop a thread from outside. So Stop
sets a flag, and the work checks it at safe points: before each model call,
before each scene, sheet or line a stage works on, and while it waits between
retries. A request already
sent is let finish (its result is logged); nothing after it starts. Work that
is already paid for (a WaveSpeed clip being made, a Kaggle GPU run) finishes
first, so the money is not thrown away.

Outside a studio job (the command line, tests) every function here does nothing.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any

# Per thread: the page's own requests run beside a job and must neither stop with it nor log into it.
_local = threading.local()


class Cancelled(BaseException):
    """The person stopped the job. A BaseException, so a stage's `except Exception` lets it through."""


class Context:
    def __init__(self, job: dict[str, Any]):
        self.job = job
        self.stop = threading.Event()
        self.started = time.time()
        self.switches: dict[str, bool] = {}  # services the person allowed in this job (switch.py)
        self._answered = threading.Event()
        self._answer = False

    def add(self, level: str, text: str, **extra: Any) -> None:
        entry = {"at": round(time.time() - self.started, 1), "level": level, "text": text, **extra}
        self.job["log"].append(entry)

    def ask(self, question: dict[str, Any], text: str) -> bool:
        """Wait, with `question` on the page, until the person answers. Stop also ends the wait."""
        self._answered.clear()
        self.job["question"] = question
        self.add("warn", f"Waiting for you: {text}")
        try:
            while not self._answered.wait(0.5):
                if self.stop.is_set():
                    raise Cancelled("stopped")
        finally:
            self.job.pop("question", None)
        self.add("info", f"You chose {'to use ' + question['to'] if self._answer else 'to stop'}")
        return self._answer

    def answer(self, use: bool) -> bool:
        """The person's answer to the waiting question. False when nothing was asked."""
        if "question" not in self.job:
            return False
        self._answer = use
        self._answered.set()
        return True


def bind(ctx: Context | None) -> None:
    """Make `ctx` the job of the calling thread (None: no job)."""
    _local.ctx = ctx


def current() -> Context | None:
    return getattr(_local, "ctx", None)


def check() -> None:
    """Stop here if the person asked to."""
    ctx = current()
    if ctx and ctx.stop.is_set():
        raise Cancelled("stopped")


def sleep(seconds: float) -> None:
    """time.sleep that a Stop cuts short."""
    ctx = current()
    if ctx is None:
        time.sleep(seconds)
        return
    if ctx.stop.wait(max(0.0, seconds)):
        raise Cancelled("stopped")


_WARN = re.compile(r"^\s*(retry|warning|skipp|fell back|falling back|used up)|quota|fallback", re.I)
_ERROR = re.compile(r"^\s*(error|failed)|traceback|exception", re.I)


def printed(line: str) -> None:
    """One printed line, with a level read from its words."""
    ctx = current()
    if ctx is None:
        return
    level = "error" if _ERROR.search(line) else "warn" if _WARN.search(line) else "info"
    ctx.add(level, line.rstrip())


def call_done(call: Any) -> None:
    """One model call, finished or failed: a row of its own in the log, and the job's totals."""
    ctx = current()
    if ctx is None:
        return
    from .costs import _usd
    row = {"provider": call.provider, "model": call.model, "cost": call.cost}
    usd = round(_usd(row), 5)
    detail = {k: v for k, v in {
        "stage": call.stage, "item": call.item, "provider": call.provider, "model": call.model,
        "status": "stopped" if call.error and call.error.startswith("Cancelled") else call.status,
        "seconds": call.latency_s, "usd": usd or None, "attempt": call.attempt if call.attempt > 1 else None,
        "error": call.error if call.status == "error" and not (call.error or "").startswith("Cancelled") else None,
    }.items() if v is not None}
    ctx.add("call" if call.status == "ok" else "error", f"{call.provider} · {call.model} · {call.item}", call=detail)
    totals = ctx.job.setdefault("totals", {"calls": 0, "failed": 0, "usd": 0.0})
    totals["calls"] += 1
    totals["failed"] += call.status != "ok"
    totals["usd"] = round(totals["usd"] + usd, 5)
    ctx.job["step"] = call.stage
