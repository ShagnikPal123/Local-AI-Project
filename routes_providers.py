"""HTTP routes for provider configuration (keys, presets, live tests).

Included by ``server.py``'s ``_include_routers()`` alongside the other
capability routers. This is the piece that makes "add your own provider" real
from the interface: without it the Models panel could only *look* at providers,
and an owner with an NVIDIA NIM key from https://build.nvidia.com/models had no
way to hand it to the app short of editing ``.env.local`` by hand.

Gating (mirrors ``routes_access.py``):

* ``GET /api/providers`` uses the chat gate — read-only, every secret already
  masked to ``last4``, and the list itself is what the picker needs to render.
* ``POST /api/providers/{name}/key``, ``.../test`` and ``DELETE`` change the
  machine's configuration, so they are owner actions: admin session once the
  install is claimed, loopback-only before that. A beta tester can already
  *chat* with whatever the owner configured; they may not reconfigure it.

The key is accepted in the request body, stored through ``secret_store``, and
pushed into the live ``SETTINGS`` object by ``config.reload_keys()`` so the
next turn uses it with no restart. It is never returned — the response carries
``last4`` only (AGENTS.md invariant 5).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from provider_specs import BUILTIN_PROVIDERS, FREE_PRESETS, PROVIDER_SPECS
from server_auth import RequireChat

router = APIRouter()


def _require_admin_or_local_owner(request: Request) -> Any:
    """Admin once claimed; loopback-only before that. See module docstring."""
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


class KeyBody(BaseModel):
    api_key: str


def _builtin_provider(name: str) -> Optional[Any]:
    """Instantiate a shipped provider class by its router name, or None."""
    from providers.anthropic_provider import AnthropicProvider
    from providers.deepseek_provider import DeepSeekProvider
    from providers.gemini_provider import GeminiProvider
    from providers.groq_provider import GroqProvider
    from providers.kimi_provider import KimiProvider
    from providers.nvidia_provider import NvidiaProvider
    from providers.ollama_provider import OllamaProvider
    from providers.openai_provider import OpenAIProvider
    from providers.perplexity_provider import PerplexityProvider
    from providers.qwen_provider import QwenProvider

    classes = {
        "claude": AnthropicProvider,
        "openai": OpenAIProvider,
        "gemini": GeminiProvider,
        "kimi": KimiProvider,
        "deepseek": DeepSeekProvider,
        "groq": GroqProvider,
        "nvidia": NvidiaProvider,
        "ollama": OllamaProvider,
        "perplexity": PerplexityProvider,
        "qwen": QwenProvider,
    }
    cls = classes.get(name)
    return cls() if cls else None


def _provider_for(name: str) -> Optional[Any]:
    """A provider object for any known name — built-in first, then custom specs."""
    provider = _builtin_provider(name)
    if provider is not None:
        return provider
    from providers.custom import CustomProvider

    spec = PROVIDER_SPECS.get(name)
    if spec is not None:
        try:
            return CustomProvider(spec)
        except Exception:  # noqa: BLE001 - an unbuildable spec is just absent
            return None
    return None


def _key_last4(key: str) -> str:
    from providers.custom import key_last4

    return key_last4(key)


def _resolve_key(name: str) -> str:
    """The configured key for a provider name, whatever kind it is."""
    provider = _provider_for(name)
    if provider is None:
        return ""
    getter = getattr(provider, "_api_key", None)
    try:
        if callable(getter):
            return str(getter() or "")
    except Exception:  # noqa: BLE001 - a broken resolver means "no key"
        return ""
    # Gemini, OpenAI and Claude read SETTINGS directly and have no _api_key(); the
    # dropdown called Gemini "(no key)" while it was answering (2026-09-15).
    from config import SETTINGS

    attr = {"claude": "anthropic_api_key"}.get(name, f"{name}_api_key")
    return str(getattr(SETTINGS, attr, "") or "")


def _signup_url(name: str) -> str:
    """Where this provider's key comes from, when the app knows one."""
    spec = PROVIDER_SPECS.get(name)
    if spec is not None and spec.signup_url:
        return spec.signup_url
    return str(BUILTIN_PROVIDERS.get(name, {}).get("signup_url", "") or "")


def _provider_entry(name: str) -> Optional[Dict[str, Any]]:
    provider = _provider_for(name)
    if provider is None:
        return None
    key = _resolve_key(name)
    label = str(BUILTIN_PROVIDERS.get(name, {}).get("label", "") or "") or name
    is_free = bool(BUILTIN_PROVIDERS.get(name, {}).get("free", False))
    if not label or label == name:
        spec = PROVIDER_SPECS.get(name)
        if spec is not None:
            label = spec.label
            is_free = spec.is_free
    model = getattr(provider, "_model_name", lambda: "")()
    return {
        "name": name,
        "label": label,
        "configured": bool(key.strip()),
        "last4": _key_last4(key),
        "model": model,
        "free": is_free,
        "signup_url": _signup_url(name),
        "builtin": name in BUILTIN_PROVIDERS,
    }


@router.get("/api/providers")
def list_providers(user=RequireChat) -> Dict[str, Any]:
    """Every provider the app can chat with, plus the free presets worth adding.

    Read-only and secret-free: keys appear as ``last4`` or not at all. The
    presets are the free tiers a user can sign up for in one click — NVIDIA NIM
    (build.nvidia.com/models) among them — filtered to names not already listed.
    """
    names = set(BUILTIN_PROVIDERS) | set(PROVIDER_SPECS.names())
    providers: List[Dict[str, Any]] = []
    try:
        # Big Kahuna (Request S) leads the list: it is the main brain that picks among the rest.
        from identity0 import NAME, CODENAME
        from identity0.state import get_settings

        providers.append({"name": "identity0", "label": NAME, "configured": bool(get_settings().get("enabled")),
                          "last4": "", "model": CODENAME, "free": True, "signup_url": "", "builtin": True})
    except Exception:  # pragma: no cover - the list works without it
        pass
    for name in sorted(names):
        entry = _provider_entry(name)
        if entry is not None:
            providers.append(entry)

    listed = {p["name"] for p in providers}
    presets = [
        {
            "name": p.name,
            "label": p.label,
            "model": p.model,
            "signup_url": p.signup_url,
            "notes": p.notes,
        }
        for p in FREE_PRESETS
        if p.name not in listed
    ]
    from config import SETTINGS

    return {
        "providers": providers,
        "presets": presets,
        "preferred": SETTINGS.preferred_online_provider,
        "free_only": SETTINGS.free_only,
    }


@router.post("/api/providers/{name}/key")
def add_provider_key(
    name: str, body: KeyBody, _admin=Depends(_require_admin_or_local_owner)
) -> Dict[str, Any]:
    """Store an API key for a known provider (built-in or user-added).

    Accepts the key once, stores it in ``secret_store`` (OS keyring, falling
    back to ``.secrets.json``), and refreshes the live settings object so the
    next turn — not the next restart — uses it. The response masks the key.
    """
    target = (name or "").strip().lower()
    if target not in BUILTIN_PROVIDERS and PROVIDER_SPECS.get(target) is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{target}'.")

    key = (body.api_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty.")
    if len(key) < 8:
        raise HTTPException(status_code=400, detail="That key is too short to be real.")

    key_name = BUILTIN_PROVIDERS.get(target, {}).get("key_name", "")
    if not key_name:
        spec = PROVIDER_SPECS.get(target)
        key_name = spec.api_key_name if spec else ""
    if not key_name:
        raise HTTPException(
            status_code=400,
            detail=f"{target} runs locally and needs no API key.",
        )

    from secret_store import add_key

    stored = add_key(key_name, key)

    changed: List[str] = []
    try:
        from config import reload_keys

        changed = reload_keys()
    except Exception:  # noqa: BLE001 - settings refresh must not fail the save
        pass

    return {
        "provider": target,
        "key_name": key_name,
        "stored": len(stored) > 0,
        "last4": _key_last4(key),
        "applied_live": bool(changed),
        # Never the key itself — not here, not in an error, not in a log.
        "masked": f"•••• {_key_last4(key)}" if _key_last4(key) else "stored",
    }


@router.post("/api/providers/{name}/test")
def test_provider(
    name: str, _admin=Depends(_require_admin_or_local_owner)
) -> Dict[str, Any]:
    """One real, minimal call against the provider. Spends at most a token."""
    provider = _provider_for(name)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{name}'.")
    if not provider.is_available():
        return {
            "ok": False,
            "provider": name,
            "detail": "No API key is configured for this provider yet.",
        }

    from providers.custom import probe_provider

    # probe_provider never raises and already scrubs the key from its detail.
    return probe_provider(provider)


@router.delete("/api/providers/{name}/key")
def remove_provider_key(
    name: str, _admin=Depends(_require_admin_or_local_owner)
) -> Dict[str, Any]:
    """Forget a provider's stored key(s). The provider stays listed, keyless."""
    target = (name or "").strip().lower()
    key_name = BUILTIN_PROVIDERS.get(target, {}).get("key_name", "")
    if not key_name:
        spec = PROVIDER_SPECS.get(target)
        key_name = spec.api_key_name if spec else ""
    if not key_name:
        raise HTTPException(status_code=400, detail=f"{target} has no removable key.")

    from secret_store import set_keys

    set_keys(key_name, [])

    changed: List[str] = []
    try:
        from config import reload_keys

        changed = reload_keys()
    except Exception:  # noqa: BLE001
        pass
    return {"provider": target, "key_name": key_name, "removed": True, "applied_live": bool(changed)}
