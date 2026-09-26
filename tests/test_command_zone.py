"""Command Zone: usage rollups, the approval inbox, dispatch to the team (owner request 2026-09-16)."""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

import command_zone
from chat_sessions import ChatSessionStore


def _turn(ts, chat="c1", provider="gemini", model="flash", message="hello there", reply_chars=400, agents=()):
    return json.dumps({"ts": ts, "chat_id": chat, "provider": provider, "model": model, "message": message,
                       "reply_chars": reply_chars, "agents": list(agents)})


@pytest.fixture()
def world(tmp_path):
    now = time.mktime((2026, 9, 16, 15, 0, 0, 0, 0, -1))
    turns = tmp_path / "turns.jsonl"
    rollup = command_zone.UsageRollup(tmp_path / "usage.json", turns_path=turns, clock=lambda: now)
    return rollup, turns, now


def test_usage_counts_sessions_messages_days_and_peak_hour(world):
    rollup, turns, now = world
    day = 86400
    turns.write_text("\n".join([
        _turn(now - 3600, chat="a"),                       # today 14:00
        _turn(now - 3500, chat="a"),                       # today 14:01
        _turn(now - 2 * day, chat="b", provider="nvidia", model=""),
        _turn(now - 40 * day, chat="c", message="x" * 400, reply_chars=0),
    ]), encoding="utf-8")

    everything = rollup.summary("all")
    assert everything["messages"] == 4 and everything["sessions"] == 3 and everything["active_days"] == 3
    assert everything["peak_hour"] == 14
    assert everything["favorite_model"]["provider"] == "gemini"
    assert everything["favorite_model"]["label"] == "Google Gemini · flash"
    assert everything["tokens_estimated"] is True and everything["tokens"] > 0

    week = rollup.summary("7d")
    assert week["messages"] == 3 and week["sessions"] == 2
    assert {m["provider"] for m in week["models"]} == {"gemini", "nvidia"}
    # The grid always spans the same window, so switching the range never reflows it.
    assert week["daily"] == everything["daily"]


def test_usage_survives_the_turn_log_rotating(world):
    rollup, turns, now = world
    turns.write_text("\n".join(_turn(now - i * 60) for i in range(5)), encoding="utf-8")
    assert rollup.summary()["messages"] == 5
    turns.write_text(_turn(now + 30), encoding="utf-8")  # the learner rotated its log; one newer turn
    assert rollup.summary()["messages"] == 6


def test_agents_are_counted_as_agents_not_models(world):
    rollup, turns, now = world
    turns.write_text("\n".join([
        _turn(now - 10, provider="agent:Coder", model=""),
        _turn(now - 5, agents=["Finance", "Finance"]),
    ]), encoding="utf-8")
    usage = rollup.summary()
    assert [m["provider"] for m in usage["models"]] == ["gemini"]
    assert {a["name"]: a["messages"] for a in usage["agents"]} == {"Coder": 1, "Finance": 1}


def test_book_comparison_reads_naturally():
    assert command_zone.compare_to_books(0) == ""
    assert "% of The Old Man and the Sea" in command_zone.compare_to_books(7_000)
    assert command_zone.compare_to_books(318_000) == "That's about 1.2× the length of Moby-Dick."
    assert command_zone.compare_to_books(19_300_000).endswith("the length of the whole Harry Potter series.")


def test_ideas_merge_duplicates_and_wait_for_the_owner(tmp_path):
    inbox = command_zone.Inbox(tmp_path / "zone.json")
    first = inbox.propose("idea", "Cache GPU prices", "Saves calls", agent="Finance")
    again = inbox.propose("idea", "cache gpu prices", "Refresh hourly", agent="Tech")
    assert first["id"] == again["id"] and "Refresh hourly" in again["detail"]
    assert [i["title"] for i in inbox.pending()] == ["Cache GPU prices"]
    with pytest.raises(ValueError):
        inbox.propose("idea", "   ")
    # It persists.
    assert command_zone.Inbox(tmp_path / "zone.json").pending()[0]["agent"] == "Finance"


def test_approving_an_idea_sends_it_to_the_team():
    item = command_zone.INBOX.propose("idea", "Add a price alert", "When a GPU drops below $300", agent="Finance")
    sent = []
    result = command_zone.resolve(item["id"], True, dispatch=lambda message: sent.append(message) or {"turn_id": "t1"})
    assert result["status"] == "approved" and result["turn_id"] == "t1"
    assert sent == ["Go ahead with this idea (Finance suggested it): Add a price alert\n\nWhen a GPU drops below $300"]
    with pytest.raises(ValueError):
        command_zone.resolve(item["id"], True, dispatch=lambda m: {})


def test_dismiss_then_restore():
    item = command_zone.INBOX.propose("tab", "GPU Prices", "you asked about GPUs 5 times")
    dismissed = command_zone.resolve(item["id"], False, dispatch=lambda m: {})
    assert dismissed["status"] == "dismissed" and command_zone.INBOX.pending() == []
    assert "gpu prices" in command_zone.INBOX.dismissed_tabs()
    restored = command_zone.restore(item["id"])
    assert restored["status"] == "pending" and "gpu prices" not in command_zone.INBOX.dismissed_tabs()


def test_approving_a_tab_builds_it_in_the_background():
    item = command_zone.INBOX.propose("tab", "Reading List", "books you mention")
    built = threading.Event()

    def make_tab(title, detail):
        built.set()
        return f"Created and opened the '{title}' tab."

    result = command_zone.resolve(item["id"], True, dispatch=lambda m: {}, make_tab=make_tab)
    assert result["status"] == "approved"
    assert built.wait(5)
    for _ in range(50):
        if command_zone.INBOX.get(item["id"])["outcome"] != "Making the tab…":
            break
        time.sleep(0.02)
    assert command_zone.INBOX.get(item["id"])["outcome"] == "Made the “Reading List” tab"


def test_predicted_tab_is_offered_until_dismissed(monkeypatch):
    import predictor

    monkeypatch.setattr(predictor.SCHEDULER, "needed_tab", lambda: ("Gpu Prices", "you came back to gpu prices in 4 recent requests"))
    offered = command_zone.predicted_tab()
    assert offered["id"] == "predicted-gpu-prices" and offered["agent"] == "Nyx"
    command_zone.resolve(offered["id"], False, dispatch=lambda m: {})
    assert command_zone.predicted_tab() is None
    assert command_zone.INBOX.recent()[0]["title"] == "Gpu Prices"


def test_the_zone_chat_is_made_quietly_and_gets_the_brief(tmp_path):
    store = ChatSessionStore(tmp_path / "chats.json")
    mine = store.create("Mine")
    zone = command_zone.ensure_chat(store)
    assert zone != mine and store.data["active_chat"] == mine  # the owner stays where they were
    assert command_zone.ensure_chat(store) == zone
    assert command_zone.brief_for_chat(zone).startswith(command_zone.BRIEF_PREFIX)
    assert command_zone.brief_for_chat(mine) == ""
    store.delete(zone)
    assert command_zone.ensure_chat(store) != zone  # deleted → made again


def test_tools_file_ideas_and_tabs():
    assert "Filed" in command_zone.tool_propose_idea("Retry flaky keys", "saw 3 fails", agent="Tech")
    assert "Suggested" in command_zone.tool_suggest_tab("Homework", "for school tasks")
    kinds = sorted(i["kind"] for i in command_zone.INBOX.pending())
    assert kinds == ["idea", "tab"]
    assert command_zone.tool_propose_idea("").startswith("Error")


def test_routes_show_state_and_answer_items(monkeypatch, tmp_path):
    import predictor
    import server
    import server_auth
    from auth import AuthStore

    unclaimed = AuthStore(tmp_path / "auth.json")  # this machine's real install may be claimed
    monkeypatch.setattr(server_auth, "AUTH_STORE", unclaimed)
    monkeypatch.setattr(server, "AUTH_STORE", unclaimed)
    monkeypatch.setattr(predictor.SCHEDULER, "needed_tab", lambda: ("", ""))
    client = TestClient(server.app)
    idea = command_zone.INBOX.propose("idea", "Summarise my notes weekly", agent="Educator")

    state = client.get("/api/command-zone?range=7d")
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["usage"]["range"] == "7d"
    assert [i["id"] for i in body["inbox"]["ideas"]] == [idea["id"]]
    assert body["inbox"]["waiting"] >= 1
    assert client.get("/api/command-zone/glance").json()["waiting"] >= 1

    dismissed = client.post(f"/api/command-zone/items/{idea['id']}", json={"approve": False})
    assert dismissed.status_code == 200 and dismissed.json()["item"]["status"] == "dismissed"
    assert client.post(f"/api/command-zone/items/{idea['id']}", json={"approve": False}).status_code == 409
    assert client.post("/api/command-zone/items/nope", json={"approve": True}).status_code == 404
    assert client.post(f"/api/command-zone/items/{idea['id']}/restore").json()["item"]["status"] == "pending"
    assert client.post("/api/command-zone/send", json={"message": "  "}).status_code == 400
