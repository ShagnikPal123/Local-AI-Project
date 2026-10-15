"""Drive doc 1 item 1.29: /rewind branches the chat without its last exchanges; /context, /rewind, /goal are listed."""

import pytest

import commands
from chat_sessions import ChatSessionStore


@pytest.fixture()
def setup(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import server

    store = ChatSessionStore(tmp_path / "chats.json")
    monkeypatch.setattr(server, "_shared_chat_store", lambda: store)
    return store, TestClient(server.app, client=("127.0.0.1", 50123))


def _talk(store, chat_id, turns):
    for n in range(turns):
        store.append("user", f"question {n}", chat_id=chat_id)
        store.append("assistant", f"answer {n}", chat_id=chat_id)


def test_rewind_one_leaves_out_the_last_exchange(setup):
    store, client = setup
    chat_id = store.create("Trip plans")
    _talk(store, chat_id, 3)

    answer = client.post(f"/api/chats/{chat_id}/branch", json={"back": 1, "title": ""})
    assert answer.status_code == 200
    branch = answer.json()["chat"]
    assert branch["title"].startswith("Trip plans")
    kept = [m["content"] for m in store.messages(branch["id"]) if m.get("role") in ("user", "assistant")]
    assert kept == ["question 0", "answer 0", "question 1", "answer 1"]


def test_rewinding_further_than_the_chat_goes_is_refused(setup):
    store, client = setup
    chat_id = store.create("Short")
    _talk(store, chat_id, 1)
    assert client.post(f"/api/chats/{chat_id}/branch", json={"back": 3}).status_code == 400


def test_context_rewind_and_goal_are_commands():
    names = {c["name"] for c in commands.all_commands()}
    assert {"context", "rewind", "goal"} <= names
