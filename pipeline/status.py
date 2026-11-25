"""`make status`: what is cached and what a run would regenerate; `make prune`."""
from __future__ import annotations

from . import storyboard as sbmod
from .cache import StageCache, key_for
from .config import Project
from .narration import line_items, spec_for

STAGE_DIRS = ("refs", "keyframes", "narration", "narration/raw", "music", "shots", "assemble/segments")
KEEP = {"manifest.json", "contact_sheet.jpg", "timing.json"}


def run(project: Project) -> None:
    sb = sbmod.load_valid(project)
    narration = StageCache(project, "narration")
    keyframes = StageCache(project, "keyframes")
    shots = StageCache(project, "shots")
    print(f"{'shot':5} {'keyframe':10} {'lines':12} {'clip':8} motion")
    lines_by_shot: dict[str, list[bool]] = {}
    for item, shot, line in line_items(sb):
        ok = narration.hit(item, key_for(spec_for(sb, line)), ".wav") is not None
        lines_by_shot.setdefault(shot["id"], []).append(ok)
    for shot in sb["shots"]:
        kf = "cached" if keyframes.current(shot["id"]) else "missing"
        spoken = lines_by_shot.get(shot["id"], [])
        lines = f"{sum(spoken)}/{len(spoken)} cached" if spoken else "silent"
        clip = "-" if shot["motion"]["mode"] != "video" else ("cached" if shots.current(shot["id"]) else "missing")
        print(f"{shot['id']:5} {kf:10} {lines:12} {clip:8} {shot['motion']['mode']}")
    print("(a keyframe or clip marked cached may still regenerate if its prompt, seed or references changed;"
          " `make film` only redoes those)")


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
