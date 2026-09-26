"Persistent multi-chat session storage with bounded cross-chat context."""

from __future__ import annotations
from datetime import datetime, timezone
import json
import re
import threading
from pathlib import Path
import uuid
from typing import Any
from paths import atomic_replace, data_path


class ChatSessionStore:
    #: Raised from 5 when chats became browser-style tabs: people open a new tab
    #: per task, and a hard stop at five made the sixth tab fail outright. Raised
    #: again from 40 (Plan Null N3): the owner sat at exactly 40 with no delete
    #: button anywhere in the Nyx chat, so "New chat" simply failed.
    MAX_CHATS = 100

    def __init__(self, path: str | Path | None = None, memory_store: Any | None = None) -> None:
        self.path = Path(path) if path is not None else data_path("chats.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One store is shared by every chat the server has open, and turns run on
        # worker threads; unsynchronised appends could interleave a save.
        self._lock = threading.RLock()
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
        with self._lock:
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            atomic_replace(temp, self.path)

    def create(self, title: str | None = None, activate: bool = True) -> str:
        """``activate=False`` makes a chat in the background (the Command Zone's) without moving the owner."""
        with self._lock:
            if len(self.data["chats"]) >= self.MAX_CHATS:
                raise RuntimeError("Chat limit reached. Delete a chat before creating another.")
            chat_id = uuid.uuid4().hex[:8]
            now = datetime.now(timezone.utc).isoformat()
            self.data["chats"][chat_id] = {"title": title or f"Chat {chat_id}", "created_at": now, "updated_at": now, "messages": []}
            if activate or not self.data.get("active_chat"):
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
        with self._lock:
            source = source_id or self.data.get("active_chat")
            parent = self.data["chats"].get(source)
            if parent is None:
                raise RuntimeError("No such chat to fork from.")

            parent_title = parent.get("title", source)
            chat_id = self.create(title or f"{parent_title} — fork")

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
            child["kind"] = "fork"
            parent.setdefault("children", []).append(chat_id)
            self._save()
            return {"id": chat_id, **child}

    def duplicate(self, source_id: str, title: str | None = None) -> dict[str, Any]:
        """An exact, unlinked copy of a chat — every message — as its own feature.

        "New chat" used to look like this by accident (Request G15). On purpose it
        is for trying something without touching the original.
        """
        with self._lock:
            source = self.data["chats"].get(source_id)
            if source is None:
                raise RuntimeError("No such chat to duplicate.")
            name = title or f"{source.get('title', source_id)} (copy)"
            chat_id = self.create(name[:80])
            copy = self.data["chats"][chat_id]
            copy["messages"] = [dict(m) for m in source.get("messages", [])]
            copy["title_locked"] = bool(title) or bool(source.get("title_locked"))
            copy["kind"] = "duplicate"
            self._save()
            return {"id": chat_id, **copy}

    def branch(self, source_id: str, upto: int | None = None, title: str | None = None) -> dict[str, Any]:
        """A linked chat holding the conversation verbatim up to one message.

        Unlike :meth:`fork` (a summary of recent context), a branch keeps the real
        messages so the conversation can go a different way from that point.
        ``upto`` counts user/assistant messages to keep; None keeps them all.
        """
        with self._lock:
            parent = self.data["chats"].get(source_id)
            if parent is None:
                raise RuntimeError("No such chat to branch from.")
            kept: list[dict[str, Any]] = []
            spoken = 0
            for message in parent.get("messages", []):
                if message.get("role") in ("user", "assistant"):
                    if upto is not None and spoken >= max(0, upto):
                        break
                    spoken += 1
                kept.append(dict(message))
            parent_title = parent.get("title", source_id)
            chat_id = self.create((title or f"{parent_title} — branch")[:80])
            child = self.data["chats"][chat_id]
            child["messages"] = kept
            child["title_locked"] = True
            child["parent_id"] = source_id
            child["parent_title"] = parent_title
            child["kind"] = "branch"
            child["branched_at"] = spoken
            parent.setdefault("children", []).append(chat_id)
            self._save()
            return {"id": chat_id, **child}

    def ensure_active(self) -> str:
        with self._lock:
            active = self.data.get("active_chat")
            if active in self.data["chats"]:
                return active
            return self.create()

    def exists(self, chat_id: str | None) -> bool:
        return bool(chat_id) and chat_id in self.data["chats"]

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"id": chat_id, **chat} for chat_id, chat in self.data["chats"].items()]

    def summaries(self) -> list[dict[str, Any]]:
        """Chats without their message bodies — what a tab strip or history list needs."""
        with self._lock:
            out = []
            for chat_id, chat in self.data["chats"].items():
                messages = chat.get("messages", [])
                last = next((m for m in reversed(messages) if m.get("role") in ("user", "assistant")), None)
                out.append({
                    "id": chat_id,
                    "title": chat.get("title", chat_id),
                    "created_at": chat.get("created_at"),
                    "updated_at": chat.get("updated_at"),
                    "message_count": sum(1 for m in messages if m.get("role") in ("user", "assistant")),
                    "preview": str(last.get("content", ""))[:140] if last else "",
                    "parent_id": chat.get("parent_id"),
                    "kind": chat.get("kind", "chat"),
                    # Owner request (2026-09-15): a chat can belong to one agent.
                    "agent": chat.get("agent", ""),
                })
            out.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
            return out

    def messages(self, chat_id: str) -> list[dict[str, Any]]:
        with self._lock:
            chat = self.data["chats"].get(chat_id)
            return list(chat.get("messages", [])) if chat else []

    def rename(self, chat_id: str, title: str) -> bool:
        with self._lock:
            chat = self.data["chats"].get(chat_id)
            clean = (title or "").strip()[:80]
            if chat is None or not clean:
                return False
            chat["title"] = clean
            chat["title_locked"] = True
            self._save()
            return True

    #: Deleted chats stay restorable this long (the Undo toast and "Recently deleted"),
    #: then go for good. A delete button next to the chat name is one slip away.
    TRASH_DAYS = 30
    TRASH_MAX = 60

    def delete(self, chat_id: str, retain_memory: bool = True) -> bool:
        """Move a chat to Recently deleted. It stops counting toward MAX_CHATS at once."""
        with self._lock:
            if chat_id not in self.data["chats"]:
                return False
            chat = self.data["chats"].pop(chat_id)
            if retain_memory and self.memory_store:
                for item in chat.get("learned", []):
                    self.memory_store.remember_important(item["topic"], item["content"], source=f"chat:{chat_id}")
            chat["deleted_at"] = datetime.now(timezone.utc).isoformat()
            self.data.setdefault("trash", {})[chat_id] = chat
            self._prune_trash()
            if self.data.get("active_chat") == chat_id:
                self.data["active_chat"] = next(iter(self.data["chats"]), None)
            self._save()
            return True

    def restore(self, chat_id: str) -> bool:
        """Bring a deleted chat back exactly as it was. False when it is not in Recently deleted."""
        with self._lock:
            trash = self.data.get("trash") or {}
            if chat_id not in trash:
                return False
            if len(self.data["chats"]) >= self.MAX_CHATS:
                raise RuntimeError("Chat limit reached. Delete a chat before restoring another.")
            chat = trash.pop(chat_id)
            chat.pop("deleted_at", None)
            self.data["chats"][chat_id] = chat
            self._save()
            return True

    def trash(self) -> list[dict[str, Any]]:
        """Recently deleted chats, newest first, without their message bodies."""
        with self._lock:
            items = [
                {"id": chat_id, "title": chat.get("title", chat_id), "deleted_at": chat.get("deleted_at"),
                 "message_count": sum(1 for m in chat.get("messages", []) if m.get("role") in ("user", "assistant"))}
                for chat_id, chat in (self.data.get("trash") or {}).items()
            ]
            items.sort(key=lambda c: c.get("deleted_at") or "", reverse=True)
            return items

    def purge(self, chat_id: str | None = None) -> int:
        """Delete for good: one chat from Recently deleted, or all of them. Returns how many went."""
        with self._lock:
            trash = self.data.get("trash") or {}
            if chat_id is None:
                count = len(trash)
                self.data["trash"] = {}
            else:
                count = 1 if trash.pop(chat_id, None) is not None else 0
            if count:
                self._save()
            return count

    def _prune_trash(self) -> None:
        trash = self.data.get("trash") or {}
        cutoff = datetime.now(timezone.utc).timestamp() - self.TRASH_DAYS * 86400
        keep = []
        for chat_id, chat in trash.items():
            try:
                when = datetime.fromisoformat(str(chat.get("deleted_at"))).timestamp()
            except ValueError:
                when = 0.0
            if when >= cutoff:
                keep.append((when, chat_id))
        keep.sort(reverse=True)
        self.data["trash"] = {chat_id: trash[chat_id] for _, chat_id in keep[: self.TRASH_MAX]}

    def add_learned(self, topic: str, content: str) -> None:
        with self._lock:
            chat = self.data["chats"][self.ensure_active()]
            chat.setdefault("learned", []).append({"topic": topic, "content": content})
            self._save()

    def switch(self, chat_id: str) -> dict[str, Any]:
        with self._lock:
            if chat_id not in self.data["chats"]:
                raise KeyError(f"Chat not found: {chat_id}")
            self.data["active_chat"] = chat_id
            self._save()
            return self.data["chats"][chat_id]

    @staticmethod
    def _title_from(text: str) -> str:
        words = re.sub(r"\s+", " ", re.sub(r"\[[^\]]*\]", "", text or "")).strip().split(" ")
        title = " ".join(words[:7]).strip(" .,:;!?")
        return (title[:48] + "…") if len(title) > 48 else title

    def append(self, role: str, content: str, chat_id: str | None = None, extra: dict | None = None) -> None:
        """Add a message to ``chat_id`` (or the active chat when not given).

        ``extra`` carries display data saved with the message — today the answer's sources
        (Request H15) — so they are still there after a reload.
        """
        with self._lock:
            target = chat_id if chat_id in self.data["chats"] else self.ensure_active()
            chat = self.data["chats"][target]
            message = {"role": role, "content": content}
            if extra:
                message.update({k: v for k, v in extra.items() if k in ("sources",) and v})
            chat["messages"].append(message)
            chat["updated_at"] = datetime.now(timezone.utc).isoformat()
            # A tab called "Chat 3fa2c1d0" tells nobody anything. Name it after the
            # first thing asked, unless the user has named it themselves.
            if role == "user" and not chat.get("title_locked") and re.fullmatch(r"Chat [0-9a-f]{8}", chat.get("title", "")):
                derived = self._title_from(content)
                if derived:
                    chat["title"] = derived
            if role == "assistant" and self.memory_store and len(chat["messages"]) % 6 == 0:
                recent = chat["messages"][-6:]
                summary = " | ".join(f"{item['role']}: {item['content'][:250]}" for item in recent)
                self.memory_store.remember_conversation(target, summary, "Continue from the latest saved exchange.")
            self._save()

    def set_agent(self, chat_id: str, agent: str) -> dict:
        """Give a chat to one agent, or hand it back to the Manager with an empty name.

        Owner request (2026-09-15): "allow for linking to a specific chat". Every message in a chat
        that belongs to an agent is answered by that agent, not by the Manager.
        """
        with self._lock:
            if chat_id not in self.data["chats"]:
                raise KeyError(chat_id)
            chat = self.data["chats"][chat_id]
            clean = (agent or "").strip()[:40]
            if clean:
                chat["agent"] = clean
            else:
                chat.pop("agent", None)
            chat["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
            return dict(chat)

    def agent_for(self, chat_id: str) -> str:
        with self._lock:
            return str((self.data["chats"].get(chat_id) or {}).get("agent", ""))

    # --- compacted context (Request Q) -------------------------------------------------------------
    # The transcript is never shortened; the model's copy of an old chat starts from this summary instead.

    def set_compaction(self, chat_id: str, summary: str, upto: int) -> None:
        with self._lock:
            chat = self.data["chats"].get(chat_id)
            if chat is None:
                raise KeyError(chat_id)
            chat["context_summary"] = str(summary)[:6000]
            chat["compacted_upto"] = max(0, int(upto))
            self._save()

    def clear_compaction(self, chat_id: str) -> None:
        with self._lock:
            chat = self.data["chats"].get(chat_id)
            if chat is not None and ("context_summary" in chat or "compacted_upto" in chat):
                chat.pop("context_summary", None)
                chat.pop("compacted_upto", None)
                self._save()

    def compaction(self, chat_id: str) -> dict:
        with self._lock:
            chat = self.data["chats"].get(chat_id) or {}
            if not chat.get("context_summary"):
                return {}
            return {"summary": chat["context_summary"], "upto": int(chat.get("compacted_upto", 0))}

    def chats_for_agent(self, agent: str) -> list[str]:
        wanted = (agent or "").strip().lower()
        with self._lock:
            return [cid for cid, chat in self.data["chats"].items() if str(chat.get("agent", "")).lower() == wanted]

    def active_messages(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self.data["chats"][self.ensure_active()]["messages"])

    def cross_chat_context(self, limit: int = 5, exclude: str | None = None) -> str:
        with self._lock:
            skip = exclude or self.data.get("active_chat")
            snippets = []
            for chat_id, chat in self.data["chats"].items():
                if chat_id == skip:
                    continue
                messages = [item for item in chat.get("messages", []) if item.get("role") == "user"][-limit:]
                if messages:
                    snippets.append(f"{chat.get('title', chat_id)}: " + " | ".join(item["content"][:300] for item in messages))
            return "Active context from other chats:\n" + "\n".join(snippets) if snippets else ""
