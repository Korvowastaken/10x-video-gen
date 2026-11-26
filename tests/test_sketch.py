"""The layout guide: plain deterministic frames, keys that follow only the composition,
and a keyframe that is sent the guide only when a reference slot is left."""
import json
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from pipeline import keyframes, sketch
from pipeline import storyboard as sbmod
from pipeline.cache import key_for
from pipeline.config import ROOT, Project
from pipeline.keyframes import KEYFRAME_SIZE, MAX_REFERENCES, keyframe_spec

FILM = ROOT / "tests" / "fixtures" / "film"  # a sample film to test against, so the real project can be empty

PROJECT = Project(FILM)


def _sb():
    return json.loads(PROJECT.storyboard.read_text("utf-8"))


def _people(sb, n=1):
    return next(s for s in sb["shots"] if len(s["characters"]) >= n and s["size"] != "insert")


def _rgb(colour):
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def _figure_rows(img):
    """How many pixel rows the figure outlines span: how tall a lone figure is drawn."""
    diff = ImageChops.difference(img, Image.new("RGB", img.size, _rgb(sketch.INK))).convert("L")
    box = diff.point(lambda v: 255 if v < 4 else 0).getbbox()
    return box[3] - box[1]


def test_guide_has_the_keyframe_shape():
    assert sketch.W * KEYFRAME_SIZE[1] == sketch.H * KEYFRAME_SIZE[0]


def test_render_is_deterministic():
    for shot in _sb()["shots"]:
        spec = sketch.layout_spec(shot)
        if spec:
            assert sketch._png(sketch.render(spec)) == sketch._png(sketch.render(json.loads(json.dumps(spec))))


def test_guide_is_outlines_on_white():
    """No colour or filled shape for the model to copy into the scene."""
    img = sketch.render(sketch.layout_spec(_people(_sb(), 2)))
    colours = img.getcolors(1 << 20)
    assert {rgb for _, rgb in colours} <= {_rgb(sketch.PAPER), _rgb(sketch.HORIZON_INK), _rgb(sketch.INK)}
    assert max(colours)[1] == _rgb(sketch.PAPER)


def test_close_up_figure_is_taller_than_wide():
    assert sketch.figure_height("close-up") > sketch.figure_height("medium") > sketch.figure_height("wide")
    shot = _people(_sb())
    heights = {}
    for size in ("wide", "close-up"):
        shot["size"] = size
        heights[size] = _figure_rows(sketch.render(sketch.layout_spec(shot)))
    assert heights["close-up"] > 1.5 * heights["wide"]


def test_words_do_not_change_the_guide():
    shot = _people(_sb())
    before = key_for(sketch.layout_spec(shot))
    shot["beat"] += " Later."
    shot["keyframe"]["prompt"] += " At dusk."
    for line in shot["lines"]:
        line["en"] += " Really."
    assert key_for(sketch.layout_spec(shot)) == before
    shot["size"] = "wide" if shot["size"] != "wide" else "medium"
    assert key_for(sketch.layout_spec(shot)) != before


def test_insert_and_empty_scenes_get_no_guide():
    sb = _sb()
    insert = next(s for s in sb["shots"] if s["size"] == "insert")
    assert insert["characters"], "the test wants an insert shot that lists characters"
    assert sketch.layout_spec(insert) is None
    empty = dict(_people(sb), characters=[])
    assert sketch.layout_spec(empty) is None


@pytest.mark.parametrize("size", ["extreme-wide", "medium-close-up", "extreme-close-up", "over-the-shoulder"])
def test_every_size_renders(size):
    shot = _people(_sb(), 2)
    shot["size"] = size
    assert sketch.render(sketch.layout_spec(shot)).size == (sketch.W, sketch.H)


def test_people_in_a_group_turn_toward_each_other():
    sb = _sb()
    pair = _people(sb, 2)
    assert [f["facing"] for f in sketch.layout_spec(pair)["figures"]] == ["right", "left"]
    alone = next(s for s in sb["shots"] if len(s["characters"]) == 1 and s["size"] != "insert")
    assert sketch.layout_spec(alone)["figures"][0]["facing"] == "front"
    pair["size"] = "over-the-shoulder"
    assert [f["facing"] for f in sketch.layout_spec(pair)["figures"]] == ["right", "left"]


def test_turning_a_figure_changes_the_guide():
    shot = _people(_sb(), 2)
    spec = sketch.layout_spec(shot)
    turned = json.loads(json.dumps(spec))
    turned["figures"][0]["facing"] = "front"
    assert sketch._png(sketch.render(spec)) != sketch._png(sketch.render(turned))


def test_layout_file_is_drawn_once_then_cached(tmp_path):
    project = Project(tmp_path)
    shot = _people(_sb())
    first = sketch.layout_file(project, shot)
    assert first.exists() and Image.open(first).size == (sketch.W, sketch.H)
    stamp = first.stat().st_mtime_ns
    assert sketch.layout_file(project, shot) == first and first.stat().st_mtime_ns == stamp


def test_keyframe_takes_the_guide_only_when_a_slot_is_left():
    sb = _sb()
    shot = _people(sb)
    model = sbmod.model_list(sb["models"]["image"])[0]
    sheet = ROOT / "tests" / "fixtures" / "film" / "storyboard.json"  # any file: only its hash goes in the spec
    roomy = keyframe_spec(sb, shot, model, [sheet])
    assert roomy["layout"] == key_for(sketch.layout_spec(shot))
    full = keyframe_spec(sb, shot, model, [sheet] * MAX_REFERENCES)
    assert "layout" not in full


def test_keyframe_without_people_keeps_its_old_key():
    """Scenes with nobody in them were drawn without a guide, and still are: no redraw."""
    sb = _sb()
    shot = next(s for s in sb["shots"] if sketch.layout_spec(s) is None)
    model = sbmod.model_list(sb["models"]["image"])[0]
    assert "layout" not in keyframe_spec(sb, shot, model, [])


def test_the_guide_is_sent_last_with_its_note(tmp_path, monkeypatch):
    sent = {}

    def fake(project, *, references, prompt, **_):
        sent.update(refs=list(references), prompt=prompt)
        return b"jpg", ".jpg"

    monkeypatch.setattr(keyframes.cloudflare, "generate_image", fake)
    monkeypatch.setattr(keyframes.keys, "slots", lambda service: [1])
    sheet, guide = tmp_path / "sheet.jpg", tmp_path / "guide.png"
    keyframes._generate(Project(tmp_path), item="S01", models=["@cf/black-forest-labs/flux-2-klein-4b"],
                        prompt="A kitchen.", seed=1, size=KEYFRAME_SIZE, references=[sheet], layout=guide)
    assert sent["refs"] == [sheet, guide]
    assert sent["prompt"].endswith(keyframes.LAYOUT_NOTE)


def test_the_fallback_model_gets_no_guide(tmp_path, monkeypatch):
    sent = {}

    def fake(project, *, references, prompt, **_):
        sent.update(refs=list(references), prompt=prompt)
        return b"jpg", ".jpg"

    monkeypatch.setattr(keyframes.cloudflare, "generate_image", fake)
    monkeypatch.setattr(keyframes.keys, "slots", lambda service: [1])
    keyframes._generate(Project(tmp_path), item="S01", models=["@cf/black-forest-labs/flux-1-schnell"],
                        prompt="A kitchen.", seed=1, size=KEYFRAME_SIZE, references=[Path("a.jpg")],
                        layout=Path("guide.png"))
    assert sent["refs"] == [] and keyframes.LAYOUT_NOTE not in sent["prompt"]


def test_renumbering_moves_the_guide_with_its_scene():
    from pipeline.flow import SCENE_CACHES, SCENE_ITEM
    assert "sketch" in SCENE_CACHES and SCENE_ITEM.match("S03_layout")


def test_no_sketch_command_left():
    assert '"sketch"' not in (ROOT / "pipeline" / "__main__.py").read_text("utf-8")
