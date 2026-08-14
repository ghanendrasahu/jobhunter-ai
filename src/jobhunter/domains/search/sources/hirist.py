"""Hirist job source — Playwright scraping."""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import quote

from jobhunter.domains.jobs import Job
from jobhunter.domains.search.sources._shared import scrape_cards
from jobhunter.domains.search.sources.base import JobSource, register

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://www.hirist.com/jobs-in-india/{query}-jobs.html"

_CARD_SELECTORS = (
    ".job-listing",
    ".job-card",
    '[class*="job-card"]',
    '[class*="listing"]',
)


@register
class HiristSource(JobSource):
    """Scrape job cards from Hirist."""

    source_name = "hirist"

    async def search(self, query: str, location: str = "India", max_results: int = 10) -> list[Job]:
        slug = quote(query.lower().replace(" ", "-"))
        search_url = _SEARCH_URL.format(query=slug)
        return await scrape_cards(search_url, _CARD_SELECTORS, self._parse_card, max_results)

    @staticmethod
    async def _parse_card(card, search_url: str) -> Job | None:
        try:
            title_el = await card.query_selector(
                '[class*="title"] a, [class*="job-title"], h2 a, a[href*="-jobs-"]'
            )
            title = await title_el.inner_text() if title_el else "Unknown"

            company_el = await card.query_selector(
                '[class*="company"], [class*="cmp-name"], [class*="org"]'
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
                url = f"https://www.hirist.com{url}"

            return Job(
                title=title.strip(),
                company=company.strip(),
                location=location.strip(),
                description="",
                description_truncated=True,
                url=url,
                source="hirist",
                source_job_id=hashlib.md5(url.encode()).hexdigest()[:8],
            )
        except Exception as exc:
            logger.debug("Failed to parse Hirist card: %s", exc)
            return None
