"""Chat tools Nyx calls from a turn: here, crossing out its own stale words (Drive doc 2, item 2.4)."""

import chat_tools
from chat_sessions import ChatSessionStore


def _chat(tmp_path, monkeypatch):
    store = ChatSessionStore(tmp_path / "chats.json")
    chat = store.create("Edits")
    store.append("user", "merge it?", chat_id=chat)
    store.append("assistant", "Should I resolve the conflict and merge PR #10?", chat_id=chat)
    monkeypatch.setattr(chat_tools, "_store", lambda: store)
    return store, chat


def test_edit_my_message_strikes_the_text_and_adds_the_note(tmp_path, monkeypatch):
    store, chat = _chat(tmp_path, monkeypatch)
    said = chat_tools.edit_my_message("Should I resolve the conflict and merge PR #10?", "no longer needed, PR #10 has merged",
                                      chat_id=chat)
    assert said.startswith("Crossed it out")
    assert store.messages(chat)[1]["content"] == (
        "~~Should I resolve the conflict and merge PR #10?~~ [Edit: no longer needed, PR #10 has merged]")
    # Twice is refused: it is already crossed out.
    assert chat_tools.edit_my_message("Should I resolve the conflict and merge PR #10?", "again", chat_id=chat).startswith("Nothing")


def test_edit_my_message_never_touches_the_owners_words_or_missing_text(tmp_path, monkeypatch):
    store, chat = _chat(tmp_path, monkeypatch)
    assert chat_tools.edit_my_message("merge it?", "no", chat_id=chat).startswith("Nothing")
    assert chat_tools.edit_my_message("not there", "no", chat_id=chat).startswith("Nothing")
    assert store.messages(chat)[0]["content"] == "merge it?"
