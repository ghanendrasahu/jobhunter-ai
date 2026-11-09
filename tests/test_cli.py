"""Tests for the CLI entry point (python -m jobhunter)."""

from pathlib import Path

import pytest

import jobhunter.cli as cli


def _fake_result(error="", jobs=2, applications=1):
    return {
        "error": error,
        "resume_text": "Software Engineer with Python experience. " * 5,
        "search_query": "Python Developer",
        "jobs": [{"id": f"j{i}"} for i in range(jobs)],
        "applications": [{"status": "recorded"} for _ in range(applications)],
    }


def test_main_missing_pdf_exits(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([str(Path("does-not-exist.pdf"))])
    assert exc.value.code == 1
    assert "File not found" in capsys.readouterr().out


def test_main_rejects_non_pdf(tmp_path, capsys):
    txt = tmp_path / "resume.txt"
    txt.write_text("hello", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        cli.main([str(txt)])
    assert exc.value.code == 1
    assert "Not a PDF" in capsys.readouterr().out


def test_main_runs_pipeline_and_prints_summary(sample_pdf, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_job_hunter", lambda path: _fake_result())
    monkeypatch.setattr(cli, "warn_missing_keys", lambda *a, **k: None)
    assert cli.main([str(sample_pdf)]) == 0
    out = capsys.readouterr().out
    assert "RESULTS" in out
    assert "Jobs found:" in out
    assert "Python Developer" in out


def test_main_pipeline_exception_exits(sample_pdf, monkeypatch, capsys):
    def boom(path):
        raise RuntimeError("agent exploded")

    monkeypatch.setattr(cli, "run_job_hunter", boom)
    monkeypatch.setattr(cli, "warn_missing_keys", lambda *a, **k: None)
    with pytest.raises(SystemExit) as exc:
        cli.main([str(sample_pdf)])
    assert exc.value.code == 1
    assert "Pipeline failed" in capsys.readouterr().out


def test_main_pipeline_error_result_prints_error(sample_pdf, monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_job_hunter", lambda path: _fake_result(error="search failed"))
    monkeypatch.setattr(cli, "warn_missing_keys", lambda *a, **k: None)
    assert cli.main([str(sample_pdf)]) == 0
    assert "search failed" in capsys.readouterr().out


def test_main_schedule_requires_query(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--schedule"])
    assert exc.value.code == 1
    assert "--query is required" in capsys.readouterr().out


def test_main_schedule_dispatches(sample_pdf, monkeypatch):
    import jobhunter.scheduler as scheduler

    captured: dict = {}

    def fake_schedule(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(scheduler, "schedule", fake_schedule)
    monkeypatch.setattr(cli, "warn_missing_keys", lambda *a, **k: None)
    assert cli.main(["--schedule", "--query", "Data Analyst", "--interval", "60", "--max-runs", "1"]) == 0
    assert captured["query"] == "Data Analyst"
    assert captured["interval_minutes"] == 60
    assert captured["max_runs"] == 1


def test_prompt_for_pdf_quits_on_q(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "q")
    with pytest.raises(SystemExit) as exc:
        cli._prompt_for_pdf()
    assert exc.value.code == 0


def test_prompt_for_pdf_retries_until_valid(sample_pdf, monkeypatch):
    answers = iter(["", str(sample_pdf)])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    assert cli._prompt_for_pdf() == str(sample_pdf)
