"""Skill taxonomy, normalization, and role-family inference.

Gives the candidate knowledge base (and, later, eligibility/ranking) a shared
vocabulary: skills are normalized to canonical names, grouped by family, and a
candidate's dominant role family is inferred from their skill profile. This is
the "role family is a soft criterion" building block.
"""

from __future__ import annotations

import re

# Canonical group name -> normalized skills that belong to it. Ordered: a skill
# is assigned to the FIRST group that contains it.
SKILL_GROUPS: dict[str, list[str]] = {
    "languages": ["python", "java", "javascript", "typescript", "c++", "c#", "go", "rust"],
    "web": ["react", "angular", "vue", "node.js", "django", "flask", "fastapi", "html", "css"],
    "databases": ["sql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch"],
    "cloud_devops": ["aws", "azure", "gcp", "docker", "kubernetes", "terraform", "ci/cd", "jenkins"],
    "ml_ds": ["machine learning", "deep learning", "nlp", "tensorflow", "pytorch",
              "scikit-learn", "pandas", "numpy", "statistics"],
    "genai": ["langchain", "openai", "llm", "rag", "generative ai", "prompt engineering"],
    "data_engineering": ["spark", "etl", "airflow", "databricks", "kafka", "hadoop"],
    "analytics": ["power bi", "tableau", "excel", "analytics"],
    "soft": ["communication", "team management", "leadership", "problem-solving", "analytical"],
}

# Aliases map to canonical skill names (lowercase, no punctuation).
SKILL_ALIASES: dict[str, str] = {
    "ml": "machine learning",
    "dl": "deep learning",
    "genai": "generative ai",
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "postgres": "postgresql",
    "k8s": "kubernetes",
    "mlops": "mlops",
    "sklearn": "scikit-learn",
    "powerbi": "power bi",
    "ci cd": "ci/cd",
}

# Candidate role families and the skill groups that indicate them.
ROLE_FAMILIES: dict[str, tuple[str, ...]] = {
    "data_science": ("ml_ds", "genai", "analytics"),
    "software": ("languages", "web"),
    "data_engineering": ("data_engineering", "databases"),
    "devops": ("cloud_devops",),
}

_FAMILY_ORDER = tuple(ROLE_FAMILIES.keys())


def normalize_skill(skill: str) -> str:
    """Return the canonical form of a skill name, or '' for garbage input."""
    value = re.sub(r"[^a-z0-9+]+", " ", (skill or "").strip().lower()).strip()
    value = SKILL_ALIASES.get(value, value)
    return re.sub(r"\s+", " ", value)


def group_skills(skills: list[str]) -> dict[str, list[str]]:
    """Assign normalized skills to their first matching skill group.

    Returns ``{group: [skills...]}``; unmatched skills land under ``"other"``.
    Empty groups are omitted.
    """
    grouped: dict[str, list[str]] = {}
    for raw in skills:
        skill = normalize_skill(raw)
        if not skill:
            continue
        for group, members in SKILL_GROUPS.items():
            if skill in members:
                grouped.setdefault(group, []).append(skill)
                break
        else:
            grouped.setdefault("other", []).append(skill)
    return grouped


def infer_role_family(skills: list[str]) -> str:
    """Return the candidate's dominant role family, or '' when undetermined.

    The family with the most matched skill-group members wins; ties are broken
    by the order in :data:`ROLE_FAMILIES` (data_science first). Empty/unknown
    profiles yield '' so downstream code can treat it as an unknown criterion.
    """
    grouped = group_skills(skills)
    best_family = ""
    best_score = 0
    for family in _FAMILY_ORDER:
        groups = ROLE_FAMILIES[family]
        score = sum(len(grouped.get(group, [])) for group in groups)
        if score > best_score:
            best_family = family
            best_score = score
    return best_family


def infer_job_role_family(text: str) -> str:
    """Return the role family a job title/description targets, or '' when undetermined.

    Reuses :func:`infer_role_family` on the skill-group members found in the
    text, so the eligibility gate can flag role-family mismatches as a soft
    (never hard) criterion.
    """
    lower = (text or "").lower()
    found: list[str] = []
    for members in SKILL_GROUPS.values():
        for member in members:
            if re.search(r"\b" + re.escape(member) + r"\b", lower) and member not in found:
                found.append(member)
    return infer_role_family(found)


def family_display(family: str) -> str:
    """Human-readable label for a role family."""
    return {
        "data_science": "Data Science / AI / ML",
        "software": "Software Engineering",
        "data_engineering": "Data Engineering",
        "devops": "DevOps / Cloud",
    }.get(family, "Other / Unknown")
