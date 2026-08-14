"""Tests for the PHASE 5 eligibility hard gate and its pipeline ordering.

These cover the invariants: hard eligibility runs before scoring, a high
semantic score can never override a hard failure, UNKNOWN is never guessed as 0,
required vs preferred is respected, and role-family mismatches stay soft.
"""

from typing import Any

import jobhunter.agent as agent
from jobhunter.agent import apply_jobs, create_agent, run_job_hunter
from jobhunter.automation.candidate import build_candidate as real_build_candidate
from jobhunter.domains.candidate import UNKNOWN_SENIORITY, Candidate
from jobhunter.domains.eligibility import (
    INSPECT,
    NOT_ELIGIBLE,
    WAITING_FOR_USER,
    classify_seniority,
    evaluate_eligibility,
    extract_skill_requirements,
    parse_experience_statements,
)
from jobhunter.domains.skills import infer_job_role_family


class FakeLLM:
    """Minimal stand-in for a chat model."""

    def __init__(self, content: str = "Python Developer"):
        self.content = content

    def invoke(self, prompt: str) -> object:
        return type("Response", (), {"content": self.content})()


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


def _fresher(**overrides) -> Candidate:
    data = dict(
        experience_years=0,
        skills=["python"],
        seniority="FRESHER",
        role_family="software",
    )
    data.update(overrides)
    return Candidate(**data)


# ---------------------------------------------------------------------------
# Experience rules
# ---------------------------------------------------------------------------
def test_fresher_vs_five_years_hard_fails():
    job = {"title": "Senior Data Engineer",
           "description": "At least 5 years of experience required. Python required."}
    result = evaluate_eligibility(job, candidate=_fresher())
    assert result.status == NOT_ELIGIBLE
    assert result.decision == "skip"
    assert any(r.kind == "experience_years" and r.level == "required" and r.met is False
               for r in result.requirements)


def test_senior_title_without_exp_requirement_inspects_not_rejects():
    job = {"title": "Senior Python Developer",
           "description": "Build APIs with FastAPI. Python required."}
    result = evaluate_eligibility(job, candidate=_fresher())
    assert result.status == INSPECT
    assert result.decision == "review"
    assert not any(r.level == "required" and r.met is False for r in result.requirements)


def test_senior_title_fresher_friendly_is_eligible():
    job = {"title": "Senior Software Engineer",
           "description": "Entry level, fresher friendly. Python required."}
    result = evaluate_eligibility(job, candidate=_fresher())
    assert result.status == "eligible"
    assert result.decision == "apply"


def test_junior_entry_level_eligible():
    job = {"title": "Junior Developer",
           "description": "Python required. 1-2 years experience."}
    candidate = Candidate(experience_years=2, skills=["python"], seniority="ENTRY_LEVEL")
    result = evaluate_eligibility(job, candidate=candidate)
    assert result.status == "eligible"
    assert result.decision == "apply"


def test_required_vs_preferred_experience():
    job = {"title": "Backend Engineer",
           "description": "Requirements: 3 years experience, Python. Preferred: 5+ years, AWS."}
    candidate = Candidate(experience_years=4, skills=["python", "aws"], seniority="JUNIOR")
    result = evaluate_eligibility(job, candidate=candidate)
    assert result.status == "eligible"
    required = [r for r in result.requirements if r.kind == "experience_years" and r.level == "required"]
    preferred = [r for r in result.requirements if r.kind == "experience_years" and r.level == "preferred"]
    assert required and required[0].met is True
    assert preferred and preferred[0].met is False  # preferred shortfall is never a hard fail


# ---------------------------------------------------------------------------
# Skill rules
# ---------------------------------------------------------------------------
def test_required_vs_preferred_skill():
    job = {"title": "Backend Engineer", "description": "Python required. AWS preferred."}
    candidate = Candidate(experience_years=3, skills=["python"], seniority="JUNIOR")
    result = evaluate_eligibility(job, candidate=candidate)
    assert result.status == "eligible"
    assert any(r.kind == "required_skill" and r.met is True for r in result.requirements)
    assert any(r.kind == "preferred_skill" and r.met is False for r in result.requirements)


def test_missing_required_skill_hard_fails():
    job = {"title": "Backend Engineer", "description": "Python required. AWS required."}
    candidate = Candidate(experience_years=3, skills=["python"], seniority="JUNIOR")
    result = evaluate_eligibility(job, candidate=candidate)
    assert result.status == NOT_ELIGIBLE
    assert any(r.kind == "required_skill" and r.met is False for r in result.requirements)


def test_skill_requirement_extraction_markers():
    required, preferred = extract_skill_requirements(
        "Requirements: Python and SQL.\nPreferred: AWS and Docker."
    )
    assert required == ["python", "sql"]
    assert preferred == ["aws", "docker"]


def test_skill_requirement_extraction_no_markers_stays_conservative():
    required, preferred = extract_skill_requirements("We use Python and Django.")
    assert required == [] and preferred == []  # no hard rule inferred without markers


def test_llm_split_is_validated_against_vocabulary():
    class LazyLLM:
        def invoke(self, prompt: str) -> object:
            content = '{"required": ["Python"], "preferred": ["aws", "bogus-nonsense"]}'
            return type("Response", (), {"content": content})()

    required, preferred = extract_skill_requirements(
        "Python and AWS on this team.",
        llm=LazyLLM(),
    )
    assert required == ["python"]
    assert preferred == ["aws"]  # unknown phrase never becomes a requirement


# ---------------------------------------------------------------------------
# UNKNOWN is never guessed
# ---------------------------------------------------------------------------
def test_unknown_experience_is_never_treated_as_zero():
    job = {"title": "Backend Engineer",
           "description": "At least 5 years of experience required. Python required."}
    candidate = Candidate(experience_years=None, skills=["python"], seniority=UNKNOWN_SENIORITY)
    result = evaluate_eligibility(job, candidate=candidate)
    assert result.status == WAITING_FOR_USER
    assert result.decision == "review"
    assert not any(r.level == "required" and r.met is False for r in result.requirements)
    assert result.exposed  # exact requirement surfaced for the user


def test_unknown_mandatory_criterion_waits_for_user():
    job = {"title": "Backend Engineer",
           "description": "Python required. At least 5 years of experience required."}
    result = evaluate_eligibility(job, candidate=None)
    assert result.status == WAITING_FOR_USER
    assert result.decision == "review"
    assert result.exposed


def test_contradictory_requirements_needs_review():
    job = {"title": "Backend Engineer",
           "description": "At least 3 years experience. At least 8 years experience."}
    result = evaluate_eligibility(job, candidate=_fresher(experience_years=5))
    assert result.status == WAITING_FOR_USER
    assert result.decision == "review"


def test_experience_parse_statements():
    statements = parse_experience_statements(
        "Requirements: 3-5 years experience. At least 5 years of experience. Preferred: 8+ years."
    )
    required = [s for s in statements if s.level == "required"]
    preferred = [s for s in statements if s.level == "preferred"]
    assert required and preferred
    assert {s.min_years for s in required} == {3, 5}
    assert preferred[0].min_years == 8


# ---------------------------------------------------------------------------
# Soft criteria
# ---------------------------------------------------------------------------
def test_role_family_mismatch_is_soft_not_hard():
    job = {"title": "Data Scientist", "description": "Pandas and numpy required. 2+ years experience."}
    candidate = Candidate(
        experience_years=3,
        skills=["pandas", "numpy"],
        seniority="JUNIOR",
        role_family="software",  # mismatched family on purpose
    )
    result = evaluate_eligibility(job, candidate=candidate)
    assert result.status == "eligible"
    assert any(r.kind == "role_family" and r.met is False for r in result.requirements)


def test_role_family_match_is_soft_pass():
    job = {"title": "ML Engineer", "description": "Python required. 2+ years experience."}
    candidate = Candidate(experience_years=3, skills=["python"], seniority="JUNIOR",
                          role_family="data_science")
    result = evaluate_eligibility(job, candidate=candidate)
    assert result.status == "eligible"


def test_infer_job_role_family():
    assert infer_job_role_family("Senior Data Scientist pandas numpy") == "data_science"
    assert infer_job_role_family("Backend Python FastAPI") == "software"
    assert infer_job_role_family("no skills mentioned") == ""


# ---------------------------------------------------------------------------
# Seniority taxonomy
# ---------------------------------------------------------------------------
def test_seniority_classification_taxonomy():
    examples = {
        "FRESHER": ["Fresher", "Graduate Trainee"],
        "ENTRY_LEVEL": ["Entry Level", "0-1 year"],
        "JUNIOR": ["Junior"],
        "ASSOCIATE": ["Associate"],
        "MID_LEVEL": ["Mid-level", "Intermediate"],
        "SENIOR": ["Senior", "Sr."],
        "LEAD": ["Lead", "Tech Lead"],
        "STAFF": ["Staff"],
        "PRINCIPAL": ["Principal"],
        "MANAGER": ["Manager"],
        "DIRECTOR": ["Director"],
    }
    for level, words in examples.items():
        for word in words:
            assert classify_seniority(word) == level, f"{word!r} should be {level}"
    assert classify_seniority("") == UNKNOWN_SENIORITY
    assert classify_seniority("unrelated text") == UNKNOWN_SENIORITY


# ---------------------------------------------------------------------------
# Pipeline ordering: hard gate before scoring, score never overrides
# ---------------------------------------------------------------------------
def test_score_node_only_scores_eligible_jobs():
    jobs = [
        {"id": "skip1", "title": "Senior", "description": "At least 9 years experience required.",
         "eligibility_decision": "skip"},
        {"id": "apply1", "title": "Junior", "description": "Python required.",
         "eligibility_decision": "apply"},
    ]
    state = _state(resume_text="Python developer", jobs=jobs)
    node = agent._make_score_jobs(FakeLLM())
    out = node(state)["jobs"]
    skip_job = next(j for j in out if j["id"] == "skip1")
    apply_job = next(j for j in out if j["id"] == "apply1")
    assert "match_score" not in skip_job
    assert "match_score" in apply_job


def test_semantic_score_never_overrides_hard_fail(monkeypatch):
    jobs = [{
        "id": "j1", "title": "Senior Data Engineer", "company": "Acme",
        "semantic_score": 95, "match_score": 95,
        "eligibility_decision": "skip",
        "eligibility_reasons": ["Requires 5+ years of experience; candidate has 0"],
    }]
    called = {"apply": False}

    def boom(job, resume):
        called["apply"] = True
        raise AssertionError("apply_to_job must never run for a hard-skipped job")

    monkeypatch.setattr(agent, "apply_to_job", boom)
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)

    out = apply_jobs(_state(resume_text="x", jobs=jobs))
    assert out["applications"][0]["status"] == "skipped"
    assert called["apply"] is False


def test_pipeline_orders_eligibility_before_scoring_and_apply(sample_pdf, monkeypatch):
    entry = Candidate(experience_years=2, skills=["python"], seniority="ENTRY_LEVEL",
                      role_family="software")
    jobs = [
        {"id": "hard", "title": "Senior Data Engineer", "company": "Acme",
         "url": "https://x.com/hard", "source": "indeed",
         "description": "At least 5 years of experience required. Python required."},
        {"id": "ok", "title": "Junior Developer", "company": "Corp",
         "url": "https://x.com/ok", "source": "linkedin",
         "description": "Python required. 1-2 years experience."},
    ]

    import jobhunter.automation.candidate as candidate_module

    monkeypatch.setattr(candidate_module, "build_candidate", lambda *a, **k: entry)
    monkeypatch.setattr(agent, "search_plan_jobs", lambda plan: jobs)
    monkeypatch.setattr(agent, "apply_to_job", lambda job, resume: {
        "job_id": job["id"], "job_title": job["title"], "company": job["company"],
        "status": "applied", "detail": "ok",
    })
    monkeypatch.setattr(agent, "send_job_alert_email", lambda *a, **k: None)

    result = run_job_hunter(str(sample_pdf), agent=create_agent(llm=FakeLLM()))

    hard = next(j for j in result["jobs"] if j["id"] == "hard")
    ok = next(j for j in result["jobs"] if j["id"] == "ok")

    # Hard-gated job: never scored, never applied.
    assert hard["eligibility_decision"] == "skip"
    assert "match_score" not in hard
    assert "semantic_score" not in hard
    assert any(a["job_id"] == "hard" and a["status"] == "skipped" for a in result["applications"])

    # Eligible job: scored and applied.
    assert ok["eligibility_decision"] == "apply"
    assert "match_score" in ok
    assert any(a["job_id"] == "ok" and a["status"] == "applied" for a in result["applications"])


def test_agent_build_candidate_uses_candidate_knowledge():
    candidate = real_build_candidate("Python developer with pandas and numpy.", profile={})
    assert isinstance(candidate, Candidate)
    assert candidate.experience_years is None or candidate.experience_years >= 0
