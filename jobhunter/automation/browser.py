"""Playwright browser management with a persistent, logged-in session.

A persistent browser profile (``data/browser_state/profile``) keeps the user
logged into job portals between runs, so credentials are only used on first login.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext, Page, sync_playwright

logger = logging.getLogger(__name__)


class BrowserSession:
    """Thin wrapper around a Playwright persistent browser context.

    Uses the user's installed Chrome (``channel="chrome"``) when available so
    logins already present in Chrome can be reused, and falls back to the
    bundled chromium build otherwise.
    """

    def __init__(self, state_dir: Path, headless: bool = False, channel: str = "chrome"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.channel = channel or "chrome"
        self._playwright = None
        self._context: Optional[BrowserContext] = None

    def start(self) -> BrowserContext:
        """Launch the persistent context (non-headless by default for human-in-the-loop)."""
        self._playwright = sync_playwright().start()
        try:
            self._context = self._launch()
        except Exception as exc:
            logger.warning("Could not launch channel %r (%s); falling back to bundled chromium", self.channel, exc)
            self._context = self._launch(channel=None)
        logger.info("Browser session started (channel=%s, headless=%s)", self.channel, self.headless)
        return self._context

    def _launch(self, channel: Optional[str] = None) -> BrowserContext:
        kwargs: dict = {
            "user_data_dir": str(self.state_dir / "profile"),
            "headless": self.headless,
            "args": ["--start-maximized"],
            "no_viewport": True,
        }
        if channel:
            kwargs["channel"] = channel
        return self._playwright.chromium.launch_persistent_context(**kwargs)

    def new_page(self) -> Page:
        if self._context is None:
            raise RuntimeError("Browser session not started. Call start() first.")
        return self._context.new_page()

    def save_state(self) -> None:
        """Persist cookies/localStorage so logins survive between runs."""
        if self._context is not None:
            path = str(self.state_dir / "storage_state.json")
            self._context.storage_state(path=path)
            logger.info("Browser session state saved to %s", path)

    def stop(self) -> None:
        try:
            self.save_state()
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Failed to save browser state: %s", exc)
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()
        logger.info("Browser session stopped")


def wait_for(page: Page, selector: str, timeout_ms: int = 15000) -> bool:
    """Wait for a selector and return whether it appeared (never raises)."""
    try:
        page.wait_for_selector(selector, timeout=timeout_ms)
        return True
    except Exception:
        return False


def is_logged_in(page: Page, logged_in_selector: str) -> bool:
    """Best-effort check for a logged-in indicator on the current page."""
    if not logged_in_selector:
        return True
    return wait_for(page, logged_in_selector, timeout_ms=3000)
