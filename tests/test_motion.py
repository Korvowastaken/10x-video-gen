"""Motion modes: the contract, the engine rules and the local motion maths."""
import copy
import json

import numpy as np

from pipeline import storyboard as sbmod
from pipeline.config import ROOT, Project
from pipeline.engines import MODES, STRETCH_CAP, stretch_cap
from pipeline.motion import mask_image, retime_plan

PROJECT = Project(ROOT)


def _sb():
    return json.loads(PROJECT.storyboard.read_text("utf-8"))


def _shot(sb, mode):
    return next(s for s in sb["shots"] if s["motion"]["mode"] == mode)


def test_flf_inbetween_needs_an_end_keyframe():
    sb = _sb()
    shot = _shot(sb, "flf_inbetween")
    del shot["motion"]["end_keyframe"]
    assert any("'end_keyframe' is a required property" in e for e in sbmod.schema_errors(sb))


def test_masked_modes_need_a_mask():
    sb = _sb()
    shot = _shot(sb, "masked_i2v")
    del shot["motion"]["mask"]
    assert any("'mask' is a required property" in e for e in sbmod.schema_errors(sb))


def test_in_between_needs_an_engine_with_last_image():
    sb = _sb()
    _shot(sb, "flf_inbetween")["motion"]["engine"] = "kaggle-wan22-ti2v-5b"
    assert any("no last_image" in e for e in sbmod.motion_errors(sb))


def test_retired_mode_names_get_a_hint():
    sb = _sb()
    sb_old = copy.deepcopy(sb)
    sb_old["shots"][0]["motion"]["mode"] = "video"
    assert sbmod.schema_errors(sb_old)  # the schema no longer accepts it
    assert any("use 'full_i2v'" in e for e in sbmod.motion_errors(sb_old))


def test_balanced_plan_stays_within_the_paid_clip_limit():
    sb = _sb()
    paid = sbmod.paid_clips(sb)
    assert len(paid) <= sb["video"]["max_paid_clips"]
    assert all(MODES[s["motion"]["mode"]]["paid"] for s in paid)


def test_stretch_caps_follow_the_subject():
    sb = _sb()
    assert stretch_cap(_shot(sb, "flf_inbetween")) == STRETCH_CAP["character"] == 1.25
    assert stretch_cap(_shot(sb, "cinemagraph")) == STRETCH_CAP["ambient"] == 1.6


def test_retime_plan_16_to_24_fps_with_stretch():
    plan = retime_plan(81, 16.0, 24.0, 1.25)
    assert len(plan) == round(81 / 16 * 1.25 * 24)
    assert plan[0] == (0, 0.0)
    assert all(0 <= i < 81 and 0 <= frac < 1 for i, frac in plan)
    assert [i for i, _ in plan] == sorted(i for i, _ in plan)  # never goes backwards


def test_mask_is_soft_inside_its_region_only():
    alpha = mask_image([{"shape": "ellipse", "x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}], (200, 400), feather=0.01)
    assert alpha.shape == (400, 200)
    assert alpha[200, 100] > 0.95  # centre of the ellipse
    assert alpha[5, 5] < 0.01      # far corner stays still
    assert 0.05 < float(np.mean(alpha)) < 0.35
