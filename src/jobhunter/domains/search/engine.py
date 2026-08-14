"""Orchestrated job search across registry sources, third-party APIs, and portal links.

The engine exposes two entry points:

- :func:`search_all_jobs` — a single-query search (portal links + every
  registered source + optional API sources).
- :func:`search_plan_jobs` — a :class:`~jobhunter.domains.search.plan.SearchPlan`
  search: portal links from the base query plus every ``(query, location)`` in
  the plan, deduplicated across all queries and sources (PHASE 2).

Both are synchronous wrappers around async internals, safe from the main
thread, worker threads, and already-running event loops.
"""

from __future__ import annotations

import asyncio
import logging
import threading

import jobhunter.domains.search.sources as _sources  # noqa: F401  # registers bundled sources
from jobhunter.config import get_settings
from jobhunter.domains.jobs import Job, dedupe_jobs
from jobhunter.domains.search.api_sources import (
    search_adzuna_jobs,
    search_jooble_jobs,
    search_jsearch_jobs,
)
from jobhunter.domains.search.description import ensure_full_descriptions
from jobhunter.domains.search.portals import build_portal_urls
from jobhunter.domains.search.sources.base import active_sources

logger = logging.getLogger(__name__)


def _wrap(jobs: list[Job]) -> list[dict]:
    """Convert normalized jobs back to the plain dicts the app consumes."""
    return [job.to_dict() for job in jobs]


async def _search_sources_async(query: str, location: str = "India") -> list[Job]:
    """Search every registered source plus the optional API sources for one query.

    Each source may fail independently; failures are logged and never break the
    overall search. Returns raw (un-deduplicated) :class:`Job` objects.
    """
    all_jobs: list[Job] = []
    sources = active_sources()
    results = await asyncio.gather(
        *[source.search(query, location=location) for source in sources],
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, list) and result:
            if isinstance(result[0], Job):
                all_jobs.extend(result)
            else:
                all_jobs.extend(Job.from_dict(job) for job in result)
            logger.info("Scraped %d jobs", len(result))

    for api_fn in (search_adzuna_jobs, search_jooble_jobs, search_jsearch_jobs):
        try:
            all_jobs.extend(Job.from_dict(job) for job in api_fn(query))
        except Exception as exc:
            logger.warning("API source %s failed: %s", getattr(api_fn, "__name__", api_fn), exc)
    return all_jobs


def _refresh_descriptions(jobs: list[Job]) -> None:
    """Best-effort full-description refresh, gated by settings."""
    settings = get_settings()
    if not settings.fetch_full_descriptions:
        return
    try:
        ensure_full_descriptions(jobs, max_fetches=settings.fetch_full_description_max)
    except Exception as exc:
        logger.warning("Full-description refresh failed: %s", exc)


async def search_all_jobs_async(
    query: str,
    location: str = "India",
    include_portals: bool = True,
) -> list[dict]:
    """Search every configured source for ``query`` and return deduplicated results.

    1. Portal search links (when ``include_portals``).
    2. Every registered :class:`JobSource` (best effort — each source may fail
       independently).
    3. Third-party API results (only when keys are configured).
    4. Optionally refresh full descriptions for snippets that are too thin.
    """
    all_jobs: list[Job] = (
        [Job.from_dict(job) for job in build_portal_urls(query)] if include_portals else []
    )
    all_jobs.extend(await _search_sources_async(query, location=location))
    all_jobs = dedupe_jobs(all_jobs)
    _refresh_descriptions(all_jobs)
    logger.info("Total %d jobs for query '%s'", len(all_jobs), query)
    return _wrap(all_jobs)


async def search_plan_jobs_async(plan) -> list[dict]:
    """Run every ``(query, location)`` in ``plan`` and deduplicate the combined results.

    Portal links are emitted once from the plan's base query so repeated queries
    never multiply search-page links.
    """
    all_jobs: list[Job] = [Job.from_dict(job) for job in build_portal_urls(plan.base_query)]

    for search in plan.deduplicated_queries:
        all_jobs.extend(await _search_sources_async(search.query, location=search.location))

    all_jobs = dedupe_jobs(all_jobs)
    _refresh_descriptions(all_jobs)
    logger.info(
        "Total %d jobs across %d planned queries for '%s'",
        len(all_jobs), plan.unique_queries, plan.base_query,
    )
    return _wrap(all_jobs)


def _run_in_loop(coro) -> list[dict]:
    """Run a coroutine to completion, even when an event loop is already active.

    If called from inside an already-running event loop (e.g. a FastAPI async
    endpoint), the coroutine runs in a separate thread so ``asyncio.run`` is
    never called while a loop is active.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[dict] = []
    barrier = threading.Event()

    def _runner() -> None:
        try:
            result.extend(asyncio.run(coro))
        finally:
            barrier.set()

    threading.Thread(target=_runner, daemon=True).start()
    barrier.wait()
    return result


def search_all_jobs(query: str, location: str = "India") -> list[dict]:
    """Synchronous wrapper around :func:`search_all_jobs_async`."""
    return _run_in_loop(search_all_jobs_async(query, location=location))


def search_plan_jobs(plan) -> list[dict]:
    """Synchronous wrapper around :func:`search_plan_jobs_async`."""
    return _run_in_loop(search_plan_jobs_async(plan))
