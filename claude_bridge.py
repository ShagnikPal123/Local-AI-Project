"""Ichos talks to Claude Code directly (owner, 2026-10-10: "app and code level talking … if I say tell claude to do
smt the AI can talk to you easily rather than open").

Instead of opening Claude Code and typing, Ichos runs it headless — ``claude -p <task> --output-format json`` in the
project folder — and reads the answer back into the chat. A follow-up ("tell Claude to also…") resumes the same
Claude session (``--resume``), so it is one conversation, not a string of strangers.

Safety: this is an *acting* tool (category ``code``): the owner's tool permissions and the taint gate apply, so after
a web or email read it asks first. Claude Code keeps its own permission system on top — the default mode here is
``acceptEdits`` (it may edit files in that folder; anything else it would need to ask about is refused in print
mode, and it says so). It uses the owner's own Claude Code sign-in and plan; nothing is sent anywhere else.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional

from paths import atomic_replace, data_path, project_path

MODES = ("plan", "acceptEdits", "default")
TIMEOUT = 900
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_claude() -> Optional[str]:
    """The `claude` command: on PATH, or the copy the Claude desktop app keeps (newest version)."""
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    root = os.path.join(os.environ.get("APPDATA", ""), "Claude", "claude-code")
    found = sorted(glob.glob(os.path.join(root, "*", "*", "claude.exe")), key=os.path.getmtime)
    return found[-1] if found else None


def _sessions_path() -> Path:
    return data_path("claude_bridge.json")


def _sessions() -> Dict[str, Any]:
    try:
        return json.loads(_sessions_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _remember(folder: str, session_id: str, task: str) -> None:
    data = _sessions()
    data[folder] = {"session_id": session_id, "task": task[:200], "at": time.time()}
    path = _sessions_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    atomic_replace(tmp, path)


def ask(task: str, folder: str = "", mode: str = "acceptEdits", continue_last: bool = False,
        runner: Any = None) -> Dict[str, Any]:
    """Send one task to Claude Code and wait for its answer. Returns {ok, text, session_id, folder, cost_usd}."""
    task = (task or "").strip()
    if not task:
        return {"ok": False, "text": "Say what Claude should do."}
    where = Path(folder).expanduser() if folder.strip() else Path(project_path("."))
    if not where.is_dir():
        return {"ok": False, "text": f"No folder at {where}."}
    exe = find_claude()
    if not exe:
        return {"ok": False, "text": "Claude Code is not installed on this PC (no `claude` command and no copy in the "
                                     "Claude desktop app)."}
    command = [exe, "-p", task, "--output-format", "json", "--permission-mode", mode if mode in MODES else "acceptEdits"]
    previous = _sessions().get(str(where.resolve()), {}).get("session_id") if continue_last else None
    if previous:
        command += ["--resume", previous]
    run = runner or subprocess.run
    try:
        result = run(command, cwd=str(where), capture_output=True, text=True, timeout=TIMEOUT, encoding="utf-8",
                     errors="replace", creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return {"ok": False, "text": f"Claude Code did not finish within {TIMEOUT // 60} minutes."}
    except OSError as error:
        return {"ok": False, "text": f"Could not start Claude Code: {error}"}
    out = (result.stdout or "").strip()
    try:
        data = json.loads(out.splitlines()[-1] if out else "{}")
    except ValueError:
        data = {}
    text = str(data.get("result") or out or result.stderr or "").strip()
    session_id = str(data.get("session_id") or "")
    if session_id:
        _remember(str(where.resolve()), session_id, task)
    ok = result.returncode == 0 and not data.get("is_error")
    return {"ok": ok, "text": text[:6000], "session_id": session_id, "folder": str(where),
            "cost_usd": data.get("total_cost_usd")}


def tool_tell_claude(task: str, folder: str = "", mode: str = "acceptEdits", continue_last: bool = False) -> str:
    reply = ask(task, folder, mode, bool(continue_last))
    head = "Claude Code answered" if reply["ok"] else "Claude Code could not finish"
    where = f" in {reply['folder']}" if reply.get("folder") else ""
    return f"{head}{where}:\n{reply['text']}"


def register_claude_bridge_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="tell_claude",
        description="Send a task straight to Claude Code (the coding agent on this PC) and get its answer back — use "
                    "when the owner says 'tell Claude to…', 'ask Claude Code…', or wants code work done in a project. "
                    "Runs headless in the folder (default: the Ichos project). continue_last resumes the last Claude "
                    "session in that folder, for follow-ups. mode: acceptEdits (may edit files, the default), plan "
                    "(read and plan only), default (refuses anything that would need approval).",
        parameters=[ToolParam("task", "string", "What Claude Code should do, in plain words"),
                    ToolParam("folder", "string", "Project folder (default: the Ichos project)", required=False),
                    ToolParam("mode", "string", "acceptEdits, plan or default", required=False,
                              enum_values=list(MODES)),
                    ToolParam("continue_last", "boolean", "Continue the last Claude session in this folder",
                              required=False)],
        handler=tool_tell_claude, category="code", label=lambda a: "Asking Claude Code",
    )
