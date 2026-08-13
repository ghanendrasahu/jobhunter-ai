"""Per-portal URLs, login flows, and job-card selectors.

Selectors are best-effort — job sites change markup frequently. Every lookup
falls back to text-based matching so the agent degrades gracefully instead of
crashing when a class name goes stale.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import quote

from playwright.sync_api import Page

PORTALS: Dict[str, Dict] = {
    "naukri": {
        "name": "Naukri",
        "search_url": "https://www.naukri.com/{query}-jobs-in-india",
        "login_url": "https://www.naukri.com/nlogin/login",
        # Selectors (best-effort)
        "job_card": ".jobTuple, [class*='jobTuple'], .srp-jobtuple-wrapper",
        "job_title": "a.title, [class*='title']",
        "job_company": "a.subTitle, [class*='subTitle']",
        "job_location": "[class*='location'], li[class*='loc']",
        "job_description": "[class*='job-description'], [class*='desc']",
        "job_link": "a.title",
        "logged_in_selector": ".ni-gnb-icn, [class*='user']",
        "email_field": "input[name='email'], input[name='username'], input[type='email']",
        "password_field": "input[name='password'], input[type='password']",
        "login_button": "button:has-text('Login'), button:has-text('Log in'), input[type='submit']",
        "apply_button": "button:has-text('Apply'), a:has-text('Apply now')",
    },
    "indeed": {
        "name": "Indeed",
        "search_url": "https://in.indeed.com/jobs?q={query}&l=India",
        "login_url": "https://secure.indeed.com/auth",
        "job_card": ".job_seen_beacon, [class*='job_seen_beacon'], .tapItem",
        "job_title": ".jobTitle, [class*='jobTitle']",
        "job_company": "[data-testid='company-name'], [class*='companyName']",
        "job_location": "[data-testid='company-location'], [class*='companyLocation']",
        "job_description": "[data-testid='job-snippet'], [class*='job-snippet']",
        "job_link": "a[href*='rc/clk'], .jobTitle a",
        "logged_in_selector": "[data-testid='account-menu'], .desktop-header-account",
        "email_field": "input[name='email'], input[type='email']",
        "password_field": "input[name='password'], input[type='password']",
        "login_button": "button[type='submit'], button:has-text('Continue')",
        "apply_button": "button:has-text('Apply now'), #applyButton",
    },
    "google_jobs": {
        "name": "Google Jobs",
        "search_url": "https://www.google.com/search?q={query}+jobs+in+India&ibp=htl;jobs",
        # Google is an aggregator — no login, no apply. It redirects to source sites.
        "job_card": "[jscontroller*='JobCard'], .i8Z77e",
        "job_title": "div[role='heading']",
        "job_company": ".gNJDp, [class*='oNwCmf']",
        "job_location": ".eK8yHd, [class*='eK8yHd']",
        "job_description": ".tNxQIb, [class*='tNxQIb']",
        "job_link": "a[href*='q=jobs'], a[href*='htl;jobs']",
        "logged_in_selector": "",
        "email_field": "",
        "password_field": "",
        "login_button": "",
        "apply_button": "",
    },
}

# Text patterns that indicate an obstacle (CAPTCHA / verification) on the page.
OBSTACLE_PATTERNS = [
    r"captcha",
    r"verify you are human",
    r"verify your identity",
    r"complete a security check",
    r"unusual traffic",
    r"too many requests",
    r"temporarily blocked",
]


def build_search_url(portal: str, query: str) -> str:
    """Return the search URL for a portal and query."""
    config = PORTALS[portal]
    return config["search_url"].replace("{query}", quote(query))


def click_by_text(page: Page, text: str, timeout_ms: int = 5000) -> bool:
    """Click an element whose visible text matches (partial). Returns success."""
    try:
        page.click(f"text={text}", timeout=timeout_ms)
        return True
    except Exception:
        return False


def fill_input(page: Page, selector: str, value: str) -> bool:
    """Fill an input if present. Returns whether it was filled."""
    try:
        page.fill(selector, value, timeout=5000)
        return True
    except Exception:
        return False


def detect_obstacle(page_url: str, page_text: str) -> Optional[str]:
    """Return a description of a bot-verification obstacle, or None."""
    combined = f"{page_url} {page_text}".lower()
    for pattern in OBSTACLE_PATTERNS:
        if re.search(pattern, combined):
            return pattern
    return None


def collect_cards(page: Page, portal: str, max_results: int = 10) -> List[Dict]:
    """Extract job cards from the current search page using the portal's selectors."""
    config = PORTALS.get(portal)
    if not config:
        return []

    cards = page.query_selector_all(config["job_card"])[:max_results]
    jobs: List[Dict] = []
    for card in cards:
        try:
            title_el = card.query_selector(config["job_title"])
            company_el = card.query_selector(config["job_company"])
            location_el = card.query_selector(config["job_location"])
            desc_el = card.query_selector(config["job_description"])
            link_el = card.query_selector(config["job_link"])

            url = link_el.get_attribute("href") if link_el else ""
            if url and url.startswith("/"):
                url = f"https://{page.url.split('/')[2]}{url}"

            jobs.append({
                "id": f"{portal}-{hashlib_md5(url)}",
                "source": portal,
                "portal": portal,
                "title": (title_el.inner_text().strip() if title_el else "Unknown"),
                "company": (company_el.inner_text().strip() if company_el else "Unknown"),
                "location": (location_el.inner_text().strip() if location_el else "India"),
                "description": (desc_el.inner_text().strip() if desc_el else ""),
                "url": url,
            })
        except Exception:
            continue
    return jobs


def hashlib_md5(value: str) -> str:
    """Short md5 of a string for stable ids."""
    import hashlib

    return hashlib.md5(value.encode()).hexdigest()[:10]


def login_selector(portal: str) -> Dict[str, str]:
    """Return the email/password/button selectors for a portal."""
    config = PORTALS.get(portal, {})
    return {
        "email": config.get("email_field", ""),
        "password": config.get("password_field", ""),
        "button": config.get("login_button", ""),
        "logged_in": config.get("logged_in_selector", ""),
    }
