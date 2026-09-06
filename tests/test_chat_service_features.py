"""Integration tests for ChatService personality, speech, and RAG features."""

from chat_service import ChatService
from personalities import PersonalityNotFoundError

import pytest


def test_chat_service_accepts_personality_id(tmp_path):
    service = ChatService(
        memory_path=str(tmp_path / "memory.json"),
        personality_id="gen_z",
    )
    assert service.get_personality()["id"] == "gen_z"
    # Personality guidance is injected as a system message.
    assert any(
        msg["role"] == "system" and "[Personality:" in msg["content"]
        for msg in service.conversation_history
    )


def test_chat_service_accepts_personality_text(tmp_path):
    service = ChatService(
        memory_path=str(tmp_path / "memory.json"),
        personality_text="Always answer in haiku.",
    )
    assert service.get_personality()["id"] == "custom"
    assert "haiku" in service.get_personality()["system_guidance"]


def test_chat_service_unknown_personality_raises(tmp_path):
    with pytest.raises(PersonalityNotFoundError):
        ChatService(memory_path=str(tmp_path / "memory.json"), personality_id="nope")


def test_set_personality_replaces_previous(tmp_path):
    service = ChatService(memory_path=str(tmp_path / "memory.json"))
    service.set_personality_from_id("gen_z")
    service.set_personality_from_id("concise")
    personality_messages = [
        msg for msg in service.conversation_history
        if msg["role"] == "system" and "[Personality:" in msg["content"]
    ]
    assert len(personality_messages) == 1
    assert "Concise" in personality_messages[0]["content"]


def test_learn_speech_patterns_from_history(tmp_path):
    service = ChatService(memory_path=str(tmp_path / "memory.json"))
    service.add_message("user", "yo that's fire fr no cap")
    service.add_message("user", "bet, let's go")
    result = service.learn_speech_patterns()
    assert "Learned" in result
    assert service.get_speech_patterns()["slang_usage"] == "frequent"


def test_clear_speech_patterns(tmp_path):
    service = ChatService(memory_path=str(tmp_path / "memory.json"))
    service.add_message("user", "yo that's fire fr")
    service.learn_speech_patterns()
    assert service.get_speech_patterns()
    service.clear_speech_patterns()
    assert service.get_speech_patterns() == {}


def test_rag_search_returns_memories(tmp_path):
    service = ChatService(memory_path=str(tmp_path / "memory.json"))
    service.remember_important("favorite color", "The user loves deep blue.")
    results = service.rag_search("favorite color")
    assert results
    assert results[0]["metadata"]["kind"] == "important"


def test_get_status_includes_new_fields(tmp_path):
    service = ChatService(memory_path=str(tmp_path / "memory.json"))
    status = service.get_status()
    assert "personality" in status
    assert "speech_patterns_learned" in status
