"""Pure, Streamlit-free helpers behind the dashboard pages.

Keeping these here (rather than inline in the views) makes the UI's logic
unit-testable without rendering Streamlit.
"""

from __future__ import annotations

from typing import Any

from jobhunter.automation.apply_contract import SUPPORTED_APPLY_PORTALS
from jobhunter.domains.search.sources.base import SOURCES, browser_available

NEEDS_REVIEW_STATUSES: tuple[str, ...] = (
    "needs_review",
    "blocked",
    "no_apply_button",
    "handed_off",
    "deferred",
    "failed",
)

_STATUS_LABELS: dict[str, str] = {
    "submitted": "Submitted",
    "applied": "Applied",
    "already_applied": "Already applied",
    "needs_review": "Needs review",
    "handed_off": "Handed off",
    "blocked": "Blocked",
    "failed": "Failed",
    "skipped": "Skipped",
    "deferred": "Deferred",
    "discovery_only": "Discovery only",
    "opened": "Opened",
    "recorded": "Recorded",
    "no_apply_button": "No apply button",
}

_STATUS_CSS: dict[str, str] = {
    "submitted": "applied",
    "applied": "applied",
    "already_applied": "skipped",
    "needs_review": "skipped",
    "handed_off": "skipped",
    "blocked": "failed",
    "failed": "failed",
    "deferred": "skipped",
    "discovery_only": "skipped",
    "no_apply_button": "failed",
}


def status_label(status: str | None) -> str:
    if not status:
        return "Unknown"
    return _STATUS_LABELS.get(status, status.replace("_", " ").title())


def status_css(status: str | None) -> str:
    return _STATUS_CSS.get(status or "", "")


def is_needs_review(status: str | None) -> bool:
    return (status or "") in NEEDS_REVIEW_STATUSES


def summarize_outcomes(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Count run outcomes by status (submission = verification-backed only)."""
    by_status: dict[str, int] = {}
    for item in results:
        key = item.get("status") or "unknown"
        by_status[key] = by_status.get(key, 0) + 1
    submitted = by_status.get("submitted", 0) + by_status.get("applied", 0)
    needs_review = sum(by_status.get(s, 0) for s in NEEDS_REVIEW_STATUSES)
    return {
        "total": len(results),
        "by_status": dict(sorted(by_status.items(), key=lambda kv: -kv[1])),
        "submitted": submitted,
        "needs_review": needs_review,
    }


def needs_review_queue(histories: list[dict[str, Any]], limit: int = 100) -> list[dict[str, Any]]:
    """Applications across all resumes that stopped before/at submission.

    These are the records that must never be read as "applied" — they are
    awaiting the user's manual step or verification.
    """
    queue: list[dict[str, Any]] = []
    for history in histories:
        resume_id = history.get("resume_id", "")
        for job in history.get("applied_jobs", []):
            if not is_needs_review(job.get("status")):
                continue
            queue.append(
                {
                    "resume_id": resume_id,
                    "job_id": job.get("job_id", ""),
                    "title": job.get("title") or "Untitled role",
                    "company": job.get("company") or "Unknown",
                    "source": job.get("source") or "unknown",
                    "url": job.get("url") or "",
                    "status": job.get("status") or "unknown",
                    "detail": job.get("detail") or "",
                    "applied_at": job.get("applied_at") or "",
                }
            )
    queue.sort(key=lambda item: str(item.get("applied_at", "")), reverse=True)
    return queue[:limit]


def source_status_report() -> list[dict[str, Any]]:
    """Registered discovery sources: availability, browser need, apply support."""
    available = browser_available()
    report: list[dict[str, Any]] = []
    for name, source_cls in sorted(SOURCES.items()):
        needs_browser = bool(getattr(source_cls, "requires_browser", False))
        discovery_only = name not in SUPPORTED_APPLY_PORTALS
        report.append(
            {
                "name": name,
                "requires_browser": needs_browser,
                "available": (not needs_browser) or available,
                "discovery_only": discovery_only,
            }
        )
    return report


_PIPELINE_MODE_LABELS = {
    "off": "Review only (never auto-submits from the pipeline)",
    "human": "Pre-fill forms, you submit (recommended)",
    "auto": "Submit automatically when complete (after verification)",
}


def pipeline_apply_mode_label(mode: str | None) -> str:
    return _PIPELINE_MODE_LABELS.get(mode or "", _PIPELINE_MODE_LABELS["off"])


def score_css(score: int | float | None) -> str:
    try:
        value = float(score or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value >= 70:
        return "high"
    if value >= 40:
        return "mid"
    return "low"


def eligibility_line(job: dict[str, Any]) -> str:
    """One-line eligibility summary for a job card."""
    decision = str(job.get("eligibility_decision") or "unreviewed")
    reasons = list(job.get("eligibility_reasons") or [])
    if reasons:
        return f"{decision}: {'; '.join(reasons[:3])}"
    exposed = list(job.get("eligibility_exposed") or [])
    if exposed:
        return f"{decision}: {'; '.join(exposed[:3])}"
    return decision


def application_explanation(job: dict[str, Any]) -> dict[str, Any]:
    """Explainability block for a job: eligibility -> relevance -> decision."""
    return {
        "eligibility": {
            "status": job.get("eligibility_status"),
            "decision": job.get("eligibility_decision"),
            "reasons": list(job.get("eligibility_reasons") or []),
            "exposed": list(job.get("eligibility_exposed") or []),
        },
        "relevance": {
            "score": job.get("match_score"),
            "decision": job.get("relevance_decision"),
            "explanation": job.get("relevance_explanation") or "",
            "components": list(job.get("relevance_components") or []),
        },
    }
