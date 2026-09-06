"""Local Ollama provider used as Nyx Ichos's offline-first default."""

from __future__ import annotations

import json
import time
from typing import Dict, Iterator, List, Optional, Tuple

import requests

from config import SETTINGS
from providers.base import Provider, ProviderError


class OllamaProvider(Provider):
    """Talk to a locally running Ollama server through its HTTP API."""

    name = "ollama"
    _TIMEOUT_SECONDS = 30
    # A loopback health check. A running Ollama answers in milliseconds; when it
    # is absent the probe costs whatever budget it is given, on every request
    # from anyone without Ollama installed.
    #
    # The trap here is that the timeout applies *per resolved address*, and
    # "localhost" resolves to both ::1 and 127.0.0.1 — so the real cost is double
    # the number written here. That is why the original 5s behaved like ~4s, and
    # why lowering it to 1s still measured 2s. `_probe_url` now pins the IPv4
    # loopback so exactly one address is tried and this budget means what it says.
    _PROBE_TIMEOUT_SECONDS = 0.5
    # Availability barely changes within a turn, and the router asks more than
    # once. Cache briefly so a cold local service costs one probe, not several.
    _AVAILABILITY_TTL_SECONDS = 30.0

    def __init__(self) -> None:
        self._availability_cache: Optional[Tuple[float, bool]] = None

    def reset_availability_cache(self) -> None:
        """Forget the cached probe result, forcing the next check to hit the network."""
        self._availability_cache = None

    @staticmethod
    def _probe_url(path: str) -> str:
        """Build a probe URL that resolves to exactly one address.

        `localhost` resolves to ::1 *and* 127.0.0.1, and requests tries each in
        turn — so any timeout is silently doubled when the service is absent.
        Pinning the IPv4 loopback keeps the budget honest. Ollama binds
        127.0.0.1 by default, so this is also where it actually listens.
        """
        host = SETTINGS.ollama_host or "http://127.0.0.1:11434"
        return f"{host.replace('//localhost:', '//127.0.0.1:')}{path}"

    def is_available(self) -> bool:
        """Check the local service without allowing network errors to escape."""
        cached = self._availability_cache
        if cached is not None and (time.monotonic() - cached[0]) < self._AVAILABILITY_TTL_SECONDS:
            return cached[1]

        try:
            response = requests.get(
                self._probe_url('/api/tags'),
                timeout=self._PROBE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            available = True
        except requests.RequestException:
            available = False

        self._availability_cache = (time.monotonic(), available)
        return available

    def is_model_installed(self, model_name: str | None = None) -> bool:
        """Verify the configured model is present on the local Ollama instance.

        Reuses `list_models`, so it inherits the same short-circuit rather than
        paying its own timeout against a server that is already known to be down.
        """
        target_model = model_name or SETTINGS.ollama_model
        return any(target_model in name for name in self.list_models())

    def list_models(self) -> list[str]:
        """Return the names of models currently installed on the local Ollama server.

        Short-circuits when the server is known to be down. Without this the call
        paid a full timeout against a dead loopback port on every request — the
        same defect fixed in `is_available()`, which made `/api/models` take four
        seconds for anyone without Ollama installed.
        """
        if not self.is_available():
            return []
        try:
            response = requests.get(
                self._probe_url('/api/tags'),
                timeout=self._PROBE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return [m.get("name", "") for m in response.json().get("models", [])]
        except requests.RequestException:
            return []

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Send a non-streaming chat request to the configured local model."""
        try:
            response = requests.post(
                f"{SETTINGS.ollama_host}/api/chat",
                json={
                    "model": SETTINGS.ollama_model,
                    "messages": messages,
                    "stream": False,
                },
                timeout=self._TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            content = response.json()["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Ollama returned a non-text response.")
            return content
        except (requests.RequestException, KeyError, TypeError, ValueError) as error:
            raise ProviderError(f"Ollama request failed: {error}") from error

    def chat_stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        """Stream chunks of the chat response from Ollama in real-time."""
        try:
            with requests.post(
                f"{SETTINGS.ollama_host}/api/chat",
                json={
                    "model": SETTINGS.ollama_model,
                    "messages": messages,
                    "stream": True,
                },
                timeout=self._TIMEOUT_SECONDS,
                stream=True,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if line:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
        except Exception as error:
            raise ProviderError(f"Ollama stream failed: {error}") from error
