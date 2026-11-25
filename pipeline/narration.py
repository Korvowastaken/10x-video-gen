"""Stage: narration. One TTS file per spoken line, so a re-take costs one call.

Two caches:
  outputs/narration/raw/   the TTS output, keyed by text, voice, direction,
                           model chain and prompt format;
  outputs/narration/       the processed line, keyed by the raw take plus the
                           post-processing version. Changing post-processing
                           never spends TTS quota again.

Each new take is listened back: a second model transcribes it and we score the
transcript against the script (character error rate, CER). A take that drifts
too far (the voice read the stage direction aloud once, FAILURES.md F7) is
re-taken, at most MAX_TAKES times, and the closest take is kept.

Processing: trim silence at both ends, shorten pauses inside the line that run
longer than 0.45 s, and set the line to -18 LUFS so every voice enters the mix
at the same level. Durations go to timing.json; assembly times shots from them.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path
from typing import Any

from . import storyboard as sbmod
from .cache import StageCache, key_for
from .config import ConfigError, Project
from .media import measure_loudness, probe_duration, run_ffmpeg, write_wav
from .providers import gemini
from .retry import ProviderError, QuotaExhausted, RetryableError

TARGET_LUFS = -18.0
POST_VERSION = 3            # bump when post-processing changes: re-renders from raw takes, no TTS calls
PROMPT_FORMAT = 3           # the bare line; see gemini.tts_prompt and FAILURES.md F7
MAX_TAKES = 3
RETAKE_CER = 0.6            # above this the take is very likely wrong, not just transcribed loosely
MIN_WORDS_PER_S = 0.9       # slower than this, the take holds more than the line (F7: a spoken style note)
TRIM_AND_TIGHTEN = (
    "silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.06,"
    "silenceremove=stop_periods=-1:stop_duration=0.45:stop_threshold=-40dB:stop_silence=0.32,"
    "areverse,silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.12,areverse"
)


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    return re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)


def char_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein distance over characters, divided by the reference length."""
    ref, hyp = _normalise(reference), _normalise(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, rc in enumerate(ref, 1):
        current = [i]
        for j, hc in enumerate(hyp, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (rc != hc)))
        previous = current
    return round(previous[-1] / len(ref), 3)


def process(raw: Path, out: Path) -> float:
    """Trim and tighten silences, then set the line to TARGET_LUFS. Returns the gain applied."""
    tightened = out.with_name(out.stem + ".tight.wav")
    run_ffmpeg(["-i", str(raw), "-af", TRIM_AND_TIGHTEN, "-ar", "24000", "-ac", "1", str(tightened)])
    loudness = measure_loudness(tightened)
    gain = max(-20.0, min(20.0, TARGET_LUFS - loudness.get("input_i", TARGET_LUFS)))
    run_ffmpeg(["-i", str(tightened), "-af", f"volume={gain:.2f}dB,alimiter=limit=0.89:level=false",
                "-ar", "24000", "-ac", "1", "-c:a", "pcm_s16le", str(out)])
    tightened.unlink(missing_ok=True)
    return round(gain, 2)


def line_items(sb: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(item id, shot, line) for every spoken line, in screen order."""
    return [(f"{shot['id']}_L{n}", shot, line) for shot in sb["shots"] for n, line in enumerate(shot["lines"], 1)]


def tts_spec(sb: dict[str, Any], line: dict[str, Any]) -> dict[str, Any]:
    """What a take depends on. Only the primary model is in the key: editing the
    fallback list must not re-speak every line. The model that actually spoke a
    take is recorded in the manifest and in runs.jsonl."""
    speaker = sbmod.characters(sb)[line["speaker"]]
    # The delivery note is not sent to the model (gemini.tts_prompt), so it is not in the key.
    return {"text": line["text"], "voice": speaker["voice"]["name"],
            "model": sbmod.model_list(sb["models"]["tts"])[0], "language": sb["language"]["code"],
            "prompt_format": PROMPT_FORMAT}


def too_long(text: str, seconds: float) -> bool:
    """A take far longer than its words allow holds something else: a spoken note, a repeat."""
    return seconds > len(text.split()) / MIN_WORDS_PER_S + 1.2


def tts_models(sb: dict[str, Any]) -> list[str]:
    return sbmod.model_list(sb["models"]["tts"])


def spec_for(sb: dict[str, Any], line: dict[str, Any]) -> dict[str, Any]:
    """Key of the processed line: the raw take's key plus the post-processing version."""
    return {"tts": key_for(tts_spec(sb, line)), "post": POST_VERSION}


def _take(project: Project, sb: dict[str, Any], item: str, spec: dict[str, Any], listen_models: list[str],
          raw_cache: StageCache) -> tuple[Path, dict[str, Any]]:
    """Speak the line, listen back, re-take while it drifts; keep the closest take."""
    best: tuple[float, Path, dict[str, Any]] | None = None
    tts_key = key_for(spec)
    for take in range(1, MAX_TAKES + 1):
        pcm, rate, used = gemini.tts(project, stage="narration", item=item if take == 1 else f"{item}-take{take}",
                                     model=tts_models(sb), text=spec["text"], voice=spec["voice"])
        raw = raw_cache.dir / f"{item}__{tts_key}.take{take}.wav"
        write_wav(raw, pcm, rate=rate)
        seconds = len(pcm) / 2 / rate
        meta: dict[str, Any] = {"model": used, "take": take, "raw_s": round(seconds, 2)}
        cer = None
        if listen_models:
            try:
                heard, _ = gemini.transcribe(project, stage="narration", item=f"{item}-listen{take}",
                                             model=listen_models, wav_bytes=raw.read_bytes(),
                                             language=sb["language"]["name"])
                cer = char_error_rate(spec["text"], heard)
                meta.update(heard=heard, cer=cer)
            except (ProviderError, QuotaExhausted, RetryableError) as exc:
                meta["listen_error"] = str(exc)[:200]
        long_take = too_long(spec["text"], seconds)
        meta["too_long"] = long_take
        score = (cer if cer is not None else 0.5) + (1.0 if long_take else 0.0)
        if best is None or score < best[0]:
            best = (score, raw, meta)
        if not long_take and (cer is None or cer <= RETAKE_CER):
            break
        reason = f"{seconds:.1f}s is too long for {len(spec['text'].split())} words" if long_take else f"CER {cer:.2f}"
        print(f"    {item}: take {take} does not match the script ({reason}); re-taking")
    assert best is not None
    _, raw, meta = best
    final_raw = raw_cache.path(item, tts_key, ".wav")
    shutil.copy2(raw, final_raw)
    for leftover in raw_cache.dir.glob(f"{item}__{tts_key}.take*.wav"):
        leftover.unlink()
    raw_cache.record(item, tts_key, final_raw, spec, **meta)
    return final_raw, meta


def run(project: Project, *, only: set[str] | None = None, force: bool = False,
        listen: bool = True) -> dict[str, float]:
    sb = sbmod.load_valid(project)
    cache = StageCache(project, "narration")
    raw_cache = StageCache(project, "narration/raw")
    listen_models = sbmod.model_list(sb["models"].get("listen", [])) if listen else []
    timing: dict[str, float] = {}
    stale: list[str] = []
    spoken = reprocessed = cached = 0
    for item, shot, line in line_items(sb):
        selected = only is None or shot["id"] in only
        tspec = tts_spec(sb, line)
        tts_key = key_for(tspec)
        key = key_for(spec_for(sb, line))
        out = cache.hit(item, key, ".wav")
        if out and not (force and selected):
            cached += 1
            timing[item] = cache.entry(item).get("duration_s") or probe_duration(out)
            continue
        if not selected and cache.current(item):
            timing[item] = probe_duration(cache.current(item))  # not selected: keep the old take
            continue
        raw = raw_cache.hit(item, tts_key, ".wav")
        if raw and not (force and selected):
            meta = {k: v for k, v in (raw_cache.entry(item) or {}).items() if k in ("model", "heard", "cer", "take")}
            reprocessed += 1
        else:
            try:
                raw, meta = _take(project, sb, item, tspec, listen_models, raw_cache)
                spoken += 1
            except (QuotaExhausted, ProviderError, RetryableError, ConfigError) as exc:
                old = cache.current(item)
                if old is None:
                    raise
                # No voice today (quota, no key): keep the previous take and say so loudly.
                stale.append(item)
                timing[item] = probe_duration(old)
                print(f"  {item}: STALE - kept the previous take ({' '.join(str(exc).split())[:100]})")
                continue
        out = cache.path(item, key, ".wav")
        gain = process(raw, out)
        duration = round(probe_duration(out), 3)
        cache.record(item, key, out, {"tts": tspec, "post": POST_VERSION}, duration_s=duration, gain_db=gain, **meta)
        timing[item] = duration
        flag = "  <-- check by ear" if (meta.get("cer") or 0) > 0.35 else ""
        cer = f", listen-back CER {meta['cer']:.2f}" if meta.get("cer") is not None else ""
        print(f"  {item}: {duration:.1f}s{cer}{flag}")
    project.out("narration", "timing.json").write_text(json.dumps(timing, indent=2) + "\n", "utf-8")
    project.out("narration", "stale.json").write_text(json.dumps(stale, indent=2) + "\n", "utf-8")
    print(f"  narration: {spoken} line(s) spoken, {reprocessed} re-processed from raw takes, {cached} cached, "
          f"{len(stale)} stale, {sum(timing.values()):.1f}s of speech")
    return timing
