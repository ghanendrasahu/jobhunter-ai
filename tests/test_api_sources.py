"""Tests for third-party job API sources (Adzuna, JSearch, Jooble)."""

from unittest.mock import MagicMock, patch

from jobhunter.domains.search.api_sources import (
    search_adzuna_jobs,
    search_jooble_jobs,
    search_jsearch_jobs,
)


def _settings(**overrides):
    base = MagicMock(
        adzuna_app_id="app", adzuna_api_key="key",
        jsearch_api_key="js", jooble_api_key="jb",
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def test_adzuna_not_configured():
    with patch("jobhunter.domains.search.api_sources.get_settings",
               return_value=_settings(adzuna_app_id="", adzuna_api_key="")):
        assert search_adzuna_jobs("python") == []


def test_adzuna_returns_jobs():
    response = MagicMock()
    response.json.return_value = {
        "results": [
            {
                "id": "1",
                "title": "Python Dev",
                "company": {"display_name": "Acme"},
                "location": {"display_name": "Pune, India"},
                "description": "desc",
                "redirect_url": "https://adzuna.example/1",
                "salary_min": 100000,
                "salary_max": 200000,
            }
        ]
    }
    with patch("jobhunter.domains.search.api_sources.get_settings", return_value=_settings()), \
         patch("jobhunter.domains.search.api_sources.requests.get", return_value=response) as get:
        jobs = search_adzuna_jobs("python", location="Mumbai")
    assert len(jobs) == 1
    assert jobs[0]["source"] == "adzuna"
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["title"] == "Python Dev"
    get.assert_called_once()


def test_adzuna_failure_returns_empty():
    with patch("jobhunter.domains.search.api_sources.get_settings", return_value=_settings()), \
         patch("jobhunter.domains.search.api_sources.requests.get", side_effect=RuntimeError("net")):
        assert search_adzuna_jobs("python") == []


def test_jsearch_not_configured():
    with patch("jobhunter.domains.search.api_sources.get_settings", return_value=_settings(jsearch_api_key="")):
        assert search_jsearch_jobs("python") == []


def test_jsearch_returns_jobs():
    response = MagicMock()
    response.json.return_value = {
        "data": [
            {
                "job_title": "Analyst",
                "employer_name": "Globex",
                "job_city": "Bengaluru",
                "job_description": "data",
                "job_apply_link": "https://j.example/1",
                "job_min_salary": 50000,
                "job_max_salary": 90000,
                "job_salary_currency": "INR",
            }
        ]
    }
    with patch("jobhunter.domains.search.api_sources.get_settings", return_value=_settings()), \
         patch("jobhunter.domains.search.api_sources.requests.get", return_value=response):
        jobs = search_jsearch_jobs("analyst")
    assert len(jobs) == 1
    assert jobs[0]["source"] == "jsearch"
    assert jobs[0]["title"] == "Analyst"
    assert jobs[0]["url"] == "https://j.example/1"


def test_jooble_not_configured():
    with patch("jobhunter.domains.search.api_sources.get_settings", return_value=_settings(jooble_api_key="")):
        assert search_jooble_jobs("python") == []


def test_jooble_returns_jobs_and_maps_source():
    response = MagicMock()
    response.json.return_value = {
        "jobs": [
            {"title": "Dev", "company": "Acme", "location": "Delhi",
             "snippet": "s", "link": "https://j.example/1", "source": "naukri"},
        ]
    }
    with patch("jobhunter.domains.search.api_sources.get_settings", return_value=_settings()), \
         patch("jobhunter.domains.search.api_sources.requests.post", return_value=response) as post:
        jobs = search_jooble_jobs("dev")
    assert len(jobs) == 1
    assert jobs[0]["source"] == "naukri"
    assert jobs[0]["id"].startswith("naukri-jooble-")
    post.assert_called_once()


def test_jooble_failure_returns_empty():
    with patch("jobhunter.domains.search.api_sources.get_settings", return_value=_settings()), \
         patch("jobhunter.domains.search.api_sources.requests.post", side_effect=RuntimeError("net")):
        assert search_jooble_jobs("dev") == []
