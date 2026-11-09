"""Page-management and detach semantics of BrowserSession (fakes; no browser)."""

import pytest

from jobhunter.automation.browser import BrowserSession


class _FakePage:
    def __init__(self):
        self.closed = False
        self.navigated: list[str] = []

    def goto(self, url, **kwargs):
        self.navigated.append(url)

    def is_closed(self):
        return self.closed

    def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self):
        self.closed = False
        self.saved_state_path = ""

    def new_page(self):
        return _FakePage()

    def close(self):
        self.closed = True

    def storage_state(self, path=None):
        self.saved_state_path = path
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{}")


class _FakePlaywright:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


def _session(tmp_path) -> BrowserSession:
    session = BrowserSession(tmp_path / "state", headless=True)
    session._context = _FakeContext()
    session._playwright = _FakePlaywright()
    return session


def test_new_tab_navigates_and_tracks_pages(tmp_path):
    session = _session(tmp_path)
    page = session.new_tab("https://naukri.com/jobs")
    assert "https://naukri.com/jobs" in page.navigated
    assert page in session._agent_pages


def test_new_page_before_start_raises(tmp_path):
    session = BrowserSession(tmp_path / "state", headless=True, cdp_url="")
    with pytest.raises(RuntimeError):
        session.new_page()


def test_open_page_before_start_raises(tmp_path):
    session = BrowserSession(tmp_path / "state", headless=True, cdp_url="")
    with pytest.raises(RuntimeError):
        session.open_page("https://example.com")


def test_open_page_is_not_registered_for_cleanup(tmp_path):
    session = _session(tmp_path)
    page = session.open_page("https://naukri.com/login")
    assert page not in session._agent_pages
    assert "https://naukri.com/login" in page.navigated


def test_close_all_pages_closes_only_agent_pages(tmp_path):
    session = _session(tmp_path)
    keep = session.open_page("https://naukri.com/login")
    agent_page = session.new_tab("https://naukri.com/job/1")
    session.close_all_pages()
    assert agent_page.closed is True
    assert keep.closed is False  # the user's login tab survives


def test_stop_cdp_detaches_without_closing_context(tmp_path):
    session = _session(tmp_path)
    session.using_cdp = True
    context = session._context
    playwright = session._playwright
    session.stop()
    assert context.closed is False  # never close the user's browser
    assert playwright.stopped is True  # detached from CDP


def test_stop_non_cdp_closes_context_and_saves_state(tmp_path):
    session = _session(tmp_path)
    context = session._context
    playwright = session._playwright
    session.new_tab("https://www.naukri.com/job/1")
    session.stop()
    assert context.closed is True
    assert playwright.stopped is True
    assert (tmp_path / "state" / "storage_state.json").exists()
