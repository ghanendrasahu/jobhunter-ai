"""Application configuration loaded from environment variables and a `.env` file."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root: the src/ layout (parents[2] of src/jobhunter/config.py), or an
# explicit override so installed (non-editable) deployments can point data dirs
# at a writable location (e.g. /app in Docker).
PROJECT_ROOT = Path(os.environ.get("JOBHUNTER_ROOT", str(Path(__file__).resolve().parents[2])))

logger = logging.getLogger(__name__)

_ENV_PATH = PROJECT_ROOT / ".env"
if not _ENV_PATH.exists():
    logger.info(
        "No .env file found. Copy .env.example to .env and fill in your "
        "API keys for full functionality."
    )


class Settings(BaseSettings):
    """Typed, environment-driven application settings.

    Every field maps to an UPPER_CASE environment variable (e.g. `OPENAI_API_KEY`).
    Values are also read from ``.env`` next to the project root.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # Optional job APIs
    adzuna_app_id: str = ""
    adzuna_api_key: str = ""
    jooble_api_key: str = ""
    jsearch_api_key: str = ""

    # SMTP email notifications (optional)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    notification_email: str = ""

    # Optional API auth (FastAPI)
    jobhunter_api_key: str = ""
    api_rate_limit: str = "20/minute"

    # ------------------------------------------------------------------
    # Application automation (semi-autonomous apply agent)
    # ------------------------------------------------------------------
    # Portal login credentials (stored in .env, never committed)
    naukri_email: str = ""
    naukri_password: str = ""
    indeed_email: str = ""
    indeed_password: str = ""

    # Automation behaviour
    auto_apply_mode: Literal["human", "auto", "off"] = "human"
    max_applications_per_run: int = 5
    headless_browser: bool = False
    browser_state_dir: Path = PROJECT_ROOT / "data" / "browser_state"
    # Browser channel: "chrome" reuses your installed Chrome (best fingerprint).
    browser_channel: str = "chrome"
    # Reuse your default Chrome account sessions: the agent copies a minimal
    # slice of your real Chrome profile (only a few MB) and launches against the
    # copy, so all existing portal logins work with zero extra login. The copy is
    # refreshed automatically when your real profile changes.
    browser_use_default_profile: bool = True
    # Optional explicit Chrome "User Data" directory (auto-detected when empty).
    browser_user_data_dir: str = ""
    # Dedicated persistent JobHunter browser (preferred). A separate, visible
    # Chrome window on its own profile dir is launched once with a remote
    # debugging port and reused across runs, so manual portal logins persist.
    # The user's real (default) Chrome profile is never touched. Disable to
    # always use the copied default-profile fallback instead.
    browser_use_dedicated_profile: bool = True
    # Directory for the dedicated JobHunter Chrome profile.
    browser_profile_dir: Path = PROJECT_ROOT / "data" / "browser_state" / "automation_profile"
    # Remote-debugging port used by the dedicated JobHunter Chrome.
    browser_debug_port: int = 9222
    # Optional explicit CDP endpoint override (e.g. http://127.0.0.1:9222).
    # When set, the agent connects to that already-running browser instead of
    # launching the dedicated one.
    browser_cdp_url: str = ""
    # Seconds to wait for a manual login in the opened browser window.
    manual_login_timeout: int = 180
    # Only consider fresher/entry-level roles (filters out senior listings).
    fresher_only: bool = True
    # Jobs requiring more than this many years of experience are skipped.
    max_experience_years: int = 2
    # Continuous mode: applications per cycle before the cooldown pause.
    batch_size: int = 10
    # Continuous mode: seconds to wait between cycles (avoid rate-limit bans).
    cooldown_seconds: int = 300
    # Rank remote/WFH jobs above office jobs of equal quality.
    prioritize_remote: bool = True
    # Query suffixes rotated across continuous-mode cycles (comma-separated).
    query_variants: str = "fresher,entry level,remote"
    # Search-plan locations swept for primary queries (comma-separated).
    search_locations: str = "India,Bengaluru,Remote,Hybrid"
    # How many result pages to walk through per query in a cycle.
    paginate_depth: int = 3

    # Full job-description refresh (PHASE 1A): when enabled, jobs whose result
    # snippet is too thin trigger a full-page fetch of the job description.
    fetch_full_descriptions: bool = False
    # Max number of full-description pages fetched per search.
    fetch_full_description_max: int = 5

    # Runtime performance tuning
    # Max planned queries searched concurrently (browser-heavy sources: keep low).
    search_max_concurrency: int = 2
    # Max threads used to run LLM relevance refinement in parallel.
    score_max_workers: int = 4

    # Runtime paths and limits
    upload_dir: Path = PROJECT_ROOT / "uploads"
    history_dir: Path = PROJECT_ROOT / "history"
    resumes_dir: Path = PROJECT_ROOT / "resumes"
    max_file_size_mb: int = 10

    @property
    def max_upload_bytes(self) -> int:
        """Maximum accepted PDF upload size in bytes."""
        return self.max_file_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton, with persisted overrides applied."""
    settings = Settings()
    overrides = _persisted_overrides()
    if overrides:
        settings = settings.model_copy(update=overrides)
    return settings


# Settings the user may persist from the dashboard (layered over .env).
PERSISTED_SETTING_KEYS: tuple[str, ...] = (
    "naukri_email",
    "naukri_password",
    "indeed_email",
    "indeed_password",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_pass",
    "notification_email",
    "auto_apply_mode",
    "max_applications_per_run",
    "batch_size",
    "cooldown_seconds",
    "prioritize_remote",
)


def _persisted_overrides() -> dict[str, object]:
    """Merge dashboard-saved settings over env, coercing to the field type."""
    try:
        from jobhunter.storage.settings import load_settings

        raw = load_settings()
    except Exception:
        return {}
    fields = Settings.model_fields
    overrides: dict[str, object] = {}
    for key in PERSISTED_SETTING_KEYS:
        if key not in raw or key not in fields:
            continue
        value: object = raw[key]
        field_info = fields[key]
        annotation = field_info.annotation
        if annotation in (int, bool, float):
            try:
                value = annotation(raw[key])
            except (TypeError, ValueError):
                continue
        overrides[key] = value
    return overrides


def missing_api_keys() -> list[str]:
    """Names of optional API keys that are not configured, in priority order."""
    settings = get_settings()
    checks: list[tuple[str, bool]] = [
        ("OPENAI_API_KEY", bool(settings.openai_api_key)),
        ("GROQ_API_KEY", bool(settings.groq_api_key)),
        ("JSEARCH_API_KEY", bool(settings.jsearch_api_key)),
        ("ADZUNA_APP_ID", bool(settings.adzuna_app_id and settings.adzuna_api_key)),
        ("JOOBLE_API_KEY", bool(settings.jooble_api_key)),
    ]
    return [name for name, present in checks if not present]


def warn_missing_keys(prefix: str = "JobHunter") -> None:
    """Log a single, clear warning when required API keys are absent."""
    missing = missing_api_keys()
    if not missing:
        return
    logger.warning(
        "%s: no key configured for %s. AI query generation and some job "
        "sources are disabled; only keyword matching and scraping will run.",
        prefix, ", ".join(missing),
    )
