"""PHASE 5 eligibility: the deterministic HARD gate that runs before scoring.

Rules this module enforces:

- Hard eligibility runs **before** semantic/relevance scoring; a high semantic
  score can never override a hard eligibility failure.
- Experience and skill requirements are distinguished as **required** vs
  **preferred**; only required criteria can fail a job.
- A required criterion whose value cannot be safely resolved (candidate
  knowledge says UNKNOWN) yields ``waiting_for_user`` with the exact requirement
  exposed — never a guess, and never treating UNKNOWN experience as 0 years.
- Contradictory/ambiguous explicit requirements yield ``waiting_for_user``.
- Role-family mismatch is **soft only**; seniority wording in the title is soft
  (``inspect`` at most) unless an explicit experience requirement says otherwise.

Statuses: ``eligible`` | ``not_eligible`` | ``waiting_for_user`` | ``inspect``.
All parsing is deterministic; an optional LLM is consulted only to disambiguate
a skill list with no required/preferred markers, and its output is validated
against the deterministic vocabulary so it can never relax a hard rule.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from jobhunter.domains.candidate import UNKNOWN_SENIORITY, Candidate
from jobhunter.domains.jobs import SENIORITY_LEVELS
from jobhunter.domains.matching import TECH_SKILLS
from jobhunter.domains.skills import SKILL_GROUPS, infer_job_role_family, normalize_skill

logger = logging.getLogger(__name__)

ELIGIBLE = "eligible"
NOT_ELIGIBLE = "not_eligible"
WAITING_FOR_USER = "waiting_for_user"
INSPECT = "inspect"

REQUIRED = "required"
PREFERRED = "preferred"

_DECISION_FOR_STATUS: dict[str, str] = {
    ELIGIBLE: "apply",
    NOT_ELIGIBLE: "skip",
    WAITING_FOR_USER: "review",
    INSPECT: "review",
}


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------
@dataclass(slots=True)
class Requirement:
    """A single (possibly unresolved) job requirement and how it was resolved."""

    kind: str  # experience_years | seniority | required_skill | preferred_skill | role_family
    level: str  # required | preferred
    description: str  # exact, human-readable requirement text
    met: bool | None  # None = cannot be safely resolved (candidate knowledge UNKNOWN)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "level": self.level,
            "description": self.description,
            "met": self.met,
        }


@dataclass(slots=True)
class EligibilityResult:
    """Outcome of the hard gate for one job."""

    status: str
    decision: str
    requirements: list[Requirement]
    reasons: list[str]
    exposed: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "decision": self.decision,
            "requirements": [r.to_dict() for r in self.requirements],
            "reasons": self.reasons,
            "exposed": self.exposed,
        }


# ---------------------------------------------------------------------------
# Experience-requirement parsing (deterministic)
# ---------------------------------------------------------------------------
_EXP_RANGE_RE = re.compile(r"(\d{1,2})\s*(?:[-–]|to)\s*(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)
_EXP_MIN_RE = re.compile(r"(?:at least|minimum|min\.?|more than|over)\s+(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)
_EXP_PLUS_RE = re.compile(r"(\d{1,2})\s*\+\s*(?:years?|yrs?)", re.IGNORECASE)
_EXP_BARE_RE = re.compile(r"(\d{1,2})\s*(?:years?|yrs?)\s+(?:of\s+)?experience", re.IGNORECASE)

_REQUIRED_MARKERS = (
    "must have", "must-have", "required", "essential", "you must", "need to have",
    "needs to have", "qualifications", "requirements", "prerequisite", "mandatory",
    "must know", "should have",
)
_PREFERRED_MARKERS = (
    "preferred", "nice to have", "good to have", "bonus", "a plus", "is a plus",
    "desired", "advantage", "beneficial", "would be great", "familiarity with",
    "extra credit",
)


@dataclass(slots=True)
class ExperienceStatement:
    """One explicit experience requirement found in the job text."""

    min_years: int
    max_years: int | None
    level: str
    raw: str


def parse_experience_statements(text: str) -> list[ExperienceStatement]:
    """Return every explicit experience statement, deduplicated and de-nested.

    Statements are classified ``required`` by default; a sentence carrying a
    preferred marker (and no required marker) yields a ``preferred`` statement.
    Bare "N years" only counts when it is clearly about experience, and nested
    duplicates (e.g. "at least 5 years" inside "at least 5 years of experience")
    collapse to the outer statement.
    """
    statements: list[ExperienceStatement] = []
    for line in (text or "").lower().splitlines():
        line = line.strip()
        if not line:
            continue
        for sentence in re.split(r"[.!?]+", line):
            sentence = sentence.strip()
            if not sentence:
                continue
            sentence_required = any(marker in sentence for marker in _REQUIRED_MARKERS)
            sentence_preferred = any(marker in sentence for marker in _PREFERRED_MARKERS)

            raw_matches: list[dict[str, Any]] = []
            for pattern in (_EXP_RANGE_RE, _EXP_MIN_RE, _EXP_PLUS_RE):
                for regex_match in pattern.finditer(sentence):
                    if pattern is _EXP_RANGE_RE:
                        raw_matches.append({
                            "min": int(regex_match.group(1)), "max": int(regex_match.group(2)),
                            "start": regex_match.start(), "end": regex_match.end(), "raw": regex_match.group(0),
                        })
                    else:
                        raw_matches.append({
                            "min": int(regex_match.group(1)), "max": None,
                            "start": regex_match.start(), "end": regex_match.end(), "raw": regex_match.group(0),
                        })
            for regex_match in _EXP_BARE_RE.finditer(sentence):
                if not any(not (regex_match.end() <= other["start"] or regex_match.start() >= other["end"])
                           for other in raw_matches):
                    raw_matches.append({
                        "min": int(regex_match.group(1)), "max": None,
                        "start": regex_match.start(), "end": regex_match.end(), "raw": regex_match.group(0),
                    })

            for raw_match in raw_matches:
                level = PREFERRED if (sentence_preferred and not sentence_required) else REQUIRED
                statements.append(
                    ExperienceStatement(raw_match["min"], raw_match["max"], level, raw_match["raw"])
                )

    seen: set[tuple[int, int | None, str, str]] = set()
    unique: list[ExperienceStatement] = []
    for statement in statements:
        key = (statement.min_years, statement.max_years, statement.level, statement.raw)
        if key not in seen:
            seen.add(key)
            unique.append(statement)
    return unique


def _experience_contradiction(required_statements: list[ExperienceStatement]) -> bool:
    """True when required experience statements clearly conflict (gap > 3 years)."""
    if len(required_statements) < 2:
        return False
    mins = [s.min_years for s in required_statements]
    if len(set(mins)) < 2:
        return False
    return (max(mins) - min(mins)) > 3


# ---------------------------------------------------------------------------
# Seniority (soft signal)
# ---------------------------------------------------------------------------
_SENIORITY_HIERARCHY: dict[str, int] = {level: i for i, level in enumerate(SENIORITY_LEVELS)}
_SENIORITY_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("FRESHER", ("fresher", "freshers", "graduate trainee", "trainee")),
    ("ENTRY_LEVEL", ("entry level", "entry-level", "entrylevel", "graduate", "0-1 year", "0 to 1 year")),
    ("JUNIOR", ("junior",)),
    ("ASSOCIATE", ("associate",)),
    ("MID_LEVEL", ("mid-level", "mid level", "midlevel", "intermediate")),
    ("SENIOR", ("senior", "sr")),
    ("LEAD", ("lead", "tech lead", "team lead")),
    ("STAFF", ("staff",)),
    ("PRINCIPAL", ("principal",)),
    ("MANAGER", ("manager",)),
    ("DIRECTOR", ("director", "head of")),
]
_SENIOR_LEVELS = ("SENIOR", "LEAD", "STAFF", "PRINCIPAL", "MANAGER", "DIRECTOR")
_EARLY_LEVELS = ("FRESHER", "ENTRY_LEVEL", "JUNIOR")
_FRESHER_MARKERS = (
    "fresher", "freshers", "entry level", "entry-level", "graduate trainee",
    "no experience", "0-1 year", "0 to 1 year", "trainee",
)


def classify_seniority(text: str) -> str:
    """Return the highest seniority level hinted by ``text``, or ``UNKNOWN``.

    Deterministic keyword scan over the canonical :data:`SENIORITY_LEVELS`.
    Multi-word phrases are matched first so a phrase like "graduate trainee"
    shadows its own sub-word ("graduate") and reports the more specific level.
    """
    lower = f" {text or ''} ".lower()
    matches: list[str] = []

    phrases: list[tuple[str, str]] = [
        (word, level) for level, words in _SENIORITY_WORDS for word in words if " " in word
    ]
    singles: list[tuple[str, str]] = [
        (word, level) for level, words in _SENIORITY_WORDS for word in words if " " not in word
    ]

    phrase_spans: list[tuple[int, int]] = []
    for word, level in phrases:
        for match in re.finditer(r"\b" + re.escape(word) + r"\b", lower):
            phrase_spans.append((match.start(), match.end()))
            matches.append(level)

    for word, level in singles:
        pattern = r"\b" + re.escape(word) + r"\b"
        for match in re.finditer(pattern, lower):
            if any(start <= match.start() and match.end() <= end for start, end in phrase_spans):
                continue  # shadowed by a matched phrase above
            matches.append(level)

    best = UNKNOWN_SENIORITY
    best_index = -1
    for level in matches:
        index = _SENIORITY_HIERARCHY[level]
        if index > best_index:
            best, best_index = level, index
    return best


# ---------------------------------------------------------------------------
# Skill-requirement parsing (deterministic + optional LLM disambiguation)
# ---------------------------------------------------------------------------
def _build_skill_vocabulary() -> list[str]:
    seen: set[str] = set()
    vocab: list[str] = []
    for skill in TECH_SKILLS:
        key = skill.lower()
        if key not in seen:
            seen.add(key)
            vocab.append(skill)
    for members in SKILL_GROUPS.values():
        for skill in members:
            key = skill.lower()
            if key not in seen:
                seen.add(key)
                vocab.append(skill)
    return sorted(vocab, key=len, reverse=True)


_SKILL_VOCABULARY = _build_skill_vocabulary()


def matched_skills(text: str) -> list[str]:
    """Canonical skills from the known vocabulary that occur in ``text``."""
    lower = (text or "").lower()
    found = {normalize_skill(phrase) for phrase in _SKILL_VOCABULARY
             if re.search(r"\b" + re.escape(phrase) + r"\b", lower)}
    return sorted(f for f in found if f)


def extract_skill_requirements(description: str, llm=None) -> tuple[list[str], list[str]]:
    """Return ``(required, preferred)`` skill lists from a job description.

    Skills are classified required/preferred by markers in the same sentence
    (e.g. "Python required.", "AWS preferred.") or by the active section header
    ("Requirements:", "Preferred qualifications:"). A skill with no clear
    classification is left out of both lists — it can never become a hard
    requirement. When the description lists skills with no markers at all, an
    optional ``llm`` is asked to split them; the result is validated against the
    deterministic vocabulary.
    """
    if not description:
        return [], []

    required: set[str] = set()
    preferred: set[str] = set()
    section: str | None = None

    for line in description.splitlines():
        line = line.strip()
        if not line:
            continue
        lower_line = line.lower()
        section = _update_section(lower_line, section)
        for sentence in re.split(r"[.!?]+", lower_line):
            sentence = sentence.strip()
            if not sentence:
                continue
            sentence_required = any(marker in sentence for marker in _REQUIRED_MARKERS)
            sentence_preferred = any(marker in sentence for marker in _PREFERRED_MARKERS)
            for skill in _sentence_skill_matches(sentence):
                if sentence_required and not sentence_preferred:
                    required.add(skill)
                elif sentence_preferred and not sentence_required:
                    preferred.add(skill)
                elif section == REQUIRED:
                    required.add(skill)
                elif section == PREFERRED:
                    preferred.add(skill)

    if llm is not None and not (required or preferred) and matched_skills(description):
        data = _llm_requirement_split(description, llm)
        known = set(matched_skills(description))
        required |= {s for s in data.get("required", []) if s in known}
        preferred |= {s for s in data.get("preferred", []) if s in known}

    return sorted(required), sorted(preferred)


def _update_section(lower_line: str, current: str | None) -> str | None:
    """Track the active required/preferred section from a header line.

    A header is a line with a colon ("Requirements:") or a short line without
    sentence punctuation ("Required Skills"); a regular sentence such as
    "python required." must NOT flip the section for the whole line.
    """
    stripped = lower_line.rstrip(".")
    has_sentence_end = any(p in lower_line for p in ".!?")
    is_header = (":" in lower_line) or (not has_sentence_end and len(stripped.split()) <= 8)
    if not is_header:
        return current
    line_required = any(marker in stripped for marker in _REQUIRED_MARKERS)
    line_preferred = any(marker in stripped for marker in _PREFERRED_MARKERS)
    if line_required and not line_preferred:
        return REQUIRED
    if line_preferred and not line_required:
        return PREFERRED
    return current


def _sentence_skill_matches(sentence: str) -> list[str]:
    """Canonical skills from the known vocabulary that occur in ``sentence``."""
    found = {normalize_skill(phrase) for phrase in _SKILL_VOCABULARY
             if re.search(r"\b" + re.escape(phrase) + r"\b", sentence)}
    return sorted(f for f in found if f)


_LLM_SPLIT_PROMPT = """A job description lists skills without saying which are mandatory.
Split the listed skills into required (must-have) and preferred (nice-to-have).

Job description:
{description}

Respond with ONLY JSON, no other text:
{{"required": ["skill names"], "preferred": ["skill names"]}}"""


def _llm_requirement_split(description: str, llm) -> dict[str, list[str]]:
    """Ask the LLM for a required/preferred split; return {} on any failure."""
    try:
        response = llm.invoke(_LLM_SPLIT_PROMPT.format(description=description[:3000]))
        content = _response_text(response)
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            return {}
        data = json.loads(content[start:end + 1])
        if not isinstance(data, dict):
            return {}
        result: dict[str, list[str]] = {}
        for key in ("required", "preferred"):
            values = data.get(key)
            if isinstance(values, list):
                result[key] = [normalize_skill(str(v)) for v in values if str(v).strip()]
        return result
    except Exception as exc:
        logger.debug("LLM requirement split failed: %s", exc)
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


# ---------------------------------------------------------------------------
# The hard gate
# ---------------------------------------------------------------------------
def evaluate_eligibility(
    job: dict,
    candidate: Candidate | None = None,
    llm=None,
) -> EligibilityResult:
    """Run the deterministic HARD eligibility gate for ``job``.

    ``candidate`` is the :class:`~jobhunter.domains.candidate.Candidate`
    (CandidateKnowledge); ``None`` means nothing is known. The result's
    ``status``/``decision`` drive whether the job may be scored/applied.
    """
    title = job.get("title") or ""
    description = job.get("description") or ""
    text = f"{title}\n{description}"

    requirements: list[Requirement] = []
    exposed: list[str] = []
    reasons: list[str] = []

    # ---- experience -------------------------------------------------------
    required_statements: list[ExperienceStatement] = []
    preferred_statements: list[ExperienceStatement] = []
    explicit_min = job.get("experience_years_min")
    if isinstance(explicit_min, int) and explicit_min >= 0:
        required_statements.append(ExperienceStatement(explicit_min, None, REQUIRED, f"{explicit_min}+ years"))
    else:
        for statement in parse_experience_statements(text):
            (required_statements if statement.level == REQUIRED else preferred_statements).append(statement)

    contradiction = _experience_contradiction(required_statements)

    if required_statements:
        required_min = min(s.min_years for s in required_statements)
        description_text = " / ".join(sorted({s.raw for s in required_statements}))
        exp_met = _resolve_experience(required_min, candidate)
        requirement = Requirement("experience_years", REQUIRED, description_text, met=exp_met)
        requirements.append(requirement)
        if exp_met is None:
            exposed.append(requirement.description)
        elif exp_met is False:
            reasons.append(f"Requires {required_min}+ years of experience; candidate has {_candidate_exp(candidate)}")
    for statement in preferred_statements:
        pref_exp_met = _resolve_experience(statement.min_years, candidate)
        requirements.append(Requirement("experience_years", PREFERRED, f"{statement.raw} (preferred)", met=pref_exp_met))

    # ---- skills -----------------------------------------------------------
    required_skills, preferred_skills = extract_skill_requirements(description, llm=llm)
    required_skills = sorted(set(required_skills) | {normalize_skill(s) for s in (job.get("required_skills") or []) if s})
    preferred_skills = sorted(set(preferred_skills) | {normalize_skill(s) for s in (job.get("preferred_skills") or []) if s})

    candidate_skills = candidate.skills if candidate else []
    candidate_skills_known = bool(candidate_skills)
    for skill in required_skills:
        skill_met: bool | None = None
        if candidate_skills_known:
            skill_met = skill in candidate_skills
        requirement = Requirement("required_skill", REQUIRED, f"Required skill: {skill}", met=skill_met)
        requirements.append(requirement)
        if skill_met is None:
            exposed.append(requirement.description)
        elif skill_met is False:
            known = ", ".join(candidate_skills[:8]) if candidate_skills else "n/a"
            reasons.append(f"Missing required skill: {skill} (candidate knows: {known})")
    for skill in preferred_skills:
        pref_skill_met: bool | None = None
        if candidate_skills_known:
            pref_skill_met = skill in candidate_skills
        requirements.append(Requirement("preferred_skill", PREFERRED, f"Preferred skill: {skill}", met=pref_skill_met))

    # ---- seniority (soft) -------------------------------------------------
    job_seniority = job.get("seniority")
    if job_seniority not in SENIORITY_LEVELS or job_seniority == UNKNOWN_SENIORITY:
        job_seniority = classify_seniority(text)
    candidate_seniority = (candidate.seniority if candidate else UNKNOWN_SENIORITY) or UNKNOWN_SENIORITY
    if job_seniority != UNKNOWN_SENIORITY:
        seniority_met: bool | None = None
        if candidate_seniority != UNKNOWN_SENIORITY:
            seniority_met = _SENIORITY_HIERARCHY[candidate_seniority] >= _SENIORITY_HIERARCHY[job_seniority]
        requirements.append(Requirement("seniority", PREFERRED, f"Role targets {job_seniority.lower()} level", met=seniority_met))

    # ---- role family (soft) -----------------------------------------------
    job_family = infer_job_role_family(text)
    candidate_family = (candidate.role_family if candidate else "") or ""
    if job_family:
        family_met: bool | None = None
        if candidate_family:
            family_met = candidate_family == job_family
        requirements.append(Requirement("role_family", PREFERRED, f"Role family: {job_family}", met=family_met))

    # ---- decision ---------------------------------------------------------
    hard_unmet = [r for r in requirements if r.level == REQUIRED and r.met is False]
    hard_unresolved = [r for r in requirements if r.level == REQUIRED and r.met is None]

    if hard_unmet:
        status = NOT_ELIGIBLE
    elif contradiction:
        status = WAITING_FOR_USER
        exposed = sorted(set(exposed) | {s.raw for s in required_statements})
        reasons = ["Conflicting experience requirements in the job description"]
    elif hard_unresolved:
        status = WAITING_FOR_USER
        reasons = ["Cannot safely resolve a required criterion — candidate knowledge is unknown (never guessed)"]
    elif _should_inspect(job_seniority, candidate_seniority, text):
        status = INSPECT
        reasons = [
            f"Job title targets {job_seniority.lower().replace('_', ' ')} level but the candidate "
            f"appears {candidate_seniority.lower().replace('_', ' ')} — verify suitability before applying."
        ]
    else:
        status = ELIGIBLE

    return EligibilityResult(
        status=status,
        decision=_DECISION_FOR_STATUS[status],
        requirements=requirements,
        reasons=reasons,
        exposed=sorted(set(exposed)),
    )


def _resolve_experience(required_min: int, candidate: Candidate | None) -> bool | None:
    """Compare candidate experience to a required minimum; None = UNKNOWN.

    An unknown candidate experience is never interpreted as 0 years — it
    returns ``None`` so the caller can route the criterion to the user.
    """
    if candidate is None or candidate.experience_years is None:
        return None
    return candidate.experience_years >= required_min


def _candidate_exp(candidate: Candidate | None) -> str:
    if candidate is None or candidate.experience_years is None:
        return "UNKNOWN years"
    return f"{candidate.experience_years} years"


def _should_inspect(job_seniority: str, candidate_seniority: str, text: str) -> bool:
    """Soft concern: early-career candidate facing a Senior-level title.

    Never fires when the role explicitly welcomes freshers/entry-level folks.
    """
    if job_seniority not in _SENIOR_LEVELS or candidate_seniority not in _EARLY_LEVELS:
        return False
    lower = (text or "").lower()
    return not any(marker in lower for marker in _FRESHER_MARKERS)
