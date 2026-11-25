"""Writing and voices across providers: the chain order, skipping, and the two-step script."""
import copy
import json

import pytest

from pipeline import keys, retry, script
from pipeline import storyboard as sbmod
from pipeline.config import ROOT, ConfigError, Project
from pipeline.providers import anthropic_api, azure_speech, gemini, route
from pipeline.retry import ProviderError, QuotaExhausted

FILM = ROOT / "tests" / "fixtures" / "film"  # a sample film to test against, so the real project can be empty

PROJECT = Project(FILM)


@pytest.fixture(autouse=True)
def clean(no_keys):
    retry.EXHAUSTED.clear()
    yield
    retry.EXHAUSTED.clear()


def test_model_ids_name_their_provider():
    assert route.provider_of("claude-haiku-5-5") == "anthropic"
    assert route.provider_of("azure-neural") == "azure"
    assert route.provider_of("groq/some-model") == "groq"
    assert route.provider_of("openrouter/vendor/model:free") == "openrouter"
    assert route.provider_of("gemini-3.5-flash") == "gemini"


def test_a_provider_without_a_key_is_skipped_without_a_call(monkeypatch):
    keys.save("gemini", {"GEMINI_API_KEY": "g-key-1111"})
    monkeypatch.setattr(anthropic_api, "generate_text", lambda *a, **k: pytest.fail("no Anthropic key is saved"))
    monkeypatch.setattr(gemini, "generate_text", lambda project, **k: (f"from {k['model'][0]}", k["model"][0]))
    text, used = route.generate_text(PROJECT, stage="t", item="i", models=["claude-haiku-5-5", "gemini-3.5-flash"],
                                     prompt="p")
    assert (text, used) == ("from gemini-3.5-flash", "gemini-3.5-flash")


def test_the_chain_moves_on_and_remembers_a_used_up_model(monkeypatch):
    keys.save("anthropic", {"ANTHROPIC_API_KEY": "a-key-2222"})
    keys.save("gemini", {"GEMINI_API_KEY": "g-key-1111"})
    calls = []

    def claude(project, **k):
        calls.append(k["model"])
        raise QuotaExhausted("credit used up")

    def refuse(project, **k):
        calls.append(k["model"][0])
        raise ProviderError("declined")

    monkeypatch.setattr(anthropic_api, "generate_text", claude)
    monkeypatch.setattr(gemini, "generate_text", lambda project, **k: refuse(project, **k)
                        if k["model"][0] == "gemini-3.8-flash" else ("ok", k["model"][0]))
    chain = ["claude-sonnet-5-5", "gemini-3.8-flash", "gemini-3.5-flash"]
    assert route.generate_text(PROJECT, stage="t", item="1", models=chain, prompt="p")[1] == "gemini-3.5-flash"
    assert route.generate_text(PROJECT, stage="t", item="2", models=chain, prompt="p")[1] == "gemini-3.5-flash"
    assert calls.count("claude-sonnet-5-5") == 1  # out of credit: not asked again this run


def test_no_key_anywhere_says_so():
    with pytest.raises(ConfigError, match="key is saved"):
        route.generate_text(PROJECT, stage="t", item="i", models=["claude-haiku-5-5"], prompt="p")


def test_azure_voice_follows_the_storyboard_voice():
    assert azure_speech.voice("Gacrux", "am") == ("am-ET", "am-ET-MekdesNeural", "-6%")  # f, mature
    assert azure_speech.voice("Puck", "am") == ("am-ET", "am-ET-AmehaNeural", "+6%")     # m, upbeat
    assert azure_speech.voice("Orus", "am")[1:] == ("am-ET-AmehaNeural", "+0%")
    with pytest.raises(ConfigError):
        azure_speech.voice("Kore", "ti")  # no Tigrinya neural voice: the chain falls back to Gemini
    assert "&amp;" in azure_speech.ssml("salt & bread", "am-ET", "am-ET-MekdesNeural", "+0%")


def test_tts_falls_back_to_gemini_for_a_language_azure_lacks(monkeypatch):
    keys.save("azure", {"AZURE_SPEECH_KEY": "z-key-3333", "AZURE_SPEECH_REGION": "eastus"})
    keys.save("gemini", {"GEMINI_API_KEY": "g-key-1111"})
    monkeypatch.setattr(gemini, "tts", lambda project, **k: (b"\0\0", 24000, k["model"][0]))
    pcm, rate, used = route.tts(PROJECT, stage="t", item="i", models=["azure-neural", "gemini-3.8-flash-tts"],
                                text="ሰላም", voice="Kore", language="ti")
    assert used == "gemini-3.8-flash-tts"


def test_claude_json_answer_loses_its_fence():
    assert json.loads(anthropic_api.json_text('```json\n{"a": 1}\n```')) == {"a": 1}


@pytest.fixture()
def sb():
    return json.loads(PROJECT.storyboard.read_text("utf-8"))


def test_lines_step_writes_each_line_and_keeps_the_subtitle(sb):
    rows = script.line_rows(sb)
    assert rows and all(r["id"].startswith(r["shot"]) for r in rows)
    answer = {"lines": [{"id": r["id"], "text": "ሰላም ነው"} for r in rows]}
    answer["lines"][0]["en"] = "A corrected subtitle"
    draft = copy.deepcopy(sb)
    hard, soft = script.apply_lines(draft, answer)
    assert hard == [] and soft == []
    lines = [line for shot in draft["shots"] for line in shot["lines"]]
    assert all(line["text"] == "ሰላም ነው" for line in lines)
    assert lines[0]["en"] == "A corrected subtitle"
    assert lines[1]["en"] == [l for s in sb["shots"] for l in s["lines"]][1]["en"]


def test_lines_step_sends_back_missing_lines_wrong_script_and_long_shots(sb):
    rows = script.line_rows(sb)
    answer = {"lines": [{"id": r["id"], "text": "hello there"} for r in rows[1:]]}
    long_shot = [s for s in sb["shots"] if s["lines"] and s["id"] != rows[0]["shot"]][-1]
    answer["lines"].append({"id": f"{long_shot['id']}_L1", "text": " ".join(["ቃል"] * 40)})
    hard, soft = script.apply_lines(copy.deepcopy(sb), answer)
    assert any(f"{rows[0]['id']} is missing" in e for e in hard)
    assert any("outside Ge'ez script" in e for e in hard)
    assert any(e.startswith(long_shot["id"]) and "make them shorter" in e for e in soft)


def test_english_draft_passes_rules_before_the_lines_step(sb):
    draft = copy.deepcopy(sb)
    for shot in draft["shots"]:
        for line in shot["lines"]:
            line["text"] = line["en"]
    assert any("outside Ge'ez script" in e for e in sbmod.rule_errors(draft))
    assert not any("outside Ge'ez script" in e for e in sbmod.rule_errors(draft, check_script=False))


def test_draft_prompt_asks_for_english_lines_and_names_the_second_writer():
    meta = dict(script.SETTINGS_DEFAULTS, language="am")
    prompt = script.build_prompt(meta, "A long walk to school. " * 10)
    assert '"en": "the spoken line, in English"' in prompt and "natural spoken Amharic" in prompt
    english = script.build_prompt(dict(meta, language="en"), "A long walk to school. " * 10)
    assert "second writer" not in english
