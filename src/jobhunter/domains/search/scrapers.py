"""Playwright-based job scrapers for Indian job portals.

All scrapers degrade gracefully: they return ``[]`` if Playwright is missing,
the network fails, or a site changes its markup.

Naukri and Indeed now live in ``jobhunter.domains.search.sources``; this module
keeps the legacy LinkedIn scraper, which is wired into the engine separately
from the registered sources.
"""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)


async def scrape_linkedin_jobs(query: str, location: str = "India", max_results: int = 10) -> list[dict]:
    """Scrape job cards from LinkedIn India."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    jobs = []
    search_url = f"https://www.linkedin.com/jobs/search/?keywords={quote(query)}&location={quote(location)}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            cards = await page.query_selector_all(".job-card-container, .jobs-search-results__list-item")
            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector(".job-card-list__title, .job-card-container__link")
                    title = await title_el.inner_text() if title_el else "Unknown"

                    company_el = await card.query_selector(
                        ".job-card-container__company-name, .artdeco-entity-lockup__subtitle"
                    )
                    company = await company_el.inner_text() if company_el else "Unknown"

                    loc_el = await card.query_selector(
                        ".job-card-container__metadata-item, .artdeco-entity-lockup__caption"
                    )
                    loc = await loc_el.inner_text() if loc_el else location

                    url_el = await card.query_selector("a")
                    url = await url_el.get_attribute("href") if url_el else search_url
                    url = url or search_url
                    if not url.startswith("http"):
                        url = f"https://www.linkedin.com{url}"

                    jobs.append({
                        "id": f"linkedin-scraped-{hashlib.md5((url or '').encode()).hexdigest()[:8]}",
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": loc.strip(),
                        "description": "",
                        "url": url,
                        "salary_min": None,
                        "salary_max": None,
                        "salary_currency": None,
                        "source": "linkedin",
                    })
                except Exception as exc:
                    logger.debug("Failed to parse LinkedIn card: %s", exc)
                    continue

            await browser.close()
            logger.info("Scraped %d jobs from LinkedIn", len(jobs))
    except Exception as exc:
        logger.warning("LinkedIn scraping failed: %s", exc)

    return jobs
