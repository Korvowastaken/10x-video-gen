"""A brand-new story (no story.md, storyboard, approvals, runs.jsonl or outputs/) opens cleanly,
and several stories can sit side by side."""
import pytest
from fastapi.testclient import TestClient

from pipeline import flow, stories, studio
from pipeline.config import Project


@pytest.fixture
def empty(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "HOME", tmp_path)
    monkeypatch.setattr(studio, "PROJECT", Project(tmp_path))
    return tmp_path


def test_state_of_an_empty_project_has_every_field_the_page_reads(empty):
    s = studio.state()
    assert s["story"] == "" and s["storyboard"] is None
    assert s["shots"] == [] and s["sheets"] == {} and s["music"] == []
    assert s["film"]["rough"] is None and s["film"]["report"] == {}
    assert s["spent"] == 0 and s["calls"] == 0
    assert not (empty / "outputs").exists() and not (empty / "runs.jsonl").exists()


def test_flow_of_an_empty_project_starts_at_the_story(empty):
    out = flow.status(Project(empty))
    assert out["current"] == "story"
    assert [s["locked"] for s in out["steps"]] == [False, True, True, True, True, True]
    assert out["steps"][0]["blockers"] == ["write the story"]


def test_the_api_answers_on_an_empty_project(empty):
    client = TestClient(studio.app)
    for url in ("/api/state", "/api/flow", "/api/stories"):
        assert client.get(url).status_code == 200, url


def test_a_new_story_is_its_own_folder_and_switching_follows_it(empty):
    client = TestClient(studio.app)
    (empty / "story.md").write_text("The first one.", "utf-8")
    listing = client.post("/api/stories", json={"name": "Grandfather's Mill"}).json()
    assert [s["name"] for s in listing] == ["First story", "Grandfather's Mill"]
    assert listing[1]["current"] and not listing[1]["written"]
    assert studio.PROJECT.root == empty / "stories" / "grandfather-s-mill"
    assert client.get("/api/state").json()["story"] == ""
    assert stories.remembered(empty) == studio.PROJECT.root

    client.put("/api/stories/home", json={"name": "The market walk"})
    listing = client.put("/api/stories/current", json={"id": "home"}).json()
    assert listing[0] == {"id": "home", "name": "The market walk", "current": True, "written": True, "drafted": False}
    assert client.get("/api/state").json()["story"] == "The first one."


def test_stories_cannot_switch_while_a_job_runs(empty, monkeypatch):
    monkeypatch.setitem(studio.JOBS, "x", {"id": "x", "kind": "script", "status": "running", "log": []})
    client = TestClient(studio.app)
    assert client.post("/api/stories", json={"name": "Another"}).status_code == 409
    assert not (empty / "stories").exists()


def test_unknown_or_unsafe_story_ids_are_refused(empty):
    client = TestClient(studio.app)
    assert client.put("/api/stories/current", json={"id": "../.."}).status_code == 404
    assert client.put("/api/stories/current", json={"id": "missing"}).status_code == 404


def test_free_limits_follow_the_models_picked_before_a_draft(empty, monkeypatch):
    """A used-up Gemini must not hold back a draft that starts on another service."""
    from pipeline import catalog
    catalog.choose(Project(empty), "script", "groq/allam-2-7b", None)
    seen = []
    monkeypatch.setattr(studio, "free_limits", lambda project, models: seen.append(models) or {})
    studio.state()
    studio.get_providers()
    assert all(m["script"][0] == "groq/allam-2-7b" for m in seen) and len(seen) == 2
