"""Tests for auto large-prompt compression and server multi-chat."""

from unittest.mock import MagicMock, patch

from chat_service import ChatService
from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Auto large-prompt compression
# ---------------------------------------------------------------------------


def test_large_prompt_auto_compressed_to_file(tmp_path):
    service = ChatService(
        memory_path=str(tmp_path / "large_prompt.json"),
        large_prompt_chars=200,
        enable_tools=True,
    )
    long_input = "This is a very long prompt with lots of detail. " * 20
    with patch.object(service, "_request_response", return_value=("answer", "ollama")) as mock_request:
        response, _ = service.chat(long_input)
    assert response == "answer"
    # The model saw a pointer to the file, not the giant text.
    user_message = [m for m in service.conversation_history if m["role"] == "user"][-1]
    assert "saved to" in user_message["content"]
    assert "Read it with the read_file tool" in user_message["content"]
    # The full text is still persisted in the chat store for fidelity.
    assert any(
        m["role"] == "user" and m["content"] == long_input
        for m in service.chat_store.active_messages()
    )


def test_normal_prompt_not_compressed(tmp_path):
    service = ChatService(memory_path=str(tmp_path / "normal_prompt.json"), large_prompt_chars=500)
    with patch.object(service, "_request_response", return_value=("answer", "ollama")):
        service.chat("short question")
    user_message = [m for m in service.conversation_history if m["role"] == "user"][-1]
    assert user_message["content"] == "short question"


# ---------------------------------------------------------------------------
# Server: concurrent chats & new endpoints
# ---------------------------------------------------------------------------


def test_server_chat_returns_chat_id():
    with patch("server._get_service") as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.chat.return_value = ("reply", "ollama")
        mock_get_svc.return_value = mock_svc
        response = client.post(
            "/api/chat",
            json={"message": "hi", "chat_id": "room-1", "use_rag": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["chat_id"] == "room-1"
        mock_get_svc.assert_called_with("room-1")


def test_server_chat_background_mode_returns_thought_id():
    with patch("server._get_service") as mock_get_svc, patch(
        "thought_loop.start_background_thought"
    ) as mock_start:
        mock_svc = MagicMock()
        mock_get_svc.return_value = mock_svc
        thinker = MagicMock()
        thinker.thought.thought_id = "thought-123"
        mock_start.return_value = thinker

        response = client.post(
            "/api/chat",
            json={"message": "research this", "background": True, "use_rag": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["thought_id"] == "thought-123"
        assert data["provider"] == "background"


def test_server_math_endpoint():
    response = client.post("/api/math", json={"expression": "2x + 3 = 11"})
    assert response.status_code == 200
    data = response.json()
    assert data["kind"] == "equation"
    assert data["solutions"] == ["4"]


def test_server_knowledge_endpoint():
    response = client.get("/api/knowledge", params={"q": "largest ocean"})
    assert response.status_code == 200
    data = response.json()
    assert data["results"]
    assert data["results"][0]["section"] == "Geography"


def test_server_think_endpoints():
    with patch("thought_loop.start_background_thought") as mock_start:
        thinker = MagicMock()
        thinker.thought.thought_id = "think-1"
        thinker.status.return_value = {"thought_id": "think-1", "status": "thinking"}
        mock_start.return_value = thinker

        started = client.post("/api/think", json={"task": "study this", "chat_id": "room-2"})
        assert started.status_code == 200
        assert started.json()["thought_id"] == "think-1"

    with patch("thought_loop.get_thought", return_value=None):
        missing = client.get("/api/think/nope")
        assert missing.status_code == 404
