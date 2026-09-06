"""Google Gemini provider via the native Generative Language REST API."""

from __future__ import annotations

import re
import time
from typing import Dict, List

import requests

from config import SETTINGS
from providers.base import Provider, ProviderError

# The Generative Language API takes its credential as a URL query parameter, so
# requests embeds the full URL — key included — in every exception message. Those
# messages reach logs, metrics, and saved chat history, so scrub before they escape.
_KEY_QUERY_RE = re.compile(r"([?&]key=)[^&\s]+")


def _scrub_key(text: str) -> str:
    """Redact any API key that a URL-bearing error message carries."""
    return _KEY_QUERY_RE.sub(r"\1[REDACTED]", text or "")


class GeminiProvider(Provider):
    """Access Google Gemini models (flash/pro variants) with system-instruction support."""

    name = "gemini"
    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/"
    # gemini-2.0-flash and gemini-2.5-flash are both retired for keys issued after
    # their sunset: generateContent returns 404 "no longer available to new users"
    # even though ListModels still shows them. Keep this current.
    #
    # Measured 2026-08-26 on this key, same prompt:
    #   gemini-flash-lite-latest  0.44s / 0.74s   <- default
    #   gemini-3.6-flash         17.94s / 2.10s   (heavy load, very variable)
    #   gemini-flash-latest      read timeout at 45s (unusable)
    # Override with GEMINI_MODEL in .env.local when a turn needs more capability.
    _MODEL = "gemini-flash-lite-latest"
    # Kept tight so a stalled provider cascades to the next one quickly rather
    # than holding the whole turn. The router now has a full fallback chain.
    _TIMEOUT_SECONDS = 20
    _MAX_RETRIES = 2
    # Only these are worth retrying. A 404 (retired model) or 401/403 (bad key)
    # will never succeed on a retry, and retrying them was adding ~8s of dead
    # latency to every request before the router gave up.
    _RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

    def _model_name(self) -> str:
        return str(getattr(SETTINGS, "gemini_model", "") or self._MODEL)

    def is_available(self) -> bool:
        """Return whether a Gemini API key is configured, without a network call."""
        try:
            return isinstance(SETTINGS.gemini_api_key, str) and bool(
                SETTINGS.gemini_api_key.strip()
            )
        except Exception:
            return False

    def _prepare_payload(self, messages: List[Dict[str, str]]) -> dict:
        """Convert OpenAI-style messages to Gemini contents (roles: user/model)."""
        system_parts: List[str] = []
        contents: List[Dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
                continue
            gemini_role = "model" if role == "assistant" else "user"
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].append({"text": content})
            else:
                contents.append({"role": gemini_role, "parts": [{"text": content}]})

        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

        payload: dict = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        return payload

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Send messages to Gemini and return the reply text."""
        if not self.is_available():
            raise ProviderError("Gemini is unavailable because no API key is configured.")

        url = self._BASE_URL + self._model_name() + ":generateContent"
        headers = {"Content-Type": "application/json"}
        payload = self._prepare_payload(messages)

        last_error = None
        for attempt in range(self._MAX_RETRIES + 1):
            try:
                response = requests.post(
                    url,
                    headers=headers,
                    params={"key": SETTINGS.gemini_api_key},
                    json=payload,
                    timeout=self._TIMEOUT_SECONDS,
                )
                if (
                    response.status_code in self._RETRYABLE_STATUS
                    and attempt < self._MAX_RETRIES
                ):
                    time.sleep(1.0 * (2**attempt))
                    continue
                try:
                    response.raise_for_status()
                except requests.HTTPError as http_error:
                    # Surface the API's own message, which explains retired models
                    # and bad keys far better than a bare status code — and never
                    # let the key-bearing URL through.
                    raise ProviderError(
                        f"Gemini request failed: {self._api_error_message(response)}"
                    ) from http_error
                content = response.json()["candidates"][0]["content"]["parts"][0]["text"]
                if not isinstance(content, str):
                    raise ValueError("Gemini returned a non-text response.")
                return content
            except ProviderError:
                raise
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

        raise ProviderError(
            f"Gemini request failed: {_scrub_key(str(last_error))}"
        ) from last_error

    @staticmethod
    def _api_error_message(response: "requests.Response") -> str:
        """Pull the human-readable message out of a Gemini error body."""
        try:
            message = response.json().get("error", {}).get("message", "")
            if isinstance(message, str) and message.strip():
                return _scrub_key(message)[:300]
        except Exception:
            pass
        try:
            return _scrub_key(str(response.text))[:300]
        except Exception:
            return "no error detail available"
