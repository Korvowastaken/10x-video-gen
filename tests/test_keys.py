"""Several keys per service: saved to .env, masked, and switched when one runs out."""
import json
from datetime import datetime, timezone

import pytest

from pipeline import config, keys, retry
from pipeline.config import Project
from pipeline.limits import NEURONS_PER_STILL, free_limits


@pytest.fixture(autouse=True)
def clean(no_keys):
    """No real key leaks in, and .env is a scratch file (tests/conftest.py)."""


def test_save_adds_numbered_slots_and_keeps_other_lines(tmp_path):
    (tmp_path / ".env").write_text("# my notes\nFFMPEG_BIN=/x/ffmpeg\n", "utf-8")
    assert keys.save("gemini", {"GEMINI_API_KEY": "first-key-1111"}) == 1
    assert keys.save("gemini", {"GEMINI_API_KEY": "second-key-2222"}) == 2
    text = (tmp_path / ".env").read_text("utf-8")
    assert "# my notes" in text and "FFMPEG_BIN=/x/ffmpeg" in text
    assert "GEMINI_API_KEY=first-key-1111" in text and "GEMINI_API_KEY_2=second-key-2222" in text
    listed = next(s for s in keys.describe() if s["id"] == "gemini")["keys"]
    assert [k["masked"]["GEMINI_API_KEY"] for k in listed] == ["…1111", "…2222"]
    assert "first-key-1111" not in json.dumps(keys.describe())


def test_duplicate_and_half_filled_keys_are_refused():
    keys.save("gemini", {"GEMINI_API_KEY": "abc12345"})
    with pytest.raises(ValueError, match="already saved"):
        keys.save("gemini", {"GEMINI_API_KEY": "abc12345"})
    with pytest.raises(ValueError, match="API token"):
        keys.save("cloudflare", {"CLOUDFLARE_ACCOUNT_ID": "acct"})


def test_switch_moves_on_until_every_key_is_out():
    keys.save("gemini", {"GEMINI_API_KEY": "one-aaaa"})
    keys.save("gemini", {"GEMINI_API_KEY": "two-bbbb"})
    assert config.env("GEMINI_API_KEY") == "one-aaaa"
    assert keys.switch("gemini", "flash") == 2
    assert config.env("GEMINI_API_KEY") == "two-bbbb"
    assert keys.switch("gemini", "flash") is None  # both out for this model
    assert keys.switch("gemini", "lite") == 1  # another model's limit is separate


def test_remove_frees_the_slot_and_falls_back_to_the_next_key():
    keys.save("gemini", {"GEMINI_API_KEY": "one-aaaa"})
    keys.save("gemini", {"GEMINI_API_KEY": "two-bbbb"})
    keys.remove("gemini", 1)
    assert keys.slots("gemini") == [2]
    assert config.env("GEMINI_API_KEY") == "two-bbbb"


def test_a_key_switch_retries_without_using_up_attempts():
    calls = []

    def fn(attempt):
        calls.append(attempt)
        if len(calls) < 3:
            raise retry.KeySwitched("switched")
        return "ok"

    assert retry.with_retries(fn, attempts=1) == "ok"
    assert calls == [1, 1, 1]


def test_pictures_left_adds_up_across_accounts(tmp_path):
    keys.save("cloudflare", {"CLOUDFLARE_ACCOUNT_ID": "a1", "CLOUDFLARE_API_TOKEN": "t1"})
    keys.save("cloudflare", {"CLOUDFLARE_ACCOUNT_ID": "a2", "CLOUDFLARE_API_TOKEN": "t2"})
    first = keys.fingerprint("cloudflare", 1)
    rows = [{"ts": "2026-11-25T10:00:00+00:00", "provider": "cloudflare", "status": "error", "key": first,
             "error": "QuotaExhausted: Cloudflare daily neuron allowance used up"}]
    (tmp_path / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), "utf-8")
    pictures = free_limits(Project(tmp_path), {}, datetime(2026, 11, 25, 17, tzinfo=timezone.utc))["pictures"]
    assert pictures["keys"][first]["used_up"] is True
    assert pictures["used_up"] is False
    assert pictures["left"] == 10_000 // NEURONS_PER_STILL
