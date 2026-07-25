"""Utility functions for resume parsing, job searching, AI matching, and history tracking."""

import json
import os
import time
import hashlib
import csv
import io
import logging
import webbrowser
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from urllib.parse import quote
from datetime import datetime
import re
from collections import Counter

from dotenv import load_dotenv
import requests
from pypdf import PdfReader

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HISTORY_DIR = Path("history")
HISTORY_DIR.mkdir(exist_ok=True)
RESUMES_DIR = Path("resumes")
RESUMES_DIR.mkdir(exist_ok=True)

INDIAN_CITIES = [
    "Bangalore", "Hyderabad", "Mumbai", "Pune", "Chennai",
    "Delhi", "Kolkata", "Ahmedabad", "Noida", "Gurgaon",
]

# ---------------------------------------------------------------------------
# Resume ID helpers
# ---------------------------------------------------------------------------
def _resume_id(resume_text: str) -> str:
    return hashlib.sha256(resume_text.encode("utf-8")).hexdigest()[:12]


def _resume_id_from_file(file_path: str) -> str:
    text = extract_text_from_pdf(file_path)
    return _resume_id(text)


# ---------------------------------------------------------------------------
# Multiple Resume Management
# ---------------------------------------------------------------------------
def save_resume(file_path: str, name: str = "") -> Dict:
    """Save a resume to the resumes directory with metadata."""
    text = extract_text_from_pdf(file_path)
    rid = _resume_id(text)
    if not name:
        name = Path(file_path).stem

    # Copy file
    dest = RESUMES_DIR / f"{rid}.pdf"
    import shutil
    shutil.copy2(file_path, dest)

    metadata = {
        "id": rid,
        "name": name,
        "file_path": str(dest),
        "created_at": datetime.now().isoformat(),
        "modified_at": datetime.now().isoformat(),
        "text": text[:500],  # preview only
        "applied_count": len(load_applied_jobs(text)),
    }

    meta_path = RESUMES_DIR / f"{rid}.json"
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logger.info("Saved resume: %s (%s)", name, rid)
    return metadata


def list_resumes() -> List[Dict]:
    """List all saved resumes with metadata."""
    resumes = []
    for path in sorted(RESUMES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            # Update applied count
            text = (RESUMES_DIR / f"{data['id']}.pdf").read_bytes()[:10000].decode("utf-8", errors="ignore")
            data["applied_count"] = len(load_applied_jobs(text)) if text else 0
            resumes.append(data)
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            pass
    return resumes


def delete_resume(resume_id: str) -> None:
    """Delete a saved resume and its history."""
    for ext in [".json", ".pdf"]:
        p = RESUMES_DIR / f"{resume_id}{ext}"
        if p.exists():
            p.unlink()
    h = HISTORY_DIR / f"{resume_id}.json"
    if h.exists():
        h.unlink()
    logger.info("Deleted resume: %s", resume_id)


# ---------------------------------------------------------------------------
# Application History
# ---------------------------------------------------------------------------
def _history_path(resume_id: str) -> Path:
    return HISTORY_DIR / f"{resume_id}.json"


def load_applied_jobs(resume_text: str) -> set:
    rid = _resume_id(resume_text)
    path = _history_path(rid)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return set(data.get("applied_job_ids", []))
        except (json.JSONDecodeError, KeyError):
            return set()
    return set()


def save_applied_jobs(resume_text: str, job_ids: List[str], job_details: List[Dict] = None) -> None:
    rid = _resume_id(resume_text)
    path = _history_path(rid)
    existing = set()
    existing_details = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            existing = set(data.get("applied_job_ids", []))
            existing_details = data.get("applied_jobs", [])
        except (json.JSONDecodeError, KeyError):
            pass
    existing.update(job_ids)

    if job_details:
        seen_urls = {j.get("url", "") for j in existing_details}
        for jd in job_details:
            if jd.get("url", "") not in seen_urls:
                seen_urls.add(jd.get("url", ""))
                existing_details.append(jd)

    path.write_text(
        json.dumps({
            "resume_id": rid,
            "applied_job_ids": sorted(existing),
            "applied_jobs": existing_details,
            "last_updated": datetime.now().isoformat(),
        }, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved %d applied job IDs for resume %s", len(existing), rid)


def get_application_history(resume_text: str) -> Dict:
    rid = _resume_id(resume_text)
    path = _history_path(rid)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError):
            pass
    return {"resume_id": rid, "applied_job_ids": [], "applied_jobs": []}


def list_all_histories() -> List[Dict]:
    histories = []
    for path in HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            histories.append(data)
        except (json.JSONDecodeError, KeyError):
            pass
    return histories


def export_history_csv(resume_text: str = None) -> str:
    """Export application history as CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Job ID", "Title", "Company", "Source", "URL", "Applied At", "Status"])

    if resume_text:
        histories = [get_application_history(resume_text)]
    else:
        histories = list_all_histories()

    for h in histories:
        for job in h.get("applied_jobs", []):
            writer.writerow([
                job.get("job_id", ""),
                job.get("title", ""),
                job.get("company", ""),
                job.get("source", ""),
                job.get("url", ""),
                job.get("applied_at", ""),
                "applied",
            ])
        # Also include legacy entries
        for jid in h.get("applied_job_ids", []):
            if not any(j.get("job_id") == jid for j in h.get("applied_jobs", [])):
                writer.writerow([jid, "", "", "", "", "", "applied"])

    return output.getvalue()


# ---------------------------------------------------------------------------
# PDF Extraction
# ---------------------------------------------------------------------------
def extract_text_from_pdf(file_path: str) -> str:
    logger.info("Extracting text from PDF: %s", file_path)
    reader = PdfReader(file_path)
    text = []
    for i, page in enumerate(reader.pages):
        page_text = page.extract_text() or ""
        text.append(page_text)
    result = "\n".join(text)
    logger.info("PDF extraction complete: %d chars", len(result))
    return result


# ---------------------------------------------------------------------------
# Job Portals
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
    "google_jobs": {
        "name": "Google Jobs",
        "search_url": "https://www.google.com/search?q={query}+jobs+in+India&ibp=htl;jobs",
        "badge_color": "#4285f4",
        "icon": "🔍",
    },
}


def build_portal_urls(query: str) -> List[Dict]:
    encoded = quote(query)
    urls = []
    for key, portal in JOB_PORTALS.items():
        url = portal["search_url"].replace("{query}", encoded)
        urls.append({
            "id": f"{key}-search",
            "source": key,
            "title": f"{portal['name']}: {query}",
            "company": f"Search on {portal['name']}",
            "location": "India",
            "url": url,
            "description": f"Search for '{query}' jobs on {portal['name']}",
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "is_portal_link": True,
            "badge_color": portal["badge_color"],
            "icon": portal["icon"],
        })
    return urls


# ---------------------------------------------------------------------------
# AI Job Matching Score
# ---------------------------------------------------------------------------
def compute_match_score(job_description: str, resume_text: str) -> Tuple[int, List[str], List[str]]:
    """Compute a match score between a job description and resume.

    Returns: (score 0-100, matched_skills, missing_skills)
    """
    if not job_description or not resume_text:
        return 0, [], []

    # Extract skills/keywords from both
    resume_lower = resume_text.lower()
    job_lower = job_description.lower()

    # Common tech skills to look for
    tech_skills = [
        "python", "javascript", "typescript", "java", "c++", "c#", "go", "rust",
        "react", "angular", "vue", "node.js", "django", "flask", "fastapi",
        "spring", "express", "next.js", "tailwind", "bootstrap",
        "sql", "postgresql", "mysql", "mongodb", "redis", "elasticsearch",
        "aws", "azure", "gcp", "docker", "kubernetes", "terraform",
        "git", "ci/cd", "jenkins", "github actions",
        "machine learning", "deep learning", "nlp", "tensorflow", "pytorch",
        "langchain", "openai", "llm", "rag",
        "rest api", "graphql", "grpc", "microservices",
        "agile", "scrum", "jira", "confluence",
        "leadership", "team management", "mentoring",
        "communication", "problem-solving", "analytical",
    ]

    matched = []
    missing = []

    for skill in tech_skills:
        # Use word boundary matching to avoid false positives (e.g. "go" in "django")
        pattern = r'\b' + re.escape(skill) + r'\b'
        in_job = bool(re.search(pattern, job_lower))
        in_resume = bool(re.search(pattern, resume_lower))
        if in_job and in_resume:
            matched.append(skill)
        elif in_job and not in_resume:
            missing.append(skill)

    # Score based on matched skills ratio
    total_job_skills = len(matched) + len(missing)
    if total_job_skills == 0:
        return 50, [], []  # neutral score if no skills detected

    base_score = (len(matched) / total_job_skills) * 70

    # Bonus for exact title matches
    common_titles = ["software engineer", "developer", "data scientist",
                     "devops", "frontend", "backend", "full stack",
                     "machine learning", "python developer", "java developer"]
    for title in common_titles:
        if title in job_lower and title in resume_lower:
            base_score += 10
            break

    # Penalty for too many missing skills
    if len(missing) > 5:
        base_score = max(base_score - 10, 0)

    score = min(int(base_score), 100)
    return score, matched, missing


def score_jobs(jobs: List[Dict], resume_text: str) -> List[Dict]:
    """Add match scores to job listings."""
    scored = []
    for job in jobs:
        description = job.get("description", "") or ""
        score, matched, missing = compute_match_score(description, resume_text)
        job["match_score"] = score
        job["matched_skills"] = matched[:10]
        job["missing_skills"] = missing[:10]
        scored.append(job)
    # Sort by match score descending
    scored.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Web Scraping with Playwright
# ---------------------------------------------------------------------------
async def scrape_indeed_jobs(query: str, location: str = "India", max_results: int = 10) -> List[Dict]:
    """Scrape real job listings from Indeed India using Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed. Run: pip install playwright && python -m playwright install chromium")
        return []

    jobs = []
    search_url = f"https://in.indeed.com/jobs?q={quote(query)}&l={quote(location)}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Extract job cards
            cards = await page.query_selector_all('[class*="job_seen_beacon"], [class*="tapItem"], .job-card-container')
            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector('[class*="jobTitle"], h2 a')
                    title = await title_el.inner_text() if title_el else "Unknown"

                    company_el = await card.query_selector('[class*="companyName"], [data-testid="company-name"]')
                    company = await company_el.inner_text() if company_el else "Unknown"

                    location_el = await card.query_selector('[class*="companyLocation"], [data-testid="company-location"]')
                    loc = await location_el.inner_text() if location_el else location

                    url_el = await card.query_selector('a[href*="rc/clk"]')
                    url = f"https://in.indeed.com{await url_el.get_attribute('href')}" if url_el else search_url

                    desc_el = await card.query_selector('[class*="job-snippet"], [data-testid="job-snippet"]')
                    desc = await desc_el.inner_text() if desc_el else ""

                    salary_el = await card.query_selector('[class*="salary-snippet"], [data-testid="salary"]')
                    salary_text = await salary_el.inner_text() if salary_el else ""

                    salary_min, salary_max = None, None
                    if "₹" in salary_text:
                        nums = re.findall(r'[\d,]+', salary_text)
                        if len(nums) >= 2:
                            salary_min = int(nums[0].replace(",", ""))
                            salary_max = int(nums[1].replace(",", ""))

                    job_id = f"indeed-scraped-{hashlib.md5(url.encode()).hexdigest()[:8]}"

                    jobs.append({
                        "id": job_id,
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": loc.strip(),
                        "description": desc.strip(),
                        "url": url,
                        "salary_min": salary_min,
                        "salary_max": salary_max,
                        "salary_currency": "INR",
                        "source": "indeed",
                    })
                except Exception as e:
                    logger.debug("Failed to parse Indeed card: %s", e)
                    continue

            await browser.close()
            logger.info("Scraped %d jobs from Indeed", len(jobs))
    except Exception as exc:
        logger.warning("Indeed scraping failed: %s", exc)

    return jobs


async def scrape_linkedin_jobs(query: str, location: str = "India", max_results: int = 10) -> List[Dict]:
    """Scrape real job listings from LinkedIn India using Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    jobs = []
    search_url = f"https://www.linkedin.com/jobs/search/?keywords={quote(query)}&location={quote(location)}"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            # Try to scroll to load more jobs
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            cards = await page.query_selector_all('.job-card-container, .jobs-search-results__list-item')
            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector('.job-card-list__title, .job-card-container__link')
                    title = await title_el.inner_text() if title_el else "Unknown"

                    company_el = await card.query_selector('.job-card-container__company-name, .artdeco-entity-lockup__subtitle')
                    company = await company_el.inner_text() if company_el else "Unknown"

                    loc_el = await card.query_selector('.job-card-container__metadata-item, .artdeco-entity-lockup__caption')
                    loc = await loc_el.inner_text() if loc_el else location

                    url_el = await card.query_selector('a')
                    url = await url_el.get_attribute('href') if url_el else search_url
                    if url and not url.startswith("http"):
                        url = f"https://www.linkedin.com{url}"

                    job_id = f"linkedin-scraped-{hashlib.md5(url.encode()).hexdigest()[:8]}"

                    jobs.append({
                        "id": job_id,
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": loc.strip(),
                        "description": "",
                        "url": url,
                        "salary_min": None,
                        "salary_max": None,
                        "salary_currency": None,
                        "source": "linkedin",
                    })
                except Exception as e:
                    logger.debug("Failed to parse LinkedIn card: %s", e)
                    continue

            await browser.close()
            logger.info("Scraped %d jobs from LinkedIn", len(jobs))
    except Exception as exc:
        logger.warning("LinkedIn scraping failed: %s", exc)

    return jobs


async def scrape_naukri_jobs(query: str, max_results: int = 10) -> List[Dict]:
    """Scrape real job listings from Naukri.com using Playwright."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return []

    jobs = []
    search_url = f"https://www.naukri.com/{quote(query)}-jobs-in-india"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)

            cards = await page.query_selector_all('.jobTuple, .list, .srp-jobtuple-wrapper')
            for card in cards[:max_results]:
                try:
                    title_el = await card.query_selector('a.title, [class*="title"]')
                    title = await title_el.inner_text() if title_el else "Unknown"

                    company_el = await card.query_selector('a.subTitle, [class*="subTitle"]')
                    company = await company_el.inner_text() if company_el else "Unknown"

                    loc_el = await card.query_selector('[class*="location"], li[class*="loc"]')
                    loc = await loc_el.inner_text() if loc_el else "India"

                    desc_el = await card.query_selector('[class*="desc"], [class*="job-description"]')
                    desc = await desc_el.inner_text() if desc_el else ""

                    url_el = await card.query_selector('a.title')
                    url = await url_el.get_attribute('href') if url_el else search_url
                    if url and not url.startswith("http"):
                        url = f"https://www.naukri.com{url}"

                    salary_el = await card.query_selector('[class*="salary"], li[class*="salary"]')
                    salary_text = await salary_el.inner_text() if salary_el else ""

                    salary_min, salary_max = None, None
                    if "₹" in salary_text or "L" in salary_text:
                        nums = re.findall(r'[\d.]+', salary_text)
                        if len(nums) >= 2:
                            salary_min = int(float(nums[0]) * 100000)
                            salary_max = int(float(nums[1]) * 100000)

                    job_id = f"naukri-scraped-{hashlib.md5(url.encode()).hexdigest()[:8]}"

                    jobs.append({
                        "id": job_id,
                        "title": title.strip(),
                        "company": company.strip(),
                        "location": loc.strip(),
                        "description": desc.strip(),
                        "url": url,
                        "salary_min": salary_min,
                        "salary_max": salary_max,
                        "salary_currency": "INR" if salary_min else None,
                        "source": "naukri",
                    })
                except Exception as e:
                    logger.debug("Failed to parse Naukri card: %s", e)
                    continue

            await browser.close()
            logger.info("Scraped %d jobs from Naukri", len(jobs))
    except Exception as exc:
        logger.warning("Naukri scraping failed: %s", exc)

    return jobs


# ---------------------------------------------------------------------------
# API-based job sources (optional)
# ---------------------------------------------------------------------------
def search_adzuna_jobs(query: str, location: str = "India") -> List[Dict]:
    app_id = os.getenv("ADZUNA_APP_ID")
    api_key = os.getenv("ADZUNA_API_KEY")
    if not app_id or not api_key:
        return []

    try:
        url = f"https://api.adzuna.com/v1/api/jobs/in/search/1"
        params = {
            "app_id": app_id, "app_key": api_key,
            "what": query, "where": location,
            "results_per_page": 15, "sort_by": "date",
        }
        response = requests.get(url, params=params, timeout=20)
        response.raise_for_status()
        data = response.json()
        jobs = []
        for item in data.get("results", []):
            jobs.append({
                "id": f"adzuna-{item.get('id')}",
                "title": item.get("title", "Unknown"),
                "company": (item.get("company", {}) or {}).get("display_name", "Unknown"),
                "location": item.get("location", {}).get("display_name", "India") or "India",
                "description": item.get("description", ""),
                "url": item.get("redirect_url", ""),
                "salary_min": item.get("salary_min"),
                "salary_max": item.get("salary_max"),
                "salary_currency": "INR",
                "source": "adzuna",
            })
        return jobs
    except Exception as exc:
        logger.warning("Adzuna failed: %s", exc)
        return []


def search_jooble_jobs(query: str, location: str = "India") -> List[Dict]:
    api_key = os.getenv("JOOBLE_API_KEY")
    if not api_key:
        return []

    try:
        url = f"https://jooble.org/api/{api_key}"
        payload = {"keywords": query, "location": location, "page": 1}
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        jobs = []
        for item in response.json().get("jobs", [])[:15]:
            source = (item.get("source", "") or "").lower()
            src_map = {"naukri": "naukri", "indeed": "indeed", "linkedin": "linkedin",
                       "monster": "monster", "timesjobs": "timesjobs", "shine": "shine"}
            mapped = "jooble"
            for k, v in src_map.items():
                if k in source:
                    mapped = v
                    break
            url_link = item.get("link", "")
            jid = f"{mapped}-jooble-{hashlib.md5(url_link.encode()).hexdigest()[:8]}"
            jobs.append({
                "id": jid, "title": item.get("title", "Unknown"),
                "company": item.get("company", "Unknown"),
                "location": item.get("location", "India"),
                "description": item.get("snippet", "") or "",
                "url": url_link,
                "salary_min": None, "salary_max": None,
                "salary_currency": None, "source": mapped,
            })
        return jobs
    except Exception as exc:
        logger.warning("Jooble failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Master job search
# ---------------------------------------------------------------------------
async def search_all_jobs_async(query: str) -> List[Dict]:
    """Search all sources: scraped + API + portal links."""
    all_jobs: List[Dict] = []
    seen_urls: set = set()

    def dedup(jobs):
        for j in jobs:
            uk = hashlib.md5(j.get("url", "").encode()).hexdigest()[:12]
            if uk not in seen_urls:
                seen_urls.add(uk)
                all_jobs.append(j)

    # 1. Portal links (always)
    dedup(build_portal_urls(query))

    # 2. Scraped jobs (async)
    import asyncio
    scraped_results = await asyncio.gather(
        scrape_indeed_jobs(query),
        scrape_linkedin_jobs(query),
        scrape_naukri_jobs(query),
        return_exceptions=True,
    )
    for result in scraped_results:
        if isinstance(result, list) and result:
            dedup(result)
            logger.info("Scraped %d jobs", len(result))

    # 3. API jobs (optional)
    dedup(search_adzuna_jobs(query))
    dedup(search_jooble_jobs(query))

    logger.info("Total: %d jobs (%d scraped, %d API, %d portals)",
                len(all_jobs),
                sum(1 for j in all_jobs if not j.get("is_portal_link") and "scraped" in j.get("id", "")),
                sum(1 for j in all_jobs if "jooble" in j.get("id", "") or "adzuna" in j.get("id", "")),
                sum(1 for j in all_jobs if j.get("is_portal_link")))
    return all_jobs


def search_all_jobs(query: str) -> List[Dict]:
    """Synchronous wrapper for search_all_jobs_async."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(search_all_jobs_async(query))


# ---------------------------------------------------------------------------
# Application recording
# ---------------------------------------------------------------------------
def apply_to_job(job: Dict, resume_text: str) -> Dict:
    job_id = job.get("id", "unknown")
    already_applied = load_applied_jobs(resume_text)

    if job_id in already_applied:
        return {
            "job_id": job_id, "job_title": job.get("title"),
            "company": job.get("company"), "status": "already_applied",
            "detail": "Already applied. Skipped.",
        }

    is_portal = job.get("is_portal_link", False)
    url = job.get("url", "")

    if is_portal and url:
        try:
            webbrowser.open(url)
        except Exception as exc:
            logger.warning("Failed to open browser: %s", exc)

    save_applied_jobs(resume_text, [job_id], [{
        "job_id": job_id,
        "title": job.get("title"),
        "company": job.get("company"),
        "source": job.get("source"),
        "url": url,
        "match_score": job.get("match_score"),
        "applied_at": datetime.now().isoformat(),
    }])

    detail = "🔗 Portal opened in your browser." if is_portal else "Application recorded."
    return {
        "job_id": job_id, "job_title": job.get("title"),
        "company": job.get("company"), "status": "applied",
        "detail": detail, "match_score": job.get("match_score"),
    }


def open_all_portals(query: str) -> None:
    for portal in build_portal_urls(query):
        url = portal["url"]
        try:
            webbrowser.open(url)
        except Exception:
            pass
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# Dashboard Analytics Data
# ---------------------------------------------------------------------------
def get_analytics_data() -> Dict:
    """Generate analytics data for dashboard charts."""
    histories = list_all_histories()
    resumes = list_resumes()

    total_applied = sum(len(h.get("applied_job_ids", [])) for h in histories)
    total_resumes = len(resumes)

    # Applications by source
    source_counts: Dict[str, int] = {}
    for h in histories:
        for j in h.get("applied_jobs", []):
            src = j.get("source", "unknown")
            source_counts[src] = source_counts.get(src, 0) + 1

    # Applications over time (daily)
    daily_counts: Dict[str, int] = {}
    for h in histories:
        for j in h.get("applied_jobs", []):
            applied_at = j.get("applied_at", "")[:10]
            if applied_at:
                daily_counts[applied_at] = daily_counts.get(applied_at, 0) + 1

    # Top companies
    company_counts: Counter = Counter()
    for h in histories:
        for j in h.get("applied_jobs", []):
            company_counts[j.get("company", "Unknown")] += 1

    return {
        "total_applied": total_applied,
        "total_resumes": total_resumes,
        "source_counts": dict(sorted(source_counts.items(), key=lambda x: -x[1])),
        "daily_counts": dict(sorted(daily_counts.items())),
        "top_companies": dict(company_counts.most_common(10)),
        "unique_jobs": len({j.get("url") for h in histories for j in h.get("applied_jobs", [])}),
    }


# ---------------------------------------------------------------------------
# Email Notification (SMTP)
# ---------------------------------------------------------------------------
def send_email_notification(
    subject: str,
    body: str,
    to_email: str = None,
) -> bool:
    """Send an email notification about new jobs/applications.

    Requires SMTP settings in .env:
        SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, NOTIFICATION_EMAIL
    """
    to_email = to_email or os.getenv("NOTIFICATION_EMAIL")
    if not to_email:
        logger.info("No NOTIFICATION_EMAIL set — skipping email")
        return False

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = os.getenv("SMTP_PORT", "587")
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    if not all([smtp_host, smtp_user, smtp_pass]):
        logger.info("SMTP not configured — skipping email")
        return False

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "html"))

        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)

        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception as exc:
        logger.warning("Failed to send email: %s", exc)
        return False


def send_job_alert_email(query: str, jobs_found: int, apps_submitted: int) -> None:
    """Send a summary email after a pipeline run."""
    subject = f"JobHunter AI: {apps_submitted} applications submitted for '{query}'"
    body = f"""
    <h2>JobHunter AI Pipeline Report</h2>
    <p><strong>Search Query:</strong> {query}</p>
    <p><strong>Jobs Found:</strong> {jobs_found}</p>
    <p><strong>Applications:</strong> {apps_submitted}</p>
    <hr>
    <p style="color: #666;">Automated from JobHunter AI</p>
    """
    send_email_notification(subject, body)