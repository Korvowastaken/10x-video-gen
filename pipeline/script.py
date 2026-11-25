"""Stage 1, script: story.md -> storyboard.json.

Gemini reads the family story and drafts the creative half of the storyboard:
the cast (as many characters as the story needs), the shots and why each one
exists, the spoken lines in the film's language with English subtitles, and a
music brief. Code fills the technical half (models, seeds, defaults), validates
the result, and sends any errors back to the model, at most three attempts.

The storyboard is regenerated only when story.md changes (its hash is stored in
storyboard.json), so hand edits to storyboard.json survive every later run.
"""
from __future__ import annotations

import json
import re
import shutil
from typing import Any

import yaml

from . import storyboard as sbmod
from .cache import sha256_bytes
from .config import DEFAULT_MODELS, ConfigError, Project
from .engines import LEGACY_MODES, MODES
from .presets import LANGUAGES, STYLES, VOICES

PARALLAX_MOVES = ("push-in", "pull-out", "slide-left", "slide-right", "rise")
KENBURNS = ("zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down")
from .providers import gemini
from .runlog import now_iso

PROMPT_VERSION = "script-v1"
SCRIPT_MODELS = DEFAULT_MODELS["script"]
# Spoken words per second with Gemini TTS. Amharic: a bare 4-word line took 2.25 s
# (~1.8 w/s with padding). The earlier "1.0" came from takes polluted by a spoken
# style note (EXPERIMENTS.md E3, FAILURES.md F7). The others are estimates.
WORDS_PER_SECOND = {"am": 1.6, "ti": 1.6, "om": 1.8, "so": 1.9, "en": 2.3}

SYSTEM = """You are the writer and storyboard artist of a tiny animation studio. You turn one family
story into a 60-90 second vertical short film that the family will watch twice and forward to
everyone they know. You answer with one JSON object and nothing else."""

TEMPLATE = """{
  "title": "short title, 2-6 words, English",
  "logline": "one sentence that sums up the story",
  "audience": {"who": "...", "where": "...", "feel": "what they should feel or understand at the end"},
  "characters": [
    {"id": "lowercase_id", "name": "display name", "role": "character or narrator",
     "visible": true, "look": "concrete visual description: apparent age, build, face, hair,
     clothes with colours, one signature item", "reference_prompt": "pose or detail for the
     character sheet", "voice": {"name": "one voice from the list", "direction": "delivery note:
     age, pace, warmth"}}
  ],
  "locations": [
    {"id": "lowercase_id", "name": "...", "look": "time of day, light, colours, key objects",
     "reference_prompt": "establishing view, no people"}
  ],
  "shots": [
    {"id": "S01", "beat": "what changes in the story here", "reason": "why the film needs this shot",
     "size": "extreme-wide | wide | medium | medium-close-up | close-up | extreme-close-up | insert | over-the-shoulder",
     "location": "location id", "characters": ["ids visible in the frame"], "duration_s": 6,
     "keyframe": {"prompt": "what this still shows: action, expression, props, angle, light"},
     "motion": {"mode": "full_i2v | flf_inbetween | masked_i2v | cinemagraph | parallax | still_kenburns",
                "prompt": "only the motion and the camera", "subject": "character | ambient", "clip_s": 5,
                "mask": {"target": "masked modes only: what should move, in words"},
                "end_keyframe": {"prompt": "flf_inbetween only: Same place and camera: the end state"},
                "parallax": {"move": "parallax only: push-in | pull-out | slide-left | slide-right | rise"},
                "kenburns": "still_kenburns only: zoom-in | zoom-out | pan-left | pan-right | pan-up | pan-down"},
     "lines": [{"speaker": "character id", "text": "spoken line in LANGUAGE", "en": "English subtitle"}],
     "music_cue": "what the music does here"}
  ],
  "music": {"caption": "genre, mood, instruments, texture, era (no tempo, no key)", "bpm": 72,
            "key": "D minor", "time_signature": "4/4",
            "cues": [{"at": "S01", "note": "where the music starts, builds, drops or returns"}]},
  "end_card_dedication": "one short line for the end card, in English"
}"""

RULES = """Rules:
1. Shots: {min_shots}-{max_shots} shots. The sum of duration_s is about {target} seconds (the end card adds
   3 more; the whole film must land between 60 and 90 seconds). Shots are 4-9 seconds long.
2. Structure: S01 is a wide establishing shot. The last shot echoes S01 so the film closes like a
   circle. Vary shot sizes: wide to show where we are, medium for what happens, close-ups and
   inserts (hands, objects) for feeling. One idea and one gentle movement per shot.
3. Cast: use only as many characters as the story needs, at most 3 visible plus an optional
   voice-only narrator (visible false, role narrator, no look). Decide between a narrator and
   dialogue by what the story needs: dialogue when people talk to each other, a narrator when the
   story is remembered. If the same person appears at two ages, make two characters with clearly
   linked looks (same face shape, same signature item).
4. Real people: {people_rule}
5. Spoken lines: every line is natural, everyday spoken {language} written only in {script}, in short
   sentences made for the ear (at most 8 words per sentence), no tongue-twisters, no rare words. A shot
   holds 0-2 lines; its words must fit its duration at about {wps} words per second (measured for this
   voice), leaving a breath. The whole film has at most {words} spoken words: fewer is better.
   "en" is a faithful English subtitle of the line, at most 70 characters.
   voice.direction is a few words about tone and age only (e.g. "warm, elderly, smiling"); never ask
   for slow speech.
6. keyframe.prompt describes only this frame: action, expression, props, camera angle, light. Do not
   repeat the style or the characters' full looks; code adds them. Keep the subject centred with
   space above heads. Never ask for text, letters or signs in the image.
7. Motion: one mode per shot. At most {paid} shots may use the paid modes (each buys one generated clip):
   - full_i2v: whole-body action such as walking. clip_s 8 only when the walk lasts more than 6 seconds.
   - flf_inbetween: a clear start and end state in one place (a hand reaches out, then they hold hands);
     give end_keyframe.prompt, starting "Same place and camera:".
   - masked_i2v: only part of the frame moves (a face, hands); give mask.target in words.
   - cinemagraph: one looping detail (steam, smoke, pouring, water, leaves); give mask.target.
   Free modes:
   - parallax: establishing shots, landscapes, rooms, still characters; give parallax.move.
   - still_kenburns: inserts and small details; give kenburns.
   motion.prompt describes only motion and camera, one slow movement, e.g. "she slowly lifts the cup,
   steam rises, the camera pushes in gently". subject is "character" when a person moves, else "ambient".
8. Culture: dress, objects and places must be accurate for the story's place and era (for example
   habesha kemis, netela shawl with a woven tibeb border, gabi, jebena clay coffee pot with a long
   neck and round belly, small handleless sini cups, rekebot tray, mesob basket, eucalyptus, false-
   banana leaves). Describe objects visually, since image models may not know their names.
9. Music: an instrumental score under the voice, gentle texture and no strong lead melody, with a
   short theme that returns at the end. Tempo and key go in bpm and key, never in the caption. key is
   a note and a mode, e.g. "D minor" or "G major"; time_signature is "4/4", "3/4", "6/8" or "2/4".
10. Voices: choose from this list (name: pitch, character): {voices}.
11. Return JSON only, exactly in this shape:
{template}"""


class ScriptError(ConfigError):
    pass


def parse_story(text: str) -> tuple[dict[str, Any], str]:
    """Split story.md into its YAML settings block and the story itself."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        raise ScriptError("story.md must start with a settings block between --- lines (see the template)")
    meta = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()
    if len(body) < 80:
        raise ScriptError("story.md: the story is too short; write a few sentences: who, where, what happened")
    meta.setdefault("language", "am")
    meta.setdefault("look", "low-poly-3d")
    meta.setdefault("target_seconds", 75)
    meta.setdefault("seed", 1)
    meta["people"] = meta.get("people") or []
    if meta["language"] not in LANGUAGES:
        raise ScriptError(f"story.md: unknown language '{meta['language']}' (use one of {sorted(LANGUAGES)})")
    if meta["look"] not in STYLES:
        raise ScriptError(f"story.md: unknown look '{meta['look']}' (use one of {sorted(STYLES)})")
    if not 60 <= int(meta["target_seconds"]) <= 90:
        raise ScriptError("story.md: target_seconds must be between 60 and 90")
    return meta, body


def build_prompt(meta: dict[str, Any], body: str) -> str:
    lang = LANGUAGES[meta["language"]]
    target = int(meta["target_seconds"]) - 3
    wps = WORDS_PER_SECOND.get(meta["language"], 2.0)
    if meta["people"]:
        listed = "; ".join(f'id "{p["id"]}" = {p["name"]}' for p in meta["people"])
        people_rule = (f"these real people may appear or speak, and must keep exactly these ids: {listed}. "
                       "Every other character must be a fictional composite, not an identifiable real person.")
    else:
        people_rule = "no real person is depicted. Every character is a fictional composite inspired by the story."
    voices = ", ".join(f"{name}: {pitch}, {mood}" for name, (pitch, mood) in VOICES.items())
    rules = RULES.format(min_shots=10, max_shots=12, target=target, people_rule=people_rule, paid=7,
                         language=lang["name"], script=lang["script"], wps=wps,
                         words=int(target * wps * 0.8), voices=voices,
                         template=TEMPLATE.replace("LANGUAGE", lang["name"]))
    audience = f"Audience (from the author): {meta.get('audience', 'not given; infer it')}. " \
               f"What they should feel at the end: {meta.get('feel', 'not given; infer it')}."
    return f"{audience}\n\nThe family story, in the author's words:\n\"\"\"\n{body}\n\"\"\"\n\n{rules}"


def _seeds(base: int, count: int) -> list[int]:
    return [base + i for i in range(count)]


def to_storyboard(draft: dict[str, Any], meta: dict[str, Any], *, story_sha: str, model: str,
                  attempt: int) -> dict[str, Any]:
    """Merge the model's creative draft with the technical fields code owns."""
    lang = LANGUAGES[meta["language"]]
    style = STYLES[meta["look"]]
    people = {p["id"]: p for p in meta["people"]}
    characters = []
    for i, c in enumerate(draft.get("characters", [])):
        visible = bool(c.get("visible", True))
        out = {"id": c.get("id", f"character_{i}"), "name": c.get("name", ""), "role": c.get("role", "character"),
               "visible": visible, "real_person": c.get("id") in people, "voice": c.get("voice", {})}
        if out["real_person"]:
            out["consent"] = people[out["id"]]["consent"]
        if visible:
            out["look"] = c.get("look", "")
            out["reference"] = {"prompt": c.get("reference_prompt") or "neutral standing pose",
                                "seeds": _seeds(100 + 10 * i, 3), "chosen": 0}
        characters.append(out)
    locations = []
    for i, loc in enumerate(draft.get("locations", [])):
        locations.append({"id": loc.get("id", f"place_{i}"), "name": loc.get("name", ""), "look": loc.get("look", ""),
                          "reference": {"prompt": loc.get("reference_prompt") or "establishing view",
                                        "seeds": [500 + 10 * i], "chosen": 0}})
    shots = []
    for n, s in enumerate(draft.get("shots", []), 1):
        given = dict(s.get("motion", {}))
        mode = LEGACY_MODES.get(given.get("mode", ""), given.get("mode", "still_kenburns"))
        motion = {"mode": mode, "prompt": given.get("prompt", ""), "seed": 1000 + 10 * n}
        if given.get("subject") in ("character", "ambient"):
            motion["subject"] = given["subject"]
        if MODES.get(mode, {}).get("paid"):
            motion["clip_s"] = 8 if given.get("clip_s") == 8 else 5
        if mode in ("masked_i2v", "cinemagraph"):
            motion["mask"] = {"target": (given.get("mask") or {}).get("target") or "the main moving detail"}
            motion["loop"] = "pingpong"
        if mode == "flf_inbetween":
            end = (given.get("end_keyframe") or {}).get("prompt") or "Same place and camera: the action completed."
            motion["end_keyframe"] = {"prompt": end, "seed": 1001 + 10 * n}
        if mode == "parallax":
            move = (given.get("parallax") or {}).get("move", "push-in")
            motion["parallax"] = {"move": move if move in PARALLAX_MOVES else "push-in", "amount": 0.03}
        if mode == "still_kenburns":
            motion["kenburns"] = given.get("kenburns") if given.get("kenburns") in KENBURNS else "zoom-in"
        shot = {k: s[k] for k in ("id", "beat", "reason", "size", "location", "characters", "duration_s", "lines")
                if k in s}
        shot["keyframe"] = {"prompt": (s.get("keyframe") or {}).get("prompt", ""), "seed": 1000 + 10 * n}
        shot["motion"] = motion
        if s.get("music_cue"):
            shot["music_cue"] = s["music_cue"]
        shots.append(shot)
    music = {k: v for k, v in (draft.get("music") or {}).items() if k in ("caption", "bpm", "key", "time_signature", "cues")}
    total = sum(float(s.get("duration_s", 0)) for s in shots) + 3
    music.update({"duration_s": round(total + 4), "instrumental": True, "seeds": [11, 22, 33], "chosen": None,
                  "gain_db": -3, "ducking": dict(sbmod.DUCKING_DEFAULTS)})
    dedication = (draft.get("end_card_dedication") or "").strip()
    end_lines = ([dedication] if dedication else []) + [
        "Pictures: FLUX.2 klein   Motion: Wan 2.2",
        "Voices: Gemini TTS   Music: ACE-Step 1.5",
    ]
    return {
        "$schema": "./schema/storyboard.schema.json",
        "version": 1,
        "title": draft.get("title", "Untitled"),
        "logline": draft.get("logline", ""),
        "source": {"story_file": "story.md", "story_sha256": story_sha, "model": model,
                   "generated_at": now_iso(), "attempts": attempt},
        "audience": {"who": meta.get("audience") or (draft.get("audience") or {}).get("who", ""),
                     "where": (draft.get("audience") or {}).get("where") or "On a phone, vertical, in a social feed",
                     "feel": meta.get("feel") or (draft.get("audience") or {}).get("feel", "")},
        "language": {"code": meta["language"], "name": lang["name"], "script": lang["script"], "subtitles": "en"},
        "models": {"script": SCRIPT_MODELS, "tts": DEFAULT_MODELS["tts"], "listen": DEFAULT_MODELS["listen"],
                   "image": DEFAULT_MODELS["image"], "video": DEFAULT_MODELS["video"],
                   "music": DEFAULT_MODELS["music"]},
        "style": {k: style[k] for k in ("block", "motion", "negative", "palette")},
        "characters": characters,
        "locations": locations,
        "shots": shots,
        "music": music,
        "end_card": {"title": "Made with AI", "lines": end_lines, "duration_s": 3},
        "video": {"max_paid_clips": 7, "budget_usd": 0.6, "interpolation": "rife", "rife_model": "rife-v4.25"},
        "edit": dict(sbmod.EDIT_DEFAULTS),
    }


def people_errors(sb: dict[str, Any], meta: dict[str, Any]) -> list[str]:
    ids = {c["id"] for c in sb["characters"]}
    return [f'real person "{p["id"]}" from story.md is missing from characters'
            for p in meta["people"] if p["id"] not in ids and any(
                p["id"] in s["characters"] or any(l["speaker"] == p["id"] for l in s["lines"]) for s in sb["shots"])]


def run(project: Project, *, force: bool = False) -> dict[str, Any]:
    if not project.story.exists():
        raise ScriptError("story.md not found: write the family story there first (see README)")
    story_text = project.story.read_text("utf-8")
    story_sha = sha256_bytes(story_text.encode("utf-8"))
    if project.storyboard.exists():
        current = json.loads(project.storyboard.read_text("utf-8"))
        if current.get("source", {}).get("story_sha256") == story_sha and not force:
            print("  storyboard.json is up to date with story.md (hand edits are kept); skipping")
            return current
        backup = project.out("script", f"storyboard__{current.get('source', {}).get('story_sha256', 'old')[:12]}.json")
        shutil.copy2(project.storyboard, backup)
        print(f"  story.md changed: previous storyboard kept at {backup.relative_to(project.root)}")

    meta, body = parse_story(story_text)
    prompt = build_prompt(meta, body)
    errors: list[str] = []
    sb: dict[str, Any] = {}
    for attempt in range(1, 4):
        feedback = ""
        if errors:
            feedback = ("\n\nYour previous answer had these problems. Return the whole JSON again with them fixed:\n- "
                        + "\n- ".join(errors[:25]))
        text, used = gemini.generate_text(project, stage="script", item=f"draft-{attempt}", model=SCRIPT_MODELS,
                                          prompt=prompt + feedback, system=SYSTEM, json_mode=True,
                                          temperature=0.9 if attempt == 1 else 0.5,
                                          seed=int(meta["seed"]) + attempt - 1)
        try:
            draft = json.loads(text)
        except json.JSONDecodeError as exc:
            errors = [f"the answer was not valid JSON ({exc})"]
            continue
        sb = to_storyboard(draft, meta, story_sha=story_sha, model=used, attempt=attempt)
        errors = sbmod.schema_errors(sb) or (sbmod.rule_errors(sb) + people_errors(sb, meta))
        if not errors:
            break
        print(f"  draft {attempt} had {len(errors)} problem(s); asking for a fix")
    if errors:
        failed = project.out("script", "rejected_draft.json")
        failed.write_text(json.dumps(sb, indent=2, ensure_ascii=False), "utf-8")
        raise ScriptError("could not draft a valid storyboard in 3 attempts:\n  - " + "\n  - ".join(errors[:15]))

    sbmod.save(project, sb)
    shutil.copy2(project.storyboard, project.out("script", f"storyboard__{story_sha[:12]}.json"))
    words = sum(len(line["text"].split()) for s in sb["shots"] for line in s["lines"])
    planned = sum(s["duration_s"] for s in sb["shots"]) + sb["end_card"]["duration_s"]
    print(f"  drafted '{sb['title']}': {len(sb['shots'])} shots, {len(sb['characters'])} character(s), "
          f"{words} spoken words, ~{planned:.0f}s planned")
    for note in sbmod.warnings(sb):
        print(f"  note: {note}")
    return sb
