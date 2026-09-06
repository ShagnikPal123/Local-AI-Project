"""Shared contract for every provider that can answer a chat request."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Iterator, List, Optional


class ProviderError(Exception):
    """Raised when a provider cannot produce a response safely."""


class Provider(ABC):
    """Keep provider implementations interchangeable for the router."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap local availability check that must not raise."""

    @abstractmethod
    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Return a plain-text reply or raise :class:`ProviderError`."""

    def chat_stream(self, messages: List[Dict[str, str]]) -> Iterator[str]:
        """Stream chunks of the response text where supported.

        Default implementation falls back to yielding the entire non-streamed response.
        """
        yield self.chat(messages)
