"""Tests for analytics aggregation and SMTP notifications."""

from unittest.mock import MagicMock, patch

from jobhunter.services.analytics import get_analytics_data
from jobhunter.services.notifications import send_email_notification, send_job_alert_email

SAMPLE_HISTORIES = [
    {
        "applied_job_ids": ["a", "b"],
        "applied_jobs": [
            {"source": "naukri", "applied_at": "2026-08-01T10:00:00", "company": "Acme", "url": "https://acme/job/a"},
            {"source": "naukri", "applied_at": "2026-08-02T09:00:00", "company": "Acme", "url": "https://acme/job/b"},
        ],
    },
    {
        "applied_job_ids": ["c"],
        "applied_jobs": [
            {"source": "linkedin", "applied_at": "2026-08-01T18:00:00", "company": "Globex", "url": "https://globex/job/c"},
        ],
    },
]


def test_analytics_aggregates_counts(monkeypatch):
    monkeypatch.setattr("jobhunter.services.analytics.list_all_histories", lambda: SAMPLE_HISTORIES)
    monkeypatch.setattr("jobhunter.services.analytics.list_resumes", lambda: [{"id": "r1"}])

    data = get_analytics_data()
    assert data["total_applied"] == 3
    assert data["total_resumes"] == 1
    assert data["source_counts"] == {"naukri": 2, "linkedin": 1}
    assert data["daily_counts"] == {"2026-08-01": 2, "2026-08-02": 1}
    assert data["unique_jobs"] == 3
    assert data["top_companies"]["Acme"] == 2


def test_analytics_empty_history():
    with patch("jobhunter.services.analytics.list_all_histories", return_value=[]), \
         patch("jobhunter.services.analytics.list_resumes", return_value=[]):
        data = get_analytics_data()
    assert data["total_applied"] == 0
    assert data["source_counts"] == {}
    assert data["unique_jobs"] == 0


def test_send_email_no_recipient_skips():
    settings = MagicMock(notification_email="", smtp_host="", smtp_user="", smtp_pass="")
    with patch("jobhunter.services.notifications.get_settings", return_value=settings):
        assert send_email_notification("s", "b") is False


def test_send_email_smtp_unconfigured_skips():
    settings = MagicMock(notification_email="x@y.com", smtp_host="", smtp_user="", smtp_pass="")
    with patch("jobhunter.services.notifications.get_settings", return_value=settings):
        assert send_email_notification("s", "b") is False


def test_send_email_success():
    settings = MagicMock(
        notification_email="x@y.com",
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_user="user@test",
        smtp_pass="pw",
    )
    fake_server = MagicMock()
    fake_server.__enter__ = MagicMock(return_value=fake_server)
    fake_server.__exit__ = MagicMock(return_value=False)
    with patch("jobhunter.services.notifications.get_settings", return_value=settings), \
         patch("jobhunter.services.notifications.SMTP", return_value=fake_server) as smtp_cls:
        assert send_email_notification("Subject", "<b>body</b>") is True
        smtp_cls.assert_called_once_with("smtp.test", 587, timeout=30)
        fake_server.starttls.assert_called_once()
        fake_server.login.assert_called_once_with("user@test", "pw")
        fake_server.send_message.assert_called_once()


def test_send_email_failure_returns_false():
    settings = MagicMock(
        notification_email="x@y.com",
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_user="user@test",
        smtp_pass="pw",
    )
    with patch("jobhunter.services.notifications.get_settings", return_value=settings), \
         patch("jobhunter.services.notifications.SMTP", side_effect=RuntimeError("boom")):
        assert send_email_notification("Subject", "body") is False


def test_send_job_alert_email_builds_report():
    with patch("jobhunter.services.notifications.send_email_notification") as sender:
        send_job_alert_email("Data Analyst", 12, 3)
    sender.assert_called_once()
    subject, body = sender.call_args.args
    assert "Data Analyst" in subject
    assert "12" in body
    assert "3" in body
