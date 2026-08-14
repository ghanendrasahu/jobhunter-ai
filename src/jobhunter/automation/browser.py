"""Playwright browser management with a persistent, logged-in session.

How JobHunter drives Chrome:

1. **Dedicated JobHunter window + CDP (the only supported automation path).**
   A separate, visible Chrome window is launched once on its own
   ``automation_profile`` directory with a remote-debugging port, then the agent
   attaches via ``connect_over_cdp`` and reuses the *same* window across runs —
   so manual portal logins (Naukri, LinkedIn, Indeed) persist. The user's
   real/default Chrome profile is never touched, copied, or closed.

2. **Why not the user's real profile?** Chrome 136+ refuses to expose a remote
   debugging port (or pipe) when the user-data-dir is the real Chrome profile —
   this is a security fix that cannot be disabled. Chrome 127+ also encrypts
   profile cookies with App-Bound Encryption, so copying the profile no longer
   carries logins (the cookies are discarded on first launch of the copy).
   JobHunter therefore uses its own window and asks for a one-time login per
   portal. ``detect_chrome_user_data_dir`` / ``list_chrome_profiles`` only *read*
   profile metadata for the UI and never modify anything.

   A legacy ``_launch_copied_profile`` fallback still exists but its sessions do
   not survive on Chrome 127+.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

logger = logging.getLogger(__name__)


class _BrowserMissing(Exception):
    """Internal marker: the requested browser executable is not installed."""

    def __init__(self, channel: str | None) -> None:
        self.channel = channel
        super().__init__(f"browser executable missing for channel={channel}")


class SessionSafetyError(RuntimeError):
    """Raised when a safe, authenticated browser session cannot be established.

    Auto-apply must never run on a copied/logged-out profile: if the dedicated
    JobHunter window (CDP + automation profile) cannot be started or attached,
    callers that require authentication (the apply agent) must refuse rather
    than silently fall back to a session whose logins do not survive Chrome 127+.
    """

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

# Hide Playwright automation fingerprints so portals (and Google sign-in)
# treat the browser as a normal Chrome instance.
_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--start-maximized",
]

_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""


@dataclass(frozen=True)
class ChromeProfileInfo:
    """A profile discovered inside the user's real Chrome "User Data" dir."""

    dir_name: str
    friendly_name: str
    path: Path
    is_default: bool


# Portal login pages + logged-in DOM indicators (presence-only, never values).
PORTAL_LOGIN_CHECKS: dict[str, tuple[str, list[str]]] = {
    "naukri": (
        "https://www.naukri.com/",
        [".ni-gnb-icn", "[class*='user']"],
    ),
    "linkedin": (
        "https://www.linkedin.com/feed/",
        [".global-nav__me", "button[aria-label*='profile']"],
    ),
    "indeed": (
        "https://in.indeed.com/",
        ["[data-testid='account-menu']", ".desktop-header-account"],
    ),
}


def _profile_number(dir_name: str) -> int:
    """Sort key for profile dirs: 'Default' first, then 'Profile N' numerically."""
    if dir_name == "Default":
        return -1
    parts = dir_name.split()
    if len(parts) == 2 and parts[0] == "Profile" and parts[1].isdigit():
        return int(parts[1])
    return 10_000


def _friendly_name(raw: object, dir_name: str) -> str:
    """Best display name for a profile from its Local State info_cache entry."""
    if isinstance(raw, str):
        return raw or dir_name
    if isinstance(raw, dict):
        for key in ("name", "shortcut_name", "user_name", "gaia_name"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return dir_name


def detect_chrome_user_data_dir() -> Path | None:
    """Locate the user's real Chrome "User Data" directory, or None.

    Read-only: the directory (and its profiles) is never modified.
    """
    home = Path.home()
    candidates = [
        home / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
        home / "Library" / "Application Support" / "Google" / "Chrome",
        home / ".config" / "google-chrome",
        home / ".config" / "chromium",
    ]
    for candidate in candidates:
        if (candidate / "Local State").exists():
            return candidate
    return None


def list_chrome_profiles(user_data_dir: Path | None = None) -> list[ChromeProfileInfo]:
    """List the user's real Chrome profiles with friendly names from Local State.

    ``friendly_name`` comes from ``Local State`` → ``profile.info_cache`` (the
    name the user sees in Chrome's profile picker) and falls back to the folder
    name when it is missing. Only metadata is read — nothing is modified.
    """
    ud = Path(user_data_dir) if user_data_dir else detect_chrome_user_data_dir()
    if ud is None or not ud.is_dir():
        return []

    info_cache: dict[str, object] = {}
    try:
        raw = (ud / "Local State").read_text(encoding="utf-8")
        info_cache = json.loads(raw).get("profile", {}).get("info_cache", {}) or {}
    except Exception:
        info_cache = {}

    profiles: list[ChromeProfileInfo] = []
    for entry in ud.iterdir():
        if not entry.is_dir():
            continue
        name = entry.name
        if name == "Default" or (
            name.startswith("Profile")
            and len(name.split()) == 2
            and name.split()[1].isdigit()
        ):
            friendly = _friendly_name(info_cache.get(name), name)
            profiles.append(
                ChromeProfileInfo(
                    dir_name=name,
                    friendly_name=friendly,
                    path=entry,
                    is_default=name == "Default",
                )
            )
    profiles.sort(key=lambda p: (not p.is_default, _profile_number(p.dir_name)))
    return profiles


def is_chrome_running() -> bool:
    """Return True when a Chrome process is currently running on this machine.

    Used only for the UI status line; does not touch or close any Chrome.
    """
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                capture_output=True, text=True, timeout=5,
            )
            return "chrome.exe" in result.stdout
        except Exception:
            return False
    try:
        result = subprocess.run(
            ["pgrep", "-x", "chrome"], capture_output=True, text=True, timeout=5,
        )
        return bool(result.stdout.strip())
    except Exception:
        return False


def _logged_in_js(selectors: list[str]) -> str:
    """Build a presence-only JS expression: true when any selector is present."""
    parts = [f"!!document.querySelector({json.dumps(s)})" for s in selectors]
    return "(() => " + " || ".join(parts) + ")()"


class BrowserSession:
    """Thin wrapper around a Playwright persistent browser context."""

    def __init__(
        self,
        state_dir: Path,
        headless: bool = False,
        channel: str = "chrome",
        use_default_profile: bool = True,
        user_data_dir: str = "",
        cdp_url: str = "",
        profile_dir: Path | None = None,
        debug_port: int = 9222,
        use_dedicated_profile: bool = True,
        allow_copied_fallback: bool = True,
    ):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.channel = channel or "chrome"
        self.use_default_profile = use_default_profile
        self.user_data_dir = Path(user_data_dir) if user_data_dir else None
        self.cdp_url = cdp_url
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.debug_port = debug_port
        self.use_dedicated_profile = use_dedicated_profile
        self.allow_copied_fallback = allow_copied_fallback
        self.using_default_profile = False
        self.using_cdp = False
        self.using_dedicated_profile = False
        self.reused_existing = False
        self.launched_new = False
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        # Pages created by the agent (so CDP cleanup never touches the user's tabs).
        self._agent_pages: list[Page] = []

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> BrowserContext:
        """Start the browser, preferring the dedicated automation profile + CDP.

        Priority: explicit ``cdp_url`` override → dedicated automation profile
        (launch-or-attach via CDP) → copied default-profile launch.

        When ``allow_copied_fallback`` is False (the auto-apply path), the
        copied-profile fallback is refused: auto-apply must never silently run
        on a copied/logged-out session, so a ``SessionSafetyError`` is raised
        instead of launching one.
        """
        self._playwright = sync_playwright().start()

        if self.cdp_url:
            return self._attach_cdp(self.cdp_url)

        if self.use_dedicated_profile:
            try:
                return self.ensure_connected()
            except Exception as exc:
                self._cleanup_playwright()
                if not self.allow_copied_fallback:
                    raise SessionSafetyError(
                        "Dedicated authenticated browser could not be established "
                        f"({exc}). Auto-apply refused: it must never run on a copied "
                        "or logged-out profile. Start the JobHunter window and log in "
                        "to Naukri/Indeed once, then re-run."
                    ) from exc
                logger.warning(
                    "Dedicated automation profile unavailable (%s); "
                    "falling back to copied-profile launch", exc,
                )

        if not self.allow_copied_fallback:
            self._cleanup_playwright()
            raise SessionSafetyError(
                "Auto-apply requires the dedicated authenticated JobHunter browser, "
                "but it is not configured (browser_use_dedicated_profile=False). "
                "Refusing to run on a copied or logged-out profile."
            )
        return self._launch_copied_profile()

    def ensure_connected(self) -> BrowserContext:
        """Launch (if needed) the dedicated JobHunter Chrome and attach via CDP.

        - Chrome already running on the configured debug port → connect and
          reuse the same window/profile.
        - Otherwise launch a new dedicated Chrome process on its own profile
          directory (never the user's default profile) with remote debugging,
          then connect.

        The visible window stays open between runs, so manual logins persist.
        Raises when neither launch nor attach is possible.
        """
        assert self._playwright is not None
        debug_url = f"http://127.0.0.1:{self.debug_port}"
        if not self._cdp_reachable(debug_url):
            self.launched_new = True
            self._launch_dedicated(debug_url)
        else:
            self.reused_existing = True
        self.using_dedicated_profile = True
        return self._attach_cdp(debug_url)

    def restart(self) -> BrowserContext:
        """Tear down and re-launch/reattach after a browser crash.

        Preserves the profile and (in CDP mode) the persistent window.
        """
        self.stop()
        self.using_cdp = False
        self.using_dedicated_profile = False
        self.reused_existing = False
        self.launched_new = False
        return self.start()

    def _cleanup_playwright(self) -> None:
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # pragma: no cover - best effort
                pass
            self._playwright = None

    def _launch_copied_profile(self) -> BrowserContext:
        """Launch a persistent context from a copy of the user's default profile."""
        if self._playwright is None:
            self._playwright = sync_playwright().start()

        launch_dir: Path | None = None
        if self.use_default_profile:
            launch_dir = self._ensure_default_profile_copy()
            if launch_dir:
                self.using_default_profile = True

        prefer_chrome = bool(launch_dir or self.channel == "chrome")
        try:
            if prefer_chrome:
                # System Chrome is the best fingerprint. Verify the *bundled*
                # Chromium exists up front so we can raise a clear error if the
                # fallback is missing too.
                self._verify_bundled_chromium()
                self._context = self._launch(
                    user_data_dir=launch_dir or self.state_dir / "profile",
                    channel="chrome",
                )
            else:
                self._verify_bundled_chromium()
                self._context = self._launch(
                    user_data_dir=launch_dir or self.state_dir / "profile",
                    channel=self.channel or None,
                )
        except _BrowserMissing as exc:
            raise RuntimeError(
                "The Playwright browser is not installed. Run:\n"
                "    python -m playwright install chromium"
            ) from exc
        except Exception as exc:
            # Chrome is installed but failed to launch (e.g. profile lock or
            # a CDP/version conflict). Fall back to bundled Chromium rather
            # than crashing with the opaque Playwright message.
            logger.warning("Could not launch Chrome (%s); falling back to bundled chromium", exc)
            self._verify_bundled_chromium()
            self._context = self._launch(
                user_data_dir=launch_dir or self.state_dir / "profile",
                channel=None,
            )

        if self.using_default_profile:
            logger.info("Using the user's default Chrome account sessions (copied profile)")
        self._apply_stealth()
        logger.info("Browser session started (channel=%s, headless=%s)", self.channel, self.headless)
        assert self._context is not None
        return self._context

    def _attach_cdp(self, url: str | None = None) -> BrowserContext:
        """Attach to an already-running Chrome via CDP (reuses the window/profile).

        No second Chrome window is opened and no profile copy is made: the agent
        drives the given browser and reuses every existing login directly.
        """
        url = (url or self.cdp_url).strip()
        if not url:
            raise RuntimeError("No CDP URL configured")
        assert self._playwright is not None
        try:
            browser = self._playwright.chromium.connect_over_cdp(url)
        except Exception as exc:
            raise RuntimeError(
                f"Could not connect to Chrome at {url}. Start Chrome with:\n"
                f"    chrome.exe --remote-debugging-port={self.debug_port}\n"
                f"Original error: {exc}"
            ) from exc
        contexts = browser.contexts
        if not contexts:
            raise RuntimeError(f"Chrome at {url} exposed no browser context")
        self._context = next((c for c in contexts if c.pages), contexts[0])
        self.using_cdp = True
        self._apply_stealth()
        logger.info("Attached to Chrome at %s (reusing window + logins)", url)
        return self._context

    # ------------------------------------------------------------- dedicated profile
    @staticmethod
    def _cdp_reachable(url: str, timeout: float = 3.0) -> bool:
        """Return True when Chrome's CDP endpoint at ``url`` answers /json/version."""
        try:
            with urllib.request.urlopen(f"{url}/json/version", timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    @staticmethod
    def _chrome_candidates() -> list[Path]:
        """Platform-specific locations of the Chrome executable (never the profile)."""
        home = Path.home()
        return [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google" / "Chrome" / "Application" / "chrome.exe",
            home / "AppData" / "Local" / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/chromium"),
            Path("/usr/bin/chromium-browser"),
        ]

    @staticmethod
    def _chrome_executable() -> str | None:
        """Return the path of the installed Chrome executable, or None."""
        for candidate in BrowserSession._chrome_candidates():
            try:
                if candidate.exists():
                    return str(candidate)
            except OSError:
                continue
        return None

    def _resolved_profile_dir(self) -> Path:
        """The dedicated automation profile directory (never the default profile)."""
        if self.profile_dir is not None:
            return Path(self.profile_dir)
        return self.state_dir / "automation_profile"

    def _launch_dedicated(self, debug_url: str) -> None:
        """Start the dedicated JobHunter Chrome window on the debug port (headful).

        The profile directory is owned by JobHunter — the user's real/default
        Chrome profile is never used, and no running Chrome is touched.
        """
        chrome = self._chrome_executable()
        if not chrome:
            raise RuntimeError(
                "Chrome executable not found; cannot start the dedicated JobHunter browser."
            )
        profile_dir = self._resolved_profile_dir()
        profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            chrome,
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={self.debug_port}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "--start-maximized",
        ]
        logger.info("Launching dedicated JobHunter Chrome (profile=%s, port=%s)", profile_dir, self.debug_port)
        try:
            subprocess.Popen(args)
        except OSError as exc:
            raise RuntimeError(f"Failed to launch Chrome: {exc}") from exc

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self._cdp_reachable(debug_url, timeout=1.0):
                logger.info("Dedicated JobHunter Chrome is ready at %s", debug_url)
                return
            time.sleep(0.5)
        raise RuntimeError(f"Dedicated Chrome did not open the debug port at {debug_url} within 20s")

    def _verify_bundled_chromium(self) -> None:
        """Raise a clear error when Playwright's bundled Chromium is missing.

        ``chromium.executable_path`` points at the bundled build (the one that
        ``launch_persistent_context`` without a ``channel`` uses). We check it
        upfront so users see a helpful install hint instead of Playwright's
        cryptic "Executable doesn't exist" crash.
        """
        if self._playwright is None:
            raise RuntimeError("browser must be started first")
        try:
            executable = self._playwright.chromium.executable_path
        except Exception:
            raise _BrowserMissing(None) from None
        if not executable or not Path(executable).exists():
            raise _BrowserMissing(None)

    def _apply_stealth(self) -> None:
        """Mask automation signals that trigger bot checks / Google sign-in blocks."""
        if self._context is None:
            raise RuntimeError("browser context must be started first")
        try:
            self._context.add_init_script(_STEALTH_SCRIPT)
        except Exception as exc:
            logger.warning("Could not apply stealth script: %s", exc)

    # ------------------------------------------------------------- default profile
    def _ensure_default_profile_copy(self) -> Path | None:
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
    def default_chrome_profile_dir() -> Path | None:
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
    def _launch(self, user_data_dir: Path, channel: str | None = None) -> BrowserContext:
        if self._playwright is None:
            raise RuntimeError("browser must be started first")
        kwargs: dict = {
            "user_data_dir": str(user_data_dir),
            "headless": self.headless,
            "args": _STEALTH_ARGS,
            "no_viewport": True,
        }
        if channel:
            kwargs["channel"] = channel
        return self._playwright.chromium.launch_persistent_context(**kwargs)

    def new_page(self) -> Page:
        if self._context is None:
            raise RuntimeError("Browser session not started. Call start() first.")
        page = self._context.new_page()
        self._agent_pages.append(page)
        return page

    def new_tab(self, url: str = "") -> Page:
        """Open a new tab (optionally navigated) and return it."""
        page = self.new_page()
        if url:
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
        return page

    def open_page(self, url: str) -> Page:
        """Open a tab that survives detach (e.g. for a manual one-time login).

        Unlike :meth:`new_tab`, the page is *not* registered for agent cleanup,
        so calling :meth:`stop` detaches from CDP and leaves the tab open in the
        JobHunter window.
        """
        if self._context is None:
            raise RuntimeError("Browser session not started. Call start() first.")
        page = self._context.new_page()
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        return page

    def close_page(self, page: Page) -> None:
        """Close a tab, swallowing errors (page may already be closed)."""
        if page in self._agent_pages:
            self._agent_pages.remove(page)
        try:
            if page and not page.is_closed():
                page.close()
        except Exception as exc:  # pragma: no cover - best effort cleanup
            logger.debug("Could not close page: %s", exc)

    def close_all_pages(self) -> None:
        """Close every tab the agent opened (never touches the user's own tabs)."""
        pages = list(self._agent_pages)
        for page in pages:
            self.close_page(page)
        self._agent_pages.clear()

    def save_state(self) -> None:
        """Persist cookies/localStorage so logins survive between runs."""
        if self._context is not None:
            path = str(self.state_dir / "storage_state.json")
            self._context.storage_state(path=path)
            logger.info("Browser session state saved to %s", path)

    def stop(self) -> None:
        if self.using_cdp:
            # Never close the user's browser or context — only the tabs we opened.
            try:
                self.close_all_pages()
            except Exception as exc:
                logger.warning("CDP cleanup of agent tabs failed: %s", exc)
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception as exc:
                    logger.warning("CDP detach failed: %s", exc)
            logger.info("Detached from Chrome (your window stays open)")
            return
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

    Files Chrome currently has open (notably ``Network``/cookies) are skipped
    individually rather than aborting the whole copy, so the existing profile
    is always preferred over silently dropping to a fresh, logged-out profile.
    """
    src_default = source / "Default"
    temp = dst.with_name(dst.name + ".tmp")
    backup = dst.with_name(dst.name + ".bak")
    for stale in (temp, backup):
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)
    temp.mkdir(parents=True, exist_ok=True)
    (temp / "Default").mkdir(parents=True, exist_ok=True)

    skipped: list[str] = []

    def _copy_one(src_path: Path, dst_path: Path) -> None:
        for _ in range(3):
            try:
                shutil.copy2(src_path, dst_path)
                return
            except PermissionError:
                time.sleep(0.2)
        skipped.append(src_path.name)

    for name in _PROFILE_TOP_FILES:
        if (source / name).exists():
            _copy_one(source / name, temp / name)

    def _copy_tree(src_dir: Path, dst_dir: Path) -> None:
        skipped_local: list[str] = []

        def _copy_file(s: str, d: str) -> None:
            try:
                shutil.copy2(s, d)
            except PermissionError:
                skipped_local.append(Path(s).name)

        try:
            shutil.copytree(
                src_dir, dst_dir, dirs_exist_ok=True,
                copy_function=_copy_file, ignore_dangling_symlinks=True,
            )
        except shutil.Error:
            skipped_local.append(src_dir.name)
        skipped.extend(skipped_local)

    for name in _PROFILE_FILES:
        src = src_default / name
        if src.is_dir():
            _copy_tree(src, temp / "Default" / name)
        elif src.exists():
            _copy_one(src, temp / "Default" / name)

    if not (temp / "Local State").exists():
        raise RuntimeError("Local State missing from profile copy")

    if skipped:
        logger.warning(
            "Chrome is probably running: %d profile file(s) were locked and skipped (%s). "
            "New logins in Chrome won't appear until you close Chrome and re-run.",
            len(skipped), ", ".join(sorted(set(skipped))),
        )

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


def build_session(settings, allow_copied_fallback: bool = True) -> BrowserSession:
    """Construct a BrowserSession from a Settings object (shared by all helpers).

    ``allow_copied_fallback=False`` marks the session as auto-apply: ``start()``
    then raises :class:`SessionSafetyError` instead of ever launching the legacy
    copied-profile fallback.
    """
    return BrowserSession(
        settings.browser_state_dir,
        settings.headless_browser,
        settings.browser_channel,
        settings.browser_use_default_profile,
        settings.browser_user_data_dir,
        settings.browser_cdp_url,
        settings.browser_profile_dir,
        settings.browser_debug_port,
        settings.browser_use_dedicated_profile,
        allow_copied_fallback=allow_copied_fallback,
    )


def browser_status(settings=None) -> dict:
    """Snapshot of the JobHunter browser state for the UI status line.

    Returns keys: ``running`` (dedicated window CDP reachable), ``cdp_url``,
    ``profile_dir``, ``chrome_running`` (any normal Chrome process), and
    ``user_data_dir`` (the user's real Chrome profile dir, or None). Read-only.
    """
    from jobhunter.config import get_settings  # local import to avoid import cycles

    if settings is None:
        settings = get_settings()
    debug_url = f"http://127.0.0.1:{settings.browser_debug_port}"
    return {
        "running": BrowserSession._cdp_reachable(debug_url),
        "cdp_url": debug_url,
        "profile_dir": str(settings.browser_profile_dir),
        "chrome_running": is_chrome_running(),
        "user_data_dir": detect_chrome_user_data_dir(),
    }


def check_portal_logins(settings=None, session: BrowserSession | None = None) -> dict[str, bool]:
    """Report (presence-only) whether each portal is logged in, per site.

    Opens a fresh tab in the JobHunter window for each portal, evaluates a
    boolean DOM expression, and closes it. Never reads or logs cookie/session
    values. Returns e.g. ``{"naukri": True, "linkedin": False, "indeed": True}``.
    """
    from jobhunter.config import get_settings  # local import to avoid import cycles

    if settings is None:
        settings = get_settings()
    if session is None:
        session = build_session(settings)
        session.start()
        own_session = True
    else:
        own_session = False

    results: dict[str, bool] = {}
    try:
        for portal, (url, selectors) in PORTAL_LOGIN_CHECKS.items():
            page = None
            try:
                page = session.new_tab(url)
                page.wait_for_timeout(3000)
                results[portal] = bool(page.evaluate(_logged_in_js(selectors)))
            except Exception as exc:
                logger.warning("Login check failed for %s: %s", portal, exc)
                results[portal] = False
            finally:
                if page is not None:
                    session.close_page(page)
    finally:
        if own_session:
            session.stop()
    return results


def open_login_page(settings=None, url: str = "") -> str:
    """Open ``url`` in the JobHunter window for a one-time manual login.

    Ensures the dedicated window is running, opens the given portal (a fresh
    tab that stays open after detach), then detaches. Returns a status message.
    """
    from jobhunter.config import get_settings  # local import to avoid import cycles

    if settings is None:
        settings = get_settings()
    if not url:
        url = PORTAL_LOGIN_CHECKS["naukri"][0]
    session = build_session(settings)
    session.start()
    try:
        session.open_page(url)
    finally:
        session.stop()
    return f"Opened {url} in the JobHunter window — log in there once; it is remembered."


def launch_dedicated_browser(settings) -> str:
    """Ensure the dedicated JobHunter Chrome is running; return a status message.

    Launches the persistent automation window on its own profile when it is not
    already running, then verifies the CDP endpoint. Never touches the user's
    default Chrome profile and never closes any running Chrome.
    """
    from jobhunter.config import get_settings  # local import to avoid import cycles

    if settings is None:
        settings = get_settings()
    debug_url = f"http://127.0.0.1:{settings.browser_debug_port}"

    if settings.browser_cdp_url:
        if BrowserSession._cdp_reachable(settings.browser_cdp_url):
            return "Browser connected — attached to the configured CDP endpoint."
        return (
            "Configured CDP endpoint is not reachable. Start Chrome on the "
            "configured port first, then retry."
        )

    if not settings.browser_use_dedicated_profile:
        return (
            "Dedicated JobHunter browser is disabled (BROWSER_USE_DEDICATED_PROFILE=false). "
            "Enable it in .env or settings to use the persistent browser."
        )

    session = build_session(settings)
    if BrowserSession._cdp_reachable(debug_url):
        return (
            f"Browser connected — reusing the dedicated JobHunter window "
            f"(port {settings.browser_debug_port})."
        )
    session._launch_dedicated(debug_url)
    return (
        f"Browser started — dedicated JobHunter window launched on port "
        f"{settings.browser_debug_port} (profile: {session._resolved_profile_dir()}). "
        "Log in to Naukri/Indeed once; sessions persist between runs."
    )
