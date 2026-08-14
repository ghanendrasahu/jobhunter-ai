"""JobSource interface and registry.

A :class:`JobSource` discovers jobs for a query (Playwright scraping, HTTP
fetch, etc.) and returns them as normalized :class:`Job` objects. Sources
self-register via :func:`register` (called from ``sources/__init__.py``), and
the active set is returned by :func:`active_sources`.
"""

from __future__ import annotations

import abc

from jobhunter.domains.jobs import Job

SOURCES: dict[str, type[JobSource]] = {}


def register(cls: type[JobSource]) -> type[JobSource]:
    """Register a JobSource subclass under ``cls.source_name``."""
    SOURCES[cls.source_name] = cls
    return cls


def active_sources() -> list[JobSource]:
    """Return one instance of every registered source."""
    return [cls() for cls in SOURCES.values()]


def get_source(name: str) -> JobSource | None:
    """Return a source instance by name, or ``None`` if not registered."""
    cls = SOURCES.get(name)
    return cls() if cls is not None else None


class JobSource(abc.ABC):
    """Interface every job source implements."""

    source_name: str = ""

    @abc.abstractmethod
    async def search(self, query: str, location: str = "India", max_results: int = 10) -> list[Job]:
        """Discover up to ``max_results`` jobs for ``query``.

        Must never raise: errors should be logged and ``[]`` returned so one
        failing source does not break the whole search.
        """
