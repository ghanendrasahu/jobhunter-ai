"""Orchestrated job search across scrapers, third-party APIs, and portal links."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
from typing import Dict, List

from jobhunter.search.api_sources import (
    search_adzuna_jobs,
    search_jsearch_jobs,
    search_jooble_jobs,
)
from jobhunter.search.portals import build_portal_urls
from jobhunter.search.scrapers import scrape_indeed_jobs, scrape_linkedin_jobs, scrape_naukri_jobs

logger = logging.getLogger(__name__)


def _normalise(text: str) -> str:
    """Lowercase and strip punctuation/whitespace for stable fingerprinting."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _fingerprint(job: Dict) -> str:
    """Fingerprint a job by URL when present, else by company + title."""
    url = (job.get("url") or "").strip()
    if url:
        return hashlib.md5(url.encode()).hexdigest()[:12]
    key = f"{_normalise(job.get('company'))}|{_normalise(job.get('title'))}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _dedupe(jobs: List[Dict], all_jobs: List[Dict], seen_keys: set) -> None:
    """Append jobs whose URL/company+title fingerprint has not been seen before.

    Portal-search links always carry a distinct URL, so they are never merged.
    """
    for job in jobs:
        key = _fingerprint(job)
        if key not in seen_keys:
            seen_keys.add(key)
            all_jobs.append(job)


async def search_all_jobs_async(query: str) -> List[Dict]:
    """Search every configured source and return deduplicated results.

    1. Portal search links (always present).
    2. Playwright-scraped listings (best effort).
    3. Third-party API results (only when keys are configured).
    """
    all_jobs: List[Dict] = []
    seen_keys: set = set()

    _dedupe(build_portal_urls(query), all_jobs, seen_keys)

    scraped_results = await asyncio.gather(
        scrape_indeed_jobs(query),
        scrape_linkedin_jobs(query),
        scrape_naukri_jobs(query),
        return_exceptions=True,
    )
    for result in scraped_results:
        if isinstance(result, list) and result:
            _dedupe(result, all_jobs, seen_keys)
            logger.info("Scraped %d jobs", len(result))

    _dedupe(search_adzuna_jobs(query), all_jobs, seen_keys)
    _dedupe(search_jooble_jobs(query), all_jobs, seen_keys)
    _dedupe(search_jsearch_jobs(query), all_jobs, seen_keys)

    logger.info("Total %d jobs for query '%s'", len(all_jobs), query)
    return all_jobs


def search_all_jobs(query: str) -> List[Dict]:
    """Synchronous wrapper around :func:`search_all_jobs_async`.

    Safe to call from the main thread, a worker thread, or the CLI. If called
    from inside an already-running event loop (e.g. a FastAPI async endpoint),
    the coroutine runs in a separate thread so ``asyncio.run`` is never called
    while a loop is active.
    """
    try:
        asyncio.get_running_loop()
        result: List[Dict] = []
        barrier = threading.Event()

        def _runner() -> None:
            try:
                result.extend(asyncio.run(search_all_jobs_async(query)))
            finally:
                barrier.set()

        threading.Thread(target=_runner, daemon=True).start()
        barrier.wait()
        return result
    except RuntimeError:
        return asyncio.run(search_all_jobs_async(query))
