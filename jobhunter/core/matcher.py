"""Keyword-based matching between job descriptions and a resume."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

TECH_SKILLS: List[str] = [
    "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust",
    "react", "angular", "vue", "node.js", "django", "flask", "fastapi",
    "spring", "express", "next.js", "tailwind", "bootstrap",
    "sql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
    "aws", "azure", "gcp", "docker", "kubernetes", "terraform",
    "git", "ci/cd", "jenkins", "github actions",
    "machine learning", "deep learning", "nlp", "tensorflow", "pytorch",
    "langchain", "openai", "llm", "rag",
    "rest api", "graphql", "grpc", "microservices",
    "agile", "scrum", "jira", "confluence",
    "leadership", "team management", "mentoring",
    "communication", "problem-solving", "analytical",
]

COMMON_TITLES: List[str] = [
    "software engineer", "developer", "data scientist",
    "devops", "frontend", "backend", "full stack",
    "machine learning", "python developer", "java developer",
]


def compute_match_score(
    job_description: str,
    resume_text: str,
) -> Tuple[int, List[str], List[str]]:
    """Return ``(score 0-100, matched_skills, missing_skills)`` for a job vs. resume."""
    if not job_description or not resume_text:
        return 0, [], []

    job_lower = job_description.lower()
    resume_lower = resume_text.lower()

    matched: List[str] = []
    missing: List[str] = []

    for skill in TECH_SKILLS:
        pattern = r"\b" + re.escape(skill) + r"\b"
        in_job = bool(re.search(pattern, job_lower))
        in_resume = bool(re.search(pattern, resume_lower))
        if in_job and in_resume:
            matched.append(skill)
        elif in_job and not in_resume:
            missing.append(skill)

    total_job_skills = len(matched) + len(missing)
    if total_job_skills == 0:
        return 50, [], []  # neutral when no detectable skills

    base_score = (len(matched) / total_job_skills) * 70

    for title in COMMON_TITLES:
        if title in job_lower and title in resume_lower:
            base_score += 10
            break

    if len(missing) > 5:
        base_score = max(base_score - 10, 0)

    return min(int(base_score), 100), matched, missing


def score_jobs(jobs: List[Dict], resume_text: str) -> List[Dict]:
    """Add ``match_score`` / ``matched_skills`` / ``missing_skills`` to each job.

    Jobs are sorted by match score, highest first.
    """
    scored: List[Dict] = []
    for job in jobs:
        description = job.get("description", "") or ""
        score, matched, missing = compute_match_score(description, resume_text)
        job["match_score"] = score
        job["matched_skills"] = matched[:10]
        job["missing_skills"] = missing[:10]
        scored.append(job)

    scored.sort(key=lambda j: j.get("match_score", 0), reverse=True)
    return scored
