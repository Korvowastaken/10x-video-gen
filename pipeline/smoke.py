"""`make smoke`: call every provider once and record what is really available today.

Free tiers and model names change monthly, so this runs before anything else.
It writes outputs/smoke/report.json (model lists, latencies, quota) and logs
each call to runs.jsonl like any other stage.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .config import ROOT, Project
from .media import write_wav

SMOKE_TTS_TEXT = "ሰላም። ይህ የድምፅ ሙከራ ነው።"  # "Hello. This is a voice test." in Amharic
SMOKE_IMAGE_PROMPT = ("low-poly 3D render, a clay coffee pot on a small wooden table, warm lamp light, "
                      "dark blue night background with soft bokeh, shallow depth of field")


def _version_key(name: str) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", name)[:3])


def pick_gemini(models: list[dict[str, Any]]) -> dict[str, list[str]]:
    names = [m["name"].removeprefix("models/") for m in models
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    tts = sorted([n for n in names if "tts" in n], key=_version_key, reverse=True)
    flash = sorted([n for n in names if re.fullmatch(r"gemini-[\d.]+-flash(-preview)?(-\d+-\d+)?", n)],
                   key=_version_key, reverse=True)
    lite = sorted([n for n in names if re.fullmatch(r"gemini-[\d.]+-flash-lite(-preview)?(-\d+-\d+)?", n)],
                  key=_version_key, reverse=True)
    return {"tts": tts, "flash": flash, "flash_lite": lite, "all": sorted(names)}


def _gemini(project: Project, report: dict[str, Any]) -> None:
    from .providers import gemini

    t0 = time.perf_counter()
    models = gemini.list_models()
    report["gemini"] = {"list_latency_s": round(time.perf_counter() - t0, 2), **pick_gemini(models)}
    picks = report["gemini"]
    if picks["flash"]:
        text, used = gemini.generate_text(project, stage="smoke", item="gemini-text", model=picks["flash"][:3],
                                          prompt="Reply with the single word: ready", temperature=0.0)
        report["gemini"]["text_reply"] = {"model": used, "text": text.strip()[:40]}
    if picks["tts"]:
        pcm, rate, used = gemini.tts(project, stage="smoke", item="gemini-tts", model=picks["tts"][:3],
                                     text=SMOKE_TTS_TEXT, voice="Kore", direction="Say warmly and slowly")
        wav = project.out("smoke", "tts_amharic.wav")
        write_wav(wav, pcm, rate=rate)
        report["gemini"]["tts"] = {"model": used, "seconds": round(len(pcm) / 2 / rate, 2),
                                   "file": str(wav.relative_to(project.root))}


def _cloudflare(project: Project, report: dict[str, Any]) -> None:
    from .providers import cloudflare

    flux = cloudflare.search_models("flux")
    report["cloudflare"] = {"flux_models": sorted(m.get("name", "") for m in flux)}
    for model in report["cloudflare"]["flux_models"]:
        if "klein" in model or "schnell" in model:
            schema = cloudflare.model_schema(model)
            report["cloudflare"].setdefault("schemas", {})[model] = schema.get("input", schema)
    tried = [m for m in report["cloudflare"]["flux_models"] if "klein" in m][:1] + \
            [m for m in report["cloudflare"]["flux_models"] if "schnell" in m][:1]
    for model in tried:
        data, ext = cloudflare.generate_image(project, stage="smoke", item=model.split("/")[-1], model=model,
                                              prompt=SMOKE_IMAGE_PROMPT, seed=7, width=512, height=512)
        path = project.out("smoke", model.split("/")[-1] + ext)
        path.write_bytes(data)
        report["cloudflare"].setdefault("images", []).append(str(path.relative_to(project.root)))


def _kaggle(project: Project, report: dict[str, Any], gpu: bool) -> None:
    from .providers import kaggle_runner

    client = kaggle_runner.api()
    report["kaggle"] = {"user": kaggle_runner.username(client), "gpu_quota": kaggle_runner.gpu_quota(client)}
    if gpu:
        _, results = kaggle_runner.run_job(
            project, stage="smoke", slug="heritage-smoke", kernel_script=ROOT / "pipeline" / "kaggle" / "smoke_kernel.py",
            job={"items": []}, inputs={}, model="nvidia-smi", poll_s=15, max_wait_s=1800)
        report["kaggle"]["gpu_job"] = results


def run(project: Project, *, kaggle_gpu: bool = False) -> int:
    report: dict[str, Any] = {}
    failures = 0
    for name, fn in (("gemini", lambda: _gemini(project, report)),
                     ("cloudflare", lambda: _cloudflare(project, report)),
                     ("kaggle", lambda: _kaggle(project, report, kaggle_gpu))):
        print(f"smoke: {name} ...")
        try:
            fn()
            print(f"smoke: {name} ok")
        except Exception as exc:  # report every provider, do not stop at the first failure
            failures += 1
            report.setdefault(name, {})["error"] = f"{type(exc).__name__}: {exc}"[:600]
            print(f"smoke: {name} FAILED: {exc}")
    out = project.out("smoke", "report.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n", "utf-8")
    print(f"smoke: report written to {Path(out).relative_to(project.root)}")
    return 1 if failures else 0
