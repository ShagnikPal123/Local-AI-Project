"""Turns that outlive their tab: record, follow, reattach, and announce.

The owner asked that chats "run outside of their window and tab". The work
already ran on a thread; what was missing was any way to see it again after the
page that started it went away. These tests pin that behaviour down.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

import turn_registry
from agent_events import BUS
from turn_registry import TurnRegistry, _compact


def test_a_late_viewer_gets_merged_text_then_live_events():
    registry = TurnRegistry()
    registry.start("t1", "chat-a", "hello")
    for piece in ("Hel", "lo ", "there"):
        registry.append("t1", {"type": "answer.delta", "text": piece})

    stream = registry.follow("t1", since=0, heartbeat=0.05)
    first = next(stream)
    assert first == {"type": "answer.delta", "text": "Hello there"}

    registry.append("t1", {"type": "done", "reply": "Hello there", "provider": "test"})
    registry.finish("t1", "done")
    rest = [e for e in stream if e is not None]
    assert rest[-1]["type"] == "done"


def test_follow_ends_when_the_turn_finishes_and_everything_was_sent():
    registry = TurnRegistry()
    registry.start("t2", "chat-a", "x")

    def later():
        time.sleep(0.05)
        registry.append("t2", {"type": "status", "text": "Thinking"})
        registry.append("t2", {"type": "done", "reply": "ok"})
        registry.finish("t2")

    threading.Thread(target=later).start()
    events = [e for e in registry.follow("t2", heartbeat=0.02) if e is not None]
    assert [e["type"] for e in events] == ["status", "done"]


def test_since_skips_events_a_viewer_already_has():
    registry = TurnRegistry()
    registry.start("t3", "c", "x")
    for i in range(5):
        registry.append("t3", {"type": "status", "text": str(i)})
    registry.finish("t3")
    texts = [e["text"] for e in registry.follow("t3", since=3) if e is not None]
    assert texts == ["3", "4"]


def test_summary_tracks_what_is_happening_now():
    registry = TurnRegistry()
    record = registry.start("t4", "chat-b", "plan my week")
    registry.append("t4", {"type": "tool.start", "call_id": "c1", "name": "search_web", "label": "Searching: gyms"})
    assert record.status == "Searching: gyms"
    assert record.tools_running == 1
    registry.append("t4", {"type": "agent.update", "agent_id": "a1", "name": "Planner", "emoji": "P",
                           "status": "working", "step": "Drafting"})
    summary = record.summary()
    assert summary["agents"][0]["name"] == "Planner"
    assert "Planner" in summary["status"]
    registry.append("t4", {"type": "tool.end", "call_id": "c1", "ok": True})
    assert record.tools_running == 0


def test_running_for_chat_finds_only_unfinished_turns():
    registry = TurnRegistry()
    registry.start("done-turn", "chat-c", "a")
    registry.finish("done-turn")
    registry.start("live-turn", "chat-c", "b")
    assert registry.running_for_chat("chat-c").turn_id == "live-turn"
    registry.finish("live-turn")
    assert registry.running_for_chat("chat-c") is None


def test_cancel_sets_the_flag_only_while_running():
    registry = TurnRegistry()
    record = registry.start("t5", "c", "x")
    assert registry.cancel("t5") is True
    assert record.cancel.is_set()
    registry.finish("t5", "stopped")
    assert registry.cancel("t5") is False


def test_state_changes_are_announced_workspace_wide():
    registry = TurnRegistry()
    with BUS.subscribe(["ui"]) as sub:
        registry.start("t6", "chat-d", "x")
        registry.append("t6", {"type": "done", "reply": "fine"})
        registry.finish("t6")
        seen = [e for e in sub.drain() if e.get("type") == "turn.state" and e.get("turn_id") == "t6"]
    assert seen[0]["state"] == "running"
    assert seen[-1]["state"] == "done"
    assert seen[-1]["chat_id"] == "chat-d"


def test_compact_keeps_agent_thoughts_apart():
    merged = _compact([
        {"type": "thought.delta", "text": "a", "agent": "Finance"},
        {"type": "thought.delta", "text": "b", "agent": "Finance"},
        {"type": "thought.delta", "text": "c", "agent": "News"},
    ])
    assert [(e["agent"], e["text"]) for e in merged] == [("Finance", "ab"), ("News", "c")]


# ---------------------------------------------------------------------------
# HTTP: start a turn, leave, come back
# ---------------------------------------------------------------------------


class _FakeService:
    """Stands in for ChatService.chat_turn so no model is called."""

    chat_id = "fake-chat"

    def __init__(self, release: threading.Event):
        self.release = release

    def set_personality(self, _p):
        pass

    def set_turn_context(self, _c):
        pass

    def chat_turn(self, text, *, sink, turn_id, cancel_event, **_kw):
        sink({"type": "turn.start", "chat_id": self.chat_id})
        sink({"type": "answer.delta", "text": "Working on "})
        self.release.wait(5)
        sink({"type": "answer.delta", "text": text})
        sink({"type": "done", "reply": f"Working on {text}", "chat_id": self.chat_id, "turn_id": turn_id})
        return {"stopped": cancel_event.is_set()}


@pytest.fixture()
def client(monkeypatch):
    import server

    release = threading.Event()
    monkeypatch.setattr(server, "_get_service", lambda chat_id=None: _FakeService(release))
    monkeypatch.setattr(turn_registry, "TURNS", TurnRegistry())
    import routes_live

    monkeypatch.setattr(routes_live, "TURNS", turn_registry.TURNS)
    test_client = TestClient(server.app, client=("127.0.0.1", 50001))
    test_client.release = release  # type: ignore[attr-defined]
    return test_client


def _events(response) -> list:
    import json

    return [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]


def test_a_turn_can_be_rejoined_from_another_tab(client):
    import routes_live

    client.release.set()
    with client.stream("POST", "/api/chat/stream", json={"message": "taxes", "use_rag": False}) as response:
        first = _events(response)
    turn_id = first[0]["turn_id"]
    assert first[-1]["type"] == "done"

    listing = client.get("/api/turns").json()["turns"]
    assert any(t["turn_id"] == turn_id and t["state"] == "done" for t in listing)

    with client.stream("GET", f"/api/turns/{turn_id}/stream") as again:
        replay = _events(again)
    assert "".join(e.get("text", "") for e in replay if e["type"] == "answer.delta") == "Working on taxes"
    assert replay[-1]["type"] == "done"
    assert routes_live.TURNS.get(turn_id).state == "done"


def test_a_running_turn_is_reported_for_its_chat(client):
    import json

    turn_ids = []

    def start():
        with client.stream("POST", "/api/chat/stream", json={"message": "slow", "use_rag": False}) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    turn_ids.append(json.loads(line[6:]).get("turn_id"))
                    break

    # TestClient buffers a streamed body until it ends, so the request is left
    # in flight on a thread while this one looks at the chat from "another tab".
    starter = threading.Thread(target=start, daemon=True)
    starter.start()
    running = None
    deadline = time.time() + 4
    while time.time() < deadline and running is None:
        running = client.get("/api/chats/fake-chat/turn").json()["turn"]
        time.sleep(0.05)
    assert running is not None and running["state"] == "running"

    client.release.set()
    starter.join(5)
    deadline = time.time() + 5
    while time.time() < deadline and client.get("/api/chats/fake-chat/turn").json()["turn"] is not None:
        time.sleep(0.05)
    assert client.get("/api/chats/fake-chat/turn").json()["turn"] is None
    assert turn_ids and client.get(f"/api/turns/{turn_ids[0]}").json()["turn"]["state"] == "done"


def test_unknown_turns_are_404(client):
    assert client.get("/api/turns/nope").status_code == 404
    assert client.get("/api/turns/nope/stream").status_code == 404
