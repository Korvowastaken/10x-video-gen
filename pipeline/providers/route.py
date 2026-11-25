"""One fallback chain across providers: the stages name models, this picks who answers.

A model id says its provider:
  claude-...            Anthropic (anthropic_api.py)
  groq/..., cerebras/..., openrouter/...   OpenAI-style hosts (openai_compat.py)
  azure-neural, azure-stt                  Azure AI Speech (azure_speech.py)
  anything else         Gemini (gemini.py)

Each model in a chain is tried in order. The chain moves on when a model is out
of quota, stays unavailable, refuses the request, or has no key saved (a
provider without a key is skipped, so a chain can name providers a person
has not signed up for). A model out of quota is skipped for the rest of the run.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

from .. import keys, paused
from ..config import ConfigError, Project
from ..retry import EXHAUSTED, ProviderError, QuotaExhausted, RetryableError
from . import anthropic_api, azure_speech, gemini, openai_compat

T = TypeVar("T")


def provider_of(model: str) -> str:
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith("azure-"):
        return "azure"
    head = model.partition("/")[0]
    if head in openai_compat.PROVIDERS:
        return head
    return "gemini"


def _chain(models: str | list[str], fn: Callable[[str], T], label: str) -> tuple[T, str]:
    chain = [models] if isinstance(models, str) else list(models)
    last: Exception | None = None
    for model in chain:
        if model in EXHAUSTED:
            continue
        service = provider_of(model)
        if service in keys.SERVICES and not keys.slots(service):
            # No key saved: skip quietly, without a failed call in runs.jsonl.
            last = last or ConfigError(f"no {keys.SERVICES[service]['label']} key is saved")
            continue
        if paused.is_paused(service):
            # Switched off on the Connections page: its keys stay, the next service takes over.
            last = last or ConfigError(f"{keys.SERVICES[service]['label']} is paused")
            continue
        try:
            return fn(model), model
        except QuotaExhausted as exc:
            EXHAUSTED.add(model)
            last = exc
            print(f"    fallback {label}: {model} is out of quota; skipping it for this run")
        except ConfigError as exc:
            last = exc
            print(f"    fallback {label}: skipping {model} ({' '.join(str(exc).split())[:110]})")
        except (RetryableError, ProviderError) as exc:
            last = exc
            print(f"    fallback {label}: {model} failed ({' '.join(str(exc).split())[:110]}); trying the next model")
    if last is None:
        raise QuotaExhausted(f"every model in {chain} is out of quota")
    raise last


def generate_text(project: Project, *, stage: str, item: str, models: str | list[str], prompt: str,
                  system: str | None = None, json_mode: bool = False, temperature: float = 0.8,
                  seed: int | None = None, timeout: float = 240, image: Path | None = None) -> tuple[str, str]:
    """Returns (text, model used)."""
    def one(model: str) -> str:
        provider = provider_of(model)
        if provider == "anthropic":
            return anthropic_api.generate_text(project, stage=stage, item=item, model=model, prompt=prompt,
                                               system=system, json_mode=json_mode, image=image,
                                               timeout=max(timeout, 300))
        if provider in openai_compat.PROVIDERS:
            if image is not None:
                raise ConfigError("this host is set up for text only")
            return openai_compat.generate_text(project, stage=stage, item=item, model=model, prompt=prompt,
                                               system=system, json_mode=json_mode, temperature=temperature,
                                               seed=seed, timeout=timeout)
        if provider == "azure":
            raise ConfigError("an Azure Speech model cannot write text")
        text, _ = gemini.generate_text(project, stage=stage, item=item, model=[model], prompt=prompt,
                                       system=system, json_mode=json_mode, temperature=temperature,
                                       seed=seed, timeout=timeout, image=image)
        return text
    return _chain(models, one, f"{stage}/{item}")


def tts(project: Project, *, stage: str, item: str, models: str | list[str], text: str, voice: str,
        language: str) -> tuple[bytes, int, str]:
    """Speak a line. `voice` is the storyboard's voice name. Returns (PCM, rate, model used)."""
    def one(model: str) -> tuple[bytes, int]:
        if provider_of(model) == "azure":
            return azure_speech.tts(project, stage=stage, item=item, text=text, voice_name=voice, language=language)
        if provider_of(model) != "gemini":
            raise ConfigError("not a speech model")
        pcm, rate, _ = gemini.tts(project, stage=stage, item=item, model=[model], text=text, voice=voice)
        return pcm, rate
    (pcm, rate), used = _chain(models, one, f"{stage}/{item}")
    return pcm, rate, used


def transcribe(project: Project, *, stage: str, item: str, models: str | list[str], wav_bytes: bytes,
               language: str, language_name: str) -> tuple[str, str]:
    """Listen back to a take. Returns (transcript, model used)."""
    def one(model: str) -> str:
        if provider_of(model) == "azure":
            return azure_speech.transcribe(project, stage=stage, item=item, wav_bytes=wav_bytes, language=language)
        if provider_of(model) != "gemini":
            raise ConfigError("not a listening model")
        heard, _ = gemini.transcribe(project, stage=stage, item=item, model=[model], wav_bytes=wav_bytes,
                                     language=language_name)
        return heard
    return _chain(models, one, f"{stage}/{item}")


def label(model: str) -> str:
    """A short credit for the end card."""
    return {"anthropic": "Claude", "azure": "Azure Speech", "gemini": "Gemini TTS"}.get(provider_of(model), model)


def services(models: list[str]) -> list[str]:
    """Providers in chain order, each once (for the studio's providers panel)."""
    return list(dict.fromkeys(provider_of(m) for m in models))

