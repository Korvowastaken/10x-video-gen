"""Load, validate and save storyboard.json, the contract between every stage.

Validation has two layers: the JSON Schema in schema/ (shape and types) and the
cross-field rules below that a schema cannot express (every speaker exists, a
narrator never appears on screen, a real person has a consent record). Every
stage calls load_valid() first, so a broken storyboard stops the run before any
model is called.

Prompt composition also lives here, so every stage describes a character or a
place with exactly the same words: drift mostly comes from re-describing.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from .config import SCHEMA_PATH, ConfigError, Project

EDIT_DEFAULTS = {"fps": 24, "lead_s": 0.4, "gap_s": 0.35, "tail_s": 0.7, "caption_chars": 38}
DUCKING_DEFAULTS = {"threshold": 0.02, "ratio": 6, "attack_ms": 300, "release_ms": 1500}

SIZE_WORDS = {
    "extreme-wide": "Extreme wide shot",
    "wide": "Wide shot",
    "medium": "Medium shot",
    "medium-close-up": "Medium close-up",
    "close-up": "Close-up",
    "extreme-close-up": "Extreme close-up",
    "insert": "Insert close-up of a detail",
    "over-the-shoulder": "Over-the-shoulder shot",
}
FRAMING = ("Vertical 9:16 frame, the main subject centred in the middle third, clear space in the top "
           "fifth of the frame. No text, letters, signs, captions or watermarks anywhere in the image.")


class StoryboardError(ConfigError):
    pass


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text("utf-8")))


def schema_errors(sb: dict[str, Any]) -> list[str]:
    errors = sorted(_validator().iter_errors(sb), key=lambda e: [str(p) for p in e.absolute_path])
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errors]


def consent_ids(project: Project) -> set[str]:
    """IDs from the consent table in ETHICS.md: rows that start with | C<n> |."""
    if not project.ethics.exists():
        return set()
    return set(re.findall(r"^\|\s*(C\d+)\s*\|", project.ethics.read_text("utf-8"), re.MULTILINE))


# Unicode blocks for languages written in Ge'ez (Ethiopic) script. A line may also
# hold spaces, digits, common punctuation and quotes, but no other script.
ETHIOPIC = r"ሀ-፿ᎀ-᎟ⶀ-⷟꬀-꬯"
GEEZ_LINE = re.compile(rf"^[{ETHIOPIC}\s0-9.,!?:;'\"()\-…“”‘’«»]*$")


def script_errors(sb: dict[str, Any]) -> list[str]:
    """Catch lines in the wrong writing system (a model once put Burmese letters
    inside an Amharic word, which the TTS would mispronounce; FAILURES.md F5)."""
    if "Ge'ez" not in sb.get("language", {}).get("script", ""):
        return []
    errors = []
    for shot in sb.get("shots", []):
        for n, line in enumerate(shot["lines"], 1):
            if not GEEZ_LINE.match(line["text"]):
                bad = sorted({ch for ch in line["text"] if not GEEZ_LINE.match(ch)})
                errors.append(f"{shot['id']} line {n}: characters outside Ge'ez script: {' '.join(bad)} "
                              f"(write the line only in {sb['language']['name']} script)")
    return errors


def rule_errors(sb: dict[str, Any], project: Project | None = None) -> list[str]:
    errors: list[str] = script_errors(sb)
    characters = {c["id"]: c for c in sb.get("characters", [])}
    if len(characters) != len(sb.get("characters", [])):
        errors.append("characters: two characters share an id")
    locations = {loc["id"] for loc in sb.get("locations", [])}
    ids = [s["id"] for s in sb.get("shots", [])]
    if len(set(ids)) != len(ids):
        errors.append("shots: two shots share an id")
    if ids != sorted(ids):
        errors.append("shots: ids must run in screen order (S01, S02, ...)")
    for shot in sb.get("shots", []):
        sid = shot["id"]
        if shot["location"] not in locations:
            errors.append(f"{sid}: unknown location '{shot['location']}'")
        for cid in shot["characters"]:
            if cid not in characters:
                errors.append(f"{sid}: unknown character '{cid}'")
            elif not characters[cid]["visible"]:
                errors.append(f"{sid}: '{cid}' is voice-only and cannot appear on screen")
        for n, line in enumerate(shot["lines"], 1):
            if line["speaker"] not in characters:
                errors.append(f"{sid} line {n}: unknown speaker '{line['speaker']}'")
        if shot["motion"]["mode"] == "video" and len(shot["motion"]["prompt"].strip()) < 5:
            errors.append(f"{sid}: a video shot needs a motion prompt")
    for character in sb.get("characters", []):
        ref = character.get("reference")
        if ref and ref.get("chosen", 0) >= len(ref["seeds"]):
            errors.append(f"characters/{character['id']}: reference.chosen is past the end of seeds")
    errors += motion_errors(sb) + budget_errors(sb)
    music = sb.get("music", {})
    if music.get("chosen") is not None and music["chosen"] >= len(music.get("seeds", [])):
        errors.append("music: chosen is past the end of seeds")
    for cue in music.get("cues", []):
        if cue["at"] not in ids:
            errors.append(f"music cue at unknown shot {cue['at']}")
    if project is not None:
        recorded = consent_ids(project)
        for character in sb.get("characters", []):
            if character.get("real_person") and character.get("consent") not in recorded:
                errors.append(
                    f"characters/{character['id']}: portrays a real person but consent "
                    f"'{character.get('consent', '?')}' has no row in the ETHICS.md consent table. "
                    "Record consent first; nothing of a real person is generated without it.")
    return errors


def motion_errors(sb: dict[str, Any]) -> list[str]:
    """Engines exist and can do what each shot's mode asks (pipeline/engines.py)."""
    from .engines import LEGACY_MODES, MODES, MUSIC_ENGINES, VIDEO_ENGINES

    errors = []
    default_engine = sb.get("models", {}).get("video")
    if default_engine not in VIDEO_ENGINES:
        errors.append(f"models.video: unknown engine '{default_engine}' (known: {', '.join(VIDEO_ENGINES)})")
    if sb.get("models", {}).get("music") not in MUSIC_ENGINES:
        errors.append(f"models.music: unknown engine '{sb.get('models', {}).get('music')}' (known: {', '.join(MUSIC_ENGINES)})")
    for shot in sb.get("shots", []):
        motion = shot["motion"]
        mode = motion["mode"]
        if mode in LEGACY_MODES:
            errors.append(f"{shot['id']}: motion.mode '{mode}' is retired; use '{LEGACY_MODES[mode]}'")
            continue
        if not MODES.get(mode, {}).get("paid"):
            continue
        name = motion.get("engine", default_engine)
        engine = VIDEO_ENGINES.get(name)
        if engine is None:
            errors.append(f"{shot['id']}: unknown video engine '{name}'")
            continue
        if mode == "flf_inbetween" and not engine["last_image"]:
            errors.append(f"{shot['id']}: engine '{name}' cannot end on a given frame (no last_image)")
        if motion.get("clip_s", 5) not in engine["clip_s"]:
            errors.append(f"{shot['id']}: engine '{name}' makes {engine['clip_s']} s clips, not {motion.get('clip_s')}")
        for region in motion.get("mask", {}).get("regions", []):
            if region["x"] + region["w"] > 1.001 or region["y"] + region["h"] > 1.001:
                errors.append(f"{shot['id']}: a mask region runs past the edge of the frame")
    return errors


def budget_errors(sb: dict[str, Any]) -> list[str]:
    """Scenes use only the allowed motion modes, and the paid ones fit the film's budget."""
    from .engines import MODES, VIDEO_ENGINES

    video = sb.get("video", {})
    allowed = video.get("allowed_modes")
    errors = [f"{s['id']}: motion mode '{s['motion']['mode']}' is not one of the allowed modes ({', '.join(allowed)})"
              for s in sb.get("shots", []) if allowed and s["motion"]["mode"] not in allowed]
    total = 0.0
    for s in sb.get("shots", []):
        if MODES.get(s["motion"]["mode"], {}).get("paid"):
            engine = VIDEO_ENGINES.get(s["motion"].get("engine") or sb.get("models", {}).get("video"), {})
            total += engine.get("usd", {}).get(s["motion"].get("clip_s", 5), 0.0)
    if "budget_usd" in video and total > video["budget_usd"] + 1e-9:
        errors.append(f"video: the paid scenes cost ${total:.2f}, over the film's budget of ${video['budget_usd']:.2f}; "
                      "pick a free mode for some scenes or raise the budget")
    return errors


def reorder(sb: dict[str, Any], order: list[str]) -> dict[str, Any]:
    """The storyboard with its scenes in a new order, renumbered S01, S02, ... (music cues
    and final-cut choices follow their scene)."""
    ids = [s["id"] for s in sb["shots"]]
    if sorted(order) != sorted(ids):
        raise StoryboardError("the new order must list every scene once")
    by_id = {s["id"]: s for s in sb["shots"]}
    renamed = {old: f"S{n:02d}" for n, old in enumerate(order, 1)}
    out = json.loads(json.dumps(sb))
    out["shots"] = [dict(json.loads(json.dumps(by_id[old])), id=renamed[old]) for old in order]
    for cue in out.get("music", {}).get("cues", []):
        cue["at"] = renamed.get(cue["at"], cue["at"])
    if out.get("edit", {}).get("use"):
        out["edit"]["use"] = {renamed[k]: v for k, v in out["edit"]["use"].items() if k in renamed}
    return out


def paid_clips(sb: dict[str, Any]) -> list[dict[str, Any]]:
    from .engines import MODES
    return [s for s in sb["shots"] if MODES.get(s["motion"]["mode"], {}).get("paid")]


def warnings(sb: dict[str, Any]) -> list[str]:
    notes = []
    planned = sum(s["duration_s"] for s in sb["shots"]) + sb["end_card"]["duration_s"]
    if not 60 <= planned <= 90:
        notes.append(f"planned length is {planned:.0f}s; the brief asks for 60-90s")
    sizes = {s["size"] for s in sb["shots"]}
    if len(sizes) < 3:
        notes.append("fewer than three shot sizes; vary wide, medium and close-up")
    limit = edit_settings(sb)["caption_chars"] * 2
    for shot in sb["shots"]:
        for line in shot["lines"]:
            if len(line["en"]) > limit:
                notes.append(f"{shot['id']}: subtitle longer than two caption lines ({len(line['en'])} chars)")
    return notes


def load(project: Project) -> dict[str, Any]:
    if not project.storyboard.exists():
        raise StoryboardError(f"{project.storyboard.name} not found; run `make script` to draft it from story.md")
    return json.loads(project.storyboard.read_text("utf-8"))


def load_valid(project: Project) -> dict[str, Any]:
    sb = load(project)
    errors = schema_errors(sb)
    if not errors:
        errors = rule_errors(sb, project)
    if errors:
        raise StoryboardError("storyboard.json is invalid:\n  - " + "\n  - ".join(errors))
    for note in warnings(sb):
        print(f"  note: {note}")
    return sb


def save(project: Project, sb: dict[str, Any]) -> None:
    tmp = project.storyboard.with_suffix(".json.part")
    tmp.write_text(json.dumps(sb, indent=2, ensure_ascii=False) + "\n", "utf-8")
    tmp.replace(project.storyboard)


def edit_settings(sb: dict[str, Any]) -> dict[str, Any]:
    return {**EDIT_DEFAULTS, **sb.get("edit", {})}


def ducking(sb: dict[str, Any]) -> dict[str, Any]:
    return {**DUCKING_DEFAULTS, **sb["music"].get("ducking", {})}


def model_list(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else list(value)


def characters(sb: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in sb["characters"]}


def locations(sb: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {loc["id"]: loc for loc in sb["locations"]}


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else text + "."


def reference_prompt(sb: dict[str, Any], character: dict[str, Any]) -> str:
    """Character sheet: one figure, plain background, so later shots can copy it."""
    return " ".join(_sentence(p) for p in (
        sb["style"]["block"],
        f"Character reference sheet of {character['name']}: {character['look']}",
        character["reference"]["prompt"],
        "Full body, standing, facing the camera, plain light grey studio background, even soft light, "
        "nothing else in the frame. No text, letters or watermarks",
    ))


def location_prompt(sb: dict[str, Any], location: dict[str, Any]) -> str:
    return " ".join(_sentence(p) for p in (
        sb["style"]["block"], f"Establishing view of {location['name']}: {location['look']}",
        location["reference"]["prompt"], "No people. No text, letters or watermarks",
    ))


def image_prompt(sb: dict[str, Any], shot: dict[str, Any]) -> str:
    cast = characters(sb)
    place = locations(sb)[shot["location"]]
    parts = [sb["style"]["block"], f"Setting: {place['look']}"]
    for cid in shot["characters"]:
        parts.append(f"{cast[cid]['name']}: {cast[cid]['look']}")
    parts.append(f"{SIZE_WORDS[shot['size']]}: {shot['keyframe']['prompt']}")
    parts.append(FRAMING)
    return " ".join(_sentence(p) for p in parts)


def end_image_prompt(sb: dict[str, Any], shot: dict[str, Any]) -> str:
    """The frame an in-between must end on: same scene and look, the new state."""
    end = dict(shot, keyframe={"prompt": shot["motion"]["end_keyframe"]["prompt"],
                               "seed": shot["motion"]["end_keyframe"]["seed"]})
    return image_prompt(sb, end) + (" Keep the camera, framing, light and every character's look exactly as in the "
                                    "first reference image; only their pose and position change.")


def motion_prompt(sb: dict[str, Any], shot: dict[str, Any]) -> str:
    tag = sb["style"].get("motion", "smooth slow motion, stable shapes")
    prompt = f"{_sentence(shot['motion']['prompt'])} {_sentence(tag)}"
    if shot["motion"]["mode"] in ("masked_i2v", "cinemagraph"):
        # The clip is pasted back onto the still, so it has to line up with it (research 1a).
        prompt += " Static locked-off camera; the background does not move."
    return prompt
