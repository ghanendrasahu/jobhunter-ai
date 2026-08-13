"""Persistent user settings (SQLite-backed).

Overrides for env-driven configuration that the user can edit from the
dashboard. Env/.env remains the base configuration; explicitly saved settings
are layered on top so credentials and preferences survive without editing files.

Data lives in the same SQLite database as application history, in a ``settings``
table of ``key -> value`` pairs.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jobhunter.config import get_settings

HISTORY_DIR: Path = get_settings().history_dir


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


def load_settings() -> dict[str, str]:
    """Return all persisted settings as ``{key: value}``."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}
    finally:
        conn.close()


def save_setting(key: str, value: str) -> None:
    """Persist a single setting (empty value removes the key)."""
    conn = _connect()
    try:
        with conn:
            if value:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, value),
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
                    conn.execute(
                        "INSERT INTO settings (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (key, value),
                    )
                else:
                    conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    finally:
        conn.close()
