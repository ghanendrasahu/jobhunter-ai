"""Job search via third-party APIs (Adzuna, Jooble). Optional; keys in `.env`."""

from __future__ import annotations

import hashlib
import logging
from typing import Dict, List

import requests

from jobhunter.config import get_settings

logger = logging.getLogger(__name__)


def search_adzuna_jobs(query: str, location: str = "India") -> List[Dict]:
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

        jobs: List[Dict] = []
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


def search_jooble_jobs(query: str, location: str = "India") -> List[Dict]:
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
        jobs: List[Dict] = []
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
