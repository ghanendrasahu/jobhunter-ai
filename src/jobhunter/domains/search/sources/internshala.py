"""Internshala source — server-rendered internship listing parsing (no browser).

Internshala serves internship cards as static HTML, so the source fetches the
listing page over HTTP and parses the cards. ``parse_internshala`` is a pure
HTML function, kept fixture-testable and network-free.
"""

from __future__ import annotations

import hashlib
import logging
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
    "Referer": "https://internshala.com/",
}

_SEARCH_URL = "https://internshala.com/internships/{query}-internship"


class _InternshalaParser(HTMLParser):
    """Extract internship cards from Internshala's listing HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict] = []
        self._current: dict | None = None
        self._card_depth = 0
        self._capture: str | None = None
        self._buffer: list[str] = []

    @staticmethod
    def _classes(attrs) -> str:
        attrs_map = {k: (v or "") for k, v in attrs}
        return f" {attrs_map.get('class', '')} "

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        if self._current is None and tag == "div" and "individual_internship" in classes:
            self._current = {"title": "", "company": "", "location": "", "url": ""}
            self._card_depth = 1
            return
        if self._current is not None:
            if tag == "div":
                self._card_depth += 1
            if tag == "a":
                attrs_map = {k: (v or "") for k, v in attrs}
                href = attrs_map.get("href") or ""
                if "/internships/" in href and not self._capture:
                    self._capture = "title"
                    self._buffer = []
                    self._current["url"] = href if href.startswith("http") else f"https://internshala.com{href}"
                    return
            elif tag == "span" and "company_name" in classes and not self._capture:
                self._capture = "company"
                self._buffer = []
                return
            elif tag in ("span", "div") and "locations" in classes and not self._capture:
                self._capture = "location"
                self._buffer = []
                return

    def handle_data(self, data):
        if self._capture is not None:
            self._buffer.append(data)

    def handle_endtag(self, tag):
        if self._current is None:
            return
        if self._capture is not None and tag in ("a", "span", "div"):
            text = " ".join(self._buffer).strip()
            if self._capture == "title":
                self._current["title"] = text
            elif self._capture == "company":
                self._current["company"] = text
            elif self._capture == "location":
                self._current["location"] = text
            self._capture = None
            self._buffer = []
            if tag == "div":
                self._card_depth -= 1
            return
        if tag == "div":
            self._card_depth -= 1
            if self._card_depth <= 0:
                if self._current and self._current["title"]:
                    self.cards.append(self._current)
                self._current = None


def parse_internshala(html: str) -> list[dict]:
    """Return normalized internship dicts from Internshala listing HTML.

    Never raises; returns [] on unparseable/missing markup.
    """
    if not html:
        return []
    parser = _InternshalaParser()
    try:
        parser.feed(html)
    except Exception as exc:
        logger.debug("Internshala parsing failed: %s", exc)
        return []
    return [
        {
            "title": card["title"],
            "company": card["company"] or "Unknown",
            "location": card["location"] or "India",
            "url": card["url"],
            "description": "",
        }
        for card in parser.cards
    ]


@register
class InternshalaSource(JobSource):
    """Fetch and parse Internshala internship listings over plain HTTP."""

    source_name = "internshala"

    async def search(self, query: str, location: str = "India", max_results: int = 10) -> list[Job]:
        try:
            slug = quote(query.lower().replace(" ", "-"))
            url = _SEARCH_URL.format(query=slug)
            response = requests.get(url, timeout=15, headers=_HEADERS)
            if response.status_code != 200 or not response.text:
                return []
            results = parse_internshala(response.text)[:max_results]
            jobs: list[Job] = []
            for result in results:
                url_value = result.get("url") or ""
                jobs.append(Job(
                    title=result.get("title") or "Unknown",
                    company=result.get("company") or "Unknown",
                    location=result.get("location") or location,
                    description=result.get("description") or "",
                    description_truncated=True,
                    url=url_value,
                    source=self.source_name,
                    source_job_id=hashlib.md5(url_value.encode()).hexdigest()[:8] if url_value else "",
                ))
            logger.info("Parsed %d internships from Internshala for '%s'", len(jobs), query)
            return jobs
        except Exception as exc:
            logger.warning("Internshala fetch failed: %s", exc)
            return []
