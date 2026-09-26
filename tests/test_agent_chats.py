"""A sub-agent can own a chat: started with or without a task, and linked later (owner, 2026-09-15)."""

from __future__ import annotations

import pytest

from chat_sessions import ChatSessionStore


def test_a_chat_can_be_given_to_an_agent_and_handed_back(tmp_path):
    store = ChatSessionStore(path=tmp_path / "chats.json")
    chat_id = store.create(title="Price Scout")
    assert store.agent_for(chat_id) == ""
    store.set_agent(chat_id, "Price Scout")
    assert store.agent_for(chat_id) == "Price Scout"
    assert store.chats_for_agent("price scout") == [chat_id]
    assert next(s for s in store.summaries() if s["id"] == chat_id)["agent"] == "Price Scout"
    store.set_agent(chat_id, "")
    assert store.agent_for(chat_id) == "" and store.chats_for_agent("Price Scout") == []
    with pytest.raises(KeyError):
        store.set_agent("nope", "Price Scout")


def test_every_message_in_an_agents_chat_is_answered_by_that_agent(tmp_path, monkeypatch):
    import agent_runtime
    import turn_runner

    store = ChatSessionStore(path=tmp_path / "chats.json")
    chat_id = store.create(title="Scout")
    store.set_agent(chat_id, "Researcher")

    class _Service:
        def __init__(self, chat, store_):
            self.chat_id = chat
            self.chat_store = store_
            self.conversation_history = [{"role": "user", "content": "earlier question"}]
            self.saved = ""

        enable_tools = True
        auto_web_search = False
        speed_mode = "auto"

        def add_message(self, role, content):
            self.conversation_history.append({"role": role, "content": content})

        def _append_assistant_response(self, reply, extra=None):
            self.saved = reply

    asked = {}

    def fake_specialist(name, task, context="", **kwargs):
        asked.update(name=name, task=task, context=context)
        return "Three options, cheapest first."

    monkeypatch.setattr(agent_runtime, "run_specialist", fake_specialist)
    monkeypatch.setattr(turn_runner, "TOOL_REGISTRY", turn_runner.TOOL_REGISTRY)

    events = []
    runner = turn_runner.TurnRunner(_Service(chat_id, store), "find me a laptop", sink=events.append)
    result = runner._answer_as_agent("Researcher", "find me a laptop")
    assert asked["name"] == "Researcher" and asked["task"] == "find me a laptop"
    assert "earlier question" in asked["context"]
    assert result["reply"] == "Three options, cheapest first."
    assert any(e.get("type") == "status" and "Researcher" in e.get("text", "") for e in events)
