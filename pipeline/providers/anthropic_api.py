"""Claude (Anthropic API): the storyboard draft, the spoken lines and scene revisions.

Paid per token with no daily cap, so a film never waits for a free quota to
reset. Claude Haiku 5.5 is cheap enough for the English storyboard (a draft is
a fraction of a cent); Claude Sonnet 5.5 writes the lines in the film's
language. Docs: https://platform.claude.com/docs/en/api/messages
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import anthropic

from .. import keys, runlog
from ..config import ConfigError, Project, env
from ..retry import KeySwitched, ProviderError, QuotaExhausted, RetryableError, with_retries

# USD per million tokens (input, output), first-party list prices, read 2026-11-25.
USD_PER_M = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
# Models that can hand a declined request to another model inside the same call.
SERVER_FALLBACK = {"claude-sonnet-5-5", "claude-opus-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def _client(timeout: float) -> anthropic.Anthropic:
    # Retries are ours (with_retries), so every attempt is one line in runs.jsonl.
    return anthropic.Anthropic(api_key=env("ANTHROPIC_API_KEY"), max_retries=0, timeout=timeout)


def json_text(text: str) -> str:
    """The JSON object in an answer, without a ```json fence or a sentence around it."""
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if start != -1 and end > start else text


def _usd(model: str, usage: Any) -> float:
    rate_in, rate_out = USD_PER_M.get(model, USD_PER_M["claude-sonnet-5-5"])
    tokens_in = (usage.input_tokens or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    return round(tokens_in * rate_in / 1e6 + (usage.output_tokens or 0) * rate_out / 1e6, 6)


def _translate(exc: anthropic.APIError) -> Exception:
    """SDK errors -> the pipeline's error types (retry.py)."""
    if isinstance(exc, anthropic.APIConnectionError):  # includes timeouts
        return RetryableError(f"network error: {exc}")
    if isinstance(exc, anthropic.RateLimitError):
        after = exc.response.headers.get("retry-after")
        return RetryableError(f"HTTP 429: {exc.message}", retry_after=float(after) if after else None)
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ConfigError(f"Anthropic did not accept ANTHROPIC_API_KEY ({exc.message})")
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:  # 529 is "overloaded"
            return RetryableError(f"HTTP {exc.status_code}: {exc.message}")
        if "credit balance" in str(exc.message).lower():
            if keys.switch("anthropic"):
                return KeySwitched("Anthropic credit used up on this key: switched to the next saved key")
            return QuotaExhausted(f"Anthropic credit used up: {exc.message}")
        return ProviderError(f"HTTP {exc.status_code}: {exc.message}")
    return ProviderError(str(exc))


@keys.for_purpose("writing")
def generate_text(project: Project, *, stage: str, item: str, model: str, prompt: str,
                  system: str | None = None, json_mode: bool = False, timeout: float = 300,
                  image: Path | None = None) -> str:
    """One answer from `model`. Sampling settings are left to the model: current Claude
    models reject temperature, and none takes a seed (the content cache keeps results stable)."""
    content: list[dict[str, Any]] = []
    if image is not None:
        mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        content.append({"type": "image", "source": {"type": "base64", "media_type": mime,
                                                    "data": base64.b64encode(image.read_bytes()).decode("ascii")}})
    content.append({"type": "text", "text": prompt})
    system_text = system or ""
    if json_mode:
        system_text = (system_text + "\n\nAnswer with one JSON object only: no code fence, no text around it.").strip()
    request: dict[str, Any] = {"model": model, "max_tokens": 16000,
                               "messages": [{"role": "user", "content": content}]}
    if system_text:
        request["system"] = system_text
    if model in SERVER_FALLBACK:
        request.update(betas=[FALLBACK_BETA], fallbacks="default")

    def attempt(n: int) -> str:
        params = {"json": json_mode, "prompt_chars": len(prompt), "prompt_sha": runlog.text_digest(prompt),
                  "image": image is not None}
        with runlog.model_call(project, stage=stage, item=item, provider="anthropic", model=model,
                               params=params, attempt=n) as call:
            try:
                client = _client(timeout)
                response = (client.beta.messages.create(**request) if "betas" in request
                            else client.messages.create(**request))
            except anthropic.APIError as exc:
                raise _translate(exc) from exc
            served = getattr(response, "model", model) or model
            call.cost = {"unit": "tokens", "input": response.usage.input_tokens,
                         "output": response.usage.output_tokens, "usd_list": _usd(served, response.usage)}
            if served != model:
                call.note = f"served by {served}"
            if response.stop_reason == "refusal":
                raise ProviderError(f"{model} declined the request")
            if response.stop_reason == "max_tokens":
                raise ProviderError(f"{model} ran out of output tokens before it finished")
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            if not text:
                raise ProviderError("model returned no text")
            if json_mode:
                text = json_text(text)
                json.loads(text)  # a broken answer is retried here, not passed on
            return text

    def guarded(n: int) -> str:
        try:
            return attempt(n)
        except json.JSONDecodeError as exc:
            raise RetryableError(f"the answer was not valid JSON ({exc})", retry_after=0) from exc

    return with_retries(guarded, attempts=3, label=f"{stage}/{item}")
