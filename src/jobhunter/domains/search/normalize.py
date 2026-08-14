"""Cross-source normalization helpers (PHASE 2).

Every source (Google Jobs, Internshala, LinkedIn, ...) surfaces the same job in
different spellings: "Bangalore" vs "Bengaluru", "WFH" vs "Remote", and URLs
burdened with tracking parameters. These helpers canonicalize titles, locations,
and URLs so dedupe and matching see one consistent job instead of many.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# URL query parameters that are pure tracking noise and never identify a posting.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "dclid", "msclkid", "igshid", "mc_cid", "mc_eid",
    "ref", "ref_", "referrer", "spm", "pk_source", "pk_medium", "pk_campaign",
    "igsh", "si", "sca_esv", "tracking", "trk",
}

# Canonical city -> aliases (lowercase). Bengaluru is the dominant Indian IT hub.
_CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "Bengaluru": ("bengaluru", "bangalore", "banglore", "bengalooru"),
    "Mumbai": ("mumbai", "bombay"),
    "Hyderabad": ("hyderabad", "hyd"),
    "Pune": ("pune", "puna"),
    "Chennai": ("chennai", "madras"),
    "Delhi": ("delhi", "new delhi", "ncr", "gurgaon", "gurugram", "noida", "faridabad", "ghaziabad"),
}

_REMOTE_TOKENS = (
    "remote", "work from home", "work-from-home", "wfh", "virtual", "anywhere",
)
_HYBRID_TOKENS = ("hybrid",)

_TITLE_NOISE = (
    "apply", "apply now", "apply today", "job", "opening", "hiring", "urgent",
    "careers", "career", "- apply", "job description",
)

_WS_RE = re.compile(r"\s+")
_PUNCT_EDGE_RE = re.compile(r"[^\w\s+.#/&-]")


def _collapse(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").strip())


def normalize_title(title: str) -> str:
    """Canonicalize a job title: trim noise like '- Apply', ' - Job', ' (Urgent)'.

    Returns a clean, single-spaced title. Never raises and keeps unknown titles
    intact (only obvious trailing noise is removed).
    """
    text = _collapse(title or "")
    if not text:
        return ""
    text = _PUNCT_EDGE_RE.sub(" ", text)
    text = _collapse(text)
    lowered = text.lower()
    for token in _TITLE_NOISE:
        pattern = re.compile(r"\s*[|:,()\[\]\-]?\s*" + re.escape(token) + r"\s*$")
        match = pattern.search(lowered)
        if match:
            text = text[: match.start()].rstrip(" |:,()-[]")
            text = _collapse(text)
            lowered = text.lower()
    return text[:120]


def normalize_location(location: str) -> str:
    """Canonicalize a location string, resolving city aliases and remote modes.

    Examples: "Bangalore" -> "Bengaluru", "Bangalore (Hybrid)" -> "Hybrid",
    "Work From Home" -> "Remote". Returns the cleaned, canonical form.
    """
    text = _collapse(location or "").lower()
    if not text:
        return ""
    lowered = _collapse(re.sub(r"[(),]", " ", text))
    if any(token in lowered for token in _REMOTE_TOKENS) and not any(
        token in lowered for token in ("hybrid", "on-site", "onsite")
    ):
        return "Remote"
    if any(token in lowered for token in _HYBRID_TOKENS):
        return "Hybrid"
    for canonical, aliases in _CITY_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return canonical
    return _collapse(text).title()


def normalize_remote_mode(location: str) -> str:
    """Return the remote-mode bucket for a location: 'remote', 'hybrid', or ''."""
    cleaned = normalize_location(location).lower()
    if cleaned == "remote":
        return "remote"
    if cleaned == "hybrid":
        return "hybrid"
    return ""


def url_dedupe_key(url: str) -> str:
    """Return a URL key stable across tracking-parameter variation.

    Tracking params (utm_*, fbclid, gclid, ...) are dropped before hashing so
    the same posting reached through different campaigns dedupes correctly.
    """
    value = (url or "").strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k.lower() not in _TRACKING_PARAMS]
        query = urlencode(keep)
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, query, ""))
    except Exception:
        return value
