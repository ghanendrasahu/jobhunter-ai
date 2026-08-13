"""Job prioritization for the apply agent.

Jobs are ranked so the best fits are applied to first within a cycle:

1. **Recency** — posted today > within 7 days > older.
2. **Fresher fit** — roles needing 0/low years (and fresher/entry-level wording).
3. **Salary** — higher-paying roles rank higher; unknown salary is neutral.
4. **Remote/WFH** — remote-friendly roles rank higher when enabled.
5. **Priority tier** — titles matching Tier-1 roles (AI/ML/Data/Analyst) get a
   bonus so they out-rank equal-recency jobs.

Scores are additive weights; higher is better.
"""

from __future__ import annotations

import re

_REMOTE_WORDS = ("work from home", "remote", "hybrid", "wfh", "telecommute")
_FRESHER_WORDS = ("fresher", "entry level", "0 to 1", "0-1", "graduate", "freshers")
_SALARY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(lpa|lakh|l|k|thousand|₹|\$)", re.IGNORECASE)
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)


def posted_days_ago(job: dict) -> int | None:
    """Return days since the job was posted, or None when unknown.

    Reads best-effort fields extracted by :func:`collect_cards` (``posted_days``,
    ``posted_at`` text) and falls back to parsing the URL slug/description.
    """
    explicit = job.get("posted_days")
    if isinstance(explicit, int) and explicit >= 0:
        return explicit
    raw = str(job.get("posted_at") or job.get("posted") or "")
    if not raw:
        raw = " ".join([str(job.get("url", "")), str(job.get("description", ""))])
    return parse_posted_text(raw)


def parse_posted_text(text: str) -> int | None:
    """Parse 'Just posted'/'Today'/'2 days ago'/'1 week ago' into days."""
    lower = (text or "").lower()
    if any(k in lower for k in ("just posted", "today", "just now", "posted today", "active today")):
        return 0
    if "yesterday" in lower:
        return 1
    for unit, days in (("month", 30), ("week", 7), ("day", 1), ("hour", 0)):
        m = re.search(r"(\d+)\s*" + unit + r"s?\s*ago", lower)
        if m:
            return int(m.group(1)) * days
    return None


def _recency_score(days: int | None) -> int:
    """Posted today = 30, within a week = 20, older = 10, unknown = 15."""
    if days is None:
        return 15
    if days <= 1:
        return 30
    if days <= 7:
        return 20
    return 10


def job_remote(job: dict) -> bool:
    """True when the job title/location/description signals remote or WFH."""
    text = " ".join([
        str(job.get("title", "")), str(job.get("location", "")),
        str(job.get("description", ""))[:500],
    ]).lower()
    return any(word in text for word in _REMOTE_WORDS)


def job_fresher_friendly(job: dict) -> bool:
    """True when the role targets freshers/entry-level candidates."""
    text = " ".join([
        str(job.get("title", "")), str(job.get("description", ""))[:500],
        str(job.get("url", "")),
    ]).lower()
    if any(word in text for word in _FRESHER_WORDS):
        return True
    years = parse_experience_years(text)
    return years is not None and years <= 2


def parse_experience_years(text: str) -> int | None:
    """Return the minimum years of experience a role needs, or None."""
    m = _YEARS_RE.search(text)
    return int(m.group(1)) if m else None


def parse_salary(job: dict) -> float | None:
    """Return the job's annual salary in LPA, or None when unknown.

    Reads ``salary_min``/``salary_max`` fields or scraped ``salary_text`` and
    normalizes monthly figures to annual LPA.
    """
    numbers: list[tuple[float, str]] = []
    for field in ("salary_min", "salary_max"):
        value = job.get(field)
        if isinstance(value, (int, float)) and value:
            numbers.append((float(value), ""))
    raw = str(job.get("salary_text") or "")
    for m in _SALARY_RE.finditer(raw):
        amount = float(m.group(1).replace(",", ""))
        numbers.append((amount, m.group(2).lower()))

    if not numbers:
        return None
    annual: list[float] = []
    for amount, unit in numbers:
        if unit in ("lpa", "lakh", "l"):
            annual.append(amount)
        elif unit == "k":
            annual.append(amount * 1000 / 100000)  # monthly "X k" -> annual LPA
        elif unit == "thousand":
            annual.append(amount / 100)
        elif unit in ("₹", "$"):
            annual.append(amount / 100000)
        else:
            annual.append(amount)  # bare number assumed annual LPA-ish
    return max(annual)


def _salary_score(salary_lpa: float | None) -> int:
    """Higher pay ranks higher; unknown salary is neutral."""
    if salary_lpa is None:
        return 10
    if salary_lpa >= 15:
        return 25
    if salary_lpa >= 8:
        return 20
    if salary_lpa >= 4:
        return 15
    return 10


def priority_score(
    job: dict,
    priority_titles: set[str] | None = None,
    prioritize_remote: bool = True,
) -> int:
    """Compute the apply-priority score for a single job (higher = sooner)."""
    score = _recency_score(posted_days_ago(job))
    score += _salary_score(parse_salary(job))

    if prioritize_remote and job_remote(job):
        score += 12
    if job_fresher_friendly(job):
        score += 15

    priority_titles = priority_titles or set()
    if priority_titles and is_priority_match(job.get("title", ""), priority_titles):
        score += 18
    return score


def is_priority_match(job_title: str, priority_titles: set[str]) -> bool:
    """True when a job title mentions a priority (Tier-1) role title."""
    from jobhunter.automation.roles import is_priority_title

    return is_priority_title(job_title, priority_titles)


def sort_jobs_by_priority(
    jobs: list[dict],
    priority_titles: set[str] | None = None,
    prioritize_remote: bool = True,
) -> list[dict]:
    """Return jobs sorted best-first (priority score descending, stable)."""
    ranked = [
        {**job, "_priority": priority_score(job, priority_titles, prioritize_remote)}
        for job in jobs
    ]
    ranked.sort(key=lambda j: j["_priority"], reverse=True)
    for job in ranked:
        job.pop("_priority", None)
    return ranked
