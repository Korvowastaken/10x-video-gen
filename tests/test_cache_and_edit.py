"""Caching regenerates only what changed; the edit helpers behave."""
import copy
import json

from pipeline import storyboard as sbmod
from pipeline.assemble import caption_chunks
from pipeline.cache import key_for
from pipeline.config import ROOT, Project
from pipeline.narration import char_error_rate, line_items, spec_for, tts_spec
from pipeline.providers.gemini import tts_prompt

PROJECT = Project(ROOT)


def _sb():
    return json.loads(PROJECT.storyboard.read_text("utf-8"))


def test_key_ignores_dict_order():
    assert key_for({"a": 1, "b": [1, 2]}) == key_for({"b": [1, 2], "a": 1})


def test_editing_one_keyframe_prompt_changes_only_that_shot():
    sb = _sb()
    before = {s["id"]: key_for({"prompt": sbmod.image_prompt(sb, s), "seed": s["keyframe"]["seed"]}) for s in sb["shots"]}
    edited = copy.deepcopy(sb)
    edited["shots"][2]["keyframe"]["prompt"] += " A red scarf."
    after = {s["id"]: key_for({"prompt": sbmod.image_prompt(edited, s), "seed": s["keyframe"]["seed"]})
             for s in edited["shots"]}
    changed = [sid for sid in before if before[sid] != after[sid]]
    assert changed == [sb["shots"][2]["id"]]


def test_editing_one_line_changes_only_that_line():
    sb = _sb()
    before = {item: key_for(spec_for(sb, line)) for item, _, line in line_items(sb)}
    edited = copy.deepcopy(sb)
    first_item, shot, line = line_items(edited)[0]
    line["text"] = line["text"] + " ።"
    after = {item: key_for(spec_for(edited, ln)) for item, _, ln in line_items(edited)}
    assert [i for i in before if before[i] != after[i]] == [first_item]


def test_tts_key_tracks_voice_and_direction():
    sb = _sb()
    _, _, line = line_items(sb)[0]
    base = key_for(tts_spec(sb, line))
    edited = copy.deepcopy(sb)
    speaker = sbmod.characters(edited)[line["speaker"]]
    speaker["voice"]["name"] = "Charon" if speaker["voice"]["name"] != "Charon" else "Kore"
    assert key_for(tts_spec(edited, line)) != base


def test_tts_prompt_starts_with_an_instruction_and_quotes_the_line():
    prompt = tts_prompt("ቀስ በቀስ፣ እንቁላል በእግሩ ይሄዳል።", "Mature, merry, loving", "Amharic")
    assert prompt.startswith("Say this line in Amharic")
    assert prompt.endswith('"ቀስ በቀስ፣ እንቁላል በእግሩ ይሄዳል።"')


def test_char_error_rate():
    assert char_error_rate("ቀስ በቀስ", "ቀስ በቀስ") == 0.0
    assert char_error_rate("ቀስ በቀስ", "mature merry loving") > 1.0  # the direction read aloud


def test_captions_split_at_punctuation_and_stay_two_lines():
    text = "She left before dawn with her mother, walking nearly three hours down the misty valley."
    chunks = caption_chunks(text, 38)
    assert chunks[0].endswith("mother,")
    assert all(chunk.count("\\N") <= 1 for chunk in chunks)
