"""Persistent Q&A memory (SQLite-backed).

Stores the candidate's confirmed answers to application-form questions, keyed
by a canonical intent from :mod:`jobhunter.domains.qa_catalog`. Answers survive
across runs so a question asked by many portals is only answered once. The
``source`` field records how the answer was obtained (``user`` = explicitly
confirmed by the candidate).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
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
            "CREATE TABLE IF NOT EXISTS qa_answers ("
            " intent TEXT PRIMARY KEY,"
            " answer TEXT NOT NULL,"
            " source TEXT NOT NULL,"
            " confirmed_at TEXT NOT NULL"
            ")"
        )
    return conn


def save_answer(intent: str, answer: str, source: str = "user") -> None:
    """Upsert the candidate's answer for ``intent`` (empty answer deletes it)."""
    conn = _connect()
    try:
        with conn:
            if not answer:
                conn.execute("DELETE FROM qa_answers WHERE intent = ?", (intent,))
                return
            conn.execute(
                "INSERT INTO qa_answers (intent, answer, source, confirmed_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(intent) DO UPDATE SET answer=excluded.answer, source=excluded.source, "
                "confirmed_at=excluded.confirmed_at",
                (intent, answer, source, datetime.now().isoformat()),
            )
    finally:
        conn.close()


def load_answer(intent: str) -> dict | None:
    """Return ``{intent, answer, source, confirmed_at}`` for ``intent``, or None."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT intent, answer, source, confirmed_at FROM qa_answers WHERE intent = ?",
            (intent,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "intent": row["intent"],
        "answer": row["answer"],
        "source": row["source"],
        "confirmed_at": row["confirmed_at"],
    }


def load_all_answers() -> list[dict]:
    """Return every stored Q&A answer."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT intent, answer, source, confirmed_at FROM qa_answers").fetchall()
    finally:
        conn.close()
    return [
        {"intent": row["intent"], "answer": row["answer"], "source": row["source"], "confirmed_at": row["confirmed_at"]}
        for row in rows
    ]


def delete_answer(intent: str) -> None:
    """Remove the stored answer for ``intent``."""
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM qa_answers WHERE intent = ?", (intent,))
    finally:
        conn.close()


def clear_answers() -> None:
    """Delete every stored Q&A answer."""
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM qa_answers")
    finally:
        conn.close()
