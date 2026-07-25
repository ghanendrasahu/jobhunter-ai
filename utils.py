"""Utility functions for resume parsing, job searching, and application simulation."""

import json
import os
import time
import hashlib
import logging
import webbrowser
from typing import List, Dict, Optional
from pathlib import Path

from dotenv import load_dotenv
import requests
from pypdf import PdfReader

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Application history database
# ---------------------------------------------------------------------------
HISTORY_DIR = Path("history")
HISTORY_DIR.mkdir(exist_ok=True)


def _resume_id(resume_text: str) -> str:
    """Generate a stable ID for a resume based on its text content."""
    return hashlib.sha256(resume_text.encode("utf-8")).hexdigest()[:12]


def _history_path(resume_id: str) -> Path:
    return HISTORY_DIR / f"{resume_id}.json"


def load_applied_jobs(resume_text: str) -> set:
    """Load the set of already-applied job IDs for this resume."""
    rid = _resume_id(resume_text)
    path = _history_path(rid)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return set(data.get("applied_job_ids", []))
        except (json.JSONDecodeError, KeyError):
            return set()
    return set()


def save_applied_jobs(resume_text: str, job_ids: List[str]) -> None:
    """Persist applied job IDs so they are never applied to again."""
    rid = _resume_id(resume_text)
    path = _history_path(rid)
    existing = set()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            existing = set(data.get("applied_job_ids", []))
        except (json.JSONDecodeError, KeyError):
            pass
    existing.update(job_ids)
    path.write_text(
        json.dumps({"resume_id": rid, "applied_job_ids": sorted(existing)}, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved %d applied job IDs for resume %s", len(existing), rid)


def get_application_history(resume_text: str) -> Dict:
    """Get full application history for a resume."""
    rid = _resume_id(resume_text)
    path = _history_path(rid)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    return {"resume_id": rid, "applied_job_ids": []}


def list_all_histories() -> List[Dict]:
    """List all resume histories (for the UI sidebar)."""
    histories = []
    for path in HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            histories.append(data)
        except (json.JSONDecodeError, KeyError):
            pass
    return histories


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------
def extract_text_from_pdf(file_path: str) -> str:
    """Extract raw text from a PDF file using pypdf."""
    logger.info("Extracting text from PDF: %s", file_path)
    reader = PdfReader(file_path)
    text = []
    for i, page in enumerate(reader.pages):
        page_text = page.extract_text() or ""
        text.append(page_text)
        logger.debug("Page %d extracted: %d chars", i + 1, len(page_text))
    result = "\n".join(text)
    logger.info("PDF extraction complete: %d chars total", len(result))
    return result


# ---------------------------------------------------------------------------
# Job Search — Open job portals directly in user's browser
# ---------------------------------------------------------------------------
JOB_PORTALS = {
    "naukri": {
        "name": "Naukri",
        "search_url": "https://www.naukri.com/{query}-jobs-in-india",
        "badge_color": "#e9692c",
        "icon": "🟠",
    },
    "indeed": {
        "name": "Indeed",
        "search_url": "https://in.indeed.com/jobs?q={query}&l=India",
        "badge_color": "#2164f3",
        "icon": "🔵",
    },
    "linkedin": {
        "name": "LinkedIn",
        "search_url": "https://www.linkedin.com/jobs/search/?keywords={query}&location=India",
        "badge_color": "#0a66c2",
        "icon": "🟣",
    },
    "monster": {
        "name": "Monster",
        "search_url": "https://www.monsterindia.com/search/{query}-jobs-in-india",
        "badge_color": "#6c2bd9",
        "icon": "🟤",
    },
    "timesjobs": {
        "name": "TimesJobs",
        "search_url": "https://www.timesjobs.com/candidate/job-search.html?searchType=home&searchTextCli={query}&from=submit",
        "badge_color": "#dc3545",
        "icon": "🔴",
    },
    "shine": {
        "name": "Shine",
        "search_url": "https://www.shine.com/job-search/{query}-jobs-in-india",
        "badge_color": "#fd7e14",
        "icon": "🟧",
    },
    "google_jobs": {
        "name": "Google Jobs (All Sources)",
        "search_url": "https://www.google.com/search?q={query}+jobs+in+India&ibp=htl;jobs",
        "badge_color": "#4285f4",
        "icon": "🔍",
    },
}


def build_portal_urls(query: str) -> List[Dict]:
    """Build search URLs for all major Indian job portals.

    Returns list of dicts with: source, name, url, badge_color, icon.
    These can be opened directly in the browser where the user is already logged in.
    """
    from urllib.parse import quote
    encoded_query = quote(query)
    urls = []
    for key, portal in JOB_PORTALS.items():
        url = portal["search_url"].replace("{query}", encoded_query)
        urls.append({
            "id": f"{key}-search",
            "source": key,
            "name": portal["name"],
            "url": url,
            "badge_color": portal["badge_color"],
            "icon": portal["icon"],
            "title": f"{portal['name']}: {query}",
            "company": f"Search on {portal['name']}",
            "location": "India",
            "description": f"Search for '{query}' jobs on {portal['name']}. Opens in your browser where you can apply directly with your logged-in account.",
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "is_portal_link": True,
        })
    return urls


def open_job_portals(query: str) -> List[Dict]:
    """Open all major Indian job portals in the user's browser with the search query.

    The user must be logged into these portals in their browser to see personalized results.
    Returns portal links as "jobs" so the UI can display them.
    """
    portal_jobs = build_portal_urls(query)
    logger.info("Built %d portal search links for query: %s", len(portal_jobs), query)
    return portal_jobs


def search_adzuna_jobs(query: str, location: str = "India") -> List[Dict]:
    """Fetch real job listings from Adzuna API (India region).

    FREE: Sign up at https://developer.adzuna.com/ — get APP_ID & API_KEY.
    Put them in .env as ADZUNA_APP_ID and ADZUNA_API_KEY.
    Falls back gracefully if not configured.
    """
    app_id = os.getenv("ADZUNA_APP_ID")
    api_key = os.getenv("ADZUNA_API_KEY")
    if not app_id or not api_key:
        return []

    try:
        base_url = f"https://api.adzuna.com/v1/api/jobs/in/search/1"
        params = {
            "app_id": app_id,
            "app_key": api_key,
            "what": query,
            "where": location,
            "content_type": "application/json",
            "results_per_page": 15,
            "sort_by": "date",
            "max_days_old": 30,
        }
        logger.info("Searching Adzuna India: query=%s", query)
        response = requests.get(base_url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        jobs = []
        for item in results:
            jobs.append({
                "id": f"adzuna-{item.get('id')}",
                "title": item.get("title", "Unknown Title"),
                "company": (item.get("company", {}) or {}).get("display_name", "Unknown Company"),
                "location": item.get("location", {}).get("display_name", "India") if item.get("location") else "India",
                "description": item.get("description", ""),
                "url": item.get("redirect_url", ""),
                "salary_min": item.get("salary_min"),
                "salary_max": item.get("salary_max"),
                "salary_currency": "INR",
                "source": "adzuna",
            })
        if jobs:
            logger.info("Adzuna India returned %d real jobs", len(jobs))
            return jobs
    except Exception as exc:
        logger.warning("Adzuna API failed (%s)", exc)
    return []


def search_jooble_jobs(query: str, location: str = "India") -> List[Dict]:
    """Fetch real job listings from Jooble API (requires JOOBLE_API_KEY in .env)."""
    api_key = os.getenv("JOOBLE_API_KEY")
    if not api_key:
        return []

    try:
        url = f"https://jooble.org/api/{api_key}"
        payload = {"keywords": query, "location": location, "page": 1, "searchMode": 1}
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        data = response.json()
        results = data.get("jobs", [])
        jobs = []
        for item in results[:15]:
            source = (item.get("source", "") or "").lower()
            source_map = {"naukri": "naukri", "indeed": "indeed", "linkedin": "linkedin",
                          "monster": "monster", "timesjobs": "timesjobs", "shine": "shine"}
            mapped_source = "jooble"
            for key, val in source_map.items():
                if key in source:
                    mapped_source = val
                    break
            url_link = item.get("link", "")
            job_id = f"{mapped_source}-jooble-{hashlib.md5(url_link.encode()).hexdigest()[:8]}"
            jobs.append({
                "id": job_id,
                "title": item.get("title", "Unknown"),
                "company": item.get("company", "Unknown Company"),
                "location": item.get("location", "India"),
                "description": item.get("snippet", "") or item.get("description", ""),
                "url": url_link,
                "salary_min": None,
                "salary_max": None,
                "salary_currency": None,
                "source": mapped_source,
            })
        if jobs:
            logger.info("Jooble returned %d real jobs", len(jobs))
            return jobs
    except Exception as exc:
        logger.warning("Jooble API failed (%s)", exc)
    return []


def search_jsearch_jobs(query: str, location: str = "India") -> List[Dict]:
    """Fetch real job listings from JSearch API (requires JSEARCH_API_KEY in .env)."""
    api_key = os.getenv("JSEARCH_API_KEY")
    if not api_key:
        return []

    try:
        url = "https://jsearch.p.rapidapi.com/search"
        headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": "jsearch.p.rapidapi.com"}
        params = {"query": f"{query} in {location}", "page": "1", "num_pages": "1", "country": "in", "date_posted": "month"}
        response = requests.get(url, headers=headers, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        results = data.get("data", [])
        jobs = []
        for item in results[:15]:
            via = (item.get("job_publisher", "") or "").lower()
            source_map = {"indeed": "indeed", "linkedin": "linkedin", "glassdoor": "glassdoor", "naukri": "naukri", "monster": "monster"}
            mapped_source = "jsearch"
            for key, val in source_map.items():
                if key in via:
                    mapped_source = val
                    break
            url_link = item.get("job_google_link", "") or item.get("job_apply_link", "")
            job_id = f"{mapped_source}-js-{hashlib.md5(url_link.encode()).hexdigest()[:8] if url_link else str(hash(item))[:8]}"
            jobs.append({
                "id": job_id,
                "title": item.get("job_title", "Unknown"),
                "company": item.get("employer_name", "Unknown Company"),
                "location": item.get("job_city", "") or item.get("job_country", "India"),
                "description": item.get("job_description", "") or "",
                "url": url_link,
                "salary_min": item.get("job_min_salary"),
                "salary_max": item.get("job_max_salary"),
                "salary_currency": "INR",
                "source": mapped_source,
            })
        if jobs:
            logger.info("JSearch returned %d real jobs", len(jobs))
            return jobs
    except Exception as exc:
        logger.warning("JSearch API failed (%s)", exc)
    return []


# ---------------------------------------------------------------------------
# Master job search
# ---------------------------------------------------------------------------
def search_all_jobs(query: str) -> List[Dict]:
    """Search for jobs using ALL available methods:

    1. Opens Naukri, Indeed, LinkedIn, Monster, TimesJobs, Shine, Google Jobs
       directly in your browser (you must be logged in)
    2. Optionally fetches via API if keys are configured

    Returns portal links + any API results.
    """
    all_jobs: List[Dict] = []
    seen_urls: set = set()

    # Always build portal links (these open in the user's browser)
    portal_jobs = build_portal_urls(query)
    for job in portal_jobs:
        url_key = hashlib.md5(job.get("url", "").encode()).hexdigest()[:12]
        if url_key not in seen_urls:
            seen_urls.add(url_key)
            all_jobs.append(job)

    # Try API sources if configured
    api_sources = [
        ("Jooble", lambda: search_jooble_jobs(query)),
        ("JSearch", lambda: search_jsearch_jobs(query)),
        ("Adzuna", lambda: search_adzuna_jobs(query)),
    ]
    for source_name, search_fn in api_sources:
        try:
            jobs = search_fn()
            if jobs:
                for job in jobs:
                    url_key = hashlib.md5(job.get("url", "").encode()).hexdigest()[:12]
                    if url_key not in seen_urls:
                        seen_urls.add(url_key)
                        all_jobs.append(job)
                logger.info("%s: added %d real jobs", source_name, len(jobs))
        except Exception as exc:
            logger.warning("%s search failed: %s", source_name, exc)

    logger.info("Total job results: %d (%d portal links, %d API)", len(all_jobs), len(portal_jobs), len(all_jobs) - len(portal_jobs))
    return all_jobs


# ---------------------------------------------------------------------------
# Application simulation (with duplicate detection)
# ---------------------------------------------------------------------------
def apply_to_job(job: Dict, resume_text: str) -> Dict:
    """Record an application, skipping if already applied for this resume.

    For portal links, opens the job search page in the user's browser.
    The user then applies manually on the portal (they're already logged in).
    """
    job_id = job.get("id", "unknown")
    already_applied = load_applied_jobs(resume_text)

    if job_id in already_applied:
        logger.info("Job %s already applied — skipping", job_id)
        return {
            "job_id": job_id,
            "job_title": job.get("title"),
            "company": job.get("company"),
            "status": "already_applied",
            "detail": "Already applied in a previous session. Skipped to avoid duplicate.",
        }

    is_portal_link = job.get("is_portal_link", False)
    url = job.get("url", "")

    if is_portal_link and url:
        logger.info("Opening job portal in browser: %s", url)
        try:
            webbrowser.open(url)
        except Exception as exc:
            logger.warning("Failed to open browser: %s", exc)

    # Mark as applied
    save_applied_jobs(resume_text, [job_id])

    if is_portal_link:
        detail = f"🔗 Portal opened in your browser. Log in and apply directly."
    else:
        detail = f"Application recorded. View job: {url}" if url else "Application recorded."

    result = {
        "job_id": job_id,
        "job_title": job.get("title"),
        "company": job.get("company"),
        "status": "applied",
        "detail": detail,
    }
    logger.debug("Application result: %s", result)
    return result


# ---------------------------------------------------------------------------
# Browser shortcut helper
# ---------------------------------------------------------------------------
def open_all_portals(query: str) -> None:
    """Open all major Indian job portals in the user's default browser."""
    urls = build_portal_urls(query)
    for portal in urls:
        url = portal["url"]
        logger.info("Opening: %s", url)
        try:
            webbrowser.open(url)
        except Exception as exc:
            logger.warning("Failed to open %s: %s", url, exc)
        time.sleep(0.5)  # Small delay between tabs