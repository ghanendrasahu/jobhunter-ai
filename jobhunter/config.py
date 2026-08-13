"""Application configuration loaded from environment variables and a `.env` file."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

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
    # Seconds to wait for a manual login in the opened browser window.
    manual_login_timeout: int = 180
    # Only consider fresher/entry-level roles (filters out senior listings).
    fresher_only: bool = True
    # Jobs requiring more than this many years of experience are skipped.
    max_experience_years: int = 2
    # Extra details injected into application forms (e.g. expected salary, notice period)
    application_notes: str = ""

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
    """Return the process-wide settings singleton."""
    return Settings()
