"""Kaggle job: Wan 2.2 TI2V-5B image-to-video for the shots in job.json.

Runs on Kaggle's "GPU T4 x2". Plan:
  1. encode every prompt once with UMT5 (bf16 for numerical safety; few calls,
     so speed does not matter), then free it;
  2. load one Wan transformer on each T4 (fp16: the T4 has no fast bf16) and
     render half of the shots on each GPU, in two threads;
  3. write each clip as soon as it is done and keep results.json current, so a
     session that dies early still returns everything it finished;
  4. stop starting new shots once the time budget is spent (the weekly quota).
"""
import gc
import glob
import json
import os
import subprocess
import threading
import time
import traceback

T0 = time.time()
INPUT = os.path.dirname(glob.glob("/kaggle/input/**/job.json", recursive=True)[0])
JOB = json.load(open(os.path.join(INPUT, "job.json")))
OUT = "/kaggle/working"
RESULTS = {"job_id": JOB["job_id"], "items": {}, "events": [], "settings": {k: v for k, v in JOB.items() if k != "items"}}
LOCK = threading.Lock()
# Wan's official negative prompt, minus "style, artwork, painting", which would fight a stylised look.
WAN_NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，"
                "多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，"
                "三条腿，背景人很多，倒着走")


def save():
    with LOCK:
        RESULTS["gpu_seconds"] = round(time.time() - T0, 1)
        with open(os.path.join(OUT, "results.json"), "w") as fh:
            json.dump(RESULTS, fh, indent=2, ensure_ascii=False)


def log(message):
    stamp = round(time.time() - T0, 1)
    print(f"[{stamp:7.1f}s] {message}", flush=True)
    with LOCK:
        RESULTS["events"].append([stamp, message])


def main():
    save()
    log("installing diffusers")
    subprocess.run("pip install -q -U diffusers transformers accelerate ftfy imageio imageio-ffmpeg",
                   shell=True, check=True)
    import numpy as np
    import torch
    from diffusers import AutoencoderKLWan, UniPCMultistepScheduler, WanImageToVideoPipeline, WanTransformer3DModel
    from diffusers.utils import export_to_video
    from huggingface_hub import snapshot_download
    from PIL import Image
    from transformers import AutoTokenizer, UMT5EncoderModel

    RESULTS["gpu_name"] = subprocess.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                                         capture_output=True, text=True).stdout.strip().replace("\n", " + ")
    RESULTS["versions"] = {"torch": torch.__version__}
    import diffusers
    RESULTS["versions"]["diffusers"] = diffusers.__version__
    dtype = torch.float16 if JOB.get("dtype", "fp16") == "fp16" else torch.bfloat16
    width, height = JOB["width"], JOB["height"]
    gpus = list(range(min(torch.cuda.device_count(), JOB.get("max_gpus", 2))))
    log(f"gpus: {RESULTS['gpu_name']} -> using {gpus}")

    t = time.time()
    path = snapshot_download(JOB["model"], cache_dir="/tmp/hf")
    RESULTS["download_s"] = round(time.time() - t, 1)
    log(f"weights ready in {RESULTS['download_s']}s")

    # 1. prompts -> embeddings, once
    t = time.time()
    tokenizer = AutoTokenizer.from_pretrained(path, subfolder="tokenizer")
    encoder = UMT5EncoderModel.from_pretrained(path, subfolder="text_encoder", torch_dtype=torch.bfloat16)
    text_device = f"cuda:{gpus[-1]}"
    encoder.to(text_device)

    def encode(text):
        """Same as diffusers' WanPipeline._get_t5_prompt_embeds: clean, pad to 512, zero the padding."""
        import html
        import re
        import ftfy
        text = re.sub(r"\s+", " ", html.unescape(html.unescape(ftfy.fix_text(text)))).strip()
        tokens = tokenizer([text], padding="max_length", max_length=512, truncation=True,
                           add_special_tokens=True, return_attention_mask=True, return_tensors="pt")
        mask = tokens.attention_mask.to(text_device)
        length = int(mask.gt(0).sum())
        with torch.no_grad():
            hidden = encoder(tokens.input_ids.to(text_device), mask).last_hidden_state[0, :length]
        return torch.cat([hidden, hidden.new_zeros(512 - length, hidden.size(1))]).unsqueeze(0).to("cpu")

    negative = JOB.get("negative") or WAN_NEGATIVE
    negative_embeds = encode(negative)
    embeds = {item["id"]: (encode(item["prompt"]), negative_embeds) for item in JOB["items"]}
    del encoder
    gc.collect()
    torch.cuda.empty_cache()
    RESULTS["encode_s"] = round(time.time() - t, 1)
    log(f"encoded {len(embeds)} prompt(s) in {RESULTS['encode_s']}s")

    # 2. one pipeline per GPU
    pipes = {}
    for gpu in gpus:
        t = time.time()
        vae = AutoencoderKLWan.from_pretrained(path, subfolder="vae", torch_dtype=torch.float32)
        transformer = WanTransformer3DModel.from_pretrained(path, subfolder="transformer", torch_dtype=dtype)
        pipe = WanImageToVideoPipeline.from_pretrained(path, transformer=transformer, vae=vae, text_encoder=None,
                                                       tokenizer=None, torch_dtype=dtype)
        if JOB.get("flow_shift"):
            pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config, flow_shift=JOB["flow_shift"])
        pipe.to(f"cuda:{gpu}")
        if hasattr(pipe.vae, "enable_tiling"):
            pipe.vae.enable_tiling()
        pipes[gpu] = pipe
        gc.collect()
        log(f"pipeline on cuda:{gpu} in {time.time() - t:.0f}s")

    def fit(image):
        """Cover-crop the keyframe to the target aspect, then resize."""
        target = width / height
        w, h = image.size
        if w / h > target:
            new_w = int(h * target)
            image = image.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
        else:
            new_h = int(w / target)
            image = image.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
        return image.resize((width, height), Image.LANCZOS)

    def worker(gpu, items):
        pipe = pipes[gpu]
        device = f"cuda:{gpu}"
        for item in items:
            sid = item["id"]
            if time.time() - T0 > JOB.get("budget_s", 3600):
                RESULTS["items"][sid] = {"status": "skipped", "error": "time budget spent"}
                log(f"{sid}: skipped, budget spent")
                save()
                continue
            try:
                image = fit(Image.open(os.path.join(INPUT, item["image"])).convert("RGB"))
                pos, neg = embeds[sid]
                generator = torch.Generator(device=device).manual_seed(item["seed"])
                t = time.time()
                with torch.inference_mode():
                    frames = pipe(image=image, prompt_embeds=pos.to(device, dtype), negative_prompt_embeds=neg.to(device, dtype),
                                  height=height, width=width, num_frames=item["frames"],
                                  num_inference_steps=JOB["steps"], guidance_scale=JOB["guidance"],
                                  generator=generator, output_type="np").frames[0]
                latency = round(time.time() - t, 1)
                frames = np.nan_to_num(frames, nan=-1.0)
                if (frames < 0).any() or float(frames.mean()) < 0.02:
                    raise RuntimeError("NaN or black frames (fp16 overflow?)")
                export_to_video(list(frames), os.path.join(OUT, f"{sid}.mp4"), fps=24)
                RESULTS["items"][sid] = {"status": "ok", "file": f"{sid}.mp4", "latency_s": latency, "gpu": gpu,
                                         "frames": item["frames"], "peak_mem_gb": round(torch.cuda.max_memory_allocated(device) / 1e9, 1)}
                log(f"{sid}: done on cuda:{gpu} in {latency}s")
            except Exception as exc:
                RESULTS["items"][sid] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:500]}
                log(f"{sid}: FAILED {exc}")
                traceback.print_exc()
                torch.cuda.empty_cache()
            save()

    threads = [threading.Thread(target=worker, args=(gpu, JOB["items"][i::len(gpus)])) for i, gpu in enumerate(gpus)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


try:
    main()
except Exception as exc:
    RESULTS["fatal"] = f"{type(exc).__name__}: {exc}"[:1000]
    traceback.print_exc()
finally:
    save()
    log("finished")
