"""Stage: music. ACE-Step 1.5 score candidates, one per seed (WaveSpeed by default).

Like a composer's sketchbook: generate a few (three by default), listen under
the narration, and record the choice in storyboard.json (music.chosen and
music.chosen_reason). Each candidate is cached by its tags, length, seed and
engine, so changing the brief regenerates the candidates and nothing else.

WaveSpeed's ACE-Step endpoint takes only tags, lyrics, duration and seed: there
is no tempo or key field, so tempo, key and metre go into the tags text, against
the brief's advice to keep them out of the caption (FAILURES.md F13). No lyrics
means an instrumental track.

Candidates are matched to -20 LUFS on arrival, so music.gain_db is a mixing
decision relative to a known level, not a repair.
"""
from __future__ import annotations

import json
from typing import Any

from . import runlog
from . import storyboard as sbmod
from .cache import StageCache, key_for, write_atomic
from .config import ROOT, Project
from .engines import music_engine
from .media import measure_loudness, probe_duration, run_ffmpeg
from .providers import wavespeed
from .retry import ProviderError, QuotaExhausted, RetryableError

MUSIC_LUFS = -20.0
TIME_SIGNATURES = {"2/4": "2", "3/4": "3", "4/4": "4", "6/8": "6"}


def tags_for(sb: dict[str, Any]) -> str:
    m = sb["music"]
    parts = [m["caption"].rstrip(". "), "instrumental" if m["instrumental"] else "",
             f"{m['bpm']} bpm", m["key"], f"{m.get('time_signature', '4/4')} time"]
    return ", ".join(p for p in parts if p)


def spec_for(sb: dict[str, Any], seed: int, duration: float | None = None) -> dict[str, Any]:
    m = sb["music"]
    engine = sb["models"]["music"]
    return {"v": 2, "engine": engine, "model": music_engine(engine)["model"], "tags": tags_for(sb),
            "duration": duration or m["duration_s"], "seed": seed, "lyrics": m.get("lyrics") if not m["instrumental"] else None}


def _store(project: Project, cache: StageCache, item: str, key: str, spec: dict[str, Any], audio: bytes, ext: str,
           **meta: Any) -> None:
    raw = cache.dir / f"{item}__{key}.raw{ext}"
    write_atomic(raw, audio)
    loud = measure_loudness(raw)
    gain = MUSIC_LUFS - loud["input_i"]
    path = cache.path(item, key, ".flac")
    run_ffmpeg(["-i", str(raw), "-af", f"volume={gain:.2f}dB,alimiter=limit=0.95:level=false", "-ar", "48000",
                "-c:a", "flac", str(path)])
    raw.unlink(missing_ok=True)
    cache.record(item, key, path, spec, source_lufs=round(loud["input_i"], 1),
                 duration_s=round(probe_duration(path), 1), **meta)


def run(project: Project, *, force: bool = False) -> None:
    sb = sbmod.load_valid(project)
    cache = StageCache(project, "music")
    engine = music_engine(sb["models"]["music"])
    pending = []
    for index, seed in enumerate(sb["music"]["seeds"]):
        spec = spec_for(sb, seed)
        key = key_for(spec)
        if cache.hit(f"candidate_{index}", key, ".flac") and not force:
            continue
        pending.append((index, seed, spec, key))
    if pending and engine["provider"] == "wavespeed":
        for index, seed, spec, key in pending:
            try:
                audio, ext, info = wavespeed.music(project, stage="music", item=f"candidate_{index}",
                                                   model=engine["model"], usd_per_s=engine["usd_per_s"],
                                                   tags=spec["tags"], duration=spec["duration"], seed=seed,
                                                   lyrics=spec["lyrics"])
            except QuotaExhausted as exc:
                print(f"  music: no WaveSpeed credit left ({exc}); assembly keeps the placeholder score")
                break
            except (ProviderError, RetryableError) as exc:
                print(f"  music: candidate_{index} failed: {exc}")
                continue
            _store(project, cache, f"candidate_{index}", key, spec, audio, ext, task=info["task"])
    elif pending:
        _kaggle(project, sb, cache, pending)
    _summary(sb, cache)


def _kaggle(project: Project, sb: dict[str, Any], cache: StageCache, pending: list) -> None:
    """Fallback engine kaggle-ace-step-1.5: all pending candidates in one Kaggle job (not run end to end)."""
    from .providers import kaggle_runner

    m = sb["music"]
    job = {"caption": m["caption"], "bpm": m["bpm"], "key": m["key"],
           "timesignature": TIME_SIGNATURES.get(m.get("time_signature", "4/4"), "4"), "duration": m["duration_s"],
           "steps": 8, "seeds": [seed for _, seed, _, _ in pending], "indices": [i for i, _, _, _ in pending]}
    out_dir, results = kaggle_runner.run_job(project, stage="music", slug="heritage-acestep-music",
                                             kernel_script=ROOT / "pipeline" / "kaggle" / "acestep_music.py",
                                             job=job, inputs={}, model=sb["models"]["music"], max_wait_s=2 * 3600)
    for index, seed, spec, key in pending:
        item = results.get("items", {}).get(str(index), {})
        ok = item.get("status") == "ok" and (out_dir / item.get("file", "")).exists()
        runlog.append(project, runlog.Call(stage="music", item=f"candidate_{index}", provider="kaggle",
                                           model=sb["models"]["music"], seed=seed, status="ok" if ok else "error",
                                           latency_s=item.get("latency_s"), gpu_s=item.get("latency_s"),
                                           error=None if ok else item.get("error") or results.get("fatal")))
        if ok:
            _store(project, cache, f"candidate_{index}", key, spec, (out_dir / item["file"]).read_bytes(), ".wav")


def _summary(sb: dict[str, Any], cache: StageCache) -> None:
    rows = []
    for index, seed in enumerate(sb["music"]["seeds"]):
        entry = cache.entry(f"candidate_{index}") or {}
        rows.append({"index": index, "seed": seed, "file": entry.get("file"), "seconds": entry.get("duration_s")})
    chosen = sb["music"].get("chosen")
    print(f"  music candidates: {json.dumps(rows)}")
    print(f"  chosen: {chosen if chosen is not None else 'none yet - listen, then set music.chosen and chosen_reason'}")
