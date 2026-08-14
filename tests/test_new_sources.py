"""Tests for PHASE 1B sources: parsing fixtures, failure isolation, LinkedIn CDP reuse."""

import asyncio
import builtins

import jobhunter.automation.browser as browser_mod
import jobhunter.domains.search.sources._shared as shared
from jobhunter.domains.jobs import Job
from jobhunter.domains.search.sources.base import active_sources
from jobhunter.domains.search.sources.cutshort import CutshortSource
from jobhunter.domains.search.sources.foundit import FounditSource
from jobhunter.domains.search.sources.google_jobs import GoogleJobsSource, extract_google_jobs
from jobhunter.domains.search.sources.hirist import HiristSource
from jobhunter.domains.search.sources.internshala import InternshalaSource, parse_internshala
from jobhunter.domains.search.sources.linkedin import LinkedInSource


def test_registry_includes_all_sources():
    names = {source.source_name for source in active_sources()}
    assert {
        "naukri", "indeed", "linkedin", "google_jobs",
        "foundit", "internshala", "cutshort", "hirist",
    } <= names


# --------------------------------------------------------------------- Google Jobs


JSON_LD_HTML = """<html><body>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting",
"title":"ML Engineer","hiringOrganization":{"name":"Acme"},
"jobLocation":{"@type":"Place","address":{"@type":"PostalAddress",
"addressLocality":"Bengaluru","addressRegion":"KA"}},
"url":"https://acme.com/jobs/ml","description":"Build ML models","datePosted":"2026-08-01"}</script>
</body></html>"""


def test_google_jobs_extracts_jsonld():
    jobs = extract_google_jobs(JSON_LD_HTML)
    assert len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "ML Engineer"
    assert job["company"] == "Acme"
    assert job["location"] == "Bengaluru, KA"
    assert job["url"] == "https://acme.com/jobs/ml"
    assert job["description"] == "Build ML models"


EMBEDDED_HTML = """<html><body><script>
window.google.hist = {"data":[{"title":"Python Developer","company":"TechCorp",
"location":"Remote","url":"https://t.co/job/1"}]};
</script></body></html>"""


def test_google_jobs_extracts_embedded_json():
    jobs = extract_google_jobs(EMBEDDED_HTML)
    match = next((j for j in jobs if j["title"] == "Python Developer"), None)
    assert match is not None
    assert match["company"] == "TechCorp"
    assert match["location"] == "Remote"
    assert match["url"] == "https://t.co/job/1"


ANCHOR_HTML = """<html><body>
<div class="card"><a href="/jobs/view/123">Backend Developer</a></div>
<div class="card"><a href="/jobs/view/456">DevOps Engineer</a></div>
</body></html>"""


def test_google_jobs_extracts_anchors_fallback():
    jobs = extract_google_jobs(ANCHOR_HTML)
    titles = {job["title"] for job in jobs}
    assert "Backend Developer" in titles
    assert "DevOps Engineer" in titles


def test_google_jobs_empty_html():
    assert extract_google_jobs("") == []


def test_google_jobs_returns_empty_on_network_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    import jobhunter.domains.search.sources.google_jobs as module

    monkeypatch.setattr(module.requests, "get", boom)
    assert asyncio.run(GoogleJobsSource().search("Python Developer")) == []


# ------------------------------------------------------------------- Internshala


INTERNSHALA_HTML = """<html><body>
<div class="individual_internship">
  <div class="heading_4_5"><a href="/internships/data-analytics-internship-in-bengaluru-at-acme">Data Analytics Intern</a></div>
  <span class="company_name">Acme Analytics</span>
  <div class="locations">Bengaluru</div>
</div>
<div class="individual_internship">
  <div class="heading_4_5"><a href="/internships/python-internship-in-remote-at-corp">Python Intern</a></div>
  <span class="company_name">Corp</span>
  <div class="locations">Remote</div>
</div>
</body></html>"""


def test_internshala_parses_cards():
    cards = parse_internshala(INTERNSHALA_HTML)
    assert len(cards) == 2
    first = cards[0]
    assert first["title"] == "Data Analytics Intern"
    assert first["company"] == "Acme Analytics"
    assert first["location"] == "Bengaluru"
    assert first["url"].startswith("https://internshala.com")
    assert cards[1]["location"] == "Remote"


def test_internshala_empty_html():
    assert parse_internshala("") == []


def test_internshala_returns_empty_on_network_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("network down")

    import jobhunter.domains.search.sources.internshala as module

    monkeypatch.setattr(module.requests, "get", boom)
    assert asyncio.run(InternshalaSource().search("python")) == []


# -------------------------------------------------------------- Playwright sources


def test_playwright_sources_return_empty_when_scrape_fails(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("portal down")

    monkeypatch.setattr(shared, "scrape_cards", boom)
    for source in (FounditSource(), CutshortSource(), HiristSource()):
        assert asyncio.run(source.search("Python Developer")) == []


def test_scrape_cards_returns_empty_when_playwright_missing(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright.async_api":
            raise ImportError("no playwright")
        return real_import(name, *args, **kwargs)

    async def parse_card(card, search_url):
        return None

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert asyncio.run(shared.scrape_cards("https://x.com/search", (".card",), parse_card)) == []


def test_playwright_sources_parse_card_to_job():
    class _Element:
        def __init__(self, text=None, href=None):
            self._text = text
            self._href = href

        async def inner_text(self):
            return self._text

        async def get_attribute(self, name):
            return self._href

    class _Card:
        def __init__(self, selector_map, anchor=None):
            self._map = selector_map
            self._anchor = anchor

        async def query_selector(self, selector):
            if selector == "a" or selector == "a[href*='/job/']":
                return self._anchor
            return self._map.get(selector)

    card = _Card({
        '[class*="jobTitle"], [class*="title"] a, a[data-bind*="title"]': _Element(text="Data Analyst"),
        '[class*="company"], [class*="cmp"] a, [class*="companyName"]': _Element(text="Acme"),
        '[class*="location"], [class*="loc"]': _Element(text="Bengaluru"),
    }, anchor=_Element(href="/job/xyz"))
    job = asyncio.run(FounditSource._parse_card(card, "https://x.com/search"))
    assert job is not None
    assert job.title == "Data Analyst"
    assert job.company == "Acme"
    assert job.location == "Bengaluru"
    assert job.url.startswith("https://www.foundit.in")


# ------------------------------------------------------------------------ LinkedIn


def test_linkedin_returns_empty_without_session(monkeypatch):
    state = {"scraped": False}
    monkeypatch.setattr(
        browser_mod.BrowserSession, "_cdp_reachable",
        staticmethod(lambda url, timeout=3.0: False),
    )

    async def fake_scrape(self, *args, **kwargs):
        state["scraped"] = True
        return []

    monkeypatch.setattr(LinkedInSource, "_scrape_sync", fake_scrape)
    assert asyncio.run(LinkedInSource().search("Python Developer")) == []
    assert state["scraped"] is False


def test_linkedin_reuses_session_when_reachable(monkeypatch):
    jobs = [Job(title="T", company="C", location="India", url="https://x.com/j", source="linkedin")]
    monkeypatch.setattr(
        browser_mod.BrowserSession, "_cdp_reachable",
        staticmethod(lambda url, timeout=3.0: True),
    )

    def fake_scrape(self, *args, **kwargs):
        return jobs

    monkeypatch.setattr(LinkedInSource, "_scrape_sync", fake_scrape)
    result = asyncio.run(LinkedInSource().search("Python Developer"))
    assert result == jobs


def test_linkedin_returns_empty_on_scrape_error(monkeypatch):
    def boom(self, *args, **kwargs):
        raise RuntimeError("cdp broken")

    monkeypatch.setattr(LinkedInSource, "_scrape_sync", boom)
    monkeypatch.setattr(
        browser_mod.BrowserSession, "_cdp_reachable",
        staticmethod(lambda url, timeout=3.0: True),
    )
    assert asyncio.run(LinkedInSource().search("Python Developer")) == []


def test_linkedin_parse_card_is_discovery_only():
    class _Element:
        def __init__(self, text=None, href=None):
            self._text = text
            self._href = href

        def inner_text(self):
            return self._text

        def get_attribute(self, name):
            return self._href

    class _Card:
        def __init__(self):
            self._map = {
                ".job-card-list__title, .job-card-container__link, .job-card__title": _Element(text="ML Engineer"),
                ".job-card-container__company-name, .artdeco-entity-lockup__subtitle": _Element(text="Acme"),
                ".job-card-container__metadata-item, .artdeco-entity-lockup__caption": _Element(text="Bengaluru"),
            }
            self._anchor = _Element(href="/jobs/view/123")

        def query_selector(self, selector):
            if selector == "a[href*='/jobs/view/']" or selector == "a":
                return self._anchor
            return self._map.get(selector)

    job = LinkedInSource._parse_card(_Card(), "https://www.linkedin.com/jobs/search/")
    assert job is not None
    assert job.title == "ML Engineer"
    assert job.company == "Acme"
    assert job.discovery_only is True
    assert job.url == "https://www.linkedin.com/jobs/view/123"
