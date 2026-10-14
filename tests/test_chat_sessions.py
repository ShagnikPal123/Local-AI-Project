"Tests for persistent multi-chat sessions."""

from datetime import datetime, timedelta, timezone

import pytest

from chat_sessions import ChatSessionStore

def test_create_switch_and_cross_chat_context(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    first = store.create("First")
    store.append("user", "Remember the database choice")
    second = store.create("Second")
    assert store.switch(first)["title"] == "First"
    assert store.cross_chat_context() == ""
    store.switch(second)
    assert "database choice" in store.cross_chat_context()

def test_sessions_reload_from_disk(tmp_path):
    path = tmp_path / "chats.json"
    store = ChatSessionStore(path)
    chat_id = store.create("Persistent")
    ChatSessionStore(path).switch(chat_id)
    assert any(item["id"] == chat_id for item in ChatSessionStore(path).list())


def test_new_chat_is_empty_and_duplicate_is_its_own_exact_copy(tmp_path):
    """Request G15: New made one empty chat; Duplicate is a separate, deliberate copy."""
    store = ChatSessionStore(tmp_path / "chats.json")
    source = store.create("Trip")
    store.append("user", "Plan Tokyo", chat_id=source)
    store.append("assistant", "Day 1: Asakusa", chat_id=source)

    fresh = store.create()
    assert store.messages(fresh) == []

    copy = store.duplicate(source)
    assert copy["title"] == "Trip (copy)"
    assert [m["content"] for m in store.messages(copy["id"])] == ["Plan Tokyo", "Day 1: Asakusa"]
    assert "parent_id" not in copy
    store.append("user", "only in the copy", chat_id=copy["id"])
    assert len(store.messages(source)) == 2


def test_branch_keeps_real_messages_up_to_a_point_and_links_both_ways(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    source = store.create("Essay")
    for role, text in [("user", "outline"), ("assistant", "I. intro"), ("user", "longer"), ("assistant", "I. intro II. body")]:
        store.append(role, text, chat_id=source)

    branch = store.branch(source, upto=2)
    assert [m["content"] for m in store.messages(branch["id"])] == ["outline", "I. intro"]
    assert branch["parent_id"] == source and branch["kind"] == "branch"
    assert branch["id"] in store.data["chats"][source]["children"]

    fork = store.fork(source)
    assert fork["kind"] == "fork" and fork["title"].endswith("— fork")
    assert store.messages(fork["id"])[0]["role"] == "system"


# --- deleting a chat (Plan Null N3) ---------------------------------------------
#
# The owner had no delete button anywhere in the Nyx chat and sat at the chat
# limit, so "New chat" failed. Deleting must free a slot at once and still be
# undoable, because a conversation is not something to lose to a stray click.

def test_a_deleted_chat_waits_in_recently_deleted_and_comes_back(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    chat_id = store.create("Groceries")
    store.append("user", "milk", chat_id=chat_id)

    assert store.delete(chat_id) is True
    assert chat_id not in [c["id"] for c in store.summaries()]

    waiting = store.trash()
    assert [t["id"] for t in waiting] == [chat_id]
    assert waiting[0]["title"] == "Groceries" and waiting[0]["message_count"] == 1

    assert store.restore(chat_id) is True
    assert [m["content"] for m in store.messages(chat_id)] == ["milk"]
    assert store.trash() == []


def test_deleting_frees_a_slot_at_the_chat_limit(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    made = [store.create(f"Chat {i}") for i in range(ChatSessionStore.MAX_CHATS)]
    with pytest.raises(RuntimeError):
        store.create("one too many")

    store.delete(made[0])
    assert store.create("now it fits")  # the deleted one no longer counts


def test_restore_is_refused_when_the_chat_was_never_deleted(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    assert store.restore(store.create("Here")) is False
    assert store.restore("nothing-like-this") is False


def test_delete_forever_leaves_nothing_to_restore(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    chat_id = store.create("Draft")
    store.delete(chat_id)

    assert store.purge(chat_id) == 1
    assert store.trash() == [] and store.restore(chat_id) is False
    assert store.purge(chat_id) == 0


def test_recently_deleted_lets_go_after_thirty_days(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    old, recent = store.create("Old"), store.create("Recent")
    store.delete(old)
    store.data["trash"][old]["deleted_at"] = (
        datetime.now(timezone.utc) - timedelta(days=ChatSessionStore.TRASH_DAYS + 1)
    ).isoformat()

    store.delete(recent)  # any delete prunes what has expired

    assert [t["id"] for t in store.trash()] == [recent]


def test_deleted_chats_survive_a_restart(tmp_path):
    path = tmp_path / "chats.json"
    store = ChatSessionStore(path)
    chat_id = store.create("Yesterday")
    store.delete(chat_id)

    assert ChatSessionStore(path).restore(chat_id) is True


def _age(store, chat_id, hours):
    """Make a chat look ``hours`` old without waiting."""
    when = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    store.data["chats"][chat_id]["updated_at"] = when


def test_auto_clean_is_off_until_turned_on(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    store.create("keep")
    empty = store.create("", activate=False)
    _age(store, empty, 200)
    assert store.auto_clean_settings()["enabled"] is False
    assert store.auto_clean() == []
    assert store.exists(empty)


def test_auto_clean_removes_only_old_empty_chats_into_the_trash(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    active = store.create("Open now")
    old_empty = store.create(activate=False)
    new_empty = store.create(activate=False)
    used = store.create("Used", activate=False)
    store.append("user", "hello", chat_id=used)
    for chat_id in (old_empty, active, used):
        _age(store, chat_id, 100)
    store.set_auto_clean(enabled=True)
    assert store.auto_clean() == [old_empty]
    assert not store.exists(old_empty)
    assert store.exists(new_empty) and store.exists(used) and store.exists(active)
    assert any(item["id"] == old_empty for item in store.trash())  # restorable, not gone
    assert store.restore(old_empty)


def test_auto_clean_old_days_spares_named_branched_and_agent_chats(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    store.create("Current")
    plain = store.create("plain", activate=False)
    named = store.create("named", activate=False)
    agent = store.create("agent", activate=False)
    for chat_id in (plain, named, agent):
        store.append("user", "hi", chat_id=chat_id)
        _age(store, chat_id, 24 * 60)
    store.rename(named, "Keep this one")
    _age(store, named, 24 * 60)
    store.set_agent(agent, "Researcher")
    _age(store, agent, 24 * 60)
    store.set_auto_clean(enabled=True, old_days=30)
    assert store.auto_clean() == [plain]
    assert store.exists(named) and store.exists(agent)


def test_auto_clean_settings_are_clamped_and_saved(tmp_path):
    path = tmp_path / "chats.json"
    store = ChatSessionStore(path)
    saved = store.set_auto_clean(enabled=True, empty_hours=0, old_days=3)
    assert saved == {"enabled": True, "empty_hours": 1, "old_days": 7}
    assert store.set_auto_clean(old_days=-5)["old_days"] == 0
    assert ChatSessionStore(path).auto_clean_settings()["enabled"] is True
