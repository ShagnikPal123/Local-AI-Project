"""Notebooks and notes for the Notes tab (Request G13).

The owner: "a notes tab with a lot of variety such as voice, record lecture and
convert to text (this doesn't save the sound and just converts), draw and convert
to notes, the AI analyzes the drawing, makes notes more detailed, can generate
practice quizzes and questions, helps answer questions step by step… useful to
college students and lectures."

What is stored: text (Markdown), and the study material made from it — quizzes,
flashcard decks, step-by-step solutions — as validated data the UI renders
(invariant 2). A drawing is kept as an image upload so it can be read again.
Lecture audio is never written anywhere: the browser turns speech into text and
only the text arrives here.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from paths import atomic_replace, data_path

_LOCK = threading.Lock()
#: "slides" is a deck read into a note (Project Null N89): the body is the deck as
#: Markdown, and the slides themselves live beside it (slide_reader.save_deck).
KINDS = ("note", "lecture", "drawing", "slides")
MAX_BODY = 400_000


class NotesError(ValueError):
    """A request the store refuses, with a sentence the UI can show."""


def _path():
    return data_path("notes/notes.json")


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("notes"), list):
            data.setdefault("notebooks", [])
            return data
    except (OSError, ValueError):
        pass
    return {"notebooks": [{"id": "inbox", "title": "Notes", "created_at": time.time()}], "notes": []}


def _write(data: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    atomic_replace(temp, path)


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


def _summary(note: Dict[str, Any]) -> Dict[str, Any]:
    body = note.get("body", "")
    return {k: note.get(k) for k in ("id", "notebook_id", "title", "kind", "created_at", "updated_at", "pinned")} | {
        "preview": " ".join(body.split())[:160], "words": len(body.split()),
        "study": {"quizzes": len(note.get("quizzes", [])), "decks": len(note.get("decks", [])),
                  "steps": len(note.get("steps", []))},
    }


def library() -> Dict[str, Any]:
    with _LOCK:
        data = _read()
    notes = sorted(data["notes"], key=lambda n: (not n.get("pinned"), -float(n.get("updated_at", 0))))
    return {"notebooks": data["notebooks"], "notes": [_summary(n) for n in notes]}


def get(note_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        data = _read()
    return next((dict(n) for n in data["notes"] if n["id"] == note_id), None)


def add_notebook(title: str) -> Dict[str, Any]:
    title = (title or "").strip()[:80]
    if not title:
        raise NotesError("Give the notebook a name, like “Biology 101”.")
    notebook = {"id": _new_id(), "title": title, "created_at": time.time()}
    with _LOCK:
        data = _read()
        data["notebooks"].append(notebook)
        _write(data)
    return notebook


def rename_notebook(notebook_id: str, title: str) -> Dict[str, Any]:
    title = (title or "").strip()[:80]
    with _LOCK:
        data = _read()
        notebook = next((b for b in data["notebooks"] if b["id"] == notebook_id), None)
        if notebook is None or not title:
            raise NotesError("No such notebook, or the name was empty.")
        notebook["title"] = title
        _write(data)
    return notebook


def delete_notebook(notebook_id: str) -> None:
    """Remove a notebook; its notes move to the first remaining notebook rather than disappearing."""
    with _LOCK:
        data = _read()
        if len(data["notebooks"]) <= 1:
            raise NotesError("Keep at least one notebook.")
        data["notebooks"] = [b for b in data["notebooks"] if b["id"] != notebook_id]
        home = data["notebooks"][0]["id"]
        for note in data["notes"]:
            if note.get("notebook_id") == notebook_id:
                note["notebook_id"] = home
        _write(data)


def create(title: str = "", body: str = "", notebook_id: str = "", kind: str = "note") -> Dict[str, Any]:
    if kind not in KINDS:
        raise NotesError(f"A note is one of: {', '.join(KINDS)}.")
    now = time.time()
    with _LOCK:
        data = _read()
        book = notebook_id if any(b["id"] == notebook_id for b in data["notebooks"]) else data["notebooks"][0]["id"]
        note = {"id": _new_id(), "notebook_id": book, "title": (title or "").strip()[:120] or _default_title(kind, now),
                "body": (body or "")[:MAX_BODY], "kind": kind, "created_at": now, "updated_at": now, "pinned": False,
                "quizzes": [], "decks": [], "steps": [], "drawings": []}
        data["notes"].append(note)
        _write(data)
    return note


def _default_title(kind: str, now: float) -> str:
    stamp = time.strftime("%b %d, %I:%M %p", time.localtime(now))
    return {"lecture": f"Lecture — {stamp}", "drawing": f"Sketch — {stamp}",
            "slides": f"Slides — {stamp}"}.get(kind, f"Note — {stamp}")


def update(note_id: str, **changes: Any) -> Dict[str, Any]:
    with _LOCK:
        data = _read()
        note = next((n for n in data["notes"] if n["id"] == note_id), None)
        if note is None:
            raise KeyError(note_id)
        if "title" in changes and changes["title"] is not None:
            note["title"] = str(changes["title"]).strip()[:120] or note["title"]
        if "body" in changes and changes["body"] is not None:
            note["body"] = str(changes["body"])[:MAX_BODY]
        if "append" in changes and changes["append"]:
            joiner = "\n\n" if note["body"].strip() else ""
            note["body"] = (note["body"].rstrip() + joiner + str(changes["append"]))[:MAX_BODY]
        if "notebook_id" in changes and any(b["id"] == changes["notebook_id"] for b in data["notebooks"]):
            note["notebook_id"] = changes["notebook_id"]
        if "pinned" in changes and changes["pinned"] is not None:
            note["pinned"] = bool(changes["pinned"])
        note["updated_at"] = time.time()
        _write(data)
        return dict(note)


def delete(note_id: str) -> bool:
    with _LOCK:
        data = _read()
        before = len(data["notes"])
        data["notes"] = [n for n in data["notes"] if n["id"] != note_id]
        _write(data)
        return len(data["notes"]) < before


def attach(note_id: str, collection: str, item: Dict[str, Any]) -> Dict[str, Any]:
    """Keep a quiz, flashcard deck, step-by-step solution or drawing with its note."""
    if collection not in ("quizzes", "decks", "steps", "drawings"):
        raise NotesError("Unknown study material.")
    item = {"id": _new_id(), "created_at": time.time(), **item}
    with _LOCK:
        data = _read()
        note = next((n for n in data["notes"] if n["id"] == note_id), None)
        if note is None:
            raise KeyError(note_id)
        note.setdefault(collection, []).insert(0, item)
        note[collection] = note[collection][:30]
        note["updated_at"] = time.time()
        _write(data)
    return item


def update_item(note_id: str, collection: str, item_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    with _LOCK:
        data = _read()
        note = next((n for n in data["notes"] if n["id"] == note_id), None)
        item = next((i for i in (note or {}).get(collection, []) if i["id"] == item_id), None)
        if item is None:
            raise KeyError(item_id)
        if collection == "decks" and isinstance(changes.get("cards"), list):
            by_id = {c.get("id"): c for c in item.get("cards", [])}
            for change in changes["cards"]:
                card = by_id.get(change.get("id"))
                if card is not None and isinstance(change.get("box"), int):
                    card["box"] = max(1, min(5, change["box"]))
                    card["reviewed_at"] = time.time()
        if collection == "quizzes" and isinstance(changes.get("attempt"), dict):
            item.setdefault("attempts", []).append({**changes["attempt"], "at": time.time()})
            item["attempts"] = item["attempts"][-10:]
        _write(data)
        return dict(item)


def delete_item(note_id: str, collection: str, item_id: str) -> None:
    with _LOCK:
        data = _read()
        note = next((n for n in data["notes"] if n["id"] == note_id), None)
        if note is None:
            raise KeyError(note_id)
        note[collection] = [i for i in note.get(collection, []) if i["id"] != item_id]
        _write(data)


def search(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    words = [w for w in (query or "").lower().split() if len(w) > 1]
    with _LOCK:
        data = _read()
    scored = []
    for note in data["notes"]:
        haystack = f"{note.get('title', '')} {note.get('body', '')}".lower()
        score = sum(haystack.count(w) for w in words) + sum(3 for w in words if w in note.get("title", "").lower())
        if score:
            scored.append((score, note))
    scored.sort(key=lambda pair: -pair[0])
    return [_summary(n) for _, n in scored[:limit]]
