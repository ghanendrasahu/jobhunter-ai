"""Structured profile extraction from raw resume text.

Uses deterministic heuristics (email/phone/skills regexes) so it works without an
LLM. An optional LLM refinement pass can be layered on top later.
"""

from __future__ import annotations

import re

from jobhunter.domains.matching import TECH_SKILLS

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s-]?)?(?:\d{10}|\d{5}[\s-]\d{5}|\d{3}[\s-]\d{3}[\s-]\d{4})")
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:years?|yrs?)", re.IGNORECASE)
_DEGREES = ["b.tech", "b.e", "b.sc", "m.tech", "m.e", "m.sc", "bca", "mca",
            "b.com", "m.com", "mba", "phd", "msc", "bba", "bachelor", "master"]

# CTC/salary, e.g. "Current CTC: 12 LPA", "Expected salary: ₹8,00,000", "5.5 Lakh".
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[A-Za-z0-9._-]+", re.IGNORECASE)
_NOTICE_RE = re.compile(r"(?:notice\s+period)\s*[:.\-]?\s*([\d.]+\s*(?:days?|weeks?|months?)?)", re.IGNORECASE)
_SECTION_HEADERS = {
    "skills", "experience", "education", "resume", "curriculum", "summary",
    "projects", "certifications", "achievements", "contact", "objective",
}

INDIAN_CITIES = [
    "bangalore", "bengaluru", "hyderabad", "mumbai", "pune", "chennai",
    "delhi", "noida", "gurgaon", "gurugram", "kolkata", "ahmedabad",
    "kochi", "jaipur", "indore", "chandigarh", "remote",
]


def profile_from_resume(resume_text: str) -> dict:
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

    # Title: first short title-cased line after the name that isn't a heading/city.
    current_title = _find_title(text, name)

    # CTC: current/expected figures, kept as the raw string the user entered.
    current_ctc = _find_ctc(text, "current")
    expected_ctc = _find_ctc(text, "expected")

    # Notice period: "Immediate joiner" wins, else the first numeric value.
    notice_period = _find_notice_period(text)

    linkedin_match = _LINKEDIN_RE.search(text)
    linkedin = linkedin_match.group(0) if linkedin_match else ""
    if linkedin and not linkedin.startswith("http"):
        linkedin = f"https://{linkedin}"

    return {
        "full_name": name,
        "email": email.group(0) if email else "",
        "phone": phone.group(0).replace(" ", "").replace("-", "") if phone else "",
        "skills": skills,
        "experience_years": int(years.group(1)) if years else 0,
        "education": degrees[0] if degrees else "",
        "location": location,
        "current_title": current_title,
        "current_ctc": current_ctc,
        "expected_ctc": expected_ctc,
        "notice_period": notice_period,
        "linkedin": linkedin,
        "cover_letter": _build_cover_letter(name, current_title, skills),
        "resume_text": text,
    }


def _find_title(text: str, name: str) -> str:
    """Best-effort job title: first short title-cased line that is not the name."""
    name_lower = (name or "").strip().lower()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower == name_lower:
            continue
        if _EMAIL_RE.search(stripped) or _PHONE_RE.search(stripped):
            continue
        if any(city in lower for city in INDIAN_CITIES):
            continue
        if lower in _SECTION_HEADERS:
            continue
        # Titles don't carry "key: value" labels.
        if ":" in stripped:
            continue
        words = stripped.split()
        if 1 <= len(words) <= 8:
            capitals = sum(1 for w in words if w[:1].isupper())
            if capitals >= 2:
                # "Software Engineer with 5+ years of experience." -> "Software Engineer"
                title = stripped.split(" with ", 1)[0].rstrip(".")
                return title
    return ""


def _find_ctc(text: str, kind: str) -> str:
    """Return the current/expected CTC string, or '' when absent."""
    if kind == "current":
        label = r"(?:current|present)\s+(?:ctc|salary|compensation)"
    else:
        label = r"(?:expected|desired|aspired)\s+(?:ctc|salary|compensation)"
    m = re.search(label, text, re.IGNORECASE)
    if not m:
        return ""
    # Slice right after the label, up to the next label or a line/column break.
    rest = text[m.end():]
    rest = re.split(
        r"[\n;|]|(?:current|present|expected|desired|aspired)\s+(?:ctc|salary|compensation)",
        rest,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    m2 = re.search(r"(\d[\d,.]*)\s*(lpa|lakh|lakhs|lak|l)?\b", rest, re.IGNORECASE)
    if not m2:
        return ""
    number = m2.group(1).replace(",", "")
    unit = (m2.group(2) or "").lower()
    if unit in ("lpa", "lakh", "lakhs", "lak", "l"):
        return f"{number} LPA"
    return number


def _find_notice_period(text: str) -> str:
    """'Immediate' when stated, else the first notice-period value."""
    if re.search(r"immediate\s+joiner|immediately\s+available|serving\s+notice\s+period\s*[:.\-]?\s*(none|no)|notice\s+period\s*[:.\-]?\s*(immediate|none|no)", text, re.IGNORECASE):
        return "Immediate"
    m = _NOTICE_RE.search(text)
    return m.group(1) if m else ""


def _build_cover_letter(name: str, title: str, skills: list[str]) -> str:
    """A short, safe cover-letter draft built from the profile (no LLM needed)."""
    if not name and not title:
        return ""
    who = name or title
    role = title or "the role"
    skill_list = ", ".join(skills[:5])
    letter = f"Dear Hiring Manager,\n\nI am {who}, applying for {role}. "
    if skill_list:
        letter += f"My skills include {skill_list}. "
    letter += (
        "I am confident my background and experience align with your requirements "
        "and would welcome the opportunity to contribute to your team.\n\n"
        "Thank you for your consideration.\n"
    )
    return letter
