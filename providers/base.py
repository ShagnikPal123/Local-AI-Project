"""Shared contract for every provider that can answer a chat request."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterator, List, Optional


class ProviderError(Exception):
    """Raised when a provider cannot produce a response safely."""


class Provider(ABC):
    """Keep provider implementations interchangeable for the router."""

    name: str = "base"
    #: Whether this provider can look at images attached to messages. A message
    #: may carry ``images: [{"mime", "data" (base64), "name"}]``; providers that
    #: cannot see them get a text note instead, so nothing crashes and the model
    #: can at least say it was sent a picture it cannot view.
    supports_vision: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        """Cheap local availability check that must not raise."""

    @abstractmethod
    def chat(self, messages: List[Dict[str, Any]]) -> str:
        """Return a plain-text reply or raise :class:`ProviderError`."""

    def chat_stream(self, messages: List[Dict[str, Any]]) -> Iterator[str]:
        """Stream chunks of the response text where supported.

        Default implementation falls back to yielding the entire non-streamed response.
        """
        yield self.chat(messages)

    def stream_events(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        thinking: bool = False,
    ) -> Iterator[Dict[str, str]]:
        """Yield ``{"type": "text" | "thought", "text": ...}`` as the reply forms.

        The default wraps ``chat_stream`` so every provider streams *something*;
        providers with real token streaming or visible reasoning override it.
        ``model`` and ``thinking`` are hints a provider may ignore.
        """
        for chunk in self.chat_stream(messages):
            if chunk:
                yield {"type": "text", "text": chunk}


#: Statuses that will not get better by asking again (bad key, payment, bad request).
FINAL_STATUSES = (400, 401, 402, 403, 404)


def api_error_detail(response: Any, limit: int = 300) -> str:
    """``HTTP 402: Insufficient Balance`` — the status plus the API's own message, never a key.

    ``raise_for_status()`` alone gave "402 Client Error: Payment Required for url", which hid
    whether a key was out of credit, invalid, or rate limited (Request H11).
    """
    import re

    status = getattr(response, "status_code", "?")
    message = ""
    try:
        body = response.json()
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict):
            parts = [str(error.get(k) or "") for k in ("code", "type", "message")]
            message = " ".join(p for p in parts if p)
        elif isinstance(error, str):
            message = error
        if not message and isinstance(body, dict):
            message = str(body.get("message") or body.get("detail") or "")
    except Exception:
        try:
            message = str(getattr(response, "text", "") or "")
        except Exception:
            message = ""
    message = re.sub(r"(key=|bearer\s+|sk-)[^\s&\"']+", r"\1[key]", message, flags=re.IGNORECASE)
    return f"HTTP {status}: {message.strip()[:limit] or 'no detail'}"


def image_note(images: List[Dict[str, Any]]) -> str:
    """Placeholder text for images sent to a provider that cannot see them."""
    names = ", ".join(str(i.get("name") or i.get("mime") or "image") for i in images)
    return f"[{len(images)} image(s) attached ({names}) — this model cannot view images]"
