"""Architecture invariant tests.

Executable statements of the safety invariants that must hold no matter how
the pipeline is reconfigured. Each test names the invariant it enforces.
These overlap with unit tests on purpose: they are the non-negotiable gates,
kept explicit so they cannot silently regress.

PH5 = eligibility hard gate (domains/eligibility.py)
PH6 = relevance ranking (domains/scoring.py)
"""

from types import SimpleNamespace

import jobhunter.agent as agent
from fakes import FakeLLM, FakeSession, agent_for
from fakes import job as _job
from jobhunter.agent import create_agent, run_job_hunter
from jobhunter.automation.apply_agent import ApplyAgent
from jobhunter.automation.apply_contract import apply_portal_for, may_auto_apply
from jobhunter.automation.browser import SessionSafetyError
from jobhunter.automation.form_filler import is_skippable
from jobhunter.automation.qa import QAMemory
from jobhunter.config import Settings
from jobhunter.domains.candidate import Candidate
from jobhunter.domains.eligibility import evaluate_eligibility
from jobhunter.storage.history import load_applied_jobs


# ---------------------------------------------------------------------------
# 1. PH5 (eligibility) executes before PH6 (scoring), and PH6 can never
#    reach a job PH5 did not clear for application.
# ---------------------------------------------------------------------------
def test_eligibility_runs_before_scoring(sample_pdf, monkeypatch):
    call_order: list[str] = []

    class _Elig:
        status = "eligible"
        decision = "apply"
        reasons: list[str] = []
        exposed: list[str] = []
        requirements: list = []

    def spy_eligibility(job, candidate=None, llm=None):
        call_order.append("eligibility")
        return _Elig()

    def spy_score(job, candidate=None, resume_text="", llm=None):
        call_order.append("score")
        return SimpleNamespace(
            overall=50,
            decision="apply",
            components=[],
            explanation="x",
            semantic_score=None,
            semantic_reason="",
        )

    monkeypatch.setattr(agent, "evaluate_eligibility", spy_eligibility)
    monkeypatch.setattr(agent, "score_relevance", spy_score)
    monkeypatch.setattr(agent, "search_plan_jobs", lambda plan, run_id=None: [_job()])
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)
    monkeypatch.setattr(
        agent,
        "apply_to_job",
        lambda job, resume: {
            "job_id": job["id"],
            "job_title": job["title"],
            "company": job["company"],
            "status": "recorded",
            "detail": "ok",
        },
    )

    result = run_job_hunter(str(sample_pdf), agent=create_agent(llm=FakeLLM()))
    assert result["error"] == ""
    assert call_order == ["eligibility", "score"]


def test_ineligible_job_never_reaches_scoring_or_apply(sample_pdf, monkeypatch):
    class _Skip:
        status = "not_eligible"
        decision = "skip"
        reasons = ["seniority mismatch"]
        exposed: list[str] = []
        requirements: list = []

    scored: list[str] = []
    monkeypatch.setattr(agent, "evaluate_eligibility", lambda job, candidate=None, llm=None: _Skip())
    monkeypatch.setattr(
        agent,
        "score_relevance",
        lambda *a, **k: (
            scored.append("scored")
            or SimpleNamespace(
                overall=99,
                decision="apply",
                components=[],
                explanation="",
                semantic_score=99,
                semantic_reason="perfect",
            )
        ),
    )
    monkeypatch.setattr(agent, "search_plan_jobs", lambda plan, run_id=None: [_job()])
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)
    monkeypatch.setattr(
        agent, "apply_to_job", lambda job, resume: (_ for _ in ()).throw(AssertionError("must not be called"))
    )

    result = run_job_hunter(str(sample_pdf), agent=create_agent(llm=FakeLLM()))
    assert scored == []  # PH6 never saw the ineligible job
    assert result["applications"][0]["status"] == "skipped"


def test_llm_score_cannot_override_ph5(sample_pdf, monkeypatch):
    """Even a 99/100 LLM relevance verdict cannot apply a PH5-skipped job."""

    class _Skip:
        status = "not_eligible"
        decision = "skip"
        reasons = ["hard gate: missing required skill"]
        exposed: list[str] = []
        requirements: list = []

    monkeypatch.setattr(agent, "evaluate_eligibility", lambda job, candidate=None, llm=None: _Skip())
    monkeypatch.setattr(
        agent,
        "score_relevance",
        lambda *a, **k: SimpleNamespace(
            overall=99,
            decision="apply",
            components=[],
            explanation="",
            semantic_score=99,
            semantic_reason="perfect fit",
        ),
    )
    monkeypatch.setattr(agent, "search_plan_jobs", lambda plan, run_id=None: [_job()])
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)
    monkeypatch.setattr(
        "jobhunter.automation.apply_agent.ApplyAgent",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not auto-apply")),
    )
    settings = Settings(pipeline_apply_mode="auto")
    monkeypatch.setattr(agent, "get_settings", lambda: settings)

    result = run_job_hunter(str(sample_pdf), agent=create_agent(llm=FakeLLM()))
    assert result["applications"][0]["status"] == "skipped"
    assert result["applications"][0]["explanation"]["eligibility"]["decision"] == "skip"


# ---------------------------------------------------------------------------
# 2. Deterministic hard gates: unknown knowledge is never guessed.
# ---------------------------------------------------------------------------
def test_unknown_experience_never_treated_as_zero():
    candidate = Candidate(experience_years=None)
    result = evaluate_eligibility(
        {"title": "Analyst", "description": "Must have SQL", "experience_years_min": 2},
        candidate=candidate,
    )
    assert result.decision == "review"  # never "apply" and never "skip" via guessing
    assert result.status == "waiting_for_user"


def test_unknown_candidate_never_treated_as_ineligible():
    candidate = Candidate()  # nothing known
    result = evaluate_eligibility(
        {"title": "Analyst", "description": "No explicit requirement"},
        candidate=candidate,
    )
    assert result.decision in ("apply", "review")


def test_missing_skill_knowledge_goes_to_review_not_rejection():
    candidate = Candidate()  # skills unknown
    result = evaluate_eligibility(
        {"title": "Analyst", "description": "Required: SQL Python", "required_skills": ["sql", "python"]},
        candidate=candidate,
    )
    assert result.status == "waiting_for_user"
    assert result.decision == "review"


# ---------------------------------------------------------------------------
# 3. Discovery-only jobs and unsupported portals can never auto-apply.
# ---------------------------------------------------------------------------
def test_discovery_only_never_auto_applies_graph_and_agent(sample_pdf, monkeypatch):
    class _Apply:
        status = "eligible"
        decision = "apply"
        reasons: list[str] = []
        exposed: list[str] = []
        requirements: list = []

    monkeypatch.setattr(agent, "evaluate_eligibility", lambda job, candidate=None, llm=None: _Apply())
    monkeypatch.setattr(
        agent,
        "search_plan_jobs",
        lambda plan, run_id=None: [
            _job(discovery_only=True, source="linkedin", portal="", url="https://www.linkedin.com/jobs/1"),
        ],
    )
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)
    settings = Settings(pipeline_apply_mode="auto")
    monkeypatch.setattr(agent, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "jobhunter.automation.apply_agent.ApplyAgent",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not auto-apply")),
    )

    result = run_job_hunter(str(sample_pdf), agent=create_agent(llm=FakeLLM()))
    assert result["applications"][0]["status"] == "discovery_only"


def test_unsupported_portal_never_auto_applies_and_never_falls_through(monkeypatch):
    for source in (
        "foundit",
        "hirist",
        "cutshort",
        "internshala",
        "linkedin",
        "google_jobs",
        "adzuna",
        "jooble",
    ):
        assert apply_portal_for({"source": source, "url": f"https://{source}.example/job/1"}) is None
        assert (
            may_auto_apply({"source": source, "title": "Dev", "url": f"https://{source}.example/job/1"})
            is False
        )


def test_ranked_jobs_refuses_unsupported_sources(monkeypatch):
    session = FakeSession()
    agent_obj = agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    attempted: list[str] = []
    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: attempted.append("x") or {})

    jobs = [_job(id="u1", source="foundit", portal="", url="https://foundit.in/job/1")]
    outcomes = agent_obj.apply_ranked_jobs(jobs, "invariant unique resume text", mode="auto")
    assert outcomes[0]["status"] == "needs_review"
    assert attempted == []


# ---------------------------------------------------------------------------
# 4. The dedicated browser is never bypassed; a failed browser never leads
#    to a logged-out copied profile applying.
# ---------------------------------------------------------------------------
def test_apply_agent_never_falls_back_to_copied_profile(monkeypatch):
    captured: list[bool] = []

    class _UnavailableSession:
        def start(self):
            raise SessionSafetyError("dedicated browser unavailable")

        def stop(self):
            pass

    import jobhunter.automation.apply_agent as apply_agent_mod

    def spy_build_session(settings, allow_copied_fallback=True):
        captured.append(allow_copied_fallback)
        return _UnavailableSession()

    monkeypatch.setattr(apply_agent_mod, "build_session", spy_build_session)
    monkeypatch.setattr(apply_agent_mod, "_default_llm", lambda: object())

    agent_obj = ApplyAgent(settings=Settings(pipeline_apply_mode="auto"))
    outcomes = agent_obj.apply_ranked_jobs(
        [_job(id="browser-1")], "invariant browser resume text", mode="auto"
    )
    assert captured == [False]  # copied-profile fallback explicitly refused
    assert all(o["status"] == "failed" for o in outcomes)
    assert load_applied_jobs("invariant browser resume text") == set()


# ---------------------------------------------------------------------------
# 5. Sensitive Q&A is never auto-filled; unrelated answers never inserted.
# ---------------------------------------------------------------------------
def test_sensitive_fields_never_auto_filled():
    for field in ("password", "confirm password", "otp", "captcha", "verification code"):
        assert is_skippable("", "", "", field) is True


def test_sensitive_qa_intent_never_answered_from_memory():
    from jobhunter.storage import qa as qa_store

    qa_store.save_answer("date_of_birth", "1990-01-01", "user")
    try:
        memory = QAMemory(llm=None, candidate=None, profile={})
        response = memory.answer_for_question("What is your date of birth?")
        assert response.status == "ask_user"
        assert response.reason == "sensitive" or response.reason in (
            "sensitive",
            "low_confidence",
            "unknown_intent",
            "ambiguous",
        )
    finally:
        qa_store.delete_answer("date_of_birth")


def test_unrelated_qa_question_never_answered():
    memory = QAMemory(llm=None, candidate=Candidate(experience_years=3, skills=["python"]), profile={})
    response = memory.answer_for_question("What is the airspeed velocity of an unladen swallow?")
    assert response.status == "ask_user"


# ---------------------------------------------------------------------------
# 6. Failed/uncertain submissions are never recorded as applied.
# ---------------------------------------------------------------------------
def test_unverified_submission_never_recorded_applied(monkeypatch):
    resume_text = "invariant unverified resume text unique"
    session = FakeSession()
    agent_obj = agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    def clicked_but_unknown(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        return {
            "job_id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "source": portal,
            "status": "needs_review",
            "detail": "Submit clicked but success could not be verified.",
        }

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", clicked_but_unknown)
    jobs = [_job(id="unverified-1", url="https://www.naukri.com/job/unverified-1")]
    agent_obj.apply_ranked_jobs(jobs, resume_text, mode="auto")
    assert "unverified-1" not in load_applied_jobs(resume_text)


def test_failed_submit_never_recorded_applied(monkeypatch):
    resume_text = "invariant failed resume text unique"
    session = FakeSession()
    agent_obj = agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    def failed_outcome(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        return {
            "job_id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "source": portal,
            "status": "failed",
            "detail": "Submit clicked but the page reported an error.",
        }

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", failed_outcome)
    jobs = [_job(id="failed-1", url="https://www.naukri.com/job/failed-1")]
    agent_obj.apply_ranked_jobs(jobs, resume_text, mode="auto")
    assert "failed-1" not in load_applied_jobs(resume_text)


# ---------------------------------------------------------------------------
# 7. Submission attempts are idempotent across process restarts.
# ---------------------------------------------------------------------------
def test_submission_attempt_marker_blocks_resubmit_after_crash(monkeypatch):
    from jobhunter.storage import run_state

    resume_text = "invariant crash resume text unique"
    job = _job(id="crash-1", url="https://www.naukri.com/job/crash-1")
    run_state.mark_submission_attempt(resume_text, job)

    session = FakeSession()
    agent_obj = agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    attempted: list[str] = []
    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: attempted.append("x") or {})

    outcomes = agent_obj.apply_ranked_jobs([job], resume_text, mode="auto")
    assert outcomes[0]["status"] == "needs_review"
    assert attempted == []


# ---------------------------------------------------------------------------
# 8. Source failure cannot stop other sources.
# ---------------------------------------------------------------------------
def test_one_source_failing_does_not_stop_others(monkeypatch):
    import asyncio

    from jobhunter.domains.jobs import Job

    class _Good:
        source_name = "good"

        async def search(self, query, location="India"):
            return [Job(title="Good Role", company="Acme", url="https://good.example/1", source="good")]

    class _Bad:
        source_name = "bad"

        async def search(self, query, location="India"):
            raise RuntimeError("source down")

    import jobhunter.domains.search.engine as engine

    monkeypatch.setattr(engine, "active_sources", lambda: [_Bad(), _Good()])
    jobs = asyncio.run(engine.search_all_jobs_async("python", include_portals=False))
    assert [j["title"] for j in jobs] == ["Good Role"]


# ---------------------------------------------------------------------------
# 9. Ineligible jobs are never submitted (belt and braces at every layer).
# ---------------------------------------------------------------------------
def test_ranked_jobs_refuses_non_apply_eligibility(monkeypatch):
    session = FakeSession()
    agent_obj = agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto"))
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    attempted: list[str] = []
    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: attempted.append("x") or {})

    job = _job(id="gate-1", eligibility_decision="skip")
    outcomes = agent_obj.apply_ranked_jobs([job], "invariant gate resume text", mode="auto")
    assert outcomes[0]["status"] == "needs_review"
    assert attempted == []
