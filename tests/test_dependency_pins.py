"""Guard ``pyproject.toml`` and ``requirements.txt`` from drifting apart.

``requirements.txt`` is documented as a mirror of the runtime pins in
``pyproject.toml`` (the flat-install path that Docker uses). If they drift,
one install path keeps working while the other silently changes behaviour;
this test turns such drift into a red suite.
"""

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_PIN_LINE = re.compile(r"^([A-Za-z0-9_.-]+(?:\[[^\]]*\])?)\s*==\s*([^\s;]+)")


def _runtime_pins_from_pyproject() -> set[str]:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = data["project"]["dependencies"]
    return {re.sub(r"\s+", "", dep) for dep in deps}


def _pins_from_requirements() -> set[str]:
    lines = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pins: set[str] = set()
    seen_directives = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _PIN_LINE.match(stripped)
        if match:
            seen_directives = True
            pins.add(f"{match.group(1)}=={match.group(2)}")
            continue
        raise AssertionError(f"requirements.txt contains an unsupported directive: {line!r}")
    assert seen_directives, "no pinned dependencies found in requirements.txt"
    return pins


def test_requirements_mirror_pyproject_pins():
    pyproject_pins = _runtime_pins_from_pyproject()
    requirements_pins = _pins_from_requirements()

    missing_from_requirements = pyproject_pins - requirements_pins
    missing_from_pyproject = requirements_pins - pyproject_pins

    assert not missing_from_requirements, (
        "dependencies pinned in pyproject.toml but missing in requirements.txt: "
        f"{sorted(missing_from_requirements)}"
    )
    assert not missing_from_pyproject, (
        "dependencies pinned in requirements.txt but not in pyproject.toml: "
        f"{sorted(missing_from_pyproject)}"
    )
