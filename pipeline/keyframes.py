"""Stage: keyframes. Reference sheets first, then one still per shot conditioned on them.

The order follows the brief's "lock the look first":
  1. a reference sheet per visible character (a few seeds; storyboard.json's
     reference.chosen marks the approved one) and an establishing image per
     location;
  2. each shot's keyframe from FLUX.2 klein, given the approved references of the
     characters and the place in that shot as input images, and, when a slot is
     left, the shot's layout guide (sketch.py): outline figures with limbs
     showing where each person stands, how big they appear and which way they face.
A keyframe's cache key includes the hashes of its references, so approving a
different character sheet regenerates exactly the shots that character is in.

Fallback: each picture goes down the storyboard's image chain. Cloudflare and
Gemini answer one picture at a time; when FLUX.2 fails or its daily allowance
is gone, the next model takes over (FLUX.1 schnell takes no references and no
seed). A Kaggle model in the chain is a batch: every picture that reaches it is
left for one GPU job at the end of the pass (sheets in references(), stills and
their end frames in run()), and a picture that job cannot draw goes on down the
chain. runs.jsonl records which model drew each image.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import jobs, keys, paused, runlog, sketch, switch
from . import storyboard as sbmod
from .cache import StageCache, key_for, sha256_file, write_atomic
from .config import FONTS, ROOT, ConfigError, Project
from .engines import IMAGE_KAGGLE
from .providers import cloudflare, gemini
from .retry import EXHAUSTED, ProviderError, QuotaExhausted, RetryableError

KEYFRAME_SIZE = (768, 1344)   # about 9:16, multiples of 16: 6 output tiles on Workers AI
REFERENCE_SIZE = (768, 1024)  # character sheet, full body: 4 tiles
MAX_REFERENCES = 4
REF_NOTE = ("Keep every character's face, hair, skin tone and clothes exactly as in the character reference "
            "images, and the place's colours and light as in the location reference image.")
LAYOUT_NOTE = ("The last input image is a composition sketch in thin black outlines, not part of the scene: "
               "frame the shot so each person stands where an outline is, at its size, turned the same way (the "
               "small point on a head shows where they face) and with arms and legs posed as drawn, the first "
               "character on the left outline. Draw no outlines, white areas or extra people from it.")


def service_of(model: str) -> str:
    if model.startswith("@cf/"):
        return "cloudflare"
    if model in IMAGE_KAGGLE:
        return "kaggle"
    if gemini.is_image_model(model):
        return "gemini"
    raise ConfigError(f"{model} is not a picture model")


def takes_references(model: str) -> bool:
    """FLUX.2 (on Cloudflare or Kaggle) and Gemini draw from reference images; FLUX.1 schnell does not."""
    return "flux-2" in model or gemini.is_image_model(model)


def _inputs(model: str, prompt: str, references: list[Any], layout: Path | None) -> tuple[str, list[Any]]:
    """The prompt and images this model is sent: references and the layout guide only if it takes them."""
    if not takes_references(model):
        return prompt, []
    refs, text = list(references), (f"{prompt} {REF_NOTE}" if references else prompt)
    if layout is not None:
        refs, text = [*refs, layout], f"{text} {LAYOUT_NOTE}"
    return text, refs[:MAX_REFERENCES]


class Deferred(Exception):
    """The chain reached a Kaggle model: the picture waits for this pass's batch."""

    def __init__(self, model: str, after: list[str]):
        super().__init__(model)
        self.model, self.after = model, after


def _generate(project: Project, *, item: str, models: list[str], prompt: str, seed: int,
              size: tuple[int, int], references: list[Path], layout: Path | None = None,
              batch: bool = False, failed: str | None = None,
              failed_exc: Exception | None = None) -> tuple[bytes, str, str]:
    """Draw with the first model in the chain that answers. A model whose service has no key
    or is paused is skipped; a Kaggle model raises Deferred when `batch` (else it is skipped).
    After a failed call, the person is asked before another service is used (switch.py);
    `failed` names a service that already failed before this chain (the Kaggle batch)."""
    last: Exception | None = failed_exc
    for i, model in enumerate(models):
        service = service_of(model)
        if model in EXHAUSTED:  # used up earlier in this run: moving past it is still a switch
            last, failed = last or QuotaExhausted(f"{model} is out of quota"), failed or service
            continue
        if not keys.slots(service):
            last = last or ConfigError(f"no {keys.SERVICES[service]['label']} key is saved")
            continue
        if paused.is_paused(service):
            last = last or ConfigError(f"{keys.SERVICES[service]['label']} is paused")
            continue
        if service == "kaggle" and not batch:
            continue
        if failed:
            switch.allow(failed, last, service, what="pictures")
        if service == "kaggle":
            raise Deferred(model, models[i + 1:])
        text, refs = _inputs(model, prompt, references, layout)
        draw = gemini.generate_image if service == "gemini" else cloudflare.generate_image
        try:
            data, ext = draw(project, stage="keyframes", item=item, model=model, prompt=text, seed=seed,
                             width=size[0], height=size[1], references=refs)
            return data, ext, model
        except QuotaExhausted as exc:
            if service == "gemini":  # Cloudflare's allowance is per account: key switching covers it
                EXHAUSTED.add(model)
            last, failed = exc, service
            print(f"    {item}: {model} failed ({' '.join(str(exc).split())[:120]}); trying the next model")
        except (RetryableError, ProviderError, ConfigError) as exc:
            last, failed = exc, service
            print(f"    {item}: {model} failed ({' '.join(str(exc).split())[:120]}); trying the next model")
    if last is None:
        raise ConfigError(f"no picture model is left to try in {models}")
    raise last


@dataclass
class Pending:
    """A picture left for the Kaggle batch. `references` may hold another Pending (an end
    frame's start frame); `spec_of` gives the cache spec once every reference exists."""
    cache: StageCache
    item: str
    prompt: str
    seed: int
    size: tuple[int, int]
    references: list[Any]
    layout: Path | None
    spec_of: Callable[[list[Path]], dict[str, Any]]
    model: str
    after: list[str]
    path: Path | None = None


# Spec fields that alone never make a picture out of date. Which model drew it is a setting:
# reordering the image models, or a run falling back to the next one, keeps every picture.
# A scene's still is also kept when a sheet it was drawn from is redrawn. Redrawing one
# scene by hand (force) still draws it with today's model and sheets.
SHEET_FREE = ("model",)
STILL_FREE = ("model", "refs")


def _store(cache: StageCache, item: str, key: str, spec: dict[str, Any], data: bytes, ext: str, used: str,
           references: list[Path], layout: Path | None) -> Path:
    path = cache.path(item, key, ext)
    write_atomic(path, data)
    _, sent = _inputs(used, "", references, layout)
    cache.record(item, key, path, spec, model=used, references=[r.name for r in sent])
    return path


def _make(project: Project, cache: StageCache, *, item: str, spec: dict[str, Any], models: list[str],
          prompt: str, seed: int,
          size: tuple[int, int], references: list[Path], force: bool, counts: dict[str, int],
          layout: Path | None = None, batch: list[Pending] | None = None,
          free: tuple[str, ...] = ()) -> Path | Pending:
    """The cached picture, or a new one. With `batch`, a picture whose chain reaches Kaggle
    is added to it and returned as a Pending. A picture that differs only in the `free`
    fields is kept as it is (see SHEET_FREE); `force` draws it again anyway."""
    key = key_for(spec)
    hit = cache.usable(item, key, (".jpg", ".png"), spec, free)
    if hit and not force:
        counts["cached"] += 1
        exact = hit.stem == cache.path(item, key, "").name
        if exact and (cache.entry(item) is None or cache.entry(item).get("key") != key):
            cache.record(item, key, hit, spec)
        return hit
    try:
        data, ext, used = _generate(project, item=item, models=models, prompt=prompt, seed=seed,
                                    size=size, references=references, layout=layout, batch=batch is not None)
    except Deferred as wait:
        assert batch is not None
        pending = Pending(cache=cache, item=item, prompt=prompt, seed=seed, size=size, references=list(references),
                          layout=layout, spec_of=lambda _refs: spec, model=wait.model, after=wait.after)
        batch.append(pending)
        return pending
    counts["made"] += 1
    return _store(cache, item, key, spec, data, ext, used, references, layout)


# FLUX.2 klein 4B is step-distilled: 4 steps and no guidance, as its model card runs it.
KAGGLE_SETTINGS = {"steps": 4, "guidance": 1.0, "dtype": "fp16", "budget_min": 60}


def run_batch(project: Project, batch: list[Pending], counts: dict[str, int]) -> None:
    """Draw every Pending in one Kaggle job, then store each picture. One the job could not draw
    goes on down the rest of its chain, one picture at a time; if none of those draws it either,
    the first such error is raised once the others are stored."""
    if not batch:
        return
    from .providers import kaggle_runner

    settings = KAGGLE_SETTINGS
    model = batch[0].model
    inputs: dict[str, Path] = {}
    items = []
    for p in batch:
        text, refs = _inputs(model, p.prompt, p.references, p.layout)
        sent = []
        for ref in refs:
            if isinstance(ref, Pending):
                sent.append({"item": ref.item})
            else:
                name = f"{sha256_file(ref)[:16]}{ref.suffix.lower()}"
                inputs[name] = ref
                sent.append({"file": name})
        items.append({"id": p.item, "prompt": text, "seed": p.seed, "width": p.size[0], "height": p.size[1],
                      "refs": sent})
    job = {"model": IMAGE_KAGGLE[model]["model"], "steps": settings["steps"], "guidance": settings["guidance"],
           "dtype": settings["dtype"], "budget_s": int(settings["budget_min"] * 60), "items": items}
    print(f"  kaggle: drawing {len(items)} picture(s) in one GPU job (it takes several minutes to start)")
    results: dict[str, Any] = {}
    out_dir: Path | None = None
    try:
        out_dir, results = kaggle_runner.run_job(project, stage="keyframes", slug="heritage-flux2-images",
                                                 kernel_script=ROOT / "pipeline" / "kaggle" / "flux2_images.py",
                                                 job=job, inputs=inputs, model=model, max_wait_s=3 * 3600)
    except (QuotaExhausted, ProviderError, ConfigError) as exc:
        if isinstance(exc, QuotaExhausted):
            EXHAUSTED.add(model)
        results = {"fatal": str(exc)}
        print(f"  kaggle: the job failed ({' '.join(str(exc).split())[:160]}); trying the next models")
    failed: Exception | None = None
    for p in batch:
        refs = [r.path if isinstance(r, Pending) else r for r in p.references]
        if any(r is None for r in refs):
            failed = failed or ProviderError(f"{p.item}: a picture it is drawn from was not made")
            continue
        spec = p.spec_of(refs)
        key = key_for(spec)
        row = results.get("items", {}).get(p.item, {})
        made = out_dir / row["file"] if out_dir and row.get("status") == "ok" and row.get("file") else None
        ok = made is not None and made.exists()
        if out_dir is not None:  # a job that never ran was logged by run_job already
            runlog.append(project, runlog.Call(stage="keyframes", item=p.item, provider="kaggle", model=model,
                                               seed=p.seed, status="ok" if ok else "error",
                                               latency_s=row.get("latency_s"), gpu_s=row.get("latency_s"),
                                               error=None if ok else row.get("error") or results.get("fatal")))
        if ok:
            p.path = _store(p.cache, p.item, key, spec, made.read_bytes(), ".png", model, refs, p.layout)
            counts["made"] += 1
            continue
        jobs.check()  # a stopped studio job ends here rather than drawing the rest one by one
        try:
            data, ext, used = _generate(project, item=p.item, models=p.after, prompt=p.prompt, seed=p.seed,
                                        size=p.size, references=refs, layout=p.layout, failed="kaggle",
                                        failed_exc=ProviderError(row.get("error") or results.get("fatal") or "not drawn"))
        except (QuotaExhausted, RetryableError, ProviderError, ConfigError) as exc:
            failed = failed or exc
            continue
        p.path = _store(p.cache, p.item, key, spec, data, ext, used, refs, p.layout)
        counts["made"] += 1
    if failed is not None:
        raise failed


def _done(value: Path | Pending) -> Path | None:
    return value.path if isinstance(value, Pending) else value


def character_ref_prompt(project: Project, sb: dict[str, Any], character: dict[str, Any]) -> tuple[str, Path | None]:
    prompt = sbmod.reference_prompt(sb, character)
    photo = _photo(project, character["reference"])
    if photo:
        prompt += (" Base the face, hair and build on the reference photo, drawn in the style above, "
                   "not as a photograph.")
    return prompt, photo


def location_ref_prompt(project: Project, sb: dict[str, Any], location: dict[str, Any]) -> tuple[str, Path | None]:
    prompt = sbmod.location_prompt(sb, location)
    photo = _photo(project, location["reference"])
    if photo:
        prompt += " Base the layout, landmarks and colours on the reference photo, drawn in the style above."
    return prompt, photo


def ref_spec(prompt: str, seed: int, model: str, size: tuple[int, int], photo: Path | None) -> dict[str, Any]:
    return {"v": 1, "prompt": prompt, "seed": seed, "model": model, "size": size,
            "photo": sha256_file(photo) if photo else None}


def guided(shot: dict[str, Any], refs: list[Path]) -> dict[str, Any] | None:
    """The shot's layout guide spec, if it has one and a reference slot is left for it.
    Likeness comes first: a full set of character and place sheets keeps every slot."""
    return sketch.layout_spec(shot) if len(refs) < MAX_REFERENCES else None


def keyframe_spec(sb: dict[str, Any], shot: dict[str, Any], model: str, refs: list[Path]) -> dict[str, Any]:
    spec = {"v": 1, "prompt": sbmod.image_prompt(sb, shot), "seed": shot["keyframe"]["seed"], "model": model,
            "size": KEYFRAME_SIZE, "refs": [sha256_file(r) for r in refs]}
    layout = guided(shot, refs)
    if layout is not None:
        spec["layout"] = key_for(layout)
    return spec


def end_keyframe_spec(sb: dict[str, Any], shot: dict[str, Any], model: str, start: Path,
                      refs: list[Path], place: Path | None) -> tuple[dict[str, Any], list[Path]]:
    """The end frame takes the start frame as its first reference, so both share one scene."""
    end_refs = [start] + [r for r in refs if r != place][:MAX_REFERENCES - 1]
    spec = {"v": 1, "prompt": sbmod.end_image_prompt(sb, shot), "seed": shot["motion"]["end_keyframe"]["seed"],
            "model": model, "size": KEYFRAME_SIZE, "refs": [sha256_file(r) for r in end_refs]}
    return spec, end_refs


def shot_refs(shot: dict[str, Any], approved: dict[str, Path]) -> list[Path]:
    """The approved sheets a keyframe is drawn from: its cast, then its place."""
    refs = [approved[c] for c in shot["characters"] if c in approved]
    place = approved.get(f"place:{shot['location']}")
    if place is not None:
        refs.append(place)
    return refs[:MAX_REFERENCES]


def references(project: Project, sb: dict[str, Any], *, force: bool = False,
               counts: dict[str, int] | None = None, needed: set[str] | None = None) -> dict[str, Path]:
    """Generate (or reuse) the reference candidates; return the approved one per character/location.

    `needed` limits work to the characters and places of the selected shots."""
    counts = counts if counts is not None else {"made": 0, "cached": 0}
    models = sbmod.model_list(sb["models"]["image"])
    cache = StageCache(project, "refs")
    approved: dict[str, Path | Pending] = {}
    batch: list[Pending] = []
    for character in sb["characters"]:
        jobs.check()  # a stopped studio job ends here, between items
        if not character["visible"] or (needed is not None and character["id"] not in needed):
            continue
        ref = character["reference"]
        prompt, photo = character_ref_prompt(project, sb, character)
        for i, seed in enumerate(ref["seeds"]):
            spec = ref_spec(prompt, seed, models[0], REFERENCE_SIZE, photo)
            path = _make(project, cache, item=f"char_{character['id']}_{i}", spec=spec, models=models, prompt=prompt,
                         seed=seed, size=REFERENCE_SIZE, references=[photo] if photo else [], force=force,
                         counts=counts, batch=batch, free=SHEET_FREE)
            if i == ref.get("chosen", 0):
                approved[character["id"]] = path
    for location in sb["locations"]:
        jobs.check()  # a stopped studio job ends here, between items
        ref = location.get("reference")
        if not ref or (needed is not None and location["id"] not in needed):
            continue
        prompt, photo = location_ref_prompt(project, sb, location)
        seed = ref["seeds"][ref.get("chosen", 0)]
        spec = ref_spec(prompt, seed, models[0], KEYFRAME_SIZE, photo)
        approved[f"place:{location['id']}"] = _make(
            project, cache, item=f"place_{location['id']}", spec=spec, models=models, prompt=prompt, seed=seed,
            size=KEYFRAME_SIZE, references=[photo] if photo else [], force=force, counts=counts, batch=batch,
            free=SHEET_FREE)
    try:
        run_batch(project, batch, counts)
    finally:
        contact_sheet([(name, p) for name, p in sorted(_all_current(cache).items())],
                      project.out("refs", "contact_sheet.jpg"), columns=4)
    return {k: path for k, v in approved.items() if (path := _done(v)) is not None}


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
    sheet: list[tuple[str, Path | Pending]] = []
    batch: list[Pending] = []
    for shot in sb["shots"]:
        jobs.check()  # a stopped studio job ends here, between items
        refs = shot_refs(shot, approved)
        place = approved.get(f"place:{shot['location']}")
        prompt = sbmod.image_prompt(sb, shot)
        spec = keyframe_spec(sb, shot, models[0], refs)
        selected = only is None or shot["id"] in only
        if not selected:  # ONLY=... limits generation; show what exists for the others
            for item in (shot["id"], f"{shot['id']}_end"):
                if cache.current(item):
                    sheet.append((item, cache.current(item)))
            continue
        layout = sketch.layout_file(project, shot) if "layout" in spec else None
        made_before = counts["made"]
        path = _make(project, cache, item=shot["id"], spec=spec, models=models, prompt=prompt, seed=shot["keyframe"]["seed"],
                     size=KEYFRAME_SIZE, references=refs, force=force, counts=counts, layout=layout, batch=batch,
                     free=STILL_FREE)
        # A new start frame needs a new end frame: the end is drawn from it (its first ref)
        end_free = SHEET_FREE if counts["made"] > made_before else STILL_FREE
        sheet.append((shot["id"], path))
        if shot["motion"]["mode"] == "flf_inbetween":
            item = f"{shot['id']}_end"
            if isinstance(path, Pending):  # the start frame waits for Kaggle, so its end frame does too
                end_refs = [path] + [r for r in refs if r != place][:MAX_REFERENCES - 1]
                end_spec_of = (lambda done, shot=shot, refs=refs, place=place:
                               end_keyframe_spec(sb, shot, models[0], done[0], refs, place)[0])
                end: Path | Pending = Pending(
                    cache=cache, item=item, prompt=sbmod.end_image_prompt(sb, shot),
                    seed=shot["motion"]["end_keyframe"]["seed"], size=KEYFRAME_SIZE, references=end_refs,
                    layout=None, spec_of=end_spec_of, model=path.model, after=path.after)
                batch.append(end)
            else:
                end_spec, end_refs = end_keyframe_spec(sb, shot, models[0], path, refs, place)
                end = _make(project, cache, item=item, spec=end_spec, models=models, prompt=end_spec["prompt"],
                            seed=end_spec["seed"], size=KEYFRAME_SIZE, references=end_refs, force=force,
                            counts=counts, batch=batch, free=end_free)
            sheet.append((item, end))
    try:
        run_batch(project, batch, counts)
    finally:
        contact_sheet([(name, path) for name, value in sheet if (path := _done(value)) is not None],
                      project.out("keyframes", "contact_sheet.jpg"), columns=5)
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
