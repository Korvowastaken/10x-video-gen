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
