"""The studio marks a scene's still or voice as stale exactly when a run would remake it."""
import copy
import json

from pipeline import storyboard as sbmod
from pipeline.cache import StageCache, key_for
from pipeline.config import ROOT, Project
from pipeline.keyframes import keyframe_spec
from pipeline.narration import spec_for
from pipeline.studio import stale

FILM = ROOT / "tests" / "fixtures" / "film"  # a sample film to test against, so the real project can be empty


def _setup(tmp_path):
    project = Project(tmp_path)
    sb = json.loads((FILM / "storyboard.json").read_text("utf-8"))
    shot = next(s for s in sb["shots"] if s["lines"] and not sbmod.paid_clips({"shots": [s]}))
    model = sbmod.model_list(sb["models"]["image"])[0]
    kf, narration = StageCache(project, "keyframes"), StageCache(project, "narration")
    spec = keyframe_spec(sb, shot, model, [])
    path = kf.path(shot["id"], key_for(spec), ".jpg")
    path.write_bytes(b"jpg")
    kf.record(shot["id"], key_for(spec), path, spec)
    line_spec = spec_for(sb, shot["lines"][0])
    take = narration.path(f"{shot['id']}_L1", key_for(line_spec), ".wav")
    take.write_bytes(b"wav")
    narration.record(f"{shot['id']}_L1", key_for(line_spec), take, line_spec)
    return project, sb, shot, kf, narration


def test_fresh_scene_is_not_stale(tmp_path):
    project, sb, shot, kf, narration = _setup(tmp_path)
    result = stale(sb, shot, kf, StageCache(project, "shots/raw"), narration, {})
    assert result["keyframe"] is False
    assert result["voice"][0] is False


def test_editing_picture_and_line_marks_them_stale(tmp_path):
    project, sb, shot, kf, narration = _setup(tmp_path)
    edited = copy.deepcopy(sb)
    target = next(s for s in edited["shots"] if s["id"] == shot["id"])
    target["keyframe"]["prompt"] += " A red scarf."
    target["lines"][0]["text"] += " ።"
    result = stale(edited, target, kf, StageCache(project, "shots/raw"), narration, {})
    assert result["keyframe"] is True
    assert result["voice"][0] is True


def test_nothing_made_yet_is_missing_not_stale(tmp_path):
    project = Project(tmp_path)
    sb = json.loads((FILM / "storyboard.json").read_text("utf-8"))
    shot = sb["shots"][0]
    caches = [StageCache(project, s) for s in ("keyframes", "shots/raw", "narration")]
    result = stale(sb, shot, caches[0], caches[1], caches[2], {})
    assert result == {"keyframe": False, "voice": [False] * len(shot["lines"]), "clip": False}
