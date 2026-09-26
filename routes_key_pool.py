"""Keys & Models, Request H8: several keys per provider, failing-key alerts, and models you add yourself.

"In keys and models allow me to add a model for api key and I can type name, company, and api key,
as well as special use ... allow me to add multiple api keys for one so if one fails it can be stored
as failed and can be retried every 5 attempts or so while the other ones are stored as working. Then
the user is alerted after a while that it failed and asks if it can disregard only the one that
doesn't work."

Every route here changes or reveals the machine's configuration, so all of them are owner actions
(owner/admin session, or loopback before the install is claimed). Keys go in once and come back only
as ``last4`` and a fingerprint (AGENTS.md invariant 5). The failover itself lives in ``key_pool`` and
the router.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


Owner = Depends(_owner)


def _apply_live() -> None:
    try:
        from config import reload_keys

        reload_keys()
    except Exception:
        pass
    try:
        from agent_events import publish_ui

        publish_ui("keys.changed")
    except Exception:
        pass


class KeyBody(BaseModel):
    api_key: str


class AlertAnswer(BaseModel):
    action: str


@router.get("/api/keys/{provider}/pool")
def key_list(provider: str, _owner_user=Owner) -> Dict[str, Any]:
    import key_pool

    summary = key_pool.summary(provider.strip().lower())
    if not summary["key_name"]:
        raise HTTPException(status_code=404, detail=f"{provider} has no API key setting.")
    return summary


@router.post("/api/keys/{provider}/pool")
def add_pool_key(provider: str, body: KeyBody, _owner_user=Owner) -> Dict[str, Any]:
    """Add another key for a provider. Nyx fails over to it when the one in use stops working."""
    import key_pool
    from secret_store import add_key

    name = provider.strip().lower()
    key_name = key_pool.key_name_for(name)
    if not key_name:
        raise HTTPException(status_code=404, detail=f"{provider} has no API key setting.")
    key = (body.api_key or "").strip()
    if len(key) < 8:
        raise HTTPException(status_code=400, detail="That key looks too short to be real.")
    if any(item["key"] == key for item in key_pool.all_keys(key_name)):
        raise HTTPException(status_code=409, detail="That key is already saved for this provider.")
    add_key(key_name, key)
    _apply_live()
    return key_pool.summary(name)


@router.delete("/api/keys/{provider}/pool/{fingerprint}")
def remove_pool_key(provider: str, fingerprint: str, _owner_user=Owner) -> Dict[str, Any]:
    """Remove exactly one key; the provider's other keys stay."""
    import key_pool

    name = provider.strip().lower()
    try:
        key_pool.resolve(key_pool.key_name_for(name), fingerprint, "drop")
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'\"")) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _apply_live()
    return key_pool.summary(name)


@router.get("/api/keys/alerts")
def key_alerts(_owner_user=Owner) -> Dict[str, Any]:
    """Keys that kept failing long enough to ask the owner about."""
    import key_pool

    return {"alerts": key_pool.alerts(), "retry_every": key_pool.RETRY_EVERY}


@router.post("/api/keys/alerts/{key_name}/{fingerprint}")
def answer_key_alert(key_name: str, fingerprint: str, body: AlertAnswer, _owner_user=Owner) -> Dict[str, Any]:
    """The owner's answer: ``drop`` removes only that key; ``keep`` keeps retrying it and stops asking."""
    import key_pool

    try:
        result = key_pool.resolve(key_name.strip().upper(), fingerprint, body.action)
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'\"")) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    _apply_live()
    return {"result": result, "alerts": key_pool.alerts()}


# --- models you add yourself ----------------------------------------------------------------

#: Companies with an OpenAI-compatible chat endpoint. Data, not code: adding a company is a row here.
COMPANIES: Dict[str, Dict[str, str]] = {
    "openai": {"label": "OpenAI", "url": "https://api.openai.com/v1/chat/completions", "example": "gpt-4.1-mini",
               "signup": "https://platform.openai.com/api-keys"},
    "anthropic": {"label": "Anthropic", "url": "https://api.anthropic.com/v1/chat/completions", "example": "claude-sonnet-4-5",
                  "signup": "https://console.anthropic.com/settings/keys"},
    "google": {"label": "Google (Gemini)", "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "example": "gemini-2.5-pro", "signup": "https://aistudio.google.com/apikey"},
    "mistral": {"label": "Mistral", "url": "https://api.mistral.ai/v1/chat/completions", "example": "mistral-large-latest",
                "signup": "https://console.mistral.ai/api-keys"},
    "openrouter": {"label": "OpenRouter", "url": "https://openrouter.ai/api/v1/chat/completions",
                   "example": "meta-llama/llama-3.3-70b-instruct:free", "signup": "https://openrouter.ai/keys"},
    "together": {"label": "Together AI", "url": "https://api.together.xyz/v1/chat/completions",
                 "example": "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free", "signup": "https://api.together.ai/settings/api-keys"},
    "cerebras": {"label": "Cerebras", "url": "https://api.cerebras.ai/v1/chat/completions", "example": "llama-3.3-70b",
                 "signup": "https://cloud.cerebras.ai/"},
    "fireworks": {"label": "Fireworks", "url": "https://api.fireworks.ai/inference/v1/chat/completions",
                  "example": "accounts/fireworks/models/llama-v3p3-70b-instruct", "signup": "https://fireworks.ai/account/api-keys"},
    "xai": {"label": "xAI (Grok)", "url": "https://api.x.ai/v1/chat/completions", "example": "grok-3-mini",
            "signup": "https://console.x.ai/"},
    "deepinfra": {"label": "DeepInfra", "url": "https://api.deepinfra.com/v1/openai/chat/completions",
                  "example": "meta-llama/Meta-Llama-3.1-70B-Instruct", "signup": "https://deepinfra.com/dash/api_keys"},
    "huggingface": {"label": "Hugging Face", "url": "https://router.huggingface.co/v1/chat/completions",
                    "example": "meta-llama/Llama-3.3-70B-Instruct", "signup": "https://huggingface.co/settings/tokens"},
    "nvidia": {"label": "NVIDIA NIM", "url": "https://integrate.api.nvidia.com/v1/chat/completions",
               "example": "meta/llama-3.3-70b-instruct", "signup": "https://build.nvidia.com/models"},
    "groq": {"label": "Groq", "url": "https://api.groq.com/openai/v1/chat/completions", "example": "llama-3.3-70b-versatile",
             "signup": "https://console.groq.com/keys"},
    "qwen": {"label": "Qwen (Alibaba Cloud)", "url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
             "example": "qwen-plus", "signup": "https://modelstudio.console.alibabacloud.com/model/settings/api-key"},
    "other": {"label": "Other (OpenAI-compatible URL)", "url": "", "example": "", "signup": ""},
}

#: What the owner can say a model is for. "chat" puts it in the model menu; the rest are notes Nyx reads.
USES = ("chat", "coding", "vision", "fast", "research", "writing", "other")


class CustomModel(BaseModel):
    name: str
    company: str
    model: str
    api_key: str = ""
    use: str = "chat"
    use_note: str = ""
    chat_url: str = ""
    free: bool = True


class CheckModel(BaseModel):
    company: str = "other"
    chat_url: str = ""
    model: str = ""
    api_key: str = ""


def normalize_chat_url(raw: str) -> str:
    """What the owner pasted → the chat-completions endpoint.

    "Chat completions URL but I can't use it" (2026-09-16): a base address (https://api.x.ai/v1), a bare host
    (localhost:1234) or a trailing slash was refused or stored as-is and then failed on the first message.
    """
    url = (raw or "").strip().strip("\"'")
    if not url:
        return ""
    if "://" not in url:
        from provider_specs import _is_local_host

        host = url.split("/")[0].rsplit(":", 1)[0]
        url = ("http://" if _is_local_host(host) else "https://") + url
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path.endswith("/completions"):
        path = (path or "/v1") + "/chat/completions"
    return urlunparse(parsed._replace(path=path))


def _is_local_url(url: str) -> bool:
    from urllib.parse import urlparse

    from provider_specs import _is_local_host

    try:
        return bool(url) and _is_local_host(urlparse(url).hostname or "")
    except ValueError:
        return False


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)[:40]


@router.get("/api/custom-models")
def list_custom_models(_owner_user=Owner) -> Dict[str, Any]:
    import key_pool
    from provider_specs import PROVIDER_SPECS

    models: List[Dict[str, Any]] = []
    for spec in PROVIDER_SPECS.list_specs():
        pool = key_pool.summary(spec.name)
        models.append({**spec.as_dict(), "keys": pool["keys"], "needs_payment": pool["needs_payment"]})
    return {"models": models, "companies": [{"id": k, **v} for k, v in COMPANIES.items()], "uses": list(USES)}


@router.post("/api/custom-models")
def add_custom_model(body: CustomModel, _owner_user=Owner) -> Dict[str, Any]:
    """Add a model by name, company, model id and key. It joins the model menu and failover like a built-in one."""
    from provider_specs import BUILTIN_NAMES, PROVIDER_SPECS, ProviderSpecError, build_spec
    from secret_store import add_key

    company = COMPANIES.get((body.company or "").strip().lower())
    if company is None:
        raise HTTPException(status_code=400, detail="Pick the company, or Other with its API address.")
    # The URL box works for every company: it overrides the company's address when filled in.
    url = normalize_chat_url(body.chat_url) or company["url"]
    if not url:
        raise HTTPException(status_code=400, detail="Other needs its API address, e.g. https://api.example.com/v1 or http://localhost:1234/v1.")
    local = _is_local_url(url)
    name = _slug(body.name)
    if not name:
        raise HTTPException(status_code=400, detail="Give the model a name.")
    if name in BUILTIN_NAMES:
        name = f"{name}-custom"
    use = body.use if body.use in USES else "other"
    note = f"use: {use}" + (f" — {body.use_note.strip()[:160]}" if body.use_note.strip() else "")
    key = (body.api_key or "").strip()
    if key and len(key) < 8:
        raise HTTPException(status_code=400, detail="That key looks too short to be real.")
    # A server on this computer (LM Studio, Ollama, llama.cpp) usually needs no key.
    key_name = f"CUSTOM_{name.upper().replace('-', '_')}_API_KEY" if (key or not local) else ""
    try:
        spec = build_spec(name=name, chat_url=url, model=body.model.strip(), api_key_name=key_name,
                          label=f"{body.name.strip()[:40]} ({company['label']})", is_free=bool(body.free),
                          added_by="owner", signup_url=company.get("signup", ""), notes=note, allow_local=local)
        PROVIDER_SPECS.add(spec)
    except ProviderSpecError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if key:
        add_key(key_name, key)
    _refresh_routers()
    _apply_live()
    return {"model": spec.as_dict()}


@router.post("/api/custom-models/check")
def check_custom_model(body: CheckModel, _owner_user=Owner) -> Dict[str, Any]:
    """Try an address before adding it: is it valid, which models does it list, does a 1-token call answer?"""
    import requests

    from provider_specs import ProviderSpecError, _validate_chat_url
    from providers.custom import scrub_secrets

    company = COMPANIES.get((body.company or "").strip().lower()) or COMPANIES["other"]
    url = normalize_chat_url(body.chat_url) or company["url"]
    local = _is_local_url(url)
    key = (body.api_key or "").strip()
    out: Dict[str, Any] = {"ok": False, "url": url, "local": local, "models": [], "detail": ""}
    if not url:
        out["detail"] = "Type the API address first."
        return out
    try:
        _validate_chat_url(url, local)
    except ProviderSpecError as error:
        out["detail"] = str(error)
        return out
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    base = url.rsplit("/chat/completions", 1)[0]
    reachable = False
    try:
        listed = requests.get(base + "/models", headers=headers, timeout=8)
        reachable = True
        if listed.ok:
            data = listed.json()
            rows = data.get("data", data.get("models", [])) if isinstance(data, dict) else []
            out["models"] = [str(r.get("id") or r.get("name")) for r in rows if isinstance(r, dict) and (r.get("id") or r.get("name"))][:80]
    except Exception:  # noqa: BLE001 - not every server lists its models
        pass
    model = (body.model or "").strip() or (out["models"][0] if out["models"] else "")
    if not model:
        out["detail"] = ("The address answers — type a model ID to send a test message." if reachable
                         else f"Nothing answered at {base} — is the server running, and is the address right?")
        return out
    try:
        reply = requests.post(url, headers=headers, timeout=25,
                              json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]})
    except requests.RequestException as error:
        out["detail"] = scrub_secrets(f"Could not reach {url}: {type(error).__name__}", key)
        return out
    if reply.status_code == 200:
        out.update(ok=True, model=model, detail=f"✓ {model} answered at {url}")
    else:
        out["detail"] = scrub_secrets(f"{reply.status_code}: {reply.text[:300]}", key)
    return out


@router.delete("/api/custom-models/{name}")
def remove_custom_model(name: str, _owner_user=Owner) -> Dict[str, Any]:
    from provider_specs import PROVIDER_SPECS
    from secret_store import set_keys

    spec = PROVIDER_SPECS.get(name)
    if spec is None or not PROVIDER_SPECS.remove(name):
        raise HTTPException(status_code=404, detail="No model by that name.")
    if spec.api_key_name.startswith("CUSTOM_"):
        set_keys(spec.api_key_name, [])
    _refresh_routers()
    _apply_live()
    return {"removed": spec.name}


def _refresh_routers() -> None:
    """Routers are cached per chat; a model added now must answer the next message."""
    try:
        import server

        for service in list(getattr(server, "_services", {}).values()):
            refresh = getattr(getattr(service, "router", None), "refresh_custom_providers", None)
            if callable(refresh):
                refresh()
    except Exception:
        pass
    try:
        from agent_runtime import _router

        _router().refresh_custom_providers()
    except Exception:
        pass


# --- storage (owner, 2026-09-15: "make sure it doesn't take too much storage") -----------------


@router.get("/api/storage")
def storage_report(_owner_user=Owner) -> Dict[str, Any]:
    import storage_budget

    return storage_budget.report()


@router.post("/api/storage/clean")
def storage_clean(_owner_user=Owner) -> Dict[str, Any]:
    """Apply the automatic budgets now (caches, backups, logs). Never touches memories, uploads or chats."""
    import storage_budget

    return {"result": storage_budget.enforce(), "report": storage_budget.report()}


@router.delete("/api/storage/leftovers/{key}")
def storage_remove_leftover(key: str, _owner_user=Owner) -> Dict[str, Any]:
    """Remove one old build folder from the fixed list, after the owner confirmed in the UI."""
    import storage_budget

    try:
        freed = storage_budget.remove_leftover(key)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Not a known leftover.") from error
    except OSError as error:
        raise HTTPException(status_code=409, detail=f"Could not remove it (is something using it?): {error}") from error
    return {"freed": freed, "report": storage_budget.report()}



# --- adult mode (owner request, 2026-09-15) ---------------------------------------------------


class ContentModeIn(BaseModel):
    adult_mode: bool


@router.get("/api/content-mode")
def read_content_mode(_owner_user=Owner) -> Dict[str, Any]:
    import content_mode

    return {"adult_mode": content_mode.enabled()}


@router.put("/api/content-mode")
def write_content_mode(body: ContentModeIn, _owner_user=Owner) -> Dict[str, Any]:
    """Turn mature content on or off for this install. The four hard limits in content_mode.py stay."""
    import content_mode

    return content_mode.set_enabled(body.adult_mode)
