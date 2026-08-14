"""Search-plan generation (PHASE 2).

A :class:`SearchPlan` turns one base query (plus optional candidate knowledge)
into a bounded, de-duplicated set of ``(query, location)`` combinations:

- **primary** queries: the role itself, plus high-signal ``role + skill`` pairs
  from the candidate's skill profile, swept across the configured locations.
- **secondary** queries: fresher/entry-level variants of the base role.
- **adjacent** queries: neighboring role titles for the detected role family,
  capped so irrelevant jobs never dominate the results.

Every query is normalized (no duplicate "fresher" terms, no equivalent query
fragments) so repeated search cycles keep widening coverage instead of repeating
themselves.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from jobhunter.domains.skills import infer_job_role_family

logger = logging.getLogger(__name__)

# Canonical role-family keys (see jobhunter.domains.skills.ROLE_FAMILIES) and the
# adjacent role titles worth searching for each. Kept small and explicit so the
# plan never drifts into irrelevant territory.
ADJACENT_ROLES: dict[str, tuple[str, ...]] = {
    "data_science": ("Machine Learning Engineer", "Data Analyst"),
    "data_engineering": ("Data Engineer", "ETL Developer"),
    "data_analyst": ("Business Analyst", "Data Analyst"),
    "software": ("Backend Developer", "Full Stack Developer"),
    "devops": ("Cloud Engineer", "Site Reliability Engineer"),
    "ml": ("Machine Learning Engineer", "Data Scientist"),
    "cloud": ("DevOps Engineer", "Cloud Engineer"),
}

# Fallback title-keyword -> adjacent roles when the family is undetermined.
_ADJACENT_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (r"\bdata\b", ("Data Analyst", "Data Engineer")),
    (r"\b(ml|machine learning|ai)\b", ("Data Scientist", "Machine Learning Engineer")),
    (r"\b(backend|full.?stack|software)\b", ("Full Stack Developer", "Backend Developer")),
    (r"\b(devops|sre|cloud)\b", ("Cloud Engineer", "DevOps Engineer")),
    (r"\b(qa|test)\b", ("QA Engineer", "Test Automation Engineer")),
)

# Default locations swept for primary queries (base "India" plus work modes).
DEFAULT_LOCATIONS: tuple[str, ...] = ("India", "Bengaluru", "Remote", "Hybrid")

# Maximum number of adjacent role titles added to a plan.
DEFAULT_MAX_ADJACENT = 2
# How many primary (query, location) combinations to generate at most.
DEFAULT_MAX_PRIMARY = 6
# How many secondary variants to generate at most.
DEFAULT_MAX_SECONDARY = 2

_FRESHER_TERMS = ("fresher", "entry level", "junior")
_FRESHER_SUFFIXES = ("fresher", "entry level")


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """A single (query, location) search the engine will run."""

    query: str
    kind: Literal["primary", "secondary", "adjacent"]
    location: str = "India"


@dataclass(slots=True)
class SearchPlan:
    """A de-duplicated set of searches derived from a base query."""

    base_query: str
    queries: list[SearchQuery] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)

    @property
    def primary_queries(self) -> list[SearchQuery]:
        return [q for q in self.queries if q.kind == "primary"]

    @property
    def secondary_queries(self) -> list[SearchQuery]:
        return [q for q in self.queries if q.kind == "secondary"]

    @property
    def adjacent_queries(self) -> list[SearchQuery]:
        return [q for q in self.queries if q.kind == "adjacent"]

    @property
    def deduplicated_queries(self) -> list[SearchQuery]:
        """Queries in execution order, collapsed to unique (query, location) pairs."""
        seen: set[tuple[str, str]] = set()
        unique: list[SearchQuery] = []
        for query in self.queries:
            key = (query.query.strip().lower(), query.location.strip().lower())
            if key in seen:
                continue
            seen.add(key)
            unique.append(query)
        return unique

    @property
    def unique_queries(self) -> int:
        return len(self.deduplicated_queries)


def dedupe_fresher_terms(query: str) -> str:
    """Collapse repeated fresher-family tokens (e.g. 'fresher fresher')."""
    words = query.split()
    seen: set[str] = set()
    cleaned: list[str] = []
    for word in words:
        key = word.lower()
        if key in _FRESHER_TERMS:
            if key in seen:
                continue
            seen.add(key)
        cleaned.append(word)
    return " ".join(cleaned)


def _clean(query: str) -> str:
    """Trim and collapse internal whitespace on a generated query."""
    return re.sub(r"\s+", " ", (query or "").strip())


def _is_redundant(query: str, base: str) -> bool:
    """True when a candidate query adds nothing over the base query."""
    q = _clean(query).lower()
    b = _clean(base).lower()
    return not q or q == b


def _detect_family(base_query: str, role_family: str) -> str:
    if role_family:
        return role_family
    return infer_job_role_family(base_query)


def _adjacent_titles(base_query: str, role_family: str) -> tuple[str, ...]:
    titles = ADJACENT_ROLES.get(role_family, ())
    if titles:
        return titles
    lowered = base_query.lower()
    for pattern, candidates in _ADJACENT_KEYWORDS:
        if re.search(pattern, lowered):
            return candidates
    return ()


def build_search_plan(
    base_query: str,
    candidate=None,
    settings=None,
    locations: tuple[str, ...] | list[str] | None = None,
    max_adjacent: int = DEFAULT_MAX_ADJACENT,
    max_primary: int = DEFAULT_MAX_PRIMARY,
    max_secondary: int = DEFAULT_MAX_SECONDARY,
) -> SearchPlan:
    """Build a bounded, de-duplicated search plan for a base query.

    ``candidate`` (optional :class:`jobhunter.domains.candidate.Candidate`)
    supplies the role family and skill profile used to generate primary and
    adjacent queries. ``settings`` (optional) supplies the location sweep;
    otherwise :data:`DEFAULT_LOCATIONS` is used.
    """
    base = _clean(base_query or "")
    if not base:
        base = "Software Engineer"

    if locations is None:
        if settings is not None:
            raw = getattr(settings, "search_locations", None)
            if raw:
                locations = [loc.strip() for loc in str(raw).split(",") if loc.strip()]
        if not locations:
            locations = list(DEFAULT_LOCATIONS)
    locations = [loc for loc in locations if loc] or list(DEFAULT_LOCATIONS)

    role_family = _detect_family(base, getattr(candidate, "role_family", "") or "")
    skills = [str(s) for s in (getattr(candidate, "skills", None) or []) if s]

    queries: list[SearchQuery] = []

    # --- primary: base role swept across locations + role+skill combos ----------
    primary_queries: list[SearchQuery] = []
    for location in locations:
        primary_queries.append(SearchQuery(query=base, kind="primary", location=location))
    for skill in skills[:2]:
        combo = f"{base} {skill}"
        if not _is_redundant(combo, base):
            primary_queries.append(SearchQuery(query=combo, kind="primary", location="India"))
    if len(primary_queries) > max_primary:
        logger.debug("Capping primary searches from %d to %d", len(primary_queries), max_primary)
        primary_queries = primary_queries[:max_primary]
    queries.extend(primary_queries)

    # --- secondary: fresher/entry-level variants -------------------------------
    if max_secondary > 0:
        for suffix in _FRESHER_SUFFIXES:
            variant = dedupe_fresher_terms(f"{base} {suffix}")
            if _is_redundant(variant, base):
                continue
            if any(term in variant.lower() for term in _FRESHER_TERMS):
                queries.append(SearchQuery(query=variant, kind="secondary", location="India"))

    # --- adjacent: neighboring role titles (capped) ----------------------------
    if max_adjacent > 0:
        for title in _adjacent_titles(base, role_family)[:max_adjacent]:
            if not _is_redundant(title, base):
                queries.append(SearchQuery(query=title, kind="adjacent", location="India"))

    # Deduplicate whole queries, keeping primary searches first.
    plan = SearchPlan(base_query=base, queries=queries, locations=list(locations))
    unique = plan.deduplicated_queries
    plan.queries = sorted(
        unique,
        key=lambda q: {"primary": 0, "secondary": 1, "adjacent": 2}[q.kind],
    )
    return plan
