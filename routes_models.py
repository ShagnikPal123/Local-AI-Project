"""HTTP routes for API keys and for which model does which job.

``/api/keys`` is the one place every credential is managed: single-key
providers (NVIDIA — free keys at build.nvidia.com — Gemini, Groq, OpenAI…),
AWS's three-part credentials, and providers the owner added. Values go into
``secret_store`` and the live settings; responses only ever carry ``last4``.

``/api/model-roles`` lets the owner point a job at a provider and model
("image check → NVIDIA Llama 3.2 Vision", "reading text → AWS Nova") and test it
right there. Nyx can do the same from chat with the ``set_model_purpose`` tool;
both publish ``model_roles.changed`` so every open window updates.

Reads use the chat gate. Writes change the owner's machine configuration, so
they need the owner (loopback on an unclaimed install, an admin session once
claimed) — the same rule as ``/api/engine``.
"""

from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()

#: Key fields per provider. Anything not listed takes one "api_key".
_FIELDS: Dict[str, List[Dict[str, Any]]] = {
    # The address is not a secret, but it belongs to the key: a Singapore key does not work on the US address.
    "qwen": [
        {"name": "api_key", "label": "API key", "secret_name": "QWEN_API_KEY", "secret": True},
        {"name": "base_url", "label": "Region address (optional — empty is Singapore)", "secret_name": "QWEN_BASE_URL",
         "secret": False, "optional": True},
    ],
    "aws": [
        {"name": "access_key_id", "label": "Access key ID", "secret_name": "AWS_ACCESS_KEY_ID", "secret": False},
        {"name": "secret_access_key", "label": "Secret access key", "secret_name": "AWS_SECRET_ACCESS_KEY", "secret": True},
        {"name": "region", "label": "Region (e.g. us-east-1)", "secret_name": "AWS_REGION", "secret": False},
        {"name": "session_token", "label": "Session token (only for temporary credentials)",
         "secret_name": "AWS_SESSION_TOKEN", "secret": True, "optional": True},
    ],
}

_LABELS = {
    "identity0": "Big Kahuna (Identity 0)", "gemini": "Google Gemini", "nvidia": "NVIDIA NIM", "groq": "Groq", "openai": "OpenAI",
    "claude": "Anthropic Claude", "deepseek": "DeepSeek", "kimi": "Moonshot Kimi", "aws": "AWS Bedrock",
    "ollama": "Ollama (on this PC)", "pollinations": "Pollinations (free images)", "qwen": "Qwen (Alibaba Cloud)",
}
_NOTES = {
    "identity0": "Nyx's own main brain, on this PC. No key and no account: it is always on, every chat goes through "
                 "it first, and it picks (and learns from) the models below. Its own model trains here too.",
    "nvidia": "Free API key with credits at build.nvidia.com — Nemotron 3 Ultra 550B (nvidia/nemotron-3-ultra-550b-a55b), vision (Llama 3.2 Vision), FLUX images, Llama chat.",
    "gemini": "Free key from Google AI Studio — fast chat, vision and long documents.",
    "groq": "Free key — very fast Llama chat.",
    "aws": "Bedrock models (Nova, Claude, Llama) with your AWS account. Needs model access enabled in the Bedrock console.",
    "ollama": "Local models, no key. Install Ollama and pull a model.",
    "pollinations": "Keyless free image generation, used as a last resort. Images carry a small watermark.",
    "openai": "Paid. GPT chat, vision and images.",
    "claude": "Paid. Claude chat and vision.",
    "qwen": "Qwen chat, coding and vision (qwen-plus, qwen-max, qwen-flash, qwen3-coder-plus, qwen-vl-plus). New Model Studio accounts get a free token quota, then it bills. Leave the address empty for Singapore, or paste your region's address from the console (US: https://dashscope-us.aliyuncs.com/compatible-mode/v1). Free Qwen also runs on NVIDIA, Groq and Ollama.",
}
_FREE = {"identity0", "nvidia", "gemini", "groq", "ollama", "pollinations"}
#: Providers that never take a credential: they run on this PC (Big Kahuna, Ollama) or are keyless services.
_KEYLESS = {"identity0", "ollama", "pollinations"}


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _last4(value: str) -> str:
    value = (value or "").strip()
    return value[-4:] if len(value) >= 8 else ""


def _single_key_name(provider: str) -> str:
    from provider_specs import BUILTIN_PROVIDERS, PROVIDER_SPECS

    name = str(BUILTIN_PROVIDERS.get(provider, {}).get("key_name", "") or "")
    if not name:
        spec = PROVIDER_SPECS.get(provider)
        name = spec.api_key_name if spec is not None else ""
    return name


def _stored(secret_name: str) -> str:
    """A non-secret setting kept beside a key (environment first, like the keys themselves)."""
    import os

    from secret_store import get_keys

    return os.getenv(secret_name, "").strip() or (get_keys(secret_name) or [""])[0]


def _entry(provider: str) -> Dict[str, Any]:
    import model_hub

    fields = _FIELDS.get(provider)
    if provider == "aws":
        creds = model_hub.aws_credentials()
        field_state = [{**{k: v for k, v in f.items() if k != "secret_name"},
                        "set": bool(creds.get(f["name"])),
                        "hint": (creds.get(f["name"]) if not f["secret"] else _last4(creds.get(f["name"], "")))}
                       for f in fields or []]
        configured = model_hub.is_configured("aws")
        last4 = _last4(creds.get("access_key_id", ""))
    elif provider in _KEYLESS:
        field_state, configured, last4 = [], model_hub.is_configured(provider), ""
    elif fields:
        # Several fields, one of them the key (Qwen: key + region address).
        key = model_hub.api_key_for(provider)
        field_state = []
        for f in fields:
            value = key if f["name"] == "api_key" else _stored(f["secret_name"])
            field_state.append({**{k: v for k, v in f.items() if k != "secret_name"}, "set": bool(value),
                                "hint": _last4(value) if f["secret"] else value[:120]})
        configured, last4 = bool(key), _last4(key)
    else:
        key = model_hub.api_key_for(provider)
        field_state = [{"name": "api_key", "label": "API key", "secret": True, "set": bool(key), "hint": _last4(key)}]
        configured, last4 = bool(key), _last4(key)
    try:
        from model_roles import MODEL_ROLES

        used_by = [entry["title"] for entry in MODEL_ROLES.list_all().values() if entry["provider"] == provider]
    except Exception:
        used_by = []
    return {
        "provider": provider,
        "label": _LABELS.get(provider, provider),
        "configured": configured,
        "last4": last4,
        "free": provider in _FREE,
        "keyless": provider in _KEYLESS,
        # Big Kahuna is Nyx's own brain: it needs no key and runs whenever Nyx runs.
        "always_on": provider == "identity0",
        "signup_url": model_hub.SIGNUP_URLS.get(provider, ""),
        "notes": _NOTES.get(provider, ""),
        "fields": field_state,
        "used_by": used_by,
    }


@router.get("/api/keys")
def list_keys(_user=RequireChat) -> Dict[str, Any]:
    """Every provider, whether it has credentials, and which jobs use it. No secrets."""
    import model_hub

    return {"providers": [_entry(name) for name in model_hub.known_providers()],
            "get_free_keys": {"nvidia": model_hub.SIGNUP_URLS["nvidia"], "gemini": model_hub.SIGNUP_URLS["gemini"],
                              "groq": model_hub.SIGNUP_URLS["groq"]}}


class KeyUpdate(BaseModel):
    api_key: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    region: str = ""
    session_token: str = ""
    base_url: str = ""


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


@router.post("/api/keys/{provider}")
def save_key(provider: str, body: KeyUpdate, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Store credentials for a provider. The response never contains them."""
    import model_hub
    from secret_store import set_keys

    name = (provider or "").strip().lower()
    if name not in model_hub.known_providers():
        raise HTTPException(status_code=404, detail=f"Unknown provider '{name}'.")
    if name in ("ollama", "pollinations"):
        raise HTTPException(status_code=400, detail=f"{_LABELS[name]} needs no key.")

    if name == "aws":
        updates = {"AWS_ACCESS_KEY_ID": body.access_key_id, "AWS_SECRET_ACCESS_KEY": body.secret_access_key,
                   "AWS_REGION": body.region, "AWS_SESSION_TOKEN": body.session_token}
        provided = {k: v.strip() for k, v in updates.items() if v and v.strip()}
        if not provided:
            raise HTTPException(status_code=400, detail="Enter at least one AWS field.")
        if "AWS_ACCESS_KEY_ID" in provided and not provided["AWS_ACCESS_KEY_ID"].startswith(("AKIA", "ASIA")):
            raise HTTPException(status_code=400, detail="An AWS access key ID starts with AKIA or ASIA.")
        for secret_name, value in provided.items():
            set_keys(secret_name, [value])
    elif name == "qwen":
        key, base = (body.api_key or "").strip(), (body.base_url or "").strip()
        if not key and not base:
            raise HTTPException(status_code=400, detail="Enter the key, the region address, or both.")
        if key and len(key) < 8:
            raise HTTPException(status_code=400, detail="That key looks too short to be real.")
        if base and not re.match(r"^https://[A-Za-z0-9.-]+\.aliyuncs\.com(/[\w./-]*)?$", base):
            raise HTTPException(status_code=400, detail="Paste the https://…aliyuncs.com address from the Model Studio console.")
        if key:
            set_keys("QWEN_API_KEY", [key])
        if base:
            set_keys("QWEN_BASE_URL", [base])
    else:
        key = (body.api_key or "").strip()
        if len(key) < 8:
            raise HTTPException(status_code=400, detail="That key looks too short to be real.")
        secret_name = _single_key_name(name)
        if not secret_name:
            raise HTTPException(status_code=400, detail=f"{name} has no key setting.")
        set_keys(secret_name, [key])
    _apply_live()
    return {"key": _entry(name)}


@router.delete("/api/keys/{provider}")
def delete_key(provider: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import model_hub
    from secret_store import set_keys

    name = (provider or "").strip().lower()
    if name not in model_hub.known_providers():
        raise HTTPException(status_code=404, detail=f"Unknown provider '{name}'.")
    names = [f["secret_name"] for f in _FIELDS.get(name, [])] or [_single_key_name(name)]
    for secret_name in filter(None, names):
        set_keys(secret_name, [])
    _apply_live()
    return {"key": _entry(name), "note": "Keys in .env.local are not changed; remove them there if present."}


@router.post("/api/keys/{provider}/test")
def test_key(provider: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """A free check that the credentials work (lists models; spends nothing)."""
    import requests

    import model_hub

    name = (provider or "").strip().lower()
    if name == "identity0":
        # Nyx's own brain: nothing to authenticate, so the check is "is it on, and who is it working with".
        try:
            from identity0 import provider as kahuna
            from identity0.state import get_settings

            if not get_settings().get("enabled"):
                return {"ok": False, "detail": "Big Kahuna is switched off in its own tab."}
            router = kahuna.shared_router()
            if router is None:  # asked before the engine built its router
                return {"ok": True, "detail": "Always on, no key needed."}
            info = kahuna.status(router)
            members = ", ".join(m["label"] for m in info["members"][:4])
            if not info["members"]:
                return {"ok": False, "detail": "Always on, no key needed — but no model is up for it to work "
                                               "with yet. Start Ollama or add a free key below."}
            return {"ok": True,
                    "detail": f"Always on, no key needed. Working with {len(info['members'])} model(s): {members}."}
        except Exception as error:  # noqa: BLE001 - reported to the owner
            return {"ok": False, "detail": f"{type(error).__name__}: {str(error)[:200]}"}
    if not model_hub.is_configured(name):
        return {"ok": False, "detail": "No credentials saved for this provider yet."}
    try:
        if name == "aws":
            creds = model_hub.aws_credentials()
            url = f"https://bedrock.{creds['region']}.amazonaws.com/foundation-models"
            headers = model_hub.sigv4_headers("GET", url, b"", region=creds["region"], service="bedrock",
                                              access_key=creds["access_key_id"], secret_key=creds["secret_access_key"],
                                              session_token=creds["session_token"])
            response = requests.get(url, headers=headers, timeout=20)
            ok = response.status_code == 200
            count = len(response.json().get("modelSummaries", [])) if ok else 0
            detail = f"AWS credentials work — {count} Bedrock models in {creds['region']}." if ok else \
                f"AWS answered {response.status_code}: {model_hub._scrub(response.text, creds['secret_access_key'])}"
            return {"ok": ok, "detail": detail}
        models = model_hub.list_models(name, refresh=True)
        if name in model_hub.IMAGE_ONLY_PROVIDERS or name == "ollama":
            return {"ok": True, "detail": f"{_LABELS.get(name, name)} is reachable."}
        live = [m for m in models if m["id"] not in set(model_hub.DEFAULT_MODELS.get(name, {}).values())]
        if not live:
            reply = model_hub.complete(name, "", "Reply with the single word OK.", max_tokens=5, timeout=30)
            return {"ok": True, "detail": f"Key works — {reply.model} answered in {reply.ms} ms."}
        return {"ok": True, "detail": f"Key works — {len(models)} models available."}
    except model_hub.ModelCallError as error:
        return {"ok": False, "detail": str(error)}
    except Exception as error:  # noqa: BLE001 - reported to the owner
        return {"ok": False, "detail": f"{type(error).__name__}: {str(error)[:200]}"}


# ---------------------------------------------------------------------------
# Model roles
# ---------------------------------------------------------------------------


class RoleUpdate(BaseModel):
    provider: str
    model: str = ""
    label: str = ""
    title: str = ""
    description: str = ""
    job: str = ""


class RoleTest(BaseModel):
    generate: bool = False


@router.get("/api/model-roles")
def get_roles(_user=RequireChat) -> Dict[str, Any]:
    from model_roles import MODEL_ROLES

    return MODEL_ROLES.snapshot()


@router.put("/api/model-roles/{role}")
def put_role(role: str, body: RoleUpdate, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    from model_roles import MODEL_ROLES, RoleError

    try:
        entry = MODEL_ROLES.assign_role(role, body.provider, model=body.model, title=body.title,
                                        announced_label=body.label, description=body.description, job=body.job,
                                        assigned_by="owner")
    except RoleError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"role": entry, "roles": MODEL_ROLES.snapshot()["roles"]}


@router.delete("/api/model-roles/{role}")
def reset_role(role: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    from model_roles import MODEL_ROLES

    entry = MODEL_ROLES.reset_role(role)
    return {"role": entry, "roles": MODEL_ROLES.snapshot()["roles"]}


def _test_image() -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (320, 200), (245, 245, 250))
    draw = ImageDraw.Draw(image)
    draw.rectangle([30, 60, 150, 140], fill=(220, 40, 40))
    draw.ellipse([190, 50, 290, 150], fill=(40, 90, 220))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@router.post("/api/model-roles/{role}/test")
def test_role(role: str, body: Optional[RoleTest] = None, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Run the role's model once on a tiny task, with no fallback, so the result is about that model."""
    import model_hub
    from model_roles import MODEL_ROLES

    entry = MODEL_ROLES.get_role(role)
    if not entry:
        raise HTTPException(status_code=404, detail="No such role.")
    try:
        if entry["job"] == "image":
            if not (body and body.generate):
                ready = model_hub.is_configured(entry["provider"])
                return {"ok": ready, "label": entry["label"],
                        "detail": "Ready to draw (send generate=true to make a test picture)." if ready
                        else "No key for this provider yet."}
            image = model_hub.generate_image(entry["provider"], entry["model"], "a small purple crystal on a desk", "1024x1024")
            return {"ok": True, "label": entry["label"], "ms": image.ms, "detail": f"Made a {len(image.data) // 1024} KB picture."}
        if entry["job"] == "vision":
            run = MODEL_ROLES.run(role, "Name the two shapes and their colours in one short sentence.",
                                  images=[(_test_image(), "image/png")], allow_fallback=False, max_tokens=60)
        else:
            run = MODEL_ROLES.run(role, "Reply with one short sentence confirming you are ready.",
                                  allow_fallback=False, max_tokens=40)
        return {"ok": True, "label": run.label, "ms": run.ms, "detail": run.text}
    except model_hub.ModelCallError as error:
        return {"ok": False, "label": entry["label"], "detail": str(error)}


@router.get("/api/usage/limits")
def usage_limit_snapshot(provider: str, refresh: bool = False, _user=RequireChat) -> Dict[str, Any]:
    """Limits the provider itself reported (headers, quota errors, balance) — empty means no bar (Request G6)."""
    import usage_limits

    return usage_limits.snapshot((provider or "").strip().lower(), refresh_balance=refresh)


@router.get("/api/models/catalog")
def model_catalog(provider: str, job: str = "", refresh: bool = False, _user=RequireChat) -> Dict[str, Any]:
    """Models a provider offers, optionally filtered by job — for the model pickers."""
    import model_hub

    name = (provider or "").strip().lower()
    if name not in model_hub.known_providers():
        raise HTTPException(status_code=404, detail=f"Unknown provider '{name}'.")
    models = model_hub.list_models(name, refresh=refresh)
    if job:
        models = [m for m in models if job in m["jobs"]]
    return {"provider": name, "models": models, "default": model_hub.default_model(name, job or "text"),
            "signup_url": model_hub.SIGNUP_URLS.get(name, "")}
