"""Tests for OpenAI and Anthropic providers."""

from unittest.mock import patch, MagicMock

import pytest

from providers.base import ProviderError
from providers.openai_provider import OpenAIProvider
from providers.anthropic_provider import AnthropicProvider


@patch("providers.openai_provider.SETTINGS")
def test_openai_provider_available_with_key(mock_settings):
    """Test that OpenAI is available when API key is set."""
    mock_settings.openai_api_key = "sk-test-key"
    provider = OpenAIProvider()
    assert provider.is_available() is True


@patch("providers.openai_provider.SETTINGS")
def test_openai_provider_unavailable_without_key(mock_settings):
    """Test that OpenAI is unavailable without API key."""
    mock_settings.openai_api_key = ""
    provider = OpenAIProvider()
    assert provider.is_available() is False


@patch("providers.openai_provider.requests.post")
@patch("providers.openai_provider.SETTINGS")
def test_openai_chat_success(mock_settings, mock_post):
    """Test successful OpenAI chat request."""
    mock_settings.openai_api_key = "sk-test-key"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "Hello from OpenAI"}}]
    }
    mock_post.return_value = mock_response

    provider = OpenAIProvider()
    messages = [{"role": "user", "content": "Hello"}]
    response = provider.chat(messages)

    assert response == "Hello from OpenAI"
    mock_post.assert_called_once()


@patch("providers.openai_provider.SETTINGS")
def test_openai_chat_unavailable(mock_settings):
    """Test that chat raises error when provider is unavailable."""
    mock_settings.openai_api_key = ""

    provider = OpenAIProvider()
    messages = [{"role": "user", "content": "Hello"}]

    with pytest.raises(ProviderError):
        provider.chat(messages)


@patch("providers.anthropic_provider.SETTINGS")
def test_anthropic_provider_available_with_key(mock_settings):
    """Test that Anthropic is available when API key is set."""
    mock_settings.anthropic_api_key = "sk-ant-test-key"
    provider = AnthropicProvider()
    assert provider.is_available() is True


@patch("providers.anthropic_provider.SETTINGS")
def test_anthropic_provider_unavailable_without_key(mock_settings):
    """Test that Anthropic is unavailable without API key."""
    mock_settings.anthropic_api_key = ""
    provider = AnthropicProvider()
    assert provider.is_available() is False


@patch("providers.anthropic_provider.requests.post")
@patch("providers.anthropic_provider.SETTINGS")
def test_anthropic_chat_success(mock_settings, mock_post):
    """Test successful Anthropic chat request."""
    mock_settings.anthropic_api_key = "sk-ant-test-key"

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "content": [{"text": "Hello from Claude"}]
    }
    mock_post.return_value = mock_response

    provider = AnthropicProvider()
    messages = [{"role": "user", "content": "Hello"}]
    response = provider.chat(messages)

    assert response == "Hello from Claude"
    mock_post.assert_called_once()


@patch("providers.anthropic_provider.SETTINGS")
def test_anthropic_chat_unavailable(mock_settings):
    """Test that chat raises error when provider is unavailable."""
    mock_settings.anthropic_api_key = ""

    provider = AnthropicProvider()
    messages = [{"role": "user", "content": "Hello"}]

    with pytest.raises(ProviderError):
        provider.chat(messages)
