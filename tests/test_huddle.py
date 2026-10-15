"""Team huddle (WS15): named bots take turns on one business; the owner can post; Slack mirrors only when set."""

import pytest

import huddle


def _team():
    huddle.set_business("Bakery", "Sell bread online")
    huddle.add_member("Maya", "head of sales")
    huddle.add_member("Theo", "baker", runs="local")


def test_each_bot_speaks_in_turn_and_sees_the_goal_and_the_talk_so_far():
    _team()
    huddle.post("Let's plan the first week.")
    prompts = []

    def speaker(member, messages):
        prompts.append((member["name"], messages))
        return f"{member['name']}: I will handle my part."

    said = huddle.run_round(speaker)
    assert [m["author"] for m in said] == ["Maya", "Theo"]
    assert said[0]["text"] == "I will handle my part."  # the name prefix is stripped
    maya_system, maya_user = prompts[0][1][0]["content"], prompts[0][1][1]["content"]
    assert "Sell bread online" in maya_system and "Theo (baker)" in maya_system
    assert "Owner: Let's plan the first week." in maya_user
    assert "Maya: I will handle my part." in prompts[1][1][1]["content"]


def test_one_failing_bot_does_not_stop_the_round():
    _team()

    def speaker(member, messages):
        if member["name"] == "Maya":
            raise RuntimeError("no key")
        return "Bread is in the oven."

    said = huddle.run_round(speaker)
    assert said[0] == {"author": "Maya", "skipped": "no key"} and said[1]["text"] == "Bread is in the oven."


def test_names_are_unique_and_a_round_needs_a_team():
    with pytest.raises(ValueError):
        huddle.run_round(lambda m, msgs: "x")
    huddle.add_member("Maya", "sales")
    with pytest.raises(ValueError):
        huddle.add_member("maya", "again")


def test_slack_mirrors_only_with_a_channel(monkeypatch):
    sent = []
    monkeypatch.setattr(huddle, "_slack_connected", lambda: True)
    import connector_use

    monkeypatch.setattr(connector_use, "call", lambda cid, action, params=None, **kw: sent.append((cid, action, params)))
    huddle.post("hello")
    assert sent == []
    huddle.set_business("Bakery", "", slack_channel="C123")
    huddle.post("hello")
    assert sent == [("slack", "post", {"channel": "C123", "text": "*Owner:* hello"})]


def test_routes(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    client = TestClient(server.app, client=("127.0.0.1", 50123))
    assert client.put("/api/huddle", json={"name": "Shop", "goal": "Sell"}).json()["business"]["name"] == "Shop"
    state = client.post("/api/huddle/members", json={"name": "Ava", "role": "ops"}).json()
    assert state["members"][0]["name"] == "Ava"
    assert client.post("/api/huddle/members", json={"name": ""}).status_code == 400
    monkeypatch.setattr(huddle, "_default_speaker", lambda member, messages: "On it.")
    assert client.post("/api/huddle/round", json={}).json()["messages"][-1]["text"] == "On it."
    assert client.delete("/api/huddle/messages").json()["messages"] == []
