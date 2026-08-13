"""Resume storage, application history, and CSV export (SQLite-backed).

Data lives in a single SQLite database (``history/history.db``) with two tables:
``resumes`` (uploaded PDFs + metadata) and ``histories`` (per-resume applied
jobs). Legacy ``*.json`` files from earlier versions are migrated automatically
on first access so no existing data is lost.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import shutil
import sqlite3
import webbrowser
from datetime import datetime
from pathlib import Path

from jobhunter.config import get_settings

logger = logging.getLogger(__name__)

# Module-level dirs (resolved once; tests may monkeypatch these globals).
HISTORY_DIR: Path = get_settings().history_dir
RESUMES_DIR: Path = get_settings().resumes_dir


# ---------------------------------------------------------------------------
# Database plumbing
# ---------------------------------------------------------------------------
def _db_path() -> Path:
    return Path(HISTORY_DIR) / "history.db"


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
"""


def _connect() -> sqlite3.Connection:
    """Open a connection, ensure the schema exists, and migrate legacy JSON."""
    Path(HISTORY_DIR).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_db_path()))
    conn.row_factory = sqlite3.Row
    with conn:
        conn.executescript(_SCHEMA)
    _migrate_legacy_json(conn)
    return conn


def _migrate_legacy_json(conn: sqlite3.Connection) -> None:
    """Import ``*.json`` files from earlier versions when the DB is empty.

    Runs only once per database (guarded by row-count checks) and is a no-op
    when no legacy files exist, keeping it cheap on every connect.
    """
    if conn.execute("SELECT COUNT(*) FROM histories").fetchone()[0] > 0:
        return
    if conn.execute("SELECT COUNT(*) FROM resumes").fetchone()[0] > 0:
        return

    migrated_history = False
    for path in sorted(Path(HISTORY_DIR).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.debug("Skipping malformed history file: %s", path)
            continue
        if "resume_id" not in data:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO histories (resume_id, applied_job_ids, applied_jobs, last_updated) "
            "VALUES (?, ?, ?, ?)",
            (
                data.get("resume_id", path.stem),
                json.dumps(data.get("applied_job_ids", [])),
                json.dumps(data.get("applied_jobs", [])),
                data.get("last_updated", ""),
            ),
        )
        migrated_history = True

    for path in sorted(Path(RESUMES_DIR).glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.debug("Skipping malformed resume metadata: %s", path)
            continue
        if "id" not in data:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO resumes (id, name, file_path, created_at, modified_at, text_preview) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                data["id"],
                data.get("name", path.stem),
                data.get("file_path", ""),
                data.get("created_at", ""),
                data.get("modified_at", ""),
                data.get("text", "")[:500],
            ),
        )

    if migrated_history:
        conn.commit()
        logger.info("Migrated legacy JSON application history into %s", _db_path())


# ---------------------------------------------------------------------------
# Resume identifiers
# ---------------------------------------------------------------------------
def resume_id_from_text(resume_text: str) -> str:
    """Return a stable short id derived from the resume text."""
    return hashlib.sha256(resume_text.encode("utf-8")).hexdigest()[:12]


_resume_id = resume_id_from_text  # backward-compatible alias


# ---------------------------------------------------------------------------
# Resume management
# ---------------------------------------------------------------------------
def save_resume(file_path: str, name: str = "") -> dict:
    """Copy a PDF into the resumes directory and persist its metadata."""
    from jobhunter.domains.resume import extract_text_from_pdf

    text = extract_text_from_pdf(file_path)
    rid = resume_id_from_text(text)
    if not name:
        name = Path(file_path).stem

    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    dest = RESUMES_DIR / f"{rid}.pdf"
    shutil.copy2(file_path, dest)

    now = datetime.now().isoformat()
    metadata = {
        "id": rid,
        "name": name,
        "file_path": str(dest),
        "created_at": now,
        "modified_at": now,
        "text": text[:500],  # preview only
        "applied_count": len(get_history_by_resume_id(rid).get("applied_job_ids", [])),
    }

    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO resumes (id, name, file_path, created_at, modified_at, text_preview) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "name=excluded.name, file_path=excluded.file_path, modified_at=excluded.modified_at",
                (rid, name, str(dest), now, now, text[:500]),
            )
    finally:
        conn.close()

    logger.info("Saved resume: %s (%s)", name, rid)
    return metadata


def list_resumes() -> list[dict]:
    """Return metadata for every saved resume, with up-to-date applied counts."""
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM resumes ORDER BY created_at DESC").fetchall()
    finally:
        conn.close()

    resumes: list[dict] = []
    for row in rows:
        resumes.append({
            "id": row["id"],
            "name": row["name"],
            "file_path": row["file_path"],
            "created_at": row["created_at"],
            "modified_at": row["modified_at"],
            "text": row["text_preview"],
            "applied_count": len(get_history_by_resume_id(row["id"]).get("applied_job_ids", [])),
        })
    return resumes


def delete_resume(resume_id: str) -> None:
    """Delete a saved resume and its application history."""
    for ext in (".json", ".pdf"):
        path = Path(RESUMES_DIR) / f"{resume_id}{ext}"
        if path.exists():
            path.unlink()
    legacy_history = Path(HISTORY_DIR) / f"{resume_id}.json"
    if legacy_history.exists():
        legacy_history.unlink()

    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM resumes WHERE id = ?", (resume_id,))
            conn.execute("DELETE FROM histories WHERE resume_id = ?", (resume_id,))
    finally:
        conn.close()
    logger.info("Deleted resume: %s", resume_id)


# ---------------------------------------------------------------------------
# Application history
# ---------------------------------------------------------------------------
def load_history(resume_id: str) -> dict:
    """Load the raw history dict for a resume id (empty history if absent)."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT resume_id, applied_job_ids, applied_jobs, last_updated "
            "FROM histories WHERE resume_id = ?",
            (resume_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is not None:
        try:
            return {
                "resume_id": row["resume_id"],
                "applied_job_ids": json.loads(row["applied_job_ids"] or "[]"),
                "applied_jobs": json.loads(row["applied_jobs"] or "[]"),
                "last_updated": row["last_updated"],
            }
        except json.JSONDecodeError:
            logger.debug("Skipping malformed history for %s", resume_id)
    return {"resume_id": resume_id, "applied_job_ids": [], "applied_jobs": []}


def save_history(resume_id: str, job_ids: set[str], job_details: list[dict]) -> None:
    """Persist a resume's applied-job ids and details."""
    existing = load_history(resume_id)
    existing_ids = set(existing.get("applied_job_ids", []))
    existing_details = existing.get("applied_jobs", [])

    existing_ids.update(job_ids)
    seen_urls = {job.get("url", "") for job in existing_details}
    for detail in job_details:
        if detail.get("url", "") and detail["url"] not in seen_urls:
            seen_urls.add(detail["url"])
            existing_details.append(detail)

    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO histories (resume_id, applied_job_ids, applied_jobs, last_updated) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(resume_id) DO UPDATE SET "
                "applied_job_ids=excluded.applied_job_ids, "
                "applied_jobs=excluded.applied_jobs, "
                "last_updated=excluded.last_updated",
                (
                    resume_id,
                    json.dumps(sorted(existing_ids)),
                    json.dumps(existing_details),
                    datetime.now().isoformat(),
                ),
            )
    finally:
        conn.close()
    logger.info("Saved %d applied job ids for resume %s", len(existing_ids), resume_id)


def get_history_by_resume_id(resume_id: str) -> dict:
    """Return application history for a resume id."""
    return load_history(resume_id)


def load_applied_jobs(resume_text: str) -> set[str]:
    """Return the set of already-applied job ids for a resume."""
    return set(load_history(resume_id_from_text(resume_text)).get("applied_job_ids", []))


def save_applied_jobs(resume_text: str, job_ids: list[str], job_details: list[dict] | None = None) -> None:
    """Record applied jobs for a resume (deduplicated by url and id)."""
    save_history(resume_id_from_text(resume_text), set(job_ids), job_details or [])


def get_application_history(resume_text: str) -> dict:
    """Return the application history dict for a resume."""
    return get_history_by_resume_id(resume_id_from_text(resume_text))


def list_all_histories() -> list[dict]:
    """Return every stored application history."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT resume_id, applied_job_ids, applied_jobs, last_updated FROM histories").fetchall()
    finally:
        conn.close()

    histories: list[dict] = []
    for row in rows:
        try:
            histories.append({
                "resume_id": row["resume_id"],
                "applied_job_ids": json.loads(row["applied_job_ids"] or "[]"),
                "applied_jobs": json.loads(row["applied_jobs"] or "[]"),
                "last_updated": row["last_updated"],
            })
        except json.JSONDecodeError:
            logger.debug("Skipping malformed history row for %s", row["resume_id"])
    return histories


def clear_all_history() -> None:
    """Delete every stored application history (resumes are kept)."""
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM histories")
    finally:
        conn.close()
    logger.info("Cleared all application history")


def export_history_csv(resume_text: str | None = None) -> str:
    """Serialize application history (one resume or all) to a CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Job ID", "Title", "Company", "Source", "URL", "Applied At", "Status"])

    if resume_text:
        histories = [get_application_history(resume_text)]
    else:
        histories = list_all_histories()

    for history in histories:
        for job in history.get("applied_jobs", []):
            writer.writerow([
                job.get("job_id", ""),
                job.get("title", ""),
                job.get("company", ""),
                job.get("source", ""),
                job.get("url", ""),
                job.get("applied_at", ""),
                "applied",
            ])
        for jid in history.get("applied_job_ids", []):
            if not any(job.get("job_id") == jid for job in history.get("applied_jobs", [])):
                writer.writerow([jid, "", "", "", "", "", "applied"])

    return output.getvalue()


# ---------------------------------------------------------------------------
# Application recording
# ---------------------------------------------------------------------------
def apply_to_job(job: dict, resume_text: str) -> dict:
    """Record an application for a job, skipping ids already applied to.

    Portal search links are opened in the user's browser.
    """
    job_id = job.get("id", "unknown")
    if job_id in load_applied_jobs(resume_text):
        return {
            "job_id": job_id,
            "job_title": job.get("title"),
            "company": job.get("company"),
            "status": "already_applied",
            "detail": "Already applied. Skipped.",
        }

    is_portal = job.get("is_portal_link", False)
    url = job.get("url", "")

    if is_portal and url:
        try:
            webbrowser.open(url)
        except Exception as exc:  # pragma: no cover - browser dependent
            logger.warning("Failed to open browser: %s", exc)

    save_applied_jobs(resume_text, [job_id], [{
        "job_id": job_id,
        "title": job.get("title"),
        "company": job.get("company"),
        "source": job.get("source"),
        "url": url,
        "match_score": job.get("match_score"),
        "applied_at": datetime.now().isoformat(),
    }])

    detail = "🔗 Portal opened in your browser." if is_portal else "Application recorded."
    return {
        "job_id": job_id,
        "job_title": job.get("title"),
        "company": job.get("company"),
        "status": "applied",
        "detail": detail,
        "match_score": job.get("match_score"),
    }
