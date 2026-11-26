"""The studio marks a scene's still or voice as stale exactly when a run would remake it."""
import copy
import json

from pipeline import storyboard as sbmod
from pipeline.cache import StageCache, key_for
from pipeline.config import ROOT, Project
from pipeline import keyframes
from pipeline.keyframes import keyframe_spec
from pipeline.narration import spec_for, take_for, tts_spec
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


def _models_reversed(sb, kind):
    edited = copy.deepcopy(sb)
    edited["models"][kind] = list(reversed(sbmod.model_list(sb["models"][kind])))
    return edited


def test_another_image_model_first_does_not_make_a_picture_stale(tmp_path):
    """Reordering the image models (or a run that fell back to the next one) is a setting,
    not a change to the scene: the studio must not ask for a redraw."""
    project, sb, shot, kf, narration = _setup(tmp_path)
    edited = _models_reversed(sb, "image")
    target = next(s for s in edited["shots"] if s["id"] == shot["id"])
    assert stale(edited, target, kf, StageCache(project, "shots/raw"), narration, {})["keyframe"] is False
    target["keyframe"]["prompt"] += " A red scarf."
    assert stale(edited, target, kf, StageCache(project, "shots/raw"), narration, {})["keyframe"] is True


def test_another_voice_model_first_does_not_make_a_line_stale(tmp_path):
    project, sb, shot, kf, narration = _setup(tmp_path)
    line, item = shot["lines"][0], f"{shot['id']}_L1"
    raw = StageCache(project, "narration/raw")
    tspec = tts_spec(sb, line)
    take = raw.path(item, key_for(tspec), ".wav")
    take.write_bytes(b"wav")
    raw.record(item, key_for(tspec), take, tspec)
    out = narration.path(item, key_for(spec_for(sb, line)), ".wav")
    narration.record(item, key_for(spec_for(sb, line)), out, {**spec_for(sb, line), "tts": tspec})  # as a run does
    edited = _models_reversed(sb, "tts")
    target = next(s for s in edited["shots"] if s["id"] == shot["id"])
    assert stale(edited, target, kf, StageCache(project, "shots/raw"), narration, {})["voice"][0] is False
    assert take_for(raw, item, edited, target["lines"][0]) == take
    target["lines"][0]["text"] += " ።"
    assert stale(edited, target, kf, StageCache(project, "shots/raw"), narration, {})["voice"][0] is True


def test_a_drawing_run_keeps_a_picture_drawn_by_another_model_unless_forced(tmp_path, monkeypatch):
    project, sb, shot, kf, _ = _setup(tmp_path)
    edited = _models_reversed(sb, "image")
    target = next(s for s in edited["shots"] if s["id"] == shot["id"])
    models = sbmod.model_list(edited["models"]["image"])
    spec = keyframe_spec(edited, target, models[0], [])
    drawn = []
    monkeypatch.setattr(keyframes, "_generate", lambda *a, **k: drawn.append(k["item"]) or (b"new", ".jpg", models[0]))
    monkeypatch.setattr(keyframes, "_inputs", lambda used, prompt, refs, layout: (prompt, refs))

    def make(force):
        return keyframes._make(project, kf, item=shot["id"], spec=spec, models=models, prompt=spec["prompt"],
                               seed=spec["seed"], size=keyframes.KEYFRAME_SIZE, references=[], force=force,
                               counts={"made": 0, "cached": 0}, free=keyframes.STILL_FREE)

    before = kf.current(shot["id"])
    assert make(force=False) == before and drawn == []
    assert make(force=True) != before and drawn == [shot["id"]]  # redrawing the scene by hand still draws it
