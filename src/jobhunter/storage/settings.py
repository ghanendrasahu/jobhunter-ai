"""Persistent user settings (SQLite-backed).

Overrides for env-driven configuration that the user can edit from the
dashboard. Env/.env remains the base configuration; explicitly saved settings
are layered on top so credentials and preferences survive without editing files.

Data lives in the same SQLite database as application history, in a ``settings``
table of ``key -> value`` pairs. Sensitive values (portal/application passwords,
mail credentials) are encrypted at rest with Fernet when ``JOBHUNTER_APP_SECRET``
is configured; values are marked with an ``enc:v1:`` prefix so plaintext values
written before the secret existed keep loading transparently and are
re-encrypted the next time they are saved.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from jobhunter.config import get_settings

HISTORY_DIR: Path = get_settings().history_dir

logger = logging.getLogger(__name__)

# Marker prefix identifying Fernet-encrypted persisted values.
_ENCRYPTION_PREFIX = "enc:v1:"

# Values encrypted at rest when a master secret is configured.
SENSITIVE_SETTING_KEYS: frozenset[str] = frozenset(
    {
        "naukri_password",
        "indeed_password",
        "smtp_pass",
    }
)


def _db_path() -> Path:
    return Path(HISTORY_DIR) / "history.db"


def _connect() -> sqlite3.Connection:
    """Open a connection and ensure the settings table exists."""
    Path(HISTORY_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings ("
            " key TEXT PRIMARY KEY,"
            " value TEXT NOT NULL"
            ")"
        )
    return conn


def _fernet() -> Fernet | None:
    """Fernet instance derived from the master secret, or None when unset.

    The secret itself is never stored: a stable key is derived from it
    (SHA-256) so the same secret reliably decrypts old data.
    """
    secret = get_settings().jobhunter_app_secret.get_secret_value()
    if not secret:
        return None
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt_value(value: str) -> str:
    """Encrypt ``value`` when a master secret is set, else return it unchanged."""
    fernet = _fernet()
    if fernet is None:
        return value
    return _ENCRYPTION_PREFIX + fernet.encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_value(value: str) -> str:
    """Decrypt a marked value; plaintext values pass through unchanged.

    Unreadable values (wrong/lost secret, tampering) return an empty string
    instead of raising so a bad secret cannot break configuration loading.
    """
    if not value.startswith(_ENCRYPTION_PREFIX):
        return value
    fernet = _fernet()
    if fernet is None:
        logger.warning(
            "Setting is stored encrypted but JOBHUNTER_APP_SECRET is not set; "
            "value ignored (re-save it with the secret configured)."
        )
        return ""
    try:
        return fernet.decrypt(value.removeprefix(_ENCRYPTION_PREFIX).encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.error(
            "Could not decrypt a stored setting (wrong or rotated "
            "JOBHUNTER_APP_SECRET?); value ignored."
        )
        return ""


def load_settings() -> dict[str, str]:
    """Return all persisted settings as ``{key: value}`` (decrypted)."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: _decrypt_value(row["value"]) for row in rows}
    finally:
        conn.close()


def save_setting(key: str, value: str) -> None:
    """Persist a single setting (empty value removes the key)."""
    conn = _connect()
    try:
        with conn:
            if value:
                stored = _encrypt_value(value) if key in SENSITIVE_SETTING_KEYS else value
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, stored),
                )
            else:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    finally:
        conn.close()


def save_settings(overrides: dict[str, str]) -> None:
    """Persist multiple settings atomically."""
    conn = _connect()
    try:
        with conn:
            for key, value in overrides.items():
                if value:
                    stored = _encrypt_value(value) if key in SENSITIVE_SETTING_KEYS else value
                    conn.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, stored),
                    )
                else:
                    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    finally:
        conn.close()
