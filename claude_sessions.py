"""Which Claude Code sessions on this PC are working, which are waiting on the owner, which are done.

From the Jarvis projects the owner pointed at (2026-10-09): a dashboard of every Claude Code session on the machine,
with "needs you" first. Claude Code writes each session as a JSON-lines transcript under
``~/.claude/projects/<project>/<session>.jsonl``; this module reads only the head (for the first request) and the
tail (for the current state) of recent ones. Read-only: it never writes to a transcript, never answers a session,
and nothing it reads is sent to a model — it is shown to the owner on their own PC.

How a state is read from the last real entry (user or assistant; attachments and system notes are skipped):
* assistant asked something (AskUserQuestion / ExitPlanMode)             → ``needs_you``
* assistant started a tool and nothing came back for a while (a prompt)   → ``needs_you`` ("may be waiting to approve")
* a tool or a request is in flight and the file moved in the last minutes → ``working``
* assistant finished its turn with text                                   → ``your_turn`` (recent) or ``idle``
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

HEAD_BYTES = 64 * 1024
TAIL_BYTES = 256 * 1024
RECENT_DAYS = 7
MAX_SESSIONS = 40
WORKING_SECONDS = 180          # a request or tool answered this recently is still being worked on
STUCK_TOOL_SECONDS = 45        # a tool call with no result for this long is probably waiting for approval
YOUR_TURN_HOURS = 12
ASKING_TOOLS = {"AskUserQuestion", "ExitPlanMode"}
_TAG = re.compile(r"<[^>]+>.*?</[^>]+>|<[^>]+>", re.S)


def root() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "projects"


def _lines(path: Path, *, head: bool) -> List[Dict[str, Any]]:
    try:
        with path.open("rb") as handle:
            if head:
                raw = handle.read(HEAD_BYTES)
            else:
                size = path.stat().st_size
                handle.seek(max(0, size - TAIL_BYTES))
                raw = handle.read()
    except OSError:
        return []
    out = []
    chunks = raw.split(b"\n")
    if not head and len(chunks) > 1:
        chunks = chunks[1:]                       # the first tail line is usually cut in half
    for chunk in chunks:
        try:
            item = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _when(item: Dict[str, Any]) -> float:
    try:
        return datetime.fromisoformat(str(item.get("timestamp", "")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(part.get("text") or "") for part in content if isinstance(part, dict) and part.get("type") == "text")
    return ""


def _clean(text: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", _TAG.sub(" ", text or "")).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _tool_uses(content: Any) -> List[str]:
    if not isinstance(content, list):
        return []
    return [str(part.get("name") or "") for part in content if isinstance(part, dict) and part.get("type") == "tool_use"]


def read_state(entries: List[Dict[str, Any]], now: float, file_age: float) -> Dict[str, Any]:
    """The session's state from its last real entries. Pure, so it is tested without files."""
    real = [e for e in entries if e.get("type") in ("user", "assistant") and isinstance(e.get("message"), dict)]
    if not real:
        return {"state": "idle", "why": "Nothing to read yet."}
    last = real[-1]
    content = last["message"].get("content")
    age = max(0.0, now - (_when(last) or now - file_age))
    if last["type"] == "assistant":
        tools = _tool_uses(content)
        if any(t in ASKING_TOOLS for t in tools):
            return {"state": "needs_you", "why": "Asked you a question."}
        if tools:
            if age > STUCK_TOOL_SECONDS and file_age > STUCK_TOOL_SECONDS:
                return {"state": "needs_you", "why": f"May be waiting for you to approve {tools[-1]}."}
            return {"state": "working", "why": f"Running {tools[-1]}."}
        said = _clean(_text_of(content), 160)
        if age < YOUR_TURN_HOURS * 3600:
            return {"state": "your_turn", "why": said or "Finished its turn."}
        return {"state": "idle", "why": said or "Finished."}
    if age < WORKING_SECONDS or file_age < WORKING_SECONDS:
        return {"state": "working", "why": "Thinking."}
    return {"state": "idle", "why": "Stopped without an answer (closed or interrupted)."}


def _title(head: List[Dict[str, Any]], tail: List[Dict[str, Any]]) -> str:
    for entry in reversed(tail):
        if entry.get("type") in ("custom-title", "summary") and (entry.get("customTitle") or entry.get("summary")):
            return _clean(str(entry.get("customTitle") or entry.get("summary")), 90)
    for entry in head:
        if entry.get("type") == "user" and isinstance(entry.get("message"), dict):
            text = _clean(_text_of(entry["message"].get("content")), 90)
            if text:
                return text
    return "Untitled session"


_CACHE: Dict[str, Any] = {"at": 0.0, "rows": None}
CACHE_SECONDS = 3.0


def sessions(now: Optional[float] = None, base: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Recent sessions, those that need the owner first, then working, then by last activity.

    The Jarvis page asks twice per poll (sessions, and "needs you"), so a live read is reused for a few seconds."""
    if now is None and base is None:
        if _CACHE["rows"] is not None and time.time() - _CACHE["at"] < CACHE_SECONDS:
            return list(_CACHE["rows"])
        rows = _read(time.time(), root())
        _CACHE.update(at=time.time(), rows=rows)
        return list(rows)
    return _read(now or time.time(), base or root())


def _read(now: float, folder: Path) -> List[Dict[str, Any]]:
    if not folder.is_dir():
        return []
    files = []
    for path in folder.glob("*/*.jsonl"):
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if now - modified <= RECENT_DAYS * 86400:
            files.append((modified, path))
    rows = []
    for modified, path in sorted(files, reverse=True)[:MAX_SESSIONS]:
        tail = _lines(path, head=False)
        head = _lines(path, head=True)
        state = read_state(tail, now, now - modified)
        cwd = next((str(e.get("cwd")) for e in reversed(tail) if e.get("cwd")), "")
        rows.append({"id": path.stem, "project": Path(cwd).name if cwd else path.parent.name, "cwd": cwd,
                     "title": _title(head, tail), "last": modified, **state})
    order = {"needs_you": 0, "working": 1, "your_turn": 2, "idle": 3}
    return sorted(rows, key=lambda r: (order.get(r["state"], 9), -r["last"]))
