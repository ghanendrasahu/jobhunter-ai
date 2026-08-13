"""Search-portal link generation."""

from __future__ import annotations

import time
import webbrowser
from urllib.parse import quote

JOB_PORTALS: dict[str, dict] = {
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


def build_portal_urls(query: str) -> list[dict]:
    """Return a list of portal-search link "jobs" for a query."""
    encoded = quote(query)
    urls: list[dict] = []
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


def open_all_portals(query: str) -> None:
    """Open every portal search URL in the default browser."""
    for portal in build_portal_urls(query):
        url = portal["url"]
        try:
            webbrowser.open(url)
        except Exception:  # pragma: no cover - browser dependent
            pass
        time.sleep(0.5)
