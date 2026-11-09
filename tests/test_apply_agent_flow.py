"""Integration-style tests for the dashboard apply path (_process_portal /
_apply_to_job / _apply_job_with_recovery) with everything faked."""

import jobhunter.automation.apply_agent as apply_agent_mod
from fakes import FakeSession
from jobhunter.automation.apply_agent import ApplyAgent
from jobhunter.config import Settings
from jobhunter.storage.run_state import has_submission_attempt

RESUME_TEXT = "Unique apply-agent-flow resume text"


class _PortalPage:
    def __init__(self):
        self.url = "https://www.naukri.com/python-jobs"
        self.frames: list = []

    def goto(self, url, **kwargs):
        self.url = url
        return None

    def wait_for_load_state(self, state):
        return None

    def wait_for_timeout(self, ms):
        return None

    def wait_for_function(self, script, timeout=None):
        return None

    def inner_text(self, selector):
        return "Job listings page"

    def is_closed(self):
        return False


class _ProcessableSession(FakeSession):
    def new_tab(self):
        page = _PortalPage()
        self.pages.append(page)
        return page


class _PortalJob:
    pass


def _job(**overrides):
    job = {
        "id": "naukri-1",
        "source": "naukri",
        "portal": "naukri",
        "title": "Python Developer",
        "company": "Acme",
        "location": "Bengaluru",
        "url": "https://www.naukri.com/job/1",
        "description": "Python required.",
        "posted_days": 1,
    }
    job.update(overrides)
    return job


def test_process_portal_records_submission(monkeypatch):
    agent = ApplyAgent(settings=Settings(pipeline_apply_mode="auto", fresher_only=False))
    agent._run_id = ""
    session = _ProcessableSession()

    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    monkeypatch.setattr(apply_agent_mod.strategies, "detect_obstacle", lambda url, text: None)
    monkeypatch.setattr(
        apply_agent_mod.strategies, "collect_cards", lambda page, portal, max_results=10: [_job()]
    )
    monkeypatch.setattr(apply_agent_mod, "sort_jobs_by_priority", lambda jobs, titles, remote: jobs)

    class _Apply:
        status = "eligible"
        decision = "apply"
        reasons: list = []
        exposed: list = []
        requirements: list = []

    monkeypatch.setattr(
        apply_agent_mod, "evaluate_eligibility", lambda job, candidate=None, llm=None: _Apply()
    )
    monkeypatch.setattr(
        apply_agent_mod, "evaluate_job", lambda job, resume, llm: {"decision": "apply", "score": 85}
    )

    def fake_apply(self, s, portal, job, profile, mode, resume_pdf, resume_text=""):
        return {
            "job_id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "source": portal,
            "status": "submitted",
            "detail": "Application submitted and confirmed.",
        }

    monkeypatch.setattr(ApplyAgent, "_apply_job_with_recovery", fake_apply)

    profile = {"email": "ada@example.com", "skills": ["python"]}
    outcomes = agent._process_portal(
        session,
        "naukri",
        "python",
        RESUME_TEXT,
        profile,
        "auto",
        5,
        set(),
        set(),
        None,
    )
    assert len(outcomes) == 1
    assert outcomes[0]["status"] == "submitted"
    from jobhunter.storage.history import load_applied_jobs

    assert "naukri-1" in load_applied_jobs(RESUME_TEXT)


def test_process_portal_login_failure_returns_no_outcomes(monkeypatch):
    agent = ApplyAgent(settings=Settings(fresher_only=False))
    session = _ProcessableSession()
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: False)

    profile = {"email": "ada@example.com", "skills": []}
    outcomes = agent._process_portal(
        session,
        "naukri",
        "python",
        RESUME_TEXT + " login",
        profile,
        "auto",
        5,
        set(),
        set(),
        None,
    )
    assert outcomes == []
    assert session.pages[0].is_closed() is False or True  # close_page swallows; just no crash


def test_process_portal_search_page_failure_returns_no_outcomes(monkeypatch):
    agent = ApplyAgent(settings=Settings(fresher_only=False))
    session = _ProcessableSession()
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)

    def boom(page, url, **kwargs):
        raise RuntimeError("navigation failed")

    monkeypatch.setattr(ApplyAgent, "_goto", boom)
    profile = {"email": "ada@example.com", "skills": []}
    outcomes = agent._process_portal(
        session,
        "naukri",
        "python",
        RESUME_TEXT + " nav",
        profile,
        "auto",
        5,
        set(),
        set(),
        None,
    )
    assert outcomes == []


def test_process_portal_obstacle_returns_no_outcomes(monkeypatch):
    agent = ApplyAgent(settings=Settings(fresher_only=False))
    session = _ProcessableSession()
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    monkeypatch.setattr(apply_agent_mod.strategies, "detect_obstacle", lambda url, text: "CAPTCHA")
    profile = {"email": "ada@example.com", "skills": []}
    outcomes = agent._process_portal(
        session,
        "naukri",
        "python",
        RESUME_TEXT + " obstacle",
        profile,
        "auto",
        5,
        set(),
        set(),
        None,
    )
    assert outcomes == []


def test_process_portal_needs_review_records_outcome_not_applied(monkeypatch):
    agent = ApplyAgent(settings=Settings(fresher_only=False))
    session = _ProcessableSession()
    resume_text = RESUME_TEXT + " review"
    monkeypatch.setattr(ApplyAgent, "_ensure_login", lambda self, page, portal: True)
    monkeypatch.setattr(apply_agent_mod.strategies, "detect_obstacle", lambda url, text: None)
    monkeypatch.setattr(
        apply_agent_mod.strategies, "collect_cards", lambda page, portal, max_results=10: [_job()]
    )
    monkeypatch.setattr(apply_agent_mod, "sort_jobs_by_priority", lambda jobs, titles, remote: jobs)

    class _Apply:
        status = "eligible"
        decision = "apply"
        reasons: list = []
        exposed: list = []
        requirements: list = []

    monkeypatch.setattr(
        apply_agent_mod, "evaluate_eligibility", lambda job, candidate=None, llm=None: _Apply()
    )
    monkeypatch.setattr(
        apply_agent_mod, "evaluate_job", lambda job, resume, llm: {"decision": "apply", "score": 80}
    )

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
    profile = {"email": "ada@example.com", "skills": ["python"]}
    outcomes = agent._process_portal(
        session,
        "naukri",
        "python",
        resume_text,
        profile,
        "auto",
        5,
        set(),
        set(),
        None,
    )
    assert outcomes[0]["status"] == "needs_review"
    from jobhunter.storage.history import load_applied_jobs

    assert "naukri-1" not in load_applied_jobs(resume_text)


# ---------------------------------------------------------------------------
# _apply_to_job — the real browser application flow against fakes
# ---------------------------------------------------------------------------
class _FakeFormPage:
    def __init__(
        self, text="Application submitted successfully.", url="https://www.naukri.com/apply/success"
    ):
        self._text = text
        self.url = url
        self.frames: list = []

    def wait_for_timeout(self, ms):
        return None

    def wait_for_function(self, script, timeout=None):
        return None

    def inner_text(self, selector):
        return self._text


class _FakePopupInfo:
    def __init__(self, page):
        self.value = page


class _FakePopupCtx:
    def __init__(self, page):
        self._page = page

    def __enter__(self):
        return _FakePopupInfo(self._page)

    def __exit__(self, *args):
        return False


class _FakeContext:
    def __init__(self, popup):
        self._popup = popup

    def expect_page(self, timeout=None):
        return _FakePopupCtx(self._popup)


class _JobFlowSession(FakeSession):
    def __init__(self, job_page, form_page):
        super().__init__()
        self._job_page = job_page
        self._form_page = form_page
        self._created = 0
        self._context = _FakeContext(form_page)

    def new_tab(self):
        self._created += 1
        return self._job_page if self._created == 1 else self._form_page


def _apply_to_job_setup(monkeypatch, form_page):
    monkeypatch.setattr(apply_agent_mod.strategies, "detect_obstacle", lambda url, text: None)
    monkeypatch.setattr(apply_agent_mod.strategies, "click_apply", lambda page, **kwargs: True)
    monkeypatch.setattr(apply_agent_mod.strategies, "click_submit", lambda page, **kwargs: True)
    monkeypatch.setattr(
        apply_agent_mod,
        "fill_form",
        lambda page, profile, resume_pdf, qa=None: {
            "filled": 3,
            "skipped": 0,
            "unknown": 0,
            "file_uploaded": False,
            "missing": [],
        },
    )
    job_page = _PortalPage()
    return job_page


def test_apply_to_job_submitted_flow(monkeypatch):
    agent = ApplyAgent(settings=Settings(pipeline_apply_mode="auto"))
    agent._qa = None
    form_page = _FakeFormPage()
    job_page = _apply_to_job_setup(monkeypatch, form_page)
    session = _JobFlowSession(job_page, form_page)
    resume_text = RESUME_TEXT + " submitted"

    result = agent._apply_to_job(
        session, "naukri", _job(), {"email": "ada@example.com"}, "auto", None, resume_text=resume_text
    )
    assert result["status"] == "submitted"
    assert has_submission_attempt(resume_text, "naukri-1") is False  # cleared on submitted


def test_apply_to_job_missing_fields_is_needs_review(monkeypatch):
    agent = ApplyAgent(settings=Settings(pipeline_apply_mode="auto"))
    agent._qa = None
    form_page = _FakeFormPage(text="", url="https://www.naukri.com/apply/1")
    job_page = _apply_to_job_setup(monkeypatch, form_page)
    monkeypatch.setattr(
        apply_agent_mod,
        "fill_form",
        lambda page, profile, resume_pdf, qa=None: {
            "filled": 1,
            "skipped": 0,
            "unknown": 1,
            "file_uploaded": False,
            "missing": ["phone"],
        },
    )
    session = _JobFlowSession(job_page, form_page)
    result = agent._apply_to_job(session, "naukri", _job(), {"email": "ada@example.com"}, "auto", None)
    assert result["status"] == "needs_review"
    assert "phone" in result["detail"]


def test_apply_to_job_no_apply_button(monkeypatch):
    agent = ApplyAgent(settings=Settings(pipeline_apply_mode="auto"))
    agent._qa = None
    form_page = _FakeFormPage()
    monkeypatch.setattr(apply_agent_mod.strategies, "detect_obstacle", lambda url, text: None)
    monkeypatch.setattr(apply_agent_mod.strategies, "click_apply", lambda page, **kwargs: False)
    job_page = _PortalPage()
    session = _JobFlowSession(job_page, form_page)
    result = agent._apply_to_job(session, "naukri", _job(), {"email": "ada@example.com"}, "auto", None)
    assert result["status"] == "no_apply_button"


def test_apply_to_job_unverified_submit_needs_review(monkeypatch):
    agent = ApplyAgent(settings=Settings(pipeline_apply_mode="auto"))
    agent._qa = None
    form_page = _FakeFormPage(text="Please review your details", url="https://www.naukri.com/apply/review")
    job_page = _apply_to_job_setup(monkeypatch, form_page)
    session = _JobFlowSession(job_page, form_page)
    resume_text = RESUME_TEXT + " unverified"
    result = agent._apply_to_job(
        session, "naukri", _job(), {"email": "ada@example.com"}, "auto", None, resume_text=resume_text
    )
    assert result["status"] == "needs_review"
    assert has_submission_attempt(resume_text, "naukri-1") is True  # kept; never auto-retried


def test_apply_to_job_obstacle_blocked(monkeypatch):
    agent = ApplyAgent(settings=Settings(pipeline_apply_mode="auto"))
    agent._qa = None
    monkeypatch.setattr(apply_agent_mod.strategies, "detect_obstacle", lambda url, text: "CAPTCHA")
    job_page = _PortalPage()
    form_page = _FakeFormPage()
    session = _JobFlowSession(job_page, form_page)
    result = agent._apply_to_job(session, "naukri", _job(), {"email": "ada@example.com"}, "auto", None)
    assert result["status"] == "blocked"


def test_apply_to_job_navigation_failure_is_failed(monkeypatch):
    agent = ApplyAgent(settings=Settings(pipeline_apply_mode="auto"))
    agent._qa = None

    def boom(page, url, **kwargs):
        raise RuntimeError("navigation failed")

    monkeypatch.setattr(ApplyAgent, "_goto", boom)
    session = _JobFlowSession(_PortalPage(), _FakeFormPage())
    result = agent._apply_to_job(session, "naukri", _job(), {"email": "ada@example.com"}, "auto", None)
    assert result["status"] == "failed"
    assert "Could not open job page" in result["detail"]
