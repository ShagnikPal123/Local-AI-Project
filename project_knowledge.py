"""A project's knowledge base: notes and text files the owner adds to a project, searched for the passages that matter
to each thread's task and put in that thread's brief.

Owner's ask (Drive doc 1, item 1.28): projects like Claude's, with a knowledge base the work draws on (RAG). Kept
small and local on purpose: no embedding model and no vector store. Each document is cut into passages and scored with
BM25 over the project's own passages, which finds the right part of a spec or a set of notes well enough and runs
anywhere the app does. What is added here is only ever read as text, never run (AGENTS.md invariant 2).

Used by commander.py (thread briefs) and routes_commander.py (the project's Setup view).
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from typing import Any, Dict, List

from paths import atomic_replace, data_path

MAX_DOCS = 200          # per project
MAX_CHARS = 60_000      # per document; longer text is cut, and the owner is told
PASSAGE = 900           # characters per passage, packed from whole paragraphs where they fit
TOP = 3                 # passages per brief
BRIEF_CHARS = 1800      # the most a brief carries, so a thread's context stays for its work

_LOCK = threading.RLock()


class KnowledgeError(ValueError):
    """Something the owner can fix (an empty note, a full knowledge base)."""


def _path():
    return data_path("project_knowledge.json")


def _load() -> Dict[str, List[Dict[str, Any]]]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if isinstance(v, list)}
    except (OSError, ValueError):
        pass
    return {}


def _save(state: Dict[str, List[Dict[str, Any]]]) -> None:
    target = _path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    atomic_replace(tmp, target)


def _row(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": doc["id"], "title": doc["title"], "chars": len(doc["text"]), "created": doc["created"],
            "cut": doc.get("cut", False)}


def add(project_id: str, title: str, text: str) -> Dict[str, Any]:
    """Add a note or a text file's contents to a project's knowledge."""
    title = " ".join(str(title or "").split())[:120]
    text = str(text or "").replace("\r\n", "\n").strip()
    if not project_id:
        raise KnowledgeError("Pick a project first.")
    if not text:
        raise KnowledgeError("There is nothing in it to add.")
    doc = {"id": f"kn-{uuid.uuid4().hex[:8]}", "title": title or text.splitlines()[0][:60], "text": text[:MAX_CHARS],
           "created": time.time(), "cut": len(text) > MAX_CHARS}
    with _LOCK:
        state = _load()
        docs = state.setdefault(project_id, [])
        if len(docs) >= MAX_DOCS:
            raise KnowledgeError(f"This project already holds {MAX_DOCS} documents. Remove one to add another.")
        docs.append(doc)
        _save(state)
    return _row(doc)


def list_docs(project_id: str) -> List[Dict[str, Any]]:
    with _LOCK:
        return [_row(d) for d in sorted(_load().get(project_id, []), key=lambda d: -d["created"])]


def delete(project_id: str, doc_id: str) -> bool:
    with _LOCK:
        state = _load()
        docs = state.get(project_id, [])
        kept = [d for d in docs if d["id"] != doc_id]
        if len(kept) == len(docs):
            return False
        state[project_id] = kept
        _save(state)
        return True


def _passages(text: str) -> List[str]:
    """Whole paragraphs packed up to PASSAGE characters; a paragraph longer than that is cut at sentence ends."""
    out: List[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text):
        para = " ".join(para.split())
        pieces = [para] if len(para) <= PASSAGE else re.findall(r".{1,%d}(?:[.!?](?=\s)|$)|.{1,%d}" % (PASSAGE, PASSAGE), para)
        for piece in pieces:
            piece = piece.strip()
            if not piece:
                continue
            if current and len(current) + len(piece) + 1 > PASSAGE:
                out.append(current)
                current = ""
            current = f"{current} {piece}".strip()
    if current:
        out.append(current)
    return out


def search(project_id: str, query: str, k: int = TOP) -> List[Dict[str, Any]]:
    """The project's passages that best match ``query`` (BM25), best first. Empty when nothing shares a word."""
    from commander_pick import words

    asked = set(words(query))
    with _LOCK:
        docs = list(_load().get(project_id, []))
    if not asked or not docs:
        return []
    passages = [(d, p, words(p)) for d in docs for p in _passages(d["title"] + "\n\n" + d["text"])]
    n = len(passages)
    average = sum(len(w) for _, _, w in passages) / n or 1.0
    seen: Dict[str, int] = {}
    for _, _, w in passages:
        for term in set(w) & asked:
            seen[term] = seen.get(term, 0) + 1
    scored = []
    for doc, text, w in passages:
        score = 0.0
        for term in asked:
            tf = w.count(term)
            if not tf:
                continue
            idf = math.log(1 + (n - seen[term] + 0.5) / (seen[term] + 0.5))
            score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * len(w) / average))
        if score > 0:
            scored.append({"doc_id": doc["id"], "title": doc["title"], "text": text, "score": round(score, 3)})
    scored.sort(key=lambda row: -row["score"])
    return scored[:k]


def brief(project_id: str, query: str) -> str:
    """The passages for a thread's brief, or "" when the project has no knowledge that fits the task."""
    try:
        found = search(project_id, query)
    except Exception:
        return ""
    if not found:
        return ""
    lines, used = [], 0
    for row in found:
        text = row["text"][: max(0, BRIEF_CHARS - used)]
        if not text:
            break
        lines.append(f"- From “{row['title']}”: {text}")
        used += len(text)
    return "From the project's knowledge (use what helps, it may be partial):\n" + "\n".join(lines)
