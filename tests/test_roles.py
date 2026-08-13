"""Tests for role discovery, priority tiers, and the prioritizer."""

from jobhunter.automation.prioritizer import (
    is_priority_match,
    job_fresher_friendly,
    job_remote,
    parse_posted_text,
    parse_salary,
    posted_days_ago,
    priority_score,
    sort_jobs_by_priority,
)
from jobhunter.automation.roles import (
    is_priority_title,
    priority_role_titles,
    suggest_roles,
)

RESUME = (
    "Data Scientist with Python, pandas, machine learning, SQL and deep learning. "
    "Built RAG pipelines with LangChain and deployed on AWS."
)


def test_suggest_roles_returns_tier_first():
    roles = suggest_roles(RESUME)
    assert roles
    tiers = [r["tier"] for r in roles]
    assert tiers == sorted(tiers)
    # AI/ML/Data roles should surface with a non-zero score.
    assert any("Data Scientist" == r["title"] for r in roles)
    assert all(r["score"] > 0 for r in roles)


def test_suggest_roles_empty_resume():
    assert suggest_roles("") == []


def test_priority_role_titles_tier1():
    titles = priority_role_titles()
    assert "Data Scientist" in titles
    assert "Machine Learning Engineer" in titles
    assert "DevOps Engineer" not in titles


def test_priority_role_titles_filtered():
    chosen = [{"title": "Data Scientist", "tier": 1}, {"title": "DevOps Engineer", "tier": 3}]
    titles = priority_role_titles(chosen)
    assert titles == {"Data Scientist"}


def test_is_priority_title_fuzzy():
    assert is_priority_title("Senior Data Scientist", {"Data Scientist"})
    assert not is_priority_title("DevOps Engineer", {"Data Scientist"})


def test_parse_posted_text():
    assert parse_posted_text("Just posted") == 0
    assert parse_posted_text("Posted today") == 0
    assert parse_posted_text("2 days ago") == 2
    assert parse_posted_text("1 week ago") == 7
    assert parse_posted_text("3 months ago") == 90
    assert parse_posted_text("no date here") is None


def test_posted_days_ago_field():
    assert posted_days_ago({"posted_days": 3}) == 3
    assert posted_days_ago({}) is None


def test_job_remote():
    assert job_remote({"title": "Data Analyst (Work From Home)"})
    assert job_remote({"description": "Remote friendly team"})
    assert not job_remote({"title": "Data Analyst", "location": "Bengaluru"})


def test_job_fresher_friendly():
    assert job_fresher_friendly({"title": "Fresher Data Analyst"})
    assert job_fresher_friendly({"description": "Entry level role"})
    assert not job_fresher_friendly({"title": "Senior Data Scientist"})


def test_parse_salary():
    assert parse_salary({"salary_text": "₹6-8 LPA"}) == 8
    assert parse_salary({"salary_text": "12 LPA"}) == 12
    assert parse_salary({"salary_min": 4, "salary_max": 9}) == 9
    assert parse_salary({"title": "no salary"}) is None


def test_priority_score_remote_and_tier_boost():
    base = {"title": "Data Scientist", "description": "Python ML", "posted_days": 0}
    base_score = priority_score(base)
    tier_score = priority_score(base, {"Data Scientist"})
    assert tier_score > base_score

    remote = {**base, "title": "Data Scientist (Remote)"}
    assert priority_score(remote) > base_score


def test_sort_jobs_by_priority():
    jobs = [
        {"title": "Data Scientist", "posted_days": 10, "description": "python"},
        {"title": "Data Analyst", "posted_days": 0, "description": "sql"},
    ]
    sorted_jobs = sort_jobs_by_priority(jobs, {"Data Analyst"})
    assert sorted_jobs[0]["title"] == "Data Analyst"  # fresher + recency + tier


def test_is_priority_match():
    assert is_priority_match("ML Engineer", {"Machine Learning Engineer"})
    assert not is_priority_match("DevOps", {"Data Scientist"})
