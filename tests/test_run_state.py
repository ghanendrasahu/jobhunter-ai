"""Extra coverage for the run-state store: listings, detail and failure paths."""

import sqlite3

from jobhunter.storage import run_state
from jobhunter.storage.run_state import (
    build_run_summary,
    clear_submission_attempt,
    events_for_run,
    get_run,
    has_submission_attempt,
    list_all_submission_attempts,
    list_runs,
    list_submission_attempts,
    record_application_event,
    record_event,
    record_source_metric,
    source_metrics_for_run,
    start_run,
    update_run,
)


def test_get_run_returns_none_for_unknown(tmp_path):
    assert get_run("run-does-not-exist") is None


def test_list_runs_newest_first(tmp_path):
    first = start_run(origin="pipeline", query="first")
    second = start_run(origin="pipeline", query="second")
    runs = list_runs(limit=10)
    ids = [run["run_id"] for run in runs]
    assert second in ids and first in ids
    assert ids.index(second) <= ids.index(first)


def test_update_run_ignores_unknown_fields():
    run_id = start_run(origin="pipeline")
    update_run(run_id, bogus_field="value", query="new query")
    run = get_run(run_id)
    assert run["query"] == "new query"


def test_update_run_with_empty_id_is_noop():
    update_run("", query="anything")


def test_finish_run_with_empty_id_is_noop():
    from jobhunter.storage.run_state import finish_run

    finish_run("", "completed", {})


def test_events_for_run_returns_ordered_entries():
    run_id = start_run(origin="pipeline")
    record_event(run_id, "info", "search", "first")
    record_event(run_id, "warning", "apply", "second")
    events = events_for_run(run_id)
    assert [event["message"] for event in events] == ["first", "second"]
    assert events[1]["level"] == "warning"


def test_record_application_event_levels():
    run_id = start_run(origin="pipeline")
    record_application_event(run_id, {"title": "Dev", "company": "Acme"}, "submitted", "Confirmed")
    record_application_event(run_id, {"title": "Dev", "company": "Acme"}, "failed", "Browser crashed")
    events = events_for_run(run_id)
    assert events[0]["level"] == "info"
    assert events[1]["level"] == "warning"
    assert "submitted" in events[0]["message"]


def test_list_all_submission_attempts_and_clear(tmp_path):
    resume_text = "phase11 attempts resume"
    job = {"id": "job-all-1", "url": "https://x/1"}
    from jobhunter.storage.run_state import mark_submission_attempt

    mark_submission_attempt(resume_text, job)
    assert any(a["job_id"] == "job-all-1" for a in list_all_submission_attempts())
    clear_submission_attempt(resume_text, "job-all-1")
    assert not any(a["job_id"] == "job-all-1" for a in list_all_submission_attempts())


def test_build_run_summary_shape():
    run_id = start_run(origin="pipeline", query="q")
    record_event(run_id, "info", "search", "found jobs")
    from jobhunter.storage.run_state import finish_run

    finish_run(run_id, "completed", {"applications": {"total": 1, "by_status": {"submitted": 1}}})
    summary = build_run_summary(run_id)
    assert summary["status"] == "completed"
    assert summary["events_by_level"]["info"] >= 1
    assert summary["applications"]["total"] == 1
    assert "source_metrics" in summary


def test_storage_failures_are_tolerated(monkeypatch):
    def boom():
        raise sqlite3.DatabaseError("database is locked")

    monkeypatch.setattr(run_state, "_connect", boom)
    assert get_run("x") is None
    assert list_runs() == []
    assert events_for_run("x") == []
    assert source_metrics_for_run("x") == {}
    assert build_run_summary("x")["status"] == "unknown"
    assert has_submission_attempt("r", "j") is False
    assert list_submission_attempts("r") == []
    assert list_all_submission_attempts() == []
    record_event("x", "info", "s", "m")
    record_source_metric("x", "naukri", found=1)
    record_application_event("x", {"title": "t", "company": "c"}, "failed", "d")
    from jobhunter.storage.run_state import finish_run, mark_submission_attempt

    finish_run("x", "completed", {})
    mark_submission_attempt("r", {"id": "j"})
    clear_submission_attempt("r", "j")
