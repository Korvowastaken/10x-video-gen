"""Gemini API with a Google AI Studio key: script drafting, TTS, a listening check and (paid) pictures.

REST is used directly (no SDK) so every request and its usage numbers are easy
to log. Docs: https://ai.google.dev/gemini-api/docs/speech-generation
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any

import httpx

from .. import runlog
from ..config import Project, env
from .. import keys
from ..retry import KeySwitched, ProviderError, QuotaExhausted, http_request, with_fallback, with_retries

BASE = "https://generativelanguage.googleapis.com/v1beta"


def _headers() -> dict[str, str]:
    return {"x-goog-api-key": env("GEMINI_API_KEY", "GOOGLE_API_KEY"), "Content-Type": "application/json"}


def _on_throttle(response: httpx.Response) -> float | None:
    """Daily quota -> QuotaExhausted; per-minute limit -> the server's retry delay."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return None
    text = json.dumps(error)
    if response.status_code == 429 and re.search(r"PerDay|per day|daily", text, re.IGNORECASE):
        # The limit is per Google project and per model: another saved key may still have it.
        try:
            model = re.search(r"/models/([^/:?]+)", str(response.request.url))
        except RuntimeError:  # a response built without a request (tests)
            model = None
        if keys.switch("gemini", model.group(1) if model else ""):
            raise KeySwitched("QuotaExhausted on this key: switched to the next saved Gemini key")
        raise QuotaExhausted(f"Gemini daily quota used up: {error.get('message', '')[:240]}")
    for detail in error.get("details", []):
        delay = detail.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return float(delay[:-1]) + 1.0
            except ValueError:
                pass
    return None


def list_models() -> list[dict[str, Any]]:
    response = http_request("GET", f"{BASE}/models?pageSize=1000", headers=_headers(), timeout=30)
    return response.json().get("models", [])


def _generate(model: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    response = http_request("POST", f"{BASE}/models/{model}:generateContent", headers=_headers(),
                            json_body=body, timeout=timeout, on_throttle=_on_throttle)
    return response.json()


def _first_candidate_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ProviderError(f"no candidates returned (promptFeedback={payload.get('promptFeedback')})")
    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts") or []
    if not parts:
        raise ProviderError(f"empty candidate (finishReason={candidate.get('finishReason')})")
    return parts


def _usage(payload: dict[str, Any]) -> dict[str, Any]:
    usage = payload.get("usageMetadata", {})
    return {"unit": "tokens", "input": usage.get("promptTokenCount"),
            "output": usage.get("candidatesTokenCount"), "thinking": usage.get("thoughtsTokenCount")}


def _models(model: str | list[str]) -> list[str]:
    return [model] if isinstance(model, str) else list(model)


@keys.for_purpose("writing")
def generate_text(project: Project, *, stage: str, item: str, model: str | list[str], prompt: str,
                  system: str | None = None, json_mode: bool = False, temperature: float = 0.8,
                  seed: int | None = None, timeout: float = 240, image: Path | None = None) -> tuple[str, str]:
    """Returns (text, model used). `model` may be a fallback chain, best first. `image` is sent before the prompt."""
    return with_fallback(_models(model), lambda m: _generate_text_once(
        project, stage=stage, item=item, model=m, prompt=prompt, system=system, json_mode=json_mode,
        temperature=temperature, seed=seed, timeout=timeout, image=image), label=f"{stage}/{item}")


def _generate_text_once(project: Project, *, stage: str, item: str, model: str, prompt: str,
                        system: str | None, json_mode: bool, temperature: float,
                        seed: int | None, timeout: float, image: Path | None = None) -> str:
    parts: list[dict[str, Any]] = []
    if image is not None:
        mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(image.read_bytes()).decode("ascii")}})
    parts.append({"text": prompt})
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": temperature},
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if seed is not None:
        body["generationConfig"]["seed"] = seed

    def attempt(n: int) -> str:
        params = {"temperature": temperature, "json": json_mode, "prompt_chars": len(prompt),
                  "prompt_sha": runlog.text_digest(prompt)}
        with runlog.model_call(project, stage=stage, item=item, provider="gemini", model=model,
                               params=params, seed=seed, attempt=n) as call:
            payload = _generate(model, body, timeout)
            call.cost = _usage(payload)
            text = "".join(p.get("text", "") for p in _first_candidate_parts(payload) if not p.get("thought"))
            if not text.strip():
                raise ProviderError("model returned no text")
            return text

    return with_retries(attempt, attempts=3, label=f"{stage}/{item}")


@keys.for_purpose("voices")
def tts(project: Project, *, stage: str, item: str, model: str | list[str], text: str, voice: str,
        direction: str | None = None, seed: int | None = None, language: str | None = None,
        timeout: float = 180) -> tuple[bytes, int, str]:
    """Speak `text` with a prebuilt voice. Returns (16-bit mono PCM, sample rate, model used).

    `direction` is a short plain-language performance note (warmth, age, mood);
    see tts_prompt() for how it is attached to the line.
    """
    (pcm, rate), used = with_fallback(_models(model), lambda m: _tts_once(
        project, stage=stage, item=item, model=m, text=text, voice=voice, direction=direction,
        seed=seed, timeout=timeout, language=language), label=f"{stage}/{item}")
    return pcm, rate, used


def tts_prompt(text: str, direction: str | None = None, language: str | None = None) -> str:
    """The bare line. With Amharic text, both formats that put an English style
    note in the prompt ("<note>:\\n<line>" and 'Say this line, <note>: "<line>"')
    made the voice speak the note aloud, partly translated, before the line:
    a 4-word line became 10 s of audio instead of 2.25 s (FAILURES.md F7).
    Delivery now comes from the choice of voice; `direction` stays in the
    storyboard as documentation until a safe way to send it is proven."""
    del direction, language
    return text


def _decode_audio(data: bytes, mime: str) -> tuple[bytes, int]:
    """Return 16-bit mono PCM and its rate. Some TTS models send raw L16, some a WAV file."""
    if data[:4] == b"RIFF":
        import io
        import wave
        with wave.open(io.BytesIO(data)) as wav:
            if wav.getsampwidth() != 2 or wav.getnchannels() != 1:
                raise ProviderError(f"unexpected WAV format: {wav.getsampwidth() * 8}-bit, {wav.getnchannels()} channel(s)")
            return wav.readframes(wav.getnframes()), wav.getframerate()
    rate_match = re.search(r"rate=(\d+)", mime)
    return data, int(rate_match.group(1)) if rate_match else 24000


def _tts_once(project: Project, *, stage: str, item: str, model: str, text: str, voice: str,
              direction: str | None, seed: int | None, timeout: float, language: str | None = None) -> tuple[bytes, int]:
    prompt = tts_prompt(text, direction, language)
    body: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
        },
    }
    if seed is not None:
        body["generationConfig"]["seed"] = seed

    def attempt(n: int) -> tuple[bytes, int]:
        params = {"voice": voice, "text_chars": len(text), "text_sha": runlog.text_digest(text),
                  "prompt_format": 3}
        with runlog.model_call(project, stage=stage, item=item, provider="gemini", model=model,
                               params=params, seed=seed, attempt=n) as call:
            payload = _generate(model, body, timeout)
            call.cost = _usage(payload)
            for part in _first_candidate_parts(payload):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    mime = inline.get("mimeType") or inline.get("mime_type") or ""
                    pcm, rate = _decode_audio(base64.b64decode(inline["data"]), mime)
                    call.note = f"audio {mime}, {len(pcm) / 2 / rate:.2f}s"
                    return pcm, rate
            raise ProviderError("TTS response had no audio part")

    return with_retries(attempt, attempts=3, label=f"{stage}/{item}")


@keys.for_purpose("voices")
def transcribe(project: Project, *, stage: str, item: str, model: str | list[str], wav_bytes: bytes,
               language: str, timeout: float = 120) -> tuple[str, str]:
    """Listen back to a TTS line and write down what was actually said. Returns (text, model used).

    A cheap automatic check: if the transcript drifts far from the script, the
    voice probably mispronounced it or read the stage direction aloud.
    """
    return with_fallback(_models(model), lambda m: _transcribe_once(
        project, stage=stage, item=item, model=m, wav_bytes=wav_bytes, language=language,
        timeout=timeout), label=f"{stage}/{item}")


def _transcribe_once(project: Project, *, stage: str, item: str, model: str, wav_bytes: bytes,
                     language: str, timeout: float) -> str:
    instruction = (f"Transcribe this {language} speech exactly as spoken, in its native script. "
                   "Output only the transcript, with no translation and no commentary.")
    body = {"contents": [{"parts": [
        {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav_bytes).decode("ascii")}},
        {"text": instruction},
    ]}], "generationConfig": {"temperature": 0.0}}

    def attempt(n: int) -> str:
        with runlog.model_call(project, stage=stage, item=item, provider="gemini", model=model,
                               params={"task": "listen-back", "audio_bytes": len(wav_bytes)},
                               attempt=n) as call:
            payload = _generate(model, body, timeout)
            call.cost = _usage(payload)
            return "".join(p.get("text", "") for p in _first_candidate_parts(payload) if not p.get("thought")).strip()

    return with_retries(attempt, attempts=3, label=f"{stage}/{item}")


# ---------------------------------------------------------------- pictures

# Native image models (Nano Banana). The free tier has no image quota, so these are paid:
# a 429 "limit: 0" on a free key ends up as QuotaExhausted and the picture chain moves on.
# Per-image list prices at 1K, from the pricing page read 2026-11-26, for the cost column only.
IMAGE_PRICES = {
    "gemini-3.1-flash-lite-image": 0.0336,
    "gemini-3.1-flash-image": 0.067,
    "gemini-3-pro-image": 0.134,
}
ASPECTS = {"1:1": 1.0, "2:3": 2 / 3, "3:2": 1.5, "3:4": 0.75, "4:3": 4 / 3, "4:5": 0.8, "5:4": 1.25,
           "9:16": 9 / 16, "16:9": 16 / 9}


def is_image_model(model: str) -> bool:
    return model.startswith("gemini-") and model.endswith("-image")


def aspect_ratio(width: int, height: int) -> str:
    """The supported aspect ratio closest to width:height."""
    return min(ASPECTS, key=lambda name: abs(ASPECTS[name] - width / height))


def fit(data: bytes, width: int, height: int) -> bytes:
    """Cover-crop to width:height and resize, so every model hands back the size the stage asked for."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        w, h = img.size
        if w / h > width / height:
            new_w = round(h * width / height)
            img = img.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
        else:
            new_h = round(w * height / width)
            img = img.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
        if img.size != (width, height):
            img = img.resize((width, height), Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue()


@keys.for_purpose("pictures")
def generate_image(project: Project, *, stage: str, item: str, model: str, prompt: str, seed: int,
                   width: int, height: int, references: list[Path] | None = None,
                   timeout: float = 240) -> tuple[bytes, str]:
    """Draw one picture with a Nano Banana model, the references sent before the prompt.
    Returns (PNG bytes, ".png") at exactly width x height."""
    parts: list[dict[str, Any]] = []
    for ref in references or []:
        mime = "image/png" if ref.suffix.lower() == ".png" else "image/jpeg"
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(ref.read_bytes()).decode("ascii")}})
    parts.append({"text": prompt})
    ratio = aspect_ratio(width, height)
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE"], "seed": seed,
                             "imageConfig": {"aspectRatio": ratio, "imageSize": "1K"}},
    }

    def attempt(n: int) -> tuple[bytes, str]:
        params = {"width": width, "height": height, "aspect": ratio, "refs": [p.name for p in references or []],
                  "prompt_chars": len(prompt), "prompt_sha": runlog.text_digest(prompt)}
        with runlog.model_call(project, stage=stage, item=item, provider="gemini", model=model,
                               params=params, seed=seed, attempt=n) as call:
            payload = _generate(model, body, timeout)
            for part in _first_candidate_parts(payload):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data") and not part.get("thought"):
                    usage = _usage(payload)
                    call.cost = {"unit": "image", "count": 1, "usd_list": IMAGE_PRICES.get(model, 0.0),
                                 "tokens_in": usage["input"], "tokens_out": usage["output"]}
                    return fit(base64.b64decode(inline["data"]), width, height), ".png"
            raise ProviderError("Gemini returned no picture (refused, or answered in text)")

    return with_retries(attempt, attempts=3, label=f"{stage}/{item}")
