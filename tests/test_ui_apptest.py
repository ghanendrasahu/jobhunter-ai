"""Smoke tests for the dashboard pages via streamlit's AppTest.

Pages render headlessly against the throwaway data dirs configured by
``conftest.py``. Assertions are deliberately shallow (renders without
exception, key widgets/labels present, one delete interaction) — the safety
gates are tested in the backend suites, not here.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from jobhunter.storage import qa as qa_store
from jobhunter.storage import run_state
from jobhunter.storage.history import save_applied_jobs

UNIQUE = "ui apptest unique resume text %s"


def _page(script: str) -> AppTest:
    at = AppTest.from_string(script, default_timeout=60)
    at.run()
    if at.exception:
        raise AssertionError(f"page raised: {at.exception}")
    return at


def test_settings_page_renders_with_pipeline_mode():
    at = _page("from jobhunter.ui import views\nviews.settings_page()\n")
    labels = [s.label for s in at.selectbox]
    assert any("Pipeline apply mode" in str(label) for label in labels)


def test_qa_memory_page_lists_and_deletes_answer():
    intent_name = "expected_ctc"
    qa_store.save_answer(intent_name, "25 LPA uiapptest-secret", "user")

    at = _page("from jobhunter.ui import control_center\ncontrol_center.qa_memory_page()\n")

    delete_button = next((b for b in at.button if b.key == f"qa_del_{intent_name}"), None)
    assert delete_button is not None, "expected a delete button for the stored answer"
    delete_button.click()
    at.run()
    if at.exception:
        raise AssertionError(f"page raised after delete: {at.exception}")
    assert qa_store.load_answer(intent_name) is None


def test_history_page_renders_seeded_outcome():
    save_applied_jobs(
        UNIQUE % "history",
        ["job-ui-history"],
        [
            {
                "job_id": "job-ui-history",
                "title": "UI History Title",
                "company": "Acme",
                "source": "naukri",
                "url": "https://www.naukri.com/job/ui-history",
                "status": "submitted",
                "detail": "Application submitted and confirmed.",
                "applied_at": "2026-11-01T10:00:00",
            }
        ],
    )
    at = _page("from jobhunter.ui import control_center\ncontrol_center.history_page()\n")
    combined = " ".join(str(el.value) for el in at.markdown)
    assert "Total outcomes" in combined
    assert "Submission rate" in combined


def test_needs_review_page_shows_stopped_items():
    save_applied_jobs(
        UNIQUE % "needsreview",
        ["job-ui-needs-review"],
        [
            {
                "job_id": "job-ui-needs-review",
                "title": "UI Needs Review Title",
                "company": "Acme",
                "source": "indeed",
                "url": "https://indeed.com/job/ui-needs-review",
                "status": "needs_review",
                "detail": "Form filled but missing: phone",
                "applied_at": "2026-11-02T10:00:00",
            }
        ],
    )
    at = _page("from jobhunter.ui import control_center\ncontrol_center.needs_review_page()\n")
    combined = " ".join(str(el.value) for el in at.markdown)
    assert "UI Needs Review Title" in combined


def test_dashboard_page_renders_runs_section():
    run_id = run_state.start_run(origin="pipeline", query="uiapptest query", mode="off")
    run_state.record_source_metric(run_id, "naukri", found=3, failed=False, duration_ms=100)
    run_state.record_event(run_id, "error", "run", "uiapptest failure marker")
    run_state.finish_run(run_id, "failed", {"applications": {"total": 0, "by_status": {}}})

    at = _page("from jobhunter.ui import views\nviews.dashboard_page()\n")
    combined = " ".join(str(el.value) for el in at.markdown)
    assert "Errors & warnings" in combined
    assert "uiapptest failure marker" in combined


def test_resumes_page_renders():
    _page("from jobhunter.ui import views\nviews.resumes_page()\n")


def test_job_search_page_renders_sources_expander():
    at = _page("from jobhunter.ui import views\nviews.job_search_page()\n")
    captions = " ".join(str(el.value) for el in at.caption)
    assert "Sources marked discovery-only never auto-apply" in captions
