"""Unit tests for the pure dashboard-state helpers (Streamlit-free)."""

from jobhunter.ui.state import (
    application_explanation,
    eligibility_line,
    is_needs_review,
    needs_review_queue,
    pipeline_apply_mode_label,
    score_css,
    source_status_report,
    status_css,
    status_label,
    summarize_outcomes,
)


def test_status_label_known_and_unknown():
    assert status_label("submitted") == "Submitted"
    assert status_label("needs_review") == "Needs review"
    assert status_label("something_new") == "Something New"
    assert status_label(None) == "Unknown"
    assert status_label("") == "Unknown"


def test_status_css_mapping():
    assert status_css("submitted") == "applied"
    assert status_css("failed") == "failed"
    assert status_css("skipped") == ""


def test_is_needs_review_statuses():
    for status in ("needs_review", "blocked", "no_apply_button", "handed_off", "deferred", "failed"):
        assert is_needs_review(status) is True
    for status in ("submitted", "applied", "already_applied", "skipped", ""):
        assert is_needs_review(status) is False


def test_summarize_outcomes_counts():
    results = [
        {"status": "submitted"},
        {"status": "submitted"},
        {"status": "needs_review"},
        {"status": "failed"},
        {"status": "discovery_only"},
    ]
    summary = summarize_outcomes(results)
    assert summary["total"] == 5
    assert summary["submitted"] == 2
    assert summary["needs_review"] == 2  # failed + needs_review
    assert summary["by_status"]["submitted"] == 2


def test_needs_review_queue_filters_and_sorts():
    histories = [
        {
            "resume_id": "r1",
            "applied_jobs": [
                {
                    "job_id": "j1",
                    "title": "A",
                    "company": "Acme",
                    "source": "naukri",
                    "status": "needs_review",
                    "detail": "missing url",
                    "applied_at": "2026-11-01T10:00:00",
                },
                {
                    "job_id": "j2",
                    "title": "B",
                    "company": "Corp",
                    "source": "indeed",
                    "status": "submitted",
                    "url": "https://x",
                    "applied_at": "2026-11-02T10:00:00",
                },
            ],
        },
        {
            "resume_id": "r2",
            "applied_jobs": [
                {
                    "job_id": "j3",
                    "title": "C",
                    "company": "GmbH",
                    "source": "linkedin",
                    "status": "blocked",
                    "detail": "captcha",
                    "applied_at": "2026-11-03T10:00:00",
                },
            ],
        },
    ]
    queue = needs_review_queue(histories)
    assert [item["job_id"] for item in queue] == ["j3", "j1"]  # newest first
    assert queue[0]["status"] == "blocked"


def test_source_status_report_shape_and_discovery_flags():
    report = source_status_report()
    names = {item["name"] for item in report}
    assert {"naukri", "indeed", "linkedin", "google_jobs"} <= names
    by_name = {item["name"]: item for item in report}
    assert by_name["naukri"]["discovery_only"] is False
    assert by_name["indeed"]["discovery_only"] is False
    for discovery_source in ("linkedin", "google_jobs", "foundit", "hirist", "internshala", "cutshort"):
        assert by_name[discovery_source]["discovery_only"] is True
    assert all(set(item) >= {"name", "requires_browser", "available", "discovery_only"} for item in report)


def test_pipeline_apply_mode_label():
    assert "never auto-submits" in pipeline_apply_mode_label("off")
    assert "Pre-fill" in pipeline_apply_mode_label("human")
    assert "Submit automatically" in pipeline_apply_mode_label("auto")
    assert "never auto-submits" in pipeline_apply_mode_label("nonsense")


def test_score_css():
    assert score_css(80) == "high"
    assert score_css(70) == "high"
    assert score_css(40) == "mid"
    assert score_css(39) == "low"
    assert score_css(None) == "low"


def test_eligibility_line_includes_reasons():
    job = {"eligibility_decision": "review", "eligibility_reasons": ["unknown experience"]}
    line = eligibility_line(job)
    assert line.startswith("review")
    assert "unknown experience" in line


def test_eligibility_line_falls_back_to_exposed_and_unreviewed():
    assert "seniority" in eligibility_line(
        {"eligibility_decision": "review", "eligibility_exposed": ["seniority"]}
    )
    assert eligibility_line({}) == "unreviewed"


def test_application_explanation_block():
    job = {
        "eligibility_status": "eligible",
        "eligibility_decision": "apply",
        "eligibility_reasons": [],
        "match_score": 75,
        "relevance_decision": "apply",
        "relevance_components": [{"name": "skills", "weight": 0.4, "score": 80, "detail": "python"}],
    }
    explanation = application_explanation(job)
    assert explanation["eligibility"]["decision"] == "apply"
    assert explanation["relevance"]["score"] == 75
    assert explanation["relevance"]["components"][0]["name"] == "skills"
