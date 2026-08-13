"""Tests for the FastAPI REST endpoints."""

import io

import pytest
from fastapi.testclient import TestClient

from conftest import make_pdf
from jobhunter.api.server import create_app
from jobhunter.config import Settings

PIPELINE_RESULT = {
    "file_path": "/tmp/x.pdf",
    "resume_text": "Software Engineer Python",
    "search_query": "Python Developer",
    "jobs": [{"id": "j1", "title": "Python Dev", "company": "Acme", "url": "https://x.com/j1"}],
    "applications": [{"job_id": "j1", "job_title": "Python Dev", "company": "Acme", "status": "applied"}],
    "error": "",
}


def _app(api_key: str = "", rate_limit: str = "50/minute") -> TestClient:
    settings = Settings(
        jobhunter_api_key=api_key,
        api_rate_limit=rate_limit,
        openai_api_key="",
    )
    return TestClient(create_app(settings))


@pytest.fixture(autouse=True)
def _patch_pipeline(monkeypatch):
    """Never run the real pipeline (scraping/LLM) from API tests."""
    from jobhunter.api import server

    monkeypatch.setattr(server, "run_job_hunter", lambda path: PIPELINE_RESULT)


@pytest.fixture
def client() -> TestClient:
    return _app()


def _upload(client: TestClient, *, name: str = "resume.pdf", content: bytes | None = None, headers=None):
    content = content if content is not None else make_pdf("Python Developer resume")
    files = {"file": (name, io.BytesIO(content), "application/pdf")}
    return client.post("/upload_resume", files=files, headers=headers)


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_success(client: TestClient):
    response = _upload(client)
    assert response.status_code == 200
    assert response.json()["search_query"] == "Python Developer"


def test_rejects_non_pdf_extension(client: TestClient):
    response = _upload(client, name="resume.txt", content=b"hello")
    assert response.status_code == 400


def test_rejects_wrong_mime(client: TestClient):
    files = {"file": ("resume.pdf", io.BytesIO(b"hello"), "text/plain")}
    response = client.post("/upload_resume", files=files)
    assert response.status_code == 400


def test_rejects_oversized_file(client: TestClient):
    big = make_pdf("A" * 100) + b"\x00" * (12 * 1024 * 1024)  # ~12 MB
    response = _upload(client, content=big)
    assert response.status_code == 413


def test_auth_requires_key():
    client = _app(api_key="secret-123")
    response = _upload(client)
    assert response.status_code == 401

    response = _upload(client, headers={"X-API-Key": "secret-123"})
    assert response.status_code == 200


def test_rate_limiting():
    client = _app(rate_limit="2/minute")
    assert _upload(client).status_code == 200
    assert _upload(client).status_code == 200
    assert _upload(client).status_code == 429
