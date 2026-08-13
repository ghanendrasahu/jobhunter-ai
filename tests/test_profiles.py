"""Tests for the persisted profile + roles store."""

from jobhunter.storage import profiles


def test_profile_roundtrip():
    profiles.save_profile({"full_name": "Test User", "email": "a@b.com", "skills": ["python", "sql"]})
    loaded = profiles.load_profile()
    assert loaded["full_name"] == "Test User"
    assert loaded["email"] == "a@b.com"
    assert loaded["skills"] == ["python", "sql"]


def test_profile_clear():
    profiles.save_profile({})
    assert profiles.load_profile() == {}


def test_selected_roles_roundtrip():
    profiles.save_selected_roles(["Data Scientist", "Data Analyst"])
    assert profiles.load_selected_roles() == ["Data Scientist", "Data Analyst"]
    profiles.save_selected_roles([])
    assert profiles.load_selected_roles() == []


def test_suggested_roles_roundtrip():
    profiles.save_suggested_roles([{"title": "Data Scientist", "tier": 1, "score": 0.9}])
    assert profiles.load_suggested_roles() == [{"title": "Data Scientist", "tier": 1, "score": 0.9}]
