"""Generic application-form filler.

Form field detection is heuristic: it classifies each visible input by its
``id``, ``name``, ``placeholder``, and nearby ``<label>`` text, then fills it
from the candidate profile. Unknown / sensitive fields are left for the user.
"""

from __future__ import annotations

import logging
import re

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

# field_name -> (aliases matched against normalized label/id/name/placeholder)
_FIELD_ALIASES: dict[str, list[str]] = {
    "full_name": ["full name", "fullname", "name"],
    "first_name": ["first name", "firstname", "first"],
    "last_name": ["last name", "lastname", "last"],
    "email": ["email", "e-mail", "mail"],
    "phone": ["phone", "mobile", "contact number", "telephone", "phone number"],
    "location": ["city", "location", "current location", "current city", "address"],
    "experience_years": ["experience", "years of experience", "total experience", "work experience"],
    "skills": ["skills", "technologies", "skill"],
    "education": ["education", "highest qualification", "degree", "qualification"],
    "linkedin": ["linkedin"],
    "current_title": ["designation", "current title", "current designation", "job title", "role"],
    "notice_period": ["notice period"],
    "current_ctc": ["current ctc", "current salary", "current compensation"],
    "expected_ctc": ["expected ctc", "expected salary", "expected compensation"],
    "resume": ["resume", "cv", "upload resume", "attach resume"],
    "cover_letter": ["cover letter"],
    "accept_terms": ["terms", "privacy", "consent", "agree"],
}

# Fields we never auto-fill (sensitive or human-only).
_SKIP_FIELDS = {"password", "confirm", "otp", "verification code", "captcha"}


def normalize(value: str) -> str:
    """Lowercase and strip to alphanumerics for robust matching."""
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def classify_field(id_attr: str, name_attr: str, placeholder: str, label_text: str) -> str:
    """Return the profile field a form control maps to, or 'unknown'."""
    haystack = normalize(" ".join([label_text, placeholder, name_attr, id_attr]))
    for field_name, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if normalize(alias) in haystack:
                return field_name
    return "unknown"


def is_skippable(id_attr: str, name_attr: str, placeholder: str, label_text: str) -> bool:
    """Return True for password/OTP/CAPTCHA fields we must not touch."""
    haystack = normalize(" ".join([label_text, placeholder, name_attr, id_attr]))
    return any(normalize(skip) in haystack for skip in _SKIP_FIELDS)


def _field_text(page: Page, handle) -> str:
    """Resolve the human-readable label for a form control."""
    try:
        label_for = handle.get_attribute("for")
    except Exception:
        label_for = None
    try:
        el_id = handle.get_attribute("id")
    except Exception:
        el_id = None
    try:
        name_attr = handle.get_attribute("name")
    except Exception:
        name_attr = None
    try:
        placeholder = handle.get_attribute("placeholder")
    except Exception:
        placeholder = None

    label_text = ""
    if label_for:
        try:
            label_el = page.query_selector(f"label[for='{label_for}']")
            if label_el:
                label_text = label_el.inner_text()
        except Exception:
            pass
    return f"{label_text} {placeholder} {name_attr} {el_id}"


def _value_for(field: str, profile: dict) -> str | None:
    """Pick the profile value for a classified field (None when not available)."""
    if field == "full_name":
        return profile.get("full_name") or ""
    if field in ("first_name", "last_name"):
        name = profile.get("full_name", "").split()
        return name[0] if field == "first_name" and name else (name[-1] if name else "")
    if field == "email":
        return profile.get("email") or ""
    if field == "phone":
        return profile.get("phone") or ""
    if field in ("location",):
        return profile.get("location") or ""
    if field == "experience_years":
        return str(profile.get("experience_years", 0))
    if field == "skills":
        return ", ".join(profile.get("skills", []))
    if field == "education":
        return profile.get("education") or ""
    if field == "current_title":
        return profile.get("current_title") or ""
    return None


def fill_form(page: Page, profile: dict, resume_pdf: str | None = None) -> dict:
    """Auto-fill an application form from the profile. Returns fill statistics."""
    stats = {"filled": 0, "skipped": 0, "unknown": 0, "file_uploaded": False}

    controls = page.query_selector_all("input, textarea, select")
    for handle in controls:
        try:
            tag = handle.evaluate("el => el.tagName")
            visible = handle.is_visible()
        except Exception:
            continue
        if not visible:
            continue

        text = _field_text(page, handle)
        field = classify_field(
            handle.get_attribute("id") or "",
            handle.get_attribute("name") or "",
            handle.get_attribute("placeholder") or "",
            text,
        )

        if field == "unknown":
            stats["unknown"] += 1
            continue
        if is_skippable(handle.get_attribute("id") or "", handle.get_attribute("name") or "",
                        handle.get_attribute("placeholder") or "", text):
            stats["skipped"] += 1
            continue

        if tag == "SELECT":
            if _fill_select(handle, profile, field):
                stats["filled"] += 1
            continue

        el_type = ""
        try:
            el_type = (handle.get_attribute("type") or "").lower()
        except Exception:
            pass

        if el_type == "file":
            if resume_pdf:
                try:
                    handle.set_input_files(resume_pdf, timeout=5000)
                    stats["filled"] += 1
                    stats["file_uploaded"] = True
                except Exception as exc:
                    logger.debug("File upload failed: %s", exc)
            continue
        if el_type in ("checkbox", "radio"):
            if field == "accept_terms":
                try:
                    if not handle.is_checked():
                        handle.check(timeout=2000)
                        stats["filled"] += 1
                except Exception as exc:
                    logger.debug("Checkbox fill failed: %s", exc)
            continue
        if el_type in ("hidden", "submit", "button", "password"):
            continue

        value = _value_for(field, profile)
        if value:
            try:
                handle.fill(value, timeout=2000)
                stats["filled"] += 1
            except Exception as exc:
                logger.debug("Fill failed for %r: %s", field, exc)

    return stats


def _fill_select(handle, profile: dict, field: str) -> bool:
    """Select the closest matching <option> for a dropdown field."""
    value = _value_for(field, profile)
    if not value:
        return False
    try:
        options = handle.evaluate("el => Array.from(el.options).map(o => o.text)")
        best = None
        for opt in options:
            if normalize(opt) == normalize(value) or normalize(opt) in normalize(value) or normalize(value) in normalize(opt):
                best = opt
                break
        if best is None:
            # Pick first meaningful option for years-of-experience style dropdowns.
            for opt in options:
                stripped = opt.strip()
                if stripped and stripped != "Select" and stripped != "- Select -":
                    best = opt
                    break
        if best is not None:
            handle.select_option(label=best, timeout=2000)
            return True
    except Exception as exc:
        logger.debug("Select fill failed: %s", exc)
    return False
