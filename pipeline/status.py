"""`make status`: what is cached and what a run would regenerate; `make prune`."""
from __future__ import annotations

from . import storyboard as sbmod
from .cache import StageCache, key_for, sha256_file
from .config import Project
from .engines import MODES
from .narration import line_file, line_items

STAGE_DIRS = ("refs", "keyframes", "narration", "narration/raw", "music", "shots", "shots/raw", "shots/masks",
              "depth", "assemble/segments")
KEEP = {"manifest.json", "contact_sheet.jpg", "timing.json"}


def run(project: Project) -> None:
    from .shots import clip_spec

    sb = sbmod.load_valid(project)
    narration = StageCache(project, "narration")
    keyframes = StageCache(project, "keyframes")
    raw = StageCache(project, "shots/raw")
    depth = StageCache(project, "depth")
    lines_by_shot: dict[str, list[bool]] = {}
    for item, shot, line in line_items(sb):
        ok = line_file(narration, item, sb, line) is not None
        lines_by_shot.setdefault(shot["id"], []).append(ok)
    print(f"{'shot':5} {'mode':15} {'keyframe':9} {'lines':10} {'clip':12} depth")
    for shot in sb["shots"]:
        sid, mode = shot["id"], shot["motion"]["mode"]
        kf = keyframes.current(sid)
        spoken = lines_by_shot.get(sid, [])
        lines = f"{sum(spoken)}/{len(spoken)}" if spoken else "silent"
        clip = "-"
        if MODES[mode]["paid"]:
            end = keyframes.current(f"{sid}_end") if mode == "flf_inbetween" else None
            ready = kf is not None and (mode != "flf_inbetween" or end is not None)
            clip = "cached" if ready and raw.hit(sid, key_for(clip_spec(sb, shot, kf, end)), ".mp4") else "to buy"
        has_depth = bool(kf and (depth.entry(sid) or {}).get("spec", {}).get("keyframe") == sha256_file(kf))
        print(f"{sid:5} {mode:15} {'ok' if kf else 'missing':9} {lines:10} {clip:12} {'ok' if has_depth else '-'}")
    print(f"paid shots: {len(sbmod.paid_clips(sb))} (limit {sb.get('video', {}).get('max_paid_clips', 7)} a run); "
          "'to buy' shots fall back to parallax or a pan until bought")


def prune(project: Project) -> None:
    removed = 0
    for stage in STAGE_DIRS:
        cache = StageCache(project, stage)
        keep = cache.referenced_files() | KEEP
        for path in cache.dir.iterdir():
            if path.is_file() and path.name not in keep:
                path.unlink()
                removed += 1
    print(f"prune: removed {removed} unreferenced file(s)")
