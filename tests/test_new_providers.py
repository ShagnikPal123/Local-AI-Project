"""Tests for the added AI models: DeepSeek, Kimi, Groq, Gemini."""

from unittest.mock import MagicMock, patch

import pytest

from chat_service import ChatService
from providers.base import ProviderError
from providers.deepseek_provider import DeepSeekProvider
from providers.gemini_provider import GeminiProvider
from providers.groq_provider import GroqProvider
from providers.kimi_provider import KimiProvider
from router import Router


# ---------------------------------------------------------------------------
# OpenAI-compatible providers (DeepSeek / Kimi / Groq)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_cls,key_field",
    [
        (DeepSeekProvider, "deepseek_api_key"),
        (KimiProvider, "kimi_api_key"),
        (GroqProvider, "groq_api_key"),
    ],
)
def test_compat_provider_available_with_key(provider_cls, key_field):
    with patch("providers.compat.SETTINGS") as mock_settings:
        setattr(mock_settings, key_field, "test-key")
        provider = provider_cls()
        assert provider.is_available() is True


@pytest.mark.parametrize(
    "provider_cls,key_field",
    [
        (DeepSeekProvider, "deepseek_api_key"),
        (KimiProvider, "kimi_api_key"),
        (GroqProvider, "groq_api_key"),
    ],
)
def test_compat_provider_unavailable_without_key(provider_cls, key_field):
    with patch("providers.compat.SETTINGS") as mock_settings:
        setattr(mock_settings, key_field, "")
        provider = provider_cls()
        assert provider.is_available() is False


@patch("providers.compat.requests.post")
def test_deepseek_chat_success(mock_post):
    with patch("providers.compat.SETTINGS") as mock_settings:
        mock_settings.deepseek_api_key = "sk-test"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello from DeepSeek"}}]
        }
        mock_post.return_value = mock_response

        provider = DeepSeekProvider()
        response = provider.chat([{"role": "user", "content": "Hello"}])
    assert response == "Hello from DeepSeek"
    # The request went to DeepSeek's endpoint.
    assert mock_post.call_args[0][0] == "https://api.deepseek.com/chat/completions"


@patch("providers.compat.SETTINGS")
def test_compat_chat_unavailable_raises(mock_settings):
    mock_settings.deepseek_api_key = ""
    with pytest.raises(ProviderError):
        DeepSeekProvider().chat([{"role": "user", "content": "Hello"}])


# ---------------------------------------------------------------------------
# Gemini (native REST)
# ---------------------------------------------------------------------------


@patch("providers.gemini_provider.SETTINGS")
def test_gemini_available_with_key(mock_settings):
    mock_settings.gemini_api_key = "test-key"
    assert GeminiProvider().is_available() is True


@patch("providers.gemini_provider.SETTINGS")
def test_gemini_unavailable_without_key(mock_settings):
    mock_settings.gemini_api_key = ""
    assert GeminiProvider().is_available() is False


@patch("providers.gemini_provider.requests.post")
def test_gemini_chat_success(mock_post):
    with patch("providers.gemini_provider.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-key"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}}]
        }
        mock_post.return_value = mock_response

        provider = GeminiProvider()
        response = provider.chat([{"role": "user", "content": "Hello"}])
    assert response == "Hello from Gemini"


@patch("providers.gemini_provider.requests.post")
def test_gemini_chat_system_instruction(mock_post):
    with patch("providers.gemini_provider.SETTINGS") as mock_settings:
        mock_settings.gemini_api_key = "test-key"
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}]
        }
        mock_post.return_value = mock_response

        GeminiProvider().chat(
            [
                {"role": "system", "content": "You are a strict assistant."},
                {"role": "user", "content": "Hi"},
            ]
        )
        payload = mock_post.call_args.kwargs["json"]
        assert payload["systemInstruction"]["parts"][0]["text"] == "You are a strict assistant."
        assert payload["contents"][0]["role"] == "user"


# ---------------------------------------------------------------------------
# Router registers the new providers
# ---------------------------------------------------------------------------


def test_router_registers_new_providers():
    with patch("router.is_online", return_value=False), patch(
        "providers.ollama_provider.OllamaProvider.is_available", return_value=False
    ):
        router = Router(web_access=False)
    for name in ("gemini", "kimi", "deepseek", "groq"):
        assert name in router.providers
    status = router.get_status()
    for flag in ("gemini_available", "kimi_available", "deepseek_available", "groq_available"):
        assert flag in status

