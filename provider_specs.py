"""User-added model providers, stored as validated specs (never as code).

`providers/compat.py` is a complete OpenAI-compatible adapter: retries, backoff,
and error normalisation all live there once. A concrete provider adds exactly
four values — a name, an endpoint, a model, and where its key is kept. That
means "support another provider" is a *config row*, not a new Python file, and
the user can add one at runtime without anybody shipping a release.

So this follows the same rule as tabs, widgets, and skills: **a spec is data,
never code** (AGENTS.md invariant 2). Nothing here is executed; the spec is
interpreted by :class:`providers.custom.CustomProvider`.

Two consequences shape the validation below:

* Everything is checked at **write** time. A spec that would fail at request
  time — an http:// endpoint, a name that collides with a built-in — must never
  reach the file, because by then the failure is in front of the user mid-chat.
* A stored spec that is invalid *now* is skipped on load, not fatal. Rules
  tighten over time, and one bad row must not stop the app from starting.

**No key value ever lives in a spec.** A spec records the *name* of the
variable ("CEREBRAS_API_KEY"); the value comes from the environment or
`secret_store`. That keeps provider_specs.json free of credentials even though
it sits next to them.
"""

from __future__ import annotations

import ipaddress
import json
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urlparse, parse_qsl

from paths import data_path


class ProviderSpecError(Exception):
    """Raised when a provider spec is malformed or unsafe."""


#: A provider name is used as a routing key, a URL path segment, and a settings
#: lookup, so it stays boring: lowercase, no spaces, no punctuation surprises.
_NAME_RE = re.compile(r"^[a-z][a-z0-9]{1,30}(?:[-_][a-z0-9]+)*$")
#: Environment-variable style, because that is exactly what it names.
_KEY_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,60}$")
#: Model ids are vendor-shaped: "gpt-4o-mini", "meta-llama/Llama-3.3-70B:free".
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/\-]{0,119}$")

_MAX_LABEL = 60
_MAX_URL = 400
_MAX_SPECS = 40

#: Bounded so a hostile or fat-fingered spec cannot pin a worker forever, and
#: cannot make the fallback chain useless by taking 10 minutes to give up.
_MIN_TIMEOUT = 1
_MAX_TIMEOUT = 120
_DEFAULT_TIMEOUT = 30

_LOCAL_HOSTNAMES = {"localhost", "ip6-localhost", "ip6-loopback"}
_LOCAL_SUFFIXES = (".local", ".internal", ".localhost", ".home.arpa")

#: Query parameters that carry a credential. The Gemini API's ?key= is the
#: reason providers/gemini_provider.py needs _scrub_key at all; a user-supplied
#: endpoint must not be allowed to create that problem a second time.
_CREDENTIAL_QUERY_KEYS = {
    "key", "api_key", "apikey", "api-key", "access_token", "accesstoken",
    "token", "secret", "password", "pwd", "auth", "authorization", "sig",
    "signature",
}


#: The providers that ship with the app. Held here rather than in router.py so
#: the HTTP layer can describe them (and find their key) without importing the
#: router and paying for a device probe.
BUILTIN_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "ollama": {"label": "Ollama (local)", "key_name": "", "settings_field": "", "free": True},
    "gemini": {"label": "Google Gemini", "key_name": "GEMINI_API_KEY",
               "settings_field": "gemini_api_key", "free": True},
    "groq": {"label": "Groq", "key_name": "GROQ_API_KEY",
             "settings_field": "groq_api_key", "free": True},
    "claude": {"label": "Anthropic Claude", "key_name": "ANTHROPIC_API_KEY",
               "settings_field": "anthropic_api_key", "free": False},
    "openai": {"label": "OpenAI", "key_name": "OPENAI_API_KEY",
               "settings_field": "openai_api_key", "free": False},
    "kimi": {"label": "Moonshot Kimi", "key_name": "KIMI_API_KEY",
             "settings_field": "kimi_api_key", "free": False},
    "deepseek": {"label": "DeepSeek", "key_name": "DEEPSEEK_API_KEY",
                 "settings_field": "deepseek_api_key", "free": False},
    "perplexity": {"label": "Perplexity", "key_name": "PERPLEXITY_API_KEY",
                   "settings_field": "perplexity_api_key", "free": False},
}

BUILTIN_NAMES = frozenset(BUILTIN_PROVIDERS)


@dataclass
class ProviderSpec:
    """One OpenAI-compatible provider, described entirely by data.

    ``api_key_name`` is a variable *name*, never a value. Empty is legal only
    for a local endpoint that wants no credential (an Ollama-style gateway).
    """

    name: str
    label: str
    chat_url: str
    model: str
    api_key_name: str
    is_free: bool = False
    added_by: str = ""
    timeout_seconds: int = _DEFAULT_TIMEOUT
    signup_url: str = ""
    #: True when this spec deliberately points at a local endpoint.
    allow_local: bool = False
    notes: str = ""

    def as_dict(self) -> Dict[str, Any]:
        """Serialise for storage and for the API. Contains no credential."""
        return {
            "name": self.name,
            "label": self.label,
            "chat_url": self.chat_url,
            "model": self.model,
            "api_key_name": self.api_key_name,
            "is_free": self.is_free,
            "added_by": self.added_by,
            "timeout_seconds": self.timeout_seconds,
            "signup_url": self.signup_url,
            "allow_local": self.allow_local,
            "notes": self.notes,
        }


# --- validation ------------------------------------------------------------


def _validate_name(name: str) -> str:
    clean = (name or "").strip().lower()
    if not clean:
        raise ProviderSpecError("A provider needs a name.")
    if not _NAME_RE.match(clean):
        raise ProviderSpecError(
            f"Invalid provider name {clean!r}: use lowercase letters, digits, "
            "and single - or _ separators, e.g. 'cerebras' or 'my-gateway'."
        )
    return clean


def _validate_key_name(api_key_name: str, allow_local: bool) -> str:
    clean = (api_key_name or "").strip().upper()
    if not clean:
        if allow_local:
            # A local gateway (Ollama and friends) authenticates nobody.
            return ""
        raise ProviderSpecError(
            "A provider needs the name of the variable holding its API key, "
            "e.g. 'CEREBRAS_API_KEY'. Give the name, not the key itself."
        )
    if not _KEY_NAME_RE.match(clean):
        raise ProviderSpecError(
            f"Invalid key name {clean!r}: use an environment-variable style "
            "name like MISTRAL_API_KEY."
        )
    return clean


def _validate_model(model: str) -> str:
    clean = (model or "").strip()
    if not clean:
        raise ProviderSpecError("A provider needs a model id.")
    if not _MODEL_RE.match(clean):
        raise ProviderSpecError(
            f"Invalid model id {clean!r}: letters, digits and . _ : / - only."
        )
    return clean


def _validate_timeout(timeout_seconds: Any) -> int:
    try:
        value = int(timeout_seconds)
    except (TypeError, ValueError) as error:
        raise ProviderSpecError("Timeout must be a whole number of seconds.") from error
    if not _MIN_TIMEOUT <= value <= _MAX_TIMEOUT:
        raise ProviderSpecError(
            f"Timeout must be between {_MIN_TIMEOUT} and {_MAX_TIMEOUT} seconds."
        )
    return value


def _is_local_host(host: str) -> bool:
    """Whether a hostname resolves to this machine or a private network.

    Name-based, deliberately: a DNS lookup here would be a slow, network-
    dependent step inside validation, and would let a hostile name pass by
    resolving to something public once and something private later. The check
    is a floor, not a sandbox — this refuses the obvious cases.
    """
    lowered = (host or "").strip().lower().strip("[]")
    if not lowered:
        return True
    if lowered in _LOCAL_HOSTNAMES or lowered.endswith(_LOCAL_SUFFIXES):
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
        or address.is_multicast
    )


def _validate_chat_url(chat_url: str, allow_local: bool) -> str:
    """Accept only an https endpoint with no credential baked into it.

    A user-supplied URL is where the interesting failures live. Three of them
    matter enough to refuse outright:

    * **http://** would put a bearer token on the wire in clear text.
    * **user:pass@host** and **?api_key=** put the credential in a string that
      ends up in logs, metrics, and exception messages — the exact hazard that
      forced `_scrub_key` into the Gemini provider.
    * **localhost / private IPs** turn this endpoint into an SSRF primitive
      pointed at the machine's own network, unless the user says explicitly
      that a local endpoint is what they meant.
    """
    clean = (chat_url or "").strip()
    if not clean:
        raise ProviderSpecError("A provider needs a chat endpoint URL.")
    if len(clean) > _MAX_URL:
        raise ProviderSpecError("That endpoint URL is unreasonably long.")

    try:
        parsed = urlparse(clean)
    except ValueError as error:
        raise ProviderSpecError(f"Could not parse the endpoint URL: {error}") from error

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ProviderSpecError(
            f"Endpoint must be an https:// URL, got {scheme or 'no'} scheme."
        )
    if not parsed.hostname:
        raise ProviderSpecError("Endpoint URL has no host.")

    if parsed.username or parsed.password or "@" in (parsed.netloc or ""):
        raise ProviderSpecError(
            "Endpoint URL must not embed credentials. Give the key separately."
        )

    for param, _value in parse_qsl(parsed.query or "", keep_blank_values=True):
        if param.strip().lower() in _CREDENTIAL_QUERY_KEYS:
            raise ProviderSpecError(
                f"Endpoint URL must not carry a credential in the query string "
                f"({param}=...). Give the key separately."
            )

    local = _is_local_host(parsed.hostname)
    if local and not allow_local:
        raise ProviderSpecError(
            f"Endpoint host {parsed.hostname!r} is local or private. Set "
            "'local' if you really are pointing at a server on this machine."
        )
    if scheme != "https" and not local:
        raise ProviderSpecError("Endpoint must be an https:// URL.")
    if not local and allow_local:
        raise ProviderSpecError(
            f"Endpoint host {parsed.hostname!r} is not local, so 'local' does "
            "not apply. Remove it."
        )
    return clean


def _validate_signup_url(signup_url: str) -> str:
    """A signup link is rendered as an anchor, so it must be a plain https URL."""
    clean = (signup_url or "").strip()
    if not clean:
        return ""
    if len(clean) > _MAX_URL:
        raise ProviderSpecError("That signup URL is unreasonably long.")
    parsed = urlparse(clean)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ProviderSpecError("Signup URL must be an https:// link.")
    if parsed.username or parsed.password:
        raise ProviderSpecError("Signup URL must not embed credentials.")
    return clean


def build_spec(
    name: str,
    chat_url: str,
    model: str,
    api_key_name: str = "",
    label: str = "",
    is_free: bool = False,
    added_by: str = "",
    timeout_seconds: Any = _DEFAULT_TIMEOUT,
    signup_url: str = "",
    allow_local: bool = False,
    notes: str = "",
) -> ProviderSpec:
    """Validate raw input into a :class:`ProviderSpec`, or raise.

    Every field is checked here so an invalid spec can never be stored and then
    fail in front of the user during a chat.
    """
    clean_name = _validate_name(name)
    if clean_name in BUILTIN_NAMES:
        raise ProviderSpecError(
            f"{clean_name!r} is already a built-in provider. Add its API key "
            "instead of redefining it."
        )

    clean_label = (label or "").strip()[:_MAX_LABEL] or clean_name
    clean_allow_local = bool(allow_local)

    return ProviderSpec(
        name=clean_name,
        label=clean_label,
        chat_url=_validate_chat_url(chat_url, clean_allow_local),
        model=_validate_model(model),
        api_key_name=_validate_key_name(api_key_name, clean_allow_local),
        is_free=bool(is_free),
        added_by=(added_by or "").strip()[:120],
        timeout_seconds=_validate_timeout(timeout_seconds),
        signup_url=_validate_signup_url(signup_url),
        allow_local=clean_allow_local,
        notes=(notes or "").strip()[:200],
    )


# --- free presets ----------------------------------------------------------
#
# Endpoint, model, and the *name* of the key variable. No keys, obviously.
# These exist so the dropdown can offer a provider the user does not have yet:
# picking one prefills everything except the key, and the signup link is right
# there. Every one of these has a genuinely free tier as of this writing.

def _preset(
    name: str,
    label: str,
    chat_url: str,
    model: str,
    api_key_name: str,
    signup_url: str,
    notes: str = "",
) -> ProviderSpec:
    """Build a preset through the same field validators user input goes through.

    A preset that would be rejected as user input is a bug, and it should fail
    at import — caught by the test suite — rather than at the moment somebody
    picks it out of the dropdown.

    ``build_spec`` is deliberately not reused: it refuses a built-in name, and
    Groq is both a built-in and a preset. A preset for a built-in still earns
    its place in the list because the user needs the signup link and the key
    prompt just the same; they simply do not get a custom spec out of it.
    """
    return ProviderSpec(
        name=_validate_name(name),
        label=(label or "").strip()[:_MAX_LABEL] or name,
        chat_url=_validate_chat_url(chat_url, False),
        model=_validate_model(model),
        api_key_name=_validate_key_name(api_key_name, False),
        is_free=True,
        added_by="preset",
        signup_url=_validate_signup_url(signup_url),
        notes=(notes or "").strip()[:200],
    )


FREE_PRESETS: List[ProviderSpec] = [
    _preset(
        "cerebras", "Cerebras",
        "https://api.cerebras.ai/v1/chat/completions",
        "llama3.1-8b",
        "CEREBRAS_API_KEY",
        "https://cloud.cerebras.ai/",
        "Free tier with a daily token allowance; the fastest of these by far.",
    ),
    _preset(
        "openrouter", "OpenRouter (free models)",
        "https://openrouter.ai/api/v1/chat/completions",
        "meta-llama/llama-3.3-70b-instruct:free",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/keys",
        "Any model id ending in ':free' costs nothing. Rate limited, not billed.",
    ),
    _preset(
        "mistral", "Mistral",
        "https://api.mistral.ai/v1/chat/completions",
        "mistral-small-latest",
        "MISTRAL_API_KEY",
        "https://console.mistral.ai/api-keys/",
        "Free experiment tier; opt in to it when creating the key.",
    ),
    _preset(
        "github-models", "GitHub Models",
        "https://models.github.ai/inference/chat/completions",
        "openai/gpt-4o-mini",
        "GITHUB_MODELS_TOKEN",
        "https://github.com/marketplace/models",
        "Uses a GitHub personal access token with the models scope.",
    ),
    _preset(
        "together", "Together AI",
        "https://api.together.xyz/v1/chat/completions",
        "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free",
        "TOGETHER_API_KEY",
        "https://api.together.ai/settings/api-keys",
        "Models with a '-Free' suffix are served at no cost.",
    ),
    _preset(
        "groq", "Groq",
        "https://api.groq.com/openai/v1/chat/completions",
        "llama-3.3-70b-versatile",
        "GROQ_API_KEY",
        "https://console.groq.com/keys",
        "Already built in — adding a key here just switches it on.",
    ),
]

PRESETS_BY_NAME: Dict[str, ProviderSpec] = {p.name: p for p in FREE_PRESETS}


def get_preset(name: str) -> Optional[ProviderSpec]:
    """Look up a shipped preset by name, case-insensitively."""
    return PRESETS_BY_NAME.get((name or "").strip().lower())


# --- storage ---------------------------------------------------------------


class ProviderSpecStore:
    """User-added provider specs, persisted next to the app's other state."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_path("provider_specs.json")
        self._specs: Dict[str, ProviderSpec] = {}
        self._lock = threading.Lock()
        self._load()

    # --- persistence -------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        for entry in (raw.get("providers") if isinstance(raw, dict) else None) or []:
            try:
                spec = build_spec(
                    name=entry["name"],
                    chat_url=entry["chat_url"],
                    model=entry["model"],
                    api_key_name=entry.get("api_key_name", ""),
                    label=entry.get("label", ""),
                    is_free=entry.get("is_free", False),
                    added_by=entry.get("added_by", ""),
                    timeout_seconds=entry.get("timeout_seconds", _DEFAULT_TIMEOUT),
                    signup_url=entry.get("signup_url", ""),
                    allow_local=entry.get("allow_local", False),
                    notes=entry.get("notes", ""),
                )
            except Exception:
                # Skip an invalid stored provider rather than losing the rest —
                # and rather than taking the whole app down at import time. A
                # spec that was legal under older rules simply disappears
                # instead of breaking startup.
                continue
            self._specs[spec.name] = spec

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"providers": [s.as_dict() for s in self._specs.values()]}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            pass

    # --- reads -------------------------------------------------------------

    def list_specs(self) -> List[ProviderSpec]:
        with self._lock:
            return sorted(self._specs.values(), key=lambda s: s.name)

    def as_dicts(self) -> List[Dict[str, Any]]:
        return [s.as_dict() for s in self.list_specs()]

    def get(self, name: str) -> Optional[ProviderSpec]:
        with self._lock:
            return self._specs.get((name or "").strip().lower())

    def names(self) -> List[str]:
        with self._lock:
            return sorted(self._specs)

    # --- writes ------------------------------------------------------------

    def add(self, spec: ProviderSpec) -> ProviderSpec:
        """Store a validated spec, replacing any earlier one with that name."""
        if not isinstance(spec, ProviderSpec):
            raise ProviderSpecError("add() takes a validated ProviderSpec.")
        with self._lock:
            if spec.name not in self._specs and len(self._specs) >= _MAX_SPECS:
                raise ProviderSpecError(
                    f"At most {_MAX_SPECS} custom providers can be stored."
                )
            self._specs[spec.name] = spec
            self._save()
            return spec

    def remove(self, name: str) -> bool:
        with self._lock:
            existing = self._specs.pop((name or "").strip().lower(), None)
            if existing is None:
                return False
            self._save()
            return True


#: Shared store, mirroring CHANGE_LOG / OVERLAY. Tests monkeypatch this.
PROVIDER_SPECS = ProviderSpecStore()
