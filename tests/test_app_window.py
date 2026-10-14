"""Nyx's own desktop window (app_window.py): the parts that run without Windows or a real WebView2.

What matters here is what the owner sees: one window per app, its last size and place, the session never in a
URL, and the browser still one click away. pywebview and the Win32 calls are faked; nothing opens a window.
"""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace

import app_window


def test_unknown_apps_open_the_full_app():
    assert app_window.app_name("nyx") == "nyx"
    assert app_window.app_name("  NYX ") == "nyx"
    assert app_window.app_name("not-an-app") == "nyx"
    assert app_window.app_spec("whatever")["title"] == "Nyx Ichos"


def test_the_page_is_told_it_is_inside_the_app_window_and_keeps_its_query():
    assert app_window.window_url("http://localhost:8000/") == "http://localhost:8000/?shell=app"
    assert app_window.window_url("http://localhost:8000/?redeem=abc") == "http://localhost:8000/?redeem=abc&shell=app"
    once = app_window.window_url("http://localhost:8000/")
    assert app_window.window_url(once) == once


def test_the_command_runs_this_file_and_carries_no_session():
    argv = app_window.command("nyx", "http://localhost:8000/")
    assert argv[1].endswith("app_window.py")
    assert argv[2:] == ["--app", "nyx", "--url", "http://localhost:8000/"]


def test_geometry_is_remembered_per_app_and_cleaned_up(tmp_path, monkeypatch):
    import paths

    monkeypatch.setattr(paths, "data_path", lambda name: tmp_path / name)
    assert app_window.load_geometry("nyx") == {"width": 1280, "height": 820, "maximized": False}

    app_window.save_geometry("nyx", {"width": 1500, "height": 900, "x": 40, "y": 30, "maximized": True})
    assert app_window.load_geometry("nyx") == {"width": 1500, "height": 900, "x": 40, "y": 30, "maximized": True}

    # A tiny size or a monitor that was unplugged must never give an unusable or invisible window.
    (tmp_path / "app_window.json").write_text(json.dumps({"nyx": {"width": 50, "height": "x", "x": -9000, "y": 5}}))
    assert app_window.load_geometry("nyx") == {"width": 720, "height": 820, "maximized": False}

    (tmp_path / "app_window.json").write_text("not json")
    assert app_window.load_geometry("nyx")["width"] == 1280


def test_the_bridge_hands_the_session_over_once_and_opens_the_browser_on_request(monkeypatch):
    opened = []
    monkeypatch.setattr(app_window.webbrowser, "open", lambda url: opened.append(url))
    bridge = app_window.Bridge("session-123", "http://localhost:8000/?shell=app")
    assert bridge.token() == "session-123"
    assert bridge.token() == "", "a page that navigated elsewhere cannot ask again"
    bridge.open_in_browser("chat")
    assert opened == ["http://localhost:8000/chat"]


def test_a_second_open_brings_the_first_window_forward(monkeypatch):
    forward = []
    monkeypatch.setattr(app_window, "set_taskbar_identity", lambda app_id: None)
    monkeypatch.setattr(app_window, "find_window", lambda title: 4242)
    monkeypatch.setattr(app_window, "bring_forward", lambda hwnd: forward.append(hwnd))
    monkeypatch.setitem(sys.modules, "webview", None)  # importing it would fail: it must not get that far
    assert app_window.main(["--app", "nyx"]) == 0
    assert forward == [4242]


def test_the_window_opens_with_the_remembered_size_and_saves_it_on_close(tmp_path, monkeypatch):
    import paths

    monkeypatch.setattr(paths, "data_path", lambda name: tmp_path / name)
    monkeypatch.setenv("NYX_APP_TOKEN", "session-123")
    monkeypatch.setattr(app_window, "set_taskbar_identity", lambda app_id: None)
    monkeypatch.setattr(app_window, "find_window", lambda title: 0)

    class Event(list):
        def __iadd__(self, handler):
            self.append(handler)
            return self

    created = {}
    events = SimpleNamespace(**{name: Event() for name in ("shown", "resized", "moved", "maximized", "restored", "closing")})

    def create_window(title, url, **kw):
        created.update(title=title, url=url, **kw)
        return SimpleNamespace(events=events)

    started = {}
    fake = SimpleNamespace(create_window=create_window, start=lambda **kw: started.update(kw))
    monkeypatch.setitem(sys.modules, "webview", fake)

    assert app_window.main(["--url", "http://localhost:8001/"]) == 0
    assert created["title"] == "Nyx Ichos" and created["url"] == "http://localhost:8001/?shell=app"
    assert created["width"] == 1280 and created["js_api"].token() == "session-123"
    assert "NYX_APP_TOKEN" not in __import__("os").environ, "the session leaves the environment once read"
    assert started["private_mode"] is False, "the window keeps its sign-in and settings like a browser profile"

    events.resized[0](1400, 950)
    events.moved[0](12, 34)
    events.closing[0]()
    assert app_window.load_geometry("nyx") == {"width": 1400, "height": 950, "x": 12, "y": 34, "maximized": False}
