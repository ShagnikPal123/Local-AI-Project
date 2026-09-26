"""Anthropic Claude API provider for Claude models."""

from __future__ import annotations

import time
from typing import Dict, Iterator, List

import requests

from config import SETTINGS
from providers.base import Provider, ProviderError


class AnthropicProvider(Provider):
    """Access Anthropic's Claude models via the official API."""

    name = "claude"
    _CHAT_URL = "https://api.anthropic.com/v1/messages"
    _MODEL = "claude-3-5-sonnet-20241022"
    _TIMEOUT_SECONDS = 30
    _MAX_RETRIES = 2

    def is_available(self) -> bool:
        """Return whether an Anthropic key is configured."""
        try:
            return isinstance(SETTINGS.anthropic_api_key, str) and bool(
                SETTINGS.anthropic_api_key.strip()
            )
        except Exception:
            return False

    def _prepare_payload(self, messages: List[Dict[str, str]]) -> tuple[dict, str]:
        """Separate system messages from conversational messages per Anthropic requirements."""
        system_parts = []
        conversation_messages = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
            else:
                conversation_messages.append({"role": role, "content": content})

        if not conversation_messages:
            conversation_messages = [{"role": "user", "content": "Hello"}]

        system_prompt = "\n\n".join(system_parts) if system_parts else ""

        payload = {
            "model": self._MODEL,
            "max_tokens": 2048,
            "messages": conversation_messages,
        }
        if system_prompt:
            payload["system"] = system_prompt

        return payload, system_prompt

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Send messages to Claude and return the response."""
        if not self.is_available():
            raise ProviderError(
                "Claude is unavailable because no API key is configured."
            )

        headers = {
            "x-api-key": SETTINGS.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        payload, _ = self._prepare_payload(messages)

        last_error = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                response = requests.post(
                    self._CHAT_URL,
                    headers=headers,
                    json=payload,
                    timeout=self._TIMEOUT_SECONDS,
                )
                if response.status_code in (429, 503, 529) and attempt < self._MAX_RETRIES:
                    time.sleep(1.0 * (2**attempt))
                    continue

                if response.status_code >= 400:
                    from providers.base import FINAL_STATUSES, api_error_detail

                    detail = api_error_detail(response)
                    if response.status_code in FINAL_STATUSES or attempt >= self._MAX_RETRIES:
                        raise ProviderError(f"Claude request failed: {detail}")
                    last_error = RuntimeError(detail)
                    continue
                data = response.json()
                content = data["content"][0]["text"]
                if not isinstance(content, str):
                    raise ValueError("Claude returned a non-text response.")
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

        raise ProviderError(f"Claude request failed: {last_error}") from last_error
