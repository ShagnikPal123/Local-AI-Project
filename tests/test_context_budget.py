"""Context bar and compaction (Request Q): measuring, compacting, saving, undo, auto-compact, routes."""

from __future__ import annotations

import pytest

import context_budget as cb
from chat_sessions import ChatSessionStore
from providers import ollama_provider


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
    assert cb.window_for("kimi", "moonshot-v1-8k") == 8_000 and cb.window_for("ollama", "llama3.1") == ollama_provider.num_ctx("llama3.1")
    assert cb.window_for("someone-new") == cb.DEFAULT_WINDOW
    service = Service()
    m = cb.measure(service.conversation_history, "kimi", "moonshot-v1-8k")
    assert m["used"] == sum(m["parts"].values()) and m["parts"]["tools"] > 500 and m["parts"]["instructions"] > 0
    # The chat holds 1M tokens whatever answers; the 8k model's own window is reported beside it.
    assert m["window"] == cb.CHAT_WINDOW and m["model_window"] == 8000 and m["fits_model"]
    assert m["parts"]["memory"] > 0 and m["messages"] == 20 and m["percent"] == pytest.approx(100 * m["used"] / cb.CHAT_WINDOW, abs=0.1)
    big = cb.measure(Service(turns=12, size=1500).conversation_history, "kimi", "moonshot-v1-8k")
    assert m["level"] == "ok" and big["level"] == "ok" and not big["fits_model"], "past 8k the model gets a fitted copy"
    assert cb.measure(service.conversation_history, "identity0")["model_window"] == 0, "Big Kahuna picks a model per turn"
    service.conversation_history[-1]["images"] = [{"name": "a.png"}]
    assert cb.measure(service.conversation_history, "gemini")["parts"]["images"] == cb.IMAGE_TOKENS



def test_a_fresh_local_chat_is_not_reported_full(monkeypatch):
    """The meter used 8,192 for Ollama while every call asks for num_ctx; ~15k of instructions read as 186 %."""
    monkeypatch.setattr(ollama_provider, "num_ctx", lambda model=None: 32_768)
    instructions = [{"role": "system", "content": "x" * int(15_000 * cb.CHARS_PER_TOKEN)},
                    {"role": "user", "content": "hi"}]
    m = cb.measure(instructions, "ollama", "qwen3.5:9b")
    assert m["window"] == cb.CHAT_WINDOW and m["model_window"] == 32_768 and m["fits_model"] and m["percent"] < 5


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
    monkeypatch.setattr(cb, "CHAT_WINDOW", 8000)  # the threshold logic, on a chat small enough to fill in a test
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
    assert measured["window"] == cb.CHAT_WINDOW and measured["model_window"] == 8000
    assert measured["can_compact"] and not measured["can_undo"]
    done = client.post(f"/api/chats/{chat_id}/compact", json={"keep_last": 4, "provider": "kimi"}).json()
    assert done["compacted_messages"] == 16 and client.get(f"/api/chats/{chat_id}/context").json()["can_undo"]
    assert client.post(f"/api/chats/{chat_id}/compact/undo", json={}).json()["undone"]
    assert client.put("/api/context/settings", json={"threshold": 90}).json()["threshold"] == 90
    assert client.get("/api/chats/nope/context").status_code == 404
    assert any(c["name"] == "compact" and c["action"] == "context.compact" for c in commands.all_commands())


# ---------------------------------------------------------------------------
# A 1M-token chat, each call sized to its model (owner, 2026-10-11)
# ---------------------------------------------------------------------------


def _long_chat(turns=200, size=2000):
    history = [{"role": "system", "content": "You are Ichos. " * 40}, {"role": "system", "content": "Memory: likes tea."}]
    for i in range(turns):
        extra = " The launch code word is PELICAN-7 and the budget is 4200 dollars." if i == 3 else ""
        history.append({"role": "user", "content": f"question {i}{extra} " + "x" * size})
        history.append({"role": "assistant", "content": f"answer {i} " + "y" * size})
    history.append({"role": "user", "content": "What was the launch code word and budget again?"})
    return history


def test_fit_leaves_a_chat_that_fits_alone():
    history = _long_chat(turns=3, size=100)
    assert cb.fit(history, 200_000) is history


def test_fit_sizes_a_long_chat_to_the_model_and_recalls_the_match():
    history = _long_chat()
    window = 32_768
    fitted = cb.fit(history, window)
    assert sum(cb._cost(m) for m in fitted) <= window, "fits the model, with room for the answer"
    assert fitted[0] == history[0] and fitted[1] == history[1], "instructions and memory always go"
    assert fitted[-1] == history[-1], "the question being answered always goes"
    note = next(m for m in fitted if str(m["content"]).startswith("[Earlier in this chat]"))
    assert "PELICAN-7" in note["content"] and "recall_chat" in note["content"], "the old match is recalled"
    after = fitted[fitted.index(note) + 1]
    assert after["role"] == "user" and after["content"].startswith("question"), "word-for-word part starts on a question"
    assert any(m["content"].startswith("answer 198") for m in fitted), "the newest messages are kept"


def test_fit_keeps_a_turns_tool_steps_and_clips_one_that_alone_overflows():
    history = _long_chat(turns=40, size=2000)
    history.append({"role": "assistant", "content": "<tool_call>web_read</tool_call>"})
    history.append({"role": "user", "_tool_results": True, "content": "Tool results:\n" + "page " * 60_000})
    fitted = cb.fit(history, 16_384)
    assert sum(cb._cost(m) for m in fitted) <= 16_384
    assert fitted[-2]["content"].startswith("<tool_call>") and fitted[-1].get("_tool_results")
    assert "characters left out here" in fitted[-1]["content"] and fitted[-1]["content"].startswith("Tool results:")


def test_recall_finds_old_messages_by_rare_words():
    history = [m for m in _long_chat(turns=50, size=50) if m["role"] != "system"]
    hits = cb.search_messages(history, "pelican-7 budget")
    assert hits and "PELICAN-7" in hits[0][1]["content"]
    assert cb.search_messages(history, "") == []


def test_a_reopened_chat_keeps_far_more_than_40_messages(tmp_path):
    from chat_service import ChatService

    store = ChatSessionStore(tmp_path / "chats.json")
    chat_id = store.create("Long")
    for i in range(150):
        store.append("user", f"long question {i}", chat_id=chat_id)
        store.append("assistant", f"long answer {i}", chat_id=chat_id)
    service = ChatService(chat_store=store, chat_id=chat_id)
    contents = [str(m.get("content", "")) for m in service.conversation_history]
    assert "long question 0" in contents and "long answer 149" in contents


def test_the_router_sizes_each_call_to_its_model():
    import router

    class Kimi:
        name = "kimi"
        model = "moonshot-v1-8k"

    class Kahuna:
        name = "identity0"

    history = _long_chat(turns=30, size=2000)
    assert sum(cb._cost(m) for m in router._fit(Kimi(), None, history)) <= 8_000
    assert router._fit(Kahuna(), None, history) is history, "Big Kahuna's member calls are sized instead"


def test_local_context_is_sized_from_the_model_and_the_gpu():
    qwen35 = {"general.architecture": "qwen35", "qwen35.block_count": 32, "qwen35.attention.head_count": 16,
              "qwen35.attention.head_count_kv": [0, 0, 0, 4] * 8, "qwen35.attention.key_length": 256,
              "qwen35.attention.value_length": 256, "qwen35.embedding_length": 4096, "qwen35.context_length": 262144}
    llama = {"general.architecture": "llama", "llama.block_count": 32, "llama.attention.head_count": 32,
             "llama.attention.head_count_kv": 8, "llama.embedding_length": 4096}
    gpu16 = 15.92 * 2 ** 30
    assert ollama_provider.kv_bytes_per_token(qwen35) == 32_768, "only one layer in four keeps a cache"
    assert ollama_provider.fit_ctx(6.59e9, 32_768, 262_144, gpu16) == 196_608, "measured: 100 % on the GPU"
    assert ollama_provider.fit_ctx(4.9e9, ollama_provider.kv_bytes_per_token(llama), 131_072, gpu16) == 65_536
    assert ollama_provider.fit_ctx(6.59e9, 32_768, 32_768, gpu16) == 32_768, "never past what the model was trained on"
