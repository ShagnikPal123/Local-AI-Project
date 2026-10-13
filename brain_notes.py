"""Shared-brain notes: one note format in the Obsidian vault that Claude sessions and both apps all read and write.

Why: the owner asked for Obsidian to be "your brain from now on alongside what you use now". Three different writers
(a Claude Code session, Nyx Ichos, the second app) only share a brain if they agree on where notes go and how they look.
So every note lands under ``Brain/<kind>/``, starts with the same front matter (so Obsidian's Properties and Dataview
can list them) and links to related notes with ``[[wikilinks]]``. Writing goes through the Obsidian connector, which
already handles the REST API, the plain-folder fallback and (see its ``_clean_path``) keeps paths inside the vault.
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional

KINDS = ("handoff", "decision", "skill", "session", "idea")


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:60] or "note"


def build_note(title: str, body: str, kind: str = "session", author: str = "nyx", links: Optional[List[str]] = None,
               tags: Optional[List[str]] = None, today: Optional[str] = None) -> str:
    """The note text: front matter, the body, then a Related section of wikilinks."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    stamp = today or time.strftime("%Y-%m-%d")
    tag_list = ["brain", kind] + [t.lstrip("#") for t in (tags or [])]
    front = ["---", f"title: {title}", f"kind: {kind}", f"author: {author}", f"created: {stamp}",
             f"tags: [{', '.join(tag_list)}]", "---", ""]
    related = [f"- [[{link}]]" for link in (links or [])]
    tail = ["", "## Related", *related] if related else []
    return "\n".join(front + [f"# {title}", "", body.strip(), *tail, ""])


def save_note(connector: Any, title: str, body: str, kind: str = "session", author: str = "nyx",
              links: Optional[List[str]] = None, tags: Optional[List[str]] = None,
              today: Optional[str] = None) -> Dict[str, Any]:
    """Write the note to ``Brain/<kind>/<date>-<slug>.md`` through the Obsidian connector."""
    text = build_note(title, body, kind, author, links, tags, today)
    stamp = today or time.strftime("%Y-%m-%d")
    path = f"Brain/{kind}/{stamp}-{_slug(title)}"
    return connector.execute("write", path=path, content=text)


def recall(connector: Any, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Brain notes matching the query (search is vault-wide; only Brain/ notes are returned)."""
    result = connector.execute("search", query=query)
    hits = [h for h in result.get("results", result.get("matches", [])) if str(h.get("filename", "")).startswith("Brain/")]
    return hits[: max(1, limit)]
