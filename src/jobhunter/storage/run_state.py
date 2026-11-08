"""Persistent run/session state, run events, source metrics, and submission
attempt markers.

Every automated run (LangGraph pipeline or the apply agent) gets a row in
``runs`` plus per-application events in ``run_events``. A run that dies without
finishing (process kill, browser crash, power loss) is later marked
``interrupted`` by :func:`recover_interrupted_runs`, so a restart can see what
was in flight instead of silently re-doing it.

The ``submission_attempts`` table records that a final submit *may* have been
clicked for a job (written just before the click, only in ``auto`` mode).
A crash between the click and the outcome recording leaves the marker behind;
the job is then never auto-attempted again — it is surfaced as ``needs_review``
instead. This is what makes crashes unable to produce duplicate applications.

Everything here is best-effort persistence: failures are logged and swallowed
with safe defaults so observability can never break the pipeline itself.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from jobhunter.config import get_settings

logger = logging.getLogger(__name__)

HISTORY_DIR: Path = get_settings().history_dir

def _db_path() -> Path:
    return Path(HISTORY_DIR) / "history.db"


def _connect() -> sqlite3.Connection:
    from jobhunter.storage.schema import connect_with_recovery

    return connect_with_recovery(_db_path())


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------
def start_run(
    *,
    origin: str,
    resume_id: str = "",
    query: str = "",
    mode: str = "",
    portals: list[str] | None = None,
) -> str:
    """Create a ``running`` run row and return its id (empty string on failure)."""
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO runs (run_id, origin, resume_id, query, mode, portals, started_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 'running')",
                    (
                        run_id,
                        origin,
                        resume_id,
                        query,
                        mode,
                        json.dumps(portals or [], sort_keys=True),
                        datetime.now().isoformat(),
                    ),
                )
        finally:
            conn.close()
        return run_id
    except Exception as exc:
        logger.warning("Failed to record run start: %s", exc)
        return ""


def update_run(run_id: str, **fields) -> None:
    """Update mutable fields of a run (query, resume_id, mode)."""
    if not run_id:
        return
    allowed = {"resume_id", "query", "mode"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    f"UPDATE runs SET {', '.join(f'{k} = ?' for k in updates)} WHERE run_id = ?",
                    (*updates.values(), run_id),
                )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to update run %s: %s", run_id, exc)


def finish_run(run_id: str, status: str, summary: dict | None = None) -> None:
    """Mark a run finished with ``status`` (completed|failed|interrupted)."""
    if not run_id:
        return
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "UPDATE runs SET status = ?, finished_at = ?, summary_json = ? WHERE run_id = ?",
                    (status, datetime.now().isoformat(), json.dumps(summary or {}, sort_keys=True), run_id),
                )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to finish run %s: %s", run_id, exc)


def recover_interrupted_runs() -> int:
    """Mark runs stuck in ``running`` as ``interrupted`` (crash/restart recovery).

    Returns the number of runs recovered. Any application recorded as attempted
    in an interrupted run is protected by the submission-attempt markers.
    """
    try:
        conn = _connect()
        try:
            with conn:
                cursor = conn.execute(
                    "UPDATE runs SET status = 'interrupted', finished_at = ? WHERE status = 'running'",
                    (datetime.now().isoformat(),),
                )
                recovered = cursor.rowcount
        finally:
            conn.close()
        if recovered:
            logger.warning("Recovered %d interrupted run(s) from a previous crash", recovered)
        return recovered
    except Exception as exc:
        logger.warning("Failed to recover interrupted runs: %s", exc)
        return 0


# ---------------------------------------------------------------------------
# Events and metrics
# ---------------------------------------------------------------------------
def record_event(run_id: str, level: str, stage: str, message: str) -> None:
    if not run_id:
        return
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO run_events (run_id, ts, level, stage, message) VALUES (?, ?, ?, ?, ?)",
                    (run_id, datetime.now().isoformat(), level, stage, message[:2000]),
                )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to record run event: %s", exc)


def record_source_metric(
    run_id: str,
    source: str,
    *,
    found: int = 0,
    failed: bool = False,
    duration_ms: int = 0,
) -> None:
    if not run_id:
        return
    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO run_source_metrics (run_id, source, found, failed, duration_ms) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(run_id, source) DO UPDATE SET "
                    "found = found + excluded.found, "
                    "failed = MAX(failed, excluded.failed), "
                    "duration_ms = duration_ms + excluded.duration_ms",
                    (run_id, source, int(found), 1 if failed else 0, int(duration_ms)),
                )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to record source metric for %s: %s", source, exc)


def record_application_event(run_id: str, job: dict, status: str, detail: str) -> None:
    """Log one application outcome as a structured run event."""
    title = job.get("title") or job.get("job_title") or "?"
    company = job.get("company") or "?"
    record_event(
        run_id,
        "info" if status in ("submitted", "applied", "already_applied") else "warning",
        "application",
        f"{status} — {title} @ {company}: {detail[:500]}",
    )


def source_metrics_for_run(run_id: str) -> dict[str, dict]:
    if not run_id:
        return {}
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT source, found, failed, duration_ms FROM run_source_metrics WHERE run_id = ?",
                (run_id,),
            ).fetchall()
        finally:
            conn.close()
        return {
            row["source"]: {
                "found": row["found"],
                "failed": bool(row["failed"]),
                "duration_ms": row["duration_ms"],
            }
            for row in rows
        }
    except Exception as exc:
        logger.warning("Failed to read source metrics for %s: %s", run_id, exc)
        return {}


def events_for_run(run_id: str) -> list[dict]:
    if not run_id:
        return []
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT ts, level, stage, message FROM run_events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("Failed to read events for %s: %s", run_id, exc)
        return []


def get_run(run_id: str) -> dict | None:
    try:
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to read run %s: %s", run_id, exc)
        return None
    if row is None:
        return None
    try:
        portals = json.loads(row["portals"] or "[]")
    except json.JSONDecodeError:
        portals = []
    try:
        summary = json.loads(row["summary_json"] or "{}")
    except json.JSONDecodeError:
        summary = {}
    return {
        "run_id": row["run_id"],
        "origin": row["origin"],
        "resume_id": row["resume_id"],
        "query": row["query"],
        "mode": row["mode"],
        "portals": portals,
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "status": row["status"],
        "summary": summary,
        "source_metrics": source_metrics_for_run(run_id),
    }


def list_runs(limit: int = 50) -> list[dict]:
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT run_id FROM runs ORDER BY started_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to list runs: %s", exc)
        return []
    runs = [get_run(row["run_id"]) for row in rows]
    return [run for run in runs if run is not None]


def build_run_summary(run_id: str) -> dict:
    """Structured run summary: lifecycle, counts by event level, source metrics."""
    run = get_run(run_id) or {}
    events = events_for_run(run_id)
    by_level: dict[str, int] = {}
    for event in events:
        by_level[event["level"]] = by_level.get(event["level"], 0) + 1
    summary = dict(run.get("summary") or {})
    summary.setdefault("applications", {"total": 0, "by_status": {}})
    summary.update(
        {
            "run_id": run_id,
            "status": run.get("status", "unknown"),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "events_by_level": by_level,
            "source_metrics": run.get("source_metrics", {}),
        }
    )
    return summary


# ---------------------------------------------------------------------------
# Submission attempt markers (crash idempotency)
# ---------------------------------------------------------------------------
def mark_submission_attempt(resume_text: str, job: dict) -> None:
    """Record that a final submit may have been clicked for ``job``.

    Written just before the click in ``auto`` mode. Never raises.
    """
    if not resume_text or not job.get("id"):
        return
    from jobhunter.storage.history import resume_id_from_text

    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "INSERT INTO submission_attempts (resume_id, job_id, url, attempted_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(resume_id, job_id) DO UPDATE SET url=excluded.url, attempted_at=excluded.attempted_at",
                    (
                        resume_id_from_text(resume_text),
                        str(job["id"]),
                        str(job.get("url") or ""),
                        datetime.now().isoformat(),
                    ),
                )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to record submission attempt marker: %s", exc)


def has_submission_attempt(resume_text: str, job_id: str) -> bool:
    """True when a previous run may have clicked submit for ``job_id`` already."""
    if not resume_text or not job_id:
        return False
    from jobhunter.storage.history import resume_id_from_text

    try:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT 1 FROM submission_attempts WHERE resume_id = ? AND job_id = ?",
                (resume_id_from_text(resume_text), str(job_id)),
            ).fetchone()
        finally:
            conn.close()
        return row is not None
    except Exception as exc:
        logger.warning("Failed to check submission attempt marker: %s", exc)
        return False


def clear_submission_attempt(resume_text: str, job_id: str) -> None:
    """Drop the marker (used when the outcome is a deterministic failure)."""
    if not resume_text or not job_id:
        return
    from jobhunter.storage.history import resume_id_from_text

    try:
        conn = _connect()
        try:
            with conn:
                conn.execute(
                    "DELETE FROM submission_attempts WHERE resume_id = ? AND job_id = ?",
                    (resume_id_from_text(resume_text), str(job_id)),
                )
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Failed to clear submission attempt marker: %s", exc)


def list_submission_attempts(resume_text: str) -> list[dict]:
    from jobhunter.storage.history import resume_id_from_text

    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT job_id, url, attempted_at FROM submission_attempts WHERE resume_id = ?",
                (resume_id_from_text(resume_text),),
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("Failed to list submission attempts: %s", exc)
        return []


def list_all_submission_attempts() -> list[dict]:
    """Every unverified submission attempt across all resumes."""
    try:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT resume_id, job_id, url, attempted_at FROM submission_attempts "
                "ORDER BY attempted_at DESC"
            ).fetchall()
        finally:
            conn.close()
        return [dict(row) for row in rows]
    except Exception as exc:
        logger.warning("Failed to list submission attempts: %s", exc)
        return []
