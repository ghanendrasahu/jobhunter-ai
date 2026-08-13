"""Playwright browser management with a persistent, logged-in session.

Modern Chrome blocks CDP automation on the *real* default profile and encrypts
its cookies (App-Bound Encryption) so third parties can't read them. The reliable
workaround used here: copy a **minimal slice** of the user's default Chrome
profile (``Local State`` + ``Preferences`` + the ``Network``/cookie folder —
only a few MB) into ``browser_state_dir/default_profile``, then launch Chrome
against that copy. Chrome decrypts its own cookies in the copy, so all existing
logins (Naukri, Indeed, ...) work with zero extra login.

The copy is refreshed automatically whenever the source profile is newer, so
new logins in the user's real Chrome are picked up on later runs.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from playwright.sync_api import BrowserContext, Page, sync_playwright

logger = logging.getLogger(__name__)

# Top-level Chrome "User Data" files needed for a working profile.
_PROFILE_TOP_FILES = ("Local State", "First Run")
# Files inside the profile dir needed for cookies/session + basic config.
_PROFILE_FILES = ("Preferences", "Secure Preferences", "Network")
# Subdirectories of the profile that hold heavy caches — never copied.
_CACHE_DIRS = {
    "Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache",
    "CachedData", "DawnGraphiteCache", "DawnWebGPUCache", "Service Worker",
    "IndexedDB", "DawnCache", "DawnShaderCache",
}


class BrowserSession:
    """Thin wrapper around a Playwright persistent browser context."""

    def __init__(
        self,
        state_dir: Path,
        headless: bool = False,
        channel: str = "chrome",
        use_default_profile: bool = True,
        user_data_dir: str = "",
    ):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.channel = channel or "chrome"
        self.use_default_profile = use_default_profile
        self.user_data_dir = Path(user_data_dir) if user_data_dir else None
        self.using_default_profile = False
        self._playwright = None
        self._context: Optional[BrowserContext] = None

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> BrowserContext:
        """Launch the persistent context, preferring a copy of the user's profile."""
        self._playwright = sync_playwright().start()

        launch_dir: Optional[Path] = None
        if self.use_default_profile:
            launch_dir = self._ensure_default_profile_copy()
            if launch_dir:
                self.using_default_profile = True

        try:
            self._context = self._launch(
                user_data_dir=launch_dir or self.state_dir / "profile",
                channel="chrome" if launch_dir else self.channel,
            )
        except Exception as exc:
            logger.warning("Could not launch Chrome (%s); falling back to bundled chromium", exc)
            self._context = self._launch(
                user_data_dir=launch_dir or self.state_dir / "profile",
                channel=None,
            )

        if self.using_default_profile:
            logger.info("Using the user's default Chrome account sessions (copied profile)")
        logger.info("Browser session started (channel=%s, headless=%s)", self.channel, self.headless)
        return self._context

    # ------------------------------------------------------------- default profile
    def _ensure_default_profile_copy(self) -> Optional[Path]:
        """Return a fresh-enough copy of the user's default Chrome profile, or None."""
        source = self.user_data_dir or self.default_chrome_profile_dir()
        if not source:
            return None
        source_local_state = source / "Local State"
        if not source_local_state.exists():
            return None

        dst = self.state_dir / "default_profile"
        dst_local_state = dst / "Local State"

        needs_refresh = not dst_local_state.exists()
        if not needs_refresh and source_local_state.exists():
            try:
                needs_refresh = source_local_state.stat().st_mtime > dst_local_state.stat().st_mtime
            except OSError:
                needs_refresh = False

        if needs_refresh:
            try:
                _copy_minimal_profile(source, dst)
                logger.info("Refreshed default-profile copy in %s", dst)
            except Exception as exc:
                logger.warning("Could not refresh default-profile copy (%s); reusing existing copy", exc)
                if not dst_local_state.exists():
                    return None
        return dst

    @staticmethod
    def default_chrome_profile_dir() -> Optional[Path]:
        """Locate the user's real Chrome 'User Data' directory (parent of 'Default')."""
        candidates = [
            Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
            Path.home() / "AppData" / "Local" / "Chromium" / "User Data",
        ]
        for candidate in candidates:
            if (candidate / "Default").exists():
                return candidate
        return None

    # ------------------------------------------------------------------ helpers
    def _launch(self, user_data_dir: Path, channel: Optional[str] = None) -> BrowserContext:
        kwargs: dict = {
            "user_data_dir": str(user_data_dir),
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


def _copy_minimal_profile(source: Path, dst: Path) -> None:
    """Copy the small files Chrome needs to boot with the user's sessions.

    ``source`` is the real "User Data" directory; the copy keeps the ``Default``
    profile structure plus the top-level ``Local State`` (encryption keys).
    The swap is crash-safe: the new copy lands in a temp dir and is renamed into
    place (old copy moved to a backup first), so a partial copy never corrupts
    the working profile.
    """
    src_default = source / "Default"
    temp = dst.with_name(dst.name + ".tmp")
    backup = dst.with_name(dst.name + ".bak")
    for stale in (temp, backup):
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)
    temp.mkdir(parents=True, exist_ok=True)
    (temp / "Default").mkdir(parents=True, exist_ok=True)

    for name in _PROFILE_TOP_FILES:
        if (source / name).exists():
            shutil.copy2(source / name, temp / name)

    for name in _PROFILE_FILES:
        src = src_default / name
        if src.is_dir():
            shutil.copytree(src, temp / "Default" / name, dirs_exist_ok=True)
        elif src.exists():
            shutil.copy2(src, temp / "Default" / name)

    if not (temp / "Local State").exists():
        raise RuntimeError("Local State missing from profile copy")

    if dst.exists():
        try:
            dst.rename(backup)
        except Exception:
            shutil.rmtree(dst, ignore_errors=True)
    try:
        temp.rename(dst)
    except Exception:
        if backup.exists() and not dst.exists():
            backup.rename(dst)
        raise
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


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
