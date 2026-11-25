"""The studio's API for the six steps (flow.py, steps.py), mounted by studio.py.

GET /api/flow says where the film is. Every action that makes something runs
as a studio job and refuses while its step is locked. Paid actions need
`confirm_usd` at least the price, so nothing is bought by a stray click.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import flow, revise, steps
from . import storyboard as sbmod
from .cache import StageCache
from .media import probe_duration

router = APIRouter(prefix="/api")


def _studio():
    from . import studio
    return studio


def _project():
    return _studio().PROJECT


def _job(step: str, kind: str, work) -> dict[str, Any]:
    """Run `work` as a studio job, once `step` is unlocked."""
    project = _project()
    try:
        flow.require(project, step)
    except flow.GateError as exc:
        raise HTTPException(409, str(exc))
    return _studio().start_job(kind, work)


def _save(sb: dict[str, Any]) -> dict[str, Any]:
    errors = sbmod.schema_errors(sb) or sbmod.rule_errors(sb, _project())
    if errors:
        raise HTTPException(422, {"errors": errors})
    sbmod.save(_project(), sb)
    return {"ok": True}


@router.get("/flow")
def get_flow() -> dict[str, Any]:
    from .script import split_story

    from .script import SETTINGS_DEFAULTS, ScriptError

    project = _project()
    url = _studio()._url
    out = flow.status(project)
    sb = sbmod.load(project) if project.storyboard.exists() else None
    story = project.story.read_text("utf-8") if project.story.exists() else ""
    try:
        out["settings"], out["story_text"] = split_story(story)
    except ScriptError:
        out["settings"], out["story_text"] = dict(SETTINGS_DEFAULTS), story
    out["catalog"] = flow.catalog(sb)
    if sb:
        sketch, previews = StageCache(project, "sketch"), StageCache(project, "preview")
        out["sketch"] = {"frames": {s["id"]: url(sketch.current(s["id"])) for s in sb["shots"]},
                         "animatic": url(sketch.current("animatic"))}
        history = flow.load_approvals(project)["history"]
        for scene in out["scenes"]:
            scene["preview"] = url(previews.current(scene["id"]))
            scene["used"] = (previews.entry(scene["id"]) or {}).get("used")
            scene["history"] = [{"at": v["at"], "mode": v["mode"], "hash": v["hash"]}
                                for v in history.get(scene["id"], [])]
            shot = next(s for s in sb["shots"] if s["id"] == scene["id"])
            scene["price"] = flow.scene_price(sb, shot)
    return out


class Approval(BaseModel):
    step: str
    scene: str | None = None


@router.post("/approve")
def post_approve(body: Approval) -> dict[str, Any]:
    try:
        return flow.approve(_project(), body.step, body.scene)
    except flow.GateError as exc:
        raise HTTPException(409, str(exc))


@router.post("/unapprove")
def post_unapprove(body: Approval) -> dict[str, Any]:
    return flow.unapprove(_project(), body.step, body.scene)


# ---------------------------------------------------------------- 1 story

class Settings(BaseModel):
    language: str | None = None
    look: str | None = None
    target_seconds: int | None = None
    audience: str | None = None
    feel: str | None = None


@router.put("/settings")
def put_settings(body: Settings) -> dict[str, Any]:
    """Change the story's settings; the story text itself stays as written."""
    from .presets import LANGUAGES, STYLES
    from .script import join_story, split_story

    project = _project()
    settings, text = split_story(project.story.read_text("utf-8") if project.story.exists() else "")
    settings.update({k: v for k, v in body.model_dump().items() if v is not None})
    if settings["language"] not in LANGUAGES or settings["look"] not in STYLES \
            or not 60 <= int(settings["target_seconds"]) <= 90:
        raise HTTPException(422, "language, look or length is not one of the choices")
    project.story.write_text(join_story(settings, text), "utf-8")
    return {"ok": True}


class StoryText(BaseModel):
    text: str


@router.put("/story/text")
def put_story_text(body: StoryText) -> dict[str, Any]:
    """Save the story itself; its settings block stays as it is."""
    from .script import join_story, split_story

    project = _project()
    settings, _ = split_story(project.story.read_text("utf-8") if project.story.exists() else "")
    project.story.write_text(join_story(settings, body.text), "utf-8")
    return {"ok": True}


@router.get("/choices")
def get_choices() -> dict[str, Any]:
    from .presets import LANGUAGES, STYLES
    from .script import SETTINGS_DEFAULTS
    return {"languages": {k: v["name"] for k, v in LANGUAGES.items()}, "looks": list(STYLES),
            "defaults": SETTINGS_DEFAULTS}


# ---------------------------------------------------------------- 2 script

@router.post("/script/draft")
def post_draft() -> dict[str, Any]:
    return _job("script", "draft the script", lambda: steps.draft_script(_project(), force=True))


class Note(BaseModel):
    text: str


@router.post("/script/revise")
def post_script_revise(body: Note) -> dict[str, Any]:
    try:
        flow.require(_project(), "script")
        return revise.propose_script(_project(), body.text)
    except flow.GateError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"could not revise: {exc}")


@router.put("/script")
def put_script(proposal: dict[str, Any]) -> dict[str, Any]:
    """Accept a revised script (the whole storyboard the revision returned)."""
    errors = revise.apply_script(_project(), proposal)
    if errors:
        raise HTTPException(422, {"errors": errors})
    return {"ok": True}


# ---------------------------------------------------------------- 3 sketch

@router.post("/sketch")
def post_sketch() -> dict[str, Any]:
    return _job("sketch", "draw the sketch", lambda: steps.make_sketch(_project()))


class Order(BaseModel):
    order: list[str]


@router.post("/sketch/order")
def post_order(body: Order) -> dict[str, Any]:
    """Put the scenes in a new order. Each scene keeps its files and approvals."""
    project = _project()
    try:
        flow.require(project, "sketch")
        old = sbmod.load(project)
        new = sbmod.reorder(old, body.order)
    except flow.GateError as exc:
        raise HTTPException(409, str(exc))
    except sbmod.StoryboardError as exc:
        raise HTTPException(422, str(exc))
    errors = sbmod.schema_errors(new) or sbmod.rule_errors(new, project)
    if errors:
        raise HTTPException(422, {"errors": errors})
    flow.save_renumbered(project, old, new)
    return {"ok": True}


# ---------------------------------------------------------------- 4 references

@router.post("/sheets/draw")
def post_references() -> dict[str, Any]:
    return _job("references", "draw the references", lambda: steps.make_references(_project()))


@router.post("/sheets/{owner_id}/another")
def post_another(owner_id: str) -> dict[str, Any]:
    """Add one more candidate sheet (a new seed) and choose it; the next draw makes it."""
    sb = sbmod.load(_project())
    for item in sb["characters"] + sb["locations"]:
        if item["id"] == owner_id and item.get("reference"):
            seeds = item["reference"]["seeds"]
            seeds.append(max(seeds) + 1)
            item["reference"]["chosen"] = len(seeds) - 1
            return _save(sb)
    raise HTTPException(404, "no such character or place")


# ---------------------------------------------------------------- 5 scenes

class Video(BaseModel):
    allowed_modes: list[str] | None = None
    budget_usd: float | None = None


@router.put("/video")
def put_video(body: Video) -> dict[str, Any]:
    sb = sbmod.load(_project())
    sb.setdefault("video", {}).update({k: v for k, v in body.model_dump().items() if v is not None})
    return _save(sb)


class Make(BaseModel):
    redo: list[str] = []
    buy: bool = False
    confirm_usd: float = 0.0


@router.post("/scenes/{scene}/make")
def post_make(scene: str, body: Make) -> dict[str, Any]:
    sb = sbmod.load(_project())
    shot = next((s for s in sb["shots"] if s["id"] == scene), None)
    if shot is None:
        raise HTTPException(404, "no such scene")
    price = flow.scene_price(sb, shot) if body.buy else 0.0
    if price and body.confirm_usd + 1e-9 < price:
        raise HTTPException(402, f"buying this clip costs ${price:.2f}; confirm it first")
    parts = ", ".join(body.redo) or "make"
    return _job("scenes", f"scene {scene}: {parts}{' + buy' if price else ''}",
                lambda: steps.make_scene(_project(), scene, redo=set(body.redo), buy=bool(price)))


class Version(BaseModel):
    version: int


@router.post("/scenes/{scene}/restore")
def post_restore(scene: str, body: Version) -> dict[str, Any]:
    try:
        errors = flow.restore(_project(), scene, body.version)
    except flow.GateError as exc:
        raise HTTPException(409, str(exc))
    if errors:
        raise HTTPException(422, {"errors": errors})
    return {"ok": True}


class Preview(BaseModel):
    item: str
    tune: dict[str, float] = {}


@router.post("/voice/preview")
def post_voice_preview(body: Preview) -> dict[str, Any]:
    """Render one line with a tuning from its saved take. Free and local: no TTS call."""
    from . import narration

    project = _project()
    sb = sbmod.load_valid(project)
    try:
        path = narration.preview(project, sb, body.item, body.tune)
    except KeyError:
        raise HTTPException(404, "no such line")
    if path is None:
        raise HTTPException(409, "this line has no saved take yet; record it first")
    path, older = path
    return {"audio": _studio()._url(path), "seconds": round(probe_duration(path), 2), "older": older}


class Tuning(BaseModel):
    characters: dict[str, dict[str, float] | None] = {}
    lines: dict[str, dict[str, float] | None] = {}


@router.put("/voice")
def put_voice(body: Tuning) -> dict[str, Any]:
    """Save character defaults and line overrides (None clears one), then re-render the
    changed lines from their saved takes. Free and local: no TTS call."""
    from . import narration, tuning

    try:
        flow.require(_project(), "scenes")
    except flow.GateError as exc:
        raise HTTPException(409, str(exc))
    sb = sbmod.load(_project())
    cast = sbmod.characters(sb)
    for cid, tune in body.characters.items():
        if cid not in cast:
            raise HTTPException(404, f"no character '{cid}'")
        voice = cast[cid]["voice"]
        voice.pop("tune", None)
        if tune and (clean := tuning.normalise(tune)):
            voice["tune"] = clean
    lines = {item: line for item, _, line in narration.line_items(sb)}
    for item, tune in body.lines.items():
        if item not in lines:
            raise HTTPException(404, f"no line '{item}'")
        lines[item].pop("tune", None)
        if tune is not None:  # its own values, neutral ones too: they override the character's default
            lines[item]["tune"] = tuning.clamp(tune)
    _save(sb)
    return _job("scenes", "tune voices (free, from saved takes)",
                lambda: narration.run(_project(), listen=False, speak=False))


# ---------------------------------------------------------------- 6 final cut

class Cut(BaseModel):
    use: dict[str, str] = {}


@router.put("/cut")
def put_cut(body: Cut) -> dict[str, Any]:
    """Per scene, the mode the final cut uses when it should differ from the scene's own."""
    sb = sbmod.load(_project())
    use = {k: v for k, v in body.use.items() if v and v != next(
        (s["motion"]["mode"] for s in sb["shots"] if s["id"] == k), v)}
    sb.setdefault("edit", {})["use"] = use
    if not use:
        sb["edit"].pop("use")
    return _save(sb)


@router.post("/cut")
def post_cut() -> dict[str, Any]:
    return _job("final", "make the final cut", lambda: steps.make_cut(_project()))


class Buy(BaseModel):
    confirm_usd: float = 0.0


@router.post("/music/generate")
def post_music(body: Buy) -> dict[str, Any]:
    sb = sbmod.load(_project())
    price = flow.music_price(sb)
    if body.confirm_usd + 1e-9 < price:
        raise HTTPException(402, f"three score candidates cost about ${price:.2f}; confirm it first")
    from .__main__ import run_stage
    return _job("final", "make the score", lambda: run_stage("music", _project()))
