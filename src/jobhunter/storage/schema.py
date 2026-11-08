"""Shared SQLite schema, versioning and corruption recovery for history.db.

All storage modules open the database through :func:`connect_with_recovery`.
That guarantees:

- **One canonical schema** — every table the app needs is created by
  ``CREATE TABLE IF NOT EXISTS`` regardless of which module connects first.
- **A schema version** — ``PRAGMA user_version`` records the current schema
  version (:data:`SCHEMA_VERSION`) so future migrations have a baseline.
  Existing databases (no version pragma) are treated as version 1 and upgraded
  idempotently by the ``IF NOT EXISTS`` creation statements.
- **Corruption recovery** — if the database file is not a readable SQLite
  database, it is moved aside to ``<name>.corrupt-<timestamp>`` (never deleted)
  and a fresh database is created, so the app starts cleanly instead of
  crashing on every launch.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

#: Current schema version. Bump when adding a migration step in ``apply_schema``.
SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    modified_at TEXT NOT NULL,
    text_preview TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS histories (
    resume_id TEXT PRIMARY KEY,
    applied_job_ids TEXT NOT NULL DEFAULT '[]',
    applied_jobs TEXT NOT NULL DEFAULT '[]',
    last_updated TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS qa_answers (
    intent TEXT PRIMARY KEY,
    answer TEXT NOT NULL,
    source TEXT NOT NULL,
    confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    origin TEXT NOT NULL DEFAULT '',
    resume_id TEXT NOT NULL DEFAULT '',
    query TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT '',
    portals TEXT NOT NULL DEFAULT '[]',
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'running',
    summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_events_run_id ON run_events (run_id);
CREATE TABLE IF NOT EXISTS run_source_metrics (
    run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    found INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, source)
);
CREATE TABLE IF NOT EXISTS submission_attempts (
    resume_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    attempted_at TEXT NOT NULL,
    PRIMARY KEY (resume_id, job_id)
);
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create/upgrade the schema idempotently and record the version."""
    conn.executescript(_SCHEMA)
    row = conn.execute("PRAGMA user_version").fetchone()
    current = int(row[0]) if row else 0
    if current > SCHEMA_VERSION:
        logger.warning(
            "Database schema version %d is newer than this build (%d) — leaving it untouched.",
            current,
            SCHEMA_VERSION,
        )
        return
    # v1 -> v2 introduced the runs tables; they are created by the IF NOT EXISTS
    # statements above, so upgrading only needs the version bump.
    if current < 1:
        logger.info("Initializing JobHunter database schema (v%d)", SCHEMA_VERSION)
    elif current < 2:
        logger.info("Upgrading JobHunter database schema v1 -> v%d", SCHEMA_VERSION)
    with conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def connect_with_recovery(db_path: Path) -> sqlite3.Connection:
    """Open (creating/upgrading when needed) the database, recovering from corruption.

    Raises nothing for unreadable database files — the corrupt file is moved
    aside and a fresh database is returned instead.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    def _open() -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            apply_schema(conn)
        except sqlite3.DatabaseError:
            conn.close()
            raise
        return conn

    try:
        return _open()
    except sqlite3.DatabaseError:
        logger.error("Database %s is not readable — moving it aside and reinitializing.", db_path)
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup = db_path.with_name(f"{db_path.name}.corrupt-{stamp}")
        try:
            db_path.rename(backup)
        except OSError:
            logger.exception("Could not move corrupt database aside; giving up")
            raise
        return _open()


def schema_version(db_path: Path) -> int:
    """Return the stored schema version (0 when the file does not exist)."""
    db_path = Path(db_path)
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("PRAGMA user_version").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()
