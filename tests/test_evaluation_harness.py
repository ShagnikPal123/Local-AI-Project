"""Evaluation and continuous improvement harness for Nyx Ichos.

This test suite covers routing decisions, offline behavior, search capabilities,
RAG retrieval budgeting, multi-agent synthesis, privacy filters, and safety confirmation gates.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch
import pytest

from providers.base import ProviderError
from router import Router
from memory import MemoryStore
from rag_memory import RagMemory
from web_access import set_enabled as set_web_enabled


@pytest.fixture
def clean_memory_store(tmp_path):
    """Create a temporary MemoryStore."""
    store = MemoryStore(path=tmp_path / "test_eval_memory.json")
    yield store


@patch("router.is_online")
@patch("router.OllamaProvider")
def test_provider_failover_evaluation(mock_ollama_class, mock_online):
    """Evaluate fallback when Ollama is available but fails during chat."""
    mock_online.return_value = True

    # Ollama is available but raises ProviderError when chat is called
    mock_ollama = MagicMock()
    mock_ollama.is_available.return_value = True
    mock_ollama.name = "ollama"
    mock_ollama.chat.side_effect = ProviderError("Ollama failed")
    mock_ollama_class.return_value = mock_ollama

    # Fallback provider succeeds (free-only mode routes fallbacks to Gemini)
    mock_gemini = MagicMock()
    mock_gemini.is_available.return_value = True
    mock_gemini.name = "gemini"
    mock_gemini.chat.return_value = "Fallback response"

    router = Router()
    router.providers["gemini"] = mock_gemini

    response, provider = router.chat([{"role": "user", "content": "hello"}])
    assert provider == "gemini"
    assert response == "Fallback response"


@patch("router.is_online")
def test_offline_behavior_evaluation(mock_online):
    """Evaluate routing behavior when offline."""
    mock_online.return_value = False

    router = Router()
    assert router._online_available() is False


def test_memory_privacy_filter(clean_memory_store):
    """Evaluate that RAG memories containing secrets are scrubbed or rejected."""
    sensitive_content = "My API key is sk-1234567890abcdef and password is password123"
    
    # Try adding memory with secret
    clean_memory_store.remember_important("secret_topic", sensitive_content)
    
    # Check that secrets are scrubbed in the stored memory
    memories = clean_memory_store.get_important()
    for mem in memories:
        content = mem.get("content", "")
        assert "sk-1234567890abcdef" not in content
        assert "password123" not in content


def test_rag_retrieval_budget(clean_memory_store):
    """Evaluate RAG context budget constraint to ensure prompt space is not bloated."""
    for i in range(100):
        clean_memory_store.remember_important(f"Topic {i}", f"Fact number {i} description text.", "user")

    # Retrieve memory using RagMemory
    rag = RagMemory(memory=clean_memory_store)
    results = rag.search(query="Fact", limit=5)
    assert len(results) <= 5
    
    # Check total characters/tokens retrieved
    total_len = sum(len(r.get("text", "")) for r in results)
    assert total_len < 1000  # Stays well within the safe retrieval context budget


def test_multi_agent_synthesis_evaluation():
    """Evaluate that sub-agents plan correctly."""
    from sub_agents import SubAgentCoordinator
    coordinator = SubAgentCoordinator()
    plan = coordinator.plan("research and implement some python code")
    agents = [item["agent"] for item in plan]
    assert "researcher" in agents
    assert "coder" in agents
    assert "reviewer" in agents
