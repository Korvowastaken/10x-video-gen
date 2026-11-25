"""Kaggle smoke job: proves the push -> run -> download loop, the GPU and internet access."""
import glob
import json
import subprocess
import time
import urllib.request

started = time.time()
job = json.load(open(glob.glob("/kaggle/input/**/job.json", recursive=True)[0]))
info = {"job_id": job["job_id"]}
info["gpu_name"] = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                  capture_output=True, text=True).stdout.strip()
try:
    import torch

    info.update(torch=torch.__version__, cuda=torch.cuda.is_available(), devices=torch.cuda.device_count())
except Exception as exc:  # report, do not crash: this job exists to report
    info["torch_error"] = str(exc)
try:
    urllib.request.urlopen("https://huggingface.co", timeout=15)
    info["internet"] = True
except Exception as exc:
    info["internet"] = f"no: {exc}"
info["disk_free_gb"] = round(int(subprocess.run(["df", "--output=avail", "-B1", "/tmp"], capture_output=True,
                                                text=True).stdout.split()[-1]) / 1e9, 1)
info["gpu_seconds"] = round(time.time() - started, 1)
json.dump(info, open("/kaggle/working/results.json", "w"), indent=2)
print(json.dumps(info, indent=2))
