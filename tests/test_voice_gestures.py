"""Clap: the sounds Nyx answers to, and the line it says when listening starts (N86).

The ear opens without anyone pressing anything, so the rules about *when* it is
open, and the promise that a taught sound is numbers rather than a recording,
are what these tests hold in place.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import voice_gestures


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_gestures, "_path", lambda: tmp_path / "voice_gestures.json")


def a_template(frames: int = 8):
    return [[0.1 * (i % 3), 0.2, 0.05, 0.4, 0.1, 0.02, 0.01, 0.03, 0.02, 0.01, 0.01, 0.01] for i in range(frames)]


def test_two_claps_are_there_from_the_start_and_only_when_you_are_away():
    state = voice_gestures.state()
    clap = next(g for g in state["gestures"] if g["kind"] == "double_clap")
    assert clap["enabled"] is True and clap["action"] == "listen"
    assert set(clap["when"]) <= {"away", "offline", "proto"}
    assert "talk" not in clap["when"], "it should not listen for claps while you are already talking to it"


def test_a_taught_sound_is_a_shape_not_a_recording():
    gesture = voice_gestures.add({"name": "Two knocks", "kind": "taught", "action": "say",
                                  "say": "I hear you.", "template": a_template(200), "when": ["away"]})
    assert len(gesture["template"]) <= voice_gestures.MAX_TEMPLATE_FRAMES
    assert all(len(frame) == voice_gestures.TEMPLATE_WIDTH for frame in gesture["template"])
    # Nothing that could be played back or read: twelve rounded numbers per frame.
    assert all(isinstance(value, float) for frame in gesture["template"] for value in frame)


def test_a_taught_sound_needs_to_have_been_taught():
    with pytest.raises(ValueError) as error:
        voice_gestures.add({"name": "Nothing", "kind": "taught", "action": "say", "template": []})
    assert "three times" in str(error.value)


def test_a_command_gesture_needs_to_know_what_to_do():
    with pytest.raises(ValueError):
        voice_gestures.add({"name": "Knock", "kind": "taught", "action": "command",
                            "template": a_template(), "text": ""})


def test_hearing_one_counts_it_and_says_what_happens_next():
    gesture = voice_gestures.add({"name": "Knock", "kind": "taught", "action": "command", "text": "read my email",
                                  "say": "On it.", "template": a_template(), "when": ["away"]})
    answer = voice_gestures.heard(gesture["id"])
    assert answer["speak"] == "On it." and answer["action"] == "command" and answer["text"] == "read my email"
    assert voice_gestures.state()["gestures"][-1]["heard"] == 1

    with pytest.raises(KeyError):
        voice_gestures.heard("nope")


def test_the_status_gesture_actually_says_something():
    gesture = voice_gestures.add({"name": "Whistle back", "kind": "taught", "action": "status",
                                  "template": a_template(), "when": ["away"]})
    spoken = voice_gestures.heard(gesture["id"])["speak"]
    assert "It's" in spoken and len(spoken) > 6


def test_the_greeting_is_said_every_time_by_default_and_can_be_made_the_owners_own():
    assert voice_gestures.greeting().lower().startswith("nyx here")

    voice_gestures.settings({"greeting": {"text": "Nyx here. Sound's on."}})
    assert voice_gestures.greeting() == "Nyx here. Sound's on."

    voice_gestures.settings({"greeting": {"when": "first"}})
    assert voice_gestures.greeting(first_today=False) == ""
    assert voice_gestures.greeting(first_today=True) == "Nyx here. Sound's on."

    voice_gestures.settings({"greeting": {"enabled": False}})
    assert voice_gestures.greeting(first_today=True) == ""


def test_there_is_a_limit_on_how_many_sounds_can_be_listened_for():
    for index in range(voice_gestures.MAX_GESTURES):
        try:
            voice_gestures.add({"name": f"s{index}", "kind": "taught", "action": "say", "template": a_template()})
        except ValueError:
            break
    with pytest.raises(ValueError):
        voice_gestures.add({"name": "one too many", "kind": "taught", "action": "say", "template": a_template()})


def test_the_routes_are_behind_the_session_once_the_install_is_claimed(tmp_path, monkeypatch):
    """A claimed install refuses a stranger — the same rule as every other /api route."""
    import server
    import server_auth
    from auth import AuthStore

    fresh = AuthStore(tmp_path / "auth.json")
    fresh.bootstrap_owner("shagnikpal@gmail.com")
    fresh.set_password("shagnikpal@gmail.com", "a-long-enough-passphrase")
    monkeypatch.setattr(server_auth, "AUTH_STORE", fresh)
    monkeypatch.setattr(server, "AUTH_STORE", fresh)

    stranger = TestClient(server.app, client=("203.0.113.9", 50011))
    assert stranger.get("/api/voice/gestures").status_code in (401, 403)
    assert stranger.post("/api/voice/gestures", json={"name": "x", "kind": "clap"}).status_code in (401, 403)
    assert stranger.post("/api/voice/gestures/clap2/heard").status_code in (401, 403)
