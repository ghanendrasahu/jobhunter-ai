"""Tests for portal links and the orchestrated job search engine."""

import jobhunter.domains.search.engine as engine
from jobhunter.domains.jobs import Job
from jobhunter.domains.search.portals import build_portal_urls
from jobhunter.domains.search.sources.base import active_sources as registered_sources


def test_build_portal_urls_returns_links():
    urls = build_portal_urls("Python Developer")
    assert len(urls) == 5
    for link in urls:
        assert link["is_portal_link"] is True
        assert link["url"].startswith("https://")
        assert link["source"] in {"naukri", "indeed", "linkedin", "monster", "google_jobs"}


def test_build_portal_urls_url_encodes_query():
    urls = build_portal_urls("Data Scientist")
    assert any("Data%20Scientist" in u["url"] for u in urls)


class _FakeSource:
    """Minimal JobSource returning a fixed list of jobs (or raising)."""

    def __init__(self, jobs, error: Exception | None = None):
        self._jobs = jobs
        self._error = error

    async def search(self, query, location="India", max_results=10):
        if self._error is not None:
            raise self._error
        return self._jobs


def _job(job_id: str, title: str, company: str, url: str, source: str, location: str = "") -> Job:
    return Job(
        title=title,
        company=company,
        location=location,
        url=url,
        source=source,
        source_job_id=job_id,
    )


def _sources(*sources) -> list[_FakeSource]:
    return list(sources)


def _noop(_query) -> list:
    return []


def _patch_search(monkeypatch, sources):
    monkeypatch.setattr(engine, "active_sources", lambda: _sources(*sources))
    monkeypatch.setattr(engine, "search_adzuna_jobs", _noop)
    monkeypatch.setattr(engine, "search_jooble_jobs", _noop)
    monkeypatch.setattr(engine, "search_jsearch_jobs", _noop)


def test_search_all_jobs_returns_portals_and_scraped(monkeypatch):
    _patch_search(monkeypatch, [
        _FakeSource([_job("1", "X", "C", "https://a.com/j1", "indeed")]),
        _FakeSource([_job("2", "Y", "C", "https://a.com/j2", "linkedin")]),
        _FakeSource([]),  # naukri finds nothing
    ])

    jobs = engine.search_all_jobs("Python Developer")
    sources = {j["source"] for j in jobs}
    assert "indeed" in sources
    assert "linkedin" in sources
    # 5 portal links + 2 scraped = 7
    assert len(jobs) == 7


def test_search_all_jobs_deduplicates_urls(monkeypatch):
    _patch_search(monkeypatch, [
        _FakeSource([_job("1", "X", "C", "https://a.com/j1", "indeed")]),
        _FakeSource([_job("2", "Y", "C", "https://a.com/j2", "linkedin")]),
        _FakeSource([_job("3", "Z", "C", "https://a.com/j1", "naukri")]),  # duplicate URL
    ])

    jobs = engine.search_all_jobs("Python Developer")
    urls = [j["url"] for j in jobs if not j.get("is_portal_link")]
    assert len(urls) == len(set(urls))  # no duplicate scraped urls
    assert len(urls) == 2


def test_search_all_jobs_deduplicates_company_title(monkeypatch):
    _patch_search(monkeypatch, [
        _FakeSource([_job("1", "X", "C", "https://a.com/j1", "indeed")]),
        _FakeSource([_job("2", "Y", "C", "https://a.com/j2", "linkedin")]),
        _FakeSource([]),
    ])
    # Same company + title as the LinkedIn job, but a different URL.
    monkeypatch.setattr(engine, "search_jsearch_jobs", lambda _q: [
        {"id": "jsearch-1", "title": "Y", "company": "C", "url": "https://other.com/j2", "source": "jsearch"}
    ])

    jobs = engine.search_all_jobs("Python Developer")
    # 5 portal links + 2 scraped (LinkedIn "Y@C" dedupes the jsearch "Y@C").
    assert len(jobs) == 7
    non_portal = [j for j in jobs if not j.get("is_portal_link")]
    assert len(non_portal) == 2


def test_search_all_jobs_accepts_dict_sources(monkeypatch):
    """Legacy dict-returning sources are wrapped defensively into jobs."""
    monkeypatch.setattr(engine, "active_sources", lambda: [
        _FakeSource([{"id": "d1", "title": "D", "company": "C", "url": "https://a.com/d1", "source": "indeed"}])
    ])
    monkeypatch.setattr(engine, "search_adzuna_jobs", _noop)
    monkeypatch.setattr(engine, "search_jooble_jobs", _noop)
    monkeypatch.setattr(engine, "search_jsearch_jobs", _noop)

    jobs = engine.search_all_jobs("Python Developer")
    assert any(j["title"] == "D" for j in jobs)
    assert any(j["id"].startswith("indeed-") for j in jobs)


def test_search_all_jobs_tolerates_failing_source(monkeypatch):
    _patch_search(monkeypatch, [
        _FakeSource([], error=RuntimeError("portal down")),
        _FakeSource([_job("2", "Y", "C", "https://a.com/j2", "linkedin")]),
    ])

    jobs = engine.search_all_jobs("Python Developer")
    assert len(jobs) == 6  # 5 portal links + 1 surviving source


def test_registry_has_naukri_and_indeed():
    names = {source.source_name for source in registered_sources()}
    assert "naukri" in names
    assert "indeed" in names


def test_search_plan_jobs_emits_portal_links_once(monkeypatch):
    from jobhunter.domains.search.plan import SearchPlan, SearchQuery

    monkeypatch.setattr(engine, "active_sources", lambda: [])
    monkeypatch.setattr(engine, "search_adzuna_jobs", _noop)
    monkeypatch.setattr(engine, "search_jooble_jobs", _noop)
    monkeypatch.setattr(engine, "search_jsearch_jobs", _noop)

    plan = SearchPlan(base_query="Python Developer", queries=[
        SearchQuery("Python Developer", "primary", "India"),
        SearchQuery("Python Developer", "primary", "Bengaluru"),
    ])
    jobs = engine.search_plan_jobs(plan)
    portal = [j for j in jobs if j.get("is_portal_link")]
    assert len(portal) == 5  # never multiplied across planned queries


def test_search_plan_jobs_dedupes_repeated_listings_across_queries(monkeypatch):
    from jobhunter.domains.search.plan import SearchPlan, SearchQuery

    class _FakeSource:
        async def search(self, query, location="India", max_results=10):
            return [_job("1", "X", "C", "https://a.com/j1?utm_source=x", "indeed", location="Bengaluru")]

    monkeypatch.setattr(engine, "active_sources", lambda: [_FakeSource()])
    monkeypatch.setattr(engine, "search_adzuna_jobs", _noop)
    monkeypatch.setattr(engine, "search_jooble_jobs", _noop)
    monkeypatch.setattr(engine, "search_jsearch_jobs", _noop)

    plan = SearchPlan(base_query="Python Developer", queries=[
        SearchQuery("Python Developer", "primary", "India"),
        SearchQuery("Python Developer", "primary", "Bengaluru"),
    ])
    jobs = engine.search_plan_jobs(plan)
    non_portal = [j for j in jobs if not j.get("is_portal_link")]
    assert len(non_portal) == 1  # same posting deduped across both planned queries
