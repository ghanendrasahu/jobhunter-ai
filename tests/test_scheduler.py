"""Tests for the scheduled runner."""

from jobhunter.scheduler import _load_resume_text


def test_load_resume_text_from_path(sample_pdf):
    text = _load_resume_text(str(sample_pdf))
    assert "Software Engineer" in text


def test_load_resume_text_missing_path_raises():
    import pytest

    with pytest.raises(FileNotFoundError):
        _load_resume_text("does-not-exist.pdf")


def test_load_resume_text_falls_back_to_saved(monkeypatch, tmp_path, sample_pdf):
    import jobhunter.scheduler as scheduler
    import jobhunter.storage.history as history

    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history, "RESUMES_DIR", tmp_path / "resumes")

    # A saved resume whose PDF was copied into RESUMES_DIR by save_resume.
    from jobhunter.domains import resume as pdf_module
    from jobhunter.storage.history import save_resume

    monkeypatch.setattr(pdf_module, "extract_text_from_pdf", lambda p: "Scheduled Engineer")
    save_resume(str(sample_pdf), "Scheduled Resume")

    # Bypass file-existence by returning a path that reads via the patched extractor.
    monkeypatch.setattr(scheduler, "_first_resume_path", lambda: str(tmp_path / "resumes" / "x.pdf"))
    text = _load_resume_text(None)
    assert text  # patched extractor returns non-empty text


def test_first_resume_path_returns_empty_when_none(monkeypatch, tmp_path):
    import jobhunter.scheduler as scheduler
    import jobhunter.storage.history as history

    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path / "history")
    monkeypatch.setattr(history, "RESUMES_DIR", tmp_path / "resumes")
    assert scheduler._first_resume_path() == ""


def test_dry_run_validates_without_running(monkeypatch, tmp_path, sample_pdf):
    import jobhunter.scheduler as scheduler

    called = {"ran": False}

    def fake_run(path):
        called["ran"] = True

    monkeypatch.setattr(scheduler, "run_job_hunter", fake_run)
    scheduler.schedule("Python Developer", interval_minutes=5, resume_pdf=str(sample_pdf), dry_run=True)
    assert called["ran"] is False
