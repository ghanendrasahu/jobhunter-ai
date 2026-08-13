"""Resume storage, application history, and CSV export."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import shutil
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from jobhunter.config import get_settings

logger = logging.getLogger(__name__)

# Module-level dirs (resolved once; tests may monkeypatch these globals).
HISTORY_DIR: Path = get_settings().history_dir
RESUMES_DIR: Path = get_settings().resumes_dir


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
def save_resume(file_path: str, name: str = "") -> Dict:
    """Copy a PDF into the resumes directory and persist its metadata."""
    from jobhunter.core.pdf import extract_text_from_pdf

    text = extract_text_from_pdf(file_path)
    rid = resume_id_from_text(text)
    if not name:
        name = Path(file_path).stem

    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    dest = RESUMES_DIR / f"{rid}.pdf"
    shutil.copy2(file_path, dest)

    metadata = {
        "id": rid,
        "name": name,
        "file_path": str(dest),
        "created_at": datetime.now().isoformat(),
        "modified_at": datetime.now().isoformat(),
        "text": text[:500],  # preview only
        "applied_count": len(get_history_by_resume_id(rid).get("applied_job_ids", [])),
    }

    meta_path = RESUMES_DIR / f"{rid}.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logger.info("Saved resume: %s (%s)", name, rid)
    return metadata


def list_resumes() -> List[Dict]:
    """Return metadata for every saved resume, with up-to-date applied counts."""
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)
    resumes: List[Dict] = []
    for path in sorted(RESUMES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["applied_count"] = len(get_history_by_resume_id(data["id"]).get("applied_job_ids", []))
            resumes.append(data)
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            logger.debug("Skipping malformed resume metadata: %s", path)
    return resumes


def delete_resume(resume_id: str) -> None:
    """Delete a saved resume and its application history."""
    for ext in (".json", ".pdf"):
        path = RESUMES_DIR / f"{resume_id}{ext}"
        if path.exists():
            path.unlink()
    history_path = HISTORY_DIR / f"{resume_id}.json"
    if history_path.exists():
        history_path.unlink()
    logger.info("Deleted resume: %s", resume_id)


# ---------------------------------------------------------------------------
# Application history
# ---------------------------------------------------------------------------
def _history_path(resume_id: str) -> Path:
    return HISTORY_DIR / f"{resume_id}.json"


def load_history(resume_id: str) -> Dict:
    """Load the raw history dict for a resume id (empty history if absent)."""
    path = _history_path(resume_id)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            logger.debug("Skipping malformed history: %s", path)
    return {"resume_id": resume_id, "applied_job_ids": [], "applied_jobs": []}


def save_history(resume_id: str, job_ids: Set[str], job_details: List[Dict]) -> None:
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

    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    _history_path(resume_id).write_text(
        json.dumps(
            {
                "resume_id": resume_id,
                "applied_job_ids": sorted(existing_ids),
                "applied_jobs": existing_details,
                "last_updated": datetime.now().isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Saved %d applied job ids for resume %s", len(existing_ids), resume_id)


def get_history_by_resume_id(resume_id: str) -> Dict:
    """Return application history for a resume id."""
    return load_history(resume_id)


def load_applied_jobs(resume_text: str) -> Set[str]:
    """Return the set of already-applied job ids for a resume."""
    return set(load_history(resume_id_from_text(resume_text)).get("applied_job_ids", []))


def save_applied_jobs(resume_text: str, job_ids: List[str], job_details: Optional[List[Dict]] = None) -> None:
    """Record applied jobs for a resume (deduplicated by url and id)."""
    save_history(resume_id_from_text(resume_text), set(job_ids), job_details or [])


def get_application_history(resume_text: str) -> Dict:
    """Return the application history dict for a resume."""
    return get_history_by_resume_id(resume_id_from_text(resume_text))


def list_all_histories() -> List[Dict]:
    """Return every stored application history."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    histories: List[Dict] = []
    for path in HISTORY_DIR.glob("*.json"):
        try:
            histories.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, KeyError):
            logger.debug("Skipping malformed history file: %s", path)
    return histories


def export_history_csv(resume_text: Optional[str] = None) -> str:
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
def apply_to_job(job: Dict, resume_text: str) -> Dict:
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
