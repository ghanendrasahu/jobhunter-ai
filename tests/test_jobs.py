"""Tests for the normalized Job model and dedupe logic."""

from jobhunter.domains.jobs import Job, dedupe_jobs


def _job(title="X", company="C", location="Bengaluru", url="https://a.com/j1", source="indeed"):
    return Job(title=title, company=company, location=location, url=url, source=source)


def test_to_dict_roundtrips_through_from_dict():
    job = Job(
        title="ML Engineer",
        company="Acme",
        location="Remote",
        salary_min=800000,
        salary_max=1500000,
        salary_currency="INR",
        description="Do ML stuff.",
        url="https://acme.com/jobs/1",
        source="naukri",
        is_portal_link=False,
    )
    data = job.to_dict()
    assert data["id"] == job.id
    assert data["salary_min"] == 800000
    assert data["is_portal_link"] is False

    rebuilt = Job.from_dict(data)
    assert rebuilt.title == job.title
    assert rebuilt.company == job.company
    assert rebuilt.location == job.location
    assert rebuilt.salary_max == 1500000
    assert rebuilt.source == "naukri"


def test_from_dict_ignores_unknown_keys():
    job = Job.from_dict({"title": "T", "company": "C", "bogus_field": 42, "url": "https://x.com/1", "source": "indeed"})
    assert job.title == "T"
    assert not hasattr(job, "bogus_field")


def test_id_uses_source_job_id_when_present():
    job = Job(source="naukri", source_job_id="abc123", url="https://x.com/1")
    assert job.id == "naukri-abc123"


def test_id_is_stable_for_same_url_and_source():
    a = Job(source="indeed", url="https://x.com/1")
    b = Job(source="indeed", url="https://x.com/1")
    assert a.id == b.id


def test_id_differs_across_sources_for_same_url():
    a = Job(source="indeed", url="https://x.com/1")
    b = Job(source="naukri", url="https://x.com/1")
    assert a.id != b.id


def test_dedupe_jobs_by_url():
    jobs = [
        _job(url="https://a.com/j1"),
        _job(title="Y", url="https://a.com/j1"),
    ]
    assert len(dedupe_jobs(jobs)) == 1


def test_dedupe_jobs_by_company_title_fingerprint():
    jobs = [
        _job(title="ML Engineer", company="Acme", location="Bengaluru", url="https://a.com/j1"),
        _job(title="ML Engineer", company="Acme", location="Bengaluru", url="https://b.com/j2"),
    ]
    assert len(dedupe_jobs(jobs)) == 1


def test_dedupe_keeps_distinct_portal_links():
    jobs = [
        _job(title="Naukri: ML Engineer", company="Search on Naukri", url="https://naukri.com/search"),
        _job(title="Naukri: ML Engineer", company="Search on Naukri", url="https://naukri.com/search"),
    ]
    jobs[0].is_portal_link = True
    jobs[1].is_portal_link = True
    assert len(dedupe_jobs(jobs)) == 1


def test_dedupe_keeps_same_company_title_different_location():
    jobs = [
        _job(title="Engineer", company="Acme", location="Bengaluru", url="https://a.com/j1"),
        _job(title="Engineer", company="Acme", location="Pune", url="https://b.com/j2"),
    ]
    assert len(dedupe_jobs(jobs)) == 2
