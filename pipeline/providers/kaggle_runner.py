"""Kaggle as a batch GPU, driven entirely from code.

A job is three API calls and a wait:
  1. upload the job (job.json + input files) as a private dataset version,
  2. push a script kernel that reads it, with a GPU and internet switched on,
  3. poll until the kernel finishes, then download /kaggle/working.

The kernel writes results.json echoing the job id, so a stale dataset version
is caught instead of silently reused.
"""
from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from .. import jobs, runlog
from ..config import Project
from ..retry import ProviderError, QuotaExhausted

ACCELERATOR = "NvidiaTeslaT4"  # Kaggle's free "GPU T4 x2"
TERMINAL = {"complete", "error", "cancel_acknowledged", "cancel_requested"}


class KaggleJobError(ProviderError):
    def __init__(self, message: str, log_path: Path | None = None):
        super().__init__(message)
        self.log_path = log_path


def api():
    """Authenticated KaggleApi. Imported lazily: the package checks credentials on import."""
    from kaggle.api.kaggle_api_extended import KaggleApi

    client = KaggleApi()
    client.authenticate()
    return client


def username(client) -> str:
    name = client.config_values.get("username")
    if not name:
        raise ProviderError("Kaggle authenticated but returned no username")
    return name


def gpu_quota(client) -> dict[str, Any]:
    """Remaining weekly GPU quota, for COSTS.md. Empty dict if the call is unavailable."""
    try:
        stats = client.quota_view()
    except Exception as exc:  # informational only
        return {"error": str(exc)[:200]}
    quota = getattr(stats, "gpu_quota", None)
    out: dict[str, Any] = {"refresh": str(getattr(stats, "quota_refresh_time", ""))}
    for attr in ("used_hours", "total_hours", "remaining_hours", "used_seconds", "total_seconds"):
        if quota is not None and hasattr(quota, attr):
            out[attr] = getattr(quota, attr)
    if quota is not None and len(out) == 1:
        out["raw"] = str(quota)[:300]
    return out


def _status_name(status_obj) -> str:
    raw = getattr(status_obj, "status", status_obj)
    name = getattr(raw, "name", str(raw))
    return name.split(".")[-1].lower()


def _wait_for_dataset(client, ref: str, timeout_s: int = 900) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            status = str(client.dataset_status(ref)).lower()
        except Exception as exc:  # brief 404s right after creation
            status = f"unknown ({exc})"
        if "ready" in status:
            return
        if "error" in status:
            raise ProviderError(f"Kaggle dataset {ref} failed to process: {status}")
        jobs.sleep(10)  # the upload is still processing: no GPU time used yet
    raise ProviderError(f"Kaggle dataset {ref} not ready after {timeout_s}s")


def run_job(project: Project, *, stage: str, slug: str, kernel_script: Path, job: dict[str, Any],
            inputs: dict[str, Path], model: str, accelerator: str = ACCELERATOR,
            poll_s: int = 30, max_wait_s: int = 4 * 3600) -> tuple[Path, dict[str, Any]]:
    """Run one batch job on Kaggle. Returns (download dir, results.json contents)."""
    client = api()
    user = username(client)
    job = dict(job)
    job["job_id"] = uuid.uuid4().hex[:12]
    staging = project.outputs / "_kaggle" / slug
    if staging.exists():
        shutil.rmtree(staging)
    dataset_dir, kernel_dir, output_dir = staging / "dataset", staging / "kernel", staging / "output"
    for folder in (dataset_dir, kernel_dir, output_dir):
        folder.mkdir(parents=True)

    for name, path in inputs.items():
        shutil.copy2(path, dataset_dir / name)
    (dataset_dir / "job.json").write_text(json.dumps(job, indent=2, ensure_ascii=False), "utf-8")
    dataset_ref = f"{user}/{slug}-inputs"
    (dataset_dir / "dataset-metadata.json").write_text(json.dumps({
        "title": f"{slug}-inputs", "id": dataset_ref, "licenses": [{"name": "CC0-1.0"}],
    }), "utf-8")

    shutil.copy2(kernel_script, kernel_dir / "main.py")
    kernel_ref = f"{user}/{slug}"
    (kernel_dir / "kernel-metadata.json").write_text(json.dumps({
        "id": kernel_ref, "title": slug, "code_file": "main.py", "language": "python",
        "kernel_type": "script", "is_private": "true", "enable_gpu": "true", "enable_internet": "true",
        "dataset_sources": [dataset_ref], "competition_sources": [], "kernel_sources": [], "model_sources": [],
    }, indent=2), "utf-8")

    params = {"accelerator": accelerator, "items": len(job.get("items", [])), "job_id": job["job_id"],
              "kernel": kernel_ref}
    with runlog.model_call(project, stage=stage, item=f"kaggle:{slug}", provider="kaggle", model=model,
                           params=params) as call:
        print(f"  kaggle: uploading {len(inputs)} input file(s) to {dataset_ref}")
        try:
            client.dataset_status(dataset_ref)
            exists = True
        except Exception:
            exists = False
        if exists:
            client.dataset_create_version(str(dataset_dir), version_notes=f"job {job['job_id']}",
                                          quiet=True, convert_to_csv=False, dir_mode="zip")
        else:
            client.dataset_create_new(str(dataset_dir), public=False, quiet=True,
                                      convert_to_csv=False, dir_mode="zip")
        _wait_for_dataset(client, dataset_ref)

        print(f"  kaggle: pushing kernel {kernel_ref} on {accelerator}")
        response = client.kernels_push(str(kernel_dir), acc=accelerator)
        error = getattr(response, "error", None)
        if error:
            if "quota" in str(error).lower():
                raise QuotaExhausted(f"Kaggle GPU quota: {error}")
            raise ProviderError(f"kernels push failed: {error}")

        started = time.time()
        last = ""
        while True:
            time.sleep(poll_s)
            status_obj = client.kernels_status(kernel_ref)
            status = _status_name(status_obj)
            if status != last:
                print(f"  kaggle: {status} after {time.time() - started:.0f}s")
                last = status
            if status in TERMINAL:
                break
            if time.time() - started > max_wait_s:
                raise ProviderError(f"Kaggle job {kernel_ref} still {status} after {max_wait_s}s")

        client.kernels_output(kernel_ref, str(output_dir), force=True, quiet=True)
        log_files = sorted(output_dir.glob("*.log"))
        if status != "complete":
            message = getattr(status_obj, "failure_message", "") or status
            raise KaggleJobError(f"Kaggle job {kernel_ref} ended {status}: {message}",
                                 log_files[0] if log_files else None)

        results_path = next(iter(output_dir.rglob("results.json")), None)
        if results_path is None:
            raise KaggleJobError(f"Kaggle job {kernel_ref} produced no results.json",
                                 log_files[0] if log_files else None)
        results = json.loads(results_path.read_text("utf-8"))
        if results.get("job_id") != job["job_id"]:
            raise KaggleJobError(f"results.json is from job {results.get('job_id')}, expected {job['job_id']}"
                                 " (the kernel read a stale dataset version)")
        call.gpu_s = results.get("gpu_seconds")
        call.output = str(output_dir.relative_to(project.root))
        call.note = f"queue+run wall time; gpu={results.get('gpu_name')}"
        return results_path.parent, results
