"""Stage 1, script: story.md -> storyboard.json, in two steps.

1. Storyboard (models.script). A cheap model with no strict daily limit reads
   the family story (plain words, any language; the settings block at the top
   of story.md is optional) and drafts the creative half of the storyboard in
   English: the cast (as many characters as the story needs), the shots and why
   each one exists, every spoken line in English (it becomes the subtitle), and
   a music brief. Code fills the technical half (models, seeds, defaults),
   validates the result, and sends any errors back, at most three attempts.
2. Lines (models.lines). Only the spoken lines go to the model best at the
   film's language, with the story and the cast, to be written the way a
   speaker of that language would say them. Code checks the script and that
   each shot's words fit its length, at most three attempts. A film in English
   skips this step.

Most of the tokens are in step 1, so the strong (and strictly limited, or
paid) model only sees the few hundred words that need it.

The storyboard is regenerated only when story.md changes (its hash is stored in
storyboard.json), so hand edits to storyboard.json survive every later run.
"""
from __future__ import annotations

import copy
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
from .providers import route
from .runlog import now_iso

PARALLAX_MOVES = ("push-in", "pull-out", "slide-left", "slide-right", "rise")
KENBURNS = ("zoom-in", "zoom-out", "pan-left", "pan-right", "pan-up", "pan-down")

PROMPT_VERSION = "script-v2"
SCRIPT_MODELS = DEFAULT_MODELS["script"]
LINES_MODELS = DEFAULT_MODELS["lines"]
# English words per second in the storyboard draft. Below the 2.3 English TTS rate so the
# lines still fit once they are in a language that takes longer to say the same thing.
DRAFT_WORDS_PER_SECOND = 2.0
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
     "lines": [{"speaker": "character id", "en": "the spoken line, in English"}],
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
5. Spoken lines: write every line in plain spoken English, in "en" (at most 70 characters; it becomes
   the subtitle).{handoff} Write for the ear: short sentences (at most 8 words), everyday words, no
   tongue-twisters, no idioms or wordplay that only work in English. A shot holds 0-2 lines; its words must
   fit its duration at about {wps} words per second, leaving a breath. The whole film has at most {words}
   spoken words: fewer is better.
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


# Settings a story may set; everything has a default, so plain text is a whole story.
SETTINGS_DEFAULTS = {"language": "am", "look": "low-poly-3d", "target_seconds": 75, "seed": 1,
                     "audience": "", "feel": "", "people": []}


def split_story(text: str) -> tuple[dict[str, Any], str]:
    """story.md as (settings, story). The settings block between --- lines is optional."""
    match = re.match(r"^﻿?---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    try:
        meta = (yaml.safe_load(match.group(1)) or {}) if match else {}
    except yaml.YAMLError as exc:
        raise ScriptError(f"story.md: the settings block between --- lines has a typo ({exc})") from exc
    if not isinstance(meta, dict):
        raise ScriptError("story.md: the settings block between --- lines is not a list of settings")
    settings = {k: meta[k] if meta.get(k) is not None else v for k, v in SETTINGS_DEFAULTS.items()}
    settings.update({k: v for k, v in meta.items() if k not in settings})
    return settings, (match.group(2) if match else text).strip()


def join_story(settings: dict[str, Any], body: str) -> str:
    """Write story.md back: a settings block only when something differs from the defaults
    (keys this code does not know, such as `placeholder`, are kept)."""
    changed = {k: v for k, v in settings.items() if k not in SETTINGS_DEFAULTS or v != SETTINGS_DEFAULTS[k]}
    if not changed:
        return body.strip() + "\n"
    block = yaml.safe_dump(changed, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{block}\n---\n\n{body.strip()}\n"


def parse_story(text: str) -> tuple[dict[str, Any], str]:
    """Settings and story, checked: a story in any language, settings from the block or the defaults."""
    meta, body = split_story(text)
    if len(body) < 80:
        raise ScriptError("story.md: the story is too short; write a few sentences: who, where, what happened")
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
    english = meta["language"] == "en"
    wps = wps if english else DRAFT_WORDS_PER_SECOND
    handoff = "" if english else (
        f" A second writer then puts each line into natural spoken {lang['name']}, so say plainly what"
        " the person means, and use names and forms of address the way the family would.")
    rules = RULES.format(min_shots=10, max_shots=12, target=target, people_rule=people_rule, paid=7,
                         handoff=handoff, wps=wps, words=int(target * wps * 0.8), voices=voices,
                         template=TEMPLATE)
    audience = f"Audience (from the author): {meta.get('audience') or 'not given; infer it'}. " \
               f"What they should feel at the end: {meta.get('feel') or 'not given; infer it'}."
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
        shot = {k: s[k] for k in ("id", "beat", "reason", "size", "location", "characters", "duration_s")
                if k in s}
        # The draft's lines are English. "text" holds the English until the lines step writes the film's language.
        shot["lines"] = [{"speaker": line.get("speaker", ""), "text": line.get("text") or line.get("en", ""),
                          "en": line.get("en") or line.get("text", "")}
                         for line in s.get("lines", []) if isinstance(line, dict)]
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
        f"Voices: {route.label(DEFAULT_MODELS['tts'][0])}   Music: ACE-Step 1.5",
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
        "models": {"script": SCRIPT_MODELS, "lines": LINES_MODELS, "tts": DEFAULT_MODELS["tts"],
                   "listen": DEFAULT_MODELS["listen"],
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


LINES_SYSTEM = """You write the spoken lines of a short family film in {language}. You know how people
really talk in {language}: at home, between generations, in the story's place and time. You answer
with one JSON object and nothing else."""


def line_rows(sb: dict[str, Any]) -> list[dict[str, Any]]:
    """Every spoken line with what its writer needs: where it falls and how long the shot is."""
    return [{"id": f"{shot['id']}_L{n}", "shot": shot["id"], "seconds": shot["duration_s"],
             "beat": shot.get("beat", ""), "speaker": line["speaker"], "en": line["en"]}
            for shot in sb["shots"] for n, line in enumerate(shot["lines"], 1)]


def build_lines_prompt(sb: dict[str, Any], body: str) -> str:
    lang = sb["language"]
    wps = WORDS_PER_SECOND.get(lang["code"], 2.0)
    cast = "\n".join(f"- {c['id']} ({c.get('name') or c['id']}, {c.get('role', 'character')}): "
                     f"{(c.get('voice') or {}).get('direction', '')}" for c in sb["characters"])
    rows = json.dumps(line_rows(sb), ensure_ascii=False, indent=1)
    quotes = '"' * 3
    return f"""The family story, in the author's words:
{quotes}
{body}
{quotes}

The film: "{sb['title']}". {sb.get('logline', '')}
Cast (id, name, role: how they sound):
{cast}

Each spoken line below was drafted in English. Write what each person actually says, in natural,
everyday spoken {lang['name']}, written only in {lang['script']}. Rules:
- Say what the English says, so it stays a faithful subtitle, but the way a {lang['name']} speaker would
  say it, not word for word. Use the forms of address, kinship words and turns of phrase a family there
  would use.
- Short sentences made for the ear (at most 8 words each), no rare words, no tongue-twisters.
- All the lines of one shot together must fit its seconds at about {wps} words per second, leaving a breath.
- If a line has to say something a little different from the English, also give "en": the corrected
  English subtitle, at most 70 characters. Otherwise leave "en" out.
- Return JSON only, {{"lines": [{{"id": "S01_L1", "text": "..."}}]}}, with every id below exactly once.

Lines:
{rows}"""


def apply_lines(sb: dict[str, Any], answer: Any) -> tuple[list[str], list[str]]:
    """Write an answer's lines into the storyboard. Returns (problems that block, problems to fix if possible)."""
    rows = answer.get("lines") if isinstance(answer, dict) else answer
    by_id = {str(r["id"]): r for r in (rows or []) if isinstance(r, dict) and r.get("id")}
    wps = WORDS_PER_SECOND.get(sb["language"]["code"], 2.0)
    hard: list[str] = []
    soft: list[str] = []
    for shot in sb["shots"]:
        words = 0
        for n, line in enumerate(shot["lines"], 1):
            row = by_id.get(f"{shot['id']}_L{n}") or {}
            text = str(row.get("text") or "").strip()
            if not text:
                hard.append(f"{shot['id']}_L{n} is missing: give its text")
                continue
            line["text"] = text
            if str(row.get("en") or "").strip():
                line["en"] = str(row["en"]).strip()
            words += len(text.split())
        fit = int(shot["duration_s"] * wps)
        if words > fit:
            soft.append(f"{shot['id']}: its lines hold {words} words, but about {fit} fit in "
                        f"{shot['duration_s']} s; make them shorter")
    return hard + sbmod.script_errors(sb), soft


def write_lines(project: Project, sb: dict[str, Any], meta: dict[str, Any], body: str) -> None:
    """Step 2: the English lines -> the film's language, by the model best at it."""
    if not any(shot["lines"] for shot in sb["shots"]):
        return
    english = [copy.deepcopy(shot["lines"]) for shot in sb["shots"]]
    prompt = build_lines_prompt(sb, body)
    system = LINES_SYSTEM.format(language=sb["language"]["name"])
    hard: list[str] = []
    soft: list[str] = []
    used = ""
    for attempt in range(1, 4):
        feedback = ""
        if hard or soft:
            feedback = ("\n\nYour previous answer had these problems. Return every line again with them fixed:\n- "
                        + "\n- ".join((hard + soft)[:25]))
        text, used = route.generate_text(project, stage="script", item=f"lines-{attempt}", models=LINES_MODELS,
                                         prompt=prompt + feedback, system=system, json_mode=True,
                                         temperature=0.7 if attempt == 1 else 0.4,
                                         seed=int(meta["seed"]) + attempt - 1)
        for shot, lines in zip(sb["shots"], english):  # each attempt starts from the English draft
            shot["lines"] = copy.deepcopy(lines)
        try:
            hard, soft = apply_lines(sb, json.loads(text))
        except json.JSONDecodeError as exc:
            hard, soft = [f"the answer was not valid JSON ({exc})"], []
            continue
        if not hard and not soft:
            break
        print(f"  lines {attempt} had {len(hard) + len(soft)} problem(s); asking for a fix")
    if hard:
        _reject(project, sb, f"could not write the {sb['language']['name']} lines in 3 attempts", hard)
    for note in soft:
        print(f"  note: {note}")
    sb["source"]["lines_model"] = used


def _reject(project: Project, sb: dict[str, Any], why: str, errors: list[str]) -> None:
    failed = project.out("script", "rejected_draft.json")
    failed.write_text(json.dumps(sb, indent=2, ensure_ascii=False), "utf-8")
    raise ScriptError(f"{why}:\n  - " + "\n  - ".join(errors[:15]))


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
    english = meta["language"] == "en"
    prompt = build_prompt(meta, body)
    errors: list[str] = []
    sb: dict[str, Any] = {}
    for attempt in range(1, 4):
        feedback = ""
        if errors:
            feedback = ("\n\nYour previous answer had these problems. Return the whole JSON again with them fixed:\n- "
                        + "\n- ".join(errors[:25]))
        text, used = route.generate_text(project, stage="script", item=f"draft-{attempt}", models=SCRIPT_MODELS,
                                         prompt=prompt + feedback, system=SYSTEM, json_mode=True,
                                         temperature=0.9 if attempt == 1 else 0.5,
                                         seed=int(meta["seed"]) + attempt - 1)
        try:
            draft = json.loads(text)
        except json.JSONDecodeError as exc:
            errors = [f"the answer was not valid JSON ({exc})"]
            continue
        sb = to_storyboard(draft, meta, story_sha=story_sha, model=used, attempt=attempt)
        # The lines are English until step 2, so the script check waits for it.
        errors = sbmod.schema_errors(sb) or (sbmod.rule_errors(sb, check_script=english) + people_errors(sb, meta))
        if not errors:
            break
        print(f"  draft {attempt} had {len(errors)} problem(s); asking for a fix")
    if errors:
        _reject(project, sb, "could not draft a valid storyboard in 3 attempts", errors)
    if not english:
        write_lines(project, sb, meta, body)
        errors = sbmod.schema_errors(sb) or (sbmod.rule_errors(sb) + people_errors(sb, meta))
        if errors:
            _reject(project, sb, "the storyboard is not valid after the lines were written", errors)

    sbmod.save(project, sb)
    shutil.copy2(project.storyboard, project.out("script", f"storyboard__{story_sha[:12]}.json"))
    words = sum(len(line["text"].split()) for s in sb["shots"] for line in s["lines"])
    planned = sum(s["duration_s"] for s in sb["shots"]) + sb["end_card"]["duration_s"]
    print(f"  drafted '{sb['title']}': {len(sb['shots'])} shots, {len(sb['characters'])} character(s), "
          f"{words} spoken words, ~{planned:.0f}s planned")
    for note in sbmod.warnings(sb):
        print(f"  note: {note}")
    return sb
