"""Kaggle job: FLUX.2 klein 4B stills for the pictures in job.json.

The same model Cloudflare runs, so a batch drawn here matches the look of the
rest. Runs on one of Kaggle's free T4s. Plan:
  1. install diffusers from main (Flux2KleinPipeline is new) and load the model
     with CPU offload (transformer and Qwen3 text encoder do not fit on 15 GB together);
  2. draw the items in order. An item's references are input files or, as
     {"item": id}, a picture drawn earlier in this job (an end frame takes its
     start frame), so one job covers a whole run;
  3. fp16 first, since the T4 has no fast bf16; if a picture comes out NaN or
     black, switch the pipeline to bf16 once and draw it again;
  4. write each picture as soon as it is done and keep results.json current, so a
     session that dies early still returns everything it finished.
"""
import glob
import json
import os
import subprocess
import time
import traceback

T0 = time.time()
INPUT = os.path.dirname(glob.glob("/kaggle/input/**/job.json", recursive=True)[0])
JOB = json.load(open(os.path.join(INPUT, "job.json")))
OUT = "/kaggle/working"
RESULTS = {"job_id": JOB["job_id"], "items": {}, "events": [], "settings": {k: v for k, v in JOB.items() if k != "items"}}


def save():
    RESULTS["gpu_seconds"] = round(time.time() - T0, 1)
    with open(os.path.join(OUT, "results.json"), "w") as fh:
        json.dump(RESULTS, fh, indent=2, ensure_ascii=False)


def log(message):
    stamp = round(time.time() - T0, 1)
    print(f"[{stamp:7.1f}s] {message}", flush=True)
    RESULTS["events"].append([stamp, message])


def main():
    save()
    log("installing diffusers")
    subprocess.run("pip install -q -U git+https://github.com/huggingface/diffusers.git transformers accelerate",
                   shell=True, check=True)
    import numpy as np
    import torch
    from diffusers import Flux2KleinPipeline
    from PIL import Image

    RESULTS["gpu_name"] = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                         capture_output=True, text=True).stdout.strip().replace("\n", " + ")
    import diffusers
    RESULTS["versions"] = {"torch": torch.__version__, "diffusers": diffusers.__version__}
    dtype = torch.float16 if JOB.get("dtype", "fp16") == "fp16" else torch.bfloat16

    t = time.time()
    pipe = Flux2KleinPipeline.from_pretrained(JOB["model"], torch_dtype=dtype, cache_dir="/tmp/hf")
    pipe.enable_model_cpu_offload()
    RESULTS["load_s"] = round(time.time() - t, 1)
    log(f"pipeline ready in {RESULTS['load_s']}s on {RESULTS['gpu_name']}")

    drawn = {}

    def reference(ref):
        path = drawn.get(ref["item"]) if "item" in ref else os.path.join(INPUT, ref["file"])
        if not path or not os.path.exists(path):
            raise RuntimeError(f"reference {ref} was not drawn")
        return Image.open(path).convert("RGB")

    def draw(item):
        refs = [reference(r) for r in item.get("refs", [])]
        generator = torch.Generator(device="cpu").manual_seed(item["seed"])
        with torch.inference_mode():
            image = pipe(prompt=item["prompt"], image=refs or None, width=item["width"], height=item["height"],
                         num_inference_steps=JOB["steps"], guidance_scale=JOB["guidance"],
                         generator=generator).images[0]
        pixels = np.asarray(image, dtype=np.float32)
        if not np.isfinite(pixels).all() or float(pixels.mean()) < 2.0:
            raise FloatingPointError("NaN or black picture (fp16 overflow?)")
        return image

    for item in JOB["items"]:
        iid = item["id"]
        if time.time() - T0 > JOB.get("budget_s", 3600):
            RESULTS["items"][iid] = {"status": "skipped", "error": "time budget spent"}
            log(f"{iid}: skipped, budget spent")
            save()
            continue
        try:
            t = time.time()
            try:
                image = draw(item)
            except FloatingPointError:
                if dtype == torch.bfloat16:
                    raise
                log(f"{iid}: NaN or black in fp16; switching to bf16")
                dtype = torch.bfloat16
                pipe.to(torch.bfloat16)
                RESULTS["settings"]["dtype"] = "bf16"
                image = draw(item)
            path = os.path.join(OUT, f"{iid}.png")
            image.save(path)
            drawn[iid] = path
            latency = round(time.time() - t, 1)
            RESULTS["items"][iid] = {"status": "ok", "file": f"{iid}.png", "latency_s": latency}
            log(f"{iid}: done in {latency}s")
        except Exception as exc:
            RESULTS["items"][iid] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:500]}
            log(f"{iid}: FAILED {exc}")
            traceback.print_exc()
            torch.cuda.empty_cache()
        save()


try:
    main()
except Exception as exc:
    RESULTS["fatal"] = f"{type(exc).__name__}: {exc}"[:1000]
    traceback.print_exc()
finally:
    save()
    log("finished")
