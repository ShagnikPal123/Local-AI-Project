"""Offline tests for the local Ollama provider."""

from unittest.mock import Mock, patch

import pytest
import requests

from providers.base import ProviderError
from providers.ollama_provider import OllamaProvider


@patch("providers.ollama_provider.requests.get")
def test_is_available_returns_true_for_healthy_server(mock_get):
    mock_get.return_value = Mock()
    assert OllamaProvider().is_available() is True


@patch("providers.ollama_provider.requests.get", side_effect=requests.ConnectionError)
def test_is_available_returns_false_when_server_cannot_be_reached(mock_get):
    assert OllamaProvider().is_available() is False


@patch("providers.ollama_provider.requests.post")
def test_chat_returns_text_from_ollama(mock_post):
    mock_post.return_value = Mock(json=lambda: {"message": {"content": "Local reply"}})
    assert OllamaProvider().chat([{"role": "user", "content": "Hello"}]) == "Local reply"


@patch("providers.ollama_provider.requests.post", side_effect=requests.Timeout)
def test_chat_converts_request_errors_to_provider_error(mock_post):
    with pytest.raises(ProviderError, match="Ollama request failed"):
        OllamaProvider().chat([{"role": "user", "content": "Hello"}])

