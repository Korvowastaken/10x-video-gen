"""Azure AI Speech: neural voices for the lines and speech-to-text for the listen-back check.

The free tier (F0) is counted per month, not per day: about 0.5 million
characters of neural speech and 5 hours of speech-to-text, far more than one
film needs. REST is used directly, like the other providers.
Docs: https://learn.microsoft.com/azure/ai-services/speech-service/rest-text-to-speech

Azure has one female and one male neural voice for Amharic, so the storyboard's
voice choice (a Gemini voice name, presets.VOICES) picks the voice by its pitch
and shifts it a little by its character, which keeps two speakers apart.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from .. import keys, runlog
from ..config import ConfigError, Project, env
from ..presets import VOICES as GEMINI_VOICES
from ..retry import KeySwitched, ProviderError, QuotaExhausted, http_request, with_retries
from .gemini import _decode_audio

MODEL_TTS = "azure-neural"
MODEL_STT = "azure-stt"
# Language code -> (locale, {"f": voice, "m": voice}). Languages missing here fall back to Gemini.
VOICES = {
    "am": ("am-ET", {"f": "am-ET-MekdesNeural", "m": "am-ET-AmehaNeural"}),
    "so": ("so-SO", {"f": "so-SO-UbaxNeural", "m": "so-SO-MuuseNeural"}),
    "en": ("en-US", {"f": "en-US-AvaNeural", "m": "en-US-AndrewNeural"}),
}
LOWER = {"mature", "gravelly", "knowledgeable", "informative", "even"}
HIGHER = {"youthful", "bright", "excitable", "lively", "upbeat"}
# List prices for the paid tier (S0), used for the "list price" column in COSTS.md; F0 is free.
USD_PER_M_CHARS = 15.0
USD_PER_AUDIO_HOUR = 1.0
VOICE_VERSION = 1  # bump when voice() or the SSML changes: re-speaks Azure lines


def voice(gemini_voice: str, language: str) -> tuple[str, str, str]:
    """(locale, Azure voice, pitch shift) for a storyboard voice in `language`."""
    if language not in VOICES:
        raise ConfigError(f"Azure Speech has no neural voice set up here for language '{language}'")
    locale, by_pitch = VOICES[language]
    pitch, mood = GEMINI_VOICES.get(gemini_voice, ("f", ""))
    shift = "-6%" if mood in LOWER else "+6%" if mood in HIGHER else "+0%"
    return locale, by_pitch[pitch], shift


def ssml(text: str, locale: str, name: str, shift: str) -> str:
    return (f"<speak version='1.0' xml:lang='{locale}' xmlns='http://www.w3.org/2001/10/synthesis'>"
            f"<voice name='{name}'><prosody pitch='{shift}'>{escape(text)}</prosody></voice></speak>")


def _region() -> str:
    return env("AZURE_SPEECH_REGION").strip().lower().replace(" ", "")


def _headers(extra: dict[str, str]) -> dict[str, str]:
    return {"Ocp-Apim-Subscription-Key": env("AZURE_SPEECH_KEY"), "User-Agent": "heritage-studio", **extra}


def _call(url: str, headers: dict[str, str], content: bytes, timeout: float, scope: str) -> Any:
    """One request; an unaccepted key or a used-up month becomes the pipeline's error types."""
    try:
        return http_request("POST", url, headers=headers, content=content, timeout=timeout)
    except ProviderError as exc:
        text = str(exc)
        if text.startswith("HTTP 401"):
            raise ConfigError("Azure did not accept AZURE_SPEECH_KEY for AZURE_SPEECH_REGION") from exc
        if text.startswith("HTTP 403") and "quota" in text.lower():
            if keys.switch("azure", scope):
                raise KeySwitched("Azure Speech quota used up on this key: switched to the next saved key") from exc
            raise QuotaExhausted(f"Azure Speech free quota used up for this month: {text[:200]}") from exc
        raise


@keys.for_purpose("voices")
def tts(project: Project, *, stage: str, item: str, text: str, voice_name: str, language: str,
        timeout: float = 60) -> tuple[bytes, int]:
    """Speak `text`. Returns (16-bit mono PCM, sample rate)."""
    locale, name, shift = voice(voice_name, language)
    body = ssml(text, locale, name, shift).encode("utf-8")

    def attempt(n: int) -> tuple[bytes, int]:
        url = f"https://{_region()}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = _headers({"Content-Type": "application/ssml+xml",
                            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm"})
        params = {"voice": name, "pitch": shift, "from_voice": voice_name, "text_chars": len(text),
                  "text_sha": runlog.text_digest(text)}
        with runlog.model_call(project, stage=stage, item=item, provider="azure", model=MODEL_TTS,
                               params=params, attempt=n) as call:
            response = _call(url, headers, body, timeout, "tts")
            pcm, rate = _decode_audio(response.content, response.headers.get("content-type", ""))
            if not pcm:
                raise ProviderError("Azure returned no audio")
            call.cost = {"unit": "characters", "input": len(text), "usd_list": round(len(text) * USD_PER_M_CHARS / 1e6, 6)}
            call.note = f"audio {len(pcm) / 2 / rate:.2f}s"
            return pcm, rate

    return with_retries(attempt, attempts=3, label=f"{stage}/{item}")


def _to_16k(wav_bytes: bytes) -> bytes:
    """Short-audio speech-to-text takes 16 kHz mono PCM WAV."""
    from ..media import ffmpeg_bin
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "in.wav", Path(tmp) / "out.wav"
        src.write_bytes(wav_bytes)
        subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(src),
                        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)], check=True, capture_output=True)
        return dst.read_bytes()


@keys.for_purpose("voices")
def transcribe(project: Project, *, stage: str, item: str, wav_bytes: bytes, language: str,
               timeout: float = 60) -> str:
    """Write down what a take actually says, for the listen-back check."""
    if language not in VOICES:
        raise ConfigError(f"Azure speech-to-text is not set up here for language '{language}'")
    locale = VOICES[language][0]
    audio = _to_16k(wav_bytes)
    seconds = max(0.0, (len(audio) - 44) / 2 / 16000)

    def attempt(n: int) -> str:
        url = (f"https://{_region()}.stt.speech.microsoft.com/speech/recognition/conversation/"
               f"cognitiveservices/v1?language={locale}&format=simple")
        headers = _headers({"Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
                            "Accept": "application/json"})
        with runlog.model_call(project, stage=stage, item=item, provider="azure", model=MODEL_STT,
                               params={"task": "listen-back", "audio_bytes": len(audio), "locale": locale},
                               attempt=n) as call:
            payload = _call(url, headers, audio, timeout, "stt").json()
            call.cost = {"unit": "audio_s", "input": round(seconds, 2),
                         "usd_list": round(seconds / 3600 * USD_PER_AUDIO_HOUR, 6)}
            status = payload.get("RecognitionStatus")
            if status in ("NoMatch", "InitialSilenceTimeout", "BabbleTimeout"):
                return ""
            if status != "Success":
                raise ProviderError(f"Azure speech-to-text answered {status}")
            return (payload.get("DisplayText") or "").strip()

    return with_retries(attempt, attempts=3, label=f"{stage}/{item}")
