"""PHASE 8 — recovery, idempotency, observability, and run metrics.

Failure-mode tests: source timeouts, source exceptions, browser crash
mid-submit, process restart recovery, duplicate prevention, interrupted runs,
and partial runs. All browser and network interaction is faked; no real Chrome
is launched and no network is touched.
"""

import asyncio

import jobhunter.domains.search.engine as engine
from fakes import FakeSession as _FakeSession
from fakes import agent_for as _agent_for
from fakes import job as _job
from jobhunter.automation.apply_agent import ApplyAgent
from jobhunter.config import Settings
from jobhunter.services import analytics
from jobhunter.services.retry import call_bounded
from jobhunter.storage import run_state
from jobhunter.storage.history import load_applied_jobs, save_applied_jobs

RESUME = "phase8 unique resume text %s"


# ---------------------------------------------------------------------------
# Bounded retry policy
# ---------------------------------------------------------------------------
def test_call_bounded_succeeds_first_try():
    assert call_bounded(lambda: "ok", attempts=3) == "ok"


def test_call_bounded_retries_and_succeeds():
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise ValueError("boom")
        return "ok"

    assert call_bounded(flaky, attempts=3, backoff_seconds=5, sleep=lambda s: None) == "ok"
    assert state["n"] == 3


def test_call_bounded_never_exceeds_attempts():
    state = {"n": 0}

    def always_fail():
        state["n"] += 1
        raise ValueError("boom")

    try:
        call_bounded(always_fail, attempts=2)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert state["n"] == 2


def test_call_bounded_reports_retries():
    seen: list[int] = []

    def fail():
        raise RuntimeError("boom")

    try:
        call_bounded(fail, attempts=3, on_retry=lambda attempt, exc: seen.append(attempt))
    except RuntimeError:
        pass
    assert seen == [1, 2]


# ---------------------------------------------------------------------------
# Run lifecycle and crash recovery
# ---------------------------------------------------------------------------
def test_recover_interrupted_runs_marks_running_runs():
    run_id = run_state.start_run(origin="test", query="q", mode="auto", portals=["naukri"])
    assert run_id
    assert run_state.recover_interrupted_runs() >= 1
    run = run_state.get_run(run_id)
    assert run is not None
    assert run["status"] == "interrupted"


def test_finished_run_is_not_marked_interrupted():
    run_id = run_state.start_run(origin="test", query="q", mode="human")
    run_state.finish_run(run_id, "completed", {"applications": {"total": 1, "by_status": {"submitted": 1}}})
    run = run_state.get_run(run_id)
    assert run["status"] == "completed"
    assert run["summary"]["applications"]["total"] == 1


def test_build_run_summary_counts_events():
    run_id = run_state.start_run(origin="test", query="q")
    run_state.record_event(run_id, "info", "search", "found 3 jobs")
    run_state.record_event(run_id, "warning", "apply", "needs_review — X")
    run_state.finish_run(
        run_id, "completed", {"applications": {"total": 2, "by_status": {"submitted": 1, "failed": 1}}}
    )
    summary = run_state.build_run_summary(run_id)
    assert summary["status"] == "completed"
    assert summary["events_by_level"] == {"info": 1, "warning": 1}
    assert summary["applications"]["total"] == 2


def test_source_metrics_roundtrip():
    run_id = run_state.start_run(origin="test", query="q")
    run_state.record_source_metric(run_id, "naukri", found=7, failed=False, duration_ms=1234)
    run_state.record_source_metric(run_id, "naukri", found=3)
    metrics = run_state.source_metrics_for_run(run_id)
    assert metrics["naukri"]["found"] == 10  # accumulates across planned queries
    assert metrics["naukri"]["failed"] is False
    assert metrics["naukri"]["duration_ms"] == 1234


def test_submission_attempt_marker_roundtrip():
    resume_text = RESUME % "marker"
    assert run_state.has_submission_attempt(resume_text, "job-1") is False
    job = {"id": "job-1", "url": "https://www.naukri.com/job/1"}
    run_state.mark_submission_attempt(resume_text, job)
    assert run_state.has_submission_attempt(resume_text, "job-1") is True
    assert run_state.list_submission_attempts(resume_text)[0]["url"] == job["url"]
    run_state.clear_submission_attempt(resume_text, "job-1")
    assert run_state.has_submission_attempt(resume_text, "job-1") is False


# ---------------------------------------------------------------------------
# Process crash between submit-click and outcome recording
# ---------------------------------------------------------------------------
def test_crash_after_submit_click_never_resubmits(monkeypatch):
    resume_text = RESUME % "crash"
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    submitted_clicks: list[str] = []
    rt = resume_text  # closure-safe handle (parameter shadows the outer name)

    def crashing_click(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        # Simulate: click already happened, process died before verification.
        if job["id"] not in submitted_clicks:
            submitted_clicks.append(job["id"])
            run_state.mark_submission_attempt(rt, job)
        raise RuntimeError("process killed mid-apply")

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", crashing_click)
    jobs = [_job(id="job-crash", url="https://www.naukri.com/job/crash")]

    outcomes = agent.apply_ranked_jobs(jobs, resume_text, mode="auto")
    assert outcomes[0]["status"] == "failed"  # crash surfaced, not swallowed
    assert "job-crash" not in load_applied_jobs(resume_text)

    # A fresh process (new agent, fresh session) sees the marker and refuses.
    session2 = _FakeSession()
    agent2 = _agent_for(monkeypatch, session2, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    called: list[str] = []
    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: called.append("x") or {})
    outcomes2 = agent2.apply_ranked_jobs(jobs, resume_text, mode="auto")
    assert outcomes2[0]["status"] == "needs_review"
    assert "never auto-retried" in outcomes2[0]["detail"]
    assert called == []


# ---------------------------------------------------------------------------
# Source timeout and source failure
# ---------------------------------------------------------------------------
class _HangingSource:
    source_name = "slow"

    async def search(self, query, location="India"):
        await asyncio.sleep(10)
        return []  # pragma: no cover - cancelled before this


class _BoomSource:
    source_name = "boom"

    async def search(self, query, location="India"):
        raise ValueError("source exploded")


def test_source_timeout_is_bounded_and_recorded(monkeypatch):
    monkeypatch.setattr(engine, "active_sources", lambda: [_HangingSource()])
    monkeypatch.setattr(
        engine,
        "get_settings",
        lambda: Settings(source_timeout_seconds=0.05),
    )
    run_id = run_state.start_run(origin="test", query="q")
    jobs = asyncio.run(engine.search_all_jobs_async("python", include_portals=False, run_id=run_id))
    assert jobs == []
    metrics = run_state.source_metrics_for_run(run_id)
    assert metrics["slow"]["failed"] is True
    assert metrics["slow"]["found"] == 0


def test_source_exception_does_not_stop_other_sources(monkeypatch):
    from jobhunter.domains.jobs import Job

    class _GoodSource:
        source_name = "good"

        async def search(self, query, location="India"):
            return [Job(title="Good Job", company="Acme", url="https://good.example/1", source="good")]

    monkeypatch.setattr(engine, "active_sources", lambda: [_BoomSource(), _GoodSource()])
    run_id = run_state.start_run(origin="test", query="q")
    jobs = asyncio.run(engine.search_all_jobs_async("python", include_portals=False, run_id=run_id))
    titles = [j["title"] for j in jobs]
    assert "Good Job" in titles
    metrics = run_state.source_metrics_for_run(run_id)
    assert metrics["boom"]["failed"] is True
    assert metrics["good"]["found"] == 1


# ---------------------------------------------------------------------------
# Interrupted and partial runs
# ---------------------------------------------------------------------------
def test_stopped_ranked_run_marks_remainder_deferred(monkeypatch):
    import threading

    resume_text = RESUME % "stop"
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    stop = threading.Event()
    stop.set()  # stop requested before the run starts
    agent._stop_event = stop

    jobs = [_job(id=f"job-{i}", url=f"https://www.naukri.com/job/{i}") for i in range(2)]
    outcomes = agent.apply_ranked_jobs(jobs, resume_text, mode="auto")
    assert all(o["status"] == "deferred" for o in outcomes)
    run = run_state.get_run(agent._run_id)
    assert run is not None
    assert run["status"] == "interrupted"


def test_partial_run_records_counts_and_summary(monkeypatch):
    resume_text = RESUME % "partial"
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto", max_applications_per_run=1))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    def fake_submitted(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        return {
            "job_id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "source": portal,
            "status": "submitted",
            "detail": "Application submitted and confirmed.",
        }

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", fake_submitted)
    jobs = [_job(id=f"job-{i}", url=f"https://www.naukri.com/job/{i}") for i in range(3)]

    own_run_id_holder: dict[str, str] = {}
    outcome = agent.apply_ranked_jobs(jobs, resume_text, mode="auto", max_applications=1)
    assert [o["status"] for o in outcome] == ["submitted", "deferred", "deferred"]
    assert agent._run_id  # a run row was recorded
    own_run_id_holder["id"] = agent._run_id
    run = run_state.get_run(own_run_id_holder["id"])
    assert run is not None
    assert run["status"] == "completed"
    assert run["summary"]["applications"]["submitted"] == 1
    assert run["summary"]["applications"]["by_status"]["deferred"] == 2


def test_form_failure_does_not_mark_applied(monkeypatch):
    resume_text = RESUME % "formfail"
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    def form_blows_up(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        raise ValueError("form controls missing")

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", form_blows_up)
    jobs = [_job(id="job-formfail")]
    outcomes = agent.apply_ranked_jobs(jobs, resume_text, mode="auto")
    assert outcomes[0]["status"] == "failed"
    assert "form controls missing" in outcomes[0]["detail"]
    assert "job-formfail" not in load_applied_jobs(resume_text)


def test_interrupted_job_is_recoverable_after_restart(monkeypatch):
    resume_text = RESUME % "restart"
    # Simulate a crash mid-run of a previous process: the run is stuck in
    # 'running' and a submit attempt marker exists for the job.
    stale_run = run_state.start_run(origin="pipeline_apply", resume_id="", query="q", mode="auto")
    job = _job(id="job-stale", url="https://www.naukri.com/job/stale")
    run_state.mark_submission_attempt(resume_text, job)

    assert run_state.recover_interrupted_runs() >= 1
    run = run_state.get_run(stale_run)
    assert run["status"] == "interrupted"

    session = _FakeSession()
    agent = _agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    called: list[str] = []
    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: called.append("x") or {})
    outcomes = agent.apply_ranked_jobs([job], resume_text, mode="auto")
    assert outcomes[0]["status"] == "needs_review"
    assert called == []


# ---------------------------------------------------------------------------
# Already-applied across restart (history is durable)
# ---------------------------------------------------------------------------
def test_already_applied_survives_restart(monkeypatch):
    resume_text = RESUME % "restart-dedup"
    save_applied_jobs(
        resume_text,
        ["job-restart"],
        [
            {
                "job_id": "job-restart",
                "title": "Python Developer",
                "company": "Acme",
                "source": "naukri",
                "url": "https://www.naukri.com/job/restart",
                "status": "submitted",
                "detail": "ok",
                "applied_at": "2026-11-01T00:00:00",
            }
        ],
    )
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    called: list[str] = []
    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: called.append("x") or {})
    outcomes = agent.apply_ranked_jobs(
        [_job(id="job-restart", url="https://www.naukri.com/job/restart")],
        resume_text,
        mode="auto",
    )
    assert outcomes[0]["status"] == "already_applied"
    assert called == []


# ---------------------------------------------------------------------------
# Application-level metrics
# ---------------------------------------------------------------------------
def test_application_metrics_aggregates_history():
    save_applied_jobs(
        RESUME % "metrics",
        ["job-metrics-1"],
        [
            {
                "job_id": "job-metrics-1",
                "title": "Dev",
                "company": "Acme",
                "source": "naukri",
                "url": "https://www.naukri.com/job/metrics-1",
                "status": "submitted",
                "detail": "ok",
                "applied_at": "2026-11-02T00:00:00",
            }
        ],
    )
    metrics = analytics.application_metrics(RESUME % "metrics")
    assert metrics["total_attempts"] >= 1
    assert metrics["submitted"] >= 1
    assert "naukri" in metrics["by_source"]
    assert metrics["submission_rate"] == 1.0
