"""Hosted open models behind an OpenAI-style chat API: Groq, Cerebras, OpenRouter.

Their free tiers are much larger than Gemini's (rate limits per minute and per
day, not 10 requests a day), which suits the English storyboard draft. A model
is named "<provider>/<model id>" in storyboard.json, e.g. "groq/<model id>";
check the provider's model list for current ids, since they change often.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .. import keys, runlog
from ..config import Project, env
from ..retry import KeySwitched, ProviderError, QuotaExhausted, http_request, with_retries

PROVIDERS = {
    "groq": {"base": "https://api.groq.com/openai/v1", "key": "GROQ_API_KEY"},
    "cerebras": {"base": "https://api.cerebras.ai/v1", "key": "CEREBRAS_API_KEY"},
    "openrouter": {"base": "https://openrouter.ai/api/v1", "key": "OPENROUTER_API_KEY"},
}


def split(model: str) -> tuple[str, str]:
    """"groq/some-model" -> ("groq", "some-model"). OpenRouter ids keep their own slash."""
    provider, _, name = model.partition("/")
    if provider not in PROVIDERS or not name:
        raise ValueError(f"not an OpenAI-compatible model id: {model}")
    return provider, name


def _on_throttle(provider: str, name: str):
    def check(response: httpx.Response) -> float | None:
        text = response.text
        if response.status_code == 429 and re.search(r"per day|daily|\bRPD\b|\bTPD\b", text, re.IGNORECASE):
            if keys.switch(provider, name):
                raise KeySwitched(f"{provider} daily limit used up on this key: switched to the next saved key")
            raise QuotaExhausted(f"{provider} daily limit used up: {text[:240]}")
        return None
    return check


@keys.for_purpose("writing")
def generate_text(project: Project, *, stage: str, item: str, model: str, prompt: str,
                  system: str | None = None, json_mode: bool = False, temperature: float = 0.8,
                  seed: int | None = None, timeout: float = 240) -> str:
    provider, name = split(model)
    spec = PROVIDERS[provider]
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body: dict[str, Any] = {"model": name, "messages": messages, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if seed is not None:
        body["seed"] = seed

    def attempt(n: int) -> str:
        headers = {"Authorization": f"Bearer {env(spec['key'])}", "Content-Type": "application/json"}
        params = {"temperature": temperature, "json": json_mode, "prompt_chars": len(prompt),
                  "prompt_sha": runlog.text_digest(prompt)}
        with runlog.model_call(project, stage=stage, item=item, provider=provider, model=name,
                               params=params, seed=seed, attempt=n) as call:
            response = http_request("POST", f"{spec['base']}/chat/completions", headers=headers, json_body=body,
                                    timeout=timeout, on_throttle=_on_throttle(provider, name))
            payload = response.json()
            usage = payload.get("usage") or {}
            call.cost = {"unit": "tokens", "input": usage.get("prompt_tokens"),
                         "output": usage.get("completion_tokens"), "usd_list": 0.0}
            choices = payload.get("choices") or []
            text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
            if not text:
                raise ProviderError(f"empty answer (finish_reason={choices[0].get('finish_reason') if choices else None})")
            if json_mode:
                try:
                    json.loads(text)
                except ValueError as exc:
                    raise ProviderError(f"the answer was not valid JSON ({exc})") from exc
            return text

    return with_retries(attempt, attempts=3, label=f"{stage}/{item}")
