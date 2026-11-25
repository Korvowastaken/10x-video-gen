"""WaveSpeed AI: hosted Wan 2.2 image-to-video and ACE-Step 1.5, one key for both.

Contract, from the API docs read on 2026-11-25:
  POST {API}/{model}                      JSON parameters -> data.id
  GET  {API}/predictions/{id}/result      data.status, data.outputs (URLs), data.error,
                                          data.timings.inference (ms)
  POST {API}/media/uploads                signed PUT URL + download_url for an input image
Status "completed" is success; failed, cancelled, timeout and deleted are final failures.

A submit is never retried after an unclear failure: WaveSpeed warns that a retry
can create a second, billed task. Only a 429 (rejected, nothing created) is
retried. Polling and downloads retry freely.
"""
from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from typing import Any

import httpx

from .. import runlog
from ..config import Project, env
from .. import keys
from ..retry import ProviderError, QuotaExhausted, RetryableError, http_request, with_retries

API = "https://api.wavespeed.ai/api/v3"
FAILED = {"failed", "cancelled", "timeout", "deleted"}
CREDIT_CODES = {1407}
MODERATION_CODES = {1200}


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {env('WAVESPEED_API_KEY')}"}


def _data(response: httpx.Response) -> dict[str, Any]:
    payload = response.json()
    return payload.get("data") if isinstance(payload.get("data"), dict) else payload


def upload(path: Path) -> str:
    """Upload a local input file; returns a URL the models accept (kept 7 days)."""
    raw = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    def attempt(_: int) -> str:
        try:
            response = http_request("POST", f"{API}/media/uploads", headers=_auth(), timeout=60,
                                    json_body={"filename": path.name, "size": len(raw), "content_type": mime})
            data = _data(response)
            target = data["upload"]
            put = httpx.request(target.get("method", "PUT"), target["url"], headers=target.get("headers") or {},
                                content=raw, timeout=180)
            if put.status_code >= 400:
                raise RetryableError(f"upload PUT failed: HTTP {put.status_code}")
            return data["download_url"]
        except (KeyError, ProviderError):
            # Older single-step endpoint, still documented as supported.
            response = http_request("POST", f"{API}/media/upload/binary", headers=_auth(), timeout=180,
                                    files={"file": (path.name, raw, mime)})
            return _data(response)["download_url"]

    return with_retries(attempt, attempts=3, label=f"upload {path.name}")


def submit(model: str, payload: dict[str, Any]) -> str:
    """Create one task. Retried only when WaveSpeed rejected it with 429 (nothing was created)."""
    for wait_s in (0, 15, 30, 60):
        time.sleep(wait_s)
        try:
            response = httpx.post(f"{API}/{model}", headers=_auth(), json=payload, timeout=60)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderError(f"submit to {model} failed in transit ({exc}); not retried, "
                                "check the WaveSpeed dashboard before running again") from exc
        if response.status_code == 429:
            continue
        if response.status_code in (401, 403):
            raise ProviderError(f"WaveSpeed rejected the key: HTTP {response.status_code} {response.text[:200]}")
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        if response.status_code >= 400 or body.get("code") not in (None, 200, 0):
            code = body.get("code")
            message = body.get("message") or response.text[:300]
            if code in CREDIT_CODES or "credit" in str(message).lower() or "balance" in str(message).lower():
                if keys.switch("wavespeed"):  # nothing was created: submit again on the next account
                    continue
                raise QuotaExhausted(f"WaveSpeed credit used up: {message}")
            raise ProviderError(f"WaveSpeed submit failed: HTTP {response.status_code} code {code}: {message}")
        task_id = _data(response).get("id")
        if not task_id:
            raise ProviderError(f"WaveSpeed returned no task id: {response.text[:300]}")
        return task_id
    raise RetryableError("WaveSpeed kept answering 429 (rate limit: 5 tasks a minute on a new account)")


def wait(task_id: str, timeout_s: float = 900) -> dict[str, Any]:
    """Poll a task until it finishes. Returns the result's data object."""
    started = time.time()
    delay = 2.0
    while True:
        def poll(_: int) -> dict[str, Any]:
            return _data(http_request("GET", f"{API}/predictions/{task_id}/result", headers=_auth(), timeout=30))
        data = with_retries(poll, attempts=4, label=f"poll {task_id}")
        status = str(data.get("status", "")).lower()
        if status == "completed":
            return data
        if status in FAILED:
            error = data.get("error") or status
            code = data.get("code")
            if code in CREDIT_CODES or "credit" in str(error).lower():
                raise QuotaExhausted(f"WaveSpeed credit used up: {error}")
            if code in MODERATION_CODES:
                raise ProviderError(f"WaveSpeed content moderation stopped the task: {error}")
            raise ProviderError(f"WaveSpeed task {task_id} {status}: {error}")
        if time.time() - started > timeout_s:
            raise ProviderError(f"WaveSpeed task {task_id} still {status or 'pending'} after {timeout_s:.0f}s")
        time.sleep(delay)
        delay = min(10.0, delay * 1.4)


def _download(url: str) -> bytes:
    def attempt(_: int) -> bytes:
        try:
            response = httpx.get(url, timeout=300, follow_redirects=True)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise RetryableError(f"download failed: {exc}") from exc
        if response.status_code >= 400:
            raise RetryableError(f"download HTTP {response.status_code}")
        return response.content
    return with_retries(attempt, attempts=4, label="download")


def image_to_video(project: Project, *, stage: str, item: str, model: str, price_usd: float, image: Path,
                   prompt: str, negative: str, seed: int, clip_s: int,
                   last_image: Path | None = None) -> tuple[bytes, dict[str, Any]]:
    """One paid Wan 2.2 clip. Returns (mp4 bytes, info) and logs one runs.jsonl line."""
    params = {"clip_s": clip_s, "last_image": last_image is not None, "prompt_chars": len(prompt),
              "prompt_sha": runlog.text_digest(prompt), "image": image.name,
              "end_image": last_image.name if last_image else None}
    with runlog.model_call(project, stage=stage, item=item, provider="wavespeed", model=model,
                           params=params, seed=seed) as call:
        payload: dict[str, Any] = {"prompt": prompt, "image": upload(image), "duration": clip_s, "seed": seed}
        if negative:
            payload["negative_prompt"] = negative
        if last_image is not None:
            payload["last_image"] = upload(last_image)
        task_id = submit(model, payload)
        result = wait(task_id)
        outputs = result.get("outputs") or []
        if not outputs:
            raise ProviderError(f"task {task_id} completed with no output")
        video = _download(outputs[0])
        inference_s = ((result.get("timings") or {}).get("inference") or 0) / 1000
        call.cost = {"unit": "usd", "usd_list": price_usd}
        call.gpu_s = round(inference_s, 2) or None
        call.note = f"task {task_id}"
        return video, {"task": task_id, "inference_s": inference_s, "url": outputs[0]}


def music(project: Project, *, stage: str, item: str, model: str, usd_per_s: float, tags: str,
          duration: float, seed: int, lyrics: str | None = None) -> tuple[bytes, str, dict[str, Any]]:
    """One ACE-Step 1.5 track. The model page says only tags are required and empty lyrics
    mean instrumental, but the API rejects a request without lyrics ("field lyrics is
    required", FAILURES.md F14), so an instrumental sends ACE-Step's own "[Instrumental]" tag."""
    params = {"duration": duration, "tags_chars": len(tags), "tags_sha": runlog.text_digest(tags),
              "instrumental": not lyrics}
    with runlog.model_call(project, stage=stage, item=item, provider="wavespeed", model=model,
                           params=params, seed=seed) as call:
        payload: dict[str, Any] = {"tags": tags, "lyrics": lyrics or "[Instrumental]", "duration": duration,
                                   "seed": seed}
        task_id = submit(model, payload)
        result = wait(task_id, timeout_s=600)
        outputs = result.get("outputs") or []
        if not outputs:
            raise ProviderError(f"task {task_id} completed with no output")
        audio = _download(outputs[0])
        ext = Path(outputs[0].split("?")[0]).suffix or ".mp3"
        call.cost = {"unit": "usd", "usd_list": round(duration * usd_per_s, 5)}
        call.gpu_s = round(((result.get("timings") or {}).get("inference") or 0) / 1000, 2) or None
        call.note = f"task {task_id}"
        return audio, ext, {"task": task_id, "url": outputs[0]}
