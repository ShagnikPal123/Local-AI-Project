"""Lightweight local memory store for personal preferences and curated online results."""

from __future__ import annotations

import json
import re
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
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
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

    def remember(self, key: str, value: str) -> None:
        """Store a personal preference or durable fact."""
        self.data.setdefault("preferences", {})
        self.data["preferences"][key] = scrub_sensitive_data(value)
        self._save()

    def remember_important(self, topic: str, content: str, source: str = "user") -> None:
        '''Store a durable, explicitly marked important fact for future context.'''
        topic_clean = scrub_sensitive_data(topic.strip())
        content_clean = scrub_sensitive_data(content.strip())
        entry = {"topic": topic_clean, "content": content_clean, "source": source}
        if not entry["topic"] or not entry["content"]:
            raise ValueError("Important memory requires a topic and content.")
        self.data.setdefault("important", [])
        self.data["important"] = [
            item for item in self.data["important"]
            if item.get("topic") != entry["topic"]
        ]
        self.data["important"].append(entry)
        self._save()

    def get_important(self) -> list[dict[str, str]]:
        'Return durable important memories.'
        return list(self.data.get("important", []))

    def remove_important(self, topic: str) -> bool:
        'Remove one important memory by topic.'
        topic = topic.strip()
        important = self.data.get("important", [])
        remaining = [item for item in important if item.get("topic") != topic]
        removed = len(remaining) != len(important)
        if removed:
            self.data["important"] = remaining
            self._save()
        return removed
    def clear_important(self) -> int:
        'Remove all important memories and return the number removed.'
        count = len(self.data.get("important", []))
        if count:
            self.data["important"] = []
            self._save()
        return count
    def remember_conversation(self, chat_id: str, summary: str, next_step: str = "") -> None:
        '''Persist a resumable checkpoint rather than relying on process memory.'''
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
        checkpoints = self.data.get("conversation_checkpoints", [])
        matches = [item for item in checkpoints if chat_id is None or item.get("chat_id") == chat_id]
        return matches[-1] if matches else None
    def record_online_result(self, provider: str, prompt: str, result: str) -> None:
        """Log a reviewed online result for future training or prompt tuning."""
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
        prefs = self.data.get("preferences", {})
        important = self.data.get("important", [])
        if not prefs and not important:
            return "No personal memory entries yet."

        lines = ["Personal memory:"]
        for item in important:
            lines.append(f"- Important ({item.get('topic', 'general')}): {item.get('content', '')}")
        for key, value in prefs.items():
            lines.append(f"- {key}: {value}")

        if self.data.get("online_results"):
            recent = self.data["online_results"][-3:]
            lines.append("Recent reviewed online examples:")
            for item in recent:
                lines.append(f"- {item['provider']}: {item['prompt']} -> {item['result']}")

        return "\n".join(lines)
