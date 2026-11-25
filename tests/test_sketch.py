"""The shape storyboard: deterministic frames, keys that follow only what is drawn."""
import copy
import json
import shutil

import pytest
from PIL import Image, ImageChops

from pipeline import sketch
from pipeline.cache import key_for
from pipeline.config import ROOT, Project
from pipeline.media import probe_duration

PROJECT = Project(ROOT)


def _sb():
    return json.loads(PROJECT.storyboard.read_text("utf-8"))


def _keys(sb):
    return {s["id"]: key_for(sketch.frame_spec(sb, s)) for s in sb["shots"]}


def _rgb(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def _figure_rows(img, sb, shot):
    """How many pixel rows the first character's colour spans: how tall that figure is drawn."""
    colour = _rgb(sketch.PALETTE[sketch.frame_spec(sb, shot)["characters"][0]["colour"]])
    diff = ImageChops.difference(img, Image.new("RGB", img.size, colour)).convert("L")
    box = diff.point(lambda v: 255 if v < 8 else 0).getbbox()
    return box[3] - box[1]


def test_render_is_deterministic():
    sb = _sb()
    for shot in sb["shots"]:
        assert sketch._png(sketch.render_frame(sb, shot)) == sketch._png(sketch.render_frame(copy.deepcopy(sb), shot))


def test_close_up_figure_is_taller_than_wide():
    assert sketch.figure_height("close-up") > sketch.figure_height("medium") > sketch.figure_height("wide")
    sb = _sb()
    shot = next(s for s in sb["shots"] if s["size"] != "insert")
    heights = {}
    for size in ("wide", "close-up"):
        shot["size"] = size
        heights[size] = _figure_rows(sketch.render_frame(sb, shot), sb, shot)
    assert heights["close-up"] > 1.5 * heights["wide"]


def test_editing_one_shot_size_changes_only_that_key():
    sb = _sb()
    before = _keys(sb)
    shot = sb["shots"][3]
    shot["size"] = "wide" if shot["size"] != "wide" else "medium"
    after = _keys(sb)
    assert [sid for sid in before if before[sid] != after[sid]] == [shot["id"]]


def test_subtitle_changes_key_but_amharic_text_does_not():
    sb = _sb()
    before = _keys(sb)
    shot = next(s for s in sb["shots"] if s["lines"])
    shot["lines"][0]["text"] += " ።"
    assert _keys(sb) == before
    shot["lines"][0]["en"] += " Really."
    after = _keys(sb)
    assert [sid for sid in before if before[sid] != after[sid]] == [shot["id"]]


def test_moving_a_figure_changes_its_frame():
    sb = _sb()
    shot = next(s for s in sb["shots"] if s["characters"] and s["size"] != "insert")
    before = sketch.render_frame(sb, shot).tobytes()
    shot["sketch"] = {"positions": {shot["characters"][0]: [0.2, 0.3]}}
    assert sketch.frame_spec(sb, shot)["characters"][0]["at"] == [0.2, 0.3]
    assert sketch.render_frame(sb, shot).tobytes() != before


def test_insert_draws_no_figures():
    sb = _sb()
    shot = next(s for s in sb["shots"] if s["size"] == "insert")
    assert shot["characters"], "the test wants an insert shot that lists characters"
    assert sketch.frame_spec(sb, shot)["characters"] == []
    drawn = {rgb for _, rgb in sketch.render_frame(sb, shot).getcolors(1 << 20)}
    assert not {_rgb(c) for c in sketch.PALETTE} & drawn


@pytest.mark.parametrize("size", ["extreme-wide", "medium-close-up", "extreme-close-up", "over-the-shoulder"])
def test_every_size_renders(size):
    sb = _sb()
    shot = next(s for s in sb["shots"] if len(s["characters"]) == 2)
    shot["size"] = size
    assert sketch.render_frame(sb, shot).size == (sketch.W, sketch.H)


def test_run_draws_frames_and_an_animatic_then_caches(tmp_path, capsys):
    for name in ("storyboard.json", "ETHICS.md"):
        shutil.copy(ROOT / name, tmp_path / name)
    project = Project(tmp_path)
    sb = json.loads(project.storyboard.read_text("utf-8"))
    total = sum(s["duration_s"] for s in sb["shots"])

    result = sketch.run(project)
    assert set(result["frames"]) == {s["id"] for s in sb["shots"]}
    assert all(p.exists() for p in result["frames"].values())
    assert (tmp_path / "outputs" / "sketch" / "contact_sheet.jpg").exists()
    assert result["seconds"] == total
    assert abs(probe_duration(result["animatic"]) - total) < 0.1
    assert sketch.frames(project, sb) == result["frames"]

    capsys.readouterr()
    sketch.run(project)
    assert f"0 frame(s) drawn, {len(sb['shots'])} cached" in capsys.readouterr().out
