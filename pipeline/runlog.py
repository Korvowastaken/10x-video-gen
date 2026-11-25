"""runs.jsonl: one JSON line per model call.

Every provider call goes through `model_call(...)`, a context manager that
times the call and appends exactly one line whether it succeeds or fails, so
retries and failures are visible in the log, not only successes. Cache hits
make no model call and write nothing here.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator

from .config import Project

RUN_ID = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:4]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


@dataclass
class Call:
    stage: str
    item: str
    provider: str
    model: str
    params: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    attempt: int = 1
    status: str = "started"
    latency_s: float | None = None
    gpu_s: float | None = None
    cost: dict[str, Any] | None = None
    cache_key: str | None = None
    output: str | None = None
    error: str | None = None
    note: str | None = None
    key: str | None = None  # which saved key made the call: a fingerprint, never the key


def append(project: Project, call: Call) -> None:
    record = {"ts": now_iso(), "run_id": RUN_ID}
    record.update({k: v for k, v in asdict(call).items() if v is not None})
    with open(project.runs, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


@contextmanager
def model_call(project: Project, **fields: Any) -> Iterator[Call]:
    """Time one model call and log it. The body may fill in cost, output, gpu_s."""
    call = Call(**fields)
    if call.key is None:  # taken now: a key that runs out is swapped before this call is logged
        from .keys import active_fingerprint
        call.key = active_fingerprint(call.provider)
    started = time.perf_counter()
    try:
        yield call
        if call.status == "started":
            call.status = "ok"
    except BaseException as exc:
        call.status = "error"
        call.error = f"{type(exc).__name__}: {exc}"[:400]
        raise
    finally:
        if call.latency_s is None:
            call.latency_s = round(time.perf_counter() - started, 3)
        append(project, call)


def read(project: Project) -> list[dict[str, Any]]:
    if not project.runs.exists():
        return []
    rows = []
    for line in project.runs.read_text("utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows
