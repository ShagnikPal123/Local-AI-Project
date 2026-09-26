"""OpenAI API provider for gpt-4, gpt-4o, and other OpenAI models."""

from __future__ import annotations

import time
from typing import Dict, Iterator, List

import requests

from config import SETTINGS
from providers.base import Provider, ProviderError


class OpenAIProvider(Provider):
    """Access OpenAI models via the official API."""

    name = "openai"
    _CHAT_URL = "https://api.openai.com/v1/chat/completions"
    _MODEL = "gpt-4o"
    _TIMEOUT_SECONDS = 30
    _MAX_RETRIES = 2

    def is_available(self) -> bool:
        """Return whether an OpenAI key is configured."""
        try:
            return isinstance(SETTINGS.openai_api_key, str) and bool(
                SETTINGS.openai_api_key.strip()
            )
        except Exception:
            return False

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Send messages to OpenAI and return the response."""
        if not self.is_available():
            raise ProviderError(
                "OpenAI is unavailable because no API key is configured."
            )

        headers = {
            "Authorization": f"Bearer {SETTINGS.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": self._MODEL, "messages": messages}

        last_error = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                response = requests.post(
                    self._CHAT_URL,
                    headers=headers,
                    json=payload,
                    timeout=self._TIMEOUT_SECONDS,
                )
                from providers.compat import _observe_limits

                _observe_limits("openai", response, self._MODEL)
                if response.status_code in (429, 500, 502, 503) and attempt < self._MAX_RETRIES:
                    time.sleep(1.0 * (2**attempt))
                    continue

                if response.status_code >= 400:
                    from providers.base import FINAL_STATUSES, api_error_detail

                    detail = api_error_detail(response)
                    if response.status_code in FINAL_STATUSES or attempt >= self._MAX_RETRIES:
                        raise ProviderError(f"OpenAI request failed: {detail}")
                    last_error = RuntimeError(detail)
                    continue
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("OpenAI returned a non-text response.")
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

        raise ProviderError(f"OpenAI request failed: {last_error}") from last_error
