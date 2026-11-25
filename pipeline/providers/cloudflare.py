"""Cloudflare Workers AI: keyframes and reference sheets with FLUX.

FLUX.2 models take multipart form data and up to four reference images, which
is what keeps a character the same across shots. FLUX.1 schnell takes JSON and
no references; it is the fallback when the FLUX.2 quota or model fails.
Docs: https://developers.cloudflare.com/workers-ai/models/
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx

from .. import runlog
from ..config import Project, env
from ..retry import ProviderError, QuotaExhausted, http_request, with_retries

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai"

# Workers AI list prices, used only for the cost column of runs.jsonl / COSTS.md.
# From the model pages and the pricing page (modified 2026-11-18), read 2026-11-25.
PRICES = {
    "@cf/black-forest-labs/flux-1-schnell": {"tile": 0.0000528, "step": 0.0001056},
    "@cf/black-forest-labs/flux-2-klein-4b": {"out_tile": 0.000287, "in_tile": 0.000059},
    "@cf/black-forest-labs/flux-2-klein-9b": {"first_mp": 0.015, "extra_mp": 0.002, "in_mp": 0.002},
}
NEURONS_PER_USD = 1000 / 0.011  # $0.011 per 1,000 neurons above the free 10,000/day


def _base() -> str:
    return API.format(account=env("CLOUDFLARE_ACCOUNT_ID"))


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {env('CLOUDFLARE_API_TOKEN')}"}


def _on_throttle(response: httpx.Response) -> float | None:
    text = response.text.lower()
    if "neuron" in text and ("daily" in text or "allocation" in text or "limit" in text):
        raise QuotaExhausted(f"Cloudflare daily neuron allowance used up: {response.text[:240]}")
    return None


def search_models(query: str) -> list[dict[str, Any]]:
    response = http_request("GET", f"{_base()}/models/search?search={query}&per_page=100",
                            headers=_auth(), timeout=30)
    rows = response.json().get("result", [])
    return [r for r in rows if query.lower() in r.get("name", "").lower()]


def model_schema(model: str) -> dict[str, Any]:
    response = http_request("GET", f"{_base()}/models/schema?model={model}", headers=_auth(), timeout=30)
    return response.json().get("result", {})


def _image_size(path: Path) -> tuple[int, int]:
    from PIL import Image

    with Image.open(path) as img:
        return img.size


def _sniff_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def _tiles(width: int, height: int) -> int:
    return -(-width // 512) * -(-height // 512)


def estimate_cost(model: str, width: int, height: int, steps: int,
                  reference_sizes: list[tuple[int, int]] | None = None) -> dict[str, Any]:
    price = PRICES.get(model)
    if not price:
        return {"unit": "image", "count": 1}
    refs = reference_sizes or []
    if "tile" in price:
        usd = _tiles(width, height) * price["tile"] + steps * price["step"]
    elif "out_tile" in price:
        usd = _tiles(width, height) * price["out_tile"] + sum(_tiles(w, h) for w, h in refs) * price["in_tile"]
    else:
        megapixels = width * height / 1_000_000
        usd = price["first_mp"] + max(0.0, megapixels - 1) * price["extra_mp"] + \
            sum(w * h / 1_000_000 for w, h in refs) * price["in_mp"]
    return {"unit": "neurons", "neurons": round(usd * NEURONS_PER_USD, 1), "usd_list": round(usd, 6)}


def generate_image(project: Project, *, stage: str, item: str, model: str, prompt: str, seed: int,
                   width: int, height: int, steps: int | None = None,
                   references: list[Path] | None = None, timeout: float = 240) -> tuple[bytes, str]:
    """Generate one image. Returns (bytes, extension)."""
    multipart = "flux-2" in model
    if references and not multipart:
        raise ProviderError(f"{model} does not take reference images")
    url = f"{_base()}/run/{model}"

    def attempt(n: int) -> tuple[bytes, str]:
        params: dict[str, Any] = {"width": width, "height": height, "steps": steps,
                                  "refs": [p.name for p in references or []],
                                  "prompt_chars": len(prompt), "prompt_sha": runlog.text_digest(prompt)}
        with runlog.model_call(project, stage=stage, item=item, provider="cloudflare", model=model,
                               params=params, seed=seed, attempt=n) as call:
            if multipart:
                # Every field as a multipart part, so the request is multipart even with no references.
                fields: list[tuple[str, Any]] = [("prompt", (None, prompt)), ("width", (None, str(width))),
                                                 ("height", (None, str(height))), ("seed", (None, str(seed)))]
                if steps:
                    fields.append(("steps", (None, str(steps))))
                for i, ref in enumerate(references or []):
                    mime = "image/png" if ref.suffix.lower() == ".png" else "image/jpeg"
                    fields.append((f"input_image_{i}", (ref.name, ref.read_bytes(), mime)))
                response = http_request("POST", url, headers=_auth(), files=fields,
                                        timeout=timeout, on_throttle=_on_throttle)
            else:
                # FLUX.1 schnell on Workers AI accepts only prompt and steps: no seed, so
                # its images cannot be reproduced; the cache is what keeps them stable.
                call.seed = None
                call.note = "model has no seed parameter"
                body: dict[str, Any] = {"prompt": prompt}
                if steps:
                    body["steps"] = min(steps, 8)
                response = http_request("POST", url, headers=_auth(), json_body=body,
                                        timeout=timeout, on_throttle=_on_throttle)
            payload = response.json()
            if not payload.get("success", True):
                raise ProviderError(f"Workers AI error: {payload.get('errors')}")
            image_b64 = (payload.get("result") or {}).get("image")
            if not image_b64:
                raise ProviderError(f"no image in response: {str(payload)[:300]}")
            data = base64.b64decode(image_b64)
            call.cost = estimate_cost(model, width, height, steps or 4,
                                      [_image_size(p) for p in references or []])
            return data, _sniff_ext(data)

    return with_retries(attempt, label=f"{stage}/{item}")
