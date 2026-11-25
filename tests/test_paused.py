"""Pausing a service on the Connections page: chains skip it, its keys stay."""

from __future__ import annotations

import os

import pytest

from pipeline import keys, paused
from pipeline.providers import route


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(keys.config, "ROOT", tmp_path)
    monkeypatch.delenv(paused.VAR, raising=False)
    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(name, "k-" + name)
    yield tmp_path
    os.environ.pop(paused.VAR, None)  # set by the code under test, outside monkeypatch


def test_pause_keeps_keys_and_writes_env(env):
    paused.set_paused("anthropic", True)
    assert paused.is_paused("anthropic")
    assert keys.slots("anthropic")  # the key is still there
    assert "STUDIO_PAUSED=anthropic" in (env / ".env").read_text("utf-8")
    paused.set_paused("anthropic", False)
    assert not paused.is_paused("anthropic")
    assert "STUDIO_PAUSED" not in (env / ".env").read_text("utf-8")


def test_only_services_with_a_fallback_can_pause(env):
    with pytest.raises(ValueError):
        paused.set_paused("cloudflare", True)


def test_chain_skips_a_paused_service(env, monkeypatch):
    seen = []
    monkeypatch.setattr(route, "provider_of", lambda m: m.split("/")[0])
    paused.set_paused("anthropic", True)
    result, model = route._chain(["anthropic/haiku", "gemini/flash"], lambda m: seen.append(m) or m, "test")
    assert model == "gemini/flash" and seen == ["gemini/flash"]
