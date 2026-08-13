"""Job search via third-party APIs (Adzuna, Jooble). Optional; keys in `.env`."""

from __future__ import annotations

import hashlib
import logging

import requests

from jobhunter.config import get_settings

logger = logging.getLogger(__name__)


def search_adzuna_jobs(query: str, location: str = "India") -> list[dict]:
    """Search Adzuna's India feed. Returns [] when not configured or on failure."""
    settings = get_settings()
    if not settings.adzuna_app_id or not settings.adzuna_api_key:
        return []

    try:
        url = "https://api.adzuna.com/v1/api/jobs/in/search/1"
        params = {
            "app_id": settings.adzuna_app_id,
            "app_key": settings.adzuna_api_key,
            "what": query,
            "where": location,
            "results_per_page": 15,
            "sort_by": "date",
        }
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()

        jobs: list[dict] = []
        for item in data.get("results", []):
            jobs.append({
                "id": f"adzuna-{item.get('id')}",
                "title": item.get("title", "Unknown"),
                "company": (item.get("company") or {}).get("display_name", "Unknown"),
                "location": (item.get("location") or {}).get("display_name", "India") or "India",
                "description": item.get("description", ""),
                "url": item.get("redirect_url", ""),
                "salary_min": item.get("salary_min"),
                "salary_max": item.get("salary_max"),
                "salary_currency": "INR",
                "source": "adzuna",
            })
        return jobs
    except Exception as exc:
        logger.warning("Adzuna search failed: %s", exc)
        return []


def search_jsearch_jobs(query: str, country: str = "in") -> list[dict]:
    """Search the JSearch API (RapidAPI). Returns [] when not configured or on failure."""
    settings = get_settings()
    if not settings.jsearch_api_key:
        return []

    try:
        url = "https://jsearch.p.rapidapi.com/search"
        headers = {
            "x-rapidapi-key": settings.jsearch_api_key,
            "x-rapidapi-host": "jsearch.p.rapidapi.com",
        }
        params = {"query": query, "country": country, "num_pages": 1}
        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()

        jobs: list[dict] = []
        for item in response.json().get("data", [])[:15]:
            link = item.get("job_apply_link", "")
            jobs.append({
                "id": f"jsearch-{hashlib.md5(link.encode()).hexdigest()[:8]}",
                "title": item.get("job_title", "Unknown"),
                "company": item.get("employer_name", "Unknown"),
                "location": item.get("job_city", "India") or "India",
                "description": item.get("job_description", "") or "",
                "url": link,
                "salary_min": item.get("job_min_salary"),
                "salary_max": item.get("job_max_salary"),
                "salary_currency": item.get("job_salary_currency"),
                "source": "jsearch",
            })
        return jobs
    except Exception as exc:
        logger.warning("JSearch search failed: %s", exc)
        return []


def search_jooble_jobs(query: str, location: str = "India") -> list[dict]:
    """Search Jooble's API. Returns [] when not configured or on failure."""
    settings = get_settings()
    if not settings.jooble_api_key:
        return []

    try:
        url = f"https://jooble.org/api/{settings.jooble_api_key}"
        response = requests.post(url, json={"keywords": query, "location": location, "page": 1}, timeout=20)
        response.raise_for_status()

        src_map = {
            "naukri": "naukri", "indeed": "indeed", "linkedin": "linkedin",
            "monster": "monster", "timesjobs": "timesjobs", "shine": "shine",
        }
        jobs: list[dict] = []
        for item in response.json().get("jobs", [])[:15]:
            source = (item.get("source") or "").lower()
            mapped = next((v for k, v in src_map.items() if k in source), "jooble")
            url_link = item.get("link", "")
            jobs.append({
                "id": f"{mapped}-jooble-{hashlib.md5(url_link.encode()).hexdigest()[:8]}",
                "title": item.get("title", "Unknown"),
                "company": item.get("company", "Unknown"),
                "location": item.get("location", "India"),
                "description": item.get("snippet", "") or "",
                "url": url_link,
                "salary_min": None,
                "salary_max": None,
                "salary_currency": None,
                "source": mapped,
            })
        return jobs
    except Exception as exc:
        logger.warning("Jooble search failed: %s", exc)
        return []
