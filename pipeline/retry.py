"""Retries with backoff, and the error types every provider raises.

RetryableError   rate limit, 5xx, timeout: wait and try again.
QuotaExhausted   the daily/weekly free quota is used up: retrying now will not
                 help, so the stage moves to its fallback.
ProviderError    the request itself is wrong (400, safety block): do not retry.
"""
from __future__ import annotations

import random
import time
from typing import Any, Callable, TypeVar

import httpx

T = TypeVar("T")


class RetryableError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class QuotaExhausted(RuntimeError):
    pass


class KeySwitched(RetryableError):
    """The key ran out and another saved key took over: try the same request again now."""

    def __init__(self, message: str):
        super().__init__(message, retry_after=0)


class ProviderError(RuntimeError):
    pass


def with_retries(fn: Callable[[int], T], *, attempts: int = 4, base: float = 4.0,
                 cap: float = 90.0, label: str = "") -> T:
    """Call fn(attempt) until it succeeds, backing off exponentially with jitter.
    A switch to another key retries at once and does not use up an attempt."""
    attempt, switches = 1, 0
    while True:
        try:
            return fn(attempt)
        except KeySwitched:
            switches += 1
            if switches > 20:  # every saved key bounced: stop rather than loop
                raise
        except RetryableError as exc:
            if attempt >= attempts:
                raise
            delay = exc.retry_after if exc.retry_after is not None else min(cap, base * 2 ** (attempt - 1))
            delay = min(cap, delay) * random.uniform(0.85, 1.15)
            print(f"    retry {label}: attempt {attempt} failed ({' '.join(str(exc).split())[:110]}); "
                  f"waiting {delay:.0f}s")
            time.sleep(delay)
            attempt += 1


EXHAUSTED: set[str] = set()  # models whose daily quota ran out during this run


def with_fallback(models: list[str], fn: Callable[[str], T], *, label: str = "") -> tuple[T, str]:
    """Try each model in order; move on when one stays overloaded or its quota is gone.

    A model that reports an exhausted daily quota is skipped for the rest of
    the run instead of being asked again for every line. Returns (result,
    model actually used) so the caller can record it.
    """
    last: Exception | None = None
    for model in models:
        if model in EXHAUSTED:
            continue
        try:
            return fn(model), model
        except QuotaExhausted as exc:
            EXHAUSTED.add(model)
            last = exc
            print(f"    fallback {label}: {model} is out of daily quota; skipping it for this run")
        except RetryableError as exc:
            last = exc
            print(f"    fallback {label}: {model} unavailable ({' '.join(str(exc).split())[:100]}); "
                  "trying the next model")
    if last is None:
        raise QuotaExhausted(f"every model in {models} is out of daily quota")
    raise last


def _retry_after_header(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def http_request(method: str, url: str, *, headers: dict[str, str] | None = None,
                 json_body: Any = None, data: dict[str, Any] | None = None,
                 files: Any = None, timeout: float = 120.0,
                 on_throttle: Callable[[httpx.Response], float | None] | None = None) -> httpx.Response:
    """One HTTP call, translated into the error types above.

    on_throttle(response) may raise QuotaExhausted for a daily quota, or return
    a server-suggested delay in seconds for a per-minute limit.
    """
    try:
        response = httpx.request(method, url, headers=headers, json=json_body, data=data,
                                 files=files, timeout=timeout)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise RetryableError(f"network error: {type(exc).__name__}: {exc}") from exc
    status = response.status_code
    if status == 429 or status == 408 or status >= 500:
        delay = on_throttle(response) if on_throttle else None
        raise RetryableError(f"HTTP {status}: {response.text[:300]}",
                             retry_after=delay if delay is not None else _retry_after_header(response))
    if status >= 400:
        raise ProviderError(f"HTTP {status}: {response.text[:600]}")
    return response
