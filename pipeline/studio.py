"""`make studio`: a local web studio over the pipeline.

Write the story, upload reference photos, edit every scene, give feedback on a
scene and let Gemini revise it, then redo just that scene's still, voice or
clip, and assemble the film. The browser app is in studio/ (React); this module
is its API. Stages run one at a time as background jobs with a live log, so
the page never waits on a model, and every edit goes through the same
validation as the command line.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import revise
from . import storyboard as sbmod
from .cache import StageCache
from .config import ROOT, Project, load_env
from .costs import summarise
from .engines import MODES, VIDEO_ENGINES

load_env()
PROJECT = Project(Path(os.environ.get("STUDIO_PROJECT", ROOT)).resolve())
DIST = ROOT / "studio" / "dist"
app = FastAPI(title="10x video gen studio")


# ---------------------------------------------------------------- jobs

class _Tee(io.TextIOBase):
    def __init__(self, sink: list[str]):
        self.sink = sink

    def write(self, text: str) -> int:
        for line in text.splitlines():
            if line.strip():
                self.sink.append(line.rstrip())
        return len(text)


JOBS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()


def start_job(kind: str, work: Callable[[], Any]) -> dict[str, Any]:
    with _LOCK:
        busy = [j for j in JOBS.values() if j["status"] == "running"]
        if busy:
            raise HTTPException(409, f"'{busy[0]['kind']}' is still running")
        job = {"id": uuid.uuid4().hex[:8], "kind": kind, "status": "running", "log": [], "started": time.time()}
        JOBS[job["id"]] = job

    def target() -> None:
        try:
            with contextlib.redirect_stdout(_Tee(job["log"])):
                work()
            job["status"] = "done"
        except Exception as exc:  # shown to the person, not swallowed
            job["status"] = "error"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["log"].append(job["error"])
        job["ended"] = time.time()

    threading.Thread(target=target, daemon=True).start()
    return job


# ---------------------------------------------------------------- state

def _url(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    rel = path.relative_to(PROJECT.outputs).as_posix() if PROJECT.outputs in path.parents else None
    if rel is None:
        rel = "../" + path.relative_to(PROJECT.root).as_posix()
    return f"/media/{rel}?v={int(path.stat().st_mtime)}"


def _ref_url(rel: str | None) -> str | None:
    return f"/refs/{Path(rel).name}?v={int((PROJECT.root / rel).stat().st_mtime)}" \
        if rel and (PROJECT.root / rel).exists() else None


def state() -> dict[str, Any]:
    story = PROJECT.story.read_text("utf-8") if PROJECT.story.exists() else ""
    if not PROJECT.storyboard.exists():
        return {"story": story, "storyboard": None, "errors": [], "jobs": list(JOBS.values())[-5:]}
    sb = sbmod.load(PROJECT)
    errors = sbmod.schema_errors(sb) or sbmod.rule_errors(sb, PROJECT)
    kf, raw, comp = (StageCache(PROJECT, s) for s in ("keyframes", "shots/raw", "shots"))
    narration, refs = StageCache(PROJECT, "narration"), StageCache(PROJECT, "refs")
    report_path = PROJECT.outputs / "final" / "heritage_short.report.json"
    report = json.loads(report_path.read_text("utf-8")) if report_path.exists() else {}
    shots = []
    for shot in sb["shots"]:
        sid, mode = shot["id"], shot["motion"]["mode"]
        engine = VIDEO_ENGINES.get(shot["motion"].get("engine") or sb["models"]["video"], {})
        lines = []
        for n, _ in enumerate(shot["lines"], 1):
            entry = narration.entry(f"{sid}_L{n}") or {}
            lines.append({"audio": _url(narration.current(f"{sid}_L{n}")), "cer": entry.get("cer"),
                          "heard": entry.get("heard"), "seconds": entry.get("duration_s")})
        shots.append({
            "id": sid, "keyframe": _url(kf.current(sid)), "end": _url(kf.current(f"{sid}_end")),
            "clip": _url(comp.current(sid) if mode in ("masked_i2v", "cinemagraph") else raw.current(sid)),
            "paid": MODES[mode]["paid"],
            "price": engine.get("usd", {}).get(shot["motion"].get("clip_s", 5), 0) if MODES[mode]["paid"] else 0,
            "lines": lines, "used": (report.get("sources") or {}).get(sid, {}).get("used"),
        })
    sheets = {}
    for c in sb["characters"]:
        if c["visible"]:
            sheets[c["id"]] = [_url(refs.current(f"char_{c['id']}_{i}")) for i in range(len(c["reference"]["seeds"]))]
    for p in sb["locations"]:
        sheets[p["id"]] = [_url(refs.current(f"place_{p['id']}"))]
    photos = {x["id"]: _ref_url((x.get("reference") or {}).get("photo"))
              for x in sb["characters"] + sb["locations"]}
    final = PROJECT.outputs / "final"
    film = {"vertical": _url(final / "heritage_short_9x16.mp4"), "wide": _url(final / "heritage_short_16x9.mp4"),
            "radio": _url(PROJECT.outputs / "cuts" / "radio_cut.mp4"),
            "rough": _url(PROJECT.outputs / "cuts" / "rough_cut_9x16.mp4"), "report": report}
    music = StageCache(PROJECT, "music")
    candidates = [_url(music.current(f"candidate_{i}")) for i in range(len(sb["music"]["seeds"]))]
    costs = summarise(PROJECT)
    return {"story": story, "storyboard": sb, "errors": errors, "shots": shots, "sheets": sheets, "photos": photos,
            "film": film, "music": candidates,
            "spent": round(sum(s["usd_list"] for k, s in costs.items() if k in ("shots", "music")), 4),
            "calls": int(sum(s["calls"] for s in costs.values())), "jobs": list(JOBS.values())[-5:]}


@app.get("/api/state")
def get_state() -> dict[str, Any]:
    return state()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    if job_id not in JOBS:
        raise HTTPException(404, "no such job")
    return JOBS[job_id]


# ---------------------------------------------------------------- edits

class Story(BaseModel):
    text: str


@app.put("/api/story")
def put_story(body: Story) -> dict[str, Any]:
    PROJECT.story.write_text(body.text, "utf-8")
    return {"ok": True}


def _save_or_422(sb: dict[str, Any]) -> dict[str, Any]:
    errors = sbmod.schema_errors(sb) or sbmod.rule_errors(sb, PROJECT)
    if errors:
        raise HTTPException(422, {"errors": errors})
    sbmod.save(PROJECT, sb)
    return {"ok": True}


@app.put("/api/shots/{shot_id}")
def put_shot(shot_id: str, shot: dict[str, Any]) -> dict[str, Any]:
    if shot.get("id") != shot_id:
        raise HTTPException(400, "the scene id cannot change")
    errors = revise.apply(PROJECT, shot)
    if errors:
        raise HTTPException(422, {"errors": errors})
    return {"ok": True}


@app.put("/api/characters/{cid}")
def put_character(cid: str, character: dict[str, Any]) -> dict[str, Any]:
    sb = sbmod.load(PROJECT)
    sb["characters"] = [character if c["id"] == cid else c for c in sb["characters"]]
    return _save_or_422(sb)


class MusicChoice(BaseModel):
    chosen: int
    reason: str = ""


@app.put("/api/music")
def put_music(body: MusicChoice) -> dict[str, Any]:
    sb = sbmod.load(PROJECT)
    sb["music"]["chosen"] = body.chosen
    sb["music"]["chosen_reason"] = body.reason
    return _save_or_422(sb)


class Feedback(BaseModel):
    text: str


@app.post("/api/shots/{shot_id}/feedback")
def post_feedback(shot_id: str, body: Feedback) -> dict[str, Any]:
    try:
        return revise.propose(PROJECT, shot_id, body.text)
    except StopIteration:
        raise HTTPException(404, "no such scene")
    except Exception as exc:
        raise HTTPException(502, f"could not revise: {exc}")


@app.post("/api/references/{owner_id}")
async def post_reference(owner_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,31}", owner_id):
        raise HTTPException(400, "bad id")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        raise HTTPException(400, "use a JPG, PNG or WebP image")
    data = await file.read()
    if len(data) > 15_000_000:
        raise HTTPException(413, "image over 15 MB")
    folder = PROJECT.root / "references"
    folder.mkdir(exist_ok=True)
    for old in folder.glob(f"{owner_id}.*"):
        old.unlink()
    path = folder / f"{owner_id}{'.jpg' if ext == '.jpeg' else ext}"
    path.write_bytes(data)
    sb = sbmod.load(PROJECT)
    for item in sb["characters"] + sb["locations"]:
        if item["id"] == owner_id:
            item.setdefault("reference", {"prompt": "neutral standing pose", "seeds": [100]})
            item["reference"]["photo"] = f"references/{path.name}"
            return _save_or_422(sb)
    path.unlink()
    raise HTTPException(404, "no such character or place")


@app.delete("/api/references/{owner_id}")
def delete_reference(owner_id: str) -> dict[str, Any]:
    sb = sbmod.load(PROJECT)
    for item in sb["characters"] + sb["locations"]:
        if item["id"] == owner_id and (item.get("reference") or {}).pop("photo", None):
            for old in (PROJECT.root / "references").glob(f"{owner_id}.*"):
                old.unlink()
    return _save_or_422(sb)


# ---------------------------------------------------------------- stage runs

@app.post("/api/run/{stage}")
def run_stage_api(stage: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    from .__main__ import run_stage

    body = body or {}
    only = set(body["only"]) if body.get("only") else None
    force = bool(body.get("force"))
    if stage == "script":
        return start_job("script", lambda: run_stage("script", PROJECT, force=force))
    if stage in ("keyframes", "narration", "music"):
        return start_job(stage, lambda: run_stage(stage, PROJECT, only=only, force=force))
    if stage == "shots":
        max_paid = int(body.get("max_paid", 0))
        return start_job("shots", lambda: run_stage("shots", PROJECT, only=only, force=force, max_paid=max_paid))
    if stage in ("radio", "rough", "final"):
        def work() -> None:
            if stage == "radio":
                run_stage("narration", PROJECT)
            run_stage("assemble", PROJECT, mode=stage)
        return start_job(f"assemble {stage}", work)
    raise HTTPException(404, "no such stage")


@app.post("/api/shots/{shot_id}/redo")
def redo_shot(shot_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """Redo one scene's still, voice and/or clip. Only a clip costs money (max one)."""
    from .__main__ import run_stage

    parts = set(body.get("parts", []))
    only = {shot_id}

    def work() -> None:
        if "keyframe" in parts:
            run_stage("keyframes", PROJECT, only=only, force=True)
        if "voice" in parts:
            run_stage("narration", PROJECT, only=only, force=True)
        if "clip" in parts:
            run_stage("shots", PROJECT, only=only, force=True, max_paid=1)
        elif "keyframe" in parts:
            run_stage("shots", PROJECT, only=only, max_paid=0)  # depth, masks for the new still
    return start_job(f"redo {shot_id}: {', '.join(sorted(parts)) or 'nothing'}", work)


# ---------------------------------------------------------------- files

app.mount("/media", StaticFiles(directory=PROJECT.outputs, check_dir=False), name="media")


@app.get("/refs/{name}")
def get_ref(name: str) -> FileResponse:
    path = PROJECT.root / "references" / Path(name).name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="app")


def main() -> None:
    import uvicorn

    port = int(os.environ.get("STUDIO_PORT", "8765"))
    print(f"studio: http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
