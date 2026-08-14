"""Tests for conditional full-description retrieval."""

from jobhunter.domains.jobs import Job
from jobhunter.domains.search.description import (
    ensure_full_descriptions,
    extract_description,
    fetch_full_description,
    snippet_sufficient,
)

FULL_HTML = """
<html><head><title>Job</title></head><body>
<div class="header">Acme Corp</div>
<div class="job-description">
  <p>We are hiring a Senior Data Scientist to own end-to-end machine learning
  projects from experimentation to production deployment.</p>
  <p>Responsibilities: design and train models for recommendation systems,
  natural language processing, and forecasting pipelines; collaborate with
  product and engineering teams; mentor junior data scientists.</p>
  <p>Must have: 4+ years of industry experience with Python, PyTorch, and
  scikit-learn. Experience with LangChain, vector databases, and LLM
  evaluation is a strong plus. Familiarity with AWS or GCP is preferred.</p>
  <p>Location: Remote (India). Compensation includes competitive salary, stock
  options, health insurance, and generous learning budgets.</p>
</div>
<div class="footer">footer stuff</div>
</body></html>
"""


def test_snippet_sufficient_short_snippet_is_not():
    assert not snippet_sufficient("Python engineer")
    assert not snippet_sufficient("")


def test_snippet_sufficient_long_snippet_is():
    text = " ".join(["word"] * 55)
    assert len(text) >= 200
    assert snippet_sufficient(text)


def test_extract_description_finds_marked_block():
    description = extract_description(FULL_HTML)
    assert "Senior Data Scientist" in description
    assert "PyTorch" in description
    assert "footer stuff" not in description


def test_extract_description_falls_back_to_page_text():
    html = "<html><body><p>Some job details with enough content.</p></body></html>"
    assert "Some job details" in extract_description(html)


def test_extract_description_returns_empty_for_garbage():
    assert extract_description("") == ""


def test_fetch_full_description_returns_empty_on_failure():
    assert fetch_full_description("https://127.0.0.1:1/never") == ""


def test_fetch_full_description_uses_session(monkeypatch):
    class _FakeResponse:
        status_code = 200
        text = "<html><body>Hello</body></html>"

    class _FakeSession:
        def get(self, url, timeout=None, headers=None):
            assert url == "https://x.com/job"
            return _FakeResponse()

    html = fetch_full_description("https://x.com/job", session=_FakeSession())
    assert "Hello" in html


def _thin_job(url="https://x.com/job", description=""):
    return Job(
        title="T",
        company="C",
        url=url,
        description=description,
        description_truncated=True,
        source="indeed",
    )


def test_ensure_full_descriptions_refreshes_thin_snippet(monkeypatch):
    job = _thin_job(description="short snippet")
    fake_session = _FakeSession()

    monkeypatch.setattr("jobhunter.domains.search.description.fetch_full_description", lambda url, session=None: FULL_HTML)

    fetched = ensure_full_descriptions([job], session=fake_session, max_fetches=5)
    assert fetched == 1
    assert job.description_truncated is False
    assert "PyTorch" in job.description


def test_ensure_full_descriptions_skips_sufficient_snippets(monkeypatch):
    rich = " ".join(["word"] * 50)
    job = _thin_job(description=rich)
    calls = {"n": 0}

    def _fake_fetch(url, session=None):
        calls["n"] += 1
        return FULL_HTML

    monkeypatch.setattr("jobhunter.domains.search.description.fetch_full_description", _fake_fetch)

    assert ensure_full_descriptions([job], max_fetches=5) == 0
    assert calls["n"] == 0


def test_ensure_full_descriptions_respects_max_fetches(monkeypatch):
    jobs = [_thin_job(url=f"https://x.com/{i}", description="tiny") for i in range(10)]
    monkeypatch.setattr("jobhunter.domains.search.description.fetch_full_description", lambda url, session=None: FULL_HTML)

    fetched = ensure_full_descriptions(jobs, max_fetches=3)
    assert fetched == 3
    refreshed = [j for j in jobs if not j.description_truncated]
    assert len(refreshed) == 3


def test_ensure_full_descriptions_ignores_short_extracted_text(monkeypatch):
    job = _thin_job(description="tiny")
    monkeypatch.setattr("jobhunter.domains.search.description.fetch_full_description", lambda url, session=None: "<html><body>hi</body></html>")

    assert ensure_full_descriptions([job], max_fetches=5) == 0
    assert job.description_truncated is True


class _FakeResponse:
    status_code = 200
    text = "<html><body>Hello</body></html>"


class _FakeSession:
    def get(self, url, timeout=None, headers=None):
        return _FakeResponse()
