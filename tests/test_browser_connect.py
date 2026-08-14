"""Tests for the dedicated automation Chrome connection/launch logic."""

import json

import pytest

import jobhunter.automation.browser as browser_mod
from jobhunter.automation.browser import BrowserSession, launch_dedicated_browser
from jobhunter.config import Settings


def _session(tmp_path, **kwargs):
    return BrowserSession(
        tmp_path / "state",
        profile_dir=tmp_path / "automation_profile",
        debug_port=9222,
        use_dedicated_profile=True,
        **kwargs,
    )


def test_cdp_reachable_true(monkeypatch, tmp_path):
    class _FakeResp:
        status = 200

    class _FakeOpener:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return _FakeResp()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(browser_mod.urllib.request, "urlopen", lambda *a, **k: _FakeOpener())
    assert BrowserSession._cdp_reachable("http://127.0.0.1:9222")


def test_cdp_reachable_false(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(browser_mod.urllib.request, "urlopen", _boom)
    assert not BrowserSession._cdp_reachable("http://127.0.0.1:9222")


def test_resolved_profile_dir_defaults(tmp_path):
    session = BrowserSession(tmp_path / "state", profile_dir=None)
    assert session._resolved_profile_dir() == tmp_path / "state" / "automation_profile"


def test_resolved_profile_dir_explicit(tmp_path):
    session = BrowserSession(tmp_path / "state", profile_dir=tmp_path / "custom")
    assert session._resolved_profile_dir() == tmp_path / "custom"


def test_chrome_executable_found(monkeypatch, tmp_path):
    found = tmp_path / "chrome.exe"
    found.write_bytes(b"x")
    monkeypatch.setattr(
        BrowserSession, "_chrome_candidates",
        staticmethod(lambda: [found, tmp_path / "nope.exe"]),
    )
    assert BrowserSession._chrome_executable() == str(found)


def test_chrome_executable_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        BrowserSession, "_chrome_candidates",
        staticmethod(lambda: [tmp_path / "nope.exe"]),
    )
    assert BrowserSession._chrome_executable() is None


def test_launch_dedicated_launches_chrome(monkeypatch, tmp_path):
    session = _session(tmp_path)
    launched = {}

    monkeypatch.setattr(BrowserSession, "_chrome_executable", staticmethod(lambda: "C:/chrome.exe"))
    monkeypatch.setattr(BrowserSession, "_cdp_reachable", staticmethod(lambda url, timeout=3.0: True))
    monkeypatch.setattr(browser_mod.subprocess, "Popen", lambda args, **kw: launched.update(args=args))
    monkeypatch.setattr(browser_mod.time, "sleep", lambda s: None)

    session._launch_dedicated("http://127.0.0.1:9222")

    args = " ".join(launched["args"])
    assert "--user-data-dir" in args
    assert str(tmp_path / "automation_profile") in args
    assert "--remote-debugging-port=9222" in args


def test_launch_dedicated_raises_when_chrome_missing(monkeypatch, tmp_path):
    session = _session(tmp_path)
    monkeypatch.setattr(BrowserSession, "_chrome_executable", staticmethod(lambda: None))
    with pytest.raises(RuntimeError):
        session._launch_dedicated("http://127.0.0.1:9222")


def test_launch_dedicated_raises_when_port_never_opens(monkeypatch, tmp_path):
    session = _session(tmp_path)
    monkeypatch.setattr(BrowserSession, "_chrome_executable", staticmethod(lambda: "C:/chrome.exe"))
    monkeypatch.setattr(BrowserSession, "_cdp_reachable", staticmethod(lambda url, timeout=3.0: False))
    monkeypatch.setattr(browser_mod.subprocess, "Popen", lambda args, **kw: None)
    monkeypatch.setattr(browser_mod.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def fake_monotonic():
        calls["n"] += 1
        return calls["n"]

    monkeypatch.setattr(browser_mod.time, "monotonic", fake_monotonic)
    with pytest.raises(RuntimeError):
        session._launch_dedicated("http://127.0.0.1:9222")


def test_ensure_connected_launches_when_not_running(monkeypatch, tmp_path):
    session = _session(tmp_path)
    session._playwright = object()
    state = {"reachable": False, "launched": False, "attached": None}

    monkeypatch.setattr(BrowserSession, "_cdp_reachable", staticmethod(lambda url, timeout=3.0: state["reachable"]))

    def fake_launch(self, url):
        state["launched"] = True

    def fake_attach(self, url):
        state["attached"] = url
        self._context = object()
        return self._context

    monkeypatch.setattr(BrowserSession, "_launch_dedicated", fake_launch)
    monkeypatch.setattr(BrowserSession, "_attach_cdp", fake_attach)

    ctx = session.ensure_connected()
    assert state["launched"] is True
    assert state["attached"] == "http://127.0.0.1:9222"
    assert session.launched_new is True
    assert session.reused_existing is False
    assert session.using_dedicated_profile is True
    assert ctx is session._context


def test_ensure_connected_reuses_when_running(monkeypatch, tmp_path):
    session = _session(tmp_path)
    session._playwright = object()
    state = {"reachable": True, "launched": False, "attached": None}

    monkeypatch.setattr(BrowserSession, "_cdp_reachable", staticmethod(lambda url, timeout=3.0: state["reachable"]))

    def fake_launch(self, url):
        state["launched"] = True

    def fake_attach(self, url):
        state["attached"] = url
        self._context = object()
        return self._context

    monkeypatch.setattr(BrowserSession, "_launch_dedicated", fake_launch)
    monkeypatch.setattr(BrowserSession, "_attach_cdp", fake_attach)

    session.ensure_connected()
    assert state["launched"] is False
    assert session.launched_new is False
    assert session.reused_existing is True
    assert session.using_dedicated_profile is True


def test_start_falls_back_to_copied_profile_on_dedicated_failure(monkeypatch, tmp_path):
    session = _session(tmp_path, cdp_url="")

    def boom_connect(self):
        raise RuntimeError("no chrome found")

    monkeypatch.setattr(BrowserSession, "ensure_connected", boom_connect)
    fake_context = object()
    monkeypatch.setattr(BrowserSession, "_launch_copied_profile", lambda self: fake_context)
    monkeypatch.setattr(browser_mod, "sync_playwright", lambda: type("PW", (), {"start": lambda self: None})())

    assert session.start() is fake_context


def test_launch_dedicated_browser_status_already_running(monkeypatch, tmp_path):
    settings = Settings(
        browser_state_dir=tmp_path / "state",
        browser_profile_dir=tmp_path / "automation_profile",
        browser_debug_port=9222,
        browser_use_dedicated_profile=True,
    )
    monkeypatch.setattr(BrowserSession, "_cdp_reachable", staticmethod(lambda url, timeout=3.0: True))
    msg = launch_dedicated_browser(settings)
    assert "connected" in msg.lower()


def test_launch_dedicated_browser_status_launched(monkeypatch, tmp_path):
    settings = Settings(
        browser_state_dir=tmp_path / "state",
        browser_profile_dir=tmp_path / "automation_profile",
        browser_debug_port=9222,
        browser_use_dedicated_profile=True,
    )
    state = {"reachable": False}
    monkeypatch.setattr(BrowserSession, "_cdp_reachable", staticmethod(lambda url, timeout=3.0: state["reachable"]))

    def fake_launch(self, url):
        state["reachable"] = True

    monkeypatch.setattr(BrowserSession, "_launch_dedicated", fake_launch)
    msg = launch_dedicated_browser(settings)
    assert "started" in msg.lower()


# ------------------------------------------------------------- profile detection


def test_detect_chrome_user_data_dir_found(monkeypatch, tmp_path):
    home = tmp_path / "home"
    ud = home / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
    ud.mkdir(parents=True)
    (ud / "Local State").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(browser_mod.Path, "home", staticmethod(lambda: home))
    assert browser_mod.detect_chrome_user_data_dir() == ud


def test_detect_chrome_user_data_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_mod.Path, "home", staticmethod(lambda: tmp_path / "empty_home"))
    assert browser_mod.detect_chrome_user_data_dir() is None


def test_list_chrome_profiles_reads_info_cache(tmp_path):
    ud = tmp_path / "User Data"
    ud.mkdir()
    (ud / "Local State").write_text(
        json.dumps({"profile": {"info_cache": {"Default": "Ghanendra", "Profile 5": "HITLER"}}}),
        encoding="utf-8",
    )
    for name in ["Default", "Profile 2", "Profile 5", "not_a_profile"]:
        (ud / name).mkdir()
    profiles = browser_mod.list_chrome_profiles(ud)
    assert [(p.dir_name, p.friendly_name) for p in profiles] == [
        ("Default", "Ghanendra"),
        ("Profile 2", "Profile 2"),
        ("Profile 5", "HITLER"),
    ]
    assert profiles[0].is_default is True
    assert profiles[1].is_default is False


def test_list_chrome_profiles_corrupt_local_state(tmp_path):
    ud = tmp_path / "User Data"
    ud.mkdir()
    (ud / "Local State").write_text("not json{", encoding="utf-8")
    (ud / "Default").mkdir()
    (ud / "Profile 3").mkdir()
    profiles = browser_mod.list_chrome_profiles(ud)
    assert [(p.dir_name, p.friendly_name) for p in profiles] == [
        ("Default", "Default"),
        ("Profile 3", "Profile 3"),
    ]


def test_list_chrome_profiles_dict_form_info_cache(tmp_path):
    ud = tmp_path / "User Data"
    ud.mkdir()
    (ud / "Local State").write_text(
        json.dumps({
            "profile": {
                "info_cache": {
                    "Default": {"name": "Ghanendra", "shortcut_name": "Ghanendra"},
                    "Profile 5": {"name": "HITLER"},
                }
            }
        }),
        encoding="utf-8",
    )
    (ud / "Default").mkdir()
    (ud / "Profile 5").mkdir()
    profiles = browser_mod.list_chrome_profiles(ud)
    assert profiles[0].friendly_name == "Ghanendra"
    assert profiles[1].friendly_name == "HITLER"


def test_list_chrome_profiles_missing_ud(tmp_path):
    assert browser_mod.list_chrome_profiles(tmp_path / "nope") == []


def test_list_chrome_profiles_no_ud_detected(monkeypatch, tmp_path):
    monkeypatch.setattr(browser_mod, "detect_chrome_user_data_dir", lambda: None)
    assert browser_mod.list_chrome_profiles() == []


def test_logged_in_js_presence_only():
    js = browser_mod._logged_in_js([".ni-gnb-icn", "[class*='user']"])
    assert js.startswith("(() => ")
    assert "querySelector" in js
    assert ".ni-gnb-icn" in js
    assert "cookie" not in js.lower()


# ------------------------------------------------------------- status + helpers


def test_browser_status(monkeypatch, tmp_path):
    settings = Settings(
        browser_state_dir=tmp_path / "state",
        browser_profile_dir=tmp_path / "automation_profile",
        browser_debug_port=9222,
        browser_use_dedicated_profile=True,
    )
    monkeypatch.setattr(BrowserSession, "_cdp_reachable", staticmethod(lambda url, timeout=3.0: True))
    monkeypatch.setattr(browser_mod, "is_chrome_running", lambda: False)
    monkeypatch.setattr(browser_mod, "detect_chrome_user_data_dir", lambda: None)
    status = browser_mod.browser_status(settings)
    assert status["running"] is True
    assert status["cdp_url"] == "http://127.0.0.1:9222"
    assert status["chrome_running"] is False
    assert status["user_data_dir"] is None


def test_is_chrome_running_windows(monkeypatch):
    class _FakeRes:
        stdout = "INFO: chrome.exe running\n"

    monkeypatch.setattr(browser_mod.os, "name", "nt")
    monkeypatch.setattr(browser_mod.subprocess, "run", lambda *a, **k: _FakeRes())
    assert browser_mod.is_chrome_running() is True


def test_is_chrome_running_windows_not_running(monkeypatch):
    class _FakeRes:
        stdout = "INFO: No tasks are running\n"

    monkeypatch.setattr(browser_mod.os, "name", "nt")
    monkeypatch.setattr(browser_mod.subprocess, "run", lambda *a, **k: _FakeRes())
    assert browser_mod.is_chrome_running() is False


def test_check_portal_logins_returns_bool_map(monkeypatch, tmp_path):
    settings = Settings(
        browser_state_dir=tmp_path / "state",
        browser_profile_dir=tmp_path / "automation_profile",
        browser_debug_port=9222,
        browser_use_dedicated_profile=True,
    )

    class _FakePage:
        def evaluate(self, js):
            return True

        def wait_for_timeout(self, ms):
            return None

    class _FakeSession:
        def __init__(self, *a, **k):
            self.calls = []

        def start(self):
            self.calls.append("start")

        def new_tab(self, url):
            self.calls.append(url)
            return _FakePage()

        def close_page(self, page):
            self.calls.append("close")

        def stop(self):
            self.calls.append("stop")

    fake = _FakeSession()
    results = browser_mod.check_portal_logins(settings, session=fake)
    assert set(results) == {"naukri", "linkedin", "indeed"}
    assert all(isinstance(v, bool) for v in results.values())
    assert "start" not in fake.calls and "stop" not in fake.calls


def test_open_login_page(monkeypatch, tmp_path):
    settings = Settings(
        browser_state_dir=tmp_path / "state",
        browser_profile_dir=tmp_path / "automation_profile",
        browser_debug_port=9222,
        browser_use_dedicated_profile=True,
    )
    opened = {}

    class _FakeSession:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

        def open_page(self, url):
            opened["url"] = url

        def stop(self):
            pass

    monkeypatch.setattr(browser_mod, "build_session", lambda settings: _FakeSession())
    msg = browser_mod.open_login_page(settings, "https://example.com/login")
    assert opened["url"] == "https://example.com/login"
    assert "Opened" in msg
