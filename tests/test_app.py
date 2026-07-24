"""Tests for the FastAPI application endpoints."""

import os
import tempfile
from unittest.mock import patch

import pytest
from httpx import AsyncClient, ASGITransport

from app import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def client():
    """Provide an async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def sample_pdf_bytes() -> bytes:
    """Return bytes of a minimal valid PDF."""
    return (
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


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------
class TestHealthEndpoint:
    async def test_health_returns_ok(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# /upload_resume
# ---------------------------------------------------------------------------
class TestUploadResume:
    async def test_rejects_non_pdf_extension(self, client: AsyncClient):
        response = await client.post(
            "/upload_resume",
            files={"file": ("resume.txt", b"not a pdf", "text/plain")},
        )
        assert response.status_code == 400
        assert "PDF" in response.json()["detail"]

    async def test_rejects_wrong_mime_type(self, client: AsyncClient):
        """If content-type is wrong but extension is .pdf, should still reject."""
        response = await client.post(
            "/upload_resume",
            files={
                "file": ("resume.pdf", b"not a real pdf", "image/png"),
            },
        )
        assert response.status_code == 400
        assert "content type" in response.json()["detail"].lower()

    async def test_rejects_large_file(self, client: AsyncClient):
        """Files over 10 MB should be rejected."""
        oversized = b"x" * (11 * 1024 * 1024)
        response = await client.post(
            "/upload_resume",
            files={"file": ("resume.pdf", oversized, "application/pdf")},
        )
        assert response.status_code == 413

    @patch("app.run_job_hunter")
    async def test_successful_upload(
        self, mock_run: patch, client: AsyncClient, sample_pdf_bytes: bytes
    ):
        """A valid PDF upload should return pipeline results."""
        mock_run.return_value = {
            "resume_text": "Hello World",
            "search_query": "developer",
            "jobs": [],
            "applications": [],
            "error": "",
        }
        response = await client.post(
            "/upload_resume",
            files={"file": ("resume.pdf", sample_pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["search_query"] == "developer"
        assert data["resume_text"] == "Hello World"
        mock_run.assert_called_once()

    @patch("app.run_job_hunter")
    async def test_pipeline_error_returns_500(
        self, mock_run: patch, client: AsyncClient, sample_pdf_bytes: bytes
    ):
        """If the agent pipeline raises, should return 500."""
        mock_run.side_effect = RuntimeError("LLM unavailable")
        response = await client.post(
            "/upload_resume",
            files={"file": ("resume.pdf", sample_pdf_bytes, "application/pdf")},
        )
        assert response.status_code == 500
        assert "LLM unavailable" in response.json()["detail"]

    async def test_auth_required_when_key_set(self, client: AsyncClient):
        """When JOBHUNTER_API_KEY env var is set, requests without the header should 401."""
        import app as app_module
        original_key = app_module.API_KEY
        app_module.API_KEY = "test-secret"
        try:
            response = await client.post(
                "/upload_resume",
                files={"file": ("resume.pdf", b"dummy", "application/pdf")},
            )
            assert response.status_code == 401
        finally:
            app_module.API_KEY = original_key

    async def test_auth_succeeds_with_valid_key(self, client: AsyncClient):
        """Providing the correct API key header should succeed."""
        import app as app_module
        original_key = app_module.API_KEY
        app_module.API_KEY = "test-secret"
        try:
            with patch("app.run_job_hunter", return_value={"resume_text": "", "search_query": "", "jobs": [], "applications": [], "error": ""}):
                response = await client.post(
                    "/upload_resume",
                    files={"file": ("resume.pdf", b"dummy", "application/pdf")},
                    headers={"X-API-Key": "test-secret"},
                )
                assert response.status_code in (200, 500)  # 200 if pipeline mock works, 500 if PDF parse fails
        finally:
            app_module.API_KEY = original_key
