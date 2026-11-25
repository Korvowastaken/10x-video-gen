"""Revise one scene from a person's feedback.

Gemini gets the story, the film's cast and style, the scene as it stands and
the feedback, and returns the scene rewritten. The proposal is validated
against the whole storyboard (schema, script, engines, consent) before anyone
sees it, and nothing is saved until it is accepted. Ids, speakers' ids and
seeds stay as they were, so caching still regenerates only this scene.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from . import storyboard as sbmod
from .config import Project
from .providers import gemini

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


def propose(project: Project, shot_id: str, feedback: str) -> dict[str, Any]:
    sb = sbmod.load(project)
    shot = next(s for s in sb["shots"] if s["id"] == shot_id)
    story = project.story.read_text("utf-8") if project.story.exists() else ""
    text, used = gemini.generate_text(project, stage="studio", item=f"{shot_id}-revise", json_mode=True,
                                      model=sbmod.model_list(sb["models"]["script"]), temperature=0.5,
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
