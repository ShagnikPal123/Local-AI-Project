"""Stop Nyx's own tools from closing Nyx.

Owner, 2026-09-24: "At times the AI seems to close the app or stops working."
The computer-control and machine tools act on the whole PC, and Nyx itself is
part of that PC: its engine is a ``pythonw.exe``, its window is a tab in the
owner's browser, and Big Kahuna answers through Ollama. So a turn that meant
"close Chrome", "kill the python processes", "press alt+f4" or
``taskkill /im pythonw.exe`` shut Nyx down in the middle of its own reply.

Every one of those paths asks this module first. It answers with a reason to
refuse (a plain sentence the model can read back to the owner) or ``""`` when
the action is safe. Nothing here stops the owner — only the assistant's tools.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

PROJECT_DIR = Path(__file__).resolve().parent
TITLE_MARKS = ("nyx ichos", "nyx pulse")
# Processes Nyx needs to answer at all. Ollama serves Big Kahuna's local models.
RUNTIME_NAMES = {"ollama", "ollama app", "ollama_llama_server"}
CLOSE_KEYS = {"alt+f4", "ctrl+w", "ctrl+f4", "ctrl+shift+w", "ctrl+q", "ctrl+shift+q"}

REFUSAL = ("Blocked: that would close Nyx itself ({what}), and this reply would stop mid-way. "
           "If the owner really wants it, they can do it themselves (tray icon → Quit Nyx).")


def _norm(name: str) -> str:
    return (name or "").strip().lower().removesuffix(".exe")


def _psutil() -> Any:
    try:
        import psutil

        return psutil
    except ImportError:  # pragma: no cover - psutil ships with Nyx
        return None


def own_pids() -> Set[int]:
    """This process, its parents up to the launcher, its children, and any other process run from this folder."""
    pids = {os.getpid()}
    psutil = _psutil()
    if psutil is None:
        return pids
    try:
        me = psutil.Process()
        pids.update(child.pid for child in me.children(recursive=True))
        for parent in me.parents():
            if _norm(parent.name()) in ("python", "pythonw", "py", "nyx"):
                pids.add(parent.pid)
    except Exception:
        pass
    root = str(PROJECT_DIR).lower()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if _norm(proc.info["name"] or "") not in ("python", "pythonw", "py", "nyx"):
                continue
            if any(root in str(part).lower() for part in (proc.info["cmdline"] or [])):
                pids.add(proc.info["pid"])
        except Exception:
            continue
    return pids


def is_nyx_window(window: Dict[str, Any], pids: Optional[Set[int]] = None) -> bool:
    title = str(window.get("title") or "").lower()
    if any(mark in title for mark in TITLE_MARKS):
        return True
    pid = window.get("pid")
    return bool(pid) and pid in (pids if pids is not None else own_pids())


def nyx_windows(windows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pids = own_pids()
    return [w for w in windows if is_nyx_window(w, pids)]


def hosting_process_names(windows: Optional[Iterable[Dict[str, Any]]] = None) -> Set[str]:
    """Names of the programs that show Nyx right now (usually one browser)."""
    if windows is None:
        try:
            from computer_control import list_windows

            windows = list_windows()
        except Exception:
            windows = []
    return {_norm(w.get("process") or "") for w in nyx_windows(windows) if w.get("process")}


# --- the checks each tool calls -------------------------------------------------------------


def check_window_action(window: Dict[str, Any], action: str) -> str:
    if (action or "").lower() in ("close", "minimize") and is_nyx_window(window):
        return REFUSAL.format(what=f"{(action or '').lower()} the Nyx window “{str(window.get('title'))[:50]}”")
    return ""


def check_keys(combo: str, foreground: Optional[Dict[str, Any]]) -> str:
    key = re.sub(r"\s+", "", (combo or "").lower())
    if key in CLOSE_KEYS and foreground is not None and is_nyx_window(foreground):
        return REFUSAL.format(what=f"{combo} while the Nyx window is in front")
    return ""


def check_kill(pid: int, name: str, hosts: Optional[Set[str]] = None, pids: Optional[Set[int]] = None) -> str:
    clean = _norm(name)
    if pid in (pids if pids is not None else own_pids()):
        return REFUSAL.format(what=f"ending Nyx's own process {name} ({pid})")
    if clean in RUNTIME_NAMES:
        return REFUSAL.format(what=f"ending {name}, which runs Nyx's local models")
    if clean in (hosts if hosts is not None else hosting_process_names()):
        return REFUSAL.format(what=f"ending {name}, which has Nyx open")
    return ""


_KILL_VERBS = re.compile(r"\b(taskkill|tskill|stop-process|spps|kill|pkill|killall)\b|\.kill\(\)|process\s+.*\bdelete\b"
                         r"|\bshutdown(\.exe)?\s+/[srpl]\b|\bstop-computer\b|\brestart-computer\b|\blogoff\b", re.I)


def check_command(command: str) -> str:
    """A shell command that ends Nyx, its browser, its model server, or the whole session."""
    text = command or ""
    if not _KILL_VERBS.search(text):
        return ""
    lowered = text.lower()
    if re.search(r"\bshutdown(\.exe)?\s+/[srpl]\b|\bstop-computer\b|\brestart-computer\b|\blogoff\b", lowered):
        return ("Blocked: shutting down, restarting or signing out of the PC from a shell command closes Nyx "
                "without warning. Use the system_power tool, which gives a delay the owner can cancel.")
    targets = {"python", "pythonw", "nyx", "uvicorn"} | RUNTIME_NAMES | hosting_process_names()
    for target in sorted(targets):
        if re.search(rf"(?<![\w-]){re.escape(target)}(\.exe|\*|\b)", lowered):
            return REFUSAL.format(what=f"a command that ends {target}")
    for pid in own_pids():
        if re.search(rf"(?<!\d){pid}(?!\d)", lowered):
            return REFUSAL.format(what=f"a command that ends Nyx's process {pid}")
    return ""
