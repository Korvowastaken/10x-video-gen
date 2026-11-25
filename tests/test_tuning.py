"""Free voice tuning: the FFmpeg chain it builds and the keys it changes."""
import copy
import json
import wave

import pytest

from pipeline import storyboard as sbmod
from pipeline import tuning
from pipeline.cache import key_for
from pipeline.config import ROOT, Project
from pipeline.media import probe_duration
from pipeline.narration import POST_VERSION, line_items, process, spec_for, tts_spec

PROJECT = Project(ROOT)


def _sb():
    return json.loads(PROJECT.storyboard.read_text("utf-8"))


def _untuned(sb):
    for c in sb["characters"]:
        c["voice"].pop("tune", None)
    for _, _, line in line_items(sb):
        line.pop("tune", None)
    return sb


# ---------------------------------------------------------------- filter chain

def test_neutral_tuning_adds_no_filters():
    assert tuning.filters({}, 24000) == []
    assert tuning.filters(None, 24000) == []
    assert tuning.filters({"speed": 1, "pitch": 0, "age": 0}, 24000) == []


def test_speed_alone_is_one_atempo():
    assert tuning.filters({"speed": 1.2}, 24000) == ["atempo=1.20000"]


def test_pitch_keeps_length_by_undoing_the_rate_change():
    chain = tuning.filters({"pitch": 12}, 24000)  # clamped to +4 semitones
    ratio = 2 ** (4 / 12)
    assert chain[0] == f"asetrate={round(24000 * ratio)}"
    assert chain[1] == "aresample=24000"
    assert chain[2] == f"atempo={1 / ratio:.5f}"


def test_pitch_and_speed_share_one_atempo():
    chain = tuning.filters({"pitch": -2, "speed": 0.9}, 48000)
    ratio = 2 ** (-2 / 12)
    assert chain == [f"asetrate={round(48000 * ratio)}", "aresample=48000", f"atempo={0.9 / ratio:.5f}"]


def test_age_direction_shapes_the_eq():
    older = ",".join(tuning.filters({"age": 0.5}, 24000))
    younger = ",".join(tuning.filters({"age": -0.5}, 24000))
    assert "highshelf=f=3200:g=-3.00" in older and "vibrato" in older
    assert "lowshelf=f=220:g=-3.00" in younger and "vibrato" not in younger


def test_tempo_outside_one_filter_range_is_chained():
    assert tuning._tempo_steps(0.3) == ["atempo=0.5", "atempo=0.60000"]
    assert tuning._tempo_steps(3.0) == ["atempo=2.0", "atempo=1.50000"]


def test_values_are_clamped_rounded_and_neutral_dropped():
    assert tuning.normalise({"speed": 2.0, "pitch": -0.04, "age": 0.333, "loud": 3}) == {"speed": 1.35, "age": 0.33}


def test_line_overrides_the_character_field_by_field():
    character = {"voice": {"name": "Kore", "direction": "warm", "tune": {"speed": 0.9, "age": 0.6}}}
    assert tuning.resolve(character, {}) == {"speed": 0.9, "age": 0.6}
    assert tuning.resolve(character, {"tune": {"pitch": -1}}) == {"speed": 0.9, "pitch": -1.0, "age": 0.6}
    # A neutral value on the line beats the default: this line sounds as recorded.
    assert tuning.resolve(character, {"tune": {"speed": 1, "age": 0}}) == {}


# ---------------------------------------------------------------- cache keys

def test_untuned_lines_keep_their_old_keys():
    """Adding tuning must not put every existing line out of date."""
    sb = _untuned(_sb())
    for _, _, line in line_items(sb):
        assert spec_for(sb, line) == {"tts": key_for(tts_spec(sb, line)), "post": POST_VERSION}


def test_tuning_changes_the_processed_key_but_not_the_take():
    sb = _untuned(_sb())
    items = line_items(sb)
    before = {i: key_for(spec_for(sb, ln)) for i, _, ln in items}
    takes = {i: key_for(tts_spec(sb, ln)) for i, _, ln in items}
    tuned = copy.deepcopy(sb)
    first, _, line = line_items(tuned)[0]
    line["tune"] = {"speed": 1.1}
    after = {i: key_for(spec_for(tuned, ln)) for i, _, ln in line_items(tuned)}
    assert [i for i in before if before[i] != after[i]] == [first]
    assert {i: key_for(tts_spec(tuned, ln)) for i, _, ln in line_items(tuned)} == takes  # no new TTS call


def test_character_default_changes_only_their_lines():
    sb = _untuned(_sb())
    speaker = line_items(sb)[0][2]["speaker"]
    before = {i: key_for(spec_for(sb, ln)) for i, _, ln in line_items(sb)}
    tuned = copy.deepcopy(sb)
    sbmod.characters(tuned)[speaker]["voice"]["tune"] = {"pitch": -1.5}
    changed = {i for i, _, ln in line_items(tuned) if key_for(spec_for(tuned, ln)) != before[i]}
    assert changed == {i for i, _, ln in line_items(sb) if ln["speaker"] == speaker}


def test_tuning_validates_in_the_schema():
    sb = _sb()
    sb["characters"][0]["voice"]["tune"] = {"speed": 0.9, "age": 0.4}
    line_items(sb)[0][2]["tune"] = {"pitch": 1.5}
    assert sbmod.schema_errors(sb) == []
    line_items(sb)[0][2]["tune"] = {"pitch": 9}
    assert any("tune" in e for e in sbmod.schema_errors(sb))
    line_items(sb)[0][2]["tune"] = {"volume": 1}
    assert any("tune" in e for e in sbmod.schema_errors(sb))


# ---------------------------------------------------------------- the real filters

def _tone(path, seconds=1.0, rate=24000):
    import math
    frames = bytearray()
    for n in range(int(seconds * rate)):
        v = int(9000 * math.sin(2 * math.pi * 220 * n / rate))
        frames += v.to_bytes(2, "little", signed=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


@pytest.mark.parametrize("tune", [{"speed": 1.25, "pitch": -3, "age": 1}, {"speed": 0.8, "pitch": 3, "age": -1}])
def test_ffmpeg_runs_the_chain_and_speed_sets_the_length(tmp_path, tune):
    raw = tmp_path / "raw.wav"
    _tone(raw, seconds=2.0)
    plain, tuned = tmp_path / "plain.wav", tmp_path / "tuned.wav"
    process(raw, plain)
    process(raw, tuned, tune)
    assert probe_duration(tuned) == pytest.approx(probe_duration(plain) / tune["speed"], rel=0.06)


def test_tuning_does_not_reopen_the_script():
    """Tuning is set in Scenes; the approved Script must stay approved."""
    from pipeline.flow import script_view

    sb = _untuned(_sb())
    before = key_for(script_view(sb))
    sb["characters"][0]["voice"]["tune"] = {"speed": 0.9}
    line_items(sb)[0][2]["tune"] = {"age": 0.5}
    assert key_for(script_view(sb)) == before
