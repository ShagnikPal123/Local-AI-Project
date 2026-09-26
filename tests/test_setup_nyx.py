"""The one-time setup that turns a Nyx folder into a one-click app.

Everything with a side effect on the machine (pip, npm, PowerShell shortcuts, the
registry, starting processes) is replaced with a recorder.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import setup_nyx


def test_missing_modules_names_what_is_absent():
    assert setup_nyx.missing_modules(("json", "definitely_not_a_module_nyx")) == ["definitely_not_a_module_nyx"]


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    calls = SimpleNamespace(shortcuts=[], autostart=[], spawned=[], registered=0)
    monkeypatch.setattr(setup_nyx.sys, "platform", "win32")
    monkeypatch.setattr(setup_nyx.sys, "prefix", str(tmp_path))
    monkeypatch.setattr(setup_nyx, "ensure_packages", lambda: True)
    monkeypatch.setattr(setup_nyx, "ensure_ui", lambda: True)
    monkeypatch.setattr(setup_nyx, "shortcut_targets",
                        lambda: [tmp_path / "Desktop" / "Nyx Ichos.lnk", tmp_path / "Programs" / "Nyx Ichos.lnk"])

    def fake_create(location: Path) -> bool:
        calls.shortcuts.append(location)
        return True

    def fake_register() -> bool:
        calls.registered += 1
        return True

    monkeypatch.setattr(setup_nyx, "create_shortcut", fake_create)
    monkeypatch.setattr(setup_nyx.launcher, "register_url_handler", fake_register)
    monkeypatch.setattr(setup_nyx.launcher, "set_autostart", lambda on: calls.autostart.append(on) or on)
    monkeypatch.setattr(setup_nyx.launcher, "_spawn_detached", lambda argv: calls.spawned.append(argv))
    return calls


def test_install_wires_every_one_click_entry_point(recorded, tmp_path):
    assert setup_nyx.install() == 0

    assert recorded.registered == 1
    assert [p.parent.name for p in recorded.shortcuts] == ["Desktop", "Programs"]
    assert recorded.autostart == [True]
    assert len(recorded.spawned) == 1, "setup should finish by starting Nyx"
    assert (tmp_path / setup_nyx.READY_MARKER).is_file(), "Start Nyx.bat relies on this to take its fast path"


def test_autostart_and_launch_can_be_skipped(recorded):
    assert setup_nyx.install(autostart=False, launch=False) == 0
    assert recorded.autostart == []
    assert recorded.spawned == []


def test_install_stops_when_packages_cannot_be_installed(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(setup_nyx, "ensure_packages", lambda: False)

    assert setup_nyx.install() == 1
    assert recorded.spawned == []
    assert not (tmp_path / setup_nyx.READY_MARKER).exists()


def test_uninstall_removes_links_but_never_user_data(recorded, monkeypatch, tmp_path):
    setup_nyx.install(launch=False)
    removed = SimpleNamespace(unregistered=False)
    monkeypatch.setattr(setup_nyx.launcher, "unregister_url_handler", lambda: setattr(removed, "unregistered", True))
    monkeypatch.setattr(setup_nyx, "remove_shortcuts", lambda: [])
    data_file = tmp_path / "chats.json"
    data_file.write_text("{}", encoding="utf-8")

    assert setup_nyx.uninstall() == 0

    assert removed.unregistered is True
    assert recorded.autostart[-1] is False
    assert not (tmp_path / setup_nyx.READY_MARKER).exists()
    assert data_file.exists()


def test_shortcut_paths_travel_through_the_environment_not_the_command_text(monkeypatch, tmp_path):
    """The project lives under a folder name with spaces; quoting it in a
    PowerShell command string is exactly the kind of thing that breaks."""
    captured = {}

    def fake_powershell(script, env):
        captured["script"], captured["env"] = script, env
        (tmp_path / "Nyx Ichos.lnk").write_bytes(b"lnk")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(setup_nyx, "_powershell", fake_powershell)

    assert setup_nyx.create_shortcut(tmp_path / "Nyx Ichos.lnk") is True
    assert str(tmp_path) not in captured["script"]
    assert captured["env"]["NYX_LNK"].endswith("Nyx Ichos.lnk")
    assert captured["env"]["NYX_ARGS"].endswith('launcher.py"') or captured["env"]["NYX_ARGS"] == ""
