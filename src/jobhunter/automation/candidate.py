"""Candidate knowledge extraction and persistence.

Builds a :class:`jobhunter.domains.candidate.Candidate` from the resume,
layering sources by authority: the user-confirmed profile wins, then the LLM
fills gaps the deterministic heuristic could not find. Extraction never guesses:
fields the sources don't mention stay empty and are marked unknown via
``known_fields`` so later phases (Q&A memory, eligibility) can ask the user.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from jobhunter.automation.profile import profile_from_resume
from jobhunter.domains.candidate import UNKNOWN_SENIORITY, Candidate, Education, seniority_for_years
from jobhunter.domains.skills import group_skills, infer_role_family, normalize_skill
from jobhunter.storage.profiles import load_candidate_knowledge, save_candidate_knowledge

logger = logging.getLogger(__name__)

_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)

# Scalar candidate fields filled from profile / LLM.
_STRING_FIELDS = (
    "full_name", "email", "phone", "location", "remote_mode", "current_title",
    "role_family", "current_ctc", "expected_ctc", "notice_period", "linkedin",
)
_LIST_FIELDS = ("projects", "certifications", "achievements")

_PROFILE_MAP: dict[str, str] = {
    "full_name": "full_name",
    "email": "email",
    "phone": "phone",
    "location": "location",
    "current_title": "current_title",
    "current_ctc": "current_ctc",
    "expected_ctc": "expected_ctc",
    "notice_period": "notice_period",
    "linkedin": "linkedin",
}


def extract_candidate(resume_text: str, llm=None, profile: dict | None = None) -> Candidate:
    """Extract candidate knowledge from resume text, layering authoritative sources.

    Order of authority: user-confirmed ``profile`` > LLM extraction > heuristic
    parser. The deterministic :func:`profile_from_resume` runs first so the
    result is fully offline-safe; the LLM only fills fields it left empty.
    """
    text = resume_text or ""
    candidate = Candidate.from_dict(profile_from_resume(text))

    if profile:
        _apply_profile(candidate, profile)

    if llm is not None:
        _fill_gaps(candidate, _extract_with_llm(text, llm))

    _finalize(candidate, text)
    return candidate


def build_candidate(
    resume_text: str,
    llm=None,
    profile: dict | None = None,
    refresh: bool = False,
) -> Candidate:
    """Return persisted candidate knowledge, re-extracting only when needed.

    Uses the saved knowledge base when present (so values survive across runs);
    pass ``refresh=True`` to force re-extraction from the resume. The result is
    always persisted, keeping the store in sync with profile edits.
    """
    if not refresh:
        saved = load_candidate_knowledge()
        if saved:
            candidate = Candidate.from_dict(saved)
            if profile:
                _apply_profile(candidate, profile)
            save_candidate_knowledge(candidate.to_dict())
            return candidate
    candidate = extract_candidate(resume_text, llm=llm, profile=profile)
    save_candidate_knowledge(candidate.to_dict())
    return candidate


# ---------------------------------------------------------------------------
# Source layering
# ---------------------------------------------------------------------------
def _apply_profile(candidate: Candidate, profile: dict) -> None:
    """Overlay user-confirmed profile values (authoritative)."""
    for profile_key, attr in _PROFILE_MAP.items():
        value = profile.get(profile_key)
        if value:
            setattr(candidate, attr, value)

    skills = profile.get("skills")
    if skills:
        candidate.skills = [str(s).strip() for s in skills if str(s).strip()]

    education = profile.get("education")
    if education:
        if isinstance(education, str):
            candidate.education = [Education(degree=education)]
        else:
            candidate.education = [
                Education.from_dict(e) if isinstance(e, dict) else Education(degree=str(e))
                for e in education
                if e
            ]

    years = profile.get("experience_years")
    if years is not None and str(years).strip().lstrip("-").isdigit():
        number = int(years)
        if number > 0:
            candidate.experience_years = number


def _fill_gaps(candidate: Candidate, llm_fields: dict) -> None:
    """Fill empty candidate fields from LLM-extracted fields (never overwrites)."""
    extra = Candidate.from_dict(llm_fields)
    for field_name in _STRING_FIELDS:
        if not getattr(candidate, field_name) and getattr(extra, field_name):
            setattr(candidate, field_name, getattr(extra, field_name))
    if candidate.experience_years is None and extra.experience_years is not None:
        candidate.experience_years = extra.experience_years
    candidate.skills = list(dict.fromkeys(candidate.skills + extra.skills))
    for field_name in _LIST_FIELDS:
        if not getattr(candidate, field_name) and getattr(extra, field_name):
            setattr(candidate, field_name, list(getattr(extra, field_name)))
    if not candidate.education and extra.education:
        candidate.education = list(extra.education)
    if not candidate.work_experience and extra.work_experience:
        candidate.work_experience = list(extra.work_experience)


# ---------------------------------------------------------------------------
# Deterministic finalization
# ---------------------------------------------------------------------------
def _finalize(candidate: Candidate, resume_text: str) -> None:
    """Normalize derived fields so the knowledge base is internally consistent."""
    if candidate.experience_years == 0 and not _YEARS_RE.search(resume_text):
        candidate.experience_years = None

    candidate.skills = _normalise_skills(candidate.skills)
    candidate.skill_groups = group_skills(candidate.skills)

    if not candidate.role_family:
        candidate.role_family = infer_role_family(candidate.skills)
    if not candidate.seniority or candidate.seniority == UNKNOWN_SENIORITY:
        candidate.seniority = seniority_for_years(candidate.experience_years)
    if not candidate.remote_mode:
        candidate.remote_mode = _infer_remote_mode(resume_text)


def _normalise_skills(skills: list[str]) -> list[str]:
    """Canonicalize, dedupe, and sort a raw skill list."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in skills:
        skill = normalize_skill(str(raw))
        if skill and skill not in seen:
            seen.add(skill)
            result.append(skill)
    return sorted(result)


def _infer_remote_mode(resume_text: str) -> str:
    """Return remote/hybrid/office only when the resume explicitly states it."""
    lower = (resume_text or "").lower()
    if "hybrid" in lower:
        return "hybrid"
    if "remote" in lower and "on-site" not in lower and "on site" not in lower:
        return "remote"
    if any(token in lower for token in ("on-site", "on site", "work from office")):
        return "office"
    return ""


# ---------------------------------------------------------------------------
# LLM extraction (best-effort; never raises)
# ---------------------------------------------------------------------------
_LLM_EXTRACT_PROMPT = """Extract candidate details from the resume below.

ONLY include information that is explicitly stated in the resume. Leave a field
empty (or null / empty list) when the resume does not state it. Never guess or
invent values — in particular never estimate years of experience, salary (CTC),
notice period, or education.

Respond with ONLY a JSON object using exactly these keys:
{{
  "full_name": "",
  "email": "",
  "phone": "",
  "location": "",
  "remote_mode": "",
  "current_title": "",
  "experience_years": null,
  "skills": [],
  "projects": [],
  "certifications": [],
  "achievements": [],
  "education": [{{"degree": "", "institution": "", "year": ""}}],
  "work_experience": [{{"title": "", "company": "", "duration": "", "description": ""}}],
  "current_ctc": "",
  "expected_ctc": "",
  "notice_period": "",
  "linkedin": ""
}}

Resume:
{resume}"""


def _extract_with_llm(resume_text: str, llm) -> dict:
    """Ask the LLM for structured candidate fields; return {} on any failure."""
    try:
        response = llm.invoke(_LLM_EXTRACT_PROMPT.format(resume=resume_text[:8000]))
        content = _response_text(response)
        start, end = content.find("{"), content.rfind("}")
        data = json.loads(content[start:end + 1]) if start >= 0 and end > start else {}
        if not isinstance(data, dict):
            return {}
        return _sanitise_llm_fields(data)
    except Exception as exc:
        logger.debug("LLM candidate extraction failed: %s", exc)
        return {}


def _response_text(response: Any) -> str:
    content = getattr(response, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return str(content or "")


def _sanitise_llm_fields(data: dict) -> dict:
    """Keep only known keys, coerced to the right types (lists filtered)."""
    result: dict[str, Any] = {}
    for key in _STRING_FIELDS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    years = data.get("experience_years")
    if isinstance(years, (int, str)) and str(years).lstrip("-").isdigit():
        number = int(years)
        if number >= 0:
            result["experience_years"] = number
    for key in ("skills", "projects", "certifications", "achievements"):
        values = data.get(key)
        if isinstance(values, list):
            result[key] = [str(v).strip() for v in values if str(v).strip()]
    for key in ("education", "work_experience"):
        values = data.get(key)
        if isinstance(values, list):
            result[key] = [v for v in values if isinstance(v, dict)]
    return result
