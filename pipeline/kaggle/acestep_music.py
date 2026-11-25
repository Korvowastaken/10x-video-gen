"""Kaggle job: ACE-Step 1.5 score candidates for the seeds in job.json.

ACE-Step pins its own torch build, so it gets its own uv environment instead of
fighting the one Kaggle ships. The language-model planner is skipped: the
storyboard already fixes caption, tempo, key and length, and the diffusion
model alone follows them (generate_music skips the LM when none is given).
"""
import glob
import json
import os
import shutil
import subprocess
import time
import traceback

T0 = time.time()
INPUT = os.path.dirname(glob.glob("/kaggle/input/**/job.json", recursive=True)[0])
JOB = json.load(open(os.path.join(INPUT, "job.json")))
OUT = "/kaggle/working"
REPO = "/tmp/acestep"
RESULTS = {"job_id": JOB["job_id"], "items": {}, "events": []}

INNER = r'''
import inspect, json, os, shutil, sys, time
sys.path.insert(0, "/tmp/acestep")
from huggingface_hub import snapshot_download
job = json.load(open(sys.argv[1])); out = sys.argv[2]
report = {"items": {}}
t = time.time()
snapshot_download("ACE-Step/Ace-Step1.5", local_dir="/tmp/acestep/checkpoints",
                  ignore_patterns=["acestep-5Hz-lm-*/*"])
report["download_s"] = round(time.time() - t, 1)
from acestep.handler import AceStepHandler
from acestep.inference import GenerationConfig, GenerationParams, generate_music
dit = AceStepHandler()
kwargs = dict(project_root="/tmp/acestep", config_path=job.get("config", "acestep-v15-turbo"), device="cuda")
accepted = inspect.signature(dit.initialize_service).parameters
t = time.time()
status = dit.initialize_service(**{k: v for k, v in kwargs.items() if k in accepted})
report["load_s"] = round(time.time() - t, 1); report["init_status"] = str(status)[:300]
for index, seed in zip(job["indices"], job["seeds"]):
    params = GenerationParams(caption=job["caption"], lyrics="[Instrumental]", instrumental=True,
                              bpm=job["bpm"], keyscale=job["key"], timesignature=job["timesignature"],
                              duration=job["duration"], inference_steps=job.get("steps", 8), seed=seed,
                              shift=job.get("shift", 3.0), thinking=False, use_cot_metas=False,
                              use_cot_caption=False, use_cot_language=False)
    config = GenerationConfig(batch_size=1, use_random_seed=False, seeds=[seed], audio_format="wav")
    t = time.time()
    result = generate_music(dit, None, params, config, save_dir=f"/tmp/music/{index}")
    latency = round(time.time() - t, 1)
    if not result.success or not result.audios:
        report["items"][str(index)] = {"status": "error", "error": str(result.error)[:400], "latency_s": latency}
    else:
        audio = result.audios[0]
        name = f"candidate_{index}.wav"
        shutil.copy(audio["path"], os.path.join(out, name))
        report["items"][str(index)] = {"status": "ok", "file": name, "seed": seed, "latency_s": latency,
                                       "sample_rate": audio.get("sample_rate"), "key": audio.get("key")}
    print(json.dumps({index: report["items"][str(index)]}), flush=True)
    json.dump(report, open(os.path.join(out, "inner.json"), "w"), indent=2)
json.dump(report, open(os.path.join(out, "inner.json"), "w"), indent=2)
'''


def save():
    RESULTS["gpu_seconds"] = round(time.time() - T0, 1)
    json.dump(RESULTS, open(os.path.join(OUT, "results.json"), "w"), indent=2)


def log(message):
    print(f"[{time.time() - T0:7.1f}s] {message}", flush=True)
    RESULTS["events"].append([round(time.time() - T0, 1), message])


def sh(command):
    log(f"$ {command}")
    subprocess.run(command, shell=True, check=True)


try:
    save()
    RESULTS["gpu_name"] = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                         capture_output=True, text=True).stdout.strip().replace("\n", " + ")
    sh("pip install -q uv")
    sh(f"git clone --depth 1 https://github.com/ACE-Step/ACE-Step-1.5.git {REPO}")
    t = time.time()
    sh(f"cd {REPO} && UV_LINK_MODE=copy uv sync --quiet")
    RESULTS["install_s"] = round(time.time() - t, 1)
    with open("/tmp/inner.py", "w") as fh:
        fh.write(INNER)
    shutil.copy(os.path.join(INPUT, "job.json"), "/tmp/job.json")
    sh(f"cd {REPO} && CUDA_VISIBLE_DEVICES=0 uv run python /tmp/inner.py /tmp/job.json {OUT}")
    inner = json.load(open(os.path.join(OUT, "inner.json")))
    RESULTS.update({k: v for k, v in inner.items() if k != "items"})
    RESULTS["items"] = inner["items"]
except Exception as exc:
    RESULTS["fatal"] = f"{type(exc).__name__}: {exc}"[:1000]
    traceback.print_exc()
    inner_path = os.path.join(OUT, "inner.json")
    if os.path.exists(inner_path):
        RESULTS["items"] = json.load(open(inner_path)).get("items", {})
finally:
    save()
    log("finished")
