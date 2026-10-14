"""Reset chats that have "gotten out of hand" (owner, 2026-10-14).

His words: "reset my chats in some way to remove the weird parts which changed how it talks and add a reset for all
users if they need", "add that as an option if the user feels their chats have gotten out of hand", and "add a clear
for whatsapp chat as well". It is a Settings card (Settings → Chats) and ``POST /api/chat-reset``.

Every reset first copies what it touches into ``backups/reset-<time>/`` under the data folder, and chats are moved
to Recently deleted (restorable for 30 days), never purged — nothing a reset does is beyond undoing.

The parts, each a checkbox:

* ``voice`` (on by default) — how Ichos talks: every open chat rebuilt without a sticky personality, custom chat
  voices dropped (avatar badges stay), the notch back to Ichos's own personality, and the answer cache emptied so an
  old reply in someone else's voice is never served again.
* ``mods`` (on by default) — pause the mods holding standing "talk like…" instructions. Paused, not deleted.
* ``messages`` — move every Ichos chat (not the avatars') to Recently deleted.
* ``avatars`` — move every avatar's own chat to Recently deleted. Each avatar's settings and notes stay.
* ``whatsapp`` — clear the WhatsApp line's chats and log; the pairing stays.
"""

from __future__ import annotations

import shutil
import time
from typing import Any, Dict, List

from paths import data_path

PARTS = ("voice", "mods", "messages", "avatars", "whatsapp")
DEFAULT_PARTS = ("voice", "mods")
#: What a reset may change, copied first. Missing files are skipped.
BACKED_UP = ("chats.json", "mods.json", "equalize_assistant.json", "avatars.json", "whatsapp/link.json",
             "learning/cache.json")


def backup(chats_file: Any = None) -> str:
    folder = data_path(f"backups/reset-{time.strftime('%Y%m%d-%H%M%S')}")
    folder.mkdir(parents=True, exist_ok=True)
    sources = {name: data_path(name) for name in BACKED_UP}
    if chats_file is not None:
        sources["chats.json"] = chats_file  # the store the server really uses
    for name, source in sources.items():
        if source.is_file():
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return str(folder)


def _reset_voice(store: Any) -> Dict[str, Any]:
    import server

    voices = 0
    for chat in store.summaries():
        persona = chat.get("persona") or {}
        if persona.get("kind") == "custom":
            store.set_persona(chat["id"], None)
            voices += 1
    with server._services_lock:
        dropped = [key for key in list(server._services) if not key.startswith("__")]
        for key in dropped:
            server._services.pop(key, None)  # rebuilt from the stored chat on its next turn, with no sticky voice
    try:
        import equalize_assistant as ea

        with ea._lock:
            state = ea._load()
            state["personality"] = {"source": "normal", "text": ""}
            state["avatar"]["keep_personality"] = False
            ea._save(state)
    except Exception:  # noqa: BLE001 - the notch is optional
        pass
    try:
        from response_cache import RESPONSE_CACHE

        RESPONSE_CACHE.clear()
    except Exception:  # noqa: BLE001
        pass
    return {"chat_voices_cleared": voices, "open_chats_rebuilt": len(dropped)}


def _pause_instruction_mods() -> List[str]:
    from mods import MOD_STORE

    paused = []
    for mod in MOD_STORE.enabled():
        if any(part.get("kind") == "instructions" for part in mod.get("parts") or []):
            MOD_STORE.set_enabled(mod["id"], False)
            paused.append(mod["name"])
    return paused


def _move_chats(store: Any, avatars: bool) -> int:
    import server

    moved = 0
    for chat in store.summaries():
        is_avatar = (chat.get("persona") or {}).get("kind") == "avatar"
        if is_avatar != avatars:
            continue
        if store.delete(chat["id"], retain_memory=False):
            server._forget_service(chat["id"])
            moved += 1
    return moved


def reset(parts: Any = DEFAULT_PARTS) -> Dict[str, Any]:
    """Run the chosen parts of a reset; returns what each one did and where the backup is."""
    import server

    wanted = [p for p in PARTS if p in set(parts or ())]
    if not wanted:
        raise ValueError("Pick at least one thing to reset.")
    store = server._shared_chat_store()
    out: Dict[str, Any] = {"backup": backup(getattr(store, "path", None)), "parts": wanted}
    if "voice" in wanted:
        out.update(_reset_voice(store))
    if "mods" in wanted:
        out["mods_paused"] = _pause_instruction_mods()
    if "messages" in wanted:
        out["chats_moved"] = _move_chats(store, avatars=False)
    if "avatars" in wanted:
        out["avatar_chats_moved"] = _move_chats(store, avatars=True)
    if "whatsapp" in wanted:
        try:
            import whatsapp_link

            done = whatsapp_link.link().clear_chat()
            out["whatsapp"] = {"cleared": done["cleared"], "chats_moved": done["chats_moved"]}
        except Exception as error:  # noqa: BLE001 - reported, the rest of the reset still counts
            out["whatsapp"] = {"cleared": False, "error": str(error)[:200]}
    return out
