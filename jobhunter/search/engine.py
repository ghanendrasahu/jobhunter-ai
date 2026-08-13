"""Orchestrated job search across scrapers, third-party APIs, and portal links."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Dict, List

from jobhunter.search.api_sources import search_adzuna_jobs, search_jooble_jobs
from jobhunter.search.portals import build_portal_urls
from jobhunter.search.scrapers import scrape_indeed_jobs, scrape_linkedin_jobs, scrape_naukri_jobs

logger = logging.getLogger(__name__)


def _dedupe(jobs: List[Dict], all_jobs: List[Dict], seen_urls: set) -> None:
    """Append jobs whose URL has not been seen before."""
    for job in jobs:
        key = hashlib.md5((job.get("url") or "").encode()).hexdigest()[:12]
        if key not in seen_urls:
            seen_urls.add(key)
            all_jobs.append(job)


async def search_all_jobs_async(query: str) -> List[Dict]:
    """Search every configured source and return deduplicated results.

    1. Portal search links (always present).
    2. Playwright-scraped listings (best effort).
    3. Third-party API results (only when keys are configured).
    """
    all_jobs: List[Dict] = []
    seen_urls: set = set()

    _dedupe(build_portal_urls(query), all_jobs, seen_urls)

    scraped_results = await asyncio.gather(
        scrape_indeed_jobs(query),
        scrape_linkedin_jobs(query),
        scrape_naukri_jobs(query),
        return_exceptions=True,
    )
    for result in scraped_results:
        if isinstance(result, list) and result:
            _dedupe(result, all_jobs, seen_urls)
            logger.info("Scraped %d jobs", len(result))

    _dedupe(search_adzuna_jobs(query), all_jobs, seen_urls)
    _dedupe(search_jooble_jobs(query), all_jobs, seen_urls)

    logger.info("Total %d jobs for query '%s'", len(all_jobs), query)
    return all_jobs


def search_all_jobs(query: str) -> List[Dict]:
    """Synchronous wrapper around :func:`search_all_jobs_async`.

    Safe to call from the main thread, a worker thread, or the CLI.
    """
    return asyncio.run(search_all_jobs_async(query))
