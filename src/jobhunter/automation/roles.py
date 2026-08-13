"""Job-role discovery and priority ranking.

Suggests the roles a resume qualifies for and marks which are "priority".
Tier 1 covers the AI/ML/Data-Science/Analyst family the user wants searched
first; Tier 2 and 3 are common software/data roles. Roles are scored by how
many of their signature skills appear in the resume, then sorted tier-first.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# title -> (tier, skill signature matched against the resume)
ROLE_CATALOG: list[dict] = [
    # Tier 1 — AI/ML/Data Science/Analyst (user's top priority)
    {"title": "Data Scientist", "tier": 1, "skills": [
        "python", "pandas", "numpy", "machine learning", "statistics", "scikit", "data", "sql"]},
    {"title": "Machine Learning Engineer", "tier": 1, "skills": [
        "python", "machine learning", "deep learning", "tensorflow", "pytorch", "langchain", "mlops", "aws"]},
    {"title": "AI Engineer", "tier": 1, "skills": [
        "llm", "rag", "langchain", "openai", "generative ai", "prompt", "nlp", "python"]},
    {"title": "Data Analyst", "tier": 1, "skills": [
        "sql", "excel", "pandas", "power bi", "tableau", "analytics", "python", "data"]},
    {"title": "Business Analyst", "tier": 1, "skills": [
        "sql", "excel", "requirements", "analytics", "stakeholder", "agile", "reporting"]},
    {"title": "NLP Engineer", "tier": 1, "skills": [
        "nlp", "transformers", "bert", "langchain", "llm", "python", "spacy", "text"]},
    {"title": "Data Engineer", "tier": 1, "skills": [
        "sql", "python", "spark", "etl", "airflow", "databricks", "warehouse", "pipeline"]},
    {"title": "Data Science Intern", "tier": 1, "skills": [
        "machine learning", "python", "data", "intern", "analytics", "sql"]},
    # Tier 2 — software engineering
    {"title": "Python Developer", "tier": 2, "skills": [
        "python", "django", "flask", "fastapi", "rest api", "postgresql", "aws"]},
    {"title": "Backend Developer", "tier": 2, "skills": [
        "python", "java", "node.js", "rest api", "microservices", "sql", "docker"]},
    {"title": "Full Stack Developer", "tier": 2, "skills": [
        "python", "javascript", "react", "node.js", "sql", "rest api", "docker"]},
    {"title": "Software Engineer", "tier": 2, "skills": [
        "python", "java", "javascript", "git", "rest api", "docker", "sql"]},
    {"title": "SQL Developer", "tier": 2, "skills": [
        "sql", "postgresql", "mysql", "query", "database", "etl", "reporting"]},
    # Tier 3 — everything else
    {"title": "DevOps Engineer", "tier": 3, "skills": [
        "docker", "kubernetes", "terraform", "aws", "ci/cd", "jenkins", "linux"]},
    {"title": "Frontend Developer", "tier": 3, "skills": [
        "javascript", "react", "html", "css", "typescript", "angular", "vue"]},
    {"title": "QA Engineer", "tier": 3, "skills": [
        "testing", "selenium", "pytest", "qa", "automation testing", "python"]},
]


def _role_score(role: dict, resume_text: str, resume_lower: str) -> float:
    """Score how well a role's skill signature matches the resume."""
    signature = role["skills"]
    hits = sum(1 for skill in signature if skill in resume_lower)
    if hits == 0:
        return 0.0
    # Keyword overlap gives the base; title-in-resume bumps it.
    base = hits / len(signature)
    title_tokens = role["title"].lower().split()
    title_hit = sum(1 for token in title_tokens if token in resume_lower)
    return round(min(base + title_hit * 0.15, 1.0), 2)


def suggest_roles(resume_text: str, llm=None) -> list[dict]:
    """Return roles the resume qualifies for, sorted tier-first then by score.

    ``llm`` is accepted for API compatibility but not required — the scoring is
    deterministic keyword matching so it works fully offline. Returns a list of
    ``{title, tier, score}`` dicts, score 0..1.
    """
    resume_lower = (resume_text or "").lower()
    scored = []
    for role in ROLE_CATALOG:
        score = _role_score(role, resume_text, resume_lower)
        if score > 0:
            scored.append({"title": role["title"], "tier": role["tier"], "score": score})
    # Tier first (1 = highest priority), then match score, then title.
    scored.sort(key=lambda r: (r["tier"], -r["score"], r["title"]))
    logger.info("Suggested %d roles from resume", len(scored))
    return scored


def priority_role_titles(roles: list[dict] | None = None) -> set[str]:
    """Return the set of Tier-1 role titles (the user's search priority).

    When ``roles`` is provided, only priority titles present in that list are
    returned, so the agent boosts jobs matching roles the user actually chose.
    """
    tier1 = {r["title"] for r in ROLE_CATALOG if r["tier"] == 1}
    if not roles:
        return tier1
    return {r["title"] for r in roles if r["title"] in tier1}


def is_priority_title(job_title: str, priority_titles: set[str]) -> bool:
    """True when a job title mentions any priority role (fuzzy word match)."""
    if not job_title:
        return False
    lower = job_title.lower()
    for title in priority_titles:
        for token in title.split():
            token_lower = token.lower()
            if len(token_lower) > 2 and token_lower in lower:
                return True
    return False


def tier_display(tier: int) -> str:
    """Human label for a tier."""
    return {1: "⭐ Priority (AI/ML/Data/Analyst)", 2: "Software roles", 3: "Other roles"}.get(
        tier, "Other roles"
    )
