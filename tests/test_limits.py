"""Free tiers: used up only when every fallback ran out since the last reset."""
import json
from datetime import datetime, timezone

import pytest

from pipeline.config import Project
from pipeline.limits import CLOUDFLARE_NEURONS_A_DAY, NEURONS_PER_STILL, free_limits

NOW = datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc)  # 09:00 in California
MODELS = {"script": ["a", "b"], "tts": ["t"]}


@pytest.fixture(autouse=True)
def clean(no_keys):
    """The real keys in .env must not decide which rows count (tests/conftest.py)."""


def _project(tmp_path, rows):
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    return Project(tmp_path)


def _gemini(model, ts, ok):
    row = {"ts": ts, "provider": "gemini", "model": model, "status": "ok" if ok else "error"}
    if not ok:
        row["error"] = "QuotaExhausted: Gemini daily quota used up"
    return row


def test_writing_is_used_up_only_when_every_model_ran_out(tmp_path):
    one = _project(tmp_path, [_gemini("a", "2026-11-25T16:00:00+00:00", False)])
    assert free_limits(one, MODELS, NOW)["writing"]["used_up"] is False
    both = _project(tmp_path, [_gemini("a", "2026-11-25T16:00:00+00:00", False),
                               _gemini("b", "2026-11-25T16:05:00+00:00", False)])
    limits = free_limits(both, MODELS, NOW)
    assert limits["writing"]["used_up"] is True
    assert limits["writing"]["resets_at"] == "2026-11-26T08:00:00+00:00"  # midnight Pacific


def test_quota_from_before_the_reset_does_not_count(tmp_path):
    project = _project(tmp_path, [_gemini("a", "2026-11-25T07:00:00+00:00", False),
                                  _gemini("b", "2026-11-25T07:00:00+00:00", False)])
    assert free_limits(project, MODELS, NOW)["writing"]["used_up"] is False


def test_a_later_success_means_quota_is_back(tmp_path):
    project = _project(tmp_path, [_gemini("t", "2026-11-25T16:00:00+00:00", False),
                                  _gemini("t", "2026-11-25T16:30:00+00:00", True)])
    assert free_limits(project, MODELS, NOW)["voices"]["used_up"] is False


def test_pictures_left_counts_todays_neurons(tmp_path):
    used = 4 * NEURONS_PER_STILL
    project = _project(tmp_path, [
        {"ts": "2026-11-25T10:00:00+00:00", "provider": "cloudflare", "status": "ok", "cost": {"neurons": used}},
        {"ts": "2026-11-24T23:00:00+00:00", "provider": "cloudflare", "status": "ok", "cost": {"neurons": 9000}},
    ])
    pictures = free_limits(project, MODELS, NOW)["pictures"]
    assert pictures["left"] == (CLOUDFLARE_NEURONS_A_DAY - used) // NEURONS_PER_STILL
    assert pictures["resets_at"] == "2026-11-26T00:00:00+00:00"
