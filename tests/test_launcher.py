"""One-click start: the launcher, the nyx:// link, start-with-Windows.

The bug these guard against was not in Python at all: Windows Smart App Control
blocked the unsigned Nyx.exe the logon task and shortcuts pointed at, so the
engine never started and nothing said why. The fix routes every entry point
through the signed pythonw.exe running launcher.py, and these tests pin that
wiring down — plus the behaviours that make a second click harmless.

The registry is faked; nothing here touches the real one.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

import launcher


# --- a dict-backed stand-in for winreg ------------------------------------------


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1

    def __init__(self):
        self.keys: dict[str, dict[str, str]] = {}

    class _Key:
        def __init__(self, reg, path):
            self.reg, self.path = reg, path

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def OpenKey(self, root, path, *args):
        if path not in self.keys:
            raise OSError("missing key")
        return self._Key(self, path)

    def CreateKey(self, root, path):
        self.keys.setdefault(path, {})
        return self._Key(self, path)

    def QueryValueEx(self, key, name):
        values = self.keys.get(key.path, {})
        if name not in values:
            raise OSError("missing value")
        return values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.keys.setdefault(key.path, {})[name] = value

    def DeleteValue(self, key, name):
        if name not in self.keys.get(key.path, {}):
            raise OSError("missing value")
        del self.keys[key.path][name]

    def DeleteKey(self, root, path):
        if path not in self.keys:
            raise OSError("missing key")
        del self.keys[path]


@pytest.fixture
def fake_registry(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(launcher.sys, "platform", "win32")
    return fake


# --- links ------------------------------------------------------------------------


@pytest.mark.parametrize("url,action", [
    ("nyx://start", "start"),
    ("nyx://start/", "start"),
    ("nyx://open", "open"),
    ("nyx:open", "open"),
    ("nyx://stop", "stop"),
    ("nyx://restart", "restart"),
    ("nyx://something-else", "open"),
    ("", "open"),
    ("https://example.com", "open"),
])
def test_links_map_to_actions(url, action):
    assert launcher.parse_link(url)[0] == action


def test_redeem_link_carries_the_key_into_the_app_url():
    action, params = launcher.parse_link("nyx://redeem?key=NYX1-abc.def%2B")
    assert action == "redeem"
    assert launcher.app_path_for(action, params) == "/?redeem=NYX1-abc.def%2B"


# --- how Windows starts us ------------------------------------------------------------


def test_source_install_launches_through_windowless_python(monkeypatch, tmp_path):
    """pythonw.exe is signed; a home-built exe is what Smart App Control blocks."""
    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.write_bytes(b"")
    pythonw.write_bytes(b"")
    monkeypatch.setattr(launcher.sys, "executable", str(python))
    monkeypatch.delattr(launcher.sys, "frozen", raising=False)

    argv = launcher.launch_command("--background")

    assert argv[0] == str(pythonw)
    assert argv[1].endswith("launcher.py")
    assert argv[2] == "--background"


def test_frozen_build_is_its_own_entry_point(monkeypatch):
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    monkeypatch.setattr(launcher.sys, "executable", r"C:\Nyx\Nyx.exe")
    assert launcher.launch_command("%1") == [r"C:\Nyx\Nyx.exe", "%1"]


def test_registry_command_line_quotes_paths_and_the_link_placeholder():
    line = launcher.command_line([r"C:\Program Files\py\pythonw.exe", r"C:\A B\launcher.py", "%1"])
    assert line == r'"C:\Program Files\py\pythonw.exe" "C:\A B\launcher.py" "%1"'
    assert launcher.command_line(["x.exe", "--background"]) == '"x.exe" --background'


def test_link_registration_is_per_user_and_points_at_this_install(fake_registry):
    assert launcher.register_url_handler() is True

    root = fake_registry.keys[r"Software\Classes\nyx"]
    assert root["URL Protocol"] == ""
    command = fake_registry.keys[r"Software\Classes\nyx\shell\open\command"][""]
    assert command == launcher.command_line(launcher.launch_command("%1"))
    assert launcher.url_handler_registered() is True


def test_link_registration_is_idempotent(fake_registry):
    launcher.register_url_handler()
    before = json.dumps(fake_registry.keys, sort_keys=True)
    launcher.register_url_handler()
    assert json.dumps(fake_registry.keys, sort_keys=True) == before


def test_unregistering_removes_the_link(fake_registry):
    launcher.register_url_handler()
    launcher.unregister_url_handler()
    assert launcher.url_handler_registered() is False


def test_start_with_windows_toggles_a_run_value_that_starts_quietly(fake_registry):
    assert launcher.autostart_enabled() is False

    assert launcher.set_autostart(True) is True
    value = fake_registry.keys[launcher._RUN_KEY][launcher.RUN_VALUE_NAME]
    assert value.endswith("--background")
    assert "pythonw.exe" in value or "Nyx.exe" in value

    assert launcher.set_autostart(False) is False
    assert launcher.RUN_VALUE_NAME not in fake_registry.keys[launcher._RUN_KEY]


def test_a_run_entry_for_another_copy_does_not_count_as_this_install_starting(fake_registry):
    with fake_registry.CreateKey(fake_registry.HKEY_CURRENT_USER, launcher._RUN_KEY) as key:
        fake_registry.SetValueEx(key, launcher.RUN_VALUE_NAME, 0, 1, r'"C:\Old\pythonw.exe" "C:\Old\launcher.py" --background')
    assert launcher.autostart_enabled() is False


def test_a_portable_copy_can_start_without_stealing_the_link(monkeypatch):
    registered = []
    monkeypatch.setattr(launcher, "register_url_handler", lambda: registered.append(True) or True)
    monkeypatch.setattr(launcher, "redirect_output_to_log", lambda: None)
    monkeypatch.setattr(launcher, "_SingleInstance", lambda: SimpleNamespace(owned=True, release=lambda: None))
    monkeypatch.setattr(launcher, "find_running_engine", lambda *a, **k: 8000)
    monkeypatch.setattr(launcher, "open_app", lambda *a, **k: None)

    launcher.main(["--no-register", "--no-browser"])

    assert registered == []


# --- finding a running engine ----------------------------------------------------------


def _serve(payload: dict) -> tuple[HTTPServer, int]:
    body = json.dumps(payload).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server naming
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def test_a_nyx_health_answer_is_recognised():
    server, port = _serve({"status": "ok", "capabilities": ["chat"], "claimed": False})
    try:
        assert launcher.probe_engine(port) is not None
    finally:
        server.shutdown()


def test_some_other_local_server_is_not_mistaken_for_nyx():
    """Opening the browser at an unrelated dev server would look like Nyx is broken."""
    server, port = _serve({"status": "ok"})
    try:
        assert launcher.probe_engine(port) is None
    finally:
        server.shutdown()


def test_a_busy_port_is_skipped_when_choosing_where_to_start():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        busy = holder.getsockname()[1]
        assert launcher.find_free_port(busy, limit=5) != busy


# --- a second click, and the link actions ---------------------------------------------


@pytest.fixture
def quiet_launcher(monkeypatch):
    """Neutralise side effects main() would otherwise have on this machine."""
    calls = SimpleNamespace(opened=[], controlled=[], started=[])
    monkeypatch.setattr(launcher, "redirect_output_to_log", lambda: None)
    monkeypatch.setattr(launcher, "register_url_handler", lambda: True)
    monkeypatch.setattr(launcher, "_SingleInstance", lambda: SimpleNamespace(owned=True, release=lambda: None))
    monkeypatch.setattr(launcher, "open_app", lambda port, path="/": calls.opened.append((port, path)))
    monkeypatch.setattr(launcher, "control_engine", lambda port, action: calls.controlled.append((port, action)) or True)
    monkeypatch.setattr(launcher, "_start_engine", lambda *a, **k: calls.started.append(a) or 0)
    return calls


def test_clicking_while_nyx_runs_opens_it_instead_of_starting_a_second_copy(monkeypatch, quiet_launcher):
    monkeypatch.setattr(launcher, "find_running_engine", lambda *a, **k: 8000)

    assert launcher.main([]) == 0

    assert quiet_launcher.opened == [(8000, "/")]
    assert quiet_launcher.started == []


def test_the_start_link_does_not_pop_a_second_browser_tab(monkeypatch, quiet_launcher):
    """The web page's Turn on button already has a tab open and reconnects itself."""
    monkeypatch.setattr(launcher, "find_running_engine", lambda *a, **k: 8000)

    launcher.main(["nyx://start"])

    assert quiet_launcher.opened == []


def test_the_stop_link_asks_the_running_engine_to_stop(monkeypatch, quiet_launcher):
    monkeypatch.setattr(launcher, "find_running_engine", lambda *a, **k: 8001)

    assert launcher.main(["nyx://stop"]) == 0

    assert quiet_launcher.controlled == [(8001, "stop")]
    assert quiet_launcher.started == []


def test_nothing_running_means_the_engine_is_started(monkeypatch, quiet_launcher):
    monkeypatch.setattr(launcher, "find_running_engine", lambda *a, **k: None)

    launcher.main(["--background"])

    assert len(quiet_launcher.started) == 1


def test_a_redeem_link_opens_the_app_on_the_redeem_screen(monkeypatch, quiet_launcher):
    monkeypatch.setattr(launcher, "find_running_engine", lambda *a, **k: 8000)

    launcher.main(["nyx://redeem?key=NYX1-k.s"])

    assert quiet_launcher.opened == [(8000, "/?redeem=NYX1-k.s")]


# --- the files people actually double-click ------------------------------------------------


PROJECT = Path(launcher.__file__).resolve().parent


def test_start_nyx_bat_uses_the_launcher_and_setup_not_a_raw_server_command():
    text = (PROJECT / "Start Nyx.bat").read_bytes()
    assert b"\r\n" in text, "batch files need CRLF line endings or labels misbehave"
    body = text.decode("utf-8")
    assert "launcher.py" in body
    assert "setup_nyx.py" in body
    assert "pythonw.exe" in body
    assert "uvicorn" not in body


def test_the_logon_runner_no_longer_points_at_the_blocked_exe():
    body = (PROJECT / "run-nyx-background.cmd").read_text(encoding="utf-8")
    command_lines = [line for line in body.splitlines() if not line.lower().lstrip().startswith("rem")]
    assert not any("Nyx.exe" in line for line in command_lines)
    assert "launcher.py" in body and "--background" in body
