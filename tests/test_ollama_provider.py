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


class _StreamResponse(Mock):
    """A streamed response that decodes like requests does.

    With no charset on the Content-Type, requests leaves ``encoding`` at its
    default and iter_lines(decode_unicode=True) then reads the raw UTF-8 bytes
    as ISO-8859-1 — the mojibake bug. A provider must pin ``encoding`` to
    "utf-8" before iterating; this fake yields text decoded per whatever is
    set at that moment, so the test asserts behaviour, not implementation.
    """

    status_code = 200

    def __init__(self, raw: bytes):
        super().__init__()
        self._raw = raw
        self.encoding = None  # requests' default for a charset-less text/* body

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        codec = self.encoding or "iso-8859-1"
        for line in self._raw.split(b"\n"):
            if not line:
                continue
            yield line.decode(codec) if decode_unicode else line

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@patch("providers.ollama_provider.requests.post")
def test_chat_stream_decodes_utf8_not_latin1(mock_post):
    """U+2019 (') must survive the stream as one character, not three."""
    body = ("{\"message\": {\"content\": \"That\u2019s live \U0001f3a7\"}}\n").encode("utf-8")
    mock_post.return_value = _StreamResponse(body)
    chunks = list(OllamaProvider().chat_stream([{"role": "user", "content": "hi"}]))
    assert chunks == ["That\u2019s live \U0001f3a7"]

