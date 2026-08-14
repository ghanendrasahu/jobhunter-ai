"""Foundit (formerly Monster India) job source — Playwright scraping."""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import quote

from jobhunter.domains.jobs import Job
from jobhunter.domains.search.sources._shared import scrape_cards
from jobhunter.domains.search.sources.base import JobSource, register

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.foundit.in/search/{query}-jobs-in-india"

_CARD_SELECTORS = (
    ".jobsearcher-result",
    ".search-result",
    '[class*="job-card"]',
    '[data-bind*="job"]',
)


@register
class FounditSource(JobSource):
    """Scrape job cards from Foundit (India)."""

    source_name = "foundit"

    async def search(self, query: str, location: str = "India", max_results: int = 10) -> list[Job]:
        search_url = _SEARCH_URL.format(query=quote(query))
        return await scrape_cards(search_url, _CARD_SELECTORS, self._parse_card, max_results)

    @staticmethod
    async def _parse_card(card, search_url: str) -> Job | None:
        try:
            title_el = await card.query_selector(
                '[class*="jobTitle"], [class*="title"] a, a[data-bind*="title"]'
            )
            title = await title_el.inner_text() if title_el else "Unknown"

            company_el = await card.query_selector(
                '[class*="company"], [class*="cmp"] a, [class*="companyName"]'
            )
            company = await company_el.inner_text() if company_el else "Unknown"

            loc_el = await card.query_selector(
                '[class*="location"], [class*="loc"]'
            )
            location = await loc_el.inner_text() if loc_el else "India"

            url_el = await card.query_selector("a")
            href = await url_el.get_attribute("href") if url_el else None
            url = href or search_url
            if url and not url.startswith("http"):
                url = f"https://www.foundit.in{url}"

            return Job(
                title=title.strip(),
                company=company.strip(),
                location=location.strip(),
                description="",
                description_truncated=True,
                url=url,
                source="foundit",
                source_job_id=hashlib.md5(url.encode()).hexdigest()[:8],
            )
        except Exception as exc:
            logger.debug("Failed to parse Foundit card: %s", exc)
            return None
