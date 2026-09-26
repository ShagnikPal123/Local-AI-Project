"""No child process may open a console window or take the keyboard (Plan Null N87).

The owner: "make sure that when a cmd opens, try to fix it so it doesnt interrupt
me or just dont have it open at all and instead opens but doesn't affect my
ability to type".

Why a black window appears at all: Nyx runs under ``pythonw.exe``, which has no
console of its own. When a process with no console starts a *console* program
(git, npm, powershell, ollama, nvidia-smi, winget, cmd…), Windows creates a new
console window for it — it pops to the front, takes the keyboard for a moment,
and whatever was being typed goes into it instead. Most call sites here already
pass ``CREATE_NO_WINDOW``; the ones that did not, and every library Nyx imports,
did not. One missed call is enough to interrupt someone mid-sentence.

So the flag becomes the default for the whole process: ``install()`` wraps
``subprocess.Popen`` (every ``run``/``call``/``check_output`` and asyncio's
Windows transport go through it) and ``os.system``. An explicit
``CREATE_NEW_CONSOLE`` or ``DETACHED_PROCESS`` is left alone — that caller
wanted its own console.

This hides the *window*. The process still has its console handle, so piped
output, exit codes and Ctrl-events are unchanged.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Any, Dict, List, Optional

#: Windows process-creation flags (values from processthreadsapi.h; defined here
#: so this module imports on every platform).
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
DETACHED_PROCESS = 0x00000008

#: Flags that mean "this caller asked for its own console" — never overridden.
_OWN_CONSOLE = CREATE_NEW_CONSOLE | DETACHED_PROCESS

#: ``ShowWindow`` command: show the window but do not take the foreground.
SW_SHOWNOACTIVATE = 4

#: Position of ``creationflags`` in ``Popen.__init__`` after ``self`` — a caller
#: passing it positionally (nobody does) is left alone rather than guessed at.
_CREATIONFLAGS_POSITION = 13

_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {"installed": False, "hidden": 0, "recent": []}
_ORIGINAL_POPEN_INIT = None
_ORIGINAL_SYSTEM = None


def quiet_flags(creationflags: int = 0) -> int:
    """``creationflags`` with the no-window bit added, unless a console was asked for."""
    if sys.platform != "win32":
        return creationflags
    if creationflags & _OWN_CONSOLE:
        return creationflags
    return creationflags | CREATE_NO_WINDOW


def popen_kwargs(**kwargs: Any) -> Dict[str, Any]:
    """Keyword arguments for a child process that opens no window.

    For call sites that want to be explicit (and for tests that never call
    ``install()``): ``subprocess.run(argv, **quiet_windows.popen_kwargs())``.
    """
    kwargs["creationflags"] = quiet_flags(int(kwargs.get("creationflags") or 0))
    return kwargs


def _note(args: Any) -> None:
    """Remember what was hidden, so Settings can show the fix is doing something."""
    try:
        if isinstance(args, (list, tuple)):
            text = " ".join(str(a) for a in args[:3])
        else:
            text = str(args)
    except Exception:  # pragma: no cover - a weird argv must not break a spawn
        text = "?"
    with _LOCK:
        _STATE["hidden"] = int(_STATE["hidden"]) + 1
        recent: List[str] = _STATE["recent"]
        recent.append(text[:120])
        del recent[:-20]


def install() -> bool:
    """Make "no console window" the default for this process. Idempotent."""
    global _ORIGINAL_POPEN_INIT, _ORIGINAL_SYSTEM

    if sys.platform != "win32" or _STATE["installed"]:
        return bool(_STATE["installed"])

    original_init = subprocess.Popen.__init__
    _ORIGINAL_POPEN_INIT = original_init

    def __init__(self: Any, *args: Any, **kwargs: Any) -> None:  # noqa: N807 - patching a dunder
        if len(args) <= _CREATIONFLAGS_POSITION:
            flags = int(kwargs.get("creationflags") or 0)
            quiet = quiet_flags(flags)
            if quiet != flags:
                kwargs["creationflags"] = quiet
                _note(args[0] if args else kwargs.get("args"))
        original_init(self, *args, **kwargs)

    __init__.__doc__ = original_init.__doc__
    __init__._nyx_quiet = True  # type: ignore[attr-defined]
    subprocess.Popen.__init__ = __init__  # type: ignore[method-assign]

    # os.system() runs cmd.exe through the C runtime, which this patch cannot
    # reach — and under pythonw.exe that is a visible console window every time.
    original_system = os.system
    _ORIGINAL_SYSTEM = original_system

    def system(command: str) -> int:
        _note(command)
        try:
            return subprocess.call(command, shell=True, creationflags=CREATE_NO_WINDOW)
        except Exception:  # pragma: no cover - fall back to the real thing
            return original_system(command)

    system._nyx_quiet = True  # type: ignore[attr-defined]
    os.system = system  # type: ignore[assignment]

    _STATE["installed"] = True
    return True


def uninstall() -> None:
    """Put the originals back (tests; nothing in the app calls this)."""
    global _ORIGINAL_POPEN_INIT, _ORIGINAL_SYSTEM

    if _ORIGINAL_POPEN_INIT is not None:
        subprocess.Popen.__init__ = _ORIGINAL_POPEN_INIT  # type: ignore[method-assign]
        _ORIGINAL_POPEN_INIT = None
    if _ORIGINAL_SYSTEM is not None:
        os.system = _ORIGINAL_SYSTEM  # type: ignore[assignment]
        _ORIGINAL_SYSTEM = None
    _STATE["installed"] = False


def startfile(path: str, *, focus: bool = True) -> None:
    """Open a file or folder in its usual app; ``focus=False`` does not steal the keyboard.

    Used for things Nyx opens on its own initiative (a log, a report it just
    wrote). When the owner asked for something to open, the window should come
    forward, so ``focus`` stays True by default.
    """
    if sys.platform != "win32":  # pragma: no cover - posix fallback
        subprocess.Popen(["xdg-open", str(path)])
        return
    if focus:
        os.startfile(str(path))  # type: ignore[attr-defined] # noqa: S606
        return
    try:
        os.startfile(str(path), show_cmd=SW_SHOWNOACTIVATE)  # type: ignore[attr-defined,call-arg]
    except TypeError:  # pragma: no cover - show_cmd is Python 3.10+
        os.startfile(str(path))  # type: ignore[attr-defined] # noqa: S606


def status() -> Dict[str, Any]:
    """What the fix has done, for Settings and for the doctor page."""
    with _LOCK:
        return {"installed": bool(_STATE["installed"]), "windows_prevented": int(_STATE["hidden"]),
                "recent": list(_STATE["recent"])[-10:], "platform": sys.platform}


#: Scripts a person runs from a console on purpose (setup, release). A window
#: there is the point, not an interruption.
DEV_SCRIPTS = {"build_release.py", "release_beta.py", "setup_nyx.py", "quiet_windows.py"}

#: Commands that only ever run on macOS or Linux, where none of this applies.
_POSIX_ONLY = ("pbpaste", "pbcopy", "xclip", "xdg-open", "pmset", "osascript", '"ps"', "[\"ps\"", "'ps'")


def check_call_sites(root: Optional[str] = None) -> List[Dict[str, str]]:
    """Nyx's own Windows call sites that do not pass the no-window flag themselves.

    ``install()`` already covers them at runtime; this is the belt-and-braces
    list, and the test that keeps new call sites honest. A call counts as safe
    when the flag (or ``popen_kwargs``) appears within its argument list.
    """
    import re
    from pathlib import Path

    base = Path(root) if root else Path(__file__).resolve().parent
    skip_dirs = {".venv", ".venv.broken", "node_modules", "frontend", "temp_inspect", "_preview", "build",
                 "dist", "__pycache__", "openai_mcp", "openai_mcp - Copy", "_archive", "code_backups", "tests"}
    call = re.compile(r"subprocess\.(Popen|run|call|check_output|check_call)\(|os\.system\(|os\.popen\(")
    findings: List[Dict[str, str]] = []
    for path in sorted(base.rglob("*.py")):
        if any(part in skip_dirs for part in path.parts) or path.name in DEV_SCRIPTS:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:  # pragma: no cover
            continue
        for number, line in enumerate(lines, start=1):
            if not call.search(line) or line.lstrip().startswith("#"):
                continue
            window = "\n".join(lines[number - 1: number + 14])
            if any(word in window for word in ("creationflags", "popen_kwargs", "_NO_WINDOW", "quiet_flags")):
                continue
            if any(tool in window.split(")")[0] for tool in _POSIX_ONLY):
                continue
            findings.append({"file": str(path.relative_to(base)), "line": str(number), "code": line.strip()[:120]})
    return findings
