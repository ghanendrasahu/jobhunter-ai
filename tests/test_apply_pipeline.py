"""Integration tests for the PHASE 7 application pipeline.

Covers the contract end-to-end (search result -> eligibility -> ranking ->
application), the opt-in ``pipeline_apply_mode`` wire in the LangGraph graph,
and the ``ApplyAgent.apply_ranked_jobs`` entry point that consumes the PH6
-ranked eligible jobs. All browser interaction is faked/mocked; no network or
real Chrome is used.
"""

from typing import Any

import jobhunter.agent as agent
from fakes import FakeSession as _FakeSession
from fakes import agent_for as _agent_for
from fakes import job as _job
from jobhunter.agent import create_agent, run_job_hunter
from jobhunter.automation.apply_agent import ApplyAgent
from jobhunter.automation.apply_contract import (
    SEARCH_RESULT_REQUIRED_FIELDS,
    validate_job_contract,
)
from jobhunter.config import Settings
from jobhunter.domains.jobs import Job
from jobhunter.storage.history import get_application_history, load_applied_jobs, save_applied_jobs


class FakeLLM:
    def __init__(self, content: str = "Python Developer"):
        self.content = content

    def invoke(self, prompt: str) -> object:
        return type("Response", (), {"content": self.content})()


def _state(**overrides) -> dict[str, Any]:
    base: dict[str, Any] = {
        "file_path": "",
        "resume_text": "resume text",
        "search_query": "Python Developer",
        "candidate": None,
        "jobs": [],
        "applications": [],
        "error": "",
    }
    base.update(overrides)
    return base




# ---------------------------------------------------------------------------
# Search-result contract (end-to-end key retention)
# ---------------------------------------------------------------------------
def test_job_to_dict_retains_contract_keys():
    job = Job(
        title="ML Engineer",
        company="Acme",
        location="Bengaluru",
        url="https://x/jobs/1",
        source="naukri",
        description="desc",
    )
    data = job.to_dict()
    missing = validate_job_contract(data)
    assert missing == []
    assert data["fingerprint"]
    assert data["portal"] == ""  # search results carry no apply-strategy hint yet


def test_validate_job_contract_reports_missing_keys():
    assert "fingerprint" in validate_job_contract({"id": "x", "title": "t", "company": "c", "url": "u"})
    assert validate_job_contract(_job()) == []


def test_search_result_contract_matches_apply_layer_needs():
    """Every key the apply layer reads is retained by search results."""
    job = Job(
        title="Dev",
        company="Acme",
        location="India",
        url="https://x/1",
        source="indeed",
        description="desc",
        required_skills=["Python"],
        preferred_skills=["AWS"],
        seniority="JUNIOR",
    )
    data = job.to_dict()
    for field in SEARCH_RESULT_REQUIRED_FIELDS:
        assert field in data


def test_google_jobs_results_are_discovery_only(monkeypatch):
    import jobhunter.domains.search.sources.google_jobs as gj

    html = """<html><body>
    <script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
    "title":"ML Engineer","hiringOrganization":{"name":"Acme"},
    "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress",
    "addressLocality":"Bengaluru"}},
    "url":"https://acme.com/jobs/ml","description":"Build ML models"}</script>
    </body></html>"""

    class _Resp:
        status_code = 200
        text = html

    monkeypatch.setattr(gj.requests, "get", lambda *a, **k: _Resp())

    import asyncio

    jobs = asyncio.run(gj.GoogleJobsSource().search("ML Engineer"))
    assert jobs, "expected at least one parsed job"
    assert all(j.discovery_only for j in jobs)


def test_collect_cards_emits_contract_keys():
    from jobhunter.automation.strategies import collect_cards

    class _El:
        def __init__(self, text="", href="https://www.naukri.com/job/1"):
            self._text = text
            self._href = href

        def inner_text(self):
            return self._text

        def get_attribute(self, name):
            return self._href if name == "href" else None

    class _Card:
        def __init__(self):
            self._els = {
                "jobTitle": _El("Python Developer"),
                "jobCompanyName": _El("Acme"),
                "jobLocation": _El("Bengaluru"),
                "jobdescription": _El("Build APIs"),
                "article__link": _El(href="https://www.naukri.com/job/1"),
            }

        def query_selector(self, selector):
            for key, el in self._els.items():
                if key in selector or selector in key:
                    return el
            return None

        def inner_text(self):
            return "Python Developer Acme Bengaluru fresher 0-1 years"

    class _Page:
        url = "https://www.naukri.com/python-jobs"

        def query_selector_all(self, selector):
            return [_Card()]

    cards = collect_cards(_Page(), "naukri", max_results=5)
    assert len(cards) == 1
    missing = validate_job_contract(cards[0])
    assert missing == []
    assert cards[0]["fingerprint"]
    assert cards[0]["discovery_only"] is False
    assert cards[0]["portal"] == "naukri"


# ---------------------------------------------------------------------------
# Graph wiring: opt-in pipeline_apply_mode
# ---------------------------------------------------------------------------
def _run_graph(sample_pdf, monkeypatch, jobs, pipeline_mode):
    from types import SimpleNamespace

    def fake_score(job, candidate=None, resume_text="", llm=None):
        return SimpleNamespace(
            overall=job.get("match_score", 0),
            decision="apply",
            components=[],
            explanation="fake relevance score",
            semantic_score=None,
            semantic_reason="",
        )

    monkeypatch.setattr(agent, "search_plan_jobs", lambda plan, run_id=None: jobs)
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)
    monkeypatch.setattr(agent, "score_relevance", fake_score)
    settings = Settings(pipeline_apply_mode=pipeline_mode, max_applications_per_run=5)
    monkeypatch.setattr(agent, "get_settings", lambda: settings)
    return run_job_hunter(str(sample_pdf), agent=create_agent(llm=FakeLLM()))


def test_graph_default_mode_records_only_never_submits(sample_pdf, monkeypatch):
    jobs = [_job()]
    monkeypatch.setattr(
        agent,
        "apply_to_job",
        lambda job, resume: {
            "job_id": job["id"],
            "job_title": job["title"],
            "company": job["company"],
            "status": "recorded",
            "detail": "Job recorded — open the link to apply manually.",
        },
    )
    result = _run_graph(sample_pdf, monkeypatch, jobs, "off")
    assert result["error"] == ""
    assert result["applications"][0]["status"] == "recorded"
    assert result["applications"][0]["explanation"]["application"]["route"] == "naukri"


def test_graph_optin_routes_supported_jobs_in_ranked_order(sample_pdf, monkeypatch):
    jobs = [
        _job(id="j-low", url="https://www.naukri.com/job/low", match_score=60, relevance_decision="apply"),
        _job(id="j-high", url="https://www.naukri.com/job/high", match_score=90, relevance_decision="apply"),
    ]
    captured: list[list[str]] = []

    class _FakeAgent:
        def apply_ranked_jobs(self, ranked, resume_text, **kwargs):
            captured.append([j["id"] for j in ranked])
            assert kwargs["mode"] == "human"
            assert kwargs["max_applications"] == 5
            return [
                {
                    "job_id": j["id"],
                    "title": j["title"],
                    "company": j["company"],
                    "source": j["source"],
                    "status": "handed_off",
                    "detail": "Form pre-filled.",
                }
                for j in ranked
            ]

    monkeypatch.setattr("jobhunter.automation.apply_agent.ApplyAgent", _FakeAgent)
    result = _run_graph(sample_pdf, monkeypatch, jobs, "human")
    assert result["error"] == ""
    # PH6 ranking order must be preserved into the application step.
    assert captured == [["j-high", "j-low"]]
    assert [a["job_id"] for a in result["applications"]] == ["j-high", "j-low"]
    assert all(a["explanation"]["application"]["outcome"] == "handed_off" for a in result["applications"])


def test_graph_optin_never_routes_discovery_only_or_unsupported(sample_pdf, monkeypatch):
    jobs = [
        _job(
            id="j-linkedin",
            source="linkedin",
            portal="",
            url="https://www.linkedin.com/jobs/1",
            discovery_only=True,
        ),
        _job(id="j-foundit", source="foundit", portal="", url="https://www.foundit.in/job/1"),
        _job(
            id="j-google",
            source="google_jobs",
            portal="",
            url="https://www.google.com/search?q=x",
            discovery_only=True,
        ),
    ]
    monkeypatch.setattr(
        "jobhunter.automation.apply_agent.ApplyAgent",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    result = _run_graph(sample_pdf, monkeypatch, jobs, "auto")
    assert result["error"] == ""
    statuses = {a["job_id"]: a["status"] for a in result["applications"]}
    assert statuses["j-linkedin"] == "discovery_only"
    assert statuses["j-foundit"] == "needs_review"
    assert statuses["j-google"] == "discovery_only"


def test_graph_optin_missing_contract_keys_goes_needs_review(sample_pdf, monkeypatch):
    job = _job(id="j-incomplete")
    for key in ("url", "fingerprint", "seniority", "portal"):
        job.pop(key, None)
    jobs = [job]
    monkeypatch.setattr(
        "jobhunter.automation.apply_agent.ApplyAgent",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    result = _run_graph(sample_pdf, monkeypatch, jobs, "auto")
    assert result["applications"][0]["status"] == "needs_review"
    assert "contract" in result["applications"][0]["detail"].lower()


def test_graph_optin_apply_agent_explosion_marks_failed_not_submitted(sample_pdf, monkeypatch):
    jobs = [_job()]

    class _ExplodingAgent:
        def apply_ranked_jobs(self, ranked, resume_text, **kwargs):
            raise RuntimeError("browser blew up")

    monkeypatch.setattr("jobhunter.automation.apply_agent.ApplyAgent", _ExplodingAgent)
    result = _run_graph(sample_pdf, monkeypatch, jobs, "auto")
    assert result["error"] == ""
    assert result["applications"][0]["status"] == "failed"
    assert "browser blew up" in result["applications"][0]["detail"]


def test_graph_skip_and_review_short_circuit_before_routing(sample_pdf, monkeypatch):
    jobs = [
        _job(id="j-skip", eligibility_decision="skip", eligibility_reasons=["seniority mismatch"]),
        _job(id="j-review", eligibility_decision="review", eligibility_reasons=["unknown experience"]),
    ]

    class _Elig:
        def __init__(self, decision):
            self.status = {"skip": "not_eligible", "review": "waiting_for_user"}[decision]
            self.decision = decision
            self.reasons = ["canned eligibility result"]
            self.exposed = []
            self.requirements = []

    monkeypatch.setattr(
        agent,
        "evaluate_eligibility",
        lambda job, candidate=None, llm=None: _Elig(job["eligibility_decision"]),
    )
    monkeypatch.setattr(
        "jobhunter.automation.apply_agent.ApplyAgent",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    result = _run_graph(sample_pdf, monkeypatch, jobs, "auto")
    statuses = {a["job_id"]: a["status"] for a in result["applications"]}
    assert statuses == {"j-skip": "skipped", "j-review": "needs_review"}


# ---------------------------------------------------------------------------
# ApplyAgent.apply_ranked_jobs (browser fully faked)
# ---------------------------------------------------------------------------




UNIQUE = "phase7 unique resume text %s"


def test_ranked_jobs_respect_cap_and_preserve_order(monkeypatch):
    jobs = [_job(id=f"job-{i}", url=f"https://www.naukri.com/job/{i}") for i in range(3)]
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session, Settings(pipeline_apply_mode="auto", max_applications_per_run=2))
    attempts: list[str] = []

    def fake_apply(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        attempts.append(job["id"])
        return {
            "job_id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "source": portal,
            "status": "submitted",
            "detail": "Application submitted and confirmed.",
        }

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", fake_apply)
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    outcomes = agent.apply_ranked_jobs(jobs, UNIQUE % "cap", mode="auto", max_applications=2)
    assert attempts == ["job-0", "job-1"]  # order preserved, third deferred by the cap
    assert [o["status"] for o in outcomes] == ["submitted", "submitted", "deferred"]
    assert load_applied_jobs(UNIQUE % "cap") >= {"job-0", "job-1"}
    assert "job-2" not in load_applied_jobs(UNIQUE % "cap")


def test_ranked_jobs_skip_already_applied(monkeypatch):
    resume_text = UNIQUE % "dedup"
    save_applied_jobs(
        resume_text,
        ["job-dup"],
        [
            {
                "job_id": "job-dup",
                "title": "Python Developer",
                "company": "Acme",
                "source": "naukri",
                "url": "https://www.naukri.com/job/dup",
                "status": "submitted",
                "detail": "ok",
                "applied_at": "2026-11-08T00:00:00",
            }
        ],
    )
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session)
    attempts: list[str] = []

    def fake_apply(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        attempts.append(job["id"])
        return {
            "job_id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "source": portal,
            "status": "submitted",
            "detail": "Application submitted and confirmed.",
        }

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", fake_apply)
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    jobs = [
        _job(id="job-dup", url="https://www.naukri.com/job/dup"),
        _job(id="job-new", url="https://www.naukri.com/job/new"),
    ]
    outcomes = agent.apply_ranked_jobs(jobs, resume_text, mode="auto")
    assert attempts == ["job-new"]  # duplicate was never attempted
    assert [o["status"] for o in outcomes] == ["already_applied", "submitted"]


def test_ranked_jobs_browser_block_never_submits(monkeypatch):
    session = _FakeSession(fail_start=RuntimeError("dedicated browser unavailable"))
    agent = _agent_for(monkeypatch, session)
    called: list[str] = []
    monkeypatch.setattr(
        ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: called.append("x") or {}
    )  # must not run

    jobs = [_job(id="job-1")]
    outcomes = agent.apply_ranked_jobs(jobs, UNIQUE % "block", mode="auto")
    assert all(o["status"] == "failed" for o in outcomes)
    assert called == []
    assert session.stopped is True
    assert load_applied_jobs(UNIQUE % "block") == set()


def test_ranked_jobs_login_failure_not_attempted(monkeypatch):
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session)
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: False)
    called: list[str] = []
    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: called.append("x") or {})

    jobs = [_job(id="job-login")]
    outcomes = agent.apply_ranked_jobs(jobs, UNIQUE % "login", mode="auto")
    assert outcomes[0]["status"] == "failed"
    assert called == []


def test_ranked_jobs_unverified_submission_not_marked_applied(monkeypatch):
    resume_text = UNIQUE % "unverified"
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session)
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    def fake_needs_review(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        return {
            "job_id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "source": portal,
            "status": "needs_review",
            "detail": "Submit clicked but success could not be verified.",
        }

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", fake_needs_review)
    jobs = [_job(id="job-unverified", url="https://www.naukri.com/job/unv")]
    outcomes = agent.apply_ranked_jobs(jobs, resume_text, mode="auto")
    assert outcomes[0]["status"] == "needs_review"
    assert "job-unverified" not in load_applied_jobs(resume_text)
    history = get_application_history(resume_text)
    statuses = [j.get("status") for j in history["applied_jobs"]]
    assert statuses == ["needs_review"]  # persisted as an honest outcome, not applied


def test_ranked_jobs_refuses_discovery_only_and_unsupported(monkeypatch):
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session)
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    attempted: list[str] = []
    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: attempted.append("x") or {})

    jobs = [
        _job(id="job-discovery", discovery_only=True),
        _job(id="job-unsupported", source="foundit", portal="", url="https://www.foundit.in/job/1"),
    ]
    outcomes = agent.apply_ranked_jobs(jobs, UNIQUE % "refuse", mode="auto")
    assert [o["status"] for o in outcomes] == ["discovery_only", "needs_review"]
    assert attempted == []


def test_ranked_jobs_fresher_gate_skips_high_experience(monkeypatch):
    session = _FakeSession()
    agent = _agent_for(
        monkeypatch, session, Settings(pipeline_apply_mode="auto", fresher_only=True, max_experience_years=2)
    )
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    attempted: list[str] = []
    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", lambda *a, **k: attempted.append("x") or {})

    jobs = [
        _job(
            id="job-senior",
            title="Senior Developer",
            description="minimum 5 years of experience in Python",
            url="https://www.naukri.com/senior/5+years",
        )
    ]
    outcomes = agent.apply_ranked_jobs(jobs, UNIQUE % "fresher", mode="auto")
    assert outcomes[0]["status"] == "skipped"
    assert attempted == []


def test_ranked_jobs_human_mode_hands_off_without_recording_applied(monkeypatch):
    resume_text = UNIQUE % "human"
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session)
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    def fake_handed_off(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        return {
            "job_id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "source": portal,
            "status": "handed_off",
            "detail": "Form pre-filled. Complete & submit in the browser window.",
        }

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", fake_handed_off)
    jobs = [_job(id="job-human", url="https://www.naukri.com/job/human")]
    outcomes = agent.apply_ranked_jobs(jobs, resume_text, mode="human")
    assert outcomes[0]["status"] == "handed_off"
    assert "job-human" not in load_applied_jobs(resume_text)


def test_ranked_jobs_returns_one_outcome_per_input_job(monkeypatch):
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session)
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
    jobs = [_job(id=f"job-{i}", url=f"https://www.naukri.com/job/{i}") for i in range(4)]
    outcomes = agent.apply_ranked_jobs(jobs, UNIQUE % "one-to-one", mode="auto", max_applications=2)
    assert len(outcomes) == len(jobs)


def test_ranked_jobs_off_mode_never_attempts(monkeypatch):
    session = _FakeSession()
    agent = _agent_for(monkeypatch, session)
    monkeypatch.setattr("jobhunter.automation.apply_agent.build_session", lambda *a, **k: session)
    outcomes = agent.apply_ranked_jobs([_job(id="job-off")], UNIQUE % "off", mode="off")
    assert outcomes[0]["status"] == "handed_off"
    assert session.started is False
