"""Tests for PHASE 2 cross-source normalization and dedupe hardening."""

from jobhunter.domains.jobs import Job, dedupe_jobs
from jobhunter.domains.search.normalize import (
    normalize_location,
    normalize_remote_mode,
    normalize_title,
    url_dedupe_key,
)


def test_normalize_location_city_alias():
    assert normalize_location("Bangalore") == "Bengaluru"
    assert normalize_location("Bengaluru") == "Bengaluru"
    assert normalize_location("Banglore") == "Bengaluru"


def test_normalize_location_remote_variants():
    assert normalize_location("Work From Home") == "Remote"
    assert normalize_location("WFH") == "Remote"
    assert normalize_location("Remote") == "Remote"


def test_normalize_location_hybrid():
    assert normalize_location("Hybrid - Bengaluru") == "Hybrid"
    assert normalize_location("Hybrid") == "Hybrid"


def test_normalize_remote_mode():
    assert normalize_remote_mode("Remote") == "remote"
    assert normalize_remote_mode("Hybrid") == "hybrid"
    assert normalize_remote_mode("Pune") == ""
    assert normalize_remote_mode("") == ""


def test_normalize_title_strips_noise():
    assert normalize_title("Python Developer - Apply") == "Python Developer"
    assert normalize_title("Data Analyst (Urgent)") == "Data Analyst"
    assert normalize_title("  ML Engineer  | Job ") == "ML Engineer"


def test_url_dedupe_key_strips_tracking_params():
    a = url_dedupe_key("https://x.com/job/1?utm_source=twitter&id=5")
    b = url_dedupe_key("https://x.com/job/1?utm_campaign=push&id=5")
    assert a == b
    assert "utm" not in a


def test_url_dedupe_key_ignores_fragment():
    a = url_dedupe_key("https://x.com/job/1#applied")
    b = url_dedupe_key("https://x.com/job/1")
    assert a == b


def test_dedupe_collapses_url_tracking_variation():
    jobs = [
        Job(title="ML Engineer", company="Acme", location="Bengaluru", url="https://a.com/j1?utm_source=x"),
        Job(title="ML Engineer", company="Acme", location="Bengaluru", url="https://a.com/j1?gclid=abc"),
    ]
    assert len(dedupe_jobs(jobs)) == 1


def test_dedupe_collapses_location_aliases():
    jobs = [
        Job(title="Engineer", company="Acme", location="Bangalore", url="https://a.com/j1"),
        Job(title="Engineer", company="Acme", location="Bengaluru", url="https://b.com/j2"),
    ]
    assert len(dedupe_jobs(jobs)) == 1


def test_dedupe_keeps_different_locations():
    jobs = [
        Job(title="Engineer", company="Acme", location="Bengaluru", url="https://a.com/j1"),
        Job(title="Engineer", company="Acme", location="Pune", url="https://b.com/j2"),
    ]
    assert len(dedupe_jobs(jobs)) == 2


def test_discovery_only_roundtrips():
    job = Job(source="linkedin", url="https://x.com/j", discovery_only=True)
    data = job.to_dict()
    assert data["discovery_only"] is True
    assert Job.from_dict(data).discovery_only is True
    assert Job.from_dict({"url": "https://x.com/j"}).discovery_only is False
