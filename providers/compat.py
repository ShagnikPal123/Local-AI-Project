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
from providers.base import Provider, ProviderError


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

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Send messages to the compatible endpoint and return the reply text."""
        if not self.is_available():
            raise ProviderError(f"{self.name} is unavailable because no API key is configured.")

        headers = {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._model_name(), "messages": messages}

        last_error = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                response = requests.post(
                    self.chat_url,
                    headers=headers,
                    json=payload,
                    timeout=self._TIMEOUT_SECONDS,
                )
                if response.status_code in (429, 500, 502, 503) and attempt < self._MAX_RETRIES:
                    time.sleep(1.0 * (2**attempt))
                    continue
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError(f"{self.name} returned a non-text response.")
                return content
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
