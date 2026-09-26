"""Shared base for OpenAI-compatible chat-completions providers.

DeepSeek, Moonshot (Kimi), Groq, and similar services all speak the OpenAI
chat-completions protocol. Subclasses only declare their endpoint, default
model, and settings key — retries, availability, and error normalization live
here once.
"""

from __future__ import annotations

import time
from typing import Dict, List

import requests

from config import SETTINGS
from providers.base import FINAL_STATUSES, Provider, ProviderError, api_error_detail


def _observe_limits(provider: str, response, model: str) -> None:
    """Feed rate-limit headers and quota errors to the usage bar (usage_limits.py)."""
    try:
        import usage_limits

        usage_limits.observe(provider, response, model)
    except Exception:  # pragma: no cover - measuring never breaks a reply
        pass


class OpenAICompatibleProvider(Provider):
    """Base provider for OpenAI-compatible chat-completions APIs."""

    name = "compat"
    chat_url = ""
    model = ""
    api_key_field = ""  # Settings attribute holding the API key
    model_field = ""  # Optional Settings attribute overriding the model
    _TIMEOUT_SECONDS = 30
    _MAX_RETRIES = 2

    def _api_key(self) -> str:
        return str(getattr(SETTINGS, self.api_key_field, "") or "")

    def _model_name(self) -> str:
        if self.model_field:
            override = getattr(SETTINGS, self.model_field, "")
            if override:
                return str(override)
        return self.model

    def is_available(self) -> bool:
        """Return whether the API key is configured, without a network call."""
        return bool(self._api_key().strip())

    def stream_events(self, messages, *, model=None, thinking=False):
        """One reply as a single text event — honouring a per-call model (an agent's own)."""
        yield {"type": "text", "text": self.chat(messages, model=model)}

    def chat(self, messages: List[Dict[str, str]], model: str | None = None) -> str:
        """Send messages to the compatible endpoint and return the reply text."""
        if not self.is_available():
            raise ProviderError(f"{self.name} is unavailable because no API key is configured.")

        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        payload = {"model": (model or "").strip() or self._model_name(), "messages": messages}

        last_error = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                response = requests.post(
                    self.chat_url,
                    headers=headers,
                    json=payload,
                    timeout=self._TIMEOUT_SECONDS,
                )
                _observe_limits(self.name, response, payload["model"])
                if response.status_code in (429, 500, 502, 503) and attempt < self._MAX_RETRIES:
                    time.sleep(1.0 * (2**attempt))
                    continue
                if response.status_code >= 400:
                    detail = api_error_detail(response)
                    if response.status_code in FINAL_STATUSES or attempt >= self._MAX_RETRIES:
                        raise ProviderError(f"{self.name} request failed: {detail}")
                    last_error = RuntimeError(detail)
                    continue
                choice = response.json()["choices"][0]
                message = choice.get("message") or {}
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    return content
                # Reasoning models (Nemotron, DeepSeek R1) can spend the whole reply on
                # reasoning and return no content. An empty "success" ended turns with
                # nothing (Request G11); an error lets the router try the next provider.
                finish = choice.get("finish_reason") or "unknown"
                reasoned = bool(message.get("reasoning_content") or message.get("reasoning"))
                if finish == "length" and "max_tokens" not in payload and attempt < self._MAX_RETRIES:
                    payload["max_tokens"] = 16384
                    continue
                raise ProviderError(
                    f"{self.name} returned no answer text (finish_reason={finish}"
                    f"{', reasoning only' if reasoned else ''})."
                )
            except (
                requests.RequestException,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
            ) as error:
                last_error = error
                if attempt < self._MAX_RETRIES:
                    time.sleep(0.5 * (attempt + 1))
                    continue

        raise ProviderError(f"{self.name} request failed: {last_error}") from last_error
