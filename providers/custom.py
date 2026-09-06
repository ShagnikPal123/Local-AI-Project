"""A provider built at runtime from a :class:`provider_specs.ProviderSpec`.

`OpenAICompatibleProvider` already holds everything that is actually hard —
retries, backoff on 429/5xx, error normalisation — and a concrete subclass adds
only four constants. This class supplies those four from a validated spec
instead of from a source file, which is what makes "add your own provider" a
runtime action rather than a release.

The key is the one thing the spec does **not** carry. `provider_specs.json`
records the *name* of the variable; the value is read here, at call time, from
the environment or `secret_store`. That keeps credentials out of a file that is
otherwise safe to read, and it is why adding a key takes effect without a
restart.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

from config import SETTINGS
from provider_specs import ProviderSpec
from providers.base import Provider, ProviderError
from providers.compat import OpenAICompatibleProvider

#: Credentials leak through exception text, not through code anybody reviewed:
#: requests puts the full URL in the message, and an upstream error body can
#: echo the Authorization header back. providers/gemini_provider.py already
#: carries a narrower version of this for its ?key= URLs.
_QUERY_KEY_RE = re.compile(
    r"([?&](?:key|api[-_]?key|access_token|token|secret|password|auth)=)[^&\s\"']+",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{8,}", re.IGNORECASE)

#: Sent when a spec deliberately points at a keyless local gateway. Something
#: has to go in the header, and a placeholder is clearer in a packet capture
#: than an empty credential.
_LOCAL_PLACEHOLDER = "local"


def scrub_secrets(text: Any, *secrets: str) -> str:
    """Redact credentials from text that is about to be shown or logged.

    Removes the literal key values we know about, then the generic shapes we do
    not — a bearer token or a ``?api_key=`` in a URL that came back inside an
    upstream error message.
    """
    cleaned = str(text or "")
    for secret in secrets:
        value = (secret or "").strip()
        if len(value) >= 6:
            cleaned = cleaned.replace(value, "[REDACTED]")
    cleaned = _QUERY_KEY_RE.sub(r"\1[REDACTED]", cleaned)
    cleaned = _BEARER_RE.sub(r"\1[REDACTED]", cleaned)
    return cleaned


def resolve_api_key(api_key_name: str) -> str:
    """Find the value for a named key, newest source first.

    Mirrors the order in ``config.load_settings``: a real environment variable
    beats a stored one, so a key exported for one run does not get shadowed by
    something saved months ago. ``SETTINGS`` is consulted first for the names it
    knows, because a write there (see ``config.reload_keys``) is what makes a
    freshly added key usable without a restart.
    """
    name = (api_key_name or "").strip()
    if not name:
        return ""

    settings_field = name.lower()
    known = getattr(SETTINGS, settings_field, None)
    if isinstance(known, str) and known.strip():
        return known.strip()

    from_env = os.getenv(name, "").strip()
    if from_env:
        return from_env

    try:
        from secret_store import get_keys

        stored = get_keys(name)
    except Exception:
        stored = []
    return (stored[0].strip() if stored else "")


class CustomProvider(OpenAICompatibleProvider):
    """One user-added OpenAI-compatible provider, described by a spec."""

    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec
        self.name = spec.name
        self.chat_url = spec.chat_url
        self.model = spec.model
        # The base class reads its key off a Settings attribute. A custom
        # provider has no such attribute, so _api_key is overridden instead and
        # this stays empty rather than silently pointing at the wrong field.
        self.api_key_field = ""
        self.model_field = ""
        self._TIMEOUT_SECONDS = spec.timeout_seconds

    @property
    def label(self) -> str:
        return self.spec.label

    @property
    def is_free(self) -> bool:
        return self.spec.is_free

    def _api_key(self) -> str:
        if not self.spec.api_key_name:
            return _LOCAL_PLACEHOLDER
        return resolve_api_key(self.spec.api_key_name)

    def last4(self) -> str:
        """Last four characters of the configured key, for the settings UI."""
        if not self.spec.api_key_name:
            return ""
        return key_last4(resolve_api_key(self.spec.api_key_name))

    def chat(self, messages: List[Dict[str, str]]) -> str:
        """Delegate to the compatible base, scrubbing the key from any error."""
        try:
            return super().chat(messages)
        except ProviderError as error:
            raise ProviderError(scrub_secrets(error, self._api_key())) from None


def key_last4(key: str) -> str:
    """Return the last four characters of a key, or '' when there is none.

    The only representation of a credential this app is allowed to return over
    HTTP (AGENTS.md §7). Short keys report nothing rather than most of
    themselves.
    """
    value = (key or "").strip()
    return value[-4:] if len(value) >= 8 else ""


def probe_provider(provider: Provider, timeout_seconds: int = 20) -> Dict[str, Any]:
    """Make one real, minimal call and report whether the provider works.

    ``is_available()`` only asks whether a key is *present*, which is why an
    expired or revoked key looked perfectly healthy right up until a chat failed
    with it. This spends a token to find out the truth.

    Never raises, and never returns the key: every message goes through
    :func:`scrub_secrets` before it leaves.
    """
    key = ""
    try:
        getter = getattr(provider, "_api_key", None)
        if callable(getter):
            key = str(getter() or "")
    except Exception:
        key = ""

    started = time.time()
    try:
        if isinstance(provider, OpenAICompatibleProvider):
            detail = _probe_compatible(provider, key, timeout_seconds)
        else:
            reply = provider.chat([{"role": "user", "content": "ping"}])
            detail = f"replied with {len(str(reply))} characters"
        return {
            "ok": True,
            "provider": provider.name,
            "detail": scrub_secrets(detail, key),
            "latency_ms": round((time.time() - started) * 1000, 1),
        }
    except Exception as error:
        return {
            "ok": False,
            "provider": provider.name,
            "detail": scrub_secrets(f"{type(error).__name__}: {error}", key),
            "latency_ms": round((time.time() - started) * 1000, 1),
        }


def _probe_compatible(
    provider: OpenAICompatibleProvider, key: str, timeout_seconds: int
) -> str:
    """One chat-completions call capped at a single output token.

    Deliberately not ``provider.chat``: that retries three times with backoff,
    which is right for a real turn and wrong for a key test the user is waiting
    on, and it would bill three requests to check one key.
    """
    if not key.strip():
        raise ProviderError("No API key is configured for this provider.")

    response = requests.post(
        provider.chat_url,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json={
            "model": provider._model_name(),
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        },
        timeout=min(timeout_seconds, provider._TIMEOUT_SECONDS),
    )
    if response.status_code >= 400:
        raise ProviderError(
            f"HTTP {response.status_code} from {provider.name}: "
            f"{_short_body(response)}"
        )
    return f"HTTP {response.status_code} from {provider.name}"


def _short_body(response: Any, limit: int = 200) -> str:
    """A trimmed response body for an error message, or a placeholder."""
    try:
        return str(response.text or "")[:limit]
    except Exception:
        return "(no body)"


def build_custom_providers(
    specs: Optional[List[ProviderSpec]] = None,
) -> Dict[str, CustomProvider]:
    """Instantiate every stored spec, skipping any that cannot be built.

    A single unbuildable spec must not stop the router from starting, for the
    same reason a single bad row does not stop the store from loading.
    """
    if specs is None:
        from provider_specs import PROVIDER_SPECS

        specs = PROVIDER_SPECS.list_specs()

    built: Dict[str, CustomProvider] = {}
    for spec in specs:
        try:
            built[spec.name] = CustomProvider(spec)
        except Exception:
            continue
    return built
