"""Utility functions for resume parsing, job searching, and application simulation."""

import os
import time
import logging
from typing import List, Dict

from dotenv import load_dotenv
import requests
from pypdf import PdfReader

load_dotenv()

logger = logging.getLogger(__name__)


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


def search_adzuna_jobs(query: str, location: str = "") -> List[Dict]:
    """Fetch job listings from the Adzuna API.

    Adzuna has a free tier (10 API calls/day) and a well-documented REST API.
    Requires ADZUNA_APP_ID and ADZUNA_API_KEY in environment variables.
    Returns a list of job dicts with normalised keys.
    """
    app_id = os.getenv("ADZUNA_APP_ID")
    api_key = os.getenv("ADZUNA_API_KEY")
    if not app_id or not api_key:
        logger.warning(
            "Adzuna credentials not found; falling back to simulated job data. "
            "Set ADZUNA_APP_ID and ADZUNA_API_KEY in .env for live results."
        )
        return _fallback_jobs(query)

    base_url = "https://api.adzuna.com/v1/api/jobs/us/search/1"
    params = {
        "app_id": app_id,
        "app_key": api_key,
        "what": query,
        "where": location or "",
        "content_type": "application/json",
        "results_per_page": 25,
        "sort_by": "date",
        "max_days_old": 30,
    }
    logger.info("Searching Adzuna jobs: query=%s, location=%s", query, location or "any")

    try:
        response = requests.get(base_url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
    except requests.RequestException as exc:
        logger.warning("Adzuna API request failed (%s); using fallback data", exc)
        return _fallback_jobs(query)

    # Normalise Adzuna fields to common schema
    jobs = []
    for item in results:
        jobs.append({
            "id": item.get("id"),
            "title": item.get("title", "Unknown Title"),
            "company": (item.get("company", {}) or {}).get("display_name", "Unknown Company"),
            "location": item.get("location", {}).get("display_name", "") if item.get("location") else "",
            "description": item.get("description", ""),
            "url": item.get("redirect_url", ""),
            "salary_min": item.get("salary_min"),
            "salary_max": item.get("salary_max"),
            "source": "adzuna",
        })
    logger.info("Adzuna returned %d jobs", len(jobs))
    return jobs


def _fallback_jobs(query: str) -> List[Dict]:
    """Return simulated jobs when no job API is configured.

    This ensures the pipeline can be demonstrated end-to-end without
    external API credentials. Replace with a real API in production.
    """
    logger.info("Generating %d simulated jobs for query: %s", 5, query)
    jobs = [
        {
            "id": "sim-001",
            "title": f"Software Engineer - {query}",
            "company": "TechCorp Inc.",
            "location": "San Francisco, CA",
            "description": f"We are looking for a skilled engineer with experience in {query} to join our team.",
            "url": "https://example.com/job/001",
            "salary_min": 120000,
            "salary_max": 160000,
            "source": "simulated",
        },
        {
            "id": "sim-002",
            "title": f"Senior Developer - {query}",
            "company": "StartupXYZ",
            "location": "New York, NY",
            "description": f"Senior role requiring deep expertise in {query} and system design.",
            "url": "https://example.com/job/002",
            "salary_min": 140000,
            "salary_max": 190000,
            "source": "simulated",
        },
        {
            "id": "sim-003",
            "title": f"Full Stack Engineer",
            "company": "BigCorp Ltd.",
            "location": "Austin, TX",
            "description": f"Full stack position. Tech stack includes {query}, React, and AWS.",
            "url": "https://example.com/job/003",
            "salary_min": 110000,
            "salary_max": 150000,
            "source": "simulated",
        },
        {
            "id": "sim-004",
            "title": "Data Scientist",
            "company": "DataDriven Co.",
            "location": "Remote",
            "description": f"Data scientist with ML skills. Key technologies: {query}, Python, TensorFlow.",
            "url": "https://example.com/job/004",
            "salary_min": 130000,
            "salary_max": 170000,
            "source": "simulated",
        },
        {
            "id": "sim-005",
            "title": "Backend Developer",
            "company": "CloudNine Solutions",
            "location": "Seattle, WA",
            "description": f"Backend engineer focusing on {query}, microservices, and distributed systems.",
            "url": "https://example.com/job/005",
            "salary_min": 125000,
            "salary_max": 165000,
            "source": "simulated",
        },
    ]
    return jobs


def apply_to_job(job: Dict, resume_text: str) -> Dict:
    """Simulate applying to a job.

    In production, this would POST to the company's ATS or use a headless
    browser to fill out the application form. Here we return a mock result
    with latency to simulate network delay.
    """
    logger.info("Applying to job %s at %s", job.get("id"), job.get("company", "unknown"))
    time.sleep(0.5)
    result = {
        "job_id": job.get("id"),
        "job_title": job.get("title"),
        "company": job.get("company"),
        "status": "applied",
        "detail": "Simulated application – integrate with real ATS in production.",
    }
    logger.debug("Application result: %s", result)
    return result
