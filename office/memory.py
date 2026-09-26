"""What an office remembers — *"It fully remembers things from previous sessions."*

Three kinds of remembering, all in one small file per office (``memory.json``):

* **summaries** — what a job was and what came out of it, written when the top manager wraps up;
* **decisions and facts** — the things the office must not re-litigate next week ("the owner wants Tailwind",
  "the API key lives in .env.local");
* **notes** — anything an agent thought was worth keeping, through its ``note`` tool.

Recall is deliberately offline: a keyword-and-recency score over a few hundred short entries beats a model call
that costs seconds and a quota, and it means an office reopened with no network still knows what it was doing.

A **linked folder** ("link work flows") widens recall to its sibling offices: their summaries, decisions and
facts come back marked with the office they came from, so two offices in one folder work as one memory without
ever writing into each other's files.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from office import library

FILE = "memory.json"
MAX_ENTRIES = 600
KINDS = ("summary", "decision", "fact", "note", "lesson", "request")
_WORD = re.compile(r"[a-z0-9][a-z0-9'+-]{1,}")
_STOP = frozenset("""the a an and or of to in for on with is are was were be been it its this that these those
i you we they he she as at by from into about over after before between not no yes do does did can could should
would will just now then than there here what which who whom whose when where why how all any both each few more
most other some such only own same so too very s t don now""".split())
_lock = threading.RLock()


def _path(office_id: str) -> Path:
    return library.office_dir(office_id) / FILE


def load(office_id: str) -> Dict[str, Any]:
    try:
        raw = library._read_json(_path(office_id))
    except Exception:  # noqa: BLE001 - a missing office is an empty memory here; callers report the real error
        raw = {}
    entries = [e for e in raw.get("entries", []) if isinstance(e, dict) and e.get("text")]
    return {"entries": entries, "profile": dict(raw.get("profile") or {})}


def _save(office_id: str, data: Dict[str, Any]) -> None:
    entries = data.get("entries", [])
    if len(entries) > MAX_ENTRIES:
        keep_always = [e for e in entries if e.get("kind") in ("summary", "decision")]
        others = [e for e in entries if e.get("kind") not in ("summary", "decision")]
        others = others[-(MAX_ENTRIES - min(len(keep_always), MAX_ENTRIES // 2)):]
        entries = sorted(keep_always[-(MAX_ENTRIES // 2):] + others, key=lambda e: float(e.get("ts") or 0))
        data["entries"] = entries
    library.write_json(_path(office_id), data)


def add(office_id: str, text: str, *, kind: str = "note", by: str = "", tags: Optional[List[str]] = None,
        job_id: str = "") -> Dict[str, Any]:
    """Keep one thing. Returns the stored entry (empty dict when there was nothing to keep)."""
    body = (text or "").strip()
    if not body:
        return {}
    entry = {"id": uuid.uuid4().hex[:10], "ts": time.time(), "kind": kind if kind in KINDS else "note",
             "text": body[:4000], "by": by or "office", "tags": [str(t)[:30] for t in (tags or [])][:8],
             "job_id": job_id}
    with _lock:
        data = load(office_id)
        data["entries"].append(entry)
        _save(office_id, data)
    return entry


def forget(office_id: str, entry_id: str) -> bool:
    with _lock:
        data = load(office_id)
        before = len(data["entries"])
        data["entries"] = [e for e in data["entries"] if e.get("id") != entry_id]
        if len(data["entries"]) == before:
            return False
        _save(office_id, data)
    return True


def set_profile(office_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    """What this office is *for* — kept apart from the log, because it is true every session."""
    with _lock:
        data = load(office_id)
        data["profile"].update({str(k)[:40]: str(v)[:600] for k, v in (changes or {}).items()})
        _save(office_id, data)
        return dict(data["profile"])


def _words(text: str) -> set:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) > 2}


def _score(entry: Dict[str, Any], wanted: set, now: float) -> float:
    if not wanted:
        return 0.0
    words = _words(str(entry.get("text", "")))
    if not words:
        return 0.0
    overlap = len(words & wanted) / (len(wanted) ** 0.5)
    age_days = max(0.0, (now - float(entry.get("ts") or now)) / 86400)
    recency = 1.0 / (1.0 + age_days / 14)
    weight = {"summary": 1.25, "decision": 1.35, "fact": 1.1, "lesson": 1.1}.get(str(entry.get("kind")), 1.0)
    return round((overlap * 1.6 + recency * 0.5) * weight, 4)


def recall(office_id: str, query: str, *, limit: int = 6, include_linked: bool = True) -> List[Dict[str, Any]]:
    """The entries worth putting in front of an agent for this request, best first."""
    wanted = _words(query)
    now = time.time()
    rows: List[Dict[str, Any]] = []
    for entry in load(office_id)["entries"]:
        score = _score(entry, wanted, now)
        if score > 0:
            rows.append({**entry, "score": score, "from": ""})
    if include_linked:
        for sibling in library.linked_siblings(office_id):
            try:
                raw = library._read_json(Path(sibling.path) / FILE)
            except Exception:  # noqa: BLE001
                continue
            for entry in raw.get("entries", []) if isinstance(raw, dict) else []:
                if not isinstance(entry, dict) or entry.get("kind") not in ("summary", "decision", "fact"):
                    continue
                score = _score(entry, wanted, now) * 0.8   # a sibling's memory is context, not this office's own
                if score > 0:
                    rows.append({**entry, "score": score, "from": sibling.name})
    rows.sort(key=lambda e: -e["score"])
    return rows[:limit]


def recent(office_id: str, kind: str = "summary", limit: int = 3) -> List[Dict[str, Any]]:
    entries = [e for e in load(office_id)["entries"] if e.get("kind") == kind]
    return entries[-limit:]


def brief(office_id: str, request: str = "", *, limit: int = 6) -> str:
    """The memory block that goes into the top manager's prompt. Empty when the office is brand new."""
    data = load(office_id)
    lines: List[str] = []
    profile = data.get("profile") or {}
    if profile:
        lines.append("What this office is for: " + "; ".join(f"{k}: {v}" for k, v in list(profile.items())[:4]))
    for entry in recent(office_id, "summary", 3):
        when = time.strftime("%d %b", time.localtime(float(entry.get("ts") or time.time())))
        lines.append(f"[{when}] {entry['text'][:400]}")
    seen = {e["text"] for e in recent(office_id, "summary", 3)}
    for entry in recall(office_id, request, limit=limit) if request else []:
        if entry["text"] in seen:
            continue
        seen.add(entry["text"])
        where = f" (from {entry['from']})" if entry.get("from") else ""
        lines.append(f"- {entry['kind']}{where}: {entry['text'][:300]}")
    if not lines:
        return ""
    return "What this office remembers:\n" + "\n".join(lines[:12])


def linked_note(office_id: str) -> str:
    """One line naming the offices this one shares memory and work with, for the manager's prompt."""
    siblings = library.linked_siblings(office_id)
    if not siblings:
        return ""
    names = ", ".join(s.name for s in siblings[:6])
    return (f"Work flows are linked in this folder: {names}. You can read their files with "
            f"read_file(\"linked/<office name>/<path>\") and their memory comes back in recall().")
