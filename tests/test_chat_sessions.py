"Tests for persistent multi-chat sessions."""

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
