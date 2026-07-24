"""Tests for the LangGraph agent pipeline."""

from unittest.mock import patch, MagicMock

import pytest

from agent import (
    JobHunterState,
    extract_resume,
    generate_query,
    find_jobs,
    apply_jobs,
    run_job_hunter,
)


# ---------------------------------------------------------------------------
# extract_resume
# ---------------------------------------------------------------------------
class TestExtractResume:
    def test_success(self):
        state: JobHunterState = {
            "file_path": "/path/to/resume.pdf",
            "resume_text": "",
            "search_query": "",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        with patch("agent.extract_text_from_pdf", return_value="resume content"):
            result = extract_resume(state)
        assert result["resume_text"] == "resume content"
        assert result["error"] == ""

    def test_missing_file_path(self):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "",
            "search_query": "",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        result = extract_resume(state)
        assert "error" in result
        assert "file_path missing" in result["error"].lower()

    def test_extraction_failure(self):
        state: JobHunterState = {
            "file_path": "/bad/path.pdf",
            "resume_text": "",
            "search_query": "",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        with patch("agent.extract_text_from_pdf", side_effect=Exception("PDF error")):
            result = extract_resume(state)
        assert "PDF error" in result["error"]


# ---------------------------------------------------------------------------
# generate_query
# ---------------------------------------------------------------------------
class TestGenerateQuery:
    def test_success(self, mock_llm: MagicMock):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "Experienced Python developer",
            "search_query": "",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        mock_response = MagicMock()
        mock_response.content = "Python developer"
        mock_llm.invoke.return_value = mock_response

        with patch("agent._llm", mock_llm):
            result = generate_query(state)
        assert result["search_query"] == "Python developer"
        assert result["error"] == ""

    def test_empty_resume_returns_error(self):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "",
            "search_query": "",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        result = generate_query(state)
        assert "error" in result
        assert "resume_text missing" in result["error"].lower()

    def test_llm_failure(self, mock_llm: MagicMock):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "Resume content",
            "search_query": "",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        mock_llm.invoke.side_effect = Exception("OpenAI error")
        with patch("agent._llm", mock_llm):
            result = generate_query(state)
        assert "OpenAI error" in result["error"]


# ---------------------------------------------------------------------------
# find_jobs
# ---------------------------------------------------------------------------
class TestFindJobs:
    def test_success(self):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "",
            "search_query": "python developer",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        fake_jobs = [{"id": "1", "title": "Python Dev"}]
        with patch("agent.search_adzuna_jobs", return_value=fake_jobs):
            result = find_jobs(state)
        assert len(result["jobs"]) == 1
        assert result["error"] == ""

    def test_missing_query(self):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "",
            "search_query": "",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        result = find_jobs(state)
        assert "error" in result
        assert "search_query missing" in result["error"].lower()

    def test_search_failure(self):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "",
            "search_query": "python",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        with patch("agent.search_adzuna_jobs", side_effect=Exception("API error")):
            result = find_jobs(state)
        assert "API error" in result["error"]


# ---------------------------------------------------------------------------
# apply_jobs
# ---------------------------------------------------------------------------
class TestApplyJobs:
    def test_applies_to_all_jobs(self):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "resume",
            "search_query": "",
            "jobs": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
            "applications": [],
            "error": "",
        }
        with patch("agent.apply_to_job", return_value={"status": "applied"}):
            result = apply_jobs(state)
        assert len(result["applications"]) == 3
        assert result["error"] == ""

    def test_no_jobs(self):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "resume",
            "search_query": "",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        result = apply_jobs(state)
        assert result["applications"] == []
        assert result["error"] == ""

    def test_partial_failure_still_continues(self):
        state: JobHunterState = {
            "file_path": "",
            "resume_text": "resume",
            "search_query": "",
            "jobs": [{"id": "1"}, {"id": "2"}],
            "applications": [],
            "error": "",
        }

        def _mock_apply(job, _):
            if job["id"] == "1":
                return {"status": "applied"}
            raise RuntimeError("Failed")

        with patch("agent.apply_to_job", side_effect=_mock_apply):
            result = apply_jobs(state)
        assert len(result["applications"]) == 1
        assert result["applications"][0]["status"] == "applied"


# ---------------------------------------------------------------------------
# run_job_hunter (integration)
# ---------------------------------------------------------------------------
class TestRunJobHunter:
    def test_happy_path(self):
        """End-to-end test with all mocks."""
        mock_extract = patch("agent.extract_text_from_pdf", return_value="dev resume")
        mock_llm_response = MagicMock()
        mock_llm_response.content = "developer"
        mock_llm = patch("agent._llm")
        mock_llm_instance = MagicMock()
        mock_llm_instance.invoke.return_value = mock_llm_response
        mock_search = patch(
            "agent.search_adzuna_jobs",
            return_value=[{"id": "1", "company": "Co", "title": "Dev"}],
        )
        mock_apply = patch("agent.apply_to_job", return_value={"status": "applied"})

        with mock_extract, mock_llm as m_llm, mock_search, mock_apply:
            m_llm.return_value = mock_llm_instance
            result = run_job_hunter("/path/to/resume.pdf")

        assert "resume_text" in result
        assert "search_query" in result
        assert "jobs" in result
        assert "applications" in result
        assert len(result["applications"]) == 1

    def test_handles_node_failure_gracefully(self):
        """If a node fails, the pipeline should still produce a result."""
        with patch("agent.extract_text_from_pdf", side_effect=Exception("fail")):
            result = run_job_hunter("/path/to/resume.pdf")
        assert "error" in result
        assert "fail" in result["error"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_llm() -> MagicMock:
    return MagicMock()
