"""The work behind each of the five steps, gated by flow.py.

The studio's buttons and the `python -m pipeline <step>` commands call these
same functions, so a scene made in the browser hits the same cache as one made
from the command line. Each refuses to run while its step is locked. Only
make_scene(buy=True) can spend money, and it buys at most one clip.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from . import flow
from . import storyboard as sbmod
from .cache import StageCache
from .config import Project


def draft_script(project: Project, *, force: bool = False) -> None:
    flow.require(project, "script")
    from . import script
    script.run(project, force=force)


def make_references(project: Project, *, force: bool = False) -> None:
    flow.require(project, "references")
    from . import keyframes
    sb = sbmod.load_valid(project)
    counts = {"made": 0, "cached": 0}
    keyframes.references(project, sb, force=force, counts=counts)
    print(f"  references: {counts['made']} sheet(s) drawn, {counts['cached']} cached "
          "(outputs/refs/contact_sheet.jpg)")


def make_scene(project: Project, scene: str, *, redo: set[str] | None = None, buy: bool = False) -> dict[str, Any]:
    """Draw the scene's picture, record its lines and render its preview. `redo` remakes
    parts that are already cached; `buy` lets a paid mode buy its one clip."""
    flow.require(project, "scenes")
    from . import assemble, keyframes, narration, shots
    redo = redo or set()
    only = {scene}
    keyframes.run(project, only=only, force="keyframe" in redo)
    try:
        narration.run(project, only=only, force="voice" in redo)
    except Exception as exc:  # no voice yet (quota, key): the preview plays silent
        print(f"  voice not recorded: {' '.join(str(exc).split())[:200]}")
    shots.run(project, only=only, force="clip" in redo and buy, max_paid=1 if buy else 0)
    result = assemble.preview(project, scene)
    print(f"  {scene}: preview {result['file'].relative_to(project.root).as_posix()} ({result['used']})")
    return result


PARTS = ("keyframe", "voice", "clip")


def save_edits(project: Project, scene: str, shot: dict[str, Any] | None,
               voices: dict[str, dict[str, Any] | None] | None = None) -> list[str]:
    """Save the scene panel's edits: the scene itself (line tunings included) and the
    speakers' default tunings (None clears one). Returns errors; nothing is saved on any."""
    from . import tuning
    sb = sbmod.load(project)
    if shot is not None:
        if shot.get("id") != scene:
            return ["the scene id cannot change"]
        shot = json.loads(json.dumps(shot))
        for line in shot.get("lines", []):
            if line.get("tune") is not None:
                line["tune"] = tuning.clamp(line["tune"])
        sb["shots"] = [shot if s["id"] == scene else s for s in sb["shots"]]
    cast = sbmod.characters(sb)
    for cid, tune in (voices or {}).items():
        if cid not in cast:
            return [f"no character '{cid}'"]
        cast[cid]["voice"].pop("tune", None)
        if tune and (clean := tuning.normalise(tune)):
            cast[cid]["voice"]["tune"] = clean
    errors = sbmod.schema_errors(sb) or sbmod.rule_errors(sb, project)
    if not errors:
        sbmod.save(project, sb)
    return errors


def _still(shot: dict[str, Any]) -> Any:
    end = shot["motion"].get("end_keyframe")
    return [shot["keyframe"]["prompt"], shot["keyframe"]["seed"], shot.get("characters"), shot.get("location"),
            shot.get("size"), end and end.get("prompt")]


def _words(shot: dict[str, Any]) -> Any:
    return [(line["speaker"], line["text"]) for line in shot["lines"]]


def redo_scene(project: Project, scene: str, *, parts: list[str], shot: dict[str, Any] | None = None,
               voices: dict[str, dict[str, Any] | None] | None = None, note: str = "",
               buy: bool = False) -> dict[str, Any]:
    """Redo parts of one scene from what the scene panel holds: save the hand edits, let the
    writer rewrite the chosen parts from the note, then remake them and the preview.

    A still redone with nothing new to draw from gets a new seed (a new take). A voice whose
    words did not change but whose tuning did is re-rendered from its saved take, for free."""
    flow.require(project, "scenes")
    from . import narration, revise
    parts = [p for p in PARTS if p in parts]
    before = next(s for s in sbmod.load(project)["shots"] if s["id"] == scene)
    if shot is not None or voices:
        errors = save_edits(project, scene, shot, voices)
        if errors:
            raise ValueError("The edits were not saved: " + "; ".join(errors[:3]))
        print(f"  {scene}: saved your edits")
    if voices:
        narration.run(project, listen=False, speak=False)  # the speakers' other lines follow their new tuning

    changed: list[str] = []
    if note.strip():
        print(f"Rewriting {', '.join(parts) or 'the scene'} of {scene} from your note: "
              f"\"{' '.join(note.split())[:200]}\"")
        out = revise.propose(project, scene, note.strip(), parts or None)
        if out["errors"]:
            raise ValueError(f"{out['model']}'s rewrite does not fit the film: " + "; ".join(out["errors"][:3]))
        old = next(s for s in sbmod.load(project)["shots"] if s["id"] == scene)
        revise.apply(project, out["proposal"])
        for label, get in (("picture", lambda s: s["keyframe"]["prompt"]),
                           ("lines", lambda s: [(line["text"], line["en"]) for line in s["lines"]]),
                           ("motion", lambda s: {k: v for k, v in s["motion"].items() if k != "seed"})):
            if get(old) != get(out["proposal"]):
                changed.append(label)
        print(f"  {out['model']} rewrote {', '.join(changed) or 'nothing'}")

    sb = sbmod.load(project)
    after = next(s for s in sb["shots"] if s["id"] == scene)
    redo = set(parts)
    drawn = StageCache(project, "keyframes").current(scene) is not None
    if "keyframe" in redo and drawn and _still(after) == _still(before):
        after["keyframe"]["seed"] += 1
        if after["motion"].get("end_keyframe"):
            after["motion"]["end_keyframe"]["seed"] += 1
        sbmod.save(project, sb)
        print(f"  {scene}: nothing new to draw from, so a new take of the still")
    if "voice" in redo and _words(after) == _words(before) and (
            voices or [line.get("tune") for line in after["lines"]] != [line.get("tune") for line in before["lines"]]):
        redo.discard("voice")
        print(f"  {scene}: same words, new tuning: re-rendering the saved takes (free)")
    result = make_scene(project, scene, redo=redo, buy=buy and "clip" in redo)
    return {**result, "file": str(result["file"]), "changed": changed}


def make_cut(project: Project) -> dict[str, Any]:
    flow.require(project, "final")
    from . import assemble
    report = assemble.run(project, mode="final")
    flow.record_cut(project)
    return report


def run(args: argparse.Namespace, project: Project) -> int:
    """`python -m pipeline flow | approve | unapprove | references | scene | revise | cut`."""
    command = args.command
    if command == "approve":
        flow.approve(project, args.step, args.scene)
        print(f"approved {args.step}{' ' + args.scene if args.scene else ''}")
    elif command == "unapprove":
        flow.unapprove(project, args.step, args.scene)
    elif command == "references":
        make_references(project, force=args.force)
    elif command == "scene":
        redo = {p.strip() for p in (args.redo or "").split(",") if p.strip()}
        make_scene(project, args.scene, redo=redo, buy=args.buy)
    elif command == "cut":
        make_cut(project)
    elif command == "revise":
        from . import revise
        if args.target == "script":
            flow.require(project, "script")
            result = revise.propose_script(project, args.feedback)
            shown = [{"id": s["id"], "beat": s["beat"], "lines": s["lines"]} for s in result["proposal"]["shots"]]
        else:
            flow.require(project, "scenes")
            result = revise.propose(project, args.target, args.feedback)
            shown = result["proposal"]
        print(json.dumps(shown, ensure_ascii=False, indent=2))
        if result["errors"]:
            print("problems:\n  - " + "\n  - ".join(result["errors"]))
            return 1
        if args.accept:
            errors = (revise.apply_script(project, result["proposal"]) if args.target == "script"
                      else revise.apply(project, result["proposal"]))
            print("saved" if not errors else "not saved:\n  - " + "\n  - ".join(errors))
        else:
            print("not saved: run again with --accept to keep it")
    flow.print_status(project)
    return 0
