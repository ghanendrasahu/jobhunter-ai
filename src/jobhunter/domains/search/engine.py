"""Orchestrated job search across scrapers, third-party APIs, and portal links."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading

from jobhunter.domains.search.api_sources import (
    search_adzuna_jobs,
    search_jooble_jobs,
    search_jsearch_jobs,
)
from jobhunter.domains.search.portals import build_portal_urls
from jobhunter.domains.search.scrapers import scrape_indeed_jobs, scrape_linkedin_jobs, scrape_naukri_jobs

logger = logging.getLogger(__name__)


def _normalise(text: str) -> str:
    """Lowercase and strip punctuation/whitespace for stable fingerprinting."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _dedupe(jobs: list[dict], all_jobs: list[dict], seen_keys: set) -> None:
    """Append jobs whose URL or company+title+location fingerprint is new.

    Two jobs count as duplicates when they share a URL, or when they share a
    normalised company+title+location (the same role posted under different
    links). Portal-search links always carry a distinct URL, so they are never
    merged with scraped listings.
    """
    for job in jobs:
        url = (job.get("url") or "").strip()
        url_key = hashlib.md5(url.encode()).hexdigest()[:12] if url else ""

        identity = f"{_normalise(str(job.get('company') or ''))}|{_normalise(str(job.get('title') or ''))}|{_normalise(str(job.get('location') or ''))}"
        identity_key = hashlib.md5(identity.encode()).hexdigest()[:12]

        if (url_key and url_key in seen_keys) or identity_key in seen_keys:
            continue
        if url_key:
            seen_keys.add(url_key)
        seen_keys.add(identity_key)
        all_jobs.append(job)


async def search_all_jobs_async(query: str) -> list[dict]:
    """Search every configured source and return deduplicated results.

    1. Portal search links (always present).
    2. Playwright-scraped listings (best effort).
    3. Third-party API results (only when keys are configured).
    """
    all_jobs: list[dict] = []
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


def search_all_jobs(query: str) -> list[dict]:
    """Synchronous wrapper around :func:`search_all_jobs_async`.

    Safe to call from the main thread, a worker thread, or the CLI. If called
    from inside an already-running event loop (e.g. a FastAPI async endpoint),
    the coroutine runs in a separate thread so ``asyncio.run`` is never called
    while a loop is active.
    """
    try:
        asyncio.get_running_loop()
        result: list[dict] = []
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
