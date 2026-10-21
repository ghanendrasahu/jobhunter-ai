"""Tests for the FastAPI REST endpoints."""

import io
from pathlib import Path

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


def _app(api_key: str = "", rate_limit: str = "50/minute", cors_origins: str = "") -> TestClient:
    settings = Settings(
        jobhunter_api_key=api_key,
        api_rate_limit=rate_limit,
        cors_origins=cors_origins,
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


# --- CORS -------------------------------------------------------------------

def test_cors_default_same_origin_only():
    """No CORS_ORIGINS configured -> no CORS middleware, browser preflight denied."""
    client = _app()
    response = client.options("/health", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_cors_explicit_origins_allow_preflight():
    client = _app(cors_origins="https://jobs.example.com")
    response = client.options(
        "/health",
        headers={"Origin": "https://jobs.example.com", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers["access-control-allow-origin"] == "https://jobs.example.com"


def test_cors_wildcard_disables_credentials():
    client = _app(cors_origins="*")
    response = client.get("/health", headers={"Origin": "https://any.example.com"})
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in {k.lower() for k in response.headers}


# --- Readiness --------------------------------------------------------------

def test_readiness_ready(client: TestClient):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_readiness_reports_unusable_upload_dir():
    """A blocked upload dir yields 503 with a reason instead of a crash."""
    import tempfile

    blocker_dir = Path(tempfile.mkdtemp())
    blocker = blocker_dir / "blocker"  # a FILE where a directory is expected
    blocker.write_text("meant to be a file", encoding="utf-8")
    settings = Settings(
        jobhunter_api_key="",
        openai_api_key="",
        upload_dir=blocker / "uploads",
    )
    with TestClient(create_app(settings)) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["problems"]
