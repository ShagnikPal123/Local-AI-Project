"""Agents in boxes (Request J6–J8): /coder [3], parallel copies with their own tasks, auto-matching, Core overview."""

from __future__ import annotations

import threading
import time

import pytest

import agent_dispatch as ad
import agent_match

ROSTER = [
    {"name": "Manager", "role": "master"},
    {"name": "Coder", "emoji": "💻", "role": "worker", "goal": "Ship working code", "expertise": ["Python", "debugging"]},
    {"name": "Web Design", "emoji": "🎨", "role": "worker", "goal": "Beautiful sites", "expertise": ["landing pages", "layout"]},
    {"name": "Price Scout", "emoji": "🏷️", "role": "worker", "goal": "Compare laptop prices across stores",
     "expertise": ["prices", "laptops"], "origin": "user", "made_by": "owner"},
]


@pytest.fixture(autouse=True)
def roster(monkeypatch):
    import agent_runtime

    monkeypatch.setattr(agent_runtime, "load_roster", lambda: [dict(a) for a in ROSTER])
    by_name = {a["name"].lower(): a for a in ROSTER}
    monkeypatch.setattr(agent_runtime, "roster_entry_exact", lambda n: by_name.get((n or "").strip().lower()))
    monkeypatch.setattr(agent_runtime, "roster_entry", lambda n: by_name.get((n or "").strip().lower()))


def names():
    return {ad.agent_slug(a["name"]): a["name"] for a in ROSTER if a["role"] != "master"}


def test_counts_in_brackets_and_each_agent_owns_its_words():
    one = ad.parse_invocations("/coder [3] build the login page", names())
    assert one["invocations"] == [{"agent": "Coder", "slug": "coder", "count": 3, "task": "build the login page"}]
    assert [i["task"] for i in ad.expand(one["invocations"])] == ["build the login page"] * 3

    mixed = ad.parse_invocations("Launch my bakery site /web-design [2] hero and menu pages /coder wire the order form", names())
    assert [(i["agent"], i["count"], i["task"]) for i in mixed["invocations"]] == [
        ("Web Design", 2, "hero and menu pages"), ("Coder", 1, "wire the order form")]

    shared = ad.parse_invocations("Fix every failing test /coder [2]", names())
    assert shared["invocations"][0]["task"] == "Fix every failing test"
    assert ad.parse_invocations("see C:/coder/file.py and /unknown [2]", names())["invocations"] == []
    assert ad.parse_invocations("/coder [99] go", names())["invocations"][0]["count"] == ad.MAX_PER_AGENT


def _registry(runner=None, posted=None, threaded=False):
    return ad.DispatchRegistry(runner=runner or (lambda agent, task, context: f"{agent} did: {task}"), threaded=threaded,
                               poster=lambda chat, text: (posted if posted is not None else []).append((chat, text)),
                               limit_fn=lambda: 3)


def test_each_copy_runs_its_own_task_and_results_land_in_the_chat():
    posted, contexts = [], []

    def runner(agent, task, context):
        contexts.append(context)
        return f"{agent} finished {task}"

    reg = _registry(runner, posted)
    view = reg.start([{"agent": "coder", "task": "login page"}, {"agent": "Coder", "task": "signup page"},
                      {"agent": "Web Design", "task": "hero"}], chat_id="chat-1", project={"name": "Bakery", "path": "C:/sites/bakery"})
    final = reg.get(view["dispatch_id"])
    assert [i["label"] for i in final["instances"]] == ["Coder #1", "Coder #2", "Web Design #1"]
    assert all(i["status"] == "done" for i in final["instances"]) and final["status"] == "done"
    assert final["agents"] == {"Coder": 2, "Web Design": 1}
    assert "Coder #2: signup page" in contexts[0] and "Project: Bakery" in contexts[0], "each copy knows the others' parts"
    assert posted and posted[0][0] == "chat-1" and "2× Coder + Web Design" in posted[0][1]


def test_a_second_box_can_be_added_while_it_runs_and_stop_works():
    gate = threading.Event()
    reg = _registry(lambda agent, task, context: gate.wait(5) and f"ok {task}", threaded=True)
    view = reg.start([{"agent": "Coder", "task": "one"}])
    added = reg.add(view["dispatch_id"], "Coder", "two")
    assert [i["label"] for i in added["instances"]] == ["Coder #1", "Coder #2"]
    gate.set()
    for _ in range(100):
        if reg.get(view["dispatch_id"])["status"] == "done":
            break
        time.sleep(0.02)
    assert reg.get(view["dispatch_id"])["counts"]["done"] == 2
    stopped = reg.stop(reg.start([{"agent": "Coder", "task": "three"}])["dispatch_id"])
    assert stopped["dispatch_id"]


def test_bad_boxes_are_explained():
    reg = _registry()
    with pytest.raises(ad.DispatchError, match="No agent called"):
        reg.start([{"agent": "Nobody", "task": "x"}])
    with pytest.raises(ad.DispatchError, match="Say what"):
        reg.start([{"agent": "Coder", "task": " "}])
    with pytest.raises(ad.DispatchError, match="Manager"):
        reg.start([{"agent": "Manager", "task": "x"}])
    with pytest.raises(ad.DispatchError, match="At most"):
        reg.start([{"agent": "Coder", "task": "x"}] * 9)


def test_the_tool_splits_tasks_and_waits_for_reports(monkeypatch):
    reg = _registry()
    monkeypatch.setattr(ad, "DISPATCHES", reg)
    out = ad.tool_dispatch_agents(agent="Coder", count=2, tasks=["parser", "tests", "docs"])
    assert out.count("Coder #") == 3 and "Coder did: docs" in out
    mixed = ad.tool_dispatch_agents(agents=[{"agent": "Coder", "task": "api"}, {"agent": "Web Design", "task": "page"}])
    assert "Web Design #1" in mixed


def test_every_agent_is_a_slash_command_and_the_brief_asks_for_a_dispatch():
    import commands

    agent_cmds = {c["name"]: c for c in commands.agent_commands()}
    assert set(agent_cmds) == {"coder", "web-design", "price-scout"}
    assert agent_cmds["price-scout"]["made_by"] == "owner" and agent_cmds["coder"]["kind"] == "agent"
    assert any(c["name"] == "coder" for c in commands.all_commands())
    brief = commands.brief_for("Make the shop faster /coder [2] and /price-scout check prices")
    assert brief["found"] == ["coder", "price-scout"]
    assert "2 copies of the Coder agent" in brief["context"] and "dispatch_agents" in brief["context"]


def test_nyx_picks_the_sub_agent_itself_but_not_for_small_talk():
    assert agent_match.match("hi there how are you", ROSTER) == []
    picked = agent_match.match("Compare laptop prices across three stores for me", ROSTER)
    assert picked and picked[0]["name"] == "Price Scout"
    assert agent_match.match("Write a python script to rename my photos by date", ROSTER)[0]["name"] == "Coder"
    assert "Price Scout" in agent_match.brief(picked) and agent_match.brief(picked).startswith(agent_match.PREFIX)


def test_core_overview_and_dispatch_routes(monkeypatch):
    import server
    from fastapi.testclient import TestClient

    reg = _registry()
    monkeypatch.setattr(ad, "DISPATCHES", reg)
    local = TestClient(server.app, client=("127.0.0.1", 50091))
    overview = local.get("/api/core/overview")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert {"machine", "engine", "providers", "agents", "processes", "today"} <= set(body)
    assert any(a["name"] == "Coder" and a["command"] == "/coder" for a in body["agents"])

    parsed = local.post("/api/dispatch/parse", json={"text": "/coder [2] build it"}).json()
    assert [i["agent"] for i in parsed["items"]] == ["Coder", "Coder"]
    started = local.post("/api/dispatch", json={"items": parsed["items"], "chat_id": ""}).json()["dispatch"]
    assert started["agents"] == {"Coder": 2}
    assert local.get(f"/api/dispatch/{started['dispatch_id']}").json()["dispatch"]["status"] == "done"
    assert local.post("/api/dispatch", json={"items": [{"agent": "Nobody", "task": "x"}]}).status_code == 400


def test_each_box_keeps_what_it_was_handed_so_the_owner_can_read_it():
    """Update 1, U46: the owner sees what each copy was asked — its task and the context it got — and its reply."""
    registry = ad.DispatchRegistry(runner=lambda agent, task, context: f"done: {task}", threaded=False,
                                   poster=lambda chat, text: None)
    view = registry.start([{"agent": "Coder", "task": "fix the header"}, {"agent": "Coder", "task": "fix the footer"}],
                          context="The site lives in site/ and uses plain CSS.")
    first, second = view["instances"]
    assert "plain CSS" in first["context"] and "Coder #2: fix the footer" in first["context"]
    assert first["report"] == "done: fix the header" and second["report"] == "done: fix the footer"
