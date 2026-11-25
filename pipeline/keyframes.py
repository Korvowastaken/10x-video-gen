"""Stage: keyframes. Reference sheets first, then one still per shot conditioned on them.

The order follows the brief's "lock the look first":
  1. a reference sheet per visible character (a few seeds; storyboard.json's
     reference.chosen marks the approved one) and an establishing image per
     location;
  2. each shot's keyframe from FLUX.2 klein, given the approved references of the
     characters and the place in that shot as input images.
A keyframe's cache key includes the hashes of its references, so approving a
different character sheet regenerates exactly the shots that character is in.

Fallback: when FLUX.2 fails or its daily allowance is gone, FLUX.1 schnell
(no references, no seed). runs.jsonl records which model drew each image.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import storyboard as sbmod
from .cache import StageCache, key_for, sha256_file, write_atomic
from .config import FONTS, Project
from .providers import cloudflare
from .retry import ProviderError, QuotaExhausted, RetryableError

KEYFRAME_SIZE = (768, 1344)   # about 9:16, multiples of 16: 6 output tiles on Workers AI
REFERENCE_SIZE = (768, 1024)  # character sheet, full body: 4 tiles
MAX_REFERENCES = 4
REF_NOTE = ("Keep every character's face, hair, skin tone and clothes exactly as in the character reference "
            "images, and the place's colours and light as in the location reference image.")


def _generate(project: Project, *, item: str, models: list[str], prompt: str, seed: int,
              size: tuple[int, int], references: list[Path]) -> tuple[bytes, str, str]:
    """Try the reference-aware model first; fall back to one without references."""
    last: Exception | None = None
    for model in models:
        refs = references if "flux-2" in model else []
        text = f"{prompt} {REF_NOTE}" if refs else prompt
        try:
            data, ext = cloudflare.generate_image(project, stage="keyframes", item=item, model=model,
                                                  prompt=text, seed=seed, width=size[0], height=size[1],
                                                  references=refs[:MAX_REFERENCES])
            return data, ext, model
        except (QuotaExhausted, RetryableError, ProviderError) as exc:
            last = exc
            print(f"    {item}: {model} failed ({' '.join(str(exc).split())[:120]}); trying the next model")
    assert last is not None
    raise last


def _make(project: Project, cache: StageCache, *, item: str, spec: dict[str, Any], models: list[str],
          prompt: str, seed: int,
          size: tuple[int, int], references: list[Path], force: bool, counts: dict[str, int]) -> Path:
    key = key_for(spec)
    hit = cache.hit(item, key, ".jpg") or cache.hit(item, key, ".png")
    if hit and not force:
        counts["cached"] += 1
        if cache.entry(item) is None or cache.entry(item).get("key") != key:
            cache.record(item, key, hit, spec)
        return hit
    data, ext, used = _generate(project, item=item, models=models, prompt=prompt, seed=seed,
                                size=size, references=references)
    path = cache.path(item, key, ext)
    write_atomic(path, data)
    cache.record(item, key, path, spec, model=used, references=[r.name for r in references if "flux-2" in used])
    counts["made"] += 1
    return path


def references(project: Project, sb: dict[str, Any], *, force: bool = False,
               counts: dict[str, int] | None = None, needed: set[str] | None = None) -> dict[str, Path]:
    """Generate (or reuse) the reference candidates; return the approved one per character/location.

    `needed` limits work to the characters and places of the selected shots."""
    counts = counts if counts is not None else {"made": 0, "cached": 0}
    models = sbmod.model_list(sb["models"]["image"])
    cache = StageCache(project, "refs")
    approved: dict[str, Path] = {}
    for character in sb["characters"]:
        if not character["visible"] or (needed is not None and character["id"] not in needed):
            continue
        ref = character["reference"]
        prompt = sbmod.reference_prompt(sb, character)
        photo = _photo(project, ref)
        if photo:
            prompt += (" Base the face, hair and build on the reference photo, drawn in the style above, "
                       "not as a photograph.")
        for i, seed in enumerate(ref["seeds"]):
            spec = {"v": 1, "prompt": prompt, "seed": seed, "model": models[0], "size": REFERENCE_SIZE,
                    "photo": sha256_file(photo) if photo else None}
            path = _make(project, cache, item=f"char_{character['id']}_{i}", spec=spec, models=models, prompt=prompt, seed=seed,
                         size=REFERENCE_SIZE, references=[photo] if photo else [], force=force, counts=counts)
            if i == ref.get("chosen", 0):
                approved[character["id"]] = path
    for location in sb["locations"]:
        ref = location.get("reference")
        if not ref or (needed is not None and location["id"] not in needed):
            continue
        prompt = sbmod.location_prompt(sb, location)
        seed = ref["seeds"][ref.get("chosen", 0)]
        photo = _photo(project, ref)
        if photo:
            prompt += " Base the layout, landmarks and colours on the reference photo, drawn in the style above."
        spec = {"v": 1, "prompt": prompt, "seed": seed, "model": models[0], "size": KEYFRAME_SIZE,
                "photo": sha256_file(photo) if photo else None}
        approved[f"place:{location['id']}"] = _make(
            project, cache, item=f"place_{location['id']}", spec=spec, models=models, prompt=prompt, seed=seed,
            size=KEYFRAME_SIZE, references=[photo] if photo else [], force=force, counts=counts)
    contact_sheet([(name, p) for name, p in sorted(_all_current(cache).items())],
                  project.out("refs", "contact_sheet.jpg"), columns=4)
    return approved


def _photo(project: Project, ref: dict[str, Any]) -> Path | None:
    """An uploaded reference photo (references/<file>) for a character or place, if there is one."""
    if not ref.get("photo"):
        return None
    path = project.root / ref["photo"]
    if not path.exists():
        raise FileNotFoundError(f"reference photo {ref['photo']} is missing")
    return path


def _all_current(cache: StageCache) -> dict[str, Path]:
    return {item: cache.dir / e["file"] for item, e in cache.manifest.items() if (cache.dir / e["file"]).exists()}


def run(project: Project, *, only: set[str] | None = None, force: bool = False) -> None:
    sb = sbmod.load_valid(project)
    counts = {"made": 0, "cached": 0}
    chosen = [s for s in sb["shots"] if only is None or s["id"] in only]
    needed = {c for s in chosen for c in s["characters"]} | {s["location"] for s in chosen}
    approved = references(project, sb, counts=counts, needed=needed)
    models = sbmod.model_list(sb["models"]["image"])
    cache = StageCache(project, "keyframes")
    sheet = []
    for shot in sb["shots"]:
        refs = [approved[c] for c in shot["characters"] if c in approved]
        place = approved.get(f"place:{shot['location']}")
        if place is not None:
            refs.append(place)
        refs = refs[:MAX_REFERENCES]
        prompt = sbmod.image_prompt(sb, shot)
        spec = {"v": 1, "prompt": prompt, "seed": shot["keyframe"]["seed"], "model": models[0],
                "size": KEYFRAME_SIZE, "refs": [sha256_file(r) for r in refs]}
        selected = only is None or shot["id"] in only
        if not selected:  # ONLY=... limits generation; show what exists for the others
            for item in (shot["id"], f"{shot['id']}_end"):
                if cache.current(item):
                    sheet.append((item, cache.current(item)))
            continue
        path = _make(project, cache, item=shot["id"], spec=spec, models=models, prompt=prompt, seed=shot["keyframe"]["seed"],
                     size=KEYFRAME_SIZE, references=refs, force=force, counts=counts)
        sheet.append((shot["id"], path))
        if shot["motion"]["mode"] == "flf_inbetween":
            # The end frame takes the start frame as its first reference, so both share one scene.
            end_refs = [path] + [r for r in refs if r != place][:MAX_REFERENCES - 1]
            end_prompt = sbmod.end_image_prompt(sb, shot)
            end_seed = shot["motion"]["end_keyframe"]["seed"]
            end_spec = {"v": 1, "prompt": end_prompt, "seed": end_seed, "model": models[0], "size": KEYFRAME_SIZE,
                        "refs": [sha256_file(r) for r in end_refs]}
            end = _make(project, cache, item=f"{shot['id']}_end", spec=end_spec, models=models, prompt=end_prompt,
                        seed=end_seed, size=KEYFRAME_SIZE, references=end_refs, force=force, counts=counts)
            sheet.append((f"{shot['id']}_end", end))
    contact_sheet(sheet, project.out("keyframes", "contact_sheet.jpg"), columns=5)
    print(f"  keyframes: {counts['made']} image(s) generated, {counts['cached']} cached "
          "(review outputs/refs/contact_sheet.jpg and outputs/keyframes/contact_sheet.jpg)")


def contact_sheet(items: list[tuple[str, Path]], out: Path, *, columns: int, thumb_w: int = 300) -> None:
    """A labelled grid of images, for a quick human (or model) review of consistency."""
    if not items:
        return
    thumbs = []
    for label, path in items:
        with Image.open(path) as img:
            img = img.convert("RGB")
            ratio = thumb_w / img.width
            thumbs.append((label, img.resize((thumb_w, int(img.height * ratio)))))
    cell_h = max(t.height for _, t in thumbs) + 40
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * thumb_w, rows * cell_h), "#111111")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype(str(FONTS / "NotoSans-Bold.ttf"), 22)
    for n, (label, thumb) in enumerate(thumbs):
        x, y = (n % columns) * thumb_w, (n // columns) * cell_h
        sheet.paste(thumb, (x, y + 40))
        draw.text((x + 8, y + 8), label, font=font, fill="#FFFFFF")
    sheet.save(out, quality=88)
