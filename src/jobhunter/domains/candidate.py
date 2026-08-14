"""Structured candidate knowledge base.

Captures everything known about the candidate from the resume, the profile
questionnaire, and (optionally) LLM extraction — as a value object downstream
phases (Q&A memory, eligibility, ranking) can rely on. The guiding rule is
"never fabricate": a field the source material doesn't mention stays empty /
``UNKNOWN`` and is simply absent from :attr:`Candidate.known_fields`, so later
stages can route it back to the user instead of guessing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from jobhunter.domains.jobs import SENIORITY_LEVELS

UNKNOWN_SENIORITY = SENIORITY_LEVELS[-1]  # "UNKNOWN"


@dataclass(slots=True)
class Education:
    """A single education entry (degree, institution, completion year)."""

    degree: str = ""
    institution: str = ""
    year: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Education:
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass(slots=True)
class WorkExperience:
    """A single work-experience entry."""

    title: str = ""
    company: str = ""
    duration: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkExperience:
        known = cls.__dataclass_fields__
        return cls(**{key: value for key, value in data.items() if key in known})


@dataclass(slots=True)
class Candidate:
    """Everything the system knows about the candidate.

    Empty/``None`` fields mean the value is unknown (never guessed). Use
    :meth:`known` / :attr:`known_fields` to distinguish "known" from "missing".
    """

    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    remote_mode: str = ""
    current_title: str = ""
    role_family: str = ""
    seniority: str = UNKNOWN_SENIORITY
    experience_years: int | None = None
    skills: list[str] = field(default_factory=list)
    skill_groups: dict[str, list[str]] = field(default_factory=dict)
    education: list[Education] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    work_experience: list[WorkExperience] = field(default_factory=list)
    current_ctc: str = ""
    expected_ctc: str = ""
    notice_period: str = ""
    linkedin: str = ""

    @property
    def known_fields(self) -> set[str]:
        """Names of fields with an actual (non-empty) value."""
        known = set()
        checks: list[tuple[str, object]] = [
            ("full_name", self.full_name),
            ("email", self.email),
            ("phone", self.phone),
            ("location", self.location),
            ("remote_mode", self.remote_mode),
            ("current_title", self.current_title),
            ("role_family", self.role_family),
            ("seniority", self.seniority),
            ("experience_years", self.experience_years),
            ("skills", self.skills),
            ("education", self.education),
            ("projects", self.projects),
            ("certifications", self.certifications),
            ("work_experience", self.work_experience),
            ("current_ctc", self.current_ctc),
            ("expected_ctc", self.expected_ctc),
            ("notice_period", self.notice_period),
            ("linkedin", self.linkedin),
        ]
        for field_name, value in checks:
            if field_name == "seniority":
                if value != UNKNOWN_SENIORITY:
                    known.add(field_name)
            elif field_name == "experience_years":
                if value is not None:
                    known.add(field_name)
            elif isinstance(value, list):
                if value:
                    known.add(field_name)
            elif value:
                known.add(field_name)
        return known

    def known(self, field_name: str) -> bool:
        """True when ``field_name`` carries an actual value for this candidate."""
        return field_name in self.known_fields

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict (education/work entries included)."""
        return {
            "full_name": self.full_name,
            "email": self.email,
            "phone": self.phone,
            "location": self.location,
            "remote_mode": self.remote_mode,
            "current_title": self.current_title,
            "role_family": self.role_family,
            "seniority": self.seniority,
            "experience_years": self.experience_years,
            "skills": list(self.skills),
            "skill_groups": {key: list(values) for key, values in self.skill_groups.items()},
            "education": [entry.to_dict() for entry in self.education],
            "projects": list(self.projects),
            "certifications": list(self.certifications),
            "achievements": list(self.achievements),
            "work_experience": [entry.to_dict() for entry in self.work_experience],
            "current_ctc": self.current_ctc,
            "expected_ctc": self.expected_ctc,
            "notice_period": self.notice_period,
            "linkedin": self.linkedin,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Candidate:
        """Rebuild a Candidate from :meth:`to_dict` output (or a partial dict)."""
        candidate = cls(
            full_name=str(data.get("full_name") or ""),
            email=str(data.get("email") or ""),
            phone=str(data.get("phone") or ""),
            location=str(data.get("location") or ""),
            remote_mode=str(data.get("remote_mode") or ""),
            current_title=str(data.get("current_title") or ""),
            role_family=str(data.get("role_family") or ""),
            seniority=str(data.get("seniority") or UNKNOWN_SENIORITY),
            experience_years=_coerce_int(data.get("experience_years")),
            skills=[str(s) for s in data.get("skills") or []],
            skill_groups={
                str(key): [str(s) for s in values]
                for key, values in (data.get("skill_groups") or {}).items()
            },
            education=_coerce_education(data.get("education")),
            projects=[str(p) for p in data.get("projects") or []],
            certifications=[str(c) for c in data.get("certifications") or []],
            achievements=[str(a) for a in data.get("achievements") or []],
            work_experience=_coerce_work(data.get("work_experience")),
            current_ctc=str(data.get("current_ctc") or ""),
            expected_ctc=str(data.get("expected_ctc") or ""),
            notice_period=str(data.get("notice_period") or ""),
            linkedin=str(data.get("linkedin") or ""),
        )
        if candidate.seniority not in SENIORITY_LEVELS:
            candidate.seniority = UNKNOWN_SENIORITY
        return candidate


def seniority_for_years(years: int | None) -> str:
    """Map years of experience to a canonical seniority bucket (see SENIORITY_LEVELS)."""
    if years is None:
        return UNKNOWN_SENIORITY
    if years < 1:
        return "FRESHER"
    if years <= 2:
        return "ENTRY_LEVEL"
    if years <= 4:
        return "JUNIOR"
    if years <= 8:
        return "MID_LEVEL"
    return "SENIOR"


def _coerce_int(value: object) -> int | None:
    """Coerce a JSON value to a positive int, or None (unknown)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, (str, float)):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
    else:
        return None
    return number if number >= 0 else None


def _coerce_education(value: object) -> list[Education]:
    """Normalize a raw education value (list of dicts, list of strings, or a single string)."""
    if not value:
        return []
    if isinstance(value, str):
        return [Education(degree=value)]
    if not isinstance(value, list):
        return []
    entries: list[Education] = []
    for item in value:
        if not item:
            continue
        entries.append(Education.from_dict(item) if isinstance(item, dict) else Education(degree=str(item)))
    return entries


def _coerce_work(value: object) -> list[WorkExperience]:
    """Normalize a raw work-experience value (list of dicts or strings)."""
    if not value or not isinstance(value, list):
        return []
    entries: list[WorkExperience] = []
    for item in value:
        if not item:
            continue
        entries.append(
            WorkExperience.from_dict(item) if isinstance(item, dict) else WorkExperience(title=str(item))
        )
    return entries
