"""Tests for the candidate knowledge base: model, extraction, and persistence."""

from jobhunter.automation.candidate import build_candidate, extract_candidate
from jobhunter.domains.candidate import Candidate, Education, seniority_for_years

RESUME = """
Aarav Sharma
Bengaluru

Email: aarav.sharma@gmail.com | Phone: +91 98765 43210

Data Scientist with 5+ years of experience.
Skills: Python, PyTorch, LangChain, SQL.
Education: B.Tech in Computer Science.
Preference: Hybrid
"""


class _JsonLLM:
    """Fake LLM returning a canned JSON payload."""

    def __init__(self, content: str):
        self._content = content

    def invoke(self, prompt):
        class _Response:
            content = ""

        _Response.content = self._content
        return _Response()


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
def test_candidate_roundtrip():
    cand = Candidate(
        full_name="X",
        email="x@y.com",
        skills=["python", "sql"],
        education=[Education(degree="B.Tech", institution="IIT")],
        experience_years=3,
    )
    rebuilt = Candidate.from_dict(cand.to_dict())
    assert rebuilt.full_name == "X"
    assert rebuilt.experience_years == 3
    assert rebuilt.skills == ["python", "sql"]
    assert rebuilt.education[0].degree == "B.Tech"
    assert rebuilt.education[0].institution == "IIT"


def test_candidate_from_dict_accepts_string_education():
    cand = Candidate.from_dict({"education": "B.Tech"})
    assert cand.education == [Education(degree="B.Tech")]


def test_candidate_known_fields():
    cand = Candidate(full_name="A", experience_years=5)
    assert cand.known("full_name")
    assert cand.known("experience_years")
    assert not cand.known("email")
    assert cand.known_fields == {"full_name", "experience_years"}


def test_candidate_unknown_seniority_not_known():
    cand = Candidate()
    assert not cand.known("seniority")
    assert not cand.known("experience_years")


def test_seniority_for_years_mapping():
    assert seniority_for_years(None) == "UNKNOWN"
    assert seniority_for_years(0) == "FRESHER"
    assert seniority_for_years(2) == "ENTRY_LEVEL"
    assert seniority_for_years(4) == "JUNIOR"
    assert seniority_for_years(8) == "MID_LEVEL"
    assert seniority_for_years(9) == "SENIOR"
    assert seniority_for_years(20) == "SENIOR"


# ---------------------------------------------------------------------------
# Heuristic extraction
# ---------------------------------------------------------------------------
def test_extract_candidate_heuristic_only():
    cand = extract_candidate(RESUME)
    assert cand.full_name == "Aarav Sharma"
    assert cand.email == "aarav.sharma@gmail.com"
    assert cand.experience_years == 5
    assert cand.role_family == "data_science"
    assert cand.seniority == "MID_LEVEL"
    assert cand.remote_mode == "hybrid"


def test_extract_candidate_never_guesses_years():
    cand = extract_candidate("Riya Patel\nEmail: r@x.com\nSkills: Python, SQL.")
    assert cand.experience_years is None
    assert not cand.known("experience_years")
    assert cand.seniority == "UNKNOWN"


def test_extract_candidate_empty_input_is_safe():
    cand = extract_candidate("")
    assert cand.full_name == ""
    assert cand.email == ""
    assert cand.experience_years is None
    assert cand.known_fields == set()


# ---------------------------------------------------------------------------
# LLM layering
# ---------------------------------------------------------------------------
def test_extract_candidate_llm_fills_gaps():
    llm = _JsonLLM(
        '{"projects": ["churn prediction", "RAG assistant"], '
        '"certifications": ["AWS ML"], '
        '"work_experience": [{"title": "Data Scientist", "company": "Acme", "duration": "3 years"}]}'
    )
    cand = extract_candidate(RESUME, llm=llm)
    assert "churn prediction" in cand.projects
    assert "AWS ML" in cand.certifications
    assert cand.work_experience and cand.work_experience[0].company == "Acme"


def test_llm_does_not_override_heuristic_or_profile():
    llm = _JsonLLM('{"email": "wrong@x.com", "full_name": "Wrong Name"}')
    cand = extract_candidate(RESUME, llm=llm)
    assert cand.email == "aarav.sharma@gmail.com"
    assert cand.full_name == "Aarav Sharma"


def test_extract_candidate_tolerates_bad_llm_output():
    cand = extract_candidate(RESUME, llm=_JsonLLM("sorry, no json here"))
    assert cand.full_name == "Aarav Sharma"
    assert cand.experience_years == 5


def test_extract_candidate_tolerates_llm_error():
    class _ErrorLLM:
        def invoke(self, prompt):
            raise RuntimeError("llm down")

    cand = extract_candidate(RESUME, llm=_ErrorLLM())
    assert cand.email == "aarav.sharma@gmail.com"


def test_profile_overrides_extraction():
    profile = {
        "full_name": "Confirmed Name",
        "email": "confirmed@x.com",
        "skills": ["python", "sql"],
        "experience_years": "3",
    }
    cand = extract_candidate(RESUME, profile=profile)
    assert cand.full_name == "Confirmed Name"
    assert cand.email == "confirmed@x.com"
    assert cand.experience_years == 3
    assert cand.skills == ["python", "sql"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def test_build_candidate_persists_and_reloads(monkeypatch, tmp_path):
    monkeypatch.setattr("jobhunter.storage.profiles.HISTORY_DIR", tmp_path / "history")
    build_candidate(RESUME)
    cand = build_candidate("")  # no resume; uses saved knowledge
    assert cand.full_name == "Aarav Sharma"
    assert cand.role_family == "data_science"


def test_build_candidate_refresh_recomputes(monkeypatch, tmp_path):
    monkeypatch.setattr("jobhunter.storage.profiles.HISTORY_DIR", tmp_path / "history")
    build_candidate(RESUME)
    cand = build_candidate(RESUME, refresh=True)
    assert cand.email == "aarav.sharma@gmail.com"
