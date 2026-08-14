"""Tests for PHASE 2 search-plan generation."""

from jobhunter.config import Settings
from jobhunter.domains.candidate import Candidate
from jobhunter.domains.search.plan import build_search_plan


def test_plan_has_all_kinds():
    plan = build_search_plan("Python Developer")
    assert plan.base_query == "Python Developer"
    assert plan.primary_queries
    assert plan.secondary_queries
    assert plan.deduplicated_queries
    assert plan.unique_queries > 0


def test_plan_primary_covers_configured_locations():
    plan = build_search_plan("Data Analyst", locations=["India", "Bengaluru", "Remote", "Hybrid"])
    locations = {q.location for q in plan.primary_queries}
    assert {"India", "Bengaluru", "Remote", "Hybrid"} <= locations


def test_plan_locations_from_settings():
    settings = Settings(search_locations="Mumbai,Remote")
    plan = build_search_plan("Python Developer", settings=settings)
    locations = {q.location for q in plan.primary_queries}
    assert "Mumbai" in locations
    assert "Remote" in locations


def test_plan_secondary_has_fresher_variant():
    plan = build_search_plan("Data Analyst")
    texts = [q.query.lower() for q in plan.secondary_queries]
    assert texts
    assert any("fresher" in text or "entry level" in text for text in texts)


def test_plan_no_repeated_fresher_terms():
    plan = build_search_plan("Data Analyst fresher")
    for query in plan.deduplicated_queries:
        lowered = query.query.lower()
        assert lowered.count("fresher") <= 1
        assert lowered.count("junior") <= 1
        assert lowered.count("entry level") <= 1


def test_plan_adjacent_uses_candidate_family():
    candidate = Candidate(role_family="data_science", skills=["python"])
    plan = build_search_plan("Data Scientist", candidate=candidate)
    adjacent = {q.query for q in plan.adjacent_queries}
    assert "Machine Learning Engineer" in adjacent
    assert "Data Analyst" in adjacent


def test_plan_adjacent_capped():
    plan = build_search_plan("Data Scientist", candidate=Candidate(role_family="data_science"), max_adjacent=1)
    assert len(plan.adjacent_queries) <= 1


def test_plan_primary_uses_candidate_skills():
    plan = build_search_plan("Data Analyst", candidate=Candidate(skills=["sql", "power bi"]))
    texts = {q.query.lower() for q in plan.primary_queries}
    assert any("sql" in text for text in texts)
    assert any("power bi" in text for text in texts)


def test_plan_deduplicates_equivalent_queries():
    plan = build_search_plan("Data Analyst", candidate=Candidate(role_family="data_analyst", skills=["python", "python"]))
    keys = [(q.query.lower(), q.location.lower()) for q in plan.deduplicated_queries]
    assert len(keys) == len(set(keys))


def test_plan_falls_back_when_empty():
    plan = build_search_plan("")
    assert plan.base_query
    assert plan.primary_queries


def test_plan_secondary_and_adjacent_use_base_location():
    plan = build_search_plan("Data Scientist", candidate=Candidate(role_family="data_science"))
    for query in plan.secondary_queries + plan.adjacent_queries:
        assert query.location == "India"
