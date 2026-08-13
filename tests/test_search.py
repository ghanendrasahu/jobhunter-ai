"""Tests for portal links and the orchestrated job search engine."""

import jobhunter.domains.search.engine as engine
from jobhunter.domains.search.portals import build_portal_urls


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


async def _fake_indeed(_query):
    return [{"id": "indeed-1", "title": "X", "company": "C", "url": "https://a.com/j1", "source": "indeed"}]


async def _fake_linkedin(_query):
    return [{"id": "linkedin-1", "title": "Y", "company": "C", "url": "https://a.com/j2", "source": "linkedin"}]


async def _fake_naukri(_query):
    return []  # duplicate of indeed url -> should be deduped
    # (kept empty: a real duplicate test is below)


async def _fake_naukri_dup(_query):
    return [{"id": "naukri-1", "title": "Z", "company": "C", "url": "https://a.com/j1", "source": "naukri"}]


def test_search_all_jobs_returns_portals_and_scraped(monkeypatch):
    monkeypatch.setattr(engine, "scrape_indeed_jobs", _fake_indeed)
    monkeypatch.setattr(engine, "scrape_linkedin_jobs", _fake_linkedin)
    monkeypatch.setattr(engine, "scrape_naukri_jobs", _fake_naukri)
    monkeypatch.setattr(engine, "search_adzuna_jobs", lambda *a, **k: [])
    monkeypatch.setattr(engine, "search_jooble_jobs", lambda *a, **k: [])
    monkeypatch.setattr(engine, "search_jsearch_jobs", lambda *a, **k: [])

    jobs = engine.search_all_jobs("Python Developer")
    sources = {j["source"] for j in jobs}
    assert "indeed" in sources
    assert "linkedin" in sources
    # 5 portal links + 2 scraped = 7
    assert len(jobs) == 7


def test_search_all_jobs_deduplicates_urls(monkeypatch):
    monkeypatch.setattr(engine, "scrape_indeed_jobs", _fake_indeed)
    monkeypatch.setattr(engine, "scrape_linkedin_jobs", _fake_linkedin)
    monkeypatch.setattr(engine, "scrape_naukri_jobs", _fake_naukri_dup)
    monkeypatch.setattr(engine, "search_adzuna_jobs", lambda *a, **k: [])
    monkeypatch.setattr(engine, "search_jooble_jobs", lambda *a, **k: [])
    monkeypatch.setattr(engine, "search_jsearch_jobs", lambda *a, **k: [])

    jobs = engine.search_all_jobs("Python Developer")
    urls = [j["url"] for j in jobs if not j.get("is_portal_link")]
    assert len(urls) == len(set(urls))  # no duplicate scraped urls


def _fake_jsearch_same_job(_query):
    # Same company + title as the LinkedIn job, but a different URL.
    return [{"id": "jsearch-1", "title": "Y", "company": "C", "url": "https://other.com/j2", "source": "jsearch"}]


def test_search_all_jobs_deduplicates_company_title(monkeypatch):
    monkeypatch.setattr(engine, "scrape_indeed_jobs", _fake_indeed)
    monkeypatch.setattr(engine, "scrape_linkedin_jobs", _fake_linkedin)
    monkeypatch.setattr(engine, "scrape_naukri_jobs", _fake_naukri)
    monkeypatch.setattr(engine, "search_adzuna_jobs", lambda *a, **k: [])
    monkeypatch.setattr(engine, "search_jooble_jobs", lambda *a, **k: [])
    monkeypatch.setattr(engine, "search_jsearch_jobs", _fake_jsearch_same_job)

    jobs = engine.search_all_jobs("Python Developer")
    # 5 portal links + 2 scraped (LinkedIn "Y@C" dedupes the jsearch "Y@C").
    assert len(jobs) == 7
    non_portal = [j for j in jobs if not j.get("is_portal_link")]
    assert len(non_portal) == 2
