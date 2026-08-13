"""Playwright-based job scrapers for Indian job portals.

All scrapers degrade gracefully: they return ``[]`` if Playwright is missing,
the network fails, or a site changes its markup.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Dict, List
from urllib.parse import quote

logger = logging.getLogger(__name__)


async def scrape_indeed_jobs(query: str, location: str = "India", max_results: int = 10) -> List[Dict]:
    """Scrape job cards from Indeed India."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        return []

    jobs = []
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
                try:
                    title_el = await card.query_selector('[class*="jobTitle"], h2 a')
                    title = await title_el.inner_text() if title_el else "Unknown"

                    company_el = await card.query_selector('[class*="companyName"], [data-testid="company-name"]')
                    company = await company_el.inner_text() if company_el else "Unknown"

                    location_el = await card.query_selector('[class*="companyLocation"], [data-testid="company-location"]')
                    loc = await location_el.inner_text() if location_el else location

                    url_el = await card.query_selector('a[href*="rc/clk"]')
                    url = f"https://in.indeed.com{await url_el.get_attribute('href')}" if url_el else search_url

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

                    jobs.append({
                        "id": f"indeed-scraped-{hashlib.md5(url.encode()).hexdigest()[:8]}",
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": loc.strip(),
                        "description": desc.strip(),
                        "url": url,
                        "salary_min": salary_min,
                        "salary_max": salary_max,
                        "salary_currency": "INR",
                        "source": "indeed",
                    })
                except Exception as exc:
                    logger.debug("Failed to parse Indeed card: %s", exc)
                    continue

            await browser.close()
            logger.info("Scraped %d jobs from Indeed", len(jobs))
    except Exception as exc:
        logger.warning("Indeed scraping failed: %s", exc)

    return jobs


async def scrape_linkedin_jobs(query: str, location: str = "India", max_results: int = 10) -> List[Dict]:
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
                    if url and not url.startswith("http"):
                        url = f"https://www.linkedin.com{url}"

                    jobs.append({
                        "id": f"linkedin-scraped-{hashlib.md5(url.encode()).hexdigest()[:8]}",
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


async def scrape_naukri_jobs(query: str, max_results: int = 10) -> List[Dict]:
    """Scrape job cards from Naukri.com."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    jobs = []
    search_url = f"https://www.naukri.com/{quote(query)}-jobs-in-india"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            cards = await page.query_selector_all(".jobTuple, .list, .srp-jobtuple-wrapper")
            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector('a.title, [class*="title"]')
                    title = await title_el.inner_text() if title_el else "Unknown"

                    company_el = await card.query_selector('a.subTitle, [class*="subTitle"]')
                    company = await company_el.inner_text() if company_el else "Unknown"

                    loc_el = await card.query_selector('[class*="location"], li[class*="loc"]')
                    loc = await loc_el.inner_text() if loc_el else "India"

                    desc_el = await card.query_selector('[class*="desc"], [class*="job-description"]')
                    desc = await desc_el.inner_text() if desc_el else ""

                    url_el = await card.query_selector("a.title")
                    url = await url_el.get_attribute("href") if url_el else search_url
                    if url and not url.startswith("http"):
                        url = f"https://www.naukri.com{url}"

                    salary_el = await card.query_selector('[class*="salary"], li[class*="salary"]')
                    salary_text = await salary_el.inner_text() if salary_el else ""

                    salary_min, salary_max = None, None
                    if "₹" in salary_text or "L" in salary_text:
                        nums = re.findall(r"[\d.]+", salary_text)
                        if len(nums) >= 2:
                            salary_min = int(float(nums[0]) * 100000)
                            salary_max = int(float(nums[1]) * 100000)

                    jobs.append({
                        "id": f"naukri-scraped-{hashlib.md5(url.encode()).hexdigest()[:8]}",
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": loc.strip(),
                        "description": desc.strip(),
                        "url": url,
                        "salary_min": salary_min,
                        "salary_max": salary_max,
                        "salary_currency": "INR" if salary_min else None,
                        "source": "naukri",
                    })
                except Exception as exc:
                    logger.debug("Failed to parse Naukri card: %s", exc)
                    continue

            await browser.close()
            logger.info("Scraped %d jobs from Naukri", len(jobs))
    except Exception as exc:
        logger.warning("Naukri scraping failed: %s", exc)

    return jobs
