"""Tests for the form-field classifier and job evaluator fallback."""

from jobhunter.automation.apply_agent import (
    ApplyAgent,
    _browser_crashed,
    _query_for_cycle,
    _verify_submission,
)
from jobhunter.automation.browser import SessionSafetyError
from jobhunter.automation.evaluator import _fallback_decision
from jobhunter.automation.form_filler import (
    _fill_control,
    _fill_select,
    classify_field,
    is_skippable,
    normalize,
)
from jobhunter.config import Settings

RESUME = (
    "Software Engineer skilled in Python, Docker, AWS, machine learning, "
    "and RAG pipelines with LangChain."
)


def test_classify_email_by_name():
    assert classify_field("", "email", "", "") == "email"


def test_classify_phone_by_placeholder():
    assert classify_field("", "", "Mobile number", "") == "phone"


def test_classify_experience_by_label():
    assert classify_field("", "", "", "Years of experience") == "experience_years"


def test_classify_unknown_field():
    assert classify_field("", "xyz123", "", "") == "unknown"


def test_password_field_is_skippable():
    assert is_skippable("", "password", "", "")
    assert is_skippable("", "", "", "Enter OTP")
    assert not is_skippable("", "", "", "Your email")


def test_normalize_strips_formatting():
    assert normalize(" First  Name! ") == "firstname"


def test_fallback_decision_applies_on_good_match():
    job = {"title": "Python Engineer", "description": "Python, Docker, AWS, machine learning required."}
    decision = _fallback_decision(job, RESUME)
    assert decision["decision"] == "apply"
    assert decision["score"] >= 60


def test_fallback_decision_skips_on_poor_match():
    job = {"title": "Java Developer", "description": "Java Spring Boot microservices with Kafka."}
    decision = _fallback_decision(job, RESUME)
    assert decision["decision"] == "skip"
    assert 0 <= decision["score"] <= 100


# ---------------------------------------------------------------------------
# Regression: "fresher" must never appear twice in a generated query
# ---------------------------------------------------------------------------
def test_query_for_cycle_appends_fresher_once_with_roles():
    settings = Settings(fresher_only=True, query_variants="fresher,entry level,remote")
    query = _query_for_cycle("", ["Data Analyst"], 1, settings)
    assert query.lower().count("fresher") == 1
    assert query == "Data Analyst fresher"


def test_query_for_cycle_no_duplicate_fresher():
    settings = Settings(fresher_only=True, query_variants="fresher,entry level,remote")
    query = _query_for_cycle("Data Analyst fresher", None, 1, settings)
    assert query.lower().count("fresher") == 1


def test_query_for_cycle_plain_when_no_variants():
    settings = Settings(fresher_only=True, query_variants="")
    assert _query_for_cycle("Data Analyst", None, 1, settings) == "Data Analyst fresher"


def test_query_for_cycle_respects_existing_fresher_term():
    settings = Settings(fresher_only=True, query_variants="")
    assert _query_for_cycle("Junior Data Analyst", None, 1, settings) == "Junior Data Analyst"


# ---------------------------------------------------------------------------
# Browser crash detection + per-job recovery
# ---------------------------------------------------------------------------
def test_browser_crashed_detects_closed_errors():
    class _ClosedError(Exception):
        pass

    assert _browser_crashed(_ClosedError("Target page, context or browser has been closed"))
    assert _browser_crashed(_ClosedError("The page has been closed"))
    assert not _browser_crashed(ValueError("boom"))


def test_apply_job_with_recovery_restarts_on_crash(monkeypatch):
    class _ClosedError(Exception):
        pass

    class _FakeSession:
        def __init__(self):
            self.restarts = 0

        def restart(self):
            self.restarts += 1

    agent = ApplyAgent()
    fake = _FakeSession()
    job = {"id": "j1", "title": "Dev", "company": "Acme", "url": "https://x.com/1"}
    calls = {"n": 0}

    def flaky(session, portal, job, profile, mode, resume_pdf):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _ClosedError("Target page, context or browser has been closed")
        return {"job_id": "j1", "title": "Dev", "company": "Acme", "source": "naukri", "status": "submitted"}

    monkeypatch.setattr(agent, "_apply_to_job", flaky)
    result = agent._apply_job_with_recovery(fake, "naukri", job, {}, "auto", None)
    assert result["status"] == "submitted"
    assert fake.restarts == 1


def test_apply_job_with_recovery_gives_up_after_retries(monkeypatch):
    class _ClosedError(Exception):
        pass

    class _FakeSession:
        def restart(self):
            pass

    agent = ApplyAgent()
    calls = {"n": 0}

    def always_crash(session, portal, job, profile, mode, resume_pdf):
        calls["n"] += 1
        raise _ClosedError("browser has been closed")

    monkeypatch.setattr(agent, "_apply_to_job", always_crash)
    result = agent._apply_job_with_recovery(_FakeSession(), "naukri", {"id": "j2"}, {}, "auto", None, retries=2)
    assert result["status"] == "failed"
    assert calls["n"] == 2


def test_apply_job_with_recovery_rethrows_other_errors(monkeypatch):
    agent = ApplyAgent()

    def boom(session, portal, job, profile, mode, resume_pdf):
        raise ValueError("bad form data")

    monkeypatch.setattr(agent, "_apply_to_job", boom)
    try:
        agent._apply_job_with_recovery(object(), "naukri", {"id": "j3"}, {}, "auto", None)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError to propagate")


# ---------------------------------------------------------------------------
# Regression (PHASE 0): a select dropdown must never auto-pick the first
# meaningful option — unmatched fields are reported as missing instead.
# ---------------------------------------------------------------------------
class _FakePage:
    def query_selector(self, selector):
        return None


class _FakeSelectHandle:
    def __init__(self, options, attrs=None, visible=True):
        self._options = options
        self._attrs = attrs or {}
        self._visible = visible
        self.page = _FakePage()
        self.selected = None

    def get_attribute(self, name):
        return self._attrs.get(name)

    def is_visible(self):
        return self._visible

    def evaluate(self, js):
        if "tagName" in js:
            return "SELECT"
        if "Array.from(el.options)" in js:
            return list(self._options)
        return None

    def select_option(self, label=None, timeout=None):
        self.selected = label


def test_select_never_auto_picks_first_option():
    handle = _FakeSelectHandle(["Select", "0-1 years", "1-2 years"])
    assert _fill_select(handle, {"experience_years": 3}, "experience_years") is False
    assert handle.selected is None


def test_select_matches_exact_option():
    handle = _FakeSelectHandle(["Select", "3 years", "5+ years"])
    assert _fill_select(handle, {"experience_years": 3}, "experience_years") is True
    assert handle.selected == "3 years"


def test_unmatched_select_reported_missing():
    handle = _FakeSelectHandle(
        ["Select", "0-1 years", "1-2 years"],
        attrs={"placeholder": "Years of experience"},
    )
    stats = {"filled": 0, "skipped": 0, "unknown": 0, "file_uploaded": False, "missing": []}
    filled = _fill_control(handle, {"experience_years": 3}, None, stats)
    assert filled is False
    assert "experience_years" in stats["missing"]
    assert handle.selected is None


# ---------------------------------------------------------------------------
# Pre-PHASE-7 hardening: honest post-submit verification
# ---------------------------------------------------------------------------
class _FakeFormPage:
    def __init__(self, url="", text="", frames=None):
        self._url = url
        self._text = text

    @property
    def url(self):
        return self._url

    def inner_text(self, selector):
        return self._text

    def wait_for_timeout(self, ms):
        return None


def test_verify_submission_success_marker():
    page = _FakeFormPage(text="Your application has been submitted successfully. Thank you.")
    assert _verify_submission(page) == "submitted"


def test_verify_submission_success_in_url():
    page = _FakeFormPage(url="https://www.naukri.com/apply/success?job=1", text="")
    assert _verify_submission(page) == "submitted"


def test_verify_submission_error_marker():
    page = _FakeFormPage(text="There was a problem submitting your application. Please try again.")
    assert _verify_submission(page) == "failed"


def test_verify_submission_obstacle_marker():
    page = _FakeFormPage(text="Complete a security check to verify you are human.")
    assert _verify_submission(page) == "failed"


def test_verify_submission_unknown_when_no_marker():
    page = _FakeFormPage(text="Please review your details before continuing.")
    assert _verify_submission(page) == "unknown"


def test_verify_submission_unknown_when_page_raises():
    class _BrokenPage:
        def wait_for_timeout(self, ms):
            raise RuntimeError("browser closed")

    assert _verify_submission(_BrokenPage()) == "unknown"


def test_submit_outcome_verified_submission_is_submitted():
    base = {"job_id": "j1", "title": "Dev", "company": "Acme", "source": "naukri"}
    result = ApplyAgent._submit_outcome(base, {}, clicked=True, verified="submitted")
    assert result["status"] == "submitted"


def test_submit_outcome_clicked_but_unverified_is_needs_review():
    base = {"job_id": "j1", "title": "Dev", "company": "Acme", "source": "naukri"}
    result = ApplyAgent._submit_outcome(base, {}, clicked=True, verified="unknown")
    assert result["status"] == "needs_review"


def test_submit_outcome_clicked_then_failed_is_failed():
    base = {"job_id": "j1", "title": "Dev", "company": "Acme", "source": "naukri"}
    result = ApplyAgent._submit_outcome(base, {}, clicked=True, verified="failed")
    assert result["status"] == "failed"


def test_submit_outcome_no_submit_button_is_needs_review():
    base = {"job_id": "j1", "title": "Dev", "company": "Acme", "source": "naukri"}
    result = ApplyAgent._submit_outcome(base, {}, clicked=False, verified="unknown")
    assert result["status"] == "needs_review"


# ---------------------------------------------------------------------------
# Pre-PHASE-7 hardening: explicit Job -> Apply contract guards
# ---------------------------------------------------------------------------
def test_should_attempt_apply_refuses_discovery_only():
    ok, reason = ApplyAgent._should_attempt_apply("naukri", {"source": "naukri", "discovery_only": True, "url": "https://x"})
    assert ok is False
    assert "discovery" in reason.lower()


def test_should_attempt_apply_refuses_unsupported_source():
    ok, reason = ApplyAgent._should_attempt_apply("naukri", {"source": "foundit", "url": "https://x"})
    assert ok is False
    assert "fall through" in reason.lower()


def test_should_attempt_apply_refuses_missing_url():
    ok, reason = ApplyAgent._should_attempt_apply("naukri", {"source": "naukri", "title": "Dev"})
    assert ok is False
    assert "url" in reason


def test_should_attempt_apply_allows_supported_complete_job():
    ok, reason = ApplyAgent._should_attempt_apply("naukri", {"source": "naukri", "title": "Dev", "url": "https://x"})
    assert ok is True
    assert reason == ""


def test_should_attempt_apply_allows_collect_cards_job():
    job = {"id": "naukri-abc", "source": "naukri", "portal": "naukri", "title": "Dev", "company": "Acme", "url": "https://x"}
    ok, reason = ApplyAgent._should_attempt_apply("naukri", job)
    assert ok is True


# ---------------------------------------------------------------------------
# Pre-PHASE-7 hardening: auto-apply refuses an unsafe browser session
# ---------------------------------------------------------------------------
def test_run_aborts_safely_when_dedicated_session_unavailable(monkeypatch):
    agent = ApplyAgent()

    class _FakeSession:
        def __init__(self, *a, **k):
            self.stopped = False

        def start(self):
            raise SessionSafetyError("dedicated browser could not be established")

        def close_all_pages(self):
            pass

        def stop(self):
            self.stopped = True

    fake = _FakeSession()
    monkeypatch.setattr(
        "jobhunter.automation.apply_agent.build_session",
        lambda settings, allow_copied_fallback=True: fake,
    )
    monkeypatch.setattr("jobhunter.automation.apply_agent._default_llm", lambda: object())

    result = agent.run("Data Analyst", "resume text", mode="auto")

    assert result["results"] == []
    assert result["mode"] == "auto"
    assert "error" in result
    assert any("blocked" in entry["message"].lower() for entry in result["log"])
    assert fake.stopped is True
