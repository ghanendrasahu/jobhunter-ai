"""Structured profile extraction from raw resume text.

Uses deterministic heuristics (email/phone/skills regexes) so it works without an
LLM. An optional LLM refinement pass can be layered on top later.
"""

from __future__ import annotations

import re
from typing import Dict

from jobhunter.core.matcher import TECH_SKILLS

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s-]?)?(?:\d{10}|\d{5}[\s-]\d{5}|\d{3}[\s-]\d{3}[\s-]\d{4})")
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)
_DEGREES = ["b.tech", "b.e", "b.sc", "m.tech", "m.e", "m.sc", "bca", "mca",
            "b.com", "m.com", "mba", "phd", "msc", "bba", "bachelor", "master"]

INDIAN_CITIES = [
    "bangalore", "bengaluru", "hyderabad", "mumbai", "pune", "chennai",
    "delhi", "noida", "gurgaon", "gurugram", "kolkata", "ahmedabad",
    "kochi", "jaipur", "indore", "chandigarh", "remote",
]


def profile_from_resume(resume_text: str) -> Dict:
    """Extract a candidate profile from resume text (LLM-free)."""
    text = resume_text or ""
    lower = text.lower()

    email = _EMAIL_RE.search(text)
    phone = _PHONE_RE.search(text)
    years = _YEARS_RE.search(text)

    skills = [s for s in TECH_SKILLS if re.search(r"\b" + re.escape(s) + r"\b", lower)]
    degrees = [d for d in _DEGREES if d.lower() in lower]

    # Name: first non-empty line that looks like a person's name (not a heading).
    name = ""
    for line in text.splitlines():
        stripped = line.strip()
        words = stripped.split()
        if 2 <= len(words) <= 4 and sum(1 for w in words if w[:1].isupper()) >= 2:
            if not re.search(r"(skills|experience|education|resume|curriculum)", stripped, re.IGNORECASE):
                name = stripped
                break

    # Location: first Indian city mention.
    location = ""
    for city in INDIAN_CITIES:
        if city in lower:
            location = city.title()
            break

    return {
        "full_name": name,
        "email": email.group(0) if email else "",
        "phone": phone.group(0).replace(" ", "").replace("-", "") if phone else "",
        "skills": skills,
        "experience_years": int(years.group(1)) if years else 0,
        "education": degrees[0] if degrees else "",
        "location": location,
        "resume_text": text,
    }
