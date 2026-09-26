"""Big Kahuna's routes for the owner at this PC: overview, settings, companion, voice intents, actions."""

import pytest
from fastapi.testclient import TestClient

import server


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "is_claimed", lambda: False)  # an unclaimed install: loopback is the owner
    return TestClient(server.app, client=("127.0.0.1", 5000))


def test_overview_lists_members_stages_and_the_own_model(client):
    body = client.get("/api/identity0").json()
    assert body["name"] == "Big Kahuna" and body["codename"] == "Identity 0"
    assert "domains" in body and "competence" in body and "own_model" in body


def test_settings_round_trip_and_bad_values_are_refused(client):
    assert client.put("/api/identity0/settings", json={"changes": {"shadow_rate": 0.5}}).json()["settings"]["shadow_rate"] == 0.5
    assert client.put("/api/identity0/settings", json={"changes": {"shadow_rate": 9}}).status_code == 400


def test_voice_intent_opens_early_and_acts_only_on_known_places(client, monkeypatch):
    from identity0 import companion

    opened = []
    monkeypatch.setattr(companion.webbrowser, "open", lambda url, new=2: opened.append(url))
    intent = client.post("/api/identity0/intent", json={"text": "open gmail and", "final": False}).json()
    action = intent["actions"][0]
    assert action["early"] and action["kind"] == "open_url"
    assert client.post("/api/identity0/act", json={"action": action}).json()["ok"]
    assert opened == [companion.GMAIL_INBOX]
    bad = client.post("/api/identity0/act", json={"action": {"kind": "open_url", "url": "https://evil.example"}})
    assert bad.status_code == 400 and len(opened) == 1


def test_an_email_becomes_a_filled_draft_that_is_never_sent(client, monkeypatch):
    from identity0 import companion

    opened = []
    monkeypatch.setattr(companion.webbrowser, "open", lambda url, new=2: opened.append(url))
    monkeypatch.setattr(companion, "draft_email", lambda spoken, to="", router=None: {
        "to": to, "subject": "Running late", "body": "Hi, I'll be ten minutes late."})
    intent = client.post("/api/identity0/intent", json={
        "text": "open gmail and type an email to sam@example.com saying I'll be ten minutes late", "final": True}).json()
    compose = next(a for a in intent["actions"] if a["kind"] == "compose_email")
    result = client.post("/api/identity0/act", json={"action": compose}).json()
    assert result["ok"] and opened[-1].startswith(companion.GMAIL_COMPOSE)
    assert "sam%40example.com" in opened[-1] and "Running%20late" in opened[-1]


def test_companion_chat_keeps_its_own_history(client, monkeypatch):
    from identity0 import companion

    monkeypatch.setattr(companion, "ask", lambda text, router: companion.say("kahuna", f"echo: {text}"))
    client.post("/api/identity0/companion/ask", json={"text": "hello"})
    messages = client.get("/api/identity0/companion").json()["messages"]
    assert messages[-1]["text"] == "echo: hello"
    assert client.delete("/api/identity0/companion").json()["messages"] == []
