"""Command line: `python -m pipeline <command>`.

The six steps, each approved before the next unlocks (the studio runs the same ones):
  studio     the web app for all six steps: http://127.0.0.1:8765
  flow       where the film is: each step approved, stale or locked, and what is next
  approve STEP [SCENE]    accept a step as it is now (scenes one at a time: approve scenes S03)
  unapprove STEP [SCENE]
  1 story    write story.md in plain words, then: approve story
  2 script   draft the script from the story; revise script "make the ending shorter"
  3 sketch   draw the shape storyboard and its animatic (free, local)
  4 references   draw the reference sheets (free tier); pick one with reference.chosen
  5 scene S03    draw the picture, record the voice and preview free motion; --buy buys its clip
             revise S03 "she should smile here"
  6 cut      the final cut, 9:16 and 16:9

Stages without the gates (for scripting and experiments):
  film       every stage in order -> outputs/final/*_9x16.mp4 and *_16x9.mp4
  radio      story -> narration -> radio cut (voice + placeholder music, black screen)
  rough      story -> keyframes + narration + music -> slow pans over stills
  script | keyframes | narration | music | shots | assemble   one stage
  validate   check storyboard.json against schema/ and the cross-field rules
  status     what is cached and what would regenerate
  smoke      call each provider once (add --kaggle-gpu to test a GPU job)
  costs      summarise runs.jsonl into per-stage latency, GPU time and cost
  prune      delete cached files no manifest points to
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import config
from .config import ConfigError, Project

STAGES = ("script", "keyframes", "narration", "music", "shots", "assemble")


def _only(value: str | None) -> set[str] | None:
    return {s.strip() for s in value.split(",") if s.strip()} if value else None


def run_stage(name: str, project: Project, *, only: set[str] | None = None, force: bool = False,
              mode: str = "final", max_paid: int | None = None, kaggle: bool = False) -> None:
    started = time.perf_counter()
    print(f"\n== {name} ==")
    if name == "script":
        from . import script
        script.run(project, force=force)
    elif name == "keyframes":
        from . import keyframes
        keyframes.run(project, only=only, force=force)
    elif name == "narration":
        from . import narration
        narration.run(project, only=only, force=force)
    elif name == "music":
        from . import music
        music.run(project, force=force)
    elif name == "shots":
        from . import shots
        if kaggle:
            shots.kaggle_batch(project, only=only)
        else:
            shots.run(project, only=only, force=force, max_paid=max_paid)
    elif name == "assemble":
        from . import assemble
        assemble.run(project, mode=mode)
    else:
        raise ConfigError(f"unknown stage {name}")
    print(f"== {name} done in {time.perf_counter() - started:.1f}s ==")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=str(config.ROOT),
                        help="folder holding story.md and storyboard.json (default: this repo)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("film", "radio", "rough", *STAGES):
        sp = sub.add_parser(name)
        sp.add_argument("--only", help="comma-separated shot ids, e.g. S03,S05")
        sp.add_argument("--force", action="store_true", help="ignore the cache for the selected items")
        if name == "assemble":
            sp.add_argument("--mode", choices=("final", "radio", "rough"), default="final")
        if name in ("shots", "film"):
            sp.add_argument("--max-paid", type=int, help="most paid clips this run may buy (overrides video.max_paid_clips)")
        if name == "shots":
            sp.add_argument("--kaggle", action="store_true", help="render kaggle-wan22-ti2v-5b shots in one Kaggle job")
    sub.add_parser("flow")
    for name in ("approve", "unapprove"):
        sp = sub.add_parser(name)
        sp.add_argument("step", help="story | script | sketch | references | scenes | final")
        sp.add_argument("scene", nargs="?", help="scene id, for scenes")
    sub.add_parser("sketch").add_argument("--force", action="store_true")
    sub.add_parser("references").add_argument("--force", action="store_true")
    sp = sub.add_parser("scene")
    sp.add_argument("scene", help="scene id, e.g. S03")
    sp.add_argument("--redo", help="comma-separated parts to remake: keyframe,voice,clip")
    sp.add_argument("--buy", action="store_true", help="buy this scene's clip if its mode is paid (one clip)")
    sp = sub.add_parser("revise")
    sp.add_argument("target", help="'script' or a scene id")
    sp.add_argument("feedback", help="what to change, in plain words")
    sp.add_argument("--accept", action="store_true", help="save the revision (otherwise it is only shown)")
    sub.add_parser("cut")
    sub.add_parser("validate")
    sub.add_parser("status")
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--kaggle-gpu", action="store_true", help="also run a 1-minute GPU job on Kaggle")
    sub.add_parser("costs")
    sub.add_parser("site")
    sub.add_parser("studio")
    sub.add_parser("prune")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252, which has no Ge'ez script
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    config.load_env()
    project = Project(Path(args.project).resolve())
    only = _only(getattr(args, "only", None))
    force = getattr(args, "force", False)
    max_paid = getattr(args, "max_paid", None)
    try:
        if args.command == "film":
            for stage in STAGES:
                run_stage(stage, project, only=only if stage in ("keyframes", "narration", "shots") else None,
                          force=force if stage != "script" else False, max_paid=max_paid)
        elif args.command == "radio":
            run_stage("script", project)
            run_stage("narration", project, only=only, force=force)
            run_stage("assemble", project, mode="radio")
        elif args.command == "rough":
            for stage in ("script", "keyframes", "narration", "music"):
                run_stage(stage, project, only=only if stage != "music" else None, force=False)
            run_stage("assemble", project, mode="rough")
        elif args.command in STAGES:
            run_stage(args.command, project, only=only, force=force, mode=getattr(args, "mode", "final"),
                      max_paid=max_paid, kaggle=getattr(args, "kaggle", False))
        elif args.command in ("flow", "approve", "unapprove", "sketch", "references", "scene", "revise", "cut"):
            from . import steps
            return steps.run(args, project)
        elif args.command == "validate":
            from . import storyboard
            sb = storyboard.load_valid(project)
            print(f"storyboard.json is valid: {len(sb['shots'])} shots, "
                  f"{len(sb['characters'])} character(s), language {sb['language']['name']}")
        elif args.command == "status":
            from . import status
            status.run(project)
        elif args.command == "smoke":
            from . import smoke
            return smoke.run(project, kaggle_gpu=args.kaggle_gpu)
        elif args.command == "studio":
            from . import studio
            studio.main()
        elif args.command == "site":
            from . import site
            site.run(project)
        elif args.command == "costs":
            from . import costs
            costs.run(project)
        elif args.command == "prune":
            from . import status
            status.prune(project)
    except ConfigError as exc:  # includes a locked step (flow.GateError)
        print(f"\nconfig error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
