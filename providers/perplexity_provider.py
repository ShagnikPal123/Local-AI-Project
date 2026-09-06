"""Perplexity Sonar provider for the personal local-first AI assistant."""

from __future__ import annotations

import time
from typing import Dict, List

import requests

from config import SETTINGS
from providers.base import Provider, ProviderError


class PerplexityProvider(Provider):
    """Keep Perplexity-specific HTTP details isolated from routing code."""

    name = "perplexity"
    _CHAT_URL = "https://api.perplexity.ai/v1/sonar"
    _MODEL = "sonar"
    _TIMEOUT_SECONDS = 30
    _MAX_RETRIES = 2

    def is_available(self) -> bool:
        """Return whether a Perplexity key is configured without a network call."""
        try:
            return isinstance(SETTINGS.perplexity_api_key, str) and bool(
                SETTINGS.perplexity_api_key.strip()
            )
        except Exception:
            return False

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Send messages to Sonar and normalize expected failures to ProviderError."""
        if not self.is_available():
            raise ProviderError(
                "Perplexity is unavailable because no API key is configured."
            )

        headers = {
            "Authorization": f"Bearer {SETTINGS.perplexity_api_key}",
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
                if response.status_code in (429, 500, 502, 503) and attempt < self._MAX_RETRIES:
                    time.sleep(1.0 * (2**attempt))
                    continue

                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("Perplexity returned a non-text response.")
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

        raise ProviderError(f"Perplexity request failed: {last_error}") from last_error
