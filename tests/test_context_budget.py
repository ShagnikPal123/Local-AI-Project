"""Context bar and compaction (Request Q): measuring, compacting, saving, undo, auto-compact, routes."""

from __future__ import annotations

import pytest

import context_budget as cb
from chat_sessions import ChatSessionStore


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "data_path", lambda rel: tmp_path / rel)
    cb._UNDO.clear()


class Service:
    def __init__(self, turns=10, size=400):
        self.conversation_history = [{"role": "system", "content": "You are Nyx." * 50},
                                     {"role": "system", "content": "Memory: likes tea."}]
        for i in range(turns):
            self.conversation_history.append({"role": "user", "content": f"question {i} " + "x" * size})
            self.conversation_history.append({"role": "assistant", "content": f"answer {i} " + "y" * size})
        self.conversation_history.append({"role": "user", "_tool_results": True, "content": "Tool results:\n" + "z" * 2000})


def test_windows_and_measurement():
    assert cb.window_for("gemini", "gemini-flash-lite-latest") == 1_048_576
    assert cb.window_for("kimi", "moonshot-v1-8k") == 8_000 and cb.window_for("ollama", "llama3.1") == 8_192
    assert cb.window_for("someone-new") == cb.DEFAULT_WINDOW
    service = Service()
    m = cb.measure(service.conversation_history, "kimi", "moonshot-v1-8k")
    assert m["used"] == sum(m["parts"].values()) and m["parts"]["tools"] > 500 and m["parts"]["instructions"] > 0
    assert m["parts"]["memory"] > 0 and m["messages"] == 20 and m["percent"] == pytest.approx(100 * m["used"] / 8000, abs=0.1)
    assert m["level"] == "ok" and cb.measure(Service(turns=12, size=1500).conversation_history, "kimi", "moonshot-v1-8k")["level"] == "full"
    service.conversation_history[-1]["images"] = [{"name": "a.png"}]
    assert cb.measure(service.conversation_history, "gemini")["parts"]["images"] == cb.IMAGE_TOKENS


def test_compact_keeps_recent_messages_and_system_prompt(tmp_path):
    service = Service(turns=10)
    store = ChatSessionStore(tmp_path / "chats.json")
    chat_id = store.create("Long chat")
    for message in service.conversation_history[2:]:
        if message["role"] in ("user", "assistant") and not message.get("_tool_results"):
            store.append(message["role"], message["content"], chat_id=chat_id)
    prompts = []
    result = cb.compact(service, provider="kimi", model="moonshot-v1-8k", keep_last=4, focus="the tea preference",
                        model_fn=lambda p: (prompts.append(p) or "- Asked ten questions about x\n- Prefers tea", "Groq llama"),
                        chat_store=store, chat_id=chat_id)
    history = service.conversation_history
    assert history[0]["content"].startswith("You are Nyx") and history[2]["content"].startswith(cb.SUMMARY_PREFIX)
    assert history[3]["role"] == "user" and "question 8" in history[3]["content"], "recent part starts on a question"
    assert result["after"]["used"] < result["before"]["used"] and result["compacted_messages"] == 16
    assert "the tea preference" in prompts[0] and result["source"] == "Groq llama"
    assert store.compaction(chat_id) == {"summary": "- Asked ten questions about x\n- Prefers tea", "upto": 16}
    assert len(store.messages(chat_id)) == 20, "the transcript the owner reads is untouched"

    undone = cb.undo(service, chat_store=store, chat_id=chat_id)
    assert undone["undone"] and len(service.conversation_history) == 23 and store.compaction(chat_id) == {}


def test_a_second_compaction_carries_the_first_summary_forward():
    service = Service(turns=10)
    cb.compact(service, keep_last=6, model_fn=lambda p: ("- First summary of the early talk", "m"))
    for i in range(6):
        service.conversation_history.append({"role": "user", "content": f"later {i}"})
        service.conversation_history.append({"role": "assistant", "content": f"reply {i}"})
    seen = []
    cb.compact(service, keep_last=4, model_fn=lambda p: (seen.append(p) or "- Merged summary covering everything", "m"))
    assert "First summary of the early talk" in seen[0]
    assert sum(1 for m in service.conversation_history if str(m.get("content", "")).startswith(cb.SUMMARY_PREFIX)) == 1


def test_without_a_model_an_offline_summary_is_used_and_short_chats_refuse():
    service = Service(turns=6)
    result = cb.compact(service, keep_last=2, model_fn=lambda p: (_ for _ in ()).throw(RuntimeError("no model")))
    assert result["source"] == "offline" and "- Asked: question 0" in result["summary"]
    with pytest.raises(cb.ContextError, match="Nothing to compact"):
        cb.compact(Service(turns=2), keep_last=6, model_fn=lambda p: ("x" * 40, "m"))


def test_auto_compact_only_past_the_threshold(monkeypatch):
    events = []
    monkeypatch.setattr(cb, "_default_model", lambda p: ("- auto summary of earlier messages", "fast"))
    small = Service(turns=3, size=10)
    assert cb.maybe_auto_compact(small, provider="gemini", emit=lambda *a, **k: events.append(a)) is None
    big = Service(turns=12, size=1500)
    result = cb.maybe_auto_compact(big, provider="kimi", model="moonshot-v1-8k", emit=lambda kind, **k: events.append((kind, k)))
    assert result and result["reason"] == "auto" and any(e[0] == "context.compacted" for e in events)
    cb.save_settings(auto_compact=False)
    assert cb.maybe_auto_compact(Service(turns=12, size=1500), provider="kimi", model="moonshot-v1-8k") is None


def test_a_reopened_chat_starts_from_its_saved_summary(tmp_path, monkeypatch):
    from chat_service import ChatService

    store = ChatSessionStore(tmp_path / "chats.json")
    chat_id = store.create("Reopened")
    for i in range(8):
        store.append("user", f"old question {i}", chat_id=chat_id)
        store.append("assistant", f"old answer {i}", chat_id=chat_id)
    store.set_compaction(chat_id, "- The early part, summarized", 12)
    service = ChatService(chat_store=store, chat_id=chat_id)
    contents = [str(m.get("content", "")) for m in service.conversation_history]
    assert any(c.startswith(cb.SUMMARY_PREFIX) for c in contents)
    assert "old question 0" not in contents and "old question 6" in contents


def test_routes_and_the_compact_command(tmp_path, monkeypatch):
    import commands
    import server
    from fastapi.testclient import TestClient

    service = Service(turns=10)
    store = ChatSessionStore(tmp_path / "chats.json")
    chat_id = store.create("Routes")
    monkeypatch.setattr(server, "_shared_chat_store", lambda: store)
    monkeypatch.setattr(server, "_get_service", lambda cid=None: service)
    monkeypatch.setattr(cb, "_default_model", lambda p: ("- summary from the route test", "fast"))
    client = TestClient(server.app, client=("127.0.0.1", 50131))
    measured = client.get(f"/api/chats/{chat_id}/context?provider=kimi&model=moonshot-v1-8k").json()
    assert measured["window"] == 8000 and measured["can_compact"] and not measured["can_undo"]
    done = client.post(f"/api/chats/{chat_id}/compact", json={"keep_last": 4, "provider": "kimi"}).json()
    assert done["compacted_messages"] == 16 and client.get(f"/api/chats/{chat_id}/context").json()["can_undo"]
    assert client.post(f"/api/chats/{chat_id}/compact/undo", json={}).json()["undone"]
    assert client.put("/api/context/settings", json={"threshold": 90}).json()["threshold"] == 90
    assert client.get("/api/chats/nope/context").status_code == 404
    assert any(c["name"] == "compact" and c["action"] == "context.compact" for c in commands.all_commands())
