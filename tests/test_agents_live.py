"""Agents that visibly update: workspace events, provenance, real roster members.

The owner: "the AI agents, subagents don't update — it doesn't make sense what I
can see." Status changed only inside the turn that ran the agent, agents made in
the Agents tab could never be given work, and nothing recorded where an agent
came from. These tests hold each of those fixed.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

import agent_runtime
from agent_events import BUS
from agent_team import AGENT_TEAM
from tool_context import ToolContext, use_context


@pytest.fixture()
def client():
    import server

    return TestClient(server.app, client=("127.0.0.1", 50002))


@pytest.fixture(autouse=True)
def forget_test_agents():
    """AGENT_TEAM is a process-wide singleton; don't leave test agents in it."""
    yield
    for member in AGENT_TEAM.members():
        if member.name in ("Packing Pro", "Budget Buddy"):
            with AGENT_TEAM._lock:
                AGENT_TEAM._agents.pop(member.agent_id, None)


def _fake_stream(reply: str):
    class _Router:
        def stream(self, history, on_event, **_kw):
            if on_event:
                on_event({"type": "text", "text": reply})
            return reply, "fake"

    return _Router()


def test_agent_updates_reach_the_workspace_channel_with_their_chat(monkeypatch):
    monkeypatch.setattr(agent_runtime, "_router", lambda: _fake_stream("Understood: explain P/E\nThe P/E ratio is price over earnings."))
    turn_events = []
    ctx = ToolContext(turn_id="turn-x", chat_id="chat-42", sink=turn_events.append)
    with BUS.subscribe(["ui"]) as sub, use_context(ctx):
        report = agent_runtime.run_specialist("Finance", "Explain the P/E ratio")
        workspace = [e for e in sub.drain() if e.get("type") == "agent.update"]

    assert "price over earnings" in report
    assert workspace, "agent.update must be published on the ui channel, not only inside the turn"
    assert {e["status"] for e in workspace} >= {"working", "done"}
    assert all(e["chat_id"] == "chat-42" and e["turn_id"] == "turn-x" for e in workspace)
    assert any(e["type"] == "agent.update" for e in turn_events)

    finance = AGENT_TEAM.find("Finance").snapshot()
    assert finance["status"] == "idle"
    assert finance["last_chat_id"] == "chat-42"
    assert finance["tasks_completed"] >= 1


def test_the_owner_sees_exactly_what_an_agent_was_asked_and_what_it_answered(monkeypatch):
    """Update 1, U46: "we the user can see what is asked as well as what they responded with"."""
    long_answer = "Understood: compare two funds\n" + "Fund A beats fund B on fees. " * 40
    monkeypatch.setattr(agent_runtime, "_router", lambda: _fake_stream(long_answer))
    events = []
    ctx = ToolContext(turn_id="turn-u46", chat_id="chat-u46", sink=events.append)
    task = "Compare fund A and fund B on fees, risk and five-year returns. " * 10
    with use_context(ctx):
        agent_runtime.run_specialist("Finance", task, context="The owner holds fund A in an ISA.")
        agent_runtime.run_specialist("Finance", "Now just fees, in one line")

    updates = [e for e in events if e["type"] == "agent.update"]
    asked = [e for e in updates if e.get("step") == "Reading the task"]
    assert asked[0]["task"] == task, "the whole request, not the first 300 characters"
    assert asked[0]["context"] == "The owner holds fund A in an ISA."
    finished = [e for e in updates if e["status"] == "done"]
    assert "Fund A beats fund B on fees." in finished[0]["report"] and len(finished[0]["report"]) > 400
    # Two hand-offs to the same agent are two things to read, not one entry overwritten by the next.
    assert len({e["call_id"] for e in asked}) == 2
    assert {e["call_id"] for e in finished} == {e["call_id"] for e in asked}


def test_an_agent_created_in_chat_remembers_where(monkeypatch):
    events = []
    ctx = ToolContext(turn_id="turn-y", chat_id="trip-chat", sink=events.append)
    with BUS.subscribe(["ui"]) as sub, use_context(ctx):
        message = agent_runtime.tool_create_agent("Packing Pro", "Make packing lists for trips", emoji="P")
        announced = [e for e in sub.drain() if e.get("type") == "agent.created"]

    assert "Created" in message
    assert announced and announced[0]["chat_id"] == "trip-chat"
    assert any(e["type"] == "agent.created" and e["name"] == "Packing Pro" for e in events)
    snapshot = AGENT_TEAM.find("Packing Pro").snapshot()
    assert snapshot["created_in_chat"] == "trip-chat"


def test_agents_made_in_the_panel_can_be_given_work(client, monkeypatch):
    monkeypatch.setattr(agent_runtime, "_router", lambda: _fake_stream("Done: here is the plan."))
    body = client.post("/api/agents", json={"agents": [
        {"name": "Budget Buddy", "goal": "Track my monthly budget", "emoji": "B", "run": True},
    ]}).json()

    assert body["created"][0]["name"] == "Budget Buddy"
    assert body["started"], "run=true must start the agent on its goal"
    turn_id = body["started"][0]["turn_id"]

    deadline = time.time() + 5
    state = "running"
    while time.time() < deadline and state == "running":
        state = client.get(f"/api/turns/{turn_id}").json()["turn"]["state"]
        time.sleep(0.05)
    assert state == "done"

    task = client.post("/api/agents/Budget Buddy/tasks", json={"task": "Summarise last month"}).json()
    assert task["turn_id"]


def test_giving_the_manager_a_task_directly_is_refused(client):
    assert client.post("/api/agents/Manager/tasks", json={"task": "x"}).status_code == 400
    assert client.post("/api/agents/Nobody Here/tasks", json={"task": "x"}).status_code == 404


def test_mentions_pick_out_roster_agents_in_order():
    from turn_runner import mentioned_agents

    assert mentioned_agents("@Finance compare funds, then @WebDesign a page") == ["Finance", "Web Design"]
    assert mentioned_agents("ask @web design and @News") == ["Web Design", "News"]
    assert mentioned_agents("write to a@b.com please") == []
    assert mentioned_agents("no mentions here") == []


def test_agent_properties_edit_a_builtin_as_an_overlay_and_route_its_model(monkeypatch, tmp_path, client):
    """Request G16b: an agent's objective and model are editable, and the model is really used."""
    monkeypatch.setattr(agent_runtime, "_overrides_path", lambda: tmp_path / "agent_overrides.json")
    monkeypatch.setattr(agent_runtime, "_custom_agents_path", lambda: tmp_path / "custom_agents.json")
    with agent_runtime._roster_lock:
        agent_runtime._roster_cache["agents"] = None

    class _Providers:
        providers = {"gemini": object(), "nvidia": object()}

    monkeypatch.setattr(agent_runtime, "_router", lambda: _Providers())
    response = client.patch("/api/agents/Researcher", json={"goal": "Compare laptops", "provider": "NVIDIA",
                                                            "model": "nvidia/nemotron-3-super-120b-a12b"})
    assert response.status_code == 200, response.text
    agent = response.json()["agent"]
    assert (agent["goal"], agent["provider"], agent["edited"]) == ("Compare laptops", "nvidia", True)
    assert "researcher" in (tmp_path / "agent_overrides.json").read_text(encoding="utf-8")

    bad = client.patch("/api/agents/Researcher", json={"provider": "nope"})
    assert bad.status_code == 400 and "Unknown provider" in bad.json()["detail"]
    assert client.get("/api/agents/Researcher/properties").json()["agent"]["model"] == "nvidia/nemotron-3-super-120b-a12b"

    seen = {}

    class _Recorder:
        providers = _Providers.providers

        def stream(self, history, on_event, **kw):
            seen.update(kw)
            return "Understood: compare\nDone.", "nvidia"

    monkeypatch.setattr(agent_runtime, "_router", lambda: _Recorder())
    report = agent_runtime.run_specialist("Researcher", "Compare two laptops")
    assert "Done." in report
    assert seen["prefer"] == "nvidia" and seen["prefer_model"] == "nvidia/nemotron-3-super-120b-a12b"
    with agent_runtime._roster_lock:
        agent_runtime._roster_cache["agents"] = None
