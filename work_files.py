"""Which files a chat's work touched: the file tree under the work queue (doc 2 item 2.3, the combined mod's tree).

Every tool call with a path argument is noted per chat: the path, whether it was read, written or deleted, and when.
Kept in memory only (the last 200 per chat, 40 chats), because it answers "what has it been touching just now",
not history; the chat transcript is the record.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Dict, List

PATH_ARGS = ("path", "file_path", "source", "destination", "dest", "target", "folder")
_PER_CHAT = 200
_CHATS = 40
_lock = threading.Lock()
_seen: "OrderedDict[str, OrderedDict[str, Dict[str, Any]]]" = OrderedDict()


def _kind(category: str) -> str:
    if category == "files.delete":
        return "deleted"
    if category == "files.write":
        return "written"
    return "read"


def note(chat_id: str, name: str, category: str, args: Dict[str, Any]) -> None:
    """After a tool ran: remember the paths it named. Never raises."""
    try:
        paths = [str(args.get(key)).strip() for key in PATH_ARGS if isinstance(args.get(key), str) and args.get(key).strip()]
        if not paths:
            return
        kind = _kind(category or "")
        with _lock:
            chat = _seen.setdefault(chat_id or "default", OrderedDict())
            _seen.move_to_end(chat_id or "default")
            for path in paths[:4]:
                entry = chat.pop(path, {"path": path, "reads": 0, "writes": 0})
                # Written beats read: once a file was changed, that is what the tree shows.
                entry["kind"] = kind if kind != "read" or entry.get("kind") in (None, "read") else entry["kind"]
                entry["reads" if kind == "read" else "writes"] += 1
                entry["tool"], entry["at"] = name, time.time()
                chat[path] = entry
            while len(chat) > _PER_CHAT:
                chat.popitem(last=False)
            while len(_seen) > _CHATS:
                _seen.popitem(last=False)
    except Exception:  # noqa: BLE001 - bookkeeping never costs a tool result
        pass


def files(chat_id: str) -> List[Dict[str, Any]]:
    """Newest first."""
    with _lock:
        chat = _seen.get(chat_id or "default") or {}
        return [dict(entry) for entry in reversed(list(chat.values()))]


def clear(chat_id: str = "") -> None:
    with _lock:
        if chat_id:
            _seen.pop(chat_id, None)
        else:
            _seen.clear()
