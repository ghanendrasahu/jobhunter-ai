"""Normalized job representation shared across search sources, matching, and history.

Every job — whether scraped from a portal, fetched from a third-party API, or
built from a portal search link — is normalized into a single :class:`Job`
value. ``Job.to_dict()`` / ``Job.from_dict()`` round-trip through the plain-dict
shape the rest of the app (history, matching, UI components) already consumes.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

# Seniority taxonomy (PHASE 5 eligibility relies on these canonical values).
SENIORITY_LEVELS: tuple[str, ...] = (
    "FRESHER",
    "ENTRY_LEVEL",
    "JUNIOR",
    "ASSOCIATE",
    "MID_LEVEL",
    "SENIOR",
    "LEAD",
    "STAFF",
    "PRINCIPAL",
    "MANAGER",
    "DIRECTOR",
    "UNKNOWN",
)


def _normalise(text: str) -> str:
    """Lowercase and strip punctuation/whitespace for stable fingerprinting."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


@dataclass(slots=True)
class Job:
    """Canonical representation of a job listing."""

    title: str = ""
    company: str = ""
    location: str = ""
    remote_mode: str = ""
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str | None = None
    experience_years_min: int | None = None
    seniority: str = "UNKNOWN"
    description: str = ""
    description_truncated: bool = False
    url: str = ""
    application_url: str = ""
    source: str = ""
    source_job_id: str = ""
    posted_date: str = ""
    posted_days: int | None = None
    extracted_skills: list[str] = field(default_factory=list)
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    is_portal_link: bool = False
    discovery_only: bool = False
    badge_color: str = ""
    icon: str = ""

    @property
    def id(self) -> str:
        """Stable, source-scoped identifier (deduped history uses this)."""
        if self.source_job_id:
            return f"{self.source}-{self.source_job_id}"
        url = self.url or self.application_url
        digest = (
            hashlib.md5(url.encode()).hexdigest()[:12]
            if url
            else hashlib.md5(f"{self.source}|{self.title}|{self.company}".encode()).hexdigest()[:12]
        )
        return f"{self.source or 'job'}-{digest}"

    def to_dict(self) -> dict[str, Any]:
        """Return the plain-dict form consumed by matching/history/UI code."""
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "remote_mode": self.remote_mode,
            "salary_min": self.salary_min,
            "salary_max": self.salary_max,
            "salary_currency": self.salary_currency,
            "experience_years_min": self.experience_years_min,
            "seniority": self.seniority,
            "description": self.description,
            "description_truncated": self.description_truncated,
            "url": self.url,
            "application_url": self.application_url,
            "source": self.source,
            "source_job_id": self.source_job_id,
            "posted_date": self.posted_date,
            "posted_days": self.posted_days,
            "extracted_skills": list(self.extracted_skills),
            "required_skills": list(self.required_skills),
            "preferred_skills": list(self.preferred_skills),
            "is_portal_link": self.is_portal_link,
            "discovery_only": self.discovery_only,
            "badge_color": self.badge_color,
            "icon": self.icon,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        """Build a :class:`Job` from a legacy job dict (or another Job's dict).

        Unknown keys are ignored, so scraper/API dicts with extra or missing
        fields keep working unchanged.
        """
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in known})

    @property
    def fingerprint(self) -> str:
        """Normalised ``company|title|location`` identity used for dedupe.

        Location aliases ("Bangalore" vs "Bengaluru") and remote-mode spellings
        ("WFH" vs "Remote") are canonicalized first so the same posting found by
        different sources collapses to one identity.
        """
        from jobhunter.domains.search.normalize import normalize_location, normalize_title

        identity = (
            f"{_normalise(self.company)}|"
            f"{_normalise(normalize_title(self.title))}|"
            f"{_normalise(normalize_location(self.location))}"
        )
        return hashlib.md5(identity.encode()).hexdigest()[:12]


def dedupe_jobs(jobs: list[Job]) -> list[Job]:
    """Dedupe jobs by URL or ``company|title|location`` fingerprint.

    URLs are compared on their normalized (tracking-stripped) form, so a posting
    surfaced by two sources with different tracking parameters collapses to one.
    Portal-search links always carry a distinct URL and are never merged with
    scraped listings (their URLs never collide with a real listing).
    """
    from jobhunter.domains.search.normalize import url_dedupe_key

    seen: set[str] = set()
    unique: list[Job] = []
    for job in jobs:
        url_key = hashlib.md5(url_dedupe_key(job.url).encode()).hexdigest()[:12] if job.url else ""
        keys = {job.fingerprint}
        if url_key:
            keys.add(url_key)
        if keys & seen:
            continue
        seen.update(keys)
        unique.append(job)
    return unique
