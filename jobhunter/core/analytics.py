"""Dashboard analytics derived from stored application history."""

from __future__ import annotations

from collections import Counter
from typing import Dict

from jobhunter.core.history import list_all_histories, list_resumes


def get_analytics_data() -> Dict:
    """Aggregate application history into chart-ready summaries."""
    histories = list_all_histories()
    resumes = list_resumes()

    source_counts: Dict[str, int] = {}
    daily_counts: Dict[str, int] = {}
    company_counts: Counter = Counter()

    for history in histories:
        for job in history.get("applied_jobs", []):
            source_counts[job.get("source", "unknown")] = source_counts.get(job.get("source", "unknown"), 0) + 1

            applied_at = (job.get("applied_at", "") or "")[:10]
            if applied_at:
                daily_counts[applied_at] = daily_counts.get(applied_at, 0) + 1

            company_counts[job.get("company", "Unknown")] += 1

    unique_jobs = {
        job.get("url")
        for history in histories
        for job in history.get("applied_jobs", [])
        if job.get("url")
    }

    return {
        "total_applied": sum(len(h.get("applied_job_ids", [])) for h in histories),
        "total_resumes": len(resumes),
        "source_counts": dict(sorted(source_counts.items(), key=lambda x: -x[1])),
        "daily_counts": dict(sorted(daily_counts.items())),
        "top_companies": dict(company_counts.most_common(10)),
        "unique_jobs": len(unique_jobs),
    }
