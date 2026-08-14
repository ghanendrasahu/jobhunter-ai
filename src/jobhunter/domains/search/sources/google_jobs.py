"""Google Jobs source — server-rendered search page parsing (no browser needed).

Google Jobs embeds its results as JSON inside the search page served for
``?ibp=htl;jobs``. ``extract_google_jobs`` recovers those listings (JSON-LD
first, then embedded JSON blobs, then anchor markup as a last resort) so the
source can run headless without a browser. Parsing is fixture-testable: the
extractors take plain HTML and never touch the network.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from html.parser import HTMLParser
from urllib.parse import quote

import requests

from jobhunter.domains.jobs import Job
from jobhunter.domains.search.sources.base import JobSource, register

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_SEARCH_URL = "https://www.google.com/search?q={query}+jobs+in+{location}&ibp=htl;jobs"

_LD_JSON_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def _text(value: object) -> str:
    """Best-effort string extraction from JSON (string or nested name/url field)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("name", "@value", "text"):
            if isinstance(value.get(key), str):
                return value[key]
        return ""
    return str(value)


def _location_from(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        locality = value.get("addressLocality")
        region = value.get("addressRegion")
        return ", ".join(x for x in (_text(locality), _text(region)) if x)
    return ""


def _from_jsonld(html: str) -> list[dict]:
    """Parse schema.org ``JobPosting`` JSON-LD blocks."""
    results: list[dict] = []
    for match in _LD_JSON_RE.findall(html):
        try:
            data = json.loads(match.strip())
        except (ValueError, TypeError):
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            if item.get("@type") not in ("JobPosting", "JobPostingJob"):
                continue
            title = _text(item.get("title"))
            company = item.get("hiringOrganization") or {}
            if isinstance(company, dict):
                company = _text(company.get("name"))
            location = item.get("jobLocation") or {}
            if isinstance(location, dict):
                location = _location_from(location.get("address") or location)
            if not title:
                continue
            results.append({
                "title": title,
                "company": company,
                "location": location,
                "url": _text(item.get("url")),
                "description": _text(item.get("description")),
                "posted_date": _text(item.get("datePosted")),
            })
    return results


def _company_from(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _text(value.get("name"))
    return ""


def _from_embedded_json(html: str) -> list[dict]:
    """Scan the page for JSON objects carrying title/company/location fields."""
    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    index = 0
    while index < len(html):
        idx = html.find('"title"', index)
        if idx == -1:
            break
        open_brace = html.rfind("{", 0, idx)
        if open_brace == -1:
            index = idx + 1
            continue
        try:
            obj, end = decoder.raw_decode(html[open_brace:])
        except (ValueError, TypeError):
            index = idx + 1
            continue
        if isinstance(obj, dict):
            title = _text(obj.get("title"))
            company = _company_from(obj.get("company"))
            location = _location_from(obj.get("location"))
            if title and (company or location):
                key = (title.lower(), company.lower(), location.lower())
                if key not in seen:
                    seen.add(key)
                    candidates.append({
                        "title": title,
                        "company": company,
                        "location": location,
                        "url": _text(obj.get("url")),
                        "description": _text(obj.get("description")),
                        "posted_date": _text(obj.get("postedDate")),
                    })
        # Advance past the decoded object (end is relative to open_brace), never
        # backwards — otherwise the scan re-reads the same brace forever.
        index = open_brace + max(end, 1)
    return candidates


class _AnchorCollector(HTMLParser):
    """Fallback: collect ``/jobs/view/`` anchors with their visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict] = []
        self._in_job_anchor = False
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs_map = {k: (v or "") for k, v in attrs}
            if "/jobs/view/" in attrs_map.get("href", ""):
                self._in_job_anchor = True
                self._text = []

    def handle_endtag(self, tag):
        if tag == "a" and self._in_job_anchor:
            self.anchors.append({"title": " ".join(self._text).strip()})
            self._in_job_anchor = False

    def handle_data(self, data):
        if self._in_job_anchor:
            self._text.append(data)


def _from_anchors(html: str) -> list[dict]:
    collector = _AnchorCollector()
    collector.feed(html)
    seen: set[str] = set()
    results: list[dict] = []
    for anchor in collector.anchors:
        title = anchor["title"]
        if not title or title.lower() in seen:
            continue
        seen.add(title.lower())
        results.append({"title": title, "company": "", "location": "", "url": "", "description": "", "posted_date": ""})
    return results


def extract_google_jobs(html: str) -> list[dict]:
    """Return normalized job dicts from a Google Jobs search page's HTML.

    Prefers structured JSON-LD, then embedded JSON blobs, then anchor markup.
    Never raises.
    """
    if not html:
        return []
    try:
        from_jsonld = _from_jsonld(html)
        if from_jsonld:
            return from_jsonld
        embedded = _from_embedded_json(html)
        if embedded:
            return embedded
        return _from_anchors(html)
    except Exception as exc:
        logger.debug("Google Jobs extraction failed: %s", exc)
        return []


@register
class GoogleJobsSource(JobSource):
    """Fetch and parse Google Jobs search results over plain HTTP."""

    source_name = "google_jobs"

    async def search(self, query: str, location: str = "India", max_results: int = 10) -> list[Job]:
        try:
            url = _SEARCH_URL.format(query=quote(query), location=quote(location))
            response = requests.get(url, timeout=15, headers=_HEADERS)
            if response.status_code != 200 or not response.text:
                return []
            results = extract_google_jobs(response.text)[:max_results]
            jobs: list[Job] = []
            for result in results:
                url_value = result.get("url") or ""
                jobs.append(Job(
                    title=result.get("title") or "Unknown",
                    company=result.get("company") or "Unknown",
                    location=result.get("location") or location,
                    description=result.get("description") or "",
                    description_truncated=not bool(result.get("description")),
                    url=url_value,
                    source=self.source_name,
                    source_job_id=hashlib.md5(url_value.encode()).hexdigest()[:8] if url_value else "",
                    posted_date=result.get("posted_date") or "",
                ))
            logger.info("Parsed %d jobs from Google Jobs for '%s'", len(jobs), query)
            return jobs
        except Exception as exc:
            logger.warning("Google Jobs fetch failed: %s", exc)
            return []
