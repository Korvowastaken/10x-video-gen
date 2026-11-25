"""The six steps from a story to a film. Each one is approved before the next unlocks.

    story -> script -> sketch -> references -> scenes -> final

A step's fingerprint is a hash of what the person looked at when they approved
it: its own content, plus the fingerprints of what it was made from. Approving
writes that fingerprint to approvals.json, next to storyboard.json. When
something changes later, the fingerprint no longer matches and the step shows
as stale, with the reason ("the script changed"). Nothing is deleted: approving
again, or redoing the part that changed, clears it.

Fingerprints follow real dependencies, the way cache keys do. Editing a line
makes the script and the sketch stale (the sketch shows the subtitles), not the
references. Unlocking follows the order: a step opens only when every step
before it is approved and fresh. The studio and `python -m pipeline flow` both
read this module, so they always agree on where you are and what comes next.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from . import storyboard as sbmod
from .cache import StageCache, key_for, sha256_bytes, sha256_file
from .config import ConfigError, Project
from .engines import MODES, MUSIC_ENGINES, VIDEO_ENGINES
from .runlog import now_iso

STEPS = ("story", "script", "sketch", "references", "scenes", "final")
TITLES = {"story": "Story", "script": "Script", "sketch": "Sketch", "references": "References",
          "scenes": "Scenes", "final": "Final cut"}
# How a changed part is named when a step goes stale.
PART_WORDS = {"story": "the story", "script": "the script", "sketch": "the sketch", "references": "the references",
              "scene": "the scene", "keyframe": "the picture", "voice": "the voice", "clip": "the clip",
              "scenes": "a scene", "cut": "the cut choices", "film": "the film"}
FILM_REPORT = ("final", "heritage_short.report.json")
CUT_MADE_FROM = ("final", "heritage_short.flow.json")  # what the film on disk was made from

# What each action costs. Free tiers cost nothing, but they have daily limits.
ACTIONS = {
    "draft_script": {"usd": 0.0, "where": "Gemini, free tier"},
    "revise": {"usd": 0.0, "where": "Gemini, free tier"},
    "sketch": {"usd": 0.0, "where": "drawn on this computer"},
    "references": {"usd": 0.0, "where": "FLUX.2 on Cloudflare, free tier (about 240 of 10,000 daily neurons each)"},
    "keyframe": {"usd": 0.0, "where": "FLUX.2 on Cloudflare, free tier"},
    "voice": {"usd": 0.0, "where": "Gemini TTS, free tier"},
    "preview": {"usd": 0.0, "where": "free motion, made on this computer"},
    "cut": {"usd": 0.0, "where": "FFmpeg on this computer"},
}


class GateError(ConfigError):
    """An action was asked for before the step it belongs to was unlocked or ready."""


# ---------------------------------------------------------------- approvals.json

def approvals_path(project: Project) -> Path:
    return project.root / "approvals.json"


def load_approvals(project: Project) -> dict[str, Any]:
    path = approvals_path(project)
    data = json.loads(path.read_text("utf-8")) if path.exists() else {}
    data.setdefault("steps", {})
    data.setdefault("scenes", {})
    data.setdefault("history", {})
    return data


def save_approvals(project: Project, data: dict[str, Any]) -> None:
    path = approvals_path(project)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", "utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- what each step is made of

def _print(parts: dict[str, Any]) -> dict[str, Any]:
    return {"hash": key_for(parts), "parts": parts}


def script_view(sb: dict[str, Any]) -> dict[str, Any]:
    """The words of the film: who speaks, what they say, what happens. Order-free,
    so reordering scenes in the sketch does not reopen the script. Voice tuning is
    left out: it is set in Scenes and only re-renders saved takes."""
    def untuned(x: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in x.items() if k != "tune"}

    cast = [{k: untuned(c[k]) if k == "voice" else c.get(k) for k in ("id", "name", "role", "visible", "voice")}
            for c in sb["characters"]]
    scenes = sorted(key_for({k: [untuned(ln) for ln in s["lines"]] if k == "lines" else s.get(k)
                             for k in ("beat", "location", "characters", "duration_s", "lines")})
                    for s in sb["shots"])
    return {"title": sb.get("title"), "logline": sb.get("logline"), "language": sb.get("language"),
            "cast": cast, "places": [{k: p.get(k) for k in ("id", "name")} for p in sb["locations"]],
            "scenes": scenes}


def sketch_view(sb: dict[str, Any]) -> list[dict[str, Any]]:
    """Composition: scene order, framing and where each figure stands."""
    return [{k: s.get(k) for k in ("id", "size", "location", "characters", "duration_s", "sketch")}
            for s in sb["shots"]]


def _sheet_key(refs: StageCache, item: str) -> str | None:
    return (refs.entry(item) or {}).get("key") if refs.current(item) else None


def chosen_sheets(sb: dict[str, Any], refs: StageCache) -> dict[str, str]:
    """Cache item of the approved sheet per character id and "place:<id>"."""
    out = {f"{c['id']}": f"char_{c['id']}_{c['reference'].get('chosen', 0)}" for c in sb["characters"] if c["visible"]}
    out.update({f"place:{p['id']}": f"place_{p['id']}" for p in sb["locations"] if p.get("reference")})
    return out


def references_view(project: Project, sb: dict[str, Any]) -> dict[str, Any]:
    refs = StageCache(project, "refs")
    looks = [{k: x.get(k) for k in ("id", "look", "reference")} for x in sb["characters"] + sb["locations"]]
    photos = {x["id"]: sha256_file(project.root / x["reference"]["photo"])
              for x in sb["characters"] + sb["locations"]
              if (x.get("reference") or {}).get("photo") and (project.root / x["reference"]["photo"]).exists()}
    sheets = {owner: _sheet_key(refs, item) for owner, item in chosen_sheets(sb, refs).items()}
    return {"style": sb.get("style"), "looks": looks, "photos": photos, "sheets": sheets}


def clip_item(shot: dict[str, Any]) -> tuple[str, str] | None:
    mode = shot["motion"]["mode"]
    if not MODES.get(mode, {}).get("paid"):
        return None
    return ("shots", shot["id"]) if mode in ("masked_i2v", "cinemagraph") else ("shots/raw", shot["id"])


def scene_parts(project: Project, sb: dict[str, Any], shot: dict[str, Any], caches: dict[str, StageCache]) -> dict[str, Any]:
    sid = shot["id"]
    sheets = chosen_sheets(sb, caches["refs"])
    owners = list(shot["characters"]) + [f"place:{shot['location']}"]
    picture = [(caches["keyframes"].entry(i) or {}).get("key") for i in (sid, f"{sid}_end")]
    voice = [(caches["narration"].entry(f"{sid}_L{n}") or {}).get("key") for n in range(1, len(shot["lines"]) + 1)]
    clip = clip_item(shot)
    return {"scene": key_for({k: v for k, v in shot.items() if k not in ("id", "sketch")}),
            "references": key_for({o: _sheet_key(caches["refs"], sheets[o]) for o in owners if o in sheets}),
            "keyframe": key_for(picture), "voice": key_for(voice),
            "clip": key_for((caches[clip[0]].entry(clip[1]) or {}).get("key") if clip else None)}


def _caches(project: Project) -> dict[str, StageCache]:
    return {s: StageCache(project, s) for s in ("refs", "keyframes", "narration", "shots", "shots/raw", "sketch")}


def fingerprints(project: Project, sb: dict[str, Any] | None) -> dict[str, Any]:
    """The fingerprint of every step, and of every scene under "scene:<id>"."""
    story = project.story.read_text("utf-8") if project.story.exists() else ""
    out: dict[str, Any] = {"story": _print({"story": sha256_bytes(story.encode("utf-8"))[:16]})}
    if sb is None:
        return out
    caches = _caches(project)
    out["script"] = _print({"script": key_for(script_view(sb)), "story": out["story"]["hash"]})
    out["sketch"] = _print({"sketch": key_for(sketch_view(sb)), "script": out["script"]["hash"]})
    out["references"] = _print({"references": key_for(references_view(project, sb))})
    for shot in sb["shots"]:
        out[f"scene:{shot['id']}"] = _print(scene_parts(project, sb, shot, caches))
    out["scenes"] = _print({"scenes": key_for({s["id"]: out[f"scene:{s['id']}"]["hash"] for s in sb["shots"]})})
    report = project.outputs.joinpath(*FILM_REPORT)
    cut = {k: sbmod.edit_settings(sb).get(k) for k in ("use", "grade", "grade_strength")}
    cut["music"] = sb["music"].get("chosen")
    out["final"] = _print({"scenes": out["scenes"]["hash"], "cut": key_for(cut),
                           "film": sha256_file(report)[:16] if report.exists() else None})
    return out


# ---------------------------------------------------------------- readiness

def _load(project: Project) -> tuple[dict[str, Any] | None, list[str]]:
    if not project.storyboard.exists():
        return None, []
    sb = sbmod.load(project)
    return sb, sbmod.schema_errors(sb) or sbmod.rule_errors(sb, project)


def _approved_sheet_files(sb: dict[str, Any], refs: StageCache) -> dict[str, Path]:
    return {owner: path for owner, item in chosen_sheets(sb, refs).items() if (path := refs.current(item))}


def scene_blockers(project: Project, sb: dict[str, Any], shot: dict[str, Any]) -> list[str]:
    """What is missing or out of date before this scene can be approved."""
    from .keyframes import end_keyframe_spec, keyframe_spec, shot_refs
    from .narration import spec_for

    sid = shot["id"]
    model = sbmod.model_list(sb["models"]["image"])[0]
    kf, narration = StageCache(project, "keyframes"), StageCache(project, "narration")
    approved = _approved_sheet_files(sb, StageCache(project, "refs"))
    refs = shot_refs(shot, approved)
    problems = []
    still = kf.hit(sid, key_for(keyframe_spec(sb, shot, model, refs)), ".jpg") or \
        kf.hit(sid, key_for(keyframe_spec(sb, shot, model, refs)), ".png")
    if still is None:
        problems.append("draw the picture" if kf.current(sid) is None else "the picture is out of date: redraw it")
    elif shot["motion"]["mode"] == "flf_inbetween":
        spec, _ = end_keyframe_spec(sb, shot, model, still, refs, approved.get(f"place:{shot['location']}"))
        if not (kf.hit(f"{sid}_end", key_for(spec), ".jpg") or kf.hit(f"{sid}_end", key_for(spec), ".png")):
            problems.append("draw the end picture")
    for n, line in enumerate(shot["lines"], 1):
        if narration.hit(f"{sid}_L{n}", key_for(spec_for(sb, line)), ".wav") is None:
            problems.append(f"record line {n}")
    return problems


def clip_bought(project: Project, sb: dict[str, Any], shot: dict[str, Any]) -> bool:
    from .shots import clip_spec

    kf = StageCache(project, "keyframes")
    still, end = kf.current(shot["id"]), kf.current(f"{shot['id']}_end")
    if not MODES.get(shot["motion"]["mode"], {}).get("paid") or still is None:
        return False
    if shot["motion"]["mode"] == "flf_inbetween" and end is None:
        return False
    spec = clip_spec(sb, shot, still, end if shot["motion"]["mode"] == "flf_inbetween" else None)
    return StageCache(project, "shots/raw").hit(shot["id"], key_for(spec), ".mp4") is not None


def blockers(project: Project, step: str, sb: dict[str, Any] | None, errors: list[str]) -> list[str]:
    """What has to happen before `step` can be approved (empty: it can be)."""
    if step == "story":
        from .script import ScriptError, parse_story
        if not project.story.exists():
            return ["write the story"]
        try:
            parse_story(project.story.read_text("utf-8"))
        except ScriptError as exc:
            return [str(exc).removeprefix("story.md: ")]
        return []
    if sb is None:
        return ["draft the script from the story"]
    if errors:
        return errors[:5]
    if step == "script":
        return []
    if step == "sketch":
        from . import sketch
        cache = StageCache(project, "sketch")
        missing = [s["id"] for s in sb["shots"] if not cache.hit(s["id"], key_for(sketch.frame_spec(sb, s)), ".png")]
        return [f"draw the sketch ({', '.join(missing)} not drawn yet)"] if missing else []
    if step == "references":
        from .keyframes import KEYFRAME_SIZE, REFERENCE_SIZE, character_ref_prompt, location_ref_prompt, ref_spec
        refs = StageCache(project, "refs")
        model = sbmod.model_list(sb["models"]["image"])[0]
        out = []
        for c in sb["characters"]:
            if c["visible"]:
                prompt, photo = character_ref_prompt(project, sb, c)
                i = c["reference"].get("chosen", 0)
                spec = ref_spec(prompt, c["reference"]["seeds"][i], model, REFERENCE_SIZE, photo)
                if not (refs.hit(f"char_{c['id']}_{i}", key_for(spec), ".jpg")
                        or refs.hit(f"char_{c['id']}_{i}", key_for(spec), ".png")):
                    out.append(f"draw {c['name']}'s sheet")
        for p in sb["locations"]:
            if p.get("reference"):
                prompt, photo = location_ref_prompt(project, sb, p)
                spec = ref_spec(prompt, p["reference"]["seeds"][p["reference"].get("chosen", 0)], model,
                                KEYFRAME_SIZE, photo)
                if not (refs.hit(f"place_{p['id']}", key_for(spec), ".jpg")
                        or refs.hit(f"place_{p['id']}", key_for(spec), ".png")):
                    out.append(f"draw {p['name']}")
        return out
    if step == "scenes":
        approvals, prints = load_approvals(project), fingerprints(project, sb)
        waiting = [s["id"] for s in sb["shots"]
                   if (approvals["scenes"].get(s["id"]) or {}).get("hash") != prints[f"scene:{s['id']}"]["hash"]]
        return [f"approve every scene ({', '.join(waiting)} to go)"] if waiting else []
    if step == "final":
        made = project.outputs.joinpath(*CUT_MADE_FROM)
        if not made.exists():
            return ["make the final cut"]
        return [] if json.loads(made.read_text("utf-8")) == _cut_inputs(project, sb) \
            else ["make the final cut again: a scene or a choice changed since"]
    raise GateError(f"unknown step '{step}'")


# ---------------------------------------------------------------- status

def _state(record: dict[str, Any] | None, now: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not record:
        return "todo", []
    if now is not None and record.get("hash") == now["hash"]:
        return "approved", []
    old = record.get("parts", {})
    changed = [PART_WORDS.get(p, p) for p, v in (now or {}).get("parts", {}).items() if old.get(p) != v]
    return "stale", changed or ["something it was made from"]


def status(project: Project) -> dict[str, Any]:
    """Where the film is: each step's state, what blocks it, what comes next, scene by scene."""
    sb, errors = _load(project)
    prints = fingerprints(project, sb)
    approvals = load_approvals(project)
    scenes = []
    for shot in (sb or {}).get("shots", []):
        state, changed = _state(approvals["scenes"].get(shot["id"]), prints[f"scene:{shot['id']}"])
        scenes.append({"id": shot["id"], "state": state, "changed": changed,
                       "versions": len(approvals["history"].get(shot["id"], [])),
                       "blockers": [] if errors else scene_blockers(project, sb, shot),
                       "clip_bought": clip_bought(project, sb, shot) if sb and not errors else False})
    steps, open_ = [], True
    for name in STEPS:
        if name == "scenes":
            states = {s["state"] for s in scenes}
            state = "approved" if scenes and states == {"approved"} else "stale" if "stale" in states else "todo"
            changed = sorted({c for s in scenes for c in s["changed"]})
        else:
            state, changed = _state(approvals["steps"].get(name), prints.get(name))
        steps.append({"id": name, "title": TITLES[name], "state": state, "changed": changed,
                      "locked": not open_, "blockers": blockers(project, name, sb, errors) if open_ else []})
        open_ = open_ and state == "approved"
    current = next((s for s in steps if s["state"] != "approved"), None)
    return {"steps": steps, "scenes": scenes, "current": current["id"] if current else None,
            "errors": errors, "budget": budget(project, sb) if sb and not errors else None}


def require(project: Project, step: str) -> None:
    """Refuse work on a step that is still locked."""
    for s in status(project)["steps"]:
        if s["id"] == step and s["locked"]:
            before = STEPS[STEPS.index(step) - 1]
            raise GateError(f"{TITLES[step]} is locked: approve {TITLES[before]} first")


# ---------------------------------------------------------------- approving

def approve(project: Project, step: str, scene: str | None = None) -> dict[str, Any]:
    """Record that the person accepts this step (or one scene) as it is now."""
    if step not in STEPS:
        raise GateError(f"unknown step '{step}' (steps: {', '.join(STEPS)})")
    require(project, step)
    sb, errors = _load(project)
    prints = fingerprints(project, sb)
    approvals = load_approvals(project)
    if step == "scenes":
        if scene is None:
            raise GateError("approve scenes one at a time: give the scene id")
        shot = next((s for s in (sb or {}).get("shots", []) if s["id"] == scene), None)
        if shot is None:
            raise GateError(f"no scene {scene}")
        problems = errors or scene_blockers(project, sb, shot)
        if problems:
            raise GateError(f"{scene} is not ready: {'; '.join(problems)}")
        record = {**prints[f"scene:{scene}"], "at": now_iso(), "mode": shot["motion"]["mode"]}
        approvals["scenes"][scene] = record
        history = approvals["history"].setdefault(scene, [])
        if not history or history[-1]["hash"] != record["hash"]:
            history.append({**record, "shot": copy.deepcopy(shot)})
    else:
        problems = blockers(project, step, sb, errors)
        if problems:
            raise GateError(f"{TITLES[step]} is not ready: {'; '.join(problems)}")
        approvals["steps"][step] = {**prints[step], "at": now_iso()}
    save_approvals(project, approvals)
    return status(project)


def unapprove(project: Project, step: str, scene: str | None = None) -> dict[str, Any]:
    approvals = load_approvals(project)
    if step == "scenes" and scene:
        approvals["scenes"].pop(scene, None)
    else:
        approvals["steps"].pop(step, None)
    save_approvals(project, approvals)
    return status(project)


def restore(project: Project, scene: str, version: int) -> list[str]:
    """Put an earlier approved version of a scene back. Its files come back from the cache."""
    from . import revise

    require(project, "scenes")
    if not any(s["id"] == scene for s in sbmod.load(project)["shots"]):
        raise GateError(f"no scene {scene}")
    history = load_approvals(project)["history"].get(scene, [])
    if not 0 <= version < len(history):
        raise GateError(f"{scene} has no version {version + 1}")
    errors = revise.apply(project, copy.deepcopy(history[version]["shot"]))
    if not errors:
        _repoint(project, sbmod.load(project), history[version]["shot"])
    return errors


def _repoint(project: Project, sb: dict[str, Any], shot: dict[str, Any]) -> None:
    """Point each cache manifest back at the files this scene's spec already made (no calls)."""
    from .keyframes import keyframe_spec, shot_refs
    from .narration import spec_for

    sid = shot["id"]
    kf, narration = StageCache(project, "keyframes"), StageCache(project, "narration")
    refs = shot_refs(shot, _approved_sheet_files(sb, StageCache(project, "refs")))
    spec = keyframe_spec(sb, shot, sbmod.model_list(sb["models"]["image"])[0], refs)
    still = kf.hit(sid, key_for(spec), ".jpg") or kf.hit(sid, key_for(spec), ".png")
    if still:
        kf.record(sid, key_for(spec), still, spec)
    for n, line in enumerate(shot["lines"], 1):
        lspec = spec_for(sb, line)
        take = narration.hit(f"{sid}_L{n}", key_for(lspec), ".wav")
        if take:
            narration.record(f"{sid}_L{n}", key_for(lspec), take, lspec)


def _cut_inputs(project: Project, sb: dict[str, Any]) -> dict[str, Any]:
    prints = fingerprints(project, sb)
    return {"scenes": prints["scenes"]["hash"], "cut": prints["final"]["parts"]["cut"]}


def record_cut(project: Project) -> None:
    """Note what the final cut on disk was made from, so a later change shows it is out of date."""
    path = project.out(*CUT_MADE_FROM)
    path.write_text(json.dumps(_cut_inputs(project, sbmod.load(project))) + "\n", "utf-8")


# ---------------------------------------------------------------- renumbering

# Cache folders whose items are named after a scene id (S03, S03_end, S03_L1, ...).
SCENE_CACHES = ("keyframes", "narration", "narration/raw", "shots", "shots/raw", "shots/masks", "depth",
                "preview", "sketch", "assemble/segments")
SCENE_ITEM = re.compile(r"^(S\d{2})(?=$|[_#])")


def renumbered(old: dict[str, Any], new: dict[str, Any]) -> dict[str, str]:
    """Old id -> new id for every scene kept from `old` to `new`. A scene keeps its keyframe
    seed through reorders and revisions, so the seed identifies it."""
    by_seed = {s["keyframe"]["seed"]: s["id"] for s in old["shots"]}
    return {by_seed[s["keyframe"]["seed"]]: s["id"] for s in new["shots"] if s["keyframe"]["seed"] in by_seed}


def save_renumbered(project: Project, old: dict[str, Any], new: dict[str, Any]) -> None:
    """Save a storyboard whose scenes moved, and move each scene's cached files and approvals
    with it, so nothing is redrawn, re-recorded or bought again."""
    mapping = renumbered(old, new)
    sbmod.save(project, new)
    if len(mapping) == len(old["shots"]) and all(o == n for o, n in mapping.items()):
        return
    moves: list[tuple[Path, Path]] = []
    for stage in SCENE_CACHES:
        cache = StageCache(project, stage)
        kept: dict[str, Any] = {}
        for item, entry in cache.manifest.items():
            match = SCENE_ITEM.match(item)
            if not match:
                kept[item] = entry
            elif match.group(1) in mapping:
                new_item = mapping[match.group(1)] + item[3:]
                if entry.get("file", "").startswith(item):
                    new_file = new_item + entry["file"][len(item):]
                    moves.append((cache.dir / entry["file"], cache.dir / new_file))
                    entry = {**entry, "file": new_file}
                kept[new_item] = entry
        cache.manifest = kept
        cache.save()
    moves = [(src, dst) for src, dst in moves if src.exists()]
    for src, dst in moves:  # two passes, so swapping S01 and S02 never overwrites a file
        src.replace(dst.with_name("~" + dst.name))
    for _, dst in moves:
        dst.with_name("~" + dst.name).replace(dst)
    approvals = load_approvals(project)
    for key in ("scenes", "history"):
        approvals[key] = {mapping[k]: v for k, v in approvals[key].items() if k in mapping}
    for sid, versions in approvals["history"].items():
        for version in versions:
            version["shot"]["id"] = sid
    save_approvals(project, approvals)


# ---------------------------------------------------------------- money

def scene_price(sb: dict[str, Any], shot: dict[str, Any]) -> float:
    """List price of the clip this scene's mode buys (0 for free modes)."""
    motion = shot["motion"]
    if not MODES.get(motion["mode"], {}).get("paid"):
        return 0.0
    engine = VIDEO_ENGINES.get(motion.get("engine") or sb["models"]["video"], {})
    return float(engine.get("usd", {}).get(motion.get("clip_s", 5), 0.0))


def music_price(sb: dict[str, Any]) -> float:
    engine = MUSIC_ENGINES.get(sb["models"]["music"], {})
    return round(engine.get("usd_per_s", 0.0) * sb["music"].get("duration_s", 80) * len(sb["music"]["seeds"]), 3)


def budget(project: Project, sb: dict[str, Any]) -> dict[str, Any]:
    """The film's budget, what the chosen modes add up to, and what is still to buy."""
    from .costs import summarise

    spent = sum(s["usd_list"] for k, s in summarise(project).items() if k in ("shots", "music"))
    planned = sum(scene_price(sb, s) for s in sb["shots"])
    to_buy = sum(scene_price(sb, s) for s in sb["shots"] if not clip_bought(project, sb, s))
    return {"budget_usd": sb.get("video", {}).get("budget_usd", 0.6), "planned_usd": round(planned, 3),
            "to_buy_usd": round(to_buy, 3), "spent_usd": round(spent, 4), "music_usd": music_price(sb),
            "allowed_modes": allowed_modes(sb)}


def allowed_modes(sb: dict[str, Any]) -> list[str]:
    return list(sb.get("video", {}).get("allowed_modes") or MODES)


def catalog(sb: dict[str, Any] | None) -> dict[str, Any]:
    """Every motion mode and engine with its price, for the scene editor's picker."""
    engines = {name: {"provider": e["provider"], "clip_s": list(e["clip_s"]),
                      "usd": {str(k): v for k, v in e["usd"].items()}} for name, e in VIDEO_ENGINES.items()}
    default = (sb or {}).get("models", {}).get("video", "wavespeed-wan22-480p")
    modes = {name: {"label": m["label"], "paid": m["paid"], "about": m["about"],
                    "usd": VIDEO_ENGINES[default]["usd"].get(5, 0.0) if m["paid"] else 0.0}
             for name, m in MODES.items()}
    return {"modes": modes, "engines": engines, "default_engine": default, "actions": ACTIONS,
            "music_usd": music_price(sb) if sb else None}


# ---------------------------------------------------------------- command line

ICONS = {"approved": "ok", "stale": "STALE", "todo": "todo"}


def print_status(project: Project) -> None:
    st = status(project)
    for s in st["steps"]:
        mark = "locked" if s["locked"] else ICONS[s["state"]]
        note = ("; changed: " + ", ".join(s["changed"])) if s["changed"] else ""
        todo = ("; to do: " + "; ".join(s["blockers"])) if s["blockers"] and s["state"] != "approved" else ""
        print(f"  {STEPS.index(s['id']) + 1}. {s['title']:11} {mark:7}{note}{todo}")
    if st["scenes"] and not st["steps"][4]["locked"]:
        print("     " + "  ".join(f"{s['id']} {ICONS[s['state']]}" for s in st["scenes"]))
    if st["budget"]:
        b = st["budget"]
        print(f"  budget ${b['budget_usd']:.2f}: chosen modes ${b['planned_usd']:.2f}, "
              f"still to buy ${b['to_buy_usd']:.2f}, spent so far ${b['spent_usd']:.2f}")
    print(f"  next: {TITLES[st['current']] if st['current'] else 'nothing, the film is approved'}")
