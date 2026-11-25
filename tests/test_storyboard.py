"""The contract: the committed storyboard validates, and broken ones fail loudly."""
import copy
import json

import pytest

from pipeline import storyboard as sbmod
from pipeline.config import ROOT, Project

FILM = ROOT / "tests" / "fixtures" / "film"  # a sample film to test against, so the real project can be empty

PROJECT = Project(FILM)


@pytest.fixture()
def sb():
    return json.loads(PROJECT.storyboard.read_text("utf-8"))


def test_committed_storyboard_is_valid(sb):
    assert sbmod.schema_errors(sb) == []
    assert sbmod.rule_errors(sb, PROJECT) == []


def test_shot_count_is_eight_to_twelve(sb):
    broken = copy.deepcopy(sb)
    broken["shots"] = broken["shots"][:7]
    assert any("should be non-empty" in e or "too short" in e for e in sbmod.schema_errors(broken))


def test_every_shot_needs_a_reason(sb):
    broken = copy.deepcopy(sb)
    del broken["shots"][0]["reason"]
    assert any("'reason' is a required property" in e for e in sbmod.schema_errors(broken))


def test_unknown_speaker_is_caught(sb):
    broken = copy.deepcopy(sb)
    shot = next(s for s in broken["shots"] if s["lines"])
    shot["lines"][0]["speaker"] = "nobody"
    assert any("unknown speaker 'nobody'" in e for e in sbmod.rule_errors(broken))


def test_wrong_script_is_caught(sb):
    """A model once put Burmese letters inside an Amharic word (FAILURES.md F5)."""
    broken = copy.deepcopy(sb)
    shot = next(s for s in broken["shots"] if s["lines"])
    shot["lines"][0]["text"] = "የቅቤ ማိုးዋንና"
    assert any("outside Ge'ez script" in e for e in sbmod.rule_errors(broken))


def test_real_person_without_consent_record_is_blocked(sb, tmp_path):
    broken = copy.deepcopy(sb)
    person = next(c for c in broken["characters"] if c["visible"])
    person["real_person"] = True
    person["consent"] = "C99"
    (tmp_path / "ETHICS.md").write_text("| ID | Person |\n|---|---|\n| C1 | someone |\n", "utf-8")
    errors = sbmod.rule_errors(broken, Project(tmp_path))
    assert any("consent 'C99' is not confirmed" in e for e in errors)


def test_prompt_composition_repeats_the_style_and_looks(sb):
    shot = next(s for s in sb["shots"] if s["characters"])
    prompt = sbmod.image_prompt(sb, shot)
    assert sb["style"]["block"][:40] in prompt
    for cid in shot["characters"]:
        assert sbmod.characters(sb)[cid]["look"][:30] in prompt
    assert "No text" in prompt
