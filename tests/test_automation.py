"""Tests for the form-field classifier and job evaluator fallback."""

from jobhunter.automation.evaluator import _fallback_decision
from jobhunter.automation.form_filler import classify_field, is_skippable, normalize

RESUME = (
    "Software Engineer skilled in Python, Docker, AWS, machine learning, "
    "and RAG pipelines with LangChain."
)


def test_classify_email_by_name():
    assert classify_field("", "email", "", "") == "email"


def test_classify_phone_by_placeholder():
    assert classify_field("", "", "Mobile number", "") == "phone"


def test_classify_experience_by_label():
    assert classify_field("", "", "", "Years of experience") == "experience_years"


def test_classify_unknown_field():
    assert classify_field("", "xyz123", "", "") == "unknown"


def test_password_field_is_skippable():
    assert is_skippable("", "password", "", "")
    assert is_skippable("", "", "", "Enter OTP")
    assert not is_skippable("", "", "", "Your email")


def test_normalize_strips_formatting():
    assert normalize(" First  Name! ") == "firstname"


def test_fallback_decision_applies_on_good_match():
    job = {"title": "Python Engineer", "description": "Python, Docker, AWS, machine learning required."}
    decision = _fallback_decision(job, RESUME)
    assert decision["decision"] == "apply"
    assert decision["score"] >= 60


def test_fallback_decision_skips_on_poor_match():
    job = {"title": "Java Developer", "description": "Java Spring Boot microservices with Kafka."}
    decision = _fallback_decision(job, RESUME)
    assert decision["decision"] == "skip"
    assert 0 <= decision["score"] <= 100
