"""Tests for the auto-apply CLI (python -m jobhunter.automation.apply)."""

import jobhunter.automation.apply as apply_cli


def test_missing_resume_returns_1(tmp_path, capsys):
    code = apply_cli.main(["-q", "Python Developer", "-r", str(tmp_path / "missing.pdf")])
    assert code == 1
    assert "Resume not found" in capsys.readouterr().err


def test_success_path_prints_results(sample_pdf, monkeypatch, capsys):
    captured: dict = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return {
            "results": [
                {
                    "status": "submitted",
                    "title": "Dev",
                    "company": "Acme",
                    "evaluation": {"score": 80},
                    "detail": "Application submitted and confirmed.",
                }
            ],
            "log": [],
            "mode": "auto",
            "cycles": 1,
        }

    monkeypatch.setattr(apply_cli, "run_application_pipeline", fake_pipeline)
    monkeypatch.setattr(apply_cli, "warn_missing_keys", lambda *a, **k: None)
    code = apply_cli.main(
        [
            "-q",
            "Python Developer",
            "-r",
            str(sample_pdf),
            "--mode",
            "auto",
            "--portals",
            "naukri",
            "--max",
            "3",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "submitted" in out
    assert captured["mode"] == "auto"
    assert captured["portals"] == ["naukri"]
    assert captured["max_applications"] == 3


def test_off_mode_reports_no_results(sample_pdf, monkeypatch, capsys):
    monkeypatch.setattr(
        apply_cli,
        "run_application_pipeline",
        lambda **kwargs: {"results": [], "log": [], "mode": "off", "cycles": 1},
    )
    monkeypatch.setattr(apply_cli, "warn_missing_keys", lambda *a, **k: None)
    code = apply_cli.main(["-q", "Python Developer", "-r", str(sample_pdf), "--mode", "off"])
    assert code == 0
    assert "No applications attempted" in capsys.readouterr().out
