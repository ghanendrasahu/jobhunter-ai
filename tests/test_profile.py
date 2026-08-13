"""Tests for the resume profile extractor."""

from jobhunter.automation.profile import profile_from_resume

RESUME = """
Aarav Sharma
Bengaluru

Email: aarav.sharma@gmail.com | Phone: +91 98765 43210

Software Engineer with 5+ years of experience.
Skills: Python, Docker, AWS, machine learning, LangChain.
Education: B.Tech in Computer Science.
"""


def test_profile_extracts_contact():
    profile = profile_from_resume(RESUME)
    assert profile["email"] == "aarav.sharma@gmail.com"
    assert "9876543210" in profile["phone"]


def test_profile_extracts_name_and_location():
    profile = profile_from_resume(RESUME)
    assert profile["full_name"] == "Aarav Sharma"
    assert profile["location"] == "Bengaluru"


def test_profile_extracts_experience_and_skills():
    profile = profile_from_resume(RESUME)
    assert profile["experience_years"] == 5
    assert "python" in profile["skills"]
    assert "docker" in profile["skills"]


def test_profile_extracts_education():
    profile = profile_from_resume(RESUME)
    assert profile["education"]


def test_profile_empty_input_is_safe():
    profile = profile_from_resume("")
    assert profile["email"] == ""
    assert profile["skills"] == []
