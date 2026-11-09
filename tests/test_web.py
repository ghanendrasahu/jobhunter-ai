"""Tests for the HTTP API-adjacent entry point (web.py) and scheduler loop."""


import jobhunter.scheduler as scheduler
import jobhunter.web as web


def test_web_main_invokes_streamlit(monkeypatch):
    calls: list[list[str]] = []

    def fake_call(cmd):
        calls.append(list(cmd))
        return 0

    monkeypatch.setattr(web.subprocess, "call", fake_call)
    assert web.main() == 0
    assert calls, "expected subprocess.call to be invoked"
    cmd = calls[0]
    assert "streamlit" in cmd
    assert "run" in cmd


# ---------------------------------------------------------------------------
# Scheduler loop (beyond the existing _load_resume_text tests)
# ---------------------------------------------------------------------------
def test_schedule_missing_resume_raises(monkeypatch, tmp_path):
    try:
        scheduler.schedule("query", interval_minutes=1, resume_pdf=str(tmp_path / "nope.pdf"))
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")


def test_schedule_runs_and_sends_email(sample_pdf, monkeypatch):
    emails: list[tuple] = []
    monkeypatch.setattr(
        scheduler,
        "run_job_hunter",
        lambda path: {
            "jobs": [{"id": "j1"}, {"id": "j2"}],
            "applications": [{"status": "submitted"}],
        },
    )
    monkeypatch.setattr(
        scheduler,
        "send_job_alert_email",
        lambda query, total, submitted: emails.append((query, total, submitted)),
    )
    monkeypatch.setattr(scheduler.time, "sleep", lambda seconds: None)
    scheduler.schedule("Python Developer", interval_minutes=1, resume_pdf=str(sample_pdf), max_runs=1)
    assert emails == [("Python Developer", 2, 1)]


def test_schedule_email_failure_is_swallowed(sample_pdf, monkeypatch):
    monkeypatch.setattr(
        scheduler,
        "run_job_hunter",
        lambda path: {
            "jobs": [],
            "applications": [],
        },
    )

    def boom(query, total, submitted):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(scheduler, "send_job_alert_email", boom)
    monkeypatch.setattr(scheduler.time, "sleep", lambda seconds: None)
    scheduler.schedule("Python Developer", interval_minutes=1, resume_pdf=str(sample_pdf), max_runs=1)


def test_schedule_pipeline_failure_continues(sample_pdf, monkeypatch):
    calls = {"n": 0}

    def flaky(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient failure")
        return {"jobs": [{"id": "j"}], "applications": [{"status": "recorded"}]}

    emails: list[tuple] = []
    monkeypatch.setattr(scheduler, "run_job_hunter", flaky)
    monkeypatch.setattr(scheduler, "send_job_alert_email", lambda *a: emails.append(a))
    monkeypatch.setattr(scheduler.time, "sleep", lambda seconds: None)
    scheduler.schedule("Python Developer", interval_minutes=1, resume_pdf=str(sample_pdf), max_runs=2)
    assert calls["n"] == 2  # failure on run 1 did not abort the loop
    assert len(emails) == 1  # only the successful run emailed


def test_main_rejects_non_positive_interval(sample_pdf):
    assert scheduler.main(["--query", "x", "--interval", "0", "--resume", str(sample_pdf)]) == 1


def test_main_missing_resume_returns_1(tmp_path):
    assert scheduler.main(["--query", "x", "--interval", "5", "--resume", str(tmp_path / "nope.pdf")]) == 1
