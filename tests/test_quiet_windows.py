"""No child process opens a console window over the owner's typing (Project Null N87).

The bug: Nyx runs under pythonw.exe, so every console program it starts (git,
powershell, ollama, ffmpeg, nvidia-smi…) got a brand-new console window that
took the keyboard for a moment. These tests hold the two halves of the fix in
place: the process-wide default, and no Windows call site that quietly opts out.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

import quiet_windows


@pytest.fixture
def installed():
    quiet_windows.install()
    try:
        yield
    finally:
        quiet_windows.uninstall()


def test_the_flag_is_added_unless_the_caller_asked_for_its_own_console():
    assert quiet_windows.quiet_flags(0) & quiet_windows.CREATE_NO_WINDOW
    assert quiet_windows.popen_kwargs(cwd=".")["creationflags"] & quiet_windows.CREATE_NO_WINDOW
    # A caller that deliberately wants a console (or a detached one) keeps it.
    for wanted in (quiet_windows.CREATE_NEW_CONSOLE, quiet_windows.DETACHED_PROCESS):
        assert quiet_windows.quiet_flags(wanted) == wanted
    # Other flags are kept alongside the new one.
    combined = quiet_windows.quiet_flags(subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0x200)
    assert combined & 0x200


@pytest.mark.skipif(sys.platform != "win32", reason="console windows are a Windows problem")
def test_a_plain_spawn_is_made_windowless_and_still_works(installed):
    before = quiet_windows.status()["windows_prevented"]
    result = subprocess.run([sys.executable, "-c", "print('hello')"], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and "hello" in result.stdout
    after = quiet_windows.status()
    assert after["windows_prevented"] == before + 1, "the spawn did not go through the patch"
    assert after["recent"] and "python" in after["recent"][-1].lower()


@pytest.mark.skipif(sys.platform != "win32", reason="os.system only opens a console window on Windows")
def test_os_system_no_longer_opens_a_console(installed):
    before = quiet_windows.status()["windows_prevented"]
    assert os.system("cd .") == 0
    assert quiet_windows.status()["windows_prevented"] > before
    assert getattr(os.system, "_nyx_quiet", False)


def test_installing_twice_does_not_stack_wrappers(installed):
    first = subprocess.Popen.__init__
    quiet_windows.install()
    assert subprocess.Popen.__init__ is first
    quiet_windows.uninstall()
    assert not getattr(subprocess.Popen.__init__, "_nyx_quiet", False)
    assert not getattr(os.system, "_nyx_quiet", False)


def test_every_windows_call_site_in_nyx_passes_the_flag_itself():
    """Belt and braces: a module imported without ``install()`` must still be quiet."""
    findings = quiet_windows.check_call_sites()
    assert findings == [], "add creationflags=_NO_WINDOW (or quiet_windows.popen_kwargs()) to:\n" + "\n".join(
        f"  {f['file']}:{f['line']}  {f['code']}" for f in findings)


def test_the_engine_and_the_launcher_install_it_before_starting_anything():
    from pathlib import Path

    project = Path(__file__).resolve().parent.parent
    for name in ("server.py", "launcher.py"):
        text = (project / name).read_text(encoding="utf-8")
        assert "quiet_windows.install()" in text, f"{name} must install the no-window default"


def test_the_logon_runner_starts_windowless():
    """The scheduled task's script must not leave a console window at logon."""
    from pathlib import Path

    body = (Path(__file__).resolve().parent.parent / "run-nyx-background.cmd").read_text(encoding="utf-8")
    assert "pythonw.exe" in body and "python.exe\"" not in body.replace("pythonw.exe", "")
