"""Conditional full job-description retrieval.

Search sources return snippets from their result cards. Fetching the full job
page for every result is slow, so the engine only does it when a snippet lacks
enough signal (:func:`snippet_sufficient`) — or never, when the setting is off.
All functions are synchronous, never raise, and are safe to call from a worker
thread via ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

logger = logging.getLogger(__name__)

# A fetched description is only trusted when it is at least this long; anything
# shorter usually means the selector missed the real content.
_MIN_FULL_DESCRIPTION_CHARS = 200
# Hard cap so history/UI never stores unbounded blobs.
_MAX_FULL_DESCRIPTION_CHARS = 6000

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

_DESCRIPTION_MARKERS = ("job-description", "jobdescription", "description")
_BLOCK_TAGS = ("div", "section", "article")

_WS_RE = re.compile(r"\s+")


def _normalise_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def snippet_sufficient(description: str, min_chars: int = 200, min_words: int = 30) -> bool:
    """Heuristic: is this snippet rich enough to skip a full-page fetch?

    A snippet counts as sufficient when it is long and wordy enough to contain
    real job-detail signal (requirements, skills) rather than an empty card.
    """
    text = (description or "").strip()
    return len(text) >= min_chars and len(text.split()) >= min_words


class _DescriptionExtractor(HTMLParser):
    """Capture text inside the first element whose class/id mentions description."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capturing = False
        self._depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._capturing:
            if tag in _BLOCK_TAGS:
                self._depth += 1
            return
        attrs_map = {key: (value or "") for key, value in attrs}
        hint = f"{attrs_map.get('class', '')} {attrs_map.get('id', '')}".lower()
        if tag in _BLOCK_TAGS and any(marker in hint for marker in _DESCRIPTION_MARKERS):
            self._capturing = True
            self._depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self._capturing and tag in _BLOCK_TAGS:
            self._depth -= 1
            if self._depth <= 0:
                self._capturing = False

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self.parts.append(data)


class _PageText(HTMLParser):
    """Strip scripts/styles and collect the page's visible text."""

    _SKIP_TAGS = {"script", "style", "head", "nav", "footer", "header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if self._skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._skip_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self.parts.append(data)


def extract_description(html: str) -> str:
    """Return the most likely job-description text from a job page's HTML.

    Tries a description-marked container first (tag-balanced capture), then
    falls back to the full rendered page text. Returns a normalized string, or
    ``""`` when the page yields nothing usable. Never raises.
    """
    try:
        extractor = _DescriptionExtractor()
        extractor.feed(html)
        block = _normalise_ws(" ".join(extractor.parts))
        if len(block) >= _MIN_FULL_DESCRIPTION_CHARS:
            return block[:_MAX_FULL_DESCRIPTION_CHARS]
    except Exception as exc:
        logger.debug("Description-block extraction failed: %s", exc)

    try:
        page = _PageText()
        page.feed(html)
        full = _normalise_ws(" ".join(page.parts))
    except Exception as exc:
        logger.debug("Page-text extraction failed: %s", exc)
        return ""
    return full[:_MAX_FULL_DESCRIPTION_CHARS]


def fetch_full_description(url: str, session=None, timeout: int = 12) -> str:
    """Download ``url`` and return its HTML, or ``""`` on any failure."""
    if not url:
        return ""
    try:
        import requests

        requester = session or requests.Session()
        response = requester.get(url, timeout=timeout, headers=_DEFAULT_HEADERS)
        if response.status_code == 200 and response.text:
            return response.text
    except Exception as exc:
        logger.debug("Full-description fetch failed for %s: %s", url, exc)
    return ""


def ensure_full_descriptions(
    jobs,
    session=None,
    max_fetches: int = 5,
    min_chars: int = _MIN_FULL_DESCRIPTION_CHARS,
) -> int:
    """Fetch full descriptions for jobs whose snippet is insufficient.

    ``jobs`` is a list of :class:`jobhunter.domains.jobs.Job` objects which is
    mutated in place: the job's ``description`` is replaced with the fetched
    text and ``description_truncated`` flips to ``False``. At most
    ``max_fetches`` pages are downloaded. Returns how many jobs were refreshed.
    """
    fetched = 0
    for job in jobs:
        if fetched >= max_fetches:
            break
        if not job.url or snippet_sufficient(job.description, min_chars=min_chars):
            continue
        html = fetch_full_description(job.url, session=session)
        if not html:
            continue
        description = extract_description(html)
        if len(description) < min_chars:
            continue
        job.description = description
        job.description_truncated = False
        fetched += 1
    if fetched:
        logger.info("Refreshed full descriptions for %d jobs", fetched)
    return fetched
