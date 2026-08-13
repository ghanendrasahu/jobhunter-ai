"""SMTP email notifications."""

from __future__ import annotations

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from smtplib import SMTP

from jobhunter.config import get_settings

logger = logging.getLogger(__name__)


def send_email_notification(subject: str, body: str, to_email: str | None = None) -> bool:
    """Send an HTML email. Requires SMTP_* and NOTIFICATION_EMAIL in the environment.

    Returns True on success, False when not configured or on failure.
    """
    settings = get_settings()
    to_email = to_email or settings.notification_email
    if not to_email:
        logger.info("No NOTIFICATION_EMAIL set — skipping email")
        return False

    if not all([settings.smtp_host, settings.smtp_user, settings.smtp_pass]):
        logger.info("SMTP not configured — skipping email")
        return False

    try:
        message = MIMEMultipart()
        message["From"] = settings.smtp_user
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(body, "html"))

        with SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_pass)
            server.send_message(message)

        logger.info("Email sent to %s: %s", to_email, subject)
        return True
    except Exception as exc:
        logger.warning("Failed to send email: %s", exc)
        return False


def send_job_alert_email(query: str, jobs_found: int, apps_submitted: int) -> None:
    """Send a summary email after a pipeline run."""
    subject = f"JobHunter AI: {apps_submitted} applications submitted for '{query}'"
    body = f"""
    <h2>JobHunter AI Pipeline Report</h2>
    <p><strong>Search Query:</strong> {query}</p>
    <p><strong>Jobs Found:</strong> {jobs_found}</p>
    <p><strong>Applications:</strong> {apps_submitted}</p>
    <hr>
    <p style="color: #666;">Automated from JobHunter AI</p>
    """
    send_email_notification(subject, body)
