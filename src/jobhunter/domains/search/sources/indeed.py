"""Indeed (India) job source.

Adapted from the legacy ``scrape_indeed_jobs`` scraper: same card selectors and
salary parsing, but results are normalized :class:`Job` objects.
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
class IndeedSource(JobSource):
    """Scrape job cards from Indeed India."""

    source_name = "indeed"

    async def search(self, query: str, location: str = "India", max_results: int = 10) -> list[Job]:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning(
                "Playwright not installed. Run: pip install playwright && python -m playwright install chromium"
            )
            return []

        jobs: list[Job] = []
        search_url = f"https://in.indeed.com/jobs?q={quote(query)}&l={quote(location)}"

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                cards = await page.query_selector_all(
                    '[class*="job_seen_beacon"], [class*="tapItem"], .job-card-container'
                )
                for card in cards[:max_results]:
                    job = await self._parse_card(card, search_url, location)
                    if job is not None:
                        jobs.append(job)

                await browser.close()
                logger.info("Scraped %d jobs from Indeed", len(jobs))
        except Exception as exc:
            logger.warning("Indeed scraping failed: %s", exc)

        return jobs

    async def _parse_card(self, card, search_url: str, fallback_location: str) -> Job | None:
        try:
            title_el = await card.query_selector('[class*="jobTitle"], h2 a')
            title = await title_el.inner_text() if title_el else "Unknown"

            company_el = await card.query_selector('[class*="companyName"], [data-testid="company-name"]')
            company = await company_el.inner_text() if company_el else "Unknown"

            location_el = await card.query_selector(
                '[class*="companyLocation"], [data-testid="company-location"]'
            )
            location = await location_el.inner_text() if location_el else fallback_location

            url_el = await card.query_selector('a[href*="rc/clk"]')
            href = await url_el.get_attribute("href") if url_el else None
            url = f"https://in.indeed.com{href}" if href else search_url

            desc_el = await card.query_selector('[class*="job-snippet"], [data-testid="job-snippet"]')
            desc = await desc_el.inner_text() if desc_el else ""

            salary_el = await card.query_selector('[class*="salary-snippet"], [data-testid="salary"]')
            salary_text = await salary_el.inner_text() if salary_el else ""

            salary_min, salary_max = None, None
            if "₹" in salary_text:
                nums = re.findall(r"[\d,]+", salary_text)
                if len(nums) >= 2:
                    salary_min = int(nums[0].replace(",", ""))
                    salary_max = int(nums[1].replace(",", ""))

            return Job(
                title=title.strip(),
                company=company.strip(),
                location=location.strip(),
                description=desc.strip(),
                description_truncated=True,
                url=url,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_currency="INR",
                source=self.source_name,
                source_job_id=hashlib.md5(url.encode()).hexdigest()[:8],
            )
        except Exception as exc:
            logger.debug("Failed to parse Indeed card: %s", exc)
            return None
