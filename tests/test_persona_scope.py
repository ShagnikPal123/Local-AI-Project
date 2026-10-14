"""Each persona speaks only in its own chats (persona_scope.py, chat_reset.py; owner, 2026-10-14).

The bug: a "Mommy" avatar's voice reached normal chat, the notch and every other avatar. These pin each path shut.
"""

from __future__ import annotations

import pytest

import avatars
import mods
import persona_scope
from chat_sessions import ChatSessionStore
from permissions import PermissionDenied

MOMMY = {"id": "av_mommy", "name": "Mommy", "main": "custom", "main_custom": "", "does": "Comfort the owner",
         "personality": "custom", "personality_custom": "Soft, caring Mommy-ASMR voice.", "functions": {"talk": "allow"},
         "goals": [], "watches": [], "lessons": [], "notes": ["owner likes tea"]}


class FakeService:
    def __init__(self, store: ChatSessionStore, chat_id: str) -> None:
        self.chat_store, self.chat_id = store, chat_id
        self.conversation_history = [{"role": "system", "content": "base prompt"}]
        self.tool_guard = None
        self.turn_persona = None
        self.personality = None

    def set_personality(self, personality):
        self.personality = personality


@pytest.fixture
def store(tmp_path):
    return ChatSessionStore(tmp_path / "chats.json")


@pytest.fixture(autouse=True)
def mommy(monkeypatch):
    monkeypatch.setattr(avatars, "get", lambda avatar_id: dict(MOMMY) if avatar_id == "av_mommy" else None)


def _speaking_as(service) -> str:
    return next(m["content"] for m in service.conversation_history
                if m["content"].startswith(persona_scope.PERSONA_PREFIX))


def test_the_avatar_bank_reaches_only_its_own_chat(store):
    mommy_chat, normal_chat = store.create("Avatar · Mommy"), store.create("Homework")
    persona_scope.badge_avatar_chat(store, mommy_chat, MOMMY)
    in_mommy, in_normal = FakeService(store, mommy_chat), FakeService(store, normal_chat)

    persona_scope.prepare_turn(in_mommy)
    persona_scope.prepare_turn(in_normal)

    assert "Mommy-ASMR" in _speaking_as(in_mommy) and "owner likes tea" in _speaking_as(in_mommy)
    assert isinstance(in_mommy.tool_guard, avatars.AvatarGuard)
    assert "Mommy" not in _speaking_as(in_normal) and _speaking_as(in_normal) == persona_scope.ICHOS_NOTE
    assert in_normal.tool_guard is None


def test_the_note_is_replaced_each_turn_not_stacked(store):
    service = FakeService(store, store.create())
    for _ in range(3):
        persona_scope.prepare_turn(service)
    assert sum(m["content"].startswith(persona_scope.PERSONA_PREFIX) for m in service.conversation_history) == 1


def test_a_persona_chat_never_shares_cached_answers_or_learning(store):
    mommy_chat, normal_chat = store.create(), store.create()
    persona_scope.badge_avatar_chat(store, mommy_chat, MOMMY)
    in_mommy, in_normal = FakeService(store, mommy_chat), FakeService(store, normal_chat)

    assert persona_scope.context_key(in_mommy) != persona_scope.context_key(in_normal) == "ichos"
    assert not persona_scope.learns_globally(in_mommy)
    assert persona_scope.learns_globally(in_normal)
    in_normal.turn_persona = {"system_guidance": "talk like a pirate"}
    assert not persona_scope.learns_globally(in_normal) and persona_scope.context_key(in_normal).startswith("voice:")


def test_a_personality_sent_with_one_turn_is_not_kept_by_the_chat(store):
    service = FakeService(store, store.create())
    persona_scope.apply_request_personality(service, None, "Mommy voice")
    assert service.turn_persona["system_guidance"] == "Mommy voice" and service.personality is None
    persona_scope.apply_request_personality(service, None, None)
    assert service.turn_persona is None


def test_an_avatar_chat_ignores_personalities_sent_from_elsewhere(store):
    chat = store.create()
    persona_scope.badge_avatar_chat(store, chat, MOMMY)
    service = FakeService(store, chat)
    persona_scope.apply_request_personality(service, "professional", "pirate")
    assert service.turn_persona is None and service.personality is None


def test_changing_the_voice_waits_for_the_owner(store):
    service = FakeService(store, store.create())
    asked = []

    def decline(*args):
        asked.append(args)
        raise PermissionDenied("The user declined this action")

    with pytest.raises(PermissionDenied):
        persona_scope.change(service, "talk like a pirate", "Pirate", ask=decline)
    assert asked and store.persona(service.chat_id) == {}

    message = persona_scope.change(service, "talk like a pirate", "Pirate", ask=lambda *a: None)
    assert "Approved" in message
    assert store.persona(service.chat_id) == {"kind": "custom", "id": "", "name": "Pirate", "text": "talk like a pirate"}

    # Going back to Ichos needs no box.
    assert "Back to Ichos" in persona_scope.change(service, "normal", ask=decline)
    assert store.persona(service.chat_id) == {}


def test_an_avatar_told_to_change_changes_only_itself_after_approval(store, monkeypatch):
    chat = store.create()
    persona_scope.badge_avatar_chat(store, chat, MOMMY)
    saved = {}
    monkeypatch.setattr(avatars, "update", lambda avatar_id, changes: saved.update({avatar_id: changes}))

    persona_scope.change(FakeService(store, chat), "calm and plain", ask=lambda *a: None)

    assert saved == {"av_mommy": {"personality": "custom", "personality_custom": "calm and plain"}}
    assert store.persona(chat)["kind"] == "avatar"


def test_badges_show_in_the_chat_list_and_persona_chats_stay_out_of_shared_context(store):
    mommy_chat, normal_chat = store.create("Avatar · Mommy"), store.create("Homework")
    persona_scope.badge_avatar_chat(store, mommy_chat, MOMMY)
    store.append("user", "sing me a lullaby", chat_id=mommy_chat)
    store.append("user", "help with maths", chat_id=normal_chat)

    badges = {c["id"]: c["persona"] for c in store.summaries()}
    assert badges[mommy_chat] == {"kind": "avatar", "id": "av_mommy", "name": "Mommy"} and badges[normal_chat] is None
    shared = store.cross_chat_context(exclude="nothing")
    assert "lullaby" not in shared and "maths" in shared


def test_an_avatar_chat_is_not_promoted_to_shared_memory_when_deleted(tmp_path):
    from memory import MemoryStore

    memory = MemoryStore(path=tmp_path / "memory.json")
    store = ChatSessionStore(tmp_path / "chats.json", memory_store=memory)
    chat = store.create()
    persona_scope.badge_avatar_chat(store, chat, MOMMY)
    store.data["chats"][chat]["learned"] = [{"topic": "voice", "content": "call the owner sweetie"}]
    store.delete(chat, retain_memory=True)
    assert "sweetie" not in memory.build_context_prompt()


def test_avatars_skip_the_owners_talk_like_instructions(tmp_path):
    store = mods.ModStore(tmp_path / "mods.json")
    store.save("Pirate", [{"kind": "instructions", "text": "Always talk like a pirate."}])
    assert "pirate" in store.turn_context("hello")
    assert "Always talk like a pirate" not in store.turn_context("hello", instructions=False)


def test_a_new_talk_like_mod_asks_the_owner_first(tmp_path, monkeypatch):
    monkeypatch.setattr(mods, "MOD_STORE", mods.ModStore(tmp_path / "mods.json"))
    asked = []

    def decline(category, summary, detail=""):
        asked.append(detail)
        raise PermissionDenied("The user declined this action")

    monkeypatch.setattr("permissions.ask", decline)
    reply = mods.tool_mod_save("Mommy", [{"kind": "instructions", "text": "Speak like a soft ASMR mommy."}])
    assert reply.startswith("Not saved") and "ASMR" in asked[0]
    assert mods.MOD_STORE.list() == []

    # A mod with no instructions (a reminder) needs no box.
    assert "Saved" in mods.tool_mod_save("Stretch", [{"kind": "reminder", "text": "Stretch", "every_minutes": 45}])


def test_an_avatars_memories_go_to_its_own_notes(monkeypatch):
    import intelligence_tools

    noted = []
    monkeypatch.setattr(avatars, "_current_avatar_id", lambda: "av_mommy")
    monkeypatch.setattr(avatars, "add_note", lambda avatar_id, note: noted.append((avatar_id, note)))
    assert "own notes" in intelligence_tools.tool_brain_remember("owner likes lullabies")
    assert noted == [("av_mommy", "owner likes lullabies")]


def test_reset_backs_up_and_clears_voices_without_touching_avatar_badges(store, monkeypatch):
    import chat_reset
    import server

    monkeypatch.setattr(server, "_shared_chat_store", lambda: store)
    monkeypatch.setattr(mods, "MOD_STORE", mods.ModStore())
    mods.MOD_STORE.save("Mommy talk", [{"kind": "instructions", "text": "Speak like a mommy."}])
    mommy_chat, pirate_chat, normal_chat = store.create(), store.create(), store.create()
    persona_scope.badge_avatar_chat(store, mommy_chat, MOMMY)
    store.set_persona(pirate_chat, {"kind": "custom", "name": "Pirate", "text": "arr"})

    out = chat_reset.reset(["voice", "mods", "messages"])

    assert out["chat_voices_cleared"] == 1 and out["mods_paused"] == ["Mommy talk"]
    assert out["chats_moved"] == 2  # the two Ichos chats; Mommy's own chat stays
    assert list(store.data["chats"]) == [mommy_chat] and store.persona(mommy_chat)["kind"] == "avatar"
    assert {c["id"] for c in store.trash()} == {pirate_chat, normal_chat}  # restorable, not purged
    from pathlib import Path

    assert (Path(out["backup"]) / "chats.json").is_file() and (Path(out["backup"]) / "mods.json").is_file()


def test_reset_needs_at_least_one_part():
    import chat_reset

    with pytest.raises(ValueError):
        chat_reset.reset([])
