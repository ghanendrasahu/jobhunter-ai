"""PHASE 10 — configuration, persistence and data-integrity tests."""

import sqlite3
from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from jobhunter.config import Settings, validate_config
from jobhunter.storage import history, profiles, run_state, schema
from jobhunter.storage import qa as qa_store
from jobhunter.storage import settings as settings_store


def _fresh_storage(tmp_path: Path, monkeypatch):
    """Point every storage module at a throwaway directory tree."""
    hist = tmp_path / "history"
    resumes = tmp_path / "resumes"
    for module in (history, qa_store, profiles, settings_store, run_state):
        monkeypatch.setattr(module, "HISTORY_DIR", hist)
    monkeypatch.setattr(history, "RESUMES_DIR", resumes)
    return hist, resumes


# ---------------------------------------------------------------------------
# Fresh installation & schema initialization
# ---------------------------------------------------------------------------
EXPECTED_TABLES = {
    "resumes",
    "histories",
    "settings",
    "profile_store",
    "qa_answers",
    "runs",
    "run_events",
    "run_source_metrics",
    "submission_attempts",
}


def test_fresh_installation_creates_full_schema(tmp_path, monkeypatch):
    hist, _ = _fresh_storage(tmp_path, monkeypatch)
    conn = schema.connect_with_recovery(hist / "history.db")
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()
    assert EXPECTED_TABLES <= tables
    assert schema.schema_version(hist / "history.db") == schema.SCHEMA_VERSION


def test_schema_connect_is_idempotent_and_preserves_data(tmp_path):
    db = tmp_path / "history.db"
    schema.connect_with_recovery(db).close()
    conn = sqlite3.connect(str(db))
    conn.execute("INSERT INTO settings (key, value) VALUES ('k', 'v')")
    conn.commit()
    conn.close()
    schema.connect_with_recovery(db).close()  # second connect must not wipe data
    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("SELECT value FROM settings WHERE key='k'").fetchone()
    finally:
        conn.close()
    assert row[0] == "v"
    assert schema.schema_version(db) == schema.SCHEMA_VERSION


def test_schema_version_zero_on_missing_file(tmp_path):
    assert schema.schema_version(tmp_path / "nope.db") == 0


# ---------------------------------------------------------------------------
# Environment validation
# ---------------------------------------------------------------------------
def test_missing_environment_variables_use_safe_defaults():
    settings = Settings(_env_file=None)
    assert settings.fresher_only is True
    assert settings.pipeline_apply_mode == "off"
    assert settings.auto_apply_mode == "human"
    assert settings.max_applications_per_run == 5
    assert settings.source_timeout_seconds == 45.0
    assert settings.retry_max_attempts == 3


def test_invalid_configuration_fails_fast():
    with pytest.raises(ValidationError):
        Settings(smtp_port=99999, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(max_file_size_mb=0, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(auto_apply_mode="bogus", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(pipeline_apply_mode="bogus", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(source_timeout_seconds=0, _env_file=None)
    with pytest.raises(ValidationError):
        Settings(browser_debug_port=70000, _env_file=None)


def test_validate_config_flags_half_configured_services():
    settings = Settings(adzuna_app_id="id-without-key", _env_file=None)
    assert any("ADZUNA" in problem for problem in validate_config(settings))

    settings = Settings(smtp_host="smtp.example.com", _env_file=None)
    assert any("SMTP_USER" in problem for problem in validate_config(settings))

    settings = Settings(jobhunter_app_secret=SecretStr("short"), _env_file=None)
    assert any("JOBHUNTER_APP_SECRET" in problem for problem in validate_config(settings))


def test_validate_config_clean_setup_reports_nothing():
    settings = Settings(
        adzuna_app_id="",
        adzuna_api_key="",
        smtp_host="",
        smtp_user="",
        smtp_pass="",
        notification_email="",
        jobhunter_app_secret=SecretStr(""),
        manual_login_timeout=180,
        _env_file=None,
    )
    assert validate_config(settings) == []


# ---------------------------------------------------------------------------
# Persistence round trips
# ---------------------------------------------------------------------------
def test_profile_round_trip(tmp_path, monkeypatch):
    _fresh_storage(tmp_path, monkeypatch)
    profile = {"full_name": "Ada Lovelace", "email": "ada@example.com", "skills": ["python", "sql"]}
    profiles.save_profile(profile)
    assert profiles.load_profile() == profile
    profiles.save_profile({})
    assert profiles.load_profile() == {}


def test_candidate_knowledge_round_trip(tmp_path, monkeypatch):
    _fresh_storage(tmp_path, monkeypatch)
    knowledge = {"role_family": "data", "skills": ["python", "sql"], "experience_years": 3}
    profiles.save_candidate_knowledge(knowledge)
    assert profiles.load_candidate_knowledge() == knowledge


def test_selected_and_suggested_roles_round_trip(tmp_path, monkeypatch):
    _fresh_storage(tmp_path, monkeypatch)
    profiles.save_selected_roles(["Data Analyst", "BI Analyst"])
    assert profiles.load_selected_roles() == ["Data Analyst", "BI Analyst"]
    suggested = [{"title": "Data Analyst", "tier": 1, "score": 0.9}]
    profiles.save_suggested_roles(suggested)
    assert profiles.load_suggested_roles() == suggested


def test_settings_round_trip_and_empty_removes(tmp_path, monkeypatch):
    _fresh_storage(tmp_path, monkeypatch)
    settings_store.save_settings({"naukri_email": "ada@example.com", "auto_apply_mode": "human"})
    loaded = settings_store.load_settings()
    assert loaded["naukri_email"] == "ada@example.com"
    settings_store.save_setting("naukri_email", "")
    assert "naukri_email" not in settings_store.load_settings()


def test_qa_round_trip_and_upsert(tmp_path, monkeypatch):
    _fresh_storage(tmp_path, monkeypatch)
    qa_store.save_answer("expected_ctc", "25 LPA", "user")
    qa_store.save_answer("expected_ctc", "30 LPA", "user")
    assert qa_store.load_answer("expected_ctc")["answer"] == "30 LPA"
    assert len(qa_store.load_all_answers()) == 1
    qa_store.delete_answer("expected_ctc")
    assert qa_store.load_answer("expected_ctc") is None


def test_run_round_trip(tmp_path, monkeypatch):
    _fresh_storage(tmp_path, monkeypatch)
    run_id = run_state.start_run(origin="pipeline", query="Python Developer", mode="off")
    assert run_state.update_run(run_id, resume_id="abc123") is None
    run_state.finish_run(run_id, "completed", {"applications": {"total": 2, "by_status": {"submitted": 2}}})
    run = run_state.get_run(run_id)
    assert run is not None
    assert run["resume_id"] == "abc123"
    assert run["status"] == "completed"
    assert run["summary"]["applications"]["by_status"]["submitted"] == 2


def test_source_metrics_accumulate_per_run(tmp_path, monkeypatch):
    _fresh_storage(tmp_path, monkeypatch)
    run_id = run_state.start_run(origin="pipeline", query="q")
    run_state.record_source_metric(run_id, "naukri", found=3, duration_ms=10)
    run_state.record_source_metric(run_id, "naukri", found=5, duration_ms=15)
    metrics = run_state.source_metrics_for_run(run_id)
    assert metrics["naukri"]["found"] == 8
    assert metrics["naukri"]["duration_ms"] == 25


# ---------------------------------------------------------------------------
# Corrupted / malformed stored data
# ---------------------------------------------------------------------------
def test_corrupt_db_file_is_moved_aside_and_reinitialized(tmp_path, monkeypatch):
    hist, _ = _fresh_storage(tmp_path, monkeypatch)
    hist.mkdir(parents=True)
    db = hist / "history.db"
    db.write_bytes(b"this is not a sqlite database at all")
    conn = schema.connect_with_recovery(db)
    conn.close()
    assert schema.schema_version(db) == schema.SCHEMA_VERSION
    backups = list(hist.glob("history.db.corrupt-*"))
    assert len(backups) == 1
    # The application works again against the fresh database.
    assert qa_store.load_all_answers() == []


def test_malformed_history_json_reads_as_empty(tmp_path, monkeypatch):
    hist, _ = _fresh_storage(tmp_path, monkeypatch)
    hist.mkdir(parents=True)
    db = hist / "history.db"
    conn = sqlite3.connect(str(db))
    schema.apply_schema(conn)
    conn.execute(
        "INSERT INTO histories (resume_id, applied_job_ids, applied_jobs, last_updated) "
        "VALUES ('r1', 'not json', 'also not json', '2026-11-01')"
    )
    conn.commit()
    conn.close()
    history.HISTORY_DIR = hist  # module global used by _db_path
    loaded = history.load_history("r1")
    assert loaded["applied_job_ids"] == []
    assert loaded["applied_jobs"] == []


def test_malformed_profile_payload_reads_as_empty(tmp_path, monkeypatch):
    hist, _ = _fresh_storage(tmp_path, monkeypatch)
    hist.mkdir(parents=True)
    db = hist / "history.db"
    conn = sqlite3.connect(str(db))
    schema.apply_schema(conn)
    conn.execute("INSERT INTO profile_store (key, value) VALUES ('profile', '{broken')")
    conn.commit()
    conn.close()
    assert profiles.load_profile() == {}
    assert profiles.load_candidate_knowledge() == {}


# ---------------------------------------------------------------------------
# Duplicate-safe records
# ---------------------------------------------------------------------------
def test_duplicate_applied_jobs_not_recorded_twice(tmp_path, monkeypatch):
    _fresh_storage(tmp_path, monkeypatch)
    resume_text = "phase10 duplicate test resume"
    detail = {
        "job_id": "job-1",
        "url": "https://x/job/1",
        "status": "submitted",
        "title": "Dev",
        "company": "Acme",
        "applied_at": "2026-11-01T10:00:00",
    }
    history.save_applied_jobs(resume_text, ["job-1"], [detail])
    history.save_applied_jobs(resume_text, ["job-1"], [detail])
    saved = history.load_history(history.resume_id_from_text(resume_text))
    assert saved["applied_job_ids"].count("job-1") == 1
    assert sum(1 for job in saved["applied_jobs"] if job.get("job_id") == "job-1") == 1


def test_submission_attempt_marker_is_upserted(tmp_path, monkeypatch):
    _fresh_storage(tmp_path, monkeypatch)
    job = {"id": "job-dup", "url": "https://x/job/dup"}
    resume_text = "phase10 attempt resume"
    run_state.mark_submission_attempt(resume_text, job)
    run_state.mark_submission_attempt(resume_text, job)
    assert len(run_state.list_submission_attempts(resume_text)) == 1


# ---------------------------------------------------------------------------
# Migration / version handling
# ---------------------------------------------------------------------------
def test_schema_migrates_version_1_database(tmp_path):
    db = tmp_path / "history.db"
    conn = sqlite3.connect(str(db))
    conn.executescript("CREATE TABLE IF NOT EXISTS foo (id TEXT);")
    conn.execute("PRAGMA user_version = 1")
    conn.close()
    schema.connect_with_recovery(db).close()
    assert schema.schema_version(db) == schema.SCHEMA_VERSION


def test_schema_preserves_newer_version(tmp_path):
    db = tmp_path / "history.db"
    conn = sqlite3.connect(str(db))
    schema.apply_schema(conn)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    schema.connect_with_recovery(db).close()
    assert schema.schema_version(db) == 99  # never downgraded


def test_apply_schema_twice_is_stable(tmp_path):
    db = tmp_path / "history.db"
    conn = schema.connect_with_recovery(db)
    schema.apply_schema(conn)
    conn.close()
    assert schema.schema_version(db) == schema.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Atomic resume writes
# ---------------------------------------------------------------------------
def test_resume_copy_failure_leaves_no_partial_file(tmp_path, monkeypatch):
    hist, resumes = _fresh_storage(tmp_path, monkeypatch)
    from conftest import make_pdf

    src_pdf = tmp_path / "resume.pdf"
    src_pdf.write_bytes(make_pdf("Atomic resume copy test content."))

    import shutil

    def exploding_copy2(src, dst, *args, **kwargs):
        from pathlib import Path as _Path

        _Path(dst).write_bytes(b"partial garbage")
        raise OSError("disk full simulated")

    monkeypatch.setattr(shutil, "copy2", exploding_copy2)
    with pytest.raises(OSError):
        history.save_resume(str(src_pdf), "atomic-test")
    assert list(resumes.glob("*.tmp-*")) == []
    assert list(resumes.glob("*.pdf")) == []
