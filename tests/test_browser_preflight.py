"""Tests for browser preflight error when executable is missing."""

from unittest.mock import MagicMock

import pytest

from jobhunter.automation.browser import BrowserSession, _BrowserMissing


def test_verify_bundled_chromium_raises_when_missing(tmp_path):
    session = BrowserSession(tmp_path)
    # mock sync_playwright / chromium.executable_path to point to non-existent path
    fake_pw = MagicMock()
    fake_pw.chromium.executable_path = str(tmp_path / "nonexistent" / "chrome.exe")
    session._playwright = fake_pw

    with pytest.raises(_BrowserMissing):
        session._verify_bundled_chromium()
