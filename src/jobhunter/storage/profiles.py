"""Persistent candidate profile + suggested roles (SQLite-backed).

The pre-flight questionnaire saves the confirmed profile (name, email, phone,
CTC, notice period, ...) plus the selected priority roles so the apply agent
doesn't re-ask on every run. Stored in the same database as settings/history.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jobhunter.config import get_settings

HISTORY_DIR: Path = get_settings().history_dir


def _db_path() -> Path:
    return Path(HISTORY_DIR) / "history.db"


def _connect() -> sqlite3.Connection:
    Path(HISTORY_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    with conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS profile_store ("
            " key TEXT PRIMARY KEY,"
            " value TEXT NOT NULL"
            ")"
        )
    return conn


def save_profile(profile: dict) -> None:
    """Persist the confirmed candidate profile (empty dict clears it)."""
    _save("profile", profile)


def load_profile() -> dict:
    """Return the last confirmed profile, or {}."""
    return _load("profile") or {}


def save_candidate_knowledge(knowledge: dict) -> None:
    """Persist the candidate knowledge base (empty dict clears it)."""
    _save("candidate_knowledge", knowledge)


def load_candidate_knowledge() -> dict:
    """Return the last built candidate knowledge base, or {}."""
    value = _load("candidate_knowledge")
    return value if isinstance(value, dict) else {}


def save_selected_roles(roles: list[str]) -> None:
    """Persist the user's chosen search roles (titles)."""
    _save("selected_roles", roles or [])


def load_selected_roles() -> list[str]:
    """Return the last chosen roles, or []."""
    value = _load("selected_roles")
    return value if isinstance(value, list) else []


def save_suggested_roles(roles: list[dict]) -> None:
    """Persist the suggested role list (title/tier/score dicts)."""
    _save("suggested_roles", roles or [])


def load_suggested_roles() -> list[dict]:
    """Return the last suggested roles, or []."""
    value = _load("suggested_roles")
    return value if isinstance(value, list) else []


def _save(key: str, value: object) -> None:
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO profile_store (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value)),
            )
    finally:
        conn.close()


def _load(key: str):
    conn = _connect()
    try:
        row = conn.execute("SELECT value FROM profile_store WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError):
        return None
