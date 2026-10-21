"""Tests for the persistent settings store and config override merge."""

from unittest.mock import patch

from jobhunter.config import PERSISTED_SETTING_KEYS, _persisted_overrides, get_settings
from jobhunter.storage import settings as settings_store


def test_settings_save_and_load_roundtrip():
    settings_store.save_settings({
        "naukri_email": "a@b.com",
        "auto_apply_mode": "auto",
        "max_applications_per_run": "7",
        "smtp_port": "2525",
    })
    loaded = settings_store.load_settings()
    assert loaded["naukri_email"] == "a@b.com"
    assert loaded["auto_apply_mode"] == "auto"
    assert loaded["max_applications_per_run"] == "7"
    assert loaded["smtp_port"] == "2525"


def test_save_empty_value_removes_key():
    settings_store.save_setting("naukri_email", "a@b.com")
    settings_store.save_setting("naukri_email", "")
    assert "naukri_email" not in settings_store.load_settings()


def test_persisted_overrides_type_coercion():
    settings_store.save_setting("max_applications_per_run", "9")
    settings_store.save_setting("smtp_port", "2525")
    overrides = _persisted_overrides()
    assert overrides["max_applications_per_run"] == 9
    assert overrides["smtp_port"] == 2525


def test_get_settings_applies_persisted_overrides():
    settings_store.save_setting("auto_apply_mode", "off")
    with patch("jobhunter.config._persisted_overrides", return_value={"auto_apply_mode": "off"}):
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.auto_apply_mode == "off"
    get_settings.cache_clear()


def test_persisted_keys_are_subset_of_settings_fields():
    from jobhunter.config import Settings

    fields = set(Settings.model_fields.keys())
    assert set(PERSISTED_SETTING_KEYS).issubset(fields)


# --- Encryption at rest -------------------------------------------------------

def _with_secret(monkeypatch, tmp_path, secret: str):
    """Point the store at a fresh tmp DB and (optionally) at a master secret."""
    import types

    from pydantic import SecretStr

    monkeypatch.setattr(settings_store, "HISTORY_DIR", tmp_path)
    monkeypatch.setattr(
        settings_store,
        "get_settings",
        lambda: types.SimpleNamespace(jobhunter_app_secret=SecretStr(secret)),
        raising=True,
    )


def _raw_value(key: str) -> str | None:
    """Read the raw stored (still-encrypted) value straight from SQLite."""
    import sqlite3

    conn = sqlite3.connect(str(settings_store._db_path()))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        conn.close()


def test_sensitive_values_encrypted_at_rest_with_secret(monkeypatch, tmp_path):
    _with_secret(monkeypatch, tmp_path, "unit-master-secret-01")
    settings_store.save_setting("naukri_password", "portal-pass-123")
    raw = _raw_value("naukri_password")
    assert raw is not None and raw.startswith("enc:v1:")
    assert "portal-pass-123" not in raw
    assert settings_store.load_settings()["naukri_password"] == "portal-pass-123"


def test_non_sensitive_values_stay_plaintext_with_secret(monkeypatch, tmp_path):
    _with_secret(monkeypatch, tmp_path, "unit-master-secret-01")
    settings_store.save_setting("naukri_email", "a@b.com")
    assert _raw_value("naukri_email") == "a@b.com"


def test_plaintext_values_still_load_after_secret_enabled(monkeypatch, tmp_path):
    _with_secret(monkeypatch, tmp_path, "")
    settings_store.save_setting("indeed_password", "old-plaintext")
    _with_secret(monkeypatch, tmp_path, "unit-master-secret-01")
    assert settings_store.load_settings()["indeed_password"] == "old-plaintext"


def test_wrong_secret_yields_empty_value(monkeypatch, tmp_path):
    _with_secret(monkeypatch, tmp_path, "correct-secret-01")
    settings_store.save_setting("naukri_password", "portal-pass-123")
    _with_secret(monkeypatch, tmp_path, "wrong-secret-01")
    assert settings_store.load_settings()["naukri_password"] == ""


def test_no_secret_stores_plaintext(monkeypatch, tmp_path):
    _with_secret(monkeypatch, tmp_path, "")
    settings_store.save_setting("naukri_password", "plain-and-fine")
    assert _raw_value("naukri_password") == "plain-and-fine"
