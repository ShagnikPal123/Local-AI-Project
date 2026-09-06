"""Offline tests for the Perplexity provider."""

from unittest.mock import Mock, patch

import pytest
import requests

from config import SETTINGS
from providers.base import ProviderError
from providers.perplexity_provider import PerplexityProvider


def test_is_available_returns_true_when_api_key_exists(monkeypatch):
    monkeypatch.setattr(SETTINGS, "perplexity_api_key", "test-key")
    assert PerplexityProvider().is_available() is True


def test_is_available_returns_false_when_api_key_is_missing(monkeypatch):
    monkeypatch.setattr(SETTINGS, "perplexity_api_key", "")
    assert PerplexityProvider().is_available() is False


@patch("providers.perplexity_provider.requests.post")
def test_chat_returns_expected_response_text(mock_post, monkeypatch):
    monkeypatch.setattr(SETTINGS, "perplexity_api_key", "test-key")
    mock_post.return_value = Mock(
        json=lambda: {"choices": [{"message": {"content": "Mocked reply"}}]}
    )
    messages = [{"role": "user", "content": "Hello"}]

    assert PerplexityProvider().chat(messages) == "Mocked reply"
    mock_post.assert_called_once_with(
        "https://api.perplexity.ai/v1/sonar",
        headers={"Authorization": "Bearer test-key", "Content-Type": "application/json"},
        json={"model": "sonar", "messages": messages},
        timeout=30,
    )


@patch("providers.perplexity_provider.requests.post", side_effect=requests.Timeout)
def test_chat_raises_provider_error_on_http_failure(mock_post, monkeypatch):
    monkeypatch.setattr(SETTINGS, "perplexity_api_key", "test-key")
    with pytest.raises(ProviderError, match="Perplexity request failed"):
        PerplexityProvider().chat([{"role": "user", "content": "Hello"}])

