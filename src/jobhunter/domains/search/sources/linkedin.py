"""LinkedIn job source — discovery only, reusing the dedicated JobHunter browser.

LinkedIn blocks logged-out scraping and unauthenticated headless browsers, so
this source never launches a browser of its own. It reuses the *existing*
dedicated JobHunter Chrome window (the same persistent CDP session the apply
agent maintains): when that window is running and logged into LinkedIn, search
results are read from the live session; otherwise the source reports itself
unavailable and returns nothing.

**Discovery-only:** results carry ``discovery_only=True`` and the apply agent
never submits applications for them — LinkedIn stays a browsing/reference
source.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from urllib.parse import quote

from jobhunter.config import get_settings
from jobhunter.domains.jobs import Job
from jobhunter.domains.search.sources.base import JobSource, register

logger = logging.getLogger(__name__)

_CARD_SELECTORS = (
    ".job-card-container",
    ".jobs-search-results__list-item",
    'li[data-occludable-job-id]',
    ".scaffold-layout__list-item",
)

_LOGIN_WALL_SELECTORS = (
    "#auth-wall",
    ".sign-in-form",
    'button[aria-label*="Sign in"]',
)

_LOGGED_IN_SELECTORS = (".global-nav__me", "button[aria-label*='profile']")


@register
class LinkedInSource(JobSource):
    """Read LinkedIn job-search results from the live JobHunter browser session."""

    source_name = "linkedin"
    discovery_only = True

    async def search(self, query: str, location: str = "India", max_results: int = 10) -> list[Job]:
        from jobhunter.automation.browser import BrowserSession  # local import avoids import cycles

        settings = get_settings()
        cdp_url = (settings.browser_cdp_url or f"http://127.0.0.1:{settings.browser_debug_port}").strip()

        if not cdp_url or not BrowserSession._cdp_reachable(cdp_url):
            logger.warning(
                "LinkedIn discovery unavailable: no JobHunter browser session at %s. "
                "Start the dedicated browser window (and log into LinkedIn) first.",
                cdp_url or "(none)",
            )
            return []

        try:
            return await asyncio.to_thread(
                self._scrape_sync, query, location, max_results, cdp_url
            )
        except Exception as exc:
            logger.warning("LinkedIn discovery failed: %s", exc)
            return []

    def _scrape_sync(self, query: str, location: str, max_results: int, cdp_url: str) -> list[Job]:
        """Synchronous CDP scrape (runs on a worker thread; never blocks the loop)."""
        from playwright.sync_api import sync_playwright

        jobs: list[Job] = []
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(cdp_url)
            contexts = [c for c in browser.contexts if c.pages]
            if not contexts:
                logger.warning("LinkedIn discovery: CDP browser exposes no context")
                return []
            context = contexts[0]
            page = context.new_page()
            try:
                search_url = (
                    f"https://www.linkedin.com/jobs/search/"
                    f"?keywords={quote(query)}&location={quote(location)}"
                )
                page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                if self._login_blocked(page):
                    logger.warning("LinkedIn discovery: login wall shown — not logged in")
                    return []

                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

                cards = page.query_selector_all(", ".join(_CARD_SELECTORS))
                for card in cards[:max_results]:
                    job = self._parse_card(card, search_url)
                    if job is not None:
                        jobs.append(job)
                logger.info("LinkedIn discovery: %d jobs for '%s'", len(jobs), query)
            finally:
                try:
                    page.close()
                except Exception:  # pragma: no cover - best effort cleanup
                    pass
        return jobs

    @staticmethod
    def _login_blocked(page) -> bool:
        """True when the search page redirected to a login wall / is not logged in."""
        try:
            for selector in _LOGIN_WALL_SELECTORS:
                if page.query_selector(selector):
                    return True
            for selector in _LOGGED_IN_SELECTORS:
                if page.query_selector(selector):
                    return False
        except Exception:  # pragma: no cover - defensive
            return True
        return True

    @staticmethod
    def _parse_card(card, search_url: str) -> Job | None:
        """Extract a normalized, discovery-only Job from a LinkedIn result card."""
        try:
            title_el = card.query_selector(
                ".job-card-list__title, .job-card-container__link, .job-card__title"
            )
            title = title_el.inner_text() if title_el else "Unknown"

            company_el = card.query_selector(
                ".job-card-container__company-name, .artdeco-entity-lockup__subtitle"
            )
            company = company_el.inner_text() if company_el else "Unknown"

            loc_el = card.query_selector(
                ".job-card-container__metadata-item, .artdeco-entity-lockup__caption"
            )
            loc = loc_el.inner_text() if loc_el else "India"

            url_el = card.query_selector("a[href*='/jobs/view/']") or card.query_selector("a")
            href = url_el.get_attribute("href") if url_el else None
            url = href or search_url
            if not url.startswith("http"):
                url = f"https://www.linkedin.com{url}"

            return Job(
                title=title.strip(),
                company=company.strip(),
                location=loc.strip(),
                description="",
                description_truncated=True,
                url=url,
                source="linkedin",
                source_job_id=hashlib.md5(url.encode()).hexdigest()[:8],
                discovery_only=True,
            )
        except Exception as exc:
            logger.debug("Failed to parse LinkedIn card: %s", exc)
            return None
