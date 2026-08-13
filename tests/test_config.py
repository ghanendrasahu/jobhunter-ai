"""Tests for configuration helpers (API-key validation)."""

from unittest.mock import patch

from jobhunter.config import missing_api_keys


def test_missing_api_keys_reports_unset():
    with patch("jobhunter.config.get_settings") as settings:
        settings.return_value.openai_api_key = ""
        settings.return_value.groq_api_key = ""
        settings.return_value.jsearch_api_key = ""
        settings.return_value.adzuna_app_id = ""
        settings.return_value.adzuna_api_key = ""
        settings.return_value.jooble_api_key = ""
        missing = missing_api_keys()
        assert "OPENAI_API_KEY" in missing
        assert "GROQ_API_KEY" in missing


def test_missing_api_keys_empty_when_configured():
    with patch("jobhunter.config.get_settings") as settings:
        settings.return_value.openai_api_key = "sk-test"
        settings.return_value.groq_api_key = "gsk-test"
        settings.return_value.jsearch_api_key = "js-test"
        settings.return_value.adzuna_app_id = "id"
        settings.return_value.adzuna_api_key = "key"
        settings.return_value.jooble_api_key = "jb-test"
        assert missing_api_keys() == []
