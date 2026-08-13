"""Tests for portal strategies (search URL, apply clicks, obstacle detection)."""

from unittest.mock import MagicMock

from jobhunter.automation.strategies import (
    build_search_url,
    click_apply,
    click_by_text,
    detect_obstacle,
    fill_input,
)


def test_build_search_url_encodes_query():
    url = build_search_url("naukri", "Data Analyst")
    assert "Data%20Analyst" in url
    assert "naukri.com" in url


def test_click_by_text_success():
    page = MagicMock()
    assert click_by_text(page, "Sign in") is True


def test_click_by_text_failure():
    page = MagicMock()
    page.get_by_text.side_effect = RuntimeError("missing")
    assert click_by_text(page, "Sign in") is False


def test_fill_input_success():
    page = MagicMock()
    assert fill_input(page, "#email", "a@b.com") is True
    page.fill.assert_called_once_with("#email", "a@b.com", timeout=5000)


def test_fill_input_failure():
    page = MagicMock()
    page.fill.side_effect = RuntimeError("stale")
    assert fill_input(page, "#email", "a@b.com") is False


def test_click_apply_visible():
    page = MagicMock()
    first = MagicMock()
    first.wait_for = MagicMock()
    first.count.return_value = 1
    first.first = first
    visible = MagicMock()
    visible.is_visible.return_value = True
    first.nth = MagicMock(return_value=visible)
    page.locator.return_value = first
    assert click_apply(page) is True
    visible.click.assert_called_once()


def test_click_apply_js_fallback():
    page = MagicMock()
    first = MagicMock()
    first.wait_for = MagicMock()
    first.count.return_value = 1
    first.first = first
    hidden = MagicMock()
    hidden.is_visible.return_value = False
    first.nth = MagicMock(return_value=hidden)
    page.locator.return_value = first
    assert click_apply(page) is True
    first.evaluate.assert_called_once()


def test_click_apply_missing_returns_false():
    page = MagicMock()
    first = MagicMock()
    first.first = first
    first.wait_for.side_effect = RuntimeError("timeout")
    page.locator.return_value = first
    assert click_apply(page) is False


def test_detect_obstacle():
    assert detect_obstacle("https://naukri.com", "Please complete a CAPTCHA") is not None
    assert detect_obstacle("https://naukri.com", "Showing 120 jobs for you") is None
