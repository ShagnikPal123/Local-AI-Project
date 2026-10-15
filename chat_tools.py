"""Chats Nyx can make by being asked: new, duplicate, branch, fork, rename (Request G15).

The owner wanted these "either by telling or by a button". The buttons call
``/api/chats/{id}/duplicate|branch|fork``; these tools do the same from a chat
turn and publish ``chat.created`` so the open chat panel moves to the new chat
when the turn ends.

Kinds, so the words mean one thing each:

* **new** — an empty chat.
* **duplicate** — an exact, unlinked copy of every message.
* **branch** — a linked chat holding the real messages up to a point, to take
  the conversation another way from there.
* **fork** — a linked chat that starts from a short summary of recent context,
  to work on a side-thread without carrying the whole history.
"""

from __future__ import annotations

from typing import Any, Optional


def _store() -> Any:
    import server

    return server._shared_chat_store()


def _current_chat() -> str:
    from tool_context import current

    ctx = current()
    return getattr(ctx, "chat_id", "") or _store().data.get("active_chat") or ""


def _announce(chat: dict, kind: str, open_it: bool) -> None:
    from tool_context import emit

    emit("chat.created", chat_id=chat["id"], title=chat.get("title", ""), kind=kind, open=open_it)


def chat_new(title: str = "", open: bool = True) -> str:
    store = _store()
    chat_id = store.create(title.strip() or None)
    if title.strip():
        store.rename(chat_id, title)
    chat = {"id": chat_id, **store.data["chats"][chat_id]}
    _announce(chat, "new", open)
    return f"Created an empty chat “{chat.get('title')}” (id {chat_id})."


def chat_duplicate(chat_id: str = "", title: str = "", open: bool = True) -> str:
    source = chat_id.strip() or _current_chat()
    chat = _store().duplicate(source, title.strip() or None)
    _announce(chat, "duplicate", open)
    return f"Duplicated the chat as “{chat.get('title')}” (id {chat['id']}, {len(chat.get('messages', []))} messages copied)."


def chat_branch(chat_id: str = "", upto: Optional[float] = None, title: str = "", open: bool = True) -> str:
    source = chat_id.strip() or _current_chat()
    keep = int(upto) if upto not in (None, "") else None
    chat = _store().branch(source, keep, title.strip() or None)
    _announce(chat, "branch", open)
    return f"Branched into “{chat.get('title')}” (id {chat['id']}), keeping {chat.get('branched_at', 0)} messages."


def chat_fork(chat_id: str = "", title: str = "", open: bool = True) -> str:
    source = chat_id.strip() or _current_chat()
    chat = _store().fork(source, title.strip() or None)
    _announce(chat, "fork", open)
    return f"Forked into “{chat.get('title')}” (id {chat['id']}) with a summary of the recent conversation."


def chat_rename(title: str, chat_id: str = "") -> str:
    target = chat_id.strip() or _current_chat()
    if not _store().rename(target, title):
        return "Could not rename: no such chat, or the name was empty."
    from tool_context import emit

    emit("chat.renamed", chat_id=target, title=title.strip()[:80])
    return f"Renamed the chat to “{title.strip()[:80]}”. Nyx will not rename it again."


def edit_my_message(old: str, note: str, new: str = "", chat_id: str = "") -> str:
    """Cross out part of one of Nyx's own earlier replies, Claude-style (Drive doc 2, item 2.4).

    The struck text stays readable and the "[Edit: …]" says why, so the owner can see what changed rather than
    finding the past quietly rewritten. Only Nyx's own replies, and only text that is really in one.
    """
    target = chat_id.strip() or _current_chat()
    old, note, new = (old or "").strip(), (note or "").strip(), (new or "").strip()
    if not old or not note:
        return "Nothing edited: give the exact text to cross out (old) and a short reason (note)."
    store = _store()
    shown = [m for m in store.messages(target) if m.get("role") in ("user", "assistant")]
    for back, message in enumerate(reversed(shown)):
        content = str(message.get("content", ""))
        if message.get("role") != "assistant" or old not in content or f"~~{old}~~" in content:
            continue
        fixed = content.replace(old, f"~~{old}~~ {new + ' ' if new else ''}[Edit: {note[:300]}]", 1)
        store.edit_message(target, len(shown) - 1 - back, content, fixed, by="nyx", note=note)
        from tool_context import emit

        emit("chat.message_edited", chat_id=target)
        return "Crossed it out in your earlier reply, with the edit note. The chat shows it as edited."
    return "Nothing edited: that exact text is not in any of your earlier replies in this chat (or it is already crossed out)."


def register_chat_tools(registry: Any) -> None:
    from tools import ToolParam as P

    def reg(name, description, params, handler, label):
        registry.register(name, description, params, handler, category="general", label=label)

    opened = P("open", "boolean", "Open the new chat when this turn ends (default true)", required=False)
    which = P("chat_id", "string", "Source chat id (default: this chat)", required=False)
    reg("chat_new", "Create one new, empty chat. Use for 'new chat', 'start fresh'.",
        [P("title", "string", "Optional name", required=False), opened], chat_new, lambda a: "Creating a new chat")
    reg("chat_duplicate", "Make an exact copy of a chat (every message, not linked). Use for 'duplicate this chat', 'make a copy'.",
        [which, P("title", "string", "Optional name", required=False), opened], chat_duplicate, lambda a: "Duplicating the chat")
    reg("chat_branch", "Branch a chat: a linked chat with the real messages up to a point, to go a different way from there. "
        "Use for 'branch this', 'branch from here', 'try another approach in a new chat'.",
        [which, P("upto", "number", "How many user/assistant messages to keep (default: all)", required=False),
         P("title", "string", "Optional name", required=False), opened], chat_branch, lambda a: "Branching the chat")
    reg("chat_fork", "Fork a chat: a linked chat that starts from a short summary of recent context. "
        "Use for 'fork this', 'work on this side-thread separately'.",
        [which, P("title", "string", "Optional name", required=False), opened], chat_fork, lambda a: "Forking the chat")
    reg("edit_my_message", "Cross out part of one of YOUR OWN earlier replies in this chat when it was wrong or has gone "
        "stale (a PR you asked about has merged, a plan changed). The struck text stays visible with '[Edit: note]', "
        "like Claude's edits. Use it instead of pretending you never said it.",
        [P("old", "string", "The exact text from your earlier reply to cross out"),
         P("note", "string", "A short reason, e.g. 'no longer needed, PR #10 has merged'"),
         P("new", "string", "Optional corrected text placed after the struck part", required=False), which],
        edit_my_message, lambda a: "Editing an earlier reply")
    reg("chat_rename", "Rename a chat. The owner's name is kept; Nyx stops auto-naming it.",
        [P("title", "string", "New name"), which], chat_rename, lambda a: f"Renaming the chat to {str(a.get('title', ''))[:40]}")
