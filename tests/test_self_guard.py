"""Nyx's own tools must not close Nyx (owner, 2026-09-24)."""

import os

import pytest

import self_guard

NYX_TAB = {"hwnd": 1, "title": "Nyx Ichos - Google Chrome", "process": "chrome.exe", "pid": 999999, "focused": True}
OTHER_TAB = {"hwnd": 2, "title": "YouTube - Google Chrome", "process": "chrome.exe", "pid": 999999, "focused": False}


@pytest.fixture(autouse=True)
def _chrome_hosts_nyx(monkeypatch):
    monkeypatch.setattr(self_guard, "hosting_process_names", lambda windows=None: {"chrome"})


def test_window_close_refused_for_nyx_only():
    assert self_guard.check_window_action(NYX_TAB, "close")
    assert self_guard.check_window_action(NYX_TAB, "minimize")
    assert not self_guard.check_window_action(NYX_TAB, "maximize")
    assert not self_guard.check_window_action(OTHER_TAB, "close")


def test_close_keys_refused_when_nyx_in_front():
    assert self_guard.check_keys("alt+f4", NYX_TAB)
    assert self_guard.check_keys("Ctrl + W", NYX_TAB)
    assert not self_guard.check_keys("alt+f4", OTHER_TAB)
    assert not self_guard.check_keys("ctrl+s", NYX_TAB)


def test_kill_refuses_self_runtime_and_host_browser():
    assert self_guard.check_kill(os.getpid(), "python.exe")
    assert self_guard.check_kill(4, "ollama.exe", hosts=set(), pids=set())
    assert self_guard.check_kill(4, "chrome.exe", hosts={"chrome"}, pids=set())
    assert not self_guard.check_kill(4, "notepad.exe", hosts={"chrome"}, pids=set())


@pytest.mark.parametrize("command", [
    "taskkill /f /im pythonw.exe",
    "Get-Process python* | Stop-Process -Force",
    "Stop-Process -Name chrome",
    "taskkill /im ollama.exe",
    f"taskkill /pid {os.getpid()} /f",
    "shutdown /r /t 0",
])
def test_commands_that_end_nyx_are_refused(command):
    assert self_guard.check_command(command)


@pytest.mark.parametrize("command", [
    "Get-Process | Sort-Object CPU",
    "taskkill /im notepad.exe",
    "python -c \"print(1)\"",
    "Stop-Process -Name spotify",
])
def test_ordinary_commands_pass(command):
    assert self_guard.check_command(command) == ""


def test_match_window_prefers_other_windows(monkeypatch):
    import computer_control

    monkeypatch.setattr(computer_control, "list_windows", lambda: [NYX_TAB, OTHER_TAB])
    assert computer_control._match_window("chrome")["hwnd"] == 2
    assert computer_control._match_window("nyx ichos")["hwnd"] == 1
