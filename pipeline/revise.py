"""Revise one scene from a person's feedback.

The writing model gets the story, the film's cast and style, the scene as it stands and
the feedback, and returns the scene rewritten. The proposal is validated
against the whole storyboard (schema, script, engines, consent) before anyone
sees it, and nothing is saved until it is accepted. Ids, speakers' ids and
seeds stay as they were, so caching still regenerates only this scene.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from . import catalog
from . import storyboard as sbmod
from .config import Project
from .providers import route

SYSTEM = ("You are the writer and storyboard artist of a tiny animation studio. You revise one scene of a "
          "short film at a time, changing only what the feedback asks for. You answer with JSON only.")


def _prompt(sb: dict[str, Any], shot: dict[str, Any], feedback: str, story: str) -> str:
    cast = [{k: c.get(k) for k in ("id", "name", "visible", "look")} for c in sb["characters"]]
    places = [{k: p[k] for k in ("id", "name", "look")} for p in sb["locations"]]
    return f"""The family story:
\"\"\"{story}\"\"\"

Film: "{sb['title']}". Spoken language: {sb['language']['name']} ({sb['language'].get('script', '')}).
Cast: {json.dumps(cast, ensure_ascii=False)}
Places: {json.dumps(places, ensure_ascii=False)}

The scene now:
{json.dumps(shot, ensure_ascii=False, indent=2)}

Feedback on this scene from the person making the film:
\"\"\"{feedback}\"\"\"

Rewrite the scene to answer the feedback and change nothing else. Rules:
- Keep "id", every "seed", and only use speaker, character and location ids from the lists above.
- Spoken lines ("text") stay in {sb['language']['name']}, written only in its own script, short and natural to say;
  "en" is a faithful English subtitle of at most 70 characters.
- keyframe.prompt describes only this frame (action, expression, props, angle, light), never text in the image.
- motion.prompt describes only motion and camera. motion.mode is one of full_i2v, flf_inbetween, masked_i2v,
  cinemagraph, parallax, still_kenburns, still; masked modes need mask.target, flf_inbetween needs end_keyframe.
- Return the whole scene as one JSON object in exactly the same shape."""


def writers(project: Project, sb: dict[str, Any]) -> list[str]:
    """The Revisions picker's chain; until it is set, the lines writer first, then the storyboard's."""
    return sbmod.model_list(catalog.chain(project, "revise", sb))


def propose(project: Project, shot_id: str, feedback: str) -> dict[str, Any]:
    sb = sbmod.load(project)
    shot = next(s for s in sb["shots"] if s["id"] == shot_id)
    story = project.story.read_text("utf-8") if project.story.exists() else ""
    text, used = route.generate_text(project, stage="studio", item=f"{shot_id}-revise", json_mode=True,
                                     models=writers(project, sb), temperature=0.5,
                                     system=SYSTEM, prompt=_prompt(sb, shot, feedback, story))
    proposal = json.loads(text)
    if isinstance(proposal, list):
        proposal = proposal[0]
    proposal = merge(shot, proposal)
    return {"proposal": proposal, "errors": check(project, sb, proposal), "model": used}


def merge(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Take the model's scene but keep the fields it must not touch."""
    out = copy.deepcopy(new)
    out["id"] = old["id"]
    out.setdefault("keyframe", {})["seed"] = old["keyframe"]["seed"]
    out.setdefault("motion", {})
    if "seed" in old["motion"]:
        out["motion"]["seed"] = old["motion"]["seed"]
    if out["motion"].get("end_keyframe") is not None:
        out["motion"]["end_keyframe"].setdefault("seed", old["motion"].get("end_keyframe", {}).get(
            "seed", old["keyframe"]["seed"] + 1))
    return out


def check(project: Project, sb: dict[str, Any], shot: dict[str, Any]) -> list[str]:
    """Errors the storyboard would have with this scene in place."""
    trial = copy.deepcopy(sb)
    trial["shots"] = [shot if s["id"] == shot["id"] else s for s in trial["shots"]]
    return sbmod.schema_errors(trial) or sbmod.rule_errors(trial, project)


def apply(project: Project, shot: dict[str, Any]) -> list[str]:
    sb = sbmod.load(project)
    errors = check(project, sb, shot)
    if not errors:
        sb["shots"] = [shot if s["id"] == shot["id"] else s for s in sb["shots"]]
        sbmod.save(project, sb)
    return errors


# ---------------------------------------------------------------- the whole script

SCRIPT_FIELDS = ("beat", "reason", "size", "location", "characters", "duration_s", "lines")


def _script_prompt(sb: dict[str, Any], feedback: str, story: str) -> str:
    scenes = [{"id": s["id"], **{k: s[k] for k in SCRIPT_FIELDS}, "picture": s["keyframe"]["prompt"]}
              for s in sb["shots"]]
    cast = [{k: c.get(k) for k in ("id", "name", "visible", "look")} for c in sb["characters"]]
    places = [{k: p[k] for k in ("id", "name", "look")} for p in sb["locations"]]
    return f"""The family story:
\"\"\"{story}\"\"\"

Film: "{sb['title']}". Spoken language: {sb['language']['name']} ({sb['language'].get('script', '')}).
Cast: {json.dumps(cast, ensure_ascii=False)}
Places: {json.dumps(places, ensure_ascii=False)}

The script now, scene by scene:
{json.dumps(scenes, ensure_ascii=False, indent=1)}

Feedback on the script from the person making the film:
\"\"\"{feedback}\"\"\"

Rewrite the script to answer the feedback and change nothing else. Rules:
- Return {{"title": "...", "scenes": [...]}} with every scene in the same shape. Keep a scene's "id" when it
  stays; a new scene gets "id": "new". Leave a scene out to cut it. The order of the list is the film's order.
- Use only character and location ids from the lists above; voice-only characters never appear on screen.
- Spoken lines ("text") stay in {sb['language']['name']}, written only in its own script, short and natural to
  say; "en" is a faithful English subtitle of at most 70 characters. A scene holds 0-2 lines.
- "picture" describes only that frame (action, expression, props, angle, light), never text in the image.
- The whole film stays between 60 and 90 seconds."""


def propose_script(project: Project, feedback: str) -> dict[str, Any]:
    """The writing model's revision of the whole script, as a full storyboard to review; nothing is saved."""
    sb = sbmod.load(project)
    story = project.story.read_text("utf-8") if project.story.exists() else ""
    text, used = route.generate_text(project, stage="studio", item="script-revise", json_mode=True,
                                     models=writers(project, sb), temperature=0.5,
                                     system=SYSTEM, prompt=_script_prompt(sb, feedback, story))
    proposal = merge_script(sb, json.loads(text))
    errors = sbmod.schema_errors(proposal) or sbmod.rule_errors(proposal, project)
    return {"proposal": proposal, "errors": errors, "model": used}


def merge_script(sb: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    """Apply a revised script to the storyboard: kept scenes keep their seeds, motion and
    pictures unless the draft rewrote them; new scenes get free motion and fresh seeds."""
    old = {s["id"]: s for s in sb["shots"]}
    shots, renamed = [], {}
    next_seed = max([s["keyframe"]["seed"] for s in sb["shots"]] + [1000]) + 10
    for n, scene in enumerate(draft.get("scenes", []), 1):
        base = copy.deepcopy(old.get(scene.get("id"))) if scene.get("id") in old else None
        if base is None:
            base = {"keyframe": {"prompt": "", "seed": next_seed},
                    "motion": {"mode": "still_kenburns", "prompt": "the camera pushes in slowly", "seed": next_seed,
                               "kenburns": "zoom-in"}}
            next_seed += 10
        base.update({k: scene[k] for k in SCRIPT_FIELDS if k in scene})
        if scene.get("picture"):
            base["keyframe"]["prompt"] = scene["picture"]
        if scene.get("id") in old:
            renamed[scene["id"]] = f"S{n:02d}"
        base["id"] = f"S{n:02d}"
        shots.append(base)
    out = copy.deepcopy(sb)
    out["title"] = draft.get("title") or sb["title"]
    out["shots"] = shots
    out["music"]["cues"] = [dict(c, at=renamed[c["at"]]) for c in sb["music"].get("cues", []) if c["at"] in renamed]
    if out.get("edit", {}).get("use"):
        out["edit"]["use"] = {renamed[k]: v for k, v in out["edit"]["use"].items() if k in renamed}
    return out


def apply_script(project: Project, proposal: dict[str, Any]) -> list[str]:
    """Save an accepted script; scenes that moved take their cached files and approvals along."""
    from . import flow

    errors = sbmod.schema_errors(proposal) or sbmod.rule_errors(proposal, project)
    if not errors:
        flow.save_renumbered(project, sbmod.load(project), proposal)
    return errors
