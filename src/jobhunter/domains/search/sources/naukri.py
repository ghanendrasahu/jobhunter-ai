"""Naukri.com job source.

Adapted from the legacy ``scrape_naukri_jobs`` scraper: same card selectors and
LPA-salary parsing, but results are normalized :class:`Job` objects.
"""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import quote

from jobhunter.domains.jobs import Job
from jobhunter.domains.search.sources.base import JobSource, register

logger = logging.getLogger(__name__)


@register
class NaukriSource(JobSource):
    """Scrape job cards from Naukri.com."""

    source_name = "naukri"

    async def search(self, query: str, location: str = "India", max_results: int = 10) -> list[Job]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return []

        jobs: list[Job] = []
        search_url = f"https://www.naukri.com/{quote(query)}-jobs-in-india"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                cards = await page.query_selector_all(".jobTuple, .list, .srp-jobtuple-wrapper")
                for card in cards[:max_results]:
                    job = await self._parse_card(card, search_url)
                    if job is not None:
                        jobs.append(job)

                await browser.close()
                logger.info("Scraped %d jobs from Naukri", len(jobs))
        except Exception as exc:
            logger.warning("Naukri scraping failed: %s", exc)

        return jobs

    async def _parse_card(self, card, search_url: str) -> Job | None:
        try:
            title_el = await card.query_selector('a.title, [class*="title"]')
            title = await title_el.inner_text() if title_el else "Unknown"

            company_el = await card.query_selector('a.subTitle, [class*="subTitle"]')
            company = await company_el.inner_text() if company_el else "Unknown"

            loc_el = await card.query_selector('[class*="location"], li[class*="loc"]')
            location = await loc_el.inner_text() if loc_el else "India"

            desc_el = await card.query_selector('[class*="desc"], [class*="job-description"]')
            desc = await desc_el.inner_text() if desc_el else ""

            url_el = await card.query_selector("a.title")
            url = await url_el.get_attribute("href") if url_el else search_url
            url = url or search_url
            if not url.startswith("http"):
                url = f"https://www.naukri.com{url}"

            salary_el = await card.query_selector('[class*="salary"], li[class*="salary"]')
            salary_text = await salary_el.inner_text() if salary_el else ""

            salary_min, salary_max = None, None
            if "₹" in salary_text or "L" in salary_text:
                nums = re.findall(r"[\d.]+", salary_text)
                if len(nums) >= 2:
                    salary_min = int(float(nums[0]) * 100000)
                    salary_max = int(float(nums[1]) * 100000)

            return Job(
                title=title.strip(),
                company=company.strip(),
                location=location.strip(),
                description=desc.strip(),
                description_truncated=True,
                url=url,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency="INR" if salary_min else None,
                source=self.source_name,
                source_job_id=hashlib.md5(url.encode()).hexdigest()[:8],
            )
        except Exception as exc:
            logger.debug("Failed to parse Naukri card: %s", exc)
            return None
