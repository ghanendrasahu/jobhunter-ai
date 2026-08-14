"""Explicit contract between job discovery and the application layer.

Graph jobs (from ``search_plan_jobs`` / ``agent.py``) and portal cards (from
``strategies.collect_cards``) both flow into the application layer. This module
defines the minimum fields the application layer reads, plus a deterministic
router that decides whether a job may be auto-applied.

Two invariants are enforced here:

- **Discovery-only jobs never enter the application path.** Sources such as
  LinkedIn are browsable but have no automated application strategy, so their
  jobs are routed to ``None`` and the caller records a safe outcome instead.
- **Unsupported sources never fall through to another portal's strategy.**
  Routing is explicit: a job's ``source``/``portal`` must be one of the
  supported apply portals. Anything else resolves to ``None`` (never applied),
  never to a different portal's application flow.
"""

from __future__ import annotations

from typing import Any

# The only sources with an automated application strategy in the apply agent.
# Everything else is discovery-only and must never be auto-applied.
SUPPORTED_APPLY_PORTALS: tuple[str, ...] = ("naukri", "indeed")

# Fields the application layer actually reads while applying to a job. A job
# missing any of these cannot be applied.
REQUIRED_APPLY_FIELDS: tuple[str, ...] = ("title", "url")

# Fields the application layer reads from graph/card job dicts (documentation
# of the contract, not validated exhaustively).
APPLY_LAYER_FIELDS: tuple[str, ...] = (
    "id",
    "source",              # source/site identity, e.g. "naukri", "foundit"
    "portal",              # apply-strategy key (set by collect_cards)
    "url",                 # job page to open for applying
    "discovery_only",      # True => never auto-apply
    "eligibility_decision",  # PH5 output: "apply" / "skip" / "review" / ...
    "relevance_decision",  # PH6 output: "apply" / "skip" / "neutral"
    "match_score",         # PH6 relevance score (0-100)
    "title",
    "company",
    "description",
    "required_skills",
    "preferred_skills",
    "experience_years_min",
    "seniority",
)


def apply_portal_for(job: dict[str, Any]) -> str | None:
    """Deterministically map a job to its application strategy portal.

    Returns the key for ``strategies.PORTALS``, or ``None`` when the job must
    never be auto-applied (discovery-only source, or a source without an
    automated application strategy). Never returns a portal other than the job's
    own source — unsupported sources are never silently re-routed.
    """
    if job.get("discovery_only"):
        return None
    source = str(job.get("source") or job.get("portal") or "").strip().lower()
    if source in SUPPORTED_APPLY_PORTALS:
        return source
    return None


def missing_apply_fields(job: dict[str, Any]) -> list[str]:
    """Return the required fields a job is missing (empty list => complete)."""
    return [field for field in REQUIRED_APPLY_FIELDS if not str(job.get(field) or "").strip()]


def may_auto_apply(job: dict[str, Any]) -> bool:
    """True only when the job is a complete, supported, non-discovery source."""
    if job.get("discovery_only"):
        return False
    if apply_portal_for(job) is None:
        return False
    return not missing_apply_fields(job)
