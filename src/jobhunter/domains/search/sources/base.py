"""JobSource interface and registry.

A :class:`JobSource` discovers jobs for a query (Playwright scraping, HTTP
fetch, etc.) and returns them as normalized :class:`Job` objects. Sources
self-register via :func:`register` (called from ``sources/__init__.py``), and
the active set is returned by :func:`active_sources`.
"""

from __future__ import annotations

import abc
import logging
import os
import sys
from functools import lru_cache
from pathlib import Path

from jobhunter.domains.jobs import Job

logger = logging.getLogger(__name__)

SOURCES: dict[str, type[JobSource]] = {}
_LOGGED_SKIP = False


def register(cls: type[JobSource]) -> type[JobSource]:
    """Register a JobSource subclass under ``cls.source_name``."""
    SOURCES[cls.source_name] = cls
    return cls


# Playwright installs its browsers into a per-user cache. These globs cover the
# full and headless-shell builds on Linux, Windows, and macOS.
_BROWSER_GLOBS = (
    "chromium-*/chrome-linux/chrome",
    "chromium-*/chrome-win/chrome.exe",
    "chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium",
    "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
    "chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe",
    "chromium_headless_shell-*/chrome-headless-shell-mac*/chrome-headless-shell",
)


def _playwright_cache_dir() -> Path:
    """Return the directory Playwright resolves browser builds from."""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if override and override != "0":
        return Path(override)
    if override == "0":
        from importlib.util import find_spec

        spec = find_spec("playwright")
        if spec and spec.origin:
            return Path(spec.origin).parent / "driver" / "package" / ".local-browsers"
        return Path("__missing__")
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ms-playwright"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "ms-playwright"


@lru_cache(maxsize=1)
def browser_available() -> bool:
    """Return True when a Playwright Chromium build is installed.

    This is a filesystem check, not a driver launch: starting Playwright just to
    test availability would itself consume the memory the check protects.
    """
    root = _playwright_cache_dir()
    if not root.is_dir():
        return False
    return any(next(root.glob(pattern), None) is not None for pattern in _BROWSER_GLOBS)


def active_sources() -> list[JobSource]:
    """Return one instance of every usable source.

    Browser-backed sources are skipped when Chromium is not installed. On a
    memory-constrained host their launches would fail anyway, but each failed
    launch still starts a Node driver; several can exceed the container limit.
    """
    instances = [cls() for cls in SOURCES.values()]
    if browser_available():
        return instances

    skipped = sorted(source.source_name for source in instances if source.requires_browser)
    global _LOGGED_SKIP
    if skipped and not _LOGGED_SKIP:
        logger.info(
            "Skipping browser sources (Chromium not installed): %s", ", ".join(skipped)
        )
        _LOGGED_SKIP = True
    return [source for source in instances if not source.requires_browser]


def get_source(name: str) -> JobSource | None:
    """Return a source instance by name, or ``None`` if not registered."""
    cls = SOURCES.get(name)
    return cls() if cls is not None else None


class JobSource(abc.ABC):
    """Interface every job source implements."""

    source_name: str = ""
    #: True when discovery needs a local Playwright browser.
    requires_browser: bool = False

    @abc.abstractmethod
    async def search(self, query: str, location: str = "India", max_results: int = 10) -> list[Job]:
        """Discover up to ``max_results`` jobs for ``query``.

        Must never raise: errors should be logged and ``[]`` returned so one
        failing source does not break the whole search.
        """
