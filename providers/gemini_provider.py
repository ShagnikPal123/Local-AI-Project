"""Google Gemini provider via the native Generative Language REST API."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Iterator, List, Optional

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
    supports_vision = True
    _BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/"
    # gemini-2.0-flash and gemini-2.5-flash are both retired for keys issued after
    # their sunset: generateContent returns 404 "no longer available to new users"
    # even though ListModels still shows them. Keep this current.
    #
    # Measured 2026-08-26 on this key, same prompt:
    #   gemini-flash-lite-latest  0.44s / 0.74s   <- default
    #   gemini-3.6-flash         17.94s / 2.10s   (heavy load, very variable)
    #   gemini-flash-latest      read timeout at 45s (unusable)
    # Re-measured 2026-09-12 (streaming, first token / total):
    #   gemini-flash-lite-latest  1.24s / 1.68s with thought summaries
    #   gemini-3.5-flash          1.81s / 2.48s with thought summaries <- smart default
    #   gemini-3.6-flash          1.88s / 2.83s
    #   gemini-3.8-flash          503 "high demand"
    # Override with GEMINI_MODEL in .env.local when a turn needs more capability.
    _MODEL = "gemini-flash-lite-latest"
    # Kept tight so a stalled provider cascades to the next one quickly rather
    # than holding the whole turn. The router now has a full fallback chain.
    _TIMEOUT_SECONDS = 20
    # Streaming holds the connection open for the whole answer, so the budget is
    # per-read, not per-reply: a long essay is fine, a dead socket is not.
    _STREAM_READ_TIMEOUT_SECONDS = 45
    #: Time to first streamed byte for an optional (smart) model before giving up.
    _OPTIONAL_READ_TIMEOUT_SECONDS = 15
    _MAX_RETRIES = 2
    # Only these are worth retrying. A 404 (retired model) or 401/403 (bad key)
    # will never succeed on a retry, and retrying them was adding ~8s of dead
    # latency to every request before the router gave up.
    _RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504})

    def __init__(self) -> None:
        # Models that rejected a thinkingConfig. Asked once, remembered, so an
        # older model does not pay a failed request on every turn.
        self._no_thinking: set[str] = set()

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

    @staticmethod
    def _parts_for(message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Text plus any inline images/PDFs a message carries."""
        parts: List[Dict[str, Any]] = []
        content = message.get("content", "")
        if content:
            parts.append({"text": content})
        for image in message.get("images") or []:
            data = image.get("data")
            if not data:
                continue
            parts.append({"inlineData": {"mimeType": image.get("mime") or "image/png", "data": data}})
        if not parts:
            parts.append({"text": " "})
        return parts

    def _prepare_payload(self, messages: List[Dict[str, Any]]) -> dict:
        """Convert OpenAI-style messages to Gemini contents (roles: user/model)."""
        system_parts: List[str] = []
        contents: List[Dict] = []
        for msg in messages:
            role = msg.get("role", "user")
            if role == "system":
                system_parts.append(msg.get("content", ""))
                continue
            gemini_role = "model" if role == "assistant" else "user"
            parts = self._parts_for(msg)
            if role == "assistant":
                # The model's own turns never carry media back in.
                parts = [p for p in parts if "text" in p] or [{"text": " "}]
            if contents and contents[-1]["role"] == gemini_role:
                contents[-1]["parts"].extend(parts)
            else:
                contents.append({"role": gemini_role, "parts": parts})

        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

        payload: dict = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
        return payload

    def chat(self, messages: List[Dict[str, Any]], model: Optional[str] = None) -> str:
        """Send messages to Gemini and return the reply text."""
        if not self.is_available():
            raise ProviderError("Gemini is unavailable because no API key is configured.")

        url = self._BASE_URL + (model or self._model_name()) + ":generateContent"
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
                from providers.compat import _observe_limits

                _observe_limits("gemini", response, model or self._model_name())
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
                parts = response.json()["candidates"][0]["content"]["parts"]
                texts = [p.get("text", "") for p in parts if isinstance(p, dict) and not p.get("thought")]
                content = "".join(t for t in texts if isinstance(t, str))
                if not isinstance(content, str) or (not content and not texts):
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

    def stream_events(
        self,
        messages: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        thinking: bool = False,
    ) -> Iterator[Dict[str, str]]:
        """Stream reply text and, when asked, the model's own thought summaries.

        Thought summaries are what let the UI show a real "thought process"
        rather than a canned "Thinking…" — Gemini returns them as parts flagged
        ``thought: true`` when ``includeThoughts`` is set. The thinking budget is
        dynamic, so an easy question costs nothing extra.
        """
        if not self.is_available():
            raise ProviderError("Gemini is unavailable because no API key is configured.")

        model_name = model or self._model_name()
        payload = self._prepare_payload(messages)
        use_thinking = thinking and model_name not in self._no_thinking
        if use_thinking:
            payload["generationConfig"] = {
                "thinkingConfig": {"includeThoughts": True, "thinkingBudget": -1}
            }

        url = self._BASE_URL + model_name + ":streamGenerateContent"
        # A non-default model (the "smart" one) is an optional upgrade with the
        # fast model behind it, so it gets one short try: waiting 45 s × 3 on an
        # overloaded model made simple turns take two minutes before falling back.
        optional = bool(model) and model_name != self._model_name()
        retries = 0 if optional else self._MAX_RETRIES
        read_timeout = self._OPTIONAL_READ_TIMEOUT_SECONDS if optional else self._STREAM_READ_TIMEOUT_SECONDS
        response = None
        for attempt in range(retries + 1):
            try:
                response = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    params={"key": SETTINGS.gemini_api_key, "alt": "sse"},
                    json=payload,
                    timeout=(6 if optional else 10, read_timeout),
                    stream=True,
                )
                self._streamed_counted(response, model_name)
            except requests.RequestException as error:
                if attempt < retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise ProviderError(f"Gemini stream failed: {_scrub_key(str(error))}") from error

            if response.status_code == 400 and use_thinking:
                detail = self._api_error_message(response)
                if "think" in detail.lower():
                    # This model does not do thinking; ask again without it.
                    self._no_thinking.add(model_name)
                    payload.pop("generationConfig", None)
                    use_thinking = False
                    response.close()
                    continue
            if response.status_code in self._RETRYABLE_STATUS and attempt < retries:
                response.close()
                time.sleep(1.0 * (2**attempt))
                continue
            break

        if response is None:  # pragma: no cover - loop always assigns or raises
            raise ProviderError("Gemini stream failed: no response")
        if response.status_code != 200:
            detail = self._api_error_message(response)
            response.close()
            raise ProviderError(f"Gemini request failed: {detail}")

        # SSE responses arrive as text/event-stream without a charset, and
        # requests then decodes them as ISO-8859-1 — which turns every UTF-8
        # apostrophe or emoji into three mojibake characters that are then
        # stored corrupted. Pin the real encoding before any decode.
        response.encoding = "utf-8"

        produced = False
        answered = False
        finish = ""
        try:
            for line in response.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                try:
                    chunk = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                if isinstance(chunk, dict) and chunk.get("error"):
                    message = chunk["error"].get("message", "stream error")
                    raise ProviderError(f"Gemini request failed: {_scrub_key(str(message))[:300]}")
                block = (chunk.get("promptFeedback") or {}).get("blockReason")
                if block:
                    finish = str(block)
                for candidate in (chunk.get("candidates") or [])[:1]:
                    finish = str(candidate.get("finishReason") or finish)
                    for part in (candidate.get("content") or {}).get("parts") or []:
                        text = part.get("text")
                        if not isinstance(text, str) or not text:
                            continue
                        produced = True
                        answered = answered or not part.get("thought")
                        yield {"type": "thought" if part.get("thought") else "text", "text": text}
        except requests.RequestException as error:
            raise ProviderError(f"Gemini stream interrupted: {_scrub_key(str(error))}") from error
        finally:
            response.close()

        if not produced:
            raise ProviderError(f"Gemini returned an empty response{f' ({finish})' if finish else ''}.")
        if not answered:
            # Thoughts but no answer (a long plan cut off, or a malformed call): an
            # error, so the router tries the next provider instead of the turn
            # ending with nothing to show (Request G11).
            raise ProviderError(f"Gemini returned only its reasoning, no answer{f' ({finish})' if finish else ''}.")

    @staticmethod
    def _streamed_counted(response: "requests.Response", model_name: str) -> None:
        """Report the stream's status to the usage bar (a 429 body names the quota hit)."""
        from providers.compat import _observe_limits

        if response.status_code == 429:
            _observe_limits("gemini", response, model_name)  # reads .text — the stream is not used after a 429
        elif response.status_code == 200:
            try:
                import usage_limits

                usage_limits.count_request("gemini", model_name)
            except Exception:  # pragma: no cover
                pass

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
