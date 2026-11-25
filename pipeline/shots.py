"""Stage: moving shots, decided per shot by motion.mode (pipeline/engines.py).

Paid modes buy one image-to-video clip each (WaveSpeed Wan 2.2 480p by
default); free modes need none. For every selected shot this stage:
  1. buys the clip if a paid mode needs one and it is not cached, within
     video.max_paid_clips and video.budget_usd for this run. A shot over the
     limit is not bought: assembly falls back to parallax or a slow pan;
  2. for masked_i2v and cinemagraph, finds the mask (Gemini draws a box round
     motion.mask.target on the keyframe, or the storyboard gives regions) and
     composites the clip onto the still as one loop cycle;
  3. estimates a depth map of the keyframe (parallax shots, and paid shots so
     they can fall back to parallax).
Work that depends on a shot's final length (RIFE retiming, looping, parallax
rendering) happens in assembly, where narration timing has fixed that length.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import motion
from . import runlog
from . import storyboard as sbmod
from .cache import StageCache, key_for, sha256_file, write_atomic
from .config import ROOT, ConfigError, Project
from .engines import MODES, VIDEO_ENGINES
from .providers import route, wavespeed
from .retry import ProviderError, QuotaExhausted, RetryableError

VIDEO_DEFAULTS = {"max_paid_clips": 7, "budget_usd": 0.6, "interpolation": "rife", "rife_model": motion.RIFE_MODEL}
MAX_ATTEMPTS = 3
VISION_FALLBACKS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
COMPOSITE_VERSION = 1
DEPTH_VERSION = 1
DEPTH_SIZE = (768, 1344)


def settings(sb: dict[str, Any]) -> dict[str, Any]:
    return {**VIDEO_DEFAULTS, **{k: v for k, v in sb.get("video", {}).items() if k != "kaggle"}}


def engine_name(sb: dict[str, Any], shot: dict[str, Any]) -> str:
    return shot["motion"].get("engine") or sb["models"]["video"]


def clip_spec(sb: dict[str, Any], shot: dict[str, Any], keyframe: Path, end: Path | None) -> dict[str, Any]:
    name = engine_name(sb, shot)
    return {"v": 1, "engine": name, "model": VIDEO_ENGINES[name]["model"], "keyframe": sha256_file(keyframe),
            "end": sha256_file(end) if end else None, "prompt": sbmod.motion_prompt(sb, shot),
            "negative": sb["style"]["negative"], "seed": shot["motion"].get("seed", shot["keyframe"]["seed"]),
            "clip_s": shot["motion"].get("clip_s", 5)}


def parse_boxes(text: str) -> list[list[float]]:
    """Boxes as [ymin, xmin, ymax, xmax] on 0-1000, from any of the shapes Gemini answers with:
    {"boxes": [[...]]}, [[...]], or its native detection list [{"box_2d": [...], "label": ...}]."""
    data = json.loads(text)
    items = data.get("boxes", data.get("box_2d", [])) if isinstance(data, dict) else data
    if items and isinstance(items[0], (int, float)):
        items = [items]
    boxes = []
    for item in items or []:
        box = item.get("box_2d") or item.get("box") if isinstance(item, dict) else item
        if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
            boxes.append([float(v) for v in box])
    return boxes


def locate(project: Project, sb: dict[str, Any], shot: dict[str, Any], keyframe: Path) -> list[dict[str, Any]]:
    """Mask regions for a shot: the storyboard's own, or boxes Gemini draws round motion.mask.target."""
    mask = shot["motion"]["mask"]
    if mask.get("regions"):
        return mask["regions"]
    cache = StageCache(project, "shots/masks")
    spec = {"v": 1, "keyframe": sha256_file(keyframe), "target": mask["target"]}
    key = key_for(spec)
    hit = cache.hit(shot["id"], key, ".json")
    if hit:
        return json.loads(hit.read_text("utf-8"))["regions"]
    prompt = (f"Find {mask['target']} in this image. Return JSON only: {{\"boxes\": [[ymin, xmin, ymax, xmax], ...]}} "
              "with coordinates from 0 to 1000. Cover everything that should move, using at most 3 boxes.")
    # Any vision model will do. Gemini first, since it is trained to find boxes; the Lite ones are
    # busy less often (all three Flash models were out at once). Claude and the rest after that.
    named = sbmod.model_list(sb["models"]["script"])
    gemini_first = [m for m in named if route.provider_of(m) == "gemini"] + VISION_FALLBACKS
    models = list(dict.fromkeys(gemini_first + named))
    text, used = route.generate_text(project, stage="shots", item=f"{shot['id']}-mask", json_mode=True,
                                     models=models, temperature=0.0, prompt=prompt, image=keyframe)
    regions = []
    for ymin, xmin, ymax, xmax in parse_boxes(text)[:3]:
        pad_x, pad_y = (xmax - xmin) * 0.12, (ymax - ymin) * 0.12
        x0, y0 = max(0.0, (xmin - pad_x) / 1000), max(0.0, (ymin - pad_y) / 1000)
        x1, y1 = min(1.0, (xmax + pad_x) / 1000), min(1.0, (ymax + pad_y) / 1000)
        if x1 > x0 and y1 > y0:
            regions.append({"shape": "ellipse", "x": round(x0, 4), "y": round(y0, 4),
                            "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)})
    if not regions:
        raise ProviderError(f"{shot['id']}: the model found no '{mask['target']}' on the keyframe")
    path = cache.path(shot["id"], key, ".json")
    write_atomic(path, json.dumps({"regions": regions, "model": used}, indent=2).encode("utf-8"))
    cache.record(shot["id"], key, path, spec, model=used)
    return regions


def _buy(project: Project, sb: dict[str, Any], shot: dict[str, Any], spec: dict[str, Any], keyframe: Path,
         end: Path | None, raw: StageCache, key: str) -> Path:
    engine = VIDEO_ENGINES[spec["engine"]]
    if engine["provider"] != "wavespeed":
        raise ProviderError(f"engine {spec['engine']} runs as a Kaggle batch: `python -m pipeline shots --kaggle`")
    video, info = wavespeed.image_to_video(project, stage="shots", item=shot["id"], model=engine["model"],
                                           price_usd=engine["usd"][spec["clip_s"]], image=keyframe,
                                           prompt=spec["prompt"], negative=spec["negative"], seed=spec["seed"],
                                           clip_s=spec["clip_s"], last_image=end)
    path = raw.path(shot["id"], key, ".mp4")
    write_atomic(path, video)
    probe = motion.probe_video(path)
    raw.record(shot["id"], key, path, spec, task=info["task"], usd=engine["usd"][spec["clip_s"]],
               width=probe["width"], height=probe["height"], fps=probe["fps"], seconds=round(probe["duration"], 2))
    return path


def run(project: Project, *, only: set[str] | None = None, force: bool = False,
        max_paid: int | None = None) -> dict[str, Any]:
    sb = sbmod.load_valid(project)
    video = settings(sb)
    limit = video["max_paid_clips"] if max_paid is None else max_paid
    keyframes = StageCache(project, "keyframes")
    raw = StageCache(project, "shots/raw")
    composites = StageCache(project, "shots")
    depths = StageCache(project, "depth")
    spent, bought, report = 0.0, 0, {}
    for shot in sb["shots"]:
        sid, mode = shot["id"], shot["motion"]["mode"]
        if only is not None and sid not in only:
            continue
        keyframe = keyframes.current(sid)
        if keyframe is None:
            report[sid] = "no keyframe yet (make keyframes)"
            continue
        status = []
        if mode == "parallax" or MODES[mode]["paid"]:
            dspec = {"v": DEPTH_VERSION, "keyframe": sha256_file(keyframe), "model": motion.DEPTH_FILE}
            dkey = key_for(dspec)
            if not depths.hit(sid, dkey, ".png"):
                dpath = depths.path(sid, dkey, ".png")
                motion.save_depth(motion.depth_map(keyframe, DEPTH_SIZE), dpath)
                depths.record(sid, dkey, dpath, dspec)
                status.append("depth made")
        if MODES[mode]["paid"]:
            end = keyframes.current(f"{sid}_end") if mode == "flf_inbetween" else None
            if mode == "flf_inbetween" and end is None:
                report[sid] = "no end keyframe yet (make keyframes)"
                continue
            spec = clip_spec(sb, shot, keyframe, end)
            key = key_for(spec)
            clip = raw.hit(sid, key, ".mp4")
            if clip is None or force:
                tries = raw.entry(f"{sid}#attempts") or {}
                count = tries.get("count", 0) if tries.get("key") == key else 0
                price = VIDEO_ENGINES[spec["engine"]]["usd"].get(spec["clip_s"], 0.0)
                if count >= MAX_ATTEMPTS:
                    status.append(f"{count} failed attempts: falls back")
                elif bought >= limit or spent + price > video["budget_usd"] + 1e-9:
                    status.append(f"not bought: limit is {limit} clip(s) / ${video['budget_usd']:.2f} this run")
                else:
                    try:
                        clip = _buy(project, sb, shot, spec, keyframe, end, raw, key)
                        bought, spent = bought + 1, spent + price
                        status.append(f"clip bought (${price:.2f})")
                    except QuotaExhausted as exc:
                        status.append(f"no credit left ({exc}): falls back")
                        limit = bought  # stop buying for the rest of the run
                    except ConfigError as exc:  # a fresh clone with no keys still builds the film
                        status.append(f"not bought ({exc}): falls back")
                        limit = bought
                    except (ProviderError, RetryableError) as exc:
                        raw.manifest[f"{sid}#attempts"] = {"key": key, "count": count + 1, "error": str(exc)[:300],
                                                           "file": ""}
                        raw.save()
                        status.append(f"clip failed (attempt {count + 1} of {MAX_ATTEMPTS}): {exc}")
            else:
                status.append("clip cached")
            if clip is not None and mode in ("masked_i2v", "cinemagraph"):
                try:
                    regions = locate(project, sb, shot, keyframe)
                except (ProviderError, RetryableError, QuotaExhausted, ValueError, ConfigError) as exc:
                    status.append(f"mask not found ({' '.join(str(exc).split())[:120]}): falls back until the next run")
                    report[sid] = "; ".join(status)
                    continue
                mask = shot["motion"]["mask"]
                cspec = {"v": COMPOSITE_VERSION, "clip": sha256_file(clip), "still": sha256_file(keyframe),
                         "regions": regions, "feather": mask.get("feather", 0.012), "align": mask.get("align", True),
                         "loop": shot["motion"].get("loop", "pingpong")}
                ckey = key_for(cspec)
                if not composites.hit(sid, ckey, ".mp4"):
                    out = composites.path(sid, ckey, ".mp4")
                    info = motion.masked_composite(keyframe, clip, out, regions=regions, feather=cspec["feather"],
                                                   align=cspec["align"], loop=cspec["loop"])
                    composites.record(sid, ckey, out, cspec, **info)
                    status.append(f"composited ({info['frames']} frames, mask {info['mask_area']:.0%} of frame)")
        report[sid] = "; ".join(status) or "nothing to do (made in assembly)"
    for sid, line in report.items():
        print(f"  {sid}: {line}")
    print(f"  shots: {bought} clip(s) bought this run, ${spent:.2f} at list price")
    return report


def kaggle_batch(project: Project, *, only: set[str] | None = None) -> None:
    """Fallback engine: render every pending kaggle-wan22-ti2v-5b shot in one Kaggle job.
    Kept from the first design (FAILURES.md F12); not run end to end."""
    from .providers import kaggle_runner

    sb = sbmod.load_valid(project)
    keyframes = StageCache(project, "keyframes")
    raw = StageCache(project, "shots/raw")
    settings_k = {"width": 480, "height": 832, "frames": 81, "steps": 30, "guidance": 5.0, "flow_shift": 3.0,
                  "dtype": "fp16", "budget_min": 75, **sb.get("video", {}).get("kaggle", {})}
    pending = []
    for shot in sbmod.paid_clips(sb):
        if engine_name(sb, shot) != "kaggle-wan22-ti2v-5b" or (only and shot["id"] not in only):
            continue
        keyframe = keyframes.current(shot["id"])
        if keyframe is None:
            continue
        spec = clip_spec(sb, shot, keyframe, None) | {k: settings_k[k] for k in ("width", "height", "frames", "steps")}
        key = key_for(spec)
        if not raw.hit(shot["id"], key, ".mp4"):
            pending.append((shot, keyframe, spec, key))
    if not pending:
        print("  kaggle: nothing to render")
        return
    job = {"model": VIDEO_ENGINES["kaggle-wan22-ti2v-5b"]["model"], **{k: settings_k[k] for k in
           ("width", "height", "steps", "guidance", "flow_shift", "dtype")}, "budget_s": int(settings_k["budget_min"] * 60),
           "items": [{"id": s["id"], "image": f"{s['id']}{kf.suffix}", "prompt": spec["prompt"], "seed": spec["seed"],
                      "frames": settings_k["frames"]} for s, kf, spec, _ in pending]}
    out_dir, results = kaggle_runner.run_job(project, stage="shots", slug="heritage-wan-shots",
                                             kernel_script=ROOT / "pipeline" / "kaggle" / "wan_i2v.py", job=job,
                                             inputs={f"{s['id']}{kf.suffix}": kf for s, kf, _, _ in pending},
                                             model=job["model"], max_wait_s=4 * 3600)
    for shot, _, spec, key in pending:
        item = results.get("items", {}).get(shot["id"], {})
        ok = item.get("status") == "ok" and (out_dir / item.get("file", "")).exists()
        runlog.append(project, runlog.Call(stage="shots", item=shot["id"], provider="kaggle", model=job["model"],
                                           seed=spec["seed"], status="ok" if ok else "error",
                                           latency_s=item.get("latency_s"), gpu_s=item.get("latency_s"),
                                           error=None if ok else item.get("error") or results.get("fatal")))
        if ok:
            path = raw.path(shot["id"], key, ".mp4")
            shutil.copy2(out_dir / item["file"], path)
            raw.record(shot["id"], key, path, spec)
