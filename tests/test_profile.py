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


def test_profile_extracts_title():
    profile = profile_from_resume(RESUME)
    assert profile["current_title"] == "Software Engineer"


def test_profile_extracts_ctc_and_notice_period():
    resume = (
        "Riya Patel\nBengaluru\n\n"
        "Data Analyst with 3 years of experience.\n"
        "Current CTC: 8 LPA | Expected CTC: 12 LPA\n"
        "Notice Period: 30 days\n"
        "LinkedIn: linkedin.com/in/riya-patel\n"
    )
    profile = profile_from_resume(resume)
    assert profile["current_ctc"] == "8 LPA"
    assert profile["expected_ctc"] == "12 LPA"
    assert profile["notice_period"] == "30 days"
    assert profile["linkedin"] == "https://linkedin.com/in/riya-patel"


def test_profile_builds_cover_letter():
    profile = profile_from_resume(RESUME)
    assert profile["cover_letter"]
    assert "Software Engineer" in profile["cover_letter"]


def test_profile_empty_input_is_safe():
    profile = profile_from_resume("")
    assert profile["email"] == ""
    assert profile["skills"] == []
    assert profile["current_title"] == ""
    assert profile["cover_letter"] == ""
