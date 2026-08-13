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
