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
from .cache import StageCache, key_for, sha256_bytes
from .config import ROOT, Project, load_env
from .costs import summarise
from .engines import MODES, VIDEO_ENGINES
from .limits import free_limits

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


def approved_sheets(sb: dict[str, Any], refs: StageCache) -> dict[str, Path]:
    """The sheet each keyframe is drawn from now, keyed as keyframes.references() keys them."""
    approved: dict[str, Path] = {}
    for c in sb["characters"]:
        path = refs.current(f"char_{c['id']}_{c['reference'].get('chosen', 0)}") if c["visible"] else None
        if path:
            approved[c["id"]] = path
    for p in sb["locations"]:
        path = refs.current(f"place_{p['id']}") if p.get("reference") else None
        if path:
            approved[f"place:{p['id']}"] = path
    return approved


def stale_sheets(sb: dict[str, Any], refs: StageCache) -> dict[str, bool]:
    """Sheets drawn from another look or photo than the storyboard holds now."""
    from .keyframes import (KEYFRAME_SIZE, REFERENCE_SIZE, character_ref_prompt, location_ref_prompt,
                            ref_spec)

    model = sbmod.model_list(sb["models"]["image"])[0]
    out: dict[str, bool] = {}

    def differs(item: str, spec: dict[str, Any]) -> bool:
        return refs.current(item) is not None and (refs.entry(item) or {}).get("key") != key_for(spec)

    for c in sb["characters"]:
        if c["visible"]:
            prompt, photo = character_ref_prompt(PROJECT, sb, c)
            out[c["id"]] = any(differs(f"char_{c['id']}_{i}", ref_spec(prompt, seed, model, REFERENCE_SIZE, photo))
                               for i, seed in enumerate(c["reference"]["seeds"]))
    for p in sb["locations"]:
        if p.get("reference"):
            prompt, photo = location_ref_prompt(PROJECT, sb, p)
            seed = p["reference"]["seeds"][p["reference"].get("chosen", 0)]
            out[p["id"]] = differs(f"place_{p['id']}", ref_spec(prompt, seed, model, KEYFRAME_SIZE, photo))
    return out


def stale(sb: dict[str, Any], shot: dict[str, Any], kf: StageCache, raw: StageCache,
          narration: StageCache, approved: dict[str, Path]) -> dict[str, Any]:
    """What a redo of this scene would remake: files that exist but were made from
    other inputs than the storyboard now holds. Same keys as the stages use, so
    "stale" means a run would really make something new."""
    from .keyframes import end_keyframe_spec, keyframe_spec, shot_refs
    from .narration import line_items, spec_for
    from .shots import clip_spec

    sid, mode = shot["id"], shot["motion"]["mode"]
    model = sbmod.model_list(sb["models"]["image"])[0]
    still, end = kf.current(sid), kf.current(f"{sid}_end") if mode == "flf_inbetween" else None
    refs = shot_refs(shot, approved)
    keyframe = bool(still) and (kf.entry(sid) or {}).get("key") != key_for(keyframe_spec(sb, shot, model, refs))
    if still and end:
        end_spec, _ = end_keyframe_spec(sb, shot, model, still, refs, approved.get(f"place:{shot['location']}"))
        keyframe = keyframe or (kf.entry(f"{sid}_end") or {}).get("key") != key_for(end_spec)
    voice = [narration.current(item) is not None and narration.hit(item, key_for(spec_for(sb, line)), ".wav") is None
             for item, s, line in line_items(sb) if s["id"] == sid]
    clip = False
    if MODES[mode]["paid"] and still and raw.current(sid) and (mode != "flf_inbetween" or end):
        clip = raw.hit(sid, key_for(clip_spec(sb, shot, still, end)), ".mp4") is None
    return {"keyframe": keyframe, "voice": voice, "clip": clip}


def _stale_or_unknown(sb: dict[str, Any], shot: dict[str, Any], kf: StageCache, raw: StageCache,
                      narration: StageCache, approved: dict[str, Path] | None) -> dict[str, Any]:
    if approved is None:  # a broken storyboard cannot build prompts; say nothing rather than guess
        return {"keyframe": False, "voice": [False] * len(shot.get("lines", [])), "clip": False}
    return stale(sb, shot, kf, raw, narration, approved)


def state() -> dict[str, Any]:
    story = PROJECT.story.read_text("utf-8") if PROJECT.story.exists() else ""
    if not PROJECT.storyboard.exists():
        from .script import SCRIPT_MODELS
        return {"story": story, "storyboard": None, "errors": [], "jobs": list(JOBS.values())[-5:],
                "limits": free_limits(PROJECT, {"script": SCRIPT_MODELS})}
    sb = sbmod.load(PROJECT)
    errors = sbmod.schema_errors(sb) or sbmod.rule_errors(sb, PROJECT)
    kf, raw, comp = (StageCache(PROJECT, s) for s in ("keyframes", "shots/raw", "shots"))
    narration, refs = StageCache(PROJECT, "narration"), StageCache(PROJECT, "refs")
    report_path = PROJECT.outputs / "final" / "heritage_short.report.json"
    report = json.loads(report_path.read_text("utf-8")) if report_path.exists() else {}
    approved = None if errors else approved_sheets(sb, refs)
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
            "stale": _stale_or_unknown(sb, shot, kf, raw, narration, approved),
        })
    sheets = {}
    for c in sb["characters"]:
        if c["visible"]:
            sheets[c["id"]] = [_url(refs.current(f"char_{c['id']}_{i}")) for i in range(len(c["reference"]["seeds"]))]
    for p in sb["locations"]:
        sheets[p["id"]] = [_url(refs.current(f"place_{p['id']}"))]
    try:
        sheets_stale = {} if errors else stale_sheets(sb, refs)
    except FileNotFoundError:  # a reference photo was removed by hand
        sheets_stale = {}
    photos = {x["id"]: _ref_url((x.get("reference") or {}).get("photo"))
              for x in sb["characters"] + sb["locations"]}
    final = PROJECT.outputs / "final"
    film = {"vertical": _url(final / "heritage_short_9x16.mp4"), "wide": _url(final / "heritage_short_16x9.mp4"),
            "radio": _url(PROJECT.outputs / "cuts" / "radio_cut.mp4"),
            "rough": _url(PROJECT.outputs / "cuts" / "rough_cut_9x16.mp4"), "report": report}
    cuts = [p for p in (final / "heritage_short_9x16.mp4", PROJECT.outputs / "cuts" / "rough_cut_9x16.mp4",
                        PROJECT.outputs / "cuts" / "radio_cut.mp4") if p.exists()]
    newest_cut = max((p.stat().st_mtime for p in cuts), default=0)
    media = [c.current(sh["id"]) for sh in sb["shots"] for c in (kf, raw)] +             [narration.current(item) for item in narration.manifest]
    film["stale"] = bool(cuts) and any(p and p.stat().st_mtime > newest_cut for p in media)
    music = StageCache(PROJECT, "music")
    candidates = [_url(music.current(f"candidate_{i}")) for i in range(len(sb["music"]["seeds"]))]
    music_price = 0.0
    if not errors:
        from .music import music_engine, spec_for as music_spec
        engine = music_engine(sb["models"]["music"])
        for i, seed in enumerate(sb["music"]["seeds"]):
            spec = music_spec(sb, seed)
            if not music.hit(f"candidate_{i}", key_for(spec), ".flac"):
                music_price += engine.get("usd_per_s", 0) * spec["duration"]
    costs = summarise(PROJECT)
    story_changed = sha256_bytes(story.encode("utf-8")) != sb.get("source", {}).get("story_sha256")
    return {"story": story, "story_changed": story_changed, "storyboard": sb, "errors": errors, "shots": shots, "sheets": sheets, "sheets_stale": sheets_stale, "photos": photos,
            "film": film, "music": candidates, "music_price": round(music_price, 3),
            "limits": free_limits(PROJECT, sb.get("models", {})),
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


# ---------------------------------------------------------------- the six steps

from .flow_api import router as flow_router  # noqa: E402  (flow_api reads PROJECT and start_job from here)

app.include_router(flow_router)


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


def build_app() -> None:
    """Build studio/dist when it is missing or older than the app's source, so
    `uv run python -m pipeline studio` is the only command needed (no make)."""
    import shutil
    import subprocess

    web = ROOT / "studio"
    index = web / "dist" / "index.html"
    sources = [web / "index.html", web / "package.json", web / "vite.config.ts", *(web / "src").rglob("*")]
    newest = max((f.stat().st_mtime for f in sources if f.is_file()), default=0)
    if index.exists() and index.stat().st_mtime >= newest:
        return
    tool = shutil.which("pnpm") or shutil.which("npm")
    if not tool:
        raise SystemExit("studio: the web app needs building, and that needs Node.js (https://nodejs.org) with pnpm or npm")
    print(f"studio: building the web app with {Path(tool).stem} (first run takes a minute)")
    if not (web / "node_modules").exists():
        subprocess.run([tool, "install"], cwd=web, check=True)
    subprocess.run([tool, "run", "build"], cwd=web, check=True)


def main() -> None:
    import uvicorn

    build_app()
    port = int(os.environ.get("STUDIO_PORT", "8765"))
    print(f"studio: http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
