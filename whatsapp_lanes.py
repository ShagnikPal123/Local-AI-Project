"""Which conversation a WhatsApp text belongs to: the general chat, another chat, or one avatar.

Owner (2026-10-13): "In whatsapp update so I can talk to different avatars for different lines … and if I am in the
general chat I can request a specific avatar to talk to or I can create one", and "a / command lists chats with the
WhatsApp badge and continues one".

A *lane* is where the next text goes. There is always exactly one current lane:

  general  the chat called "WhatsApp" (what the line always did)
  chat     any chat from the PC, picked with ``/chats`` then ``/chat 2``
  avatar   one of the owner's avatars, picked with ``/avatar Mira`` or made with ``/newavatar``

A single text can also name an avatar without switching: ``@Mira what is on today?`` is answered by Mira and the lane
stays where it was. Every reply that is not from the general lane starts with the speaker's name in bold, so on one
phone number the owner can still tell who is talking.

This module is only the words: parsing what the owner typed and formatting what goes back. It touches no WhatsApp,
no chat store and no avatar, so it is tested without any of them. ``whatsapp_link`` does the acting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

GENERAL = "general"
CHAT = "chat"
AVATAR = "avatar"
LANE_KINDS = (GENERAL, CHAT, AVATAR)

#: How many chats ``/chats`` lists; numbers stay valid until the next ``/chats``.
CHATS_SHOWN = 9
#: A new avatar made from the phone starts off, with the safest set of functions (web only), like the PC's default.
NEW_AVATAR_NOTE = "It starts switched off, with web search only. Switch it on and give it more in Avatars on the PC."

HELP = (
    "Nyx on WhatsApp. Just text me.\n"
    "/chats — your recent chats; /chat 2 continues the second one\n"
    "/avatars — your avatars; /avatar Mira talks to Mira from now on\n"
    "@Mira your question — ask one avatar once, without switching\n"
    "/newavatar Name: what it does — make an avatar\n"
    "/general — back to the main WhatsApp chat\n"
    "/where — who I am answering as right now\n"
    "/away — I am gone: text me when chats finish or need me; /back to go by how long I have been idle\n"
    "/new — start a fresh conversation in this lane\n"
    "/status — what this line is tied to\n"
    "/pause — stop answering until you resume it on the PC\n"
    "/help — this list"
)


@dataclass(frozen=True)
class Command:
    """A shortcut the owner typed: ``name`` without the slash, ``arg`` the rest of the line."""

    name: str
    arg: str = ""


_COMMANDS = frozenset({"help", "status", "pause", "new", "chats", "chat", "avatars", "avatar", "newavatar", "general",
                       "where", "away", "back"})


def parse(text: str) -> Optional[Command]:
    """``/chat 2`` → Command("chat", "2"). Anything that is not a known shortcut is ordinary talk (None)."""
    text = (text or "").strip()
    if not text.startswith("/"):
        return None
    head, _, rest = text[1:].partition(" ")
    name = head.strip().lower()
    return Command(name, rest.strip()) if name in _COMMANDS else None


_MENTION = re.compile(r"^@([^\s@:,]{1,40})[\s:,]+(.+)$", re.DOTALL)


def split_mention(text: str) -> Optional[Tuple[str, str]]:
    """``@Mira what is on today?`` → ("Mira", "what is on today?"). The caller checks that Mira is a real avatar."""
    found = _MENTION.match((text or "").strip())
    return (found.group(1), found.group(2).strip()) if found else None


def split_new_avatar(arg: str) -> Optional[Tuple[str, str]]:
    """``Mira: watches my inbox`` or ``Mira - watches my inbox`` → ("Mira", "watches my inbox")."""
    found = re.match(r"^\s*([^:\-–—]{1,40}?)\s*(?::|\s[-–—]\s)\s*(.+)$", arg or "", re.DOTALL)
    if not found:
        return None
    name, does = found.group(1).strip(), found.group(2).strip()
    return (name, does) if name and does else None


def lane(kind: str = GENERAL, ident: str = "") -> Dict[str, str]:
    return {"kind": kind if kind in LANE_KINDS else GENERAL, "id": ident if kind in (CHAT, AVATAR) else ""}


def is_general(current: Optional[Dict[str, Any]]) -> bool:
    return not current or current.get("kind", GENERAL) == GENERAL


def tag(name: str, text: str) -> str:
    """Put the speaker first so one phone number can carry several voices."""
    name = (name or "").strip()
    return f"*{name}*\n{text}" if name and text else text


def format_chats(chats: Sequence[Dict[str, Any]], current_id: str = "", linked: Sequence[str] = ()) -> Tuple[str, List[str]]:
    """The numbered list for ``/chats`` and the ids behind the numbers (stored, so ``/chat 2`` means that one)."""
    shown = list(chats)[:CHATS_SHOWN]
    if not shown:
        return "You have no chats yet. Start one on the PC, or just text me here.", []
    lines = []
    for number, chat in enumerate(shown, 1):
        marks = []
        if chat["id"] == current_id:
            marks.append("talking here now")
        if chat["id"] in linked:
            marks.append("on WhatsApp")
        lines.append(f"{number}. {str(chat.get('title') or chat['id'])[:60]}" + (f" ({', '.join(marks)})" if marks else ""))
    return "Your chats:\n" + "\n".join(lines) + "\n\nText /chat and a number to continue one.", [c["id"] for c in shown]


def pick_chat(arg: str, listing: Sequence[str], chats: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A chat from ``/chat <number|part of the title>``. A number means the last ``/chats`` list; words must match
    exactly one title, so a vague guess never lands in the wrong conversation."""
    arg = (arg or "").strip()
    by_id = {chat["id"]: chat for chat in chats}
    if arg.isdigit():
        index = int(arg) - 1
        if 0 <= index < len(listing):
            return by_id.get(listing[index])
        return None
    if arg in by_id:
        return by_id[arg]
    wanted = arg.lower()
    matches = [c for c in chats if wanted and wanted in str(c.get("title") or "").lower()]
    return matches[0] if len(matches) == 1 else None


def format_avatars(avatars: Sequence[Dict[str, Any]], current_id: str = "") -> str:
    if not avatars:
        return "You have no avatars yet. Make one: /newavatar Name: what it does"
    lines = []
    for item in avatars:
        state = "" if item.get("enabled", True) else ", off"
        here = " ← talking to now" if item["id"] == current_id else ""
        does = str(item.get("does") or "").strip().replace("\n", " ")
        lines.append(f"• {item['name']}{state}" + (f" — {does[:70]}" if does else "") + here)
    return "Your avatars:\n" + "\n".join(lines) + "\n\n/avatar Name to talk to one, or @Name before a question."


def describe(current: Optional[Dict[str, Any]], name: str = "") -> str:
    """One line for ``/where``."""
    kind = (current or {}).get("kind", GENERAL)
    if kind == AVATAR:
        return f"You are talking to the avatar {name or 'unknown'}. /general goes back to the main chat."
    if kind == CHAT:
        return f"You are continuing the chat “{name or 'unknown'}”. /general goes back to the main chat."
    return "You are in the main WhatsApp chat. /chats and /avatars show where else you can go."
