"""Steps unlock in order, approvals go stale exactly when what they cover changes."""
import copy
import json
import shutil

import pytest

from pipeline import flow, revise
from pipeline import storyboard as sbmod
from pipeline.cache import StageCache, key_for
from pipeline.config import ROOT, Project
from pipeline.keyframes import (KEYFRAME_SIZE, REFERENCE_SIZE, character_ref_prompt, keyframe_spec,
                                location_ref_prompt, ref_spec, shot_refs)
from pipeline.narration import spec_for


@pytest.fixture
def project(tmp_path):
    for name in ("story.md", "storyboard.json", "ETHICS.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    return Project(tmp_path)


def _sb(project):
    return sbmod.load(project)


def _fake(cache: StageCache, item: str, spec: dict, ext: str, data: bytes):
    path = cache.path(item, key_for(spec), ext)
    path.write_bytes(data)
    cache.record(item, key_for(spec), path, spec)
    return path


def _draw_references(project):
    """Stand-in sheets whose cache keys match the storyboard, as keyframes.references would."""
    sb, refs = _sb(project), StageCache(project, "refs")
    model = sbmod.model_list(sb["models"]["image"])[0]
    for c in sb["characters"]:
        if c["visible"]:
            prompt, photo = character_ref_prompt(project, sb, c)
            i = c["reference"].get("chosen", 0)
            _fake(refs, f"char_{c['id']}_{i}", ref_spec(prompt, c["reference"]["seeds"][i], model, REFERENCE_SIZE, photo),
                  ".jpg", c["id"].encode())
    for p in sb["locations"]:
        prompt, photo = location_ref_prompt(project, sb, p)
        _fake(refs, f"place_{p['id']}", ref_spec(prompt, p["reference"]["seeds"][0], model, KEYFRAME_SIZE, photo),
              ".jpg", p["id"].encode())


def _draw_scene(project, sid, picture=b"still"):
    sb, refs = _sb(project), StageCache(project, "refs")
    shot = next(s for s in sb["shots"] if s["id"] == sid)
    approved = flow._approved_sheet_files(sb, refs)
    spec = keyframe_spec(sb, shot, sbmod.model_list(sb["models"]["image"])[0], shot_refs(shot, approved))
    _fake(StageCache(project, "keyframes"), sid, spec, ".jpg", picture)
    for n, line in enumerate(shot["lines"], 1):
        _fake(StageCache(project, "narration"), f"{sid}_L{n}", spec_for(sb, line), ".wav", b"wav")


def _step(project, name):
    return next(s for s in flow.status(project)["steps"] if s["id"] == name)


def _open_through_references(project):
    from pipeline import sketch
    flow.approve(project, "story")
    flow.approve(project, "script")
    sketch.run(project)
    flow.approve(project, "sketch")
    _draw_references(project)
    flow.approve(project, "references")


def test_a_fresh_film_starts_at_the_story_with_everything_after_it_locked(project):
    st = flow.status(project)
    assert st["current"] == "story"
    assert [s["locked"] for s in st["steps"]] == [False, True, True, True, True, True]


def test_a_locked_step_cannot_be_approved_or_worked_on(project):
    with pytest.raises(flow.GateError, match="locked"):
        flow.approve(project, "script")
    with pytest.raises(flow.GateError, match="approve Story first"):
        flow.require(project, "script")


def test_approving_a_step_unlocks_the_next(project):
    flow.approve(project, "story")
    flow.approve(project, "script")
    sketch = _step(project, "sketch")
    assert not sketch["locked"] and sketch["state"] == "todo"
    assert sketch["blockers"], "nothing drawn yet, so the sketch cannot be approved"
    with pytest.raises(flow.GateError, match="not ready"):
        flow.approve(project, "sketch")


def test_editing_a_line_makes_the_script_and_sketch_stale_but_not_the_references(project):
    _open_through_references(project)
    sb = _sb(project)
    sb["shots"][0]["lines"][0]["en"] = "A different subtitle."
    sbmod.save(project, sb)
    st = {s["id"]: s for s in flow.status(project)["steps"]}
    assert st["script"]["state"] == "stale" and st["script"]["changed"] == ["the script"]
    assert st["sketch"]["state"] == "stale" and "the script" in st["sketch"]["changed"]
    assert st["references"]["state"] == "approved"
    assert st["references"]["locked"], "a stale step before it locks it again"


def test_editing_the_story_makes_the_script_stale_and_says_why(project):
    flow.approve(project, "story")
    flow.approve(project, "script")
    project.story.write_text(project.story.read_text("utf-8") + "\nOne more sentence.\n", "utf-8")
    st = {s["id"]: s for s in flow.status(project)["steps"]}
    assert st["story"]["state"] == "stale"
    assert st["script"]["state"] == "stale" and st["script"]["changed"] == ["the story"]


def test_reordering_scenes_reopens_the_sketch_not_the_script(project):
    flow.approve(project, "story")
    flow.approve(project, "script")
    sb = _sb(project)
    ids = [s["id"] for s in sb["shots"]]
    reordered = sbmod.reorder(sb, [ids[1], ids[0], *ids[2:]])
    assert [s["id"] for s in reordered["shots"]] == ids
    assert reordered["shots"][0]["beat"] == sb["shots"][1]["beat"]
    sbmod.save(project, reordered)
    assert _step(project, "script")["state"] == "approved"
    assert flow.key_for(flow.sketch_view(reordered)) != flow.key_for(flow.sketch_view(sb))


def test_a_scene_goes_stale_when_redrawn_and_an_old_version_can_be_restored(project):
    _open_through_references(project)
    sid = _sb(project)["shots"][0]["id"]
    _draw_scene(project, sid)
    flow.approve(project, "scenes", sid)
    scene = next(s for s in flow.status(project)["scenes"] if s["id"] == sid)
    assert scene["state"] == "approved" and scene["versions"] == 1

    sb = _sb(project)
    sb["shots"][0]["keyframe"]["prompt"] += " She holds a red scarf."
    sbmod.save(project, sb)
    _draw_scene(project, sid, picture=b"another still")
    scene = next(s for s in flow.status(project)["scenes"] if s["id"] == sid)
    assert scene["state"] == "stale" and "the picture" in scene["changed"]

    assert flow.restore(project, sid, 0) == []
    scene = next(s for s in flow.status(project)["scenes"] if s["id"] == sid)
    assert scene["state"] == "approved", "the old prompt hits the old files in the cache"


def test_a_scene_cannot_be_approved_before_its_picture_and_voice_exist(project):
    _open_through_references(project)
    sid = _sb(project)["shots"][0]["id"]
    with pytest.raises(flow.GateError, match="draw the picture"):
        flow.approve(project, "scenes", sid)


def test_fingerprints_do_not_change_when_nothing_changes(project):
    _draw_references(project)
    sb = _sb(project)
    assert flow.fingerprints(project, sb) == flow.fingerprints(project, copy.deepcopy(sb))


def test_modes_outside_the_allowed_list_and_over_budget_are_errors():
    sb = json.loads((ROOT / "storyboard.json").read_text("utf-8"))
    paid = next(s for s in sb["shots"] if sbmod.paid_clips({"shots": [s]}))
    sb["video"]["allowed_modes"] = ["parallax", "still_kenburns", "still"]
    assert any(paid["id"] in e and "not one of the allowed" in e for e in sbmod.budget_errors(sb))
    sb["video"].pop("allowed_modes")
    sb["video"]["budget_usd"] = 0.05
    assert any("over the film's budget" in e for e in sbmod.budget_errors(sb))


def test_a_revised_script_keeps_seeds_of_kept_scenes_and_numbers_scenes_in_order():
    sb = json.loads((ROOT / "storyboard.json").read_text("utf-8"))
    first, second = sb["shots"][0], sb["shots"][1]
    draft = {"scenes": [{"id": second["id"], "beat": "Now first."},
                        {"id": "new", "beat": "A new scene in the market.", "reason": "It shows the bargaining.",
                         "size": "wide", "location": first["location"], "characters": [], "duration_s": 5,
                         "lines": [], "picture": "The busy market at noon, seen from above."},
                        {"id": first["id"]}]}
    out = revise.merge_script(sb, draft)
    assert [s["id"] for s in out["shots"]] == ["S01", "S02", "S03"]
    assert out["shots"][0]["keyframe"]["seed"] == second["keyframe"]["seed"]
    assert out["shots"][0]["beat"] == "Now first."
    assert out["shots"][1]["keyframe"]["seed"] not in {s["keyframe"]["seed"] for s in sb["shots"]}
    assert out["shots"][2]["lines"] == first["lines"]


def test_reordering_moves_each_scenes_files_and_approvals_with_it(project):
    _open_through_references(project)
    sb = _sb(project)
    a, b = sb["shots"][0]["id"], sb["shots"][1]["id"]
    _draw_scene(project, a, picture=b"first")
    _draw_scene(project, b, picture=b"second")
    flow.approve(project, "scenes", a)
    flow.save_renumbered(project, sb, sbmod.reorder(sb, [b, a, *[s["id"] for s in sb["shots"][2:]]]))
    kf = StageCache(project, "keyframes")
    assert kf.current(a).read_bytes() == b"second" and kf.current(b).read_bytes() == b"first"
    scenes = {s["id"]: s for s in flow.status(project)["scenes"]}
    assert scenes[b]["state"] == "approved", "the approval followed its scene to its new number"
    assert scenes[a]["state"] == "todo"


def test_the_final_cut_needs_remaking_after_a_choice_changes(project):
    _open_through_references(project)
    sb = _sb(project)
    project.out(*flow.FILM_REPORT).write_text("{}", "utf-8")
    flow.record_cut(project)
    assert flow.blockers(project, "final", sb, []) == []
    sb.setdefault("edit", {})["grade"] = False
    sbmod.save(project, sb)
    assert "again" in flow.blockers(project, "final", _sb(project), [])[0]


def test_a_settings_typo_is_a_story_blocker_not_a_crash(project):
    project.story.write_text("---\nlanguage: [am\n---\n" + "A long enough story. " * 10, "utf-8")
    story = _step(project, "story")
    assert story["blockers"] and "typo" in story["blockers"][0]


def test_settings_round_trip_keeps_unknown_keys_and_drops_defaults():
    from pipeline.script import join_story, split_story
    text = join_story({**split_story("x")[0], "look": "painted-2d", "placeholder": True}, "The story.")
    settings, body = split_story(text)
    assert settings["look"] == "painted-2d" and settings["placeholder"] is True and body == "The story."
    assert "language" not in text
