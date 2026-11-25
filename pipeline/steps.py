"""The work behind each of the six steps, gated by flow.py.

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
from .config import Project


def draft_script(project: Project, *, force: bool = False) -> None:
    flow.require(project, "script")
    from . import script
    script.run(project, force=force)


def make_sketch(project: Project, *, force: bool = False) -> dict[str, Any]:
    flow.require(project, "sketch")
    from . import sketch
    return sketch.run(project, force=force)


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


def make_cut(project: Project) -> dict[str, Any]:
    flow.require(project, "final")
    from . import assemble
    report = assemble.run(project, mode="final")
    flow.record_cut(project)
    return report


def run(args: argparse.Namespace, project: Project) -> int:
    """`python -m pipeline flow | approve | unapprove | sketch | references | scene | revise | cut`."""
    command = args.command
    if command == "approve":
        flow.approve(project, args.step, args.scene)
        print(f"approved {args.step}{' ' + args.scene if args.scene else ''}")
    elif command == "unapprove":
        flow.unapprove(project, args.step, args.scene)
    elif command == "sketch":
        make_sketch(project, force=args.force)
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
