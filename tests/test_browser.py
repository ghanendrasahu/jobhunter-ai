"""Tests for the minimal Chrome profile copy."""

from pathlib import Path

import pytest

from jobhunter.automation.browser import _copy_minimal_profile


@pytest.fixture
def fake_chrome_profile(tmp_path: Path):
    src = tmp_path / "user-data"
    src_default = src / "Default"
    src_default.mkdir(parents=True)
    (src / "Local State").write_text('{"crypto_key": 1}')
    (src / "First Run").write_text("x")
    (src / "Default" / "Preferences").write_text('{"prefs": 1}')
    (src / "Default" / "Network").mkdir()
    (src / "Default" / "Network" / "Cookies").write_bytes(b"cookies")
    cache = src_default / "Cache"
    cache.mkdir()
    (cache / "big.bin").write_bytes(b"0" * 1000)
    return src


def test_copy_creates_expected_files(fake_chrome_profile, tmp_path):
    dst = tmp_path / "profile-copy"
    _copy_minimal_profile(fake_chrome_profile, dst)
    assert (dst / "Local State").exists()
    assert (dst / "First Run").exists()
    assert (dst / "Default" / "Preferences").exists()
    assert (dst / "Default" / "Network" / "Cookies").exists()
    assert not (dst / "Default" / "Cache").exists()


def test_copy_tolerates_locked_file(fake_chrome_profile, tmp_path, monkeypatch):
    import shutil

    dst = tmp_path / "profile-copy"
    original = shutil.copy2
    calls = {"n": 0}

    def flaky_copy(src, dst2, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1 and Path(src).name == "Local State":
            raise PermissionError("locked")
        return original(src, dst2, *args, **kwargs)

    monkeypatch.setattr(shutil, "copy2", flaky_copy)
    _copy_minimal_profile(fake_chrome_profile, dst)
    assert (dst / "Local State").exists()


def test_copy_raises_when_local_state_missing(tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    with pytest.raises(RuntimeError):
        _copy_minimal_profile(src, tmp_path / "out")
