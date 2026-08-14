"""Shared Playwright scraping helper for registered job sources.

The Foundit, Cutshort, and Hirist sources all follow the same shape as the
existing Indeed/Naukri scrapers: launch a headless browser, walk the result
cards, parse each into a normalized :class:`Job`, degrade to ``[]`` on any
failure. This module factors that shared flow so the per-source modules only
supply their URL and card selectors.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from jobhunter.domains.jobs import Job

logger = logging.getLogger(__name__)

ParseCard = Callable[[object, str], Awaitable[Job | None]]


async def scrape_cards(
    search_url: str,
    card_selectors: tuple[str, ...],
    parse_card: ParseCard,
    max_results: int = 10,
) -> list[Job]:
    """Scrape up to ``max_results`` cards from a Playwright page and parse them.

    Returns ``[]`` when Playwright is missing, the network fails, or the site
    changes its markup — a failing source never raises.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        return []

    jobs: list[Job] = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            cards = await page.query_selector_all(", ".join(card_selectors))
            for card in cards[:max_results]:
                job = await parse_card(card, search_url)
                if job is not None:
                    jobs.append(job)
            await browser.close()
    except Exception as exc:
        logger.warning("Scrape failed for %s: %s", search_url, exc)
    logger.info("Scraped %d jobs from %s", len(jobs), search_url)
    return jobs
