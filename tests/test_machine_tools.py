"""Machine tools: real work on the PC, safe defaults, visible and permissioned."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

import pytest

import machine_tools
import permissions
from tools import ToolRegistry


def test_every_tool_registers_with_a_category_and_label():
    registry = ToolRegistry()
    machine_tools.register_machine_tools(registry)
    names = set(registry.tools)
    assert {"run_command", "run_python", "write_file", "delete_path", "search_files", "kill_process",
            "set_volume", "notify", "open_app", "view_image", "get_environment"} <= names
    categories = {t.name: t.category for t in registry.list_tools()}
    assert categories["run_command"] == "shell"
    assert categories["delete_path"] == "files.delete"
    assert categories["run_python"] == "code"
    for tool in registry.list_tools():
        assert all(hasattr(p, "param_type") for p in tool.parameters)


def test_run_command_reports_exit_code_and_output(monkeypatch, tmp_path):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(argv=argv, cwd=kwargs.get("cwd"))
        return SimpleNamespace(returncode=0, stdout="hello\n", stderr="")

    monkeypatch.setattr(machine_tools.subprocess, "run", fake_run)
    result = machine_tools.run_command("Write-Output hello", cwd=str(tmp_path))
    assert result.startswith("Exit code 0") and "hello" in result
    assert seen["argv"][0] == "powershell" and seen["cwd"] == str(tmp_path)


def test_run_command_times_out_cleanly(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"), output="partial")

    monkeypatch.setattr(machine_tools.subprocess, "run", fake_run)
    assert machine_tools.run_command("sleep 999", timeout_seconds=2).startswith("Timed out after 2s")


def test_run_python_really_runs_code():
    result = machine_tools.run_python("print(6 * 7)")
    assert "Exit code 0" in result and "42" in result


def test_file_round_trip_and_copy_move(tmp_path):
    note = tmp_path / "a" / "note.txt"
    assert "Wrote" in machine_tools.write_file(str(note), "one")
    assert "Appended" in machine_tools.write_file(str(note), " two", append=True)
    assert note.read_text() == "one two"
    assert "Copied" in machine_tools.copy_path(str(note), str(tmp_path / "copy.txt"))
    assert "Moved" in machine_tools.move_path(str(tmp_path / "copy.txt"), str(tmp_path / "moved.txt"))
    assert (tmp_path / "moved.txt").read_text() == "one two"
    found = machine_tools.search_files("note", root=str(tmp_path))
    assert "note.txt" in found


def test_protected_credential_files_are_not_touched(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "is_protected_path", lambda path: path.endswith(".env.local"))
    secret = tmp_path / ".env.local"
    secret.write_text("KEY=1")
    assert machine_tools.write_file(str(secret), "overwrite").startswith("Blocked")
    assert machine_tools.delete_path(str(secret), permanent=True).startswith("Blocked")
    assert secret.read_text() == "KEY=1"


def test_permanent_delete_and_refusing_the_home_folder(tmp_path):
    doomed = tmp_path / "old.txt"
    doomed.write_text("x")
    assert "Permanently deleted" in machine_tools.delete_path(str(doomed), permanent=True)
    assert not doomed.exists()
    from pathlib import Path

    assert machine_tools.delete_path(str(Path.home()), permanent=True).startswith("Refused")


def test_media_key_names_are_validated(monkeypatch):
    pressed = []
    monkeypatch.setattr(machine_tools, "_key_tap", pressed.append)
    if sys.platform == "win32":
        assert machine_tools.media_key("pause") == "Pressed play pause."
        assert pressed == [0xB3]
    assert machine_tools.media_key("explode").startswith("Error")


def test_kill_process_never_ends_nyx_itself(monkeypatch):
    import os

    import psutil

    class Fake:
        def __init__(self, pid, name):
            self.pid, self._name, self.info = pid, name, {"name": name}
            self.terminated = False

        def name(self):
            return self._name

        def terminate(self):
            self.terminated = True

    mine = Fake(os.getpid(), "python.exe")
    other = Fake(424242, "python.exe")
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [mine, other])
    result = machine_tools.kill_process("python")
    assert other.terminated and not mine.terminated
    assert "424242" in result


def test_power_actions_are_validated(monkeypatch):
    calls = []
    monkeypatch.setattr(machine_tools.subprocess, "run", lambda argv, **k: calls.append(argv))
    assert machine_tools.system_power("explode").startswith("Error")
    assert "restart in 60 seconds" in machine_tools.system_power("restart", 60)
    assert calls[-1][:3] == ["shutdown", "/r", "/t"]


def test_blocked_category_is_enforced_by_the_registry(monkeypatch, tmp_path):
    registry = ToolRegistry()
    machine_tools.register_machine_tools(registry)
    monkeypatch.setattr(permissions, "POLICY", permissions.PermissionPolicy(tmp_path / "p.json"))
    permissions.POLICY.update(categories={"shell": "block"})
    result = registry.call_tool("run_command", command="Write-Output hi")
    assert result.startswith("Blocked")
