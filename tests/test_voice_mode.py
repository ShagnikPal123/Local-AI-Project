"""Hands-free voice turns: what the model is told, and what it is not (Request R11)."""

import threading

import pytest
from fastapi.testclient import TestClient

import routes_live


class _FakeService:
    """Stands in for ChatService so no model is called; records what the turn was told."""

    chat_id = "voice-chat"

    def __init__(self, seen):
        self.seen = seen

    def set_personality(self, p):
        self.seen.append(f"personality={(p or {}).get('system_guidance', '')}")

    def set_turn_context(self, context):
        self.seen.append(context)

    def chat_turn(self, text, *, sink, turn_id, cancel_event, **kw):
        self.seen.append(f"voice={kw.get('voice')}")
        sink({"type": "turn.start", "chat_id": self.chat_id})
        sink({"type": "done", "reply": "ok", "chat_id": self.chat_id, "turn_id": turn_id})
        return {"stopped": False}


@pytest.fixture()
def client(monkeypatch):
    import server
    import turn_registry

    seen: list = []
    monkeypatch.setattr(server, "_get_service", lambda chat_id=None: _FakeService(seen))
    monkeypatch.setattr(turn_registry, "TURNS", turn_registry.TurnRegistry())
    monkeypatch.setattr(routes_live, "TURNS", turn_registry.TURNS)
    test_client = TestClient(server.app, client=("127.0.0.1", 50061))
    test_client.seen = seen  # type: ignore[attr-defined]
    return test_client


def test_a_spoken_turn_is_told_to_answer_like_speech(client):
    with client.stream("POST", "/api/chat/stream", json={"message": "what is the time", "use_rag": False, "voice": True}) as response:
        response.read()
    note = "\n".join(client.seen)
    assert "[Hands-free voice]" in note and "three short sentences" in note
    assert "no markdown" in note and "read aloud" in note


def test_a_typed_turn_is_not(client):
    with client.stream("POST", "/api/chat/stream", json={"message": "what is the time", "use_rag": False}) as response:
        response.read()
    assert "[Hands-free voice]" not in "\n".join(client.seen)


def test_the_voice_note_is_the_only_thing_added(client):
    """It goes in the turn context beside anything the memory added, never into the owner's own words."""
    with client.stream("POST", "/api/chat/stream", json={"message": "hello there", "use_rag": False, "voice": True}) as response:
        events = [line for line in response.iter_lines() if line.startswith("data: ")]
    assert events and "hello there" not in routes_live.VOICE_NOTE


def test_a_spoken_turn_reaches_the_runner_as_voice_and_is_told_not_to_speak_twice(client):
    """The answer is read aloud by the chat; a speak tool call on top made every answer heard twice (Fixer Upper S33)."""
    with client.stream("POST", "/api/chat/stream", json={"message": "what is the time", "use_rag": False, "voice": True}) as response:
        response.read()
    assert "voice=True" in client.seen
    assert "never call the speak tool" in "\n".join(client.seen)


def test_the_speak_tool_says_nothing_on_a_voice_turn_and_still_works_on_a_typed_one(monkeypatch):
    from tool_context import ToolContext, use_context
    from tools import TOOL_REGISTRY

    played = []
    tool = TOOL_REGISTRY.get_tool("speak")
    monkeypatch.setattr(tool, "handler", lambda **kw: played.append(kw.get("text")) or "Spoken.")

    with use_context(ToolContext(voice=True)):
        result = TOOL_REGISTRY.call_tool("speak", text="It is three o'clock.")
    assert played == [] and "read aloud" in result

    with use_context(ToolContext(voice=False)):
        assert TOOL_REGISTRY.call_tool("speak", text="Hello.") == "Spoken."
    assert played == ["Hello."]


def test_a_runner_for_a_spoken_turn_marks_its_tools_as_voice():
    from turn_runner import TurnRunner

    class Service:
        chat_id = "c1"

    spoken = TurnRunner(Service(), "hi", sink=lambda e: None, voice_session="voice-abc")
    typed = TurnRunner(Service(), "hi", sink=lambda e: None)
    assert spoken.context.voice is True and typed.context.voice is False


def test_talking_out_loud_uses_the_avatar_chosen_for_equalize(client, monkeypatch):
    """Spoken turns land in the last chat used; with Equalize's Talk on, its chosen avatar answers (Fixer Upper S34)."""
    import equalize_assistant

    monkeypatch.setattr(equalize_assistant, "voice_personality", lambda: "You are Io. Warm and quick.")
    with client.stream("POST", "/api/chat/stream", json={"message": "hello there", "use_rag": False, "voice": True}) as response:
        response.read()
    assert "personality=You are Io. Warm and quick." in client.seen

    client.seen.clear()
    with client.stream("POST", "/api/chat/stream", json={"message": "hello there", "use_rag": False}) as response:
        response.read()
    assert not any("You are Io" in line for line in client.seen), "typed turns keep the chat's own personality"


def test_equalize_voice_personality_follows_talk_and_the_chosen_source(tmp_path, monkeypatch):
    import equalize_assistant

    monkeypatch.setattr(equalize_assistant, "STORE", tmp_path / "equalize_assistant.json")
    assert equalize_assistant.voice_personality() == ""                 # Talk is off by default
    equalize_assistant.update({"talk": True})
    assert equalize_assistant.voice_personality() == ""                 # normal personality: the chat's own
    equalize_assistant.set_avatar(name="Pip", personality="Cheerful and brief.", keep_personality=True)
    assert equalize_assistant.voice_personality() == "You are Pip. Cheerful and brief."
    equalize_assistant.update({"personality": {"source": "custom", "text": "Talk like a pirate."}})
    assert equalize_assistant.voice_personality() == "Talk like a pirate."
