"""Lightweight local memory store for personal preferences and curated online results."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from paths import data_path


def scrub_sensitive_data(text: str) -> str:
    """Scrub sensitive credentials, API keys, tokens, and passwords from stored text."""
    if not isinstance(text, str):
        return text
    scrubbed = text
    # Known key token prefixes (sk-, ghp-, gho-, Slack, AWS, etc.)
    scrubbed = re.sub(
        r"\b(sk-[a-zA-Z0-9_\-]{8,}|ghp_[a-zA-Z0-9]{16,}|gho_[a-zA-Z0-9]{16,}|xox[baprs]-[a-zA-Z0-9\-]+|AKIA[0-9A-Z]{16})\b",
        "[REDACTED_SECRET]",
        scrubbed,
        flags=re.IGNORECASE,
    )
    # API key / token assignments
    scrubbed = re.sub(
        r"(?i)\b(api[_-]?key|apikey|secret[_-]?key|access[_-]?token|auth[_-]?token|bearer)\s*(?:is|=|:)\s*([a-zA-Z0-9_\-\.]{4,})",
        r"\1: [REDACTED_KEY]",
        scrubbed,
    )
    # Password assignments
    scrubbed = re.sub(
        r"(?i)\b(password|passwd|pwd)\s*(?:is|=|:)\s*([^\s,;]+)",
        r"\1 is [REDACTED_PASSWORD]",
        scrubbed,
    )
    return scrubbed


class MemoryStore:
    """Persist user preferences and reviewed training-like outputs locally."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else data_path("memory.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mtime: float | None = None
        self.data = self._load()

    def _disk_mtime(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except OSError:
            return None

    def _fresh(self) -> None:
        """Reload when another store (every chat has one) wrote the file since we last did.

        Without this, the last chat to save wrote its old copy over memories saved from another chat.
        """
        mtime = self._disk_mtime()
        if mtime is not None and mtime != self._mtime:
            self.data = self._load()

    def _load(self) -> dict[str, Any]:
        self._mtime = self._disk_mtime()
        if not self.path.exists():
            return {
                "preferences": {},
                "online_results": [],
            }

        try:
            with self.path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
                if isinstance(loaded, dict):
                    loaded.setdefault("preferences", {})
                    loaded.setdefault("important", [])
                    loaded.setdefault("online_results", [])
                    return loaded
        except (json.JSONDecodeError, OSError):
            pass

        return {
            "preferences": {},
            "important": [],
            "online_results": [],
        }

    def _save(self) -> None:
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, ensure_ascii=False)
        self._mtime = self._disk_mtime()

    def remember(self, key: str, value: str) -> None:
        """Store a personal preference or durable fact."""
        self._fresh()
        self.data.setdefault("preferences", {})
        self.data["preferences"][key] = scrub_sensitive_data(value)
        self._save()

    # --- Lasting memories (like Claude's memory files) ---------------------------------------
    #
    # Every important memory is one entry with an id, when it was added and last changed, and an
    # optional "keep long term" mark with the reason it is worth keeping. Topic stays the human
    # name; saving the same topic again updates that entry (same id, same added date). Each entry is
    # also mirrored to one Markdown file per topic in `memory_notes/` next to memory.json, so the
    # notes can be read or backed up outside the app.

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _new_id() -> str:
        return "mem_" + uuid.uuid4().hex[:10]

    def _important_list(self) -> list[dict[str, Any]]:
        """Return the important list, giving old entries an id and the new fields once."""
        items = self.data.setdefault("important", [])
        for item in items:
            if not item.get("id"):
                item["id"] = self._new_id()
            item.setdefault("added_at", None)  # saved before ids existed: the date is unknown
            item.setdefault("updated_at", item.get("added_at"))
            item.setdefault("keep", False)
            item.setdefault("keep_reason", "")
            item.setdefault("source", "user")
        return items

    def _find_important(self, ref: str) -> dict[str, Any] | None:
        """Find one memory by id, or by topic when no id matches."""
        ref = (ref or "").strip()
        items = self._important_list()
        for item in items:
            if item.get("id") == ref:
                return item
        for item in items:
            if item.get("topic") == ref:
                return item
        return None

    @property
    def notes_dir(self) -> Path:
        return self.path.parent / "memory_notes"

    @staticmethod
    def _slug(topic: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
        return (slug or "note")[:60]

    def _mirror_notes(self) -> None:
        """Write one Markdown file per topic and remove files for deleted topics. Best effort."""
        try:
            folder = self.notes_dir
            items = self._important_list()
            if not items and not folder.exists():
                return
            folder.mkdir(parents=True, exist_ok=True)
            wanted: dict[str, str] = {}
            for item in items:
                name = f"{self._slug(item.get('topic', ''))}.md"
                lines = [
                    "---",
                    f"id: {item['id']}",
                    f"topic: {item.get('topic', '')}",
                    f"added: {item.get('added_at') or 'unknown'}",
                    f"updated: {item.get('updated_at') or 'unknown'}",
                    f"keep_long_term: {'yes' if item.get('keep') else 'no'}",
                ]
                if item.get("keep_reason"):
                    lines.append(f"why_keep: {item['keep_reason']}")
                lines += [f"source: {item.get('source', 'user')}", "---", "", item.get("content", ""), ""]
                # Two topics can share a slug; keep both in the same file rather than losing one.
                wanted[name] = wanted.get(name, "") + "\n".join(lines)
            for name, text in wanted.items():
                (folder / name).write_text(text, encoding="utf-8")
            for old in folder.glob("*.md"):
                if old.name not in wanted:
                    old.unlink()
        except OSError:
            pass

    def _save_important(self) -> None:
        self._save()
        self._mirror_notes()

    def remember_important(
        self,
        topic: str,
        content: str,
        source: str = "user",
        keep: bool | None = None,
        keep_reason: str | None = None,
    ) -> dict[str, Any]:
        '''Store a durable fact. The same topic updates its entry (id and added date stay).'''
        self._fresh()
        topic_clean = scrub_sensitive_data(topic.strip())
        content_clean = scrub_sensitive_data(content.strip())
        if not topic_clean or not content_clean:
            raise ValueError("Important memory requires a topic and content.")
        now = self._now()
        existing = self._find_important(topic_clean)
        if existing is not None and existing.get("topic") == topic_clean:
            existing["content"] = content_clean
            existing["source"] = source
            existing["updated_at"] = now
            if keep is not None:
                existing["keep"] = bool(keep)
            if keep_reason is not None:
                existing["keep_reason"] = scrub_sensitive_data(keep_reason.strip())
            entry = existing
        else:
            entry = {
                "id": self._new_id(),
                "topic": topic_clean,
                "content": content_clean,
                "source": source,
                "added_at": now,
                "updated_at": now,
                "keep": bool(keep),
                "keep_reason": scrub_sensitive_data((keep_reason or "").strip()),
            }
            self._important_list().append(entry)
        self._save_important()
        return dict(entry)

    def update_important(self, ref: str, **changes: Any) -> dict[str, Any] | None:
        '''Edit one memory by id (or topic). Allowed: topic, content, keep, keep_reason.'''
        self._fresh()
        item = self._find_important(ref)
        if item is None:
            return None
        if "topic" in changes and changes["topic"] is not None:
            topic = scrub_sensitive_data(str(changes["topic"]).strip())
            if not topic:
                raise ValueError("A memory needs a topic.")
            clash = self._find_important(topic)
            if clash is not None and clash is not item and clash.get("topic") == topic:
                raise ValueError(f"Another memory already uses the topic '{topic}'.")
            item["topic"] = topic
        if "content" in changes and changes["content"] is not None:
            content = scrub_sensitive_data(str(changes["content"]).strip())
            if not content:
                raise ValueError("A memory needs some content.")
            item["content"] = content
        if "keep" in changes and changes["keep"] is not None:
            item["keep"] = bool(changes["keep"])
        if "keep_reason" in changes and changes["keep_reason"] is not None:
            item["keep_reason"] = scrub_sensitive_data(str(changes["keep_reason"]).strip())
        item["updated_at"] = self._now()
        self._save_important()
        return dict(item)

    def get_important(self) -> list[dict[str, Any]]:
        'Return durable important memories (each with id, dates and the keep mark).'
        self._fresh()
        before = [dict(item) for item in self.data.get("important", [])]
        items = self._important_list()
        if items != before:
            self._save()  # old entries just got their ids; keep them stable from now on
        return [dict(item) for item in items]

    def get_important_by_id(self, ref: str) -> dict[str, Any] | None:
        self._fresh()
        item = self._find_important(ref)
        return dict(item) if item else None

    def remove_important(self, ref: str) -> bool:
        'Remove one important memory by id or topic.'
        self._fresh()
        item = self._find_important(ref)
        if item is None:
            return False
        self.data["important"] = [entry for entry in self._important_list() if entry is not item]
        self._save_important()
        return True

    def clear_important(self, keep_long_term: bool = False) -> int:
        '''Remove important memories and return how many went. keep_long_term spares the marked ones.'''
        self._fresh()
        items = self._important_list()
        remaining = [item for item in items if keep_long_term and item.get("keep")]
        count = len(items) - len(remaining)
        if count:
            self.data["important"] = remaining
            self._save_important()
        return count
    def remember_conversation(self, chat_id: str, summary: str, next_step: str = "") -> None:
        '''Persist a resumable checkpoint rather than relying on process memory.'''
        self._fresh()
        self.data.setdefault("conversation_checkpoints", [])
        self.data["conversation_checkpoints"].append({
            "chat_id": chat_id,
            "summary": scrub_sensitive_data(summary),
            "next_step": scrub_sensitive_data(next_step),
            "saved_at": datetime.now(timezone.utc).isoformat()
        })
        self.data["conversation_checkpoints"] = self.data["conversation_checkpoints"][-20:]
        self._save()
    def latest_checkpoint(self, chat_id: str | None = None) -> dict[str, str] | None:
        self._fresh()
        checkpoints = self.data.get("conversation_checkpoints", [])
        matches = [item for item in checkpoints if chat_id is None or item.get("chat_id") == chat_id]
        return matches[-1] if matches else None
    def record_online_result(self, provider: str, prompt: str, result: str) -> None:
        """Log a reviewed online result for future training or prompt tuning."""
        self._fresh()
        entry = {
            "provider": provider,
            "prompt": scrub_sensitive_data(prompt),
            "result": scrub_sensitive_data(result),
        }
        self.data.setdefault("online_results", [])
        self.data["online_results"].append(entry)
        self._save()

    def build_context_prompt(self) -> str:
        """Create a small local learning prompt that can be injected into chat context."""
        self._fresh()
        prefs = self.data.get("preferences", {})
        important = self.data.get("important", [])
        if not prefs and not important:
            return "No personal memory entries yet."

        lines = ["Personal memory:"]
        # Long-term memories first: they are the ones the owner said to keep.
        for item in sorted(important, key=lambda entry: not entry.get("keep")):
            mark = "Keep" if item.get("keep") else "Important"
            lines.append(f"- {mark} ({item.get('topic', 'general')}): {item.get('content', '')}")
        for key, value in prefs.items():
            lines.append(f"- {key}: {value}")

        if self.data.get("online_results"):
            recent = self.data["online_results"][-3:]
            lines.append("Recent reviewed online examples:")
            for item in recent:
                lines.append(f"- {item['provider']}: {item['prompt']} -> {item['result']}")

        return "\n".join(lines)
