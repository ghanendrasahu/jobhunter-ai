"""Tests for utility functions (PDF extraction, job search, application)."""

import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest
import requests

from utils import extract_text_from_pdf, search_adzuna_jobs, apply_to_job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def sample_pdf_path() -> str:
    """Create a minimal valid PDF for extraction testing."""
    # Minimal PDF that says "Hello World"
    content = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length 44>>stream\n"
        b"BT /F1 12 Tf 100 700 Td (Hello World) Tj ET\n"
        b"endstream\n"
        b"endobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n"
        b"0 6\n"
        b"0000000000 65535 f \n"
        b"0000000009 00000 n \n"
        b"0000000058 00000 n \n"
        b"0000000115 00000 n \n"
        b"0000000266 00000 n \n"
        b"0000000362 00000 n \n"
        b"trailer<</Size 6/Root 1 0 R>>\n"
        b"startxref\n"
        b"417\n"
        b"%%EOF\n"
    )
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(content)
    tmp.close()
    yield tmp.name
    os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# extract_text_from_pdf
# ---------------------------------------------------------------------------
class TestExtractTextFromPdf:
    def test_extracts_text(self, sample_pdf_path: str):
        text = extract_text_from_pdf(sample_pdf_path)
        assert "Hello World" in text

    def test_returns_string(self, sample_pdf_path: str):
        text = extract_text_from_pdf(sample_pdf_path)
        assert isinstance(text, str)

    def test_nonexistent_file_raises(self):
        with pytest.raises(Exception):
            extract_text_from_pdf("/nonexistent/path.pdf")

    def test_empty_pdf(self):
        """A PDF with no text content should return an empty string."""
        content = (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"xref\n"
            b"0 4\n"
            b"0000000000 65535 f \n"
            b"0000000009 00000 n \n"
            b"0000000058 00000 n \n"
            b"0000000115 00000 n \n"
            b"trailer<</Size 4/Root 1 0 R>>\n"
            b"startxref\n"
            b"207\n"
            b"%%EOF\n"
        )
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(content)
        tmp.close()
        try:
            text = extract_text_from_pdf(tmp.name)
            assert text == "" or text == "\n"
        finally:
            os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# search_adzuna_jobs
# ---------------------------------------------------------------------------
class TestSearchAdzunaJobs:
    @patch("utils.os.getenv")
    def test_no_credentials_returns_fallback(self, mock_getenv: MagicMock):
        """When Adzuna creds are missing, should return simulated jobs."""
        mock_getenv.side_effect = lambda key, default=None: None
        jobs = search_adzuna_jobs("python developer")
        assert len(jobs) == 5
        assert all(j["source"] == "simulated" for j in jobs)

    @patch("utils.requests.get")
    @patch("utils.os.getenv")
    def test_api_failure_returns_fallback(
        self, mock_getenv: MagicMock, mock_get: MagicMock
    ):
        """When the API call fails, should fall back to simulated jobs."""
        mock_getenv.side_effect = lambda key, default=None: (
            "app-id" if "APP_ID" in key else "api-key"
        )
        mock_get.side_effect = requests.RequestException("Network error")
        jobs = search_adzuna_jobs("python developer")
        assert len(jobs) == 5
        assert all(j["source"] == "simulated" for j in jobs)

    @patch("utils.requests.get")
    @patch("utils.os.getenv")
    def test_successful_api_call(
        self, mock_getenv: MagicMock, mock_get: MagicMock
    ):
        mock_getenv.side_effect = lambda key, default=None: (
            "app-id" if "APP_ID" in key else "api-key"
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "123",
                    "title": "Python Developer",
                    "company": {"display_name": "Acme Corp"},
                    "location": {"display_name": "London"},
                    "description": "Great job",
                    "redirect_url": "https://example.com/apply",
                    "salary_min": 50000,
                    "salary_max": 70000,
                }
            ]
        }
        mock_get.return_value = mock_response
        jobs = search_adzuna_jobs("python developer")
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Python Developer"
        assert jobs[0]["company"] == "Acme Corp"
        assert jobs[0]["source"] == "adzuna"

    @patch("utils.requests.get")
    @patch("utils.os.getenv")
    def test_empty_results(self, mock_getenv: MagicMock, mock_get: MagicMock):
        mock_getenv.side_effect = lambda key, default=None: (
            "app-id" if "APP_ID" in key else "api-key"
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {"results": []}
        mock_get.return_value = mock_response
        jobs = search_adzuna_jobs("some obscure role")
        assert jobs == []

    @patch("utils.requests.get")
    @patch("utils.os.getenv")
    def test_missing_company_field(
        self, mock_getenv: MagicMock, mock_get: MagicMock
    ):
        mock_getenv.side_effect = lambda key, default=None: (
            "app-id" if "APP_ID" in key else "api-key"
        )
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {
                    "id": "456",
                    "title": "Engineer",
                    # company key missing entirely
                    "description": "desc",
                }
            ]
        }
        mock_get.return_value = mock_response
        jobs = search_adzuna_jobs("engineer")
        assert jobs[0]["company"] == "Unknown Company"


# ---------------------------------------------------------------------------
# apply_to_job
# ---------------------------------------------------------------------------
class TestApplyToJob:
    def test_returns_dict_with_expected_keys(self):
        job = {"id": "abc", "title": "Dev", "company": "Co"}
        result = apply_to_job(job, "resume text")
        assert result["job_id"] == "abc"
        assert result["job_title"] == "Dev"
        assert result["company"] == "Co"
        assert result["status"] == "applied"

    def test_handles_missing_fields_gracefully(self):
        job = {}
        result = apply_to_job(job, "")
        assert result["job_id"] is None
        assert result["status"] == "applied"
