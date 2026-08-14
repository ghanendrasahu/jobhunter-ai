"""Tests for the skill taxonomy, normalization, and role-family inference."""

from jobhunter.domains.skills import group_skills, infer_role_family, normalize_skill


def test_normalize_skill_aliases():
    assert normalize_skill("PyTorch") == "pytorch"
    assert normalize_skill("ML") == "machine learning"
    assert normalize_skill("  Postgres ") == "postgresql"
    assert normalize_skill("") == ""


def test_normalize_skill_unknown_passthrough():
    assert normalize_skill("LangGraph") == "langgraph"


def test_group_skills_assigns_to_first_group():
    grouped = group_skills(["python", "pytorch", "langchain", "django", "kafka", "weirdskill"])
    assert grouped["languages"] == ["python"]
    assert grouped["ml_ds"] == ["pytorch"]
    assert grouped["genai"] == ["langchain"]
    assert grouped["web"] == ["django"]
    assert grouped["data_engineering"] == ["kafka"]
    assert grouped["other"] == ["weirdskill"]


def test_group_skills_normalizes_input():
    grouped = group_skills(["ML", "PyTorch"])
    assert "machine learning" in grouped["ml_ds"]


def test_group_skills_omits_empty_groups():
    assert group_skills([]) == {}


def test_infer_role_family_data_science():
    assert infer_role_family(["pytorch", "langchain", "pandas"]) == "data_science"


def test_infer_role_family_software():
    assert infer_role_family(["react", "django", "javascript"]) == "software"


def test_infer_role_family_devops():
    assert infer_role_family(["docker", "kubernetes", "terraform"]) == "devops"


def test_infer_role_family_empty_is_unknown():
    assert infer_role_family([]) == ""
    assert infer_role_family(["cooking", "gardening"]) == ""
