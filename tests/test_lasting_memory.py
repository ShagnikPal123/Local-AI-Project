"""Lasting memories: ids, dates, the "keep long term" mark, editing, and one note file per topic."""

import json

import pytest

from memory import MemoryStore


def test_new_memory_gets_id_dates_and_keep_mark(tmp_path):
    store = MemoryStore(path=tmp_path / "memory.json")
    entry = store.remember_important("editor", "Uses VS Code", keep=True, keep_reason="Asked me to remember")

    assert entry["id"].startswith("mem_")
    assert entry["added_at"] and entry["added_at"] == entry["updated_at"]
    assert entry["keep"] is True
    assert entry["keep_reason"] == "Asked me to remember"


def test_same_topic_updates_and_keeps_id_and_added_date(tmp_path):
    store = MemoryStore(path=tmp_path / "memory.json")
    first = store.remember_important("editor", "Uses VS Code")
    second = store.remember_important("editor", "Uses Cursor")

    assert second["id"] == first["id"]
    assert second["added_at"] == first["added_at"]
    assert [item["content"] for item in store.get_important()] == ["Uses Cursor"]


def test_update_by_id_and_rename_clash(tmp_path):
    store = MemoryStore(path=tmp_path / "memory.json")
    a = store.remember_important("a", "one")
    store.remember_important("b", "two")

    edited = store.update_important(a["id"], content="uno", keep=True, keep_reason="core fact")
    assert edited["content"] == "uno" and edited["keep"] and edited["keep_reason"] == "core fact"
    with pytest.raises(ValueError):
        store.update_important(a["id"], topic="b")
    assert store.update_important("mem_missing", content="x") is None


def test_remove_by_id_or_topic_and_clear_spares_kept(tmp_path):
    store = MemoryStore(path=tmp_path / "memory.json")
    a = store.remember_important("a", "one")
    store.remember_important("b", "two", keep=True)
    store.remember_important("c", "three")

    assert store.remove_important(a["id"]) is True
    assert store.remove_important("c") is True
    store.remember_important("d", "four")
    assert store.clear_important(keep_long_term=True) == 1
    assert [item["topic"] for item in store.get_important()] == ["b"]


def test_old_entries_get_ids_once(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text(json.dumps({"preferences": {}, "important": [{"topic": "x", "content": "y", "source": "user"}]}))
    store = MemoryStore(path=path)

    first = store.get_important()[0]
    assert first["id"].startswith("mem_") and first["added_at"] is None and first["keep"] is False
    assert MemoryStore(path=path).get_important()[0]["id"] == first["id"]


def test_two_stores_do_not_overwrite_each_other(tmp_path):
    path = tmp_path / "memory.json"
    one, two = MemoryStore(path=path), MemoryStore(path=path)
    one.remember_important("from-one", "first chat")
    two.remember_important("from-two", "second chat")

    topics = {item["topic"] for item in MemoryStore(path=path).get_important()}
    assert topics == {"from-one", "from-two"}


def test_one_note_file_per_topic(tmp_path):
    store = MemoryStore(path=tmp_path / "memory.json")
    entry = store.remember_important("Favourite Food", "Pasta", keep=True, keep_reason="said so")
    note = (tmp_path / "memory_notes" / "favourite-food.md").read_text(encoding="utf-8")
    assert f"id: {entry['id']}" in note and "keep_long_term: yes" in note and "Pasta" in note

    store.remove_important(entry["id"])
    assert not (tmp_path / "memory_notes" / "favourite-food.md").exists()


def test_kept_memories_come_first_in_context(tmp_path):
    store = MemoryStore(path=tmp_path / "memory.json")
    store.remember_important("plain", "a")
    store.remember_important("kept", "b", keep=True)
    prompt = store.build_context_prompt()
    assert prompt.index("Keep (kept)") < prompt.index("Important (plain)")


def test_secrets_are_scrubbed_from_reason(tmp_path):
    store = MemoryStore(path=tmp_path / "memory.json")
    entry = store.remember_important("k", "note", keep=True, keep_reason="password is hunter2")
    assert "hunter2" not in entry["keep_reason"]
