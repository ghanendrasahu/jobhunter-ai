"""Tests for resume management and application history."""

from pathlib import Path

import jobhunter.core.history as history
from jobhunter.core.history import (
    apply_to_job,
    delete_resume,
    export_history_csv,
    get_application_history,
    list_all_histories,
    list_resumes,
    load_applied_jobs,
    resume_id_from_text,
    save_applied_jobs,
    save_resume,
)


def test_resume_id_is_stable():
    assert resume_id_from_text("same text") == resume_id_from_text("same text")
    assert resume_id_from_text("same text") != resume_id_from_text("other text")


def test_save_and_load_applied_jobs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history, "RESUMES_DIR", tmp_path / "resumes")

    resume = "Software Engineer Python"
    save_applied_jobs(resume, ["job-1"], [{"job_id": "job-1", "url": "https://x.com/1"}])
    save_applied_jobs(resume, ["job-2"], [{"job_id": "job-2", "url": "https://x.com/2"}])

    assert load_applied_jobs(resume) == {"job-1", "job-2"}
    assert get_application_history(resume)["applied_job_ids"] == ["job-1", "job-2"]


def test_history_deduplicates_by_url(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history, "RESUMES_DIR", tmp_path / "resumes")

    resume = "Data Scientist"
    save_applied_jobs(resume, ["a"], [{"job_id": "a", "url": "https://x.com/same"}])
    save_applied_jobs(resume, ["b"], [{"job_id": "b", "url": "https://x.com/same"}])

    assert len(get_application_history(resume)["applied_jobs"]) == 1


def test_export_csv_contains_header(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history, "RESUMES_DIR", tmp_path / "resumes")

    save_applied_jobs("Resume Text", ["job-1"], [{"job_id": "job-1", "title": "Dev"}])
    csv_text = export_history_csv()
    assert "Job ID" in csv_text
    assert "job-1" in csv_text


def test_save_resume_copies_pdf_and_metadata(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history, "RESUMES_DIR", tmp_path / "resumes")

    pdf_path = tmp_path / "me.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")

    # Patch extraction to avoid needing a valid PDF in this test.
    from jobhunter.core import pdf as pdf_module

    monkeypatch.setattr(pdf_module, "extract_text_from_pdf", lambda p: "Python Developer")

    metadata = save_resume(str(pdf_path), "My Resume")
    assert metadata["name"] == "My Resume"
    assert (tmp_path / "resumes" / f"{metadata['id']}.pdf").exists()
    assert len(list_resumes()) == 1


def test_delete_resume_removes_files(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history, "RESUMES_DIR", tmp_path / "resumes")

    rid = "abcdef123456"
    (tmp_path / "resumes").mkdir(parents=True, exist_ok=True)
    (tmp_path / "history").mkdir(parents=True, exist_ok=True)
    (tmp_path / "resumes" / f"{rid}.json").write_text("{}")
    (tmp_path / "resumes" / f"{rid}.pdf").write_bytes(b"%PDF")
    (tmp_path / "history" / f"{rid}.json").write_text("{}")

    delete_resume(rid)
    assert not (tmp_path / "resumes" / f"{rid}.pdf").exists()
    assert not (tmp_path / "history" / f"{rid}.json").exists()


def test_apply_to_job_records_and_skips_duplicates(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history, "RESUMES_DIR", tmp_path / "resumes")
    monkeypatch.setattr(history, "webbrowser", _FakeBrowser())

    resume = "Python Engineer"
    job = {"id": "job-9", "title": "Backend Dev", "company": "Acme", "url": "https://x.com/9", "source": "indeed"}

    first = apply_to_job(job, resume)
    second = apply_to_job(job, resume)

    assert first["status"] == "applied"
    assert second["status"] == "already_applied"


class _FakeBrowser:
    """No-op stand-in for webbrowser so tests never open a browser."""

    def open(self, url: str) -> bool:
        return True
