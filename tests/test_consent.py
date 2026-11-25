"""Consent for a real person is confirmed in the studio, kept with the story, and can be withdrawn."""
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from pipeline import consent, studio
from pipeline import storyboard as sbmod
from pipeline.config import ROOT, Project

FILM = ROOT / "tests" / "fixtures" / "film"


@pytest.fixture
def project(tmp_path, monkeypatch):
    for name in ("story.md", "storyboard.json"):  # no ETHICS.md: the studio's records alone decide
        shutil.copy(FILM / name, tmp_path / name)
    monkeypatch.setattr(studio, "PROJECT", Project(tmp_path))
    return Project(tmp_path)


def _speaker(project):
    sb = sbmod.load(project)
    return next(c for c in sb["characters"] if any(l["speaker"] == c["id"] for s in sb["shots"] for l in s["lines"]))


def _blocked(project):
    return [e for e in sbmod.rule_errors(sbmod.load(project), project) if "is not confirmed" in e]


def test_confirming_needs_all_three_ticks_and_how_it_was_recorded(project):
    client = TestClient(studio.app)
    c = _speaker(project)
    half = {"character": c["id"], "read_out": True, "agreed": True, "recording_kept": False, "how": "voice note"}
    assert client.post("/api/consent", json=half).status_code == 422
    assert not (project.root / "consent.json").exists()


def test_a_confirmed_consent_marks_the_real_person_and_keeps_what_they_heard(project):
    client = TestClient(studio.app)
    c = _speaker(project)
    out = client.post("/api/consent", json={"character": c["id"], "read_out": True, "agreed": True,
                                            "recording_kept": True, "how": "voice note on my phone"}).json()
    row = next(x for x in out["characters"] if x["id"] == c["id"])
    assert row["status"] == "agreed" and row["consent"] == "C1" and not row["lines_changed"]
    rec = out["records"][0]
    assert rec["person"] == c["name"] and rec["lines"] and rec["how"] == "voice note on my phone"
    assert sbmod.load(project)["characters"][[x["id"] for x in out["characters"]].index(c["id"])]["real_person"]
    assert not _blocked(project)
    assert consent.people(project) == [{"id": c["id"], "name": c["name"], "consent": "C1"}]


def test_changed_lines_are_flagged_and_withdrawal_blocks_the_person_again(project):
    client = TestClient(studio.app)
    c = _speaker(project)
    client.post("/api/consent", json={"character": c["id"], "self": True})
    sb = sbmod.load(project)
    shot = next(s for s in sb["shots"] if any(l["speaker"] == c["id"] for l in s["lines"]))
    next(l for l in shot["lines"] if l["speaker"] == c["id"])["en"] = "A different line."
    sbmod.save(project, sb)
    row = next(x for x in client.get("/api/consent").json()["characters"] if x["id"] == c["id"])
    assert row["lines_changed"]

    out = client.post("/api/consent/C1/withdraw").json()
    assert next(x for x in out["characters"] if x["id"] == c["id"])["status"] == "withdrawn"
    assert _blocked(project)  # nothing of them is generated now
    assert consent.people(project)  # and a redraft still treats them as real


def test_not_a_real_person_after_all_unblocks_the_character_as_fictional(project):
    client = TestClient(studio.app)
    c = _speaker(project)
    client.post("/api/consent", json={"character": c["id"], "self": True})
    client.post("/api/consent/C1/withdraw")
    out = client.post("/api/consent/C1/fictional").json()
    assert next(x for x in out["characters"] if x["id"] == c["id"])["status"] == "fictional"
    assert not _blocked(project) and consent.people(project) == []
    assert json.loads((project.root / "consent.json").read_text("utf-8"))["records"][0]["status"] == "fictional"


def test_ids_continue_after_the_ethics_table(project):
    (project.root / "ETHICS.md").write_text("| ID | Person |\n|---|---|\n| C4 | someone |\n", "utf-8")
    client = TestClient(studio.app)
    out = client.post("/api/consent", json={"character": _speaker(project)["id"], "self": True}).json()
    assert out["records"][0]["id"] == "C5"


def test_the_read_out_comes_from_ethics_md():
    blocks = consent.wording()
    assert [b["label"] for b in blocks][:2] == ["English", "Amharic"]
    assert "Do you agree?" in blocks[0]["text"]
