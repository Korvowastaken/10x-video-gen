"""Asking before a chain moves to another service: in a studio job, at a terminal, nowhere else."""
import threading
import time

import pytest

from pipeline import jobs, keyframes, keys, retry, switch
from pipeline.config import ROOT, Project
from pipeline.keyframes import KEYFRAME_SIZE, Deferred
from pipeline.providers import anthropic_api, gemini, route
from pipeline.retry import QuotaExhausted

PROJECT = Project(ROOT / "tests" / "fixtures" / "film")
FLUX2 = "@cf/black-forest-labs/flux-2-klein-4b"
KAGGLE = "kaggle-flux-2-klein-4b"


@pytest.fixture(autouse=True)
def asking(no_keys, monkeypatch):
    monkeypatch.setattr(switch, "AUTO", False)
    monkeypatch.setattr(switch, "INTERACTIVE", False)
    retry.EXHAUSTED.clear()
    yield
    retry.EXHAUSTED.clear()
    jobs.bind(None)


@pytest.fixture
def claude_out_gemini_ok(monkeypatch):
    keys.save("anthropic", {"ANTHROPIC_API_KEY": "a-key-2222"})
    keys.save("gemini", {"GEMINI_API_KEY": "g-key-1111"})
    calls = []

    def claude(project, **k):
        calls.append(k["model"])
        raise QuotaExhausted("credit used up")

    def gem(project, **k):
        calls.append(k["model"][0])
        return "ok", k["model"][0]
    monkeypatch.setattr(anthropic_api, "generate_text", claude)
    monkeypatch.setattr(gemini, "generate_text", gem)
    return calls


def _job():
    ctx = jobs.Context({"log": []})
    jobs.bind(ctx)
    return ctx


def _answer(ctx, use):
    """Answer the question once it is on the page, from another thread, as the studio does."""
    def later():
        for _ in range(200):
            if ctx.answer(use):
                return
            time.sleep(0.01)
    threading.Thread(target=later, daemon=True).start()


CHAIN = ["claude-sonnet-5-5", "gemini-3.5-flash"]


def test_a_job_waits_for_a_yes_and_asks_once(claude_out_gemini_ok):
    ctx = _job()
    _answer(ctx, True)
    assert route.generate_text(PROJECT, stage="t", item="1", models=CHAIN, prompt="p")[1] == "gemini-3.5-flash"
    assert route.generate_text(PROJECT, stage="t", item="2", models=CHAIN, prompt="p")[1] == "gemini-3.5-flash"
    asked = [e["text"] for e in ctx.job["log"] if e["text"].startswith("Waiting for you")]
    assert len(asked) == 1 and "Claude has used up its free limit" in asked[0] and "Use Gemini" in asked[0]
    assert "question" not in ctx.job


def test_stop_ends_the_job_without_calling_the_next_service(claude_out_gemini_ok):
    ctx = _job()
    _answer(ctx, False)
    with pytest.raises(jobs.Cancelled):
        route.generate_text(PROJECT, stage="t", item="1", models=CHAIN, prompt="p")
    assert claude_out_gemini_ok == ["claude-sonnet-5-5"]


def test_the_stop_button_also_ends_the_wait(claude_out_gemini_ok):
    ctx = _job()
    threading.Timer(0.05, ctx.stop.set).start()
    with pytest.raises(jobs.Cancelled):
        route.generate_text(PROJECT, stage="t", item="1", models=CHAIN, prompt="p")
    assert "gemini-3.5-flash" not in claude_out_gemini_ok


def test_with_nobody_to_ask_it_refuses(claude_out_gemini_ok):
    for item in ("1", "2"):  # the used-up model is skipped the second time, and that is still a switch
        with pytest.raises(switch.Declined, match="Use Gemini instead"):
            route.generate_text(PROJECT, stage="t", item=item, models=CHAIN, prompt="p")
    assert claude_out_gemini_ok == ["claude-sonnet-5-5"]


def test_a_terminal_asks_y_or_n(claude_out_gemini_ok, monkeypatch):
    monkeypatch.setattr(switch, "INTERACTIVE", True)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    assert route.generate_text(PROJECT, stage="t", item="1", models=CHAIN, prompt="p")[1] == "gemini-3.5-flash"


def test_models_of_one_service_and_unkeyed_ones_do_not_ask(monkeypatch):
    keys.save("gemini", {"GEMINI_API_KEY": "g-key-1111"})
    monkeypatch.setattr(gemini, "generate_text", lambda project, **k: (_ for _ in ()).throw(QuotaExhausted("x"))
                        if k["model"][0] == "gemini-3.8-flash" else ("ok", k["model"][0]))
    chain = ["claude-sonnet-5-5", "gemini-3.8-flash", "gemini-3.5-flash"]  # no Claude key: skipped, no call
    assert route.generate_text(PROJECT, stage="t", item="1", models=chain, prompt="p")[1] == "gemini-3.5-flash"


def test_cloudflare_running_out_asks_before_kaggle(tmp_path, monkeypatch):
    monkeypatch.setattr(keyframes.keys, "slots", lambda s: [1] if s in ("cloudflare", "kaggle") else [])
    monkeypatch.setattr(keyframes.cloudflare, "generate_image",
                        lambda *a, **k: (_ for _ in ()).throw(QuotaExhausted("daily neuron allowance used up")))
    with pytest.raises(switch.Declined, match="Cloudflare has used up its free limit for pictures. Use Kaggle"):
        keyframes._generate(Project(tmp_path), item="S01", models=[FLUX2, KAGGLE], prompt="p", seed=1,
                            size=KEYFRAME_SIZE, references=[], batch=True)
    ctx = _job()
    _answer(ctx, True)
    with pytest.raises(Deferred):  # allowed: the picture waits for the Kaggle batch
        keyframes._generate(Project(tmp_path), item="S01", models=[FLUX2, KAGGLE], prompt="p", seed=1,
                            size=KEYFRAME_SIZE, references=[], batch=True)
