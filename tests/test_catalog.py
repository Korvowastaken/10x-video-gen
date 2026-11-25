from pipeline import catalog
from pipeline.config import DEFAULT_MODELS, Project


def test_choice_goes_first_and_keeps_fallbacks(tmp_path):
    project = Project(tmp_path)
    sb = {"models": {"script": ["a", "b", "c"]}}
    assert catalog.choose(project, "script", "c", sb) == ["c", "a", "b"]
    assert sb["models"]["script"] == ["c", "a", "b"]


def test_choice_before_a_storyboard_carries_into_the_draft(tmp_path):
    project = Project(tmp_path)
    catalog.choose(project, "lines", "gemini-3.5-flash", None)
    block = catalog.models_block(project, None)
    assert block["lines"][0] == "gemini-3.5-flash"
    assert block["tts"] == DEFAULT_MODELS["tts"]


def test_engines_are_one_value(tmp_path):
    project = Project(tmp_path)
    assert catalog.choose(project, "video", "wavespeed-wan22-720p", None) == "wavespeed-wan22-720p"


def test_names_read_well():
    assert catalog.pretty("claude-haiku-5-5") == "Claude Haiku 5.5"
    assert catalog.pretty("gemini-3.8-flash-tts") == "Gemini 3.8 Flash TTS"
    assert catalog.pretty("groq/openai/gpt-oss-120b") == "openai/gpt-oss-120b"


def test_revisions_follow_the_writers_until_chosen(tmp_path):
    project = Project(tmp_path)
    sb = {"models": {"script": ["groq/x", "gemini-3.5-flash"], "lines": ["claude-sonnet-5-5"]}}
    assert catalog.chain(project, "revise", sb) == ["claude-sonnet-5-5", "groq/x", "gemini-3.5-flash"]
    assert "revise" not in catalog.models_block(project, sb)
    catalog.choose(project, "revise", "groq/x", sb)
    assert sb["models"]["revise"] == ["groq/x", "claude-sonnet-5-5", "gemini-3.5-flash"]
    assert catalog.models_block(project, sb)["revise"][0] == "groq/x"


def test_mask_finding_puts_gemini_first(tmp_path):
    project = Project(tmp_path)
    sb = {"models": {"script": ["claude-haiku-5-5", "gemini-3.5-flash"]}}
    assert catalog.chain(project, "mask", sb)[:2] == ["gemini-3.5-flash", "gemini-3.5-flash-lite"]
