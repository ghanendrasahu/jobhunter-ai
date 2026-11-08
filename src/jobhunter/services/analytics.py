"""Dashboard analytics derived from stored application history."""

from __future__ import annotations

from collections import Counter
from typing import Any

from jobhunter.storage.history import get_application_history, list_all_histories, list_resumes


def get_analytics_data() -> dict:
    """Aggregate application history into chart-ready summaries."""
    histories = list_all_histories()
    resumes = list_resumes()

    source_counts: dict[str, int] = {}
    daily_counts: dict[str, int] = {}
    company_counts: Counter = Counter()

    for history in histories:
        for job in history.get("applied_jobs", []):
            source_counts[job.get("source", "unknown")] = (
                source_counts.get(job.get("source", "unknown"), 0) + 1
            )

            applied_at = (job.get("applied_at", "") or "")[:10]
            if applied_at:
                daily_counts[applied_at] = daily_counts.get(applied_at, 0) + 1

            company_counts[job.get("company", "Unknown")] += 1

    unique_jobs = {
        job.get("url") for history in histories for job in history.get("applied_jobs", []) if job.get("url")
    }

    return {
        "total_applied": sum(len(h.get("applied_job_ids", [])) for h in histories),
        "total_resumes": len(resumes),
        "source_counts": dict(sorted(source_counts.items(), key=lambda x: -x[1])),
        "daily_counts": dict(sorted(daily_counts.items())),
        "top_companies": dict(company_counts.most_common(10)),
        "unique_jobs": len(unique_jobs),
    }


_SUBMITTED_STATUSES = ("submitted", "applied")


def application_metrics(resume_text: str | None = None) -> dict[str, Any]:
    """Application-level metrics aggregated from recorded history.

    Counts every recorded outcome (submitted, needs_review, failed, skipped, …)
    per status and per source, and reports the verification-backed submission
    rate. Never raises; empty history yields zeros.
    """
    histories = [get_application_history(resume_text)] if resume_text else list_all_histories()

    by_status: Counter = Counter()
    by_source: Counter = Counter()
    total = 0
    submitted = 0
    for history in histories:
        for job in history.get("applied_jobs", []):
            status = job.get("status", "unknown") or "unknown"
            by_status[status] += 1
            by_source[job.get("source", "unknown") or "unknown"] += 1
            total += 1
            if status in _SUBMITTED_STATUSES:
                submitted += 1

    return {
        "total_attempts": total,
        "submitted": submitted,
        "submission_rate": round(submitted / total, 3) if total else 0.0,
        "by_status": dict(by_status.most_common()),
        "by_source": dict(by_source.most_common()),
    }
