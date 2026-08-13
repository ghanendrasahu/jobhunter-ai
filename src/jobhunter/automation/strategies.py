"""Per-portal URLs, login flows, and job-card selectors.

Selectors are best-effort — job sites change markup frequently. Every lookup
falls back to text-based matching so the agent degrades gracefully instead of
crashing when a class name goes stale.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from playwright.sync_api import Page

PORTALS: dict[str, dict] = {
    "naukri": {
        "name": "Naukri",
        "home_url": "https://www.naukri.com",
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
        "home_url": "https://in.indeed.com",
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
        "home_url": "https://www.google.com/search?q={query}+jobs+in+India&ibp=htl;jobs",
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

# Text patterns that indicate an obstacle (CAPTCHA / bot-verification) on the page.
OBSTACLE_PATTERNS = [
    r"captcha",
    r"verify you are human",
    r"verify your identity",
    r"complete a security check",
    r"unusual traffic",
    r"too many requests",
    r"temporarily blocked",
    r"additional verification required",
    r"cloudflare",
    r"checking your browser",
    r"attention required",
    r"enable javascript and cookies",
]

# Common Indian cities used to strip location tokens from URL slugs.
INDIAN_CITIES = [
    "bangalore", "bengaluru", "hyderabad", "mumbai", "pune", "chennai",
    "delhi", "noida", "gurgaon", "gurugram", "kolkata", "ahmedabad",
    "kochi", "jaipur", "indore", "chandigarh", "remote", "india",
]


def build_search_url(portal: str, query: str) -> str:
    """Return the search URL for a portal and query."""
    config = PORTALS[portal]
    return config["search_url"].replace("{query}", quote(query))


def click_by_text(page: Page, text: str, timeout_ms: int = 5000) -> bool:
    """Click the first visible element whose text contains ``text`` (non-strict)."""
    try:
        page.get_by_text(text, exact=False).first.click(timeout=timeout_ms)
        return True
    except Exception:
        return False


def click_apply(page: Page, timeout_ms: int = 15000) -> bool:
    """Click the first visible apply button/link whose text contains 'Apply'.

    Falls back to a JS click for portals (e.g. Naukri) that render the apply
    button off-screen or at zero size.
    """
    candidates = page.locator(
        "button:has-text('Apply'), a:has-text('Apply'), [role='button']:has-text('Apply')"
    )
    try:
        candidates.first.wait_for(state="attached", timeout=timeout_ms)
    except Exception:
        return False
    for i in range(min(5, candidates.count())):
        locator = candidates.nth(i)
        try:
            if locator.is_visible():
                locator.click(timeout=5000)
                return True
        except Exception:
            continue
    try:
        candidates.first.evaluate("el => el.click()")
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


def detect_obstacle(page_url: str, page_text: str) -> str | None:
    """Return a description of a bot-verification obstacle, or None."""
    combined = f"{page_url} {page_text}".lower()
    for pattern in OBSTACLE_PATTERNS:
        if re.search(pattern, combined):
            return pattern
    return None


def job_experience_years(job: dict) -> int | None:
    """Return the minimum years a job requires, or None when unknown.

    Parses the URL slug, title, and description (e.g. ``5-to-10-years``,
    ``5+ years``, ``fresher``, ``0 to 1 years``).
    """
    text = " ".join([
        job.get("url", ""), job.get("title", ""), job.get("description", ""),
    ]).lower()
    if any(k in text for k in ("fresher", "entry level", "0 to 1 years", "0-1 years", "freshers")):
        return 0
    norm = re.sub(r"\s+", " ", text)
    norm = re.sub(r"\bto\b", "-", norm)
    norm = re.sub(r"[-–—\s]+", "-", norm)
    match = re.search(r"(\d{1,2})-(\d{1,2})-(?:years?|yrs)\b", norm)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{1,2})\+-(?:years?|yrs)\b", norm)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{1,2})-(?:years?|yrs)\b", norm)
    return int(match.group(1)) if match else None


def collect_cards(page: Page, portal: str, max_results: int = 10) -> list[dict]:
    """Extract job cards from the current search page using the portal's selectors."""
    config = PORTALS.get(portal)
    if not config:
        return []

    cards = page.query_selector_all(config["job_card"])[:max_results]
    jobs: list[dict] = []
    for card in cards:
        try:
            title_el = card.query_selector(config["job_title"])
            company_el = card.query_selector(config["job_company"])
            location_el = card.query_selector(config["job_location"])
            desc_el = card.query_selector(config["job_description"])
            link_el = card.query_selector(config["job_link"])

            url = link_el.get_attribute("href") if link_el else ""
            url = url or ""
            if url.startswith("/"):
                url = f"https://{page.url.split('/')[2]}{url}"

            title = (title_el.inner_text().strip() if title_el else "Unknown")
            company = (company_el.inner_text().strip() if company_el else "")
            if not company or company == "Unknown":
                company = _fallback_company(card, title, url or "")

            card_text = ""
            try:
                card_text = card.inner_text()[:2000]
            except Exception:
                pass
            posted_days = parse_posted_days(card_text)

            jobs.append({
                "id": f"{portal}-{hashlib_md5(url or '')}",
                "source": portal,
                "portal": portal,
                "title": title,
                "company": company or "Unknown",
                "location": (location_el.inner_text().strip() if location_el else "India"),
                "description": (desc_el.inner_text().strip() if desc_el else ""),
                "url": url,
                "posted_days": posted_days,
                "salary_text": _extract_salary_text(card_text),
            })
        except Exception:
            continue
    return jobs


def hashlib_md5(value: str) -> str:
    """Short md5 of a string for stable ids."""
    import hashlib

    return hashlib.md5(value.encode()).hexdigest()[:10]


def parse_posted_days(text: str) -> int | None:
    """Extract days-since-posted from a job card's text (best-effort)."""
    from jobhunter.automation.prioritizer import parse_posted_text

    return parse_posted_text(text)


_SALARY_PATTERN = re.compile(
    r"(?:₹|Rs\.?|INR\s*)?\s*"
    r"(\d[\d,]*\.?\d*)\s*(?:-|–|to)\s*"
    r"(?:₹|Rs\.?|INR\s*)?\s*(\d[\d,]*\.?\d*)\s*"
    r"(lpa|lakh|lakhs|LPA|Lakh|thousand|k)?",
    re.IGNORECASE,
)


def _extract_salary_text(text: str) -> str:
    """Return the raw salary snippet from a card, or '' when absent."""
    match = _SALARY_PATTERN.search(text or "")
    if not match:
        return ""
    return match.group(0).strip()


def _fallback_company(card, title: str, url: str) -> str:
    """Best-effort company extraction when the primary selector misses.

    Tries the Naukri company link, then ``Title (@Company)``, then the URL slug
    (e.g. ``job-listings-python-developer-infosys-infosys-kolkata-...``).
    """
    try:
        link = card.query_selector("a[href*='/companies/']")
        if link:
            text = link.inner_text().strip()
            if text:
                return text
    except Exception:
        pass

    match = re.search(r"\(@\s*([^)]+)\)", title) or re.search(r"\s@\s*([^\s@]+)", title)
    if match:
        return match.group(1).strip()

    slug = url.split("/")[-1]
    if slug.startswith("job-listings-"):
        body = slug[len("job-listings-"):]
        body = re.sub(r"-\d{4,}$", "", body)
        body = re.sub(r"-\d+-to-\d+-years|-to-\d+-years|-\d+-years|-years", "", body)
        title_slug = re.sub(r"[\s@()]+", "-", title.strip().lower()).strip("-")
        tokens = [t for t in title_slug.split("-") if t]
        tokens.sort(key=len, reverse=True)
        for token in tokens:
            body = re.sub(rf"(^|-){re.escape(token)}(?=-|$)", "-", body, count=1)
        for city in INDIAN_CITIES:
            body = re.sub(rf"-{re.escape(city)}(?=-|$)", "-", body, count=1)
        return body.strip("-") if body else ""
    return ""


def login_selector(portal: str) -> dict[str, str]:
    """Return the email/password/button selectors for a portal."""
    config = PORTALS.get(portal, {})
    return {
        "email": config.get("email_field", ""),
        "password": config.get("password_field", ""),
        "button": config.get("login_button", ""),
        "logged_in": config.get("logged_in_selector", ""),
    }
