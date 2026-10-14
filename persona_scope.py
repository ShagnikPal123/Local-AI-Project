"""Each persona speaks only in its own chats, from its own memory bank (owner, 2026-10-14).

The owner made a "Mommy" avatar and its ASMR voice turned up everywhere: normal chat, the notch's quick chat and
every other avatar. His words: "instead of feeding the prompt and what to do into the normal chat, feed into a
select memory bank for each avatar which is called upon for that avatar, avatar badge, /avatar, and if that avatar is
selected as main for the assistant", "have specific chats only for a personality and add the badges feature so it
ids as that personality", and "when it is told to change it asks the user in an approve box".

How the voice leaked, and what holds each path shut now:

* **Shared answers.** The response cache keyed a reply by personality and model only, so a cached Mommy reply to
  "hi" came back in any chat. → ``context_key`` adds the persona; persona chats are never cached or learned from.
* **Shared learning.** Every turn fed the super brain, Nyx Core and the shared memory, which every chat reads back.
  → ``learns_globally`` is False in a persona chat; ``brain_remember`` there writes to the avatar's own notes.
* **Standing instructions.** A mod's "talk like…" instructions ran in every chat and every avatar.
  → a new or changed instructions mod asks the owner first (mods.py), and avatars skip mod instructions.
* **Sticky personalities.** A personality sent with one notch turn was installed in that chat for good, and the
  Settings personality was pushed into avatar chats too. → the notch's is for that turn only; avatar chats keep theirs.

The persona of a chat is a badge stored with the chat (``ChatSessionStore.set_persona``): an avatar, a voice the
owner approved for that one chat, or nothing — Ichos itself. ``prepare_turn`` reads the badge at the start of every
turn and attaches that persona's bank (who it is, its personality, its goals and notes) and nothing else's.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Optional

#: The system note that says who is speaking this turn; replaced every turn, never stored in the chat.
PERSONA_PREFIX = "[Speaking as]"

ICHOS_NOTE = (f"{PERSONA_PREFIX} Ichos, in its own voice. The owner's avatars each speak only in their own chats; "
              "never take on an avatar's personality, pet names or way of talking here. If the owner asks you to talk "
              "differently or to become a persona, call persona_change: it asks them in an approval box first.")


def _store(service: Any) -> Any:
    return getattr(service, "chat_store", None)


def persona_of(service: Any) -> Dict[str, Any]:
    """The badge of the chat this service is bound to ({} for Ichos)."""
    store = _store(service)
    if store is None or not hasattr(store, "persona"):
        return {}
    try:
        return store.persona(getattr(service, "chat_id", "") or "")
    except Exception:  # noqa: BLE001 - a missing badge is Ichos, never a failed turn
        return {}


def speaks_as_persona(service: Any) -> bool:
    """True in an avatar's chat, an approved custom voice, or a turn the notch gave a personality."""
    return bool(persona_of(service)) or bool(getattr(service, "turn_persona", None))


def learns_globally(service: Any) -> bool:
    """Only Ichos's own turns may teach the shared brain, memory and answer cache what to say."""
    return not speaks_as_persona(service)


def context_key(service: Any) -> str:
    """The persona part of a cached answer's key, so one persona's reply is never served as another's."""
    persona = persona_of(service)
    if persona.get("kind") == "avatar":
        return f"avatar:{persona.get('id', '')}"
    text = persona.get("text") or (getattr(service, "turn_persona", None) or {}).get("system_guidance", "")
    if text:
        return "voice:" + hashlib.sha1(str(text).encode("utf-8")).hexdigest()[:10]
    return "ichos"


def _avatar_note(avatar: Dict[str, Any]) -> str:
    import avatars

    return (f"{PERSONA_PREFIX} {avatar['name']}. This chat is {avatar['name']}'s own; speak only as {avatar['name']}, "
            "from the bank below, never as another avatar or as plain Ichos. If you are asked to change who you are or "
            "how you talk, call persona_change: it asks the owner in an approval box first.\n" + avatars.note_for(avatar))


def note_for(service: Any) -> str:
    """The [Speaking as] note for this service's next turn."""
    persona = persona_of(service)
    if persona.get("kind") == "avatar":
        import avatars

        avatar = avatars.get(persona.get("id", ""))
        if avatar is not None:
            return _avatar_note(avatar)
        return (f"{PERSONA_PREFIX} {persona.get('name', 'an avatar')}, an avatar that has since been removed. "
                "Answer plainly as Ichos and say that avatar is gone.")
    if persona.get("kind") == "custom" and persona.get("text"):
        return (f"{PERSONA_PREFIX} {persona.get('name', 'a voice')} — in this chat only, the owner approved: "
                f"{persona['text']}")
    turn = getattr(service, "turn_persona", None) or {}
    if turn.get("system_guidance"):
        return (f"{PERSONA_PREFIX} {turn.get('display_name') or 'the voice chosen for this turn'} — for this message "
                f"only: {turn['system_guidance']}")
    return ICHOS_NOTE


def prepare_turn(service: Any) -> Dict[str, Any]:
    """Attach this turn's [Speaking as] note, and an avatar's guard in its own chat. Returns the badge.

    Runs at the start of every turn whoever started it (the app, the notch, WhatsApp, an avatar's schedule), so a
    persona's bank reaches only its own chats.
    """
    persona = persona_of(service)
    history = getattr(service, "conversation_history", None)
    if history is None:
        return persona
    service.conversation_history = [m for m in history if not (
        m.get("role") == "system" and str(m.get("content", "")).startswith(PERSONA_PREFIX))]
    insert_at = 1 if service.conversation_history else 0
    service.conversation_history.insert(insert_at, {"role": "system", "content": note_for(service)})
    if persona.get("kind") == "avatar":
        import avatars

        avatar = avatars.get(persona.get("id", ""))
        guard = getattr(service, "tool_guard", None)
        # Typed into the avatar's chat from the app, it still runs behind the avatar's own rules. A guard someone
        # else set for this turn (WhatsApp's phone guard wraps the avatar's) is left alone.
        if avatar is not None and (guard is None or isinstance(guard, avatars.AvatarGuard)):
            service.tool_guard = avatars.AvatarGuard(avatar)
    return persona


def badge_avatar_chat(store: Any, chat_id: str, avatar: Dict[str, Any]) -> None:
    """Mark ``chat_id`` as ``avatar``'s own chat (and keep the badge's name current)."""
    try:
        store.set_persona(chat_id, {"kind": "avatar", "id": avatar["id"], "name": avatar["name"]})
    except Exception:  # noqa: BLE001 - a store without badges (tests) still runs the turn
        pass


# ---------------------------------------------------------------------------
# persona_change: the approval box
# ---------------------------------------------------------------------------

_BACK_TO_NORMAL = ("normal", "ichos", "default", "yourself", "reset", "none", "off", "plain")


def _current_service() -> Any:
    """The chat service running this tool call (its turn context names the chat)."""
    try:
        from tool_context import current

        ctx = current()
        if ctx is None or not ctx.chat_id or ctx.chat_id == "default":
            return None
        import server

        return server._get_service(ctx.chat_id)
    except Exception:  # noqa: BLE001
        return None


def change(service: Any, how: str, name: str = "", ask: Any = None) -> str:
    """Change who this one chat speaks as, after the owner approves. ``ask`` raises PermissionDenied on a no."""
    how = (how or "").strip()
    if not how:
        return "Error: say how the owner wants you to talk."
    store, chat_id = _store(service), getattr(service, "chat_id", "") or ""
    if store is None or not hasattr(store, "set_persona") or not store.exists(chat_id):
        return "Error: this conversation has no chat to change."
    persona = persona_of(service)
    normal = how.lower().strip(" .!") in _BACK_TO_NORMAL
    if normal and persona.get("kind") != "avatar":
        store.set_persona(chat_id, None)
        return "Back to Ichos's own voice in this chat."
    if ask is None:
        from permissions import ask as approval_box

        ask = approval_box
    if persona.get("kind") == "avatar":
        import avatars

        avatar = avatars.get(persona.get("id", ""))
        if avatar is None:
            return "Error: this chat's avatar no longer exists."
        ask("persona", f"Change how {avatar['name']} talks?",
            f"{avatar['name']} was asked to change its personality to: {how[:600]}\n"
            "Approve to save it as this avatar's personality. Its other chats and every other avatar stay as they are.")
        avatars.update(avatar["id"], {"personality": "custom", "personality_custom": how[:1200]})
        return f"Approved. {avatar['name']}'s personality is now: {how[:200]}"
    label = (name or "Custom voice").strip()[:40]
    ask("persona", "Change how Ichos talks in this chat?",
        f"Asked to speak as: {how[:600]}\nApprove to give this one chat that voice (with a badge). Every other chat, "
        "the notch and the avatars stay as they are.")
    store.set_persona(chat_id, {"kind": "custom", "name": label, "text": how})
    return f"Approved. This chat now speaks as {label}; it shows a badge, and no other chat changes."


def tool_persona_change(how: str, name: str = "") -> str:
    service = _current_service()
    if service is None:
        return "Error: no chat to change here."
    try:
        return change(service, how, name)
    except Exception as error:  # noqa: BLE001 - a "no" from the owner, or no one watching, is the answer
        return f"Not changed: {error}"


def register_persona_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="persona_change",
        description="Change who this chat speaks as — when the owner asks you to talk differently, take on a persona "
                    "or personality, or go back to normal. Changing it opens an approval box for the owner; it applies "
                    "to this one chat only (in an avatar's chat, to that avatar). how='normal' goes back to Ichos.",
        parameters=[ToolParam("how", "string", "How to talk, in the owner's words, or 'normal'"),
                    ToolParam("name", "string", "A short name for the badge, e.g. Pirate", required=False)],
        handler=tool_persona_change, category="general", label=lambda a: "Asking to change how I talk",
    )


def apply_request_personality(service: Any, personality_id: Optional[str], personality_text: Optional[str]) -> None:
    """A personality sent with one request. Custom words (the notch's chosen voice, a spoken turn) last that turn
    only; a preset id is the chat's own setting. An avatar's chat ignores both: it speaks only as itself."""
    from personalities import resolve_personality

    service.turn_persona = None
    if persona_of(service).get("kind") == "avatar":
        return
    if personality_text and personality_text.strip():
        service.turn_persona = resolve_personality(None, personality_text)
    elif personality_id:
        personality = resolve_personality(personality_id, None)
        if personality:
            service.set_personality(personality)
