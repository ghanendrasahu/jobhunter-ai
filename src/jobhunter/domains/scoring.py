"""PHASE 6 relevance scoring: the post-eligibility ranking layer.

Only jobs that passed the PHASE 5 hard gate may be scored here. The model is
deterministic and explainable:

- **Required skills** carry far more weight than preferred skills.
- **Role family** is soft: a mismatch lowers the score but never rejects.
- **Experience / seniority fit** respects the PH5 eligibility result; when the
  candidate's value is UNKNOWN the component is *neutral* (excluded from the
  weighted average) so missing information is never a hard failure.
- An **optional LLM** may refine the overall score and add a short reason, but
  it can never change the eligibility decision or grant a score to an
  ineligible job (those always return ``overall=0``, ``semantic_score=None``).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from jobhunter.domains.candidate import UNKNOWN_SENIORITY, Candidate
from jobhunter.domains.eligibility import (
    INSPECT,
    NOT_ELIGIBLE,
    WAITING_FOR_USER,
    classify_seniority,
    evaluate_eligibility,
    extract_skill_requirements,
)
from jobhunter.domains.jobs import SENIORITY_LEVELS
from jobhunter.domains.skills import infer_job_role_family, normalize_skill

logger = logging.getLogger(__name__)

# Component weights (must sum to 1.0). Required skills dominate preferred skills.
REQUIRED_SKILL_WEIGHT = 0.45
PREFERRED_SKILL_WEIGHT = 0.20
EXPERIENCE_WEIGHT = 0.15
SENIORITY_WEIGHT = 0.10
ROLE_FAMILY_WEIGHT = 0.10

# The only PH5 decision that may receive a relevance score.
ELIGIBLE_DECISION = "apply"

_SENIORITY_HIERARCHY: dict[str, int] = {level: i for i, level in enumerate(SENIORITY_LEVELS)}

_SEMANTIC_PROMPT = """Score how relevant this candidate is for the job, 0-100.
Do NOT evaluate eligibility — the job already passed the hard requirements gate.

Candidate profile:
- Skills: {skills}
- Experience: {experience}
- Seniority: {seniority}
- Role family: {family}

Job:
Title: {title}
Description: {description}

Respond with ONLY a JSON object, no markdown:
{{"score": 0-100, "reason": "one short sentence"}}"""


@dataclass(slots=True)
class ScoreComponent:
    """One explainable subscore (0..1) and its weight in the overall score.

    ``score is None`` marks a *neutral* component: the underlying candidate
    information is UNKNOWN (or the job states no such requirement), so it is
    excluded from the weighted average and never penalized.
    """

    name: str
    score: float | None
    weight: float
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "weight": self.weight,
            "detail": self.detail,
        }


@dataclass(slots=True)
class RelevanceScore:
    """Explainable relevance score for a job that passed the PH5 hard gate."""

    overall: int
    decision: str  # "apply" for eligible; "skip" for hard-gated jobs
    components: list[ScoreComponent]
    explanation: list[str]
    semantic_score: int | None = None
    semantic_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "decision": self.decision,
            "components": [c.to_dict() for c in self.components],
            "explanation": self.explanation,
            "semantic_score": self.semantic_score,
            "semantic_reason": self.semantic_reason,
        }


def score_relevance(
    job: dict,
    candidate: Candidate | None = None,
    resume_text: str = "",
    llm: Any | None = None,
    eligibility=None,
) -> RelevanceScore:
    """Score how relevant an **eligible** job is for the candidate.

    Re-runs the deterministic hard gate when ``eligibility`` is not supplied;
    an ineligible job always returns ``overall=0`` with ``semantic_score=None``
    so a hard PH5 failure can never receive an actionable score.
    """
    if eligibility is None:
        eligibility = evaluate_eligibility(job, candidate=candidate)

    if eligibility.decision != ELIGIBLE_DECISION:
        status = eligibility.status
        if status == NOT_ELIGIBLE:
            message = "Job failed the PH5 hard eligibility gate"
        elif status == WAITING_FOR_USER:
            message = "Job needs review — a required criterion could not be resolved"
        elif status == INSPECT:
            message = "Job flagged for inspection before applying"
        else:
            message = f"Job not eligible (status: {status})"
        reason = "; ".join(eligibility.reasons) or message
        return RelevanceScore(
            overall=0,
            decision=eligibility.decision,
            components=[],
            explanation=[f"{message}: {reason}"],
            semantic_score=None,
            semantic_reason="",
        )

    components = _deterministic_components(job, candidate, eligibility)
    overall = _weighted_overall(components)
    explanation = _build_explanation(job, components, overall)

    semantic: tuple[int, str] | None = None
    if llm is not None:
        semantic = _semantic_relevance(job, candidate, llm)

    semantic_score: int | None = None
    semantic_reason = ""
    if semantic is not None:
        semantic_score, semantic_reason = semantic
        blended = round(0.7 * overall + 0.3 * semantic_score)
        explanation.append(f"LLM refined overall to {blended} (semantic {semantic_score}/100: {semantic_reason})")
        overall = blended

    return RelevanceScore(
        overall=overall,
        decision="apply",
        components=components,
        explanation=explanation,
        semantic_score=semantic_score,
        semantic_reason=semantic_reason,
    )


def _deterministic_components(
    job: dict,
    candidate: Candidate | None,
    eligibility: Any,
) -> list[ScoreComponent]:
    """Compute the five deterministic, explainable subscores."""
    title = job.get("title") or ""
    description = job.get("description") or ""
    text = f"{title}\n{description}"
    candidate_skills = set(candidate.skills) if candidate else set()
    skills_known = bool(candidate_skills)

    required_skills, preferred_skills = extract_skill_requirements(description, llm=None)
    required_skills = sorted(set(required_skills) | {normalize_skill(s) for s in (job.get("required_skills") or []) if s})
    preferred_skills = sorted(set(preferred_skills) | {normalize_skill(s) for s in (job.get("preferred_skills") or []) if s})

    components: list[ScoreComponent] = []

    # ---- required skills (dominant weight) ---------------------------------
    if not required_skills:
        components.append(ScoreComponent(
            "required_skills", None, REQUIRED_SKILL_WEIGHT,
            "Job lists no explicit required skills",
        ))
    elif not skills_known:
        components.append(ScoreComponent(
            "required_skills", None, REQUIRED_SKILL_WEIGHT,
            "Candidate skills UNKNOWN — no score, no penalty",
        ))
    else:
        matched = sum(1 for s in required_skills if s in candidate_skills)
        ratio = matched / len(required_skills)
        missing = ", ".join(s for s in required_skills if s not in candidate_skills) or "none"
        components.append(ScoreComponent(
            "required_skills", ratio, REQUIRED_SKILL_WEIGHT,
            f"{matched}/{len(required_skills)} required skills matched; missing: {missing}",
        ))

    # ---- preferred skills --------------------------------------------------
    if not preferred_skills:
        components.append(ScoreComponent(
            "preferred_skills", None, PREFERRED_SKILL_WEIGHT,
            "Job lists no explicit preferred skills",
        ))
    elif not skills_known:
        components.append(ScoreComponent(
            "preferred_skills", None, PREFERRED_SKILL_WEIGHT,
            "Candidate skills UNKNOWN — no score, no penalty",
        ))
    else:
        matched = sum(1 for s in preferred_skills if s in candidate_skills)
        ratio = matched / len(preferred_skills)
        missing = ", ".join(s for s in preferred_skills if s not in candidate_skills) or "none"
        components.append(ScoreComponent(
            "preferred_skills", ratio, PREFERRED_SKILL_WEIGHT,
            f"{matched}/{len(preferred_skills)} preferred skills matched; missing: {missing}",
        ))

    # ---- experience fit (respects the PH5 eligibility result) --------------
    exp_values: list[float] = []
    exp_details: list[str] = []
    for req in eligibility.requirements:
        if req.kind != "experience_years":
            continue
        if req.level == "required":
            if req.met is True:
                exp_values.append(1.0)
                exp_details.append(f"required {req.description} met")
            else:
                exp_details.append(f"required {req.description} unresolved (neutral)")
        else:  # preferred
            if req.met is True:
                exp_values.append(1.0)
                exp_details.append(f"preferred {req.description} met")
            elif req.met is False:
                exp_values.append(0.5)
                exp_details.append(f"preferred {req.description} not met (partial credit)")
            else:
                exp_details.append(f"preferred {req.description} unresolved (neutral)")
    if exp_values:
        components.append(ScoreComponent(
            "experience", sum(exp_values) / len(exp_values), EXPERIENCE_WEIGHT,
            "; ".join(exp_details),
        ))
    else:
        components.append(ScoreComponent(
            "experience", None, EXPERIENCE_WEIGHT,
            "No explicit experience requirement or candidate experience UNKNOWN — neutral",
        ))

    # ---- seniority fit (soft) ----------------------------------------------
    job_seniority = job.get("seniority")
    if job_seniority not in SENIORITY_LEVELS or job_seniority == UNKNOWN_SENIORITY:
        job_seniority = classify_seniority(text)
    candidate_seniority = (candidate.seniority if candidate else UNKNOWN_SENIORITY) or UNKNOWN_SENIORITY
    if job_seniority == UNKNOWN_SENIORITY or candidate_seniority == UNKNOWN_SENIORITY:
        components.append(ScoreComponent(
            "seniority", None, SENIORITY_WEIGHT,
            "Role seniority or candidate seniority UNKNOWN — neutral",
        ))
    else:
        if _SENIORITY_HIERARCHY[candidate_seniority] >= _SENIORITY_HIERARCHY[job_seniority]:
            score = 1.0
            detail = f"candidate {candidate_seniority.lower()} at or above role {job_seniority.lower()}"
        else:
            score = 0.6
            detail = f"candidate {candidate_seniority.lower()} below role {job_seniority.lower()} (soft)"
        components.append(ScoreComponent("seniority", score, SENIORITY_WEIGHT, detail))

    # ---- role family (soft only) -------------------------------------------
    job_family = infer_job_role_family(text)
    candidate_family = (candidate.role_family if candidate else "") or ""
    if not job_family or not candidate_family:
        components.append(ScoreComponent(
            "role_family", None, ROLE_FAMILY_WEIGHT,
            "Job or candidate role family UNKNOWN — neutral",
        ))
    else:
        if job_family == candidate_family:
            score = 1.0
            detail = f"candidate {candidate_family} matches role {job_family}"
        else:
            score = 0.4
            detail = f"candidate {candidate_family} vs role {job_family} — soft reduction only"
        components.append(ScoreComponent("role_family", score, ROLE_FAMILY_WEIGHT, detail))

    return components


def _weighted_overall(components: list[ScoreComponent]) -> int:
    """Weighted average over known (non-neutral) components; 50 when none are known."""
    known = [c for c in components if c.score is not None]
    if not known:
        return 50
    total_weight = sum(c.weight for c in known)
    if total_weight <= 0:
        return 50
    weighted = sum(c.score * c.weight for c in known if c.score is not None) / total_weight
    return min(max(round(weighted * 100), 0), 100)


def _build_explanation(job: dict, components: list[ScoreComponent], overall: int) -> list[str]:
    """Human-readable lines whose numbers mirror the actual subscores."""
    lines: list[str] = []
    for component in components:
        if component.score is None:
            lines.append(f"{component.name}: n/a ({component.detail})")
        else:
            lines.append(
                f"{component.name}: {round(component.score * 100)}% "
                f"(weight {component.weight:.2f}) — {component.detail}"
            )
    known = [c for c in components if c.score is not None]
    lines.append(
        f"Overall relevance: {overall}/100 "
        f"({len(known)}/{len(components)} components known; unknown components are neutral)"
    )
    return lines


def _semantic_relevance(job: dict, candidate: Candidate | None, llm: Any) -> tuple[int, str] | None:
    """Ask the LLM for a 0-100 relevance score + reason; None on any failure."""
    try:
        response = llm.invoke(
            _SEMANTIC_PROMPT.format(
                skills=", ".join(candidate.skills[:12]) if candidate and candidate.skills else "UNKNOWN",
                experience=(f"{candidate.experience_years} years" if candidate and candidate.experience_years is not None else "UNKNOWN"),
                seniority=(candidate.seniority if candidate else UNKNOWN_SENIORITY) or UNKNOWN_SENIORITY,
                family=(candidate.role_family if candidate else "") or "UNKNOWN",
                title=job.get("title", ""),
                description=(job.get("description") or "")[:3000],
            )
        )
        content = (getattr(response, "content", None) or "")
        content = re.sub(r"```(?:json)?", "", content).strip("` \n")
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                return None
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
        score = int(data.get("score", -1))
        if not (0 <= score <= 100):
            return None
        return score, str(data.get("reason", ""))[:200]
    except Exception as exc:
        logger.debug("Semantic relevance refinement failed: %s", exc)
        return None
