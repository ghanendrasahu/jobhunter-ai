"""Tests for the PHASE 6 post-eligibility relevance scoring layer.

Covers: only eligible jobs are scored, deterministic-first ranking with
explainable subscores, required > preferred weighting, role-family softness,
UNKNOWN-candidate neutrality, and the real pipeline ordering.
"""

from typing import Any

import jobhunter.agent as agent
from jobhunter.agent import create_agent, run_job_hunter
from jobhunter.domains.candidate import Candidate
from jobhunter.domains.eligibility import evaluate_eligibility
from jobhunter.domains.scoring import (
    PREFERRED_SKILL_WEIGHT,
    REQUIRED_SKILL_WEIGHT,
    score_relevance,
)


class FakeLLM:
    """Minimal chat-model stand-in; content drives the LLM refinement."""

    def __init__(self, content: str = "95"):
        self.content = content

    def invoke(self, prompt: str) -> object:
        return type("Response", (), {"content": self.content})()


class JsonLLM:
    """Chat-model stand-in that always returns valid JSON for refinement."""

    def __init__(self, score: int, reason: str = "good fit"):
        self.score = score
        self.reason = reason

    def invoke(self, prompt: str) -> object:
        return type("Response", (), {"content": f'{{"score": {self.score}, "reason": "{self.reason}"}}'})()


def _fresher(**overrides) -> Candidate:
    data = dict(
        experience_years=0,
        skills=["python"],
        seniority="FRESHER",
        role_family="software",
    )
    data.update(overrides)
    return Candidate(**data)


def _state(**overrides) -> dict[str, Any]:
    base: dict[str, Any] = {
        "file_path": "",
        "resume_text": "",
        "search_query": "",
        "candidate": None,
        "jobs": [],
        "applications": [],
        "error": "",
    }
    base.update(overrides)
    return base


def _high_match_job() -> dict:
    return {"id": "high", "title": "Python Developer",
            "description": "Python required. Django preferred. 1-2 years experience."}


def _low_match_job() -> dict:
    return {"id": "low", "title": "Backend Engineer",
            "description": "Python required. Go and Rust preferred."}


def _good_candidate() -> Candidate:
    return Candidate(
        experience_years=2,
        skills=["python", "django", "aws"],
        seniority="ENTRY_LEVEL",
        role_family="software",
    )


# ---------------------------------------------------------------------------
# Deterministic ranking
# ---------------------------------------------------------------------------
def test_eligible_high_match_ranks_highly():
    result = score_relevance(_high_match_job(), candidate=_good_candidate(), llm=None)
    assert result.decision == "apply"
    assert result.overall >= 85
    assert result.semantic_score is None  # LLM disabled -> deterministic only


def test_eligible_low_match_ranks_lower():
    low = score_relevance(_low_match_job(), candidate=_good_candidate(), llm=None)
    high = score_relevance(_high_match_job(), candidate=_good_candidate(), llm=None)
    assert low.decision == "apply"
    assert low.overall < high.overall


def test_role_family_mismatch_reduces_score_but_does_not_reject():
    job = _high_match_job()
    mismatch = Candidate(
        experience_years=2, skills=["python", "django", "aws"],
        seniority="ENTRY_LEVEL", role_family="data_science",
    )
    matched = _good_candidate()
    mismatch_result = score_relevance(job, candidate=mismatch, llm=None)
    matched_result = score_relevance(job, candidate=matched, llm=None)
    assert mismatch_result.overall < matched_result.overall
    assert mismatch_result.decision == "apply"  # soft: no rejection


def test_required_skill_weight_exceeds_preferred():
    assert REQUIRED_SKILL_WEIGHT > PREFERRED_SKILL_WEIGHT


def test_required_skill_match_outweighs_preferred_skill_match():
    job = {"id": "r", "title": "Backend Engineer",
           "description": "Python required. AWS preferred."}
    only_required = Candidate(experience_years=2, skills=["python"], seniority="ENTRY_LEVEL",
                              role_family="software")
    both = Candidate(experience_years=2, skills=["python", "aws"], seniority="ENTRY_LEVEL",
                     role_family="software")
    only_required_result = score_relevance(job, candidate=only_required, llm=None)
    both_result = score_relevance(job, candidate=both, llm=None)
    assert both_result.overall > only_required_result.overall  # preferred adds value


def test_preferred_only_knowledge_is_not_actionable():
    # Candidate knows ONLY a preferred skill (missing the required one): the
    # hard gate fails, so nothing is scored or applied.
    job = {"id": "p", "title": "Backend Engineer",
           "description": "Python required. AWS preferred."}
    candidate = Candidate(experience_years=2, skills=["aws"], seniority="ENTRY_LEVEL",
                          role_family="software")
    eligibility = evaluate_eligibility(job, candidate=candidate)
    assert eligibility.decision == "skip"
    result = score_relevance(job, candidate=candidate, llm=FakeLLM("95"))
    assert result.overall == 0
    assert result.semantic_score is None


# ---------------------------------------------------------------------------
# UNKNOWN candidate information
# ---------------------------------------------------------------------------
def test_missing_candidate_info_does_not_hard_fail():
    job = {"id": "u", "title": "Backend Engineer",
           "description": "Python preferred."}
    candidate = Candidate(experience_years=None, skills=[], seniority="UNKNOWN",
                          role_family="")
    result = score_relevance(job, candidate=candidate, llm=None)
    assert result.decision == "apply"
    assert result.overall == 50  # all components neutral -> neutral default
    assert all(c.score is None for c in result.components)


def test_deterministic_scoring_with_llm_disabled():
    result = score_relevance(_high_match_job(), candidate=_good_candidate(), llm=None)
    assert 0 <= result.overall <= 100
    assert result.semantic_score is None
    assert result.components


# ---------------------------------------------------------------------------
# Hard-gate protection
# ---------------------------------------------------------------------------
def test_hard_failed_job_never_receives_actionable_semantic_score():
    job = {"id": "hard", "title": "Senior Data Engineer",
           "description": "At least 9 years of experience required. Python required."}
    result = score_relevance(job, candidate=_fresher(), llm=FakeLLM("95"))
    assert result.overall == 0
    assert result.semantic_score is None
    assert result.decision == "skip"


def test_ph5_failure_cannot_be_overridden_by_95_percent_semantic(monkeypatch):
    jobs = [{
        "id": "j1", "title": "Senior Data Engineer", "company": "Acme",
        "semantic_score": 95, "match_score": 95,
        "eligibility_decision": "skip",
        "eligibility_reasons": ["Requires 9+ years of experience"],
    }]
    called = {"apply": False}

    def boom(job, resume):
        called["apply"] = True
        raise AssertionError("must never apply a hard-skipped job")

    monkeypatch.setattr(agent, "apply_to_job", boom)
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)
    out = agent.apply_jobs(_state(resume_text="x", jobs=jobs))
    assert out["applications"][0]["status"] == "skipped"
    assert called["apply"] is False


def test_score_node_never_scores_skipped_jobs():
    jobs = [
        {"id": "skip1", "title": "Senior", "description": "At least 9 years experience required.",
         "eligibility_decision": "skip"},
        {"id": "apply1", "title": "Junior", "description": "Python required.",
         "eligibility_decision": "apply"},
    ]
    state = _state(resume_text="Python developer", candidate=_fresher(experience_years=1), jobs=jobs)
    out = agent._make_score_jobs(FakeLLM())(state)["jobs"]
    skip_job = next(j for j in out if j["id"] == "skip1")
    apply_job = next(j for j in out if j["id"] == "apply1")
    assert "match_score" not in skip_job
    assert "relevance_score" not in skip_job
    assert "match_score" in apply_job
    assert "relevance_components" in apply_job


# ---------------------------------------------------------------------------
# Explainability
# ---------------------------------------------------------------------------
def test_explanations_match_subscores():
    result = score_relevance(_high_match_job(), candidate=_good_candidate(), llm=None)
    known = [c for c in result.components if c.score is not None]
    total_weight = sum(c.weight for c in known)
    weighted = sum(c.score * c.weight for c in known) / total_weight
    assert round(weighted * 100) == result.overall
    for component in result.components:
        if component.score is not None:
            assert any(component.name in line for line in result.explanation)


def test_llm_refinement_is_optional_and_recorded():
    deterministic = score_relevance(_high_match_job(), candidate=_good_candidate(), llm=None)
    refined = score_relevance(_high_match_job(), candidate=_good_candidate(), llm=JsonLLM(80))
    assert refined.semantic_score == 80
    assert refined.semantic_reason
    assert refined.decision == "apply"  # refinement never changes the decision
    assert any("LLM refined" in line for line in refined.explanation)
    assert deterministic.semantic_score is None


def test_llm_garbage_refinement_ignored():
    result = score_relevance(_high_match_job(), candidate=_good_candidate(), llm=FakeLLM("not-a-number"))
    assert result.semantic_score is None


# ---------------------------------------------------------------------------
# Pipeline ordering (real graph)
# ---------------------------------------------------------------------------
def test_pipeline_scores_only_eligible_and_ranks(sample_pdf, monkeypatch):
    candidate = _good_candidate()
    jobs = [
        {"id": "high", "title": "Python Developer", "company": "Acme",
         "url": "https://x.com/high", "source": "indeed",
         "description": "Python required. Django preferred. 1-2 years experience."},
        {"id": "low", "title": "Backend Engineer", "company": "Corp",
         "url": "https://x.com/low", "source": "linkedin",
         "description": "Python required. Go and Rust preferred."},
        {"id": "hard", "title": "Senior Data Engineer", "company": "BigCo",
         "url": "https://x.com/hard", "source": "indeed",
         "description": "At least 9 years of experience required. Python required."},
    ]

    import jobhunter.automation.candidate as candidate_module

    monkeypatch.setattr(candidate_module, "build_candidate", lambda *a, **k: candidate)
    monkeypatch.setattr(agent, "search_plan_jobs", lambda plan: jobs)
    monkeypatch.setattr(agent, "apply_to_job", lambda job, resume: {
        "job_id": job["id"], "job_title": job["title"], "company": job["company"],
        "status": "applied", "detail": "ok",
    })
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)

    result = run_job_hunter(str(sample_pdf), agent=create_agent(llm=FakeLLM()))

    by_id = {j["id"]: j for j in result["jobs"]}

    # Hard-gated job: never scored, never applied.
    assert "match_score" not in by_id["hard"]
    assert "relevance_score" not in by_id["hard"]
    assert any(a["job_id"] == "hard" and a["status"] == "skipped" for a in result["applications"])

    # Eligible jobs: scored, explainable, ranked high -> low.
    assert by_id["high"]["match_score"] > by_id["low"]["match_score"]
    assert result["jobs"][0]["id"] == "high"
    assert result["jobs"][1]["id"] == "low"
    assert result["jobs"][0]["relevance_components"]
    assert result["jobs"][0]["relevance_explanation"]
    assert any(a["job_id"] == "high" and a["status"] == "applied" for a in result["applications"])
    assert any(a["job_id"] == "low" and a["status"] == "applied" for a in result["applications"])
