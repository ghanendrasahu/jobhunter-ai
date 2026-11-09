"""Tests for the legacy LinkedIn scraper (playwright fully mocked)."""

import asyncio
import sys

from jobhunter.domains.search import scrapers


class _El:
    def __init__(self, text="", href=None):
        self._text = text
        self._href = href

    async def inner_text(self):
        return self._text

    async def get_attribute(self, name):
        return self._href


class _Card:
    def __init__(self, title, company, loc):
        self._title = title
        self._company = company
        self._loc = loc

    async def query_selector(self, selector):
        if "company-name" in selector or "subtitle" in selector:
            return _El(self._company)
        if "metadata" in selector or "caption" in selector:
            return _El(self._loc)
        if "title" in selector or "container__link" in selector:
            return _El(self._title)
        if selector.strip() == "a" or "href" in selector:
            return _El(href=f"https://www.linkedin.com/jobs/view/{abs(hash(self._title))}")
        return None


class _Page:
    def __init__(self, cards):
        self._cards = cards

    async def goto(self, url, **kwargs):
        return None

    async def wait_for_timeout(self, ms):
        return None

    async def evaluate(self, script):
        return None

    async def query_selector_all(self, selector):
        return list(self._cards)


class _Browser:
    def __init__(self, page):
        self._page = page
        self.closed = False

    async def new_page(self):
        return self._page

    async def close(self):
        self.closed = True


class _Chromium:
    def __init__(self, browser):
        self._browser = browser

    async def launch(self, **kwargs):
        return self._browser


class _PW:
    def __init__(self, browser):
        self.chromium = _Chromium(browser)


class _Ctx:
    def __init__(self, browser):
        self._browser = browser

    async def __aenter__(self):
        return _PW(self._browser)

    async def __aexit__(self, *args):
        return False


def _install_fake_playwright(monkeypatch, browser):
    import types

    fake_module = types.SimpleNamespace(async_playwright=lambda: _Ctx(browser))
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_module)


def test_scrape_linkedin_jobs_parses_cards(monkeypatch):
    cards = [
        _Card("Python Developer", "Acme Corp", "Bengaluru"),
        _Card("Data Analyst", "Corp Ltd", "Mumbai"),
    ]
    browser = _Browser(_Page(cards))
    _install_fake_playwright(monkeypatch, browser)

    jobs = asyncio.run(scrapers.scrape_linkedin_jobs("Python Developer", location="India", max_results=10))
    assert len(jobs) == 2
    first = jobs[0]
    assert first["title"] == "Python Developer"
    assert first["company"] == "Acme Corp"
    assert first["source"] == "linkedin"
    assert first["discovery_only"] is True
    assert first["fingerprint"]
    assert "jobs/view" in first["url"]


def test_scrape_linkedin_jobs_missing_playwright_returns_empty(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    jobs = asyncio.run(scrapers.scrape_linkedin_jobs("Python"))
    assert jobs == []


def test_scrape_linkedin_jobs_launch_failure_returns_empty(monkeypatch):
    import types

    class _ExplodingChromium:
        async def launch(self, **kwargs):
            raise RuntimeError("chromium failed to start")

    class _ExplodingPW:
        chromium = _ExplodingChromium()

    class _ExplodingCtx:
        async def __aenter__(self):
            return _ExplodingPW()

        async def __aexit__(self, *args):
            return False

    fake_module = types.SimpleNamespace(async_playwright=lambda: _ExplodingCtx())
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_module)
    jobs = asyncio.run(scrapers.scrape_linkedin_jobs("Python"))
    assert jobs == []
