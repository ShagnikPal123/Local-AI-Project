"""Tests for FastAPI server endpoints and frontend interoperability."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from server import app

client = TestClient(app)


def test_health_endpoint():
    """Verify /api/health returns ok status and capability list."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "chat" in data["capabilities"]


def test_status_endpoint():
    """Verify /api/status returns service status and folders."""
    response = client.get("/api/status")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert "folders" in data


def test_chat_endpoint_with_single_message():
    """Verify /api/chat with a simple string message."""
    with patch("server._get_service") as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.chat.return_value = ("Mocked Assistant Reply", "ollama")
        mock_get_svc.return_value = mock_svc

        response = client.post(
            "/api/chat",
            json={"message": "Hello Nyx", "use_rag": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "Mocked Assistant Reply"
        assert data["provider"] == "ollama"


def test_chat_endpoint_with_messages_array():
    """Verify /api/chat interoperability with frontend messages array."""
    with patch("server._get_service") as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.chat.return_value = ("Frontend Handshake Succeeded", "claude")
        mock_get_svc.return_value = mock_svc

        response = client.post(
            "/api/chat",
            json={
                "messages": [
                    {"id": "msg-1", "role": "user", "content": "How are you?", "time": "12:00"},
                ],
                "model": "qwen2.5-coder:14b",
                "provider": "Ollama · Local",
                "use_rag": False,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["reply"] == "Frontend Handshake Succeeded"


def test_connectors_endpoints():
    """Verify /api/connectors lists all active connectors."""
    response = client.get("/api/connectors")
    assert response.status_code == 200
    data = response.json()
    assert "connectors" in data
    assert len(data["connectors"]) >= 5


def test_doctor_endpoint():
    """Verify /api/doctor returns hardware and connectivity diagnostics."""
    response = client.get("/api/doctor")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "hardware" in data
    assert "connectors" in data


def test_graph_endpoints():
    """Verify /api/graphs/create and /api/graphs/read."""
    create_res = client.post(
        "/api/graphs/create",
        json={
            "nodes": [{"id": "A", "label": "Client"}, {"id": "B", "label": "Backend"}],
            "edges": [{"from": "A", "to": "B", "label": "HTTP"}],
        },
    )
    assert create_res.status_code == 200
    data = create_res.json()
    assert "mermaid" in data
    assert "ascii" in data
