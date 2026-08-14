"""Tests for the explicit Job -> Apply contract and deterministic routing."""

import pytest

from jobhunter.automation.apply_contract import (
    SUPPORTED_APPLY_PORTALS,
    apply_portal_for,
    may_auto_apply,
    missing_apply_fields,
)


# ---------------------------------------------------------------------------
# Deterministic routing: supported portals
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("source", SUPPORTED_APPLY_PORTALS)
def test_apply_portal_for_supported_source(source):
    job = {"source": source, "url": "https://x.example/job/1"}
    assert apply_portal_for(job) == source


def test_apply_portal_for_uses_portal_when_source_missing():
    job = {"portal": "naukri", "url": "https://x.example/job/1"}
    assert apply_portal_for(job) == "naukri"


def test_apply_portal_for_is_case_insensitive():
    job = {"source": "Indeed", "url": "https://x.example/job/1"}
    assert apply_portal_for(job) == "indeed"


# ---------------------------------------------------------------------------
# Deterministic routing: discovery-only jobs are never applied
# ---------------------------------------------------------------------------
def test_apply_portal_for_none_when_discovery_only():
    job = {"source": "naukri", "discovery_only": True, "url": "https://x.example/job/1"}
    assert apply_portal_for(job) is None
    assert may_auto_apply(job) is False


def test_may_auto_apply_false_for_discovery_only():
    assert may_auto_apply({"source": "naukri", "discovery_only": True}) is False


# ---------------------------------------------------------------------------
# Deterministic routing: unsupported sources never fall through
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "source",
    ["foundit", "linkedin", "cutshort", "hirist", "internshala", "google_jobs", "adzuna", "jooble", "jsearch", "unknown", ""],
)
def test_apply_portal_for_none_for_unsupported_source(source):
    job = {"source": source, "url": "https://x.example/job/1"}
    assert apply_portal_for(job) is None


def test_unsupported_source_never_routes_to_another_portal():
    job = {"source": "foundit", "url": "https://x.example/job/1"}
    assert apply_portal_for(job) is None  # never "naukri" / "indeed"


def test_empty_source_without_portal_routes_to_none():
    assert apply_portal_for({}) is None


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------
def test_missing_apply_fields_reports_url():
    job = {"title": "Software Engineer"}
    assert missing_apply_fields(job) == ["url"]


def test_missing_apply_fields_reports_title_and_url():
    assert missing_apply_fields({}) == ["title", "url"]


def test_missing_apply_fields_empty_when_complete():
    job = {"title": "Software Engineer", "url": "https://x.example/job/1"}
    assert missing_apply_fields(job) == []


def test_may_auto_apply_false_when_url_missing():
    assert may_auto_apply({"source": "naukri", "title": "Dev"}) is False


def test_may_auto_apply_true_for_complete_supported_job():
    job = {"source": "naukri", "title": "Dev", "url": "https://x.example/job/1"}
    assert may_auto_apply(job) is True


def test_may_auto_apply_false_for_unsupported_complete_job():
    job = {"source": "foundit", "title": "Dev", "url": "https://x.example/job/1"}
    assert may_auto_apply(job) is False
