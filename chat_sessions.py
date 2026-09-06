"Persistent multi-chat session storage with bounded cross-chat context."""

from __future__ import annotations
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
from typing import Any
from paths import atomic_replace, data_path
class ChatSessionStore:
    MAX_CHATS = 5
    def __init__(self, path: str | Path | None = None, memory_store: Any | None = None) -> None:
        self.path = Path(path) if path is not None else data_path("chats.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()
        self.memory_store = memory_store

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("chats"), dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return {"active_chat": None, "chats": {}}

    def _save(self) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        atomic_replace(temp, self.path)

    def create(self, title: str | None = None) -> str:
        if len(self.data["chats"]) >= self.MAX_CHATS:
            raise RuntimeError("Chat limit reached. Delete a chat before creating another.")
        chat_id = uuid.uuid4().hex[:8]
        now = datetime.now(timezone.utc).isoformat()
        self.data["chats"][chat_id] = {"title": title or f"Chat {chat_id}", "created_at": now, "updated_at": now, "messages": []}
        self.data["active_chat"] = chat_id
        self._save()
        return chat_id
    def fork(self, source_id: str | None = None, title: str | None = None,
             carry: int = 12) -> dict[str, Any]:
        """Branch a new chat from an existing one, keeping the link between them.

        Opening a blank chat loses the thread you were pulling on; continuing in
        the same one buries it. A fork does neither: the new chat starts with a
        summary of where it came from, and both ends record the relationship, so
        work can be split across chats and still be reasoned about as one piece.

        Only the tail is carried. Copying the whole history would double the
        token cost of every later turn for context the branch usually does not
        need, and the parent is still reachable through `parent_id`.
        """
        source = source_id or self.data.get("active_chat")
        parent = self.data["chats"].get(source)
        if parent is None:
            raise RuntimeError("No such chat to fork from.")

        parent_title = parent.get("title", source)
        chat_id = self.create(title or f"{parent_title} — branch")

        child = self.data["chats"][chat_id]
        child["parent_id"] = source
        child["parent_title"] = parent_title

        tail = [m for m in parent.get("messages", []) if m.get("role") in ("user", "assistant")][-carry:]
        if tail:
            transcript = "\n".join(
                f"{m['role']}: {str(m.get('content', ''))[:600]}" for m in tail
            )
            child["messages"].append({
                "role": "system",
                "content": (
                    f"[Branched from “{parent_title}”]\n"
                    "You are continuing that conversation in a separate thread. Recent context:\n"
                    f"{transcript}"
                ),
            })

        # Record the branch on the parent too, so the relationship is visible
        # from either side rather than only from the child.
        parent.setdefault("children", []).append(chat_id)
        self._save()
        return {"id": chat_id, **child}

    def ensure_active(self) -> str:
        active = self.data.get("active_chat")
        if active in self.data["chats"]:
            return active
        return self.create()

    def list(self) -> list[dict[str, Any]]:
        return [{"id": chat_id, **chat} for chat_id, chat in self.data["chats"].items()]

    def delete(self, chat_id: str, retain_memory: bool = True) -> bool:
        if chat_id not in self.data["chats"]:
            return False
        chat = self.data["chats"].pop(chat_id)
        if retain_memory and self.memory_store:
            for item in chat.get("learned", []):
                self.memory_store.remember_important(item["topic"], item["content"], source=f"chat:{chat_id}")
        if self.data.get("active_chat") == chat_id:
            self.data["active_chat"] = next(iter(self.data["chats"]), None)
        self._save()
        return True
    def add_learned(self, topic: str, content: str) -> None:
        chat = self.data["chats"][self.ensure_active()]
        chat.setdefault("learned", []).append({"topic": topic, "content": content})
        self._save()

    def switch(self, chat_id: str) -> dict[str, Any]:
        if chat_id not in self.data["chats"]:
            raise KeyError(f"Chat not found: {chat_id}")
        self.data["active_chat"] = chat_id
        self._save()
        return self.data["chats"][chat_id]

    def append(self, role: str, content: str) -> None:
        chat_id = self.ensure_active()
        chat = self.data["chats"][chat_id]
        chat["messages"].append({"role": role, "content": content})
        chat["updated_at"] = datetime.now(timezone.utc).isoformat()
        if role == "assistant" and self.memory_store and len(chat["messages"]) % 6 == 0:
            recent = chat["messages"][-6:]
            summary = " | ".join(f"{item['role']}: {item['content'][:250]}" for item in recent)
            self.memory_store.remember_conversation(chat_id, summary, "Continue from the latest saved exchange.")
        self._save()

    def active_messages(self) -> list[dict[str, str]]:
        return list(self.data["chats"][self.ensure_active()]["messages"])

    def cross_chat_context(self, limit: int = 5) -> str:
        active = self.data.get("active_chat")
        snippets = []
        for chat_id, chat in self.data["chats"].items():
            if chat_id == active:
                continue
            messages = [item for item in chat.get("messages", []) if item.get("role") == "user"][-limit:]
            if messages:
                snippets.append(f"{chat.get('title', chat_id)}: " + " | ".join(item["content"][:300] for item in messages))
        return "Active context from other chats:\n" + "\n".join(snippets) if snippets else ""
