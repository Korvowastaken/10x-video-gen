"""A studio job can be stopped, and its log says what it did, call by call."""
import threading
import time

import pytest

from pipeline import jobs, runlog, studio
from pipeline.config import Project


def _wait(job, timeout=5.0):
    end = time.time() + timeout
    while job["status"] == "running" and time.time() < end:
        time.sleep(0.02)
    return job


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, "PROJECT", Project(tmp_path))
    monkeypatch.setattr(studio, "JOBS", {})
    return Project(tmp_path)


def test_stop_ends_a_job_at_its_next_wait_and_starts_nothing_after(project):
    made = []

    def work():
        for i in range(50):
            with runlog.model_call(project, stage="script", item=f"S{i:02}", provider="groq", model="allam-2-7b", key="k"):
                made.append(i)
            print(f"wrote S{i:02}")
            jobs.sleep(0.2)

    job = studio.start_job("draft the script", work)
    time.sleep(0.3)
    studio.stop_job(job["id"])
    _wait(job)
    assert job["status"] == "cancelled" and "stopping" not in job
    assert 1 <= len(made) < 5  # stopped well before the end
    levels = [e["level"] for e in job["log"]]
    assert levels[0] == "info" and levels[-1] == "warn" and "call" in levels
    call = next(e for e in job["log"] if e["level"] == "call")["call"]
    assert call["provider"] == "groq" and call["model"] == "allam-2-7b" and call["status"] == "ok"
    assert job["totals"]["calls"] == len(made) and job["totals"]["failed"] == 0
    assert len(runlog.read(project)) == len(made)  # nothing was started after the stop


def test_a_failed_call_and_a_retry_line_are_marked(project):
    def work():
        print("    retry S01: attempt 1 failed (503); waiting 0s")
        with pytest.raises(RuntimeError):
            with runlog.model_call(project, stage="script", item="S01", provider="gemini", model="g", key="k"):
                raise RuntimeError("bad request")

    job = _wait(studio.start_job("draft", work))
    assert job["status"] == "done"
    assert [e["level"] for e in job["log"]] == ["info", "warn", "error", "done"]
    assert job["log"][2]["call"]["error"].startswith("RuntimeError") and job["totals"]["failed"] == 1


def test_stopping_a_finished_job_changes_nothing(project):
    job = _wait(studio.start_job("draft", lambda: None))
    assert studio.stop_job(job["id"])["status"] == "done"


def test_outside_a_job_the_hooks_do_nothing():
    jobs.check()
    jobs.printed("hello")
    jobs.sleep(0)


def test_a_request_beside_a_stopping_job_is_not_stopped_or_logged_into_it(project):
    release = threading.Event()
    job = studio.start_job("draft", lambda: release.wait(5) and jobs.check())
    studio.stop_job(job["id"])
    # the page's own request thread: a revision's model call while the job winds down
    with runlog.model_call(project, stage="revise", item="S01", provider="groq", model="m", key="k"):
        pass
    release.set()
    _wait(job)
    assert job["status"] == "cancelled"
    assert not any(e.get("call") for e in job["log"]) and job["totals"]["calls"] == 0


def test_a_redo_runs_as_a_job_with_the_edits_and_note_and_hands_back_what_changed(project, monkeypatch):
    from fastapi.testclient import TestClient
    from pipeline import flow, flow_api, steps

    calls = []

    def fake(project_, scene, **kw):
        calls.append((scene, kw))
        with runlog.model_call(project_, stage="studio", item=f"{scene}-revise", provider="groq", model="m", key="k"):
            print(f"Rewriting keyframe of {scene} from your note")
        return {"file": "x.mp4", "used": "still", "changed": ["picture"]}

    shot = {"id": "S01", "motion": {"mode": "still"}}
    monkeypatch.setattr(steps, "redo_scene", fake)
    monkeypatch.setattr(flow, "require", lambda *a: None)
    monkeypatch.setattr(flow_api.sbmod, "load", lambda p: {"shots": [shot]})
    monkeypatch.setattr(flow_api.revise, "check", lambda p, sb, s: [])
    client = TestClient(studio.app)
    started = client.post("/api/scenes/S01/redo", json={"parts": ["keyframe"], "shot": shot, "note": "warmer"}).json()
    job = _wait(studio.JOBS[started["id"]])
    assert job["status"] == "done" and job["kind"] == "redo S01: keyframe from a note"
    assert job["result"]["changed"] == ["picture"]
    assert calls[0][1]["note"] == "warmer" and calls[0][1]["shot"] == shot and calls[0][1]["buy"] is False
    assert job["totals"]["calls"] == 1
    assert client.post("/api/scenes/S99/redo", json={"parts": ["voice"]}).status_code == 404
    assert client.post("/api/scenes/S01/redo", json={"parts": ["sound"]}).status_code == 400
    assert client.post("/api/scenes/S01/redo", json={"note": "warmer"}).status_code == 400  # a note needs a part


def test_a_note_aimed_at_one_part_rewrites_only_that_part():
    from pipeline import revise

    old = {"id": "S01", "beat": "tea", "keyframe": {"prompt": "grandma pours tea", "seed": 7},
           "lines": [{"speaker": "g", "text": "ሻይ", "en": "Tea"}],
           "motion": {"mode": "still_kenburns", "prompt": "push in", "seed": 9, "kenburns": "zoom-in"}}
    new = {"id": "S02", "beat": "coffee", "keyframe": {"prompt": "grandma laughs, pouring tea", "seed": 1},
           "lines": [{"speaker": "x", "text": "ቡና", "en": "Coffee"}],
           "motion": {"mode": "full_i2v", "prompt": "she laughs", "seed": 2}}
    out = revise.keep_outside(old, new, ["keyframe"])
    assert out["keyframe"] == {"prompt": "grandma laughs, pouring tea", "seed": 7}
    assert out["lines"] == old["lines"] and out["motion"] == old["motion"] and out["beat"] == "tea"
    out = revise.keep_outside(old, new, ["voice", "clip"])
    assert out["lines"] == [{"speaker": "g", "text": "ቡና", "en": "Coffee"}]  # the speaker stays
    assert out["motion"] == {"mode": "full_i2v", "prompt": "she laughs", "seed": 9}
    assert out["keyframe"] == old["keyframe"]
