"""Pictures from more than Cloudflare: Gemini one at a time, Kaggle as one batch per pass."""
import base64
import io
import json

import pytest
from PIL import Image

from pipeline import accounts, catalog, keyframes
from pipeline.cache import StageCache, key_for
from pipeline.config import Project
from pipeline.keyframes import KEYFRAME_SIZE, REFERENCE_SIZE, Pending
from pipeline.providers import gemini, kaggle_runner
from pipeline.retry import EXHAUSTED, QuotaExhausted

FLUX2 = "@cf/black-forest-labs/flux-2-klein-4b"
SCHNELL = "@cf/black-forest-labs/flux-1-schnell"
NANO = "gemini-3.1-flash-lite-image"
KAGGLE = "kaggle-flux-2-klein-4b"


def _png(size=(64, 64), colour="#808080") -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def _clean():
    EXHAUSTED.clear()
    yield
    EXHAUSTED.clear()


@pytest.fixture
def keyed(monkeypatch):
    """Pretend these services have a saved key."""
    def use(*services):
        monkeypatch.setattr(keyframes.keys, "slots", lambda s: [1] if s in services else [])
    return use


def test_gemini_asks_for_the_nearest_aspect_and_hands_back_the_exact_size():
    assert gemini.aspect_ratio(*KEYFRAME_SIZE) == "9:16"
    assert gemini.aspect_ratio(*REFERENCE_SIZE) == "3:4"
    out = gemini.fit(_png((900, 1600)), *KEYFRAME_SIZE)
    with Image.open(io.BytesIO(out)) as img:
        assert img.size == KEYFRAME_SIZE


def test_gemini_sends_the_references_before_the_prompt(tmp_path, monkeypatch):
    sent = {}

    def fake(model, body, timeout):
        sent.update(model=model, body=body)
        return {"candidates": [{"content": {"parts": [
            {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(_png((576, 1024))).decode()}}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 1290}}

    monkeypatch.setattr(gemini, "_generate", fake)
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(_png())
    data, ext = gemini.generate_image(Project(tmp_path), stage="keyframes", item="S01", model=NANO,
                                      prompt="A kitchen.", seed=7, width=768, height=1344, references=[sheet])
    parts = sent["body"]["contents"][0]["parts"]
    assert "inlineData" in parts[0] and parts[-1] == {"text": "A kitchen."}
    config = sent["body"]["generationConfig"]
    assert config["responseModalities"] == ["IMAGE"] and config["imageConfig"]["aspectRatio"] == "9:16"
    assert config["seed"] == 7 and ext == ".png"
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (768, 1344)
    row = json.loads((tmp_path / "runs.jsonl").read_text("utf-8").splitlines()[-1])
    assert row["provider"] == "gemini" and row["cost"]["usd_list"] == gemini.IMAGE_PRICES[NANO]


def test_a_service_without_a_key_hands_over_to_gemini(tmp_path, monkeypatch, keyed):
    keyed("gemini")
    sent = {}

    def fake(project, *, model, prompt, references, **_):
        sent.update(model=model, prompt=prompt, refs=references)
        return b"png", ".png"

    monkeypatch.setattr(keyframes.gemini, "generate_image", fake)
    monkeypatch.setattr(keyframes.cloudflare, "generate_image", lambda *a, **k: pytest.fail("no Cloudflare key"))
    sheet = tmp_path / "sheet.png"
    _, _, used = keyframes._generate(Project(tmp_path), item="S01", models=[FLUX2, NANO, SCHNELL], prompt="A kitchen.",
                                     seed=1, size=KEYFRAME_SIZE, references=[sheet])
    assert used == NANO and sent["refs"] == [sheet] and sent["prompt"].endswith(keyframes.REF_NOTE)


def test_gemini_out_of_quota_is_skipped_for_the_rest_of_the_run(tmp_path, monkeypatch, keyed):
    keyed("gemini", "cloudflare")
    calls = []

    def nano(*_, **__):
        calls.append("nano")
        raise QuotaExhausted("limit: 0")

    monkeypatch.setattr(keyframes.gemini, "generate_image", nano)
    monkeypatch.setattr(keyframes.cloudflare, "generate_image", lambda *a, **k: (b"jpg", ".jpg"))
    for item in ("S01", "S02"):
        keyframes._generate(Project(tmp_path), item=item, models=[NANO, FLUX2], prompt="p", seed=1,
                            size=KEYFRAME_SIZE, references=[])
    assert calls == ["nano"]


def test_kaggle_draws_every_waiting_picture_in_one_job(tmp_path, monkeypatch, keyed):
    """A start frame and its end frame go in one job; the end frame names the start as its
    reference, and its cache key is made from the start frame the job drew."""
    keyed("kaggle", "cloudflare")
    project = Project(tmp_path)
    cache = StageCache(project, "keyframes")
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(_png())
    jobs = []

    def run_job(project, *, job, inputs, **_):
        jobs.append((job, inputs))
        out = tmp_path / "kaggle_out"
        out.mkdir(exist_ok=True)
        items = {}
        for n, item in enumerate(job["items"]):
            (out / f"{item['id']}.png").write_bytes(_png(colour=f"#{n + 1:02x}0000"))
            items[item["id"]] = {"status": "ok", "file": f"{item['id']}.png", "latency_s": 9.0}
        return out, {"job_id": job.get("job_id"), "items": items}

    monkeypatch.setattr(kaggle_runner, "run_job", run_job)
    monkeypatch.setattr(keyframes.cloudflare, "generate_image", lambda *a, **k: pytest.fail("Kaggle drew it"))
    batch: list[Pending] = []
    counts = {"made": 0, "cached": 0}
    start = keyframes._make(project, cache, item="S01", spec={"v": 1, "x": "start"}, models=[KAGGLE, FLUX2],
                            prompt="Start.", seed=3, size=KEYFRAME_SIZE, references=[sheet], force=False,
                            counts=counts, batch=batch)
    assert isinstance(start, Pending) and start.after == [FLUX2]
    seen = []
    end = Pending(cache=cache, item="S01_end", prompt="End.", seed=4, size=KEYFRAME_SIZE, references=[start],
                  layout=None, spec_of=lambda done: seen.append(done[0]) or {"v": 1, "start": done[0].name},
                  model=KAGGLE, after=[FLUX2])
    batch.append(end)
    keyframes.run_batch(project, batch, counts)

    assert len(jobs) == 1
    job, inputs = jobs[0]
    assert [i["id"] for i in job["items"]] == ["S01", "S01_end"]
    assert job["items"][0]["refs"][0]["file"] in inputs and job["items"][1]["refs"] == [{"item": "S01"}]
    assert job["model"] == "black-forest-labs/FLUX.2-klein-4B" and job["steps"] == 4
    assert start.path.exists() and end.path.exists() and seen == [start.path]
    assert cache.entry("S01_end")["key"] == key_for({"v": 1, "start": start.path.name})
    assert cache.entry("S01")["model"] == KAGGLE and counts["made"] == 2


def test_a_picture_the_kaggle_job_misses_goes_on_down_the_chain(tmp_path, monkeypatch, keyed):
    keyed("kaggle", "cloudflare")
    project = Project(tmp_path)
    cache = StageCache(project, "refs")
    monkeypatch.setattr(kaggle_runner, "run_job",
                        lambda project, **_: (_ for _ in ()).throw(QuotaExhausted("Kaggle GPU quota")))
    monkeypatch.setattr(keyframes.cloudflare, "generate_image", lambda *a, **k: (_png(), ".png"))
    batch: list[Pending] = []
    counts = {"made": 0, "cached": 0}
    pending = keyframes._make(project, cache, item="char_a_0", spec={"v": 1}, models=[KAGGLE, FLUX2], prompt="A.",
                              seed=1, size=REFERENCE_SIZE, references=[], force=False, counts=counts, batch=batch)
    keyframes.run_batch(project, batch, counts)
    assert pending.path.exists() and cache.entry("char_a_0")["model"] == FLUX2
    assert KAGGLE in EXHAUSTED


def test_without_a_batch_kaggle_is_skipped(tmp_path, monkeypatch, keyed):
    keyed("kaggle", "cloudflare")
    monkeypatch.setattr(keyframes.cloudflare, "generate_image", lambda *a, **k: (b"jpg", ".jpg"))
    _, _, used = keyframes._generate(Project(tmp_path), item="S01", models=[KAGGLE, FLUX2], prompt="p", seed=1,
                                     size=KEYFRAME_SIZE, references=[])
    assert used == FLUX2


def test_the_picker_offers_gemini_and_kaggle():
    assert catalog.provider_of(KAGGLE) == "kaggle" and catalog.provider_of(NANO) == "gemini"
    assert {NANO, KAGGLE} <= set(catalog.candidates("image"))
    assert catalog._price(NANO, "gemini")[1] is True and catalog._price(KAGGLE, "kaggle") == ("Free weekly GPU hours", False)
    assert NANO not in catalog._gemini("text")


def test_the_pictures_panel_follows_the_image_chain():
    assert accounts._services("pictures", {"image": [NANO, FLUX2, KAGGLE]}) == ["gemini", "cloudflare", "kaggle"]
    assert accounts._services("clips", {}) is None


def test_switching_back_to_a_model_keeps_the_chosen_sheet(tmp_path):
    """An old sheet drawn earlier by the model now first does not replace the one in use."""
    cache = StageCache(Project(root=tmp_path), "refs")
    old = {"prompt": "Robel", "seed": 1, "model": FLUX2}
    chosen = {**old, "model": NANO}
    for spec in (old, chosen):
        path = cache.path("char_robel_1", key_for(spec), ".png")
        path.write_bytes(_png())
        cache.record("char_robel_1", key_for(spec), path, spec)
    assert cache.usable("char_robel_1", key_for(old), (".png",), old, ("model",)) == cache.current("char_robel_1")
    assert cache.current("char_robel_1").name == f"char_robel_1__{key_for(chosen)}.png"
    other = {**old, "prompt": "Robel in red"}
    assert cache.usable("char_robel_1", key_for(other), (".png",), other, ("model",)) is None


def test_a_missing_reference_photo_draws_from_the_description(tmp_path, capsys):
    # references/ is git-ignored, so a fresh clone has no photos: the run goes on without them.
    project = Project(tmp_path)
    assert keyframes._photo(project, {"photo": "references/someone.jpg"}) is None
    assert "references/someone.jpg is missing" in capsys.readouterr().err
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "someone.jpg").write_bytes(b"jpg")
    assert keyframes._photo(project, {"photo": "references/someone.jpg"}) == tmp_path / "references" / "someone.jpg"
