"""Call any model the owner names, for any purpose — text, vision, or pictures.

The router answers chat: it picks *a* working provider and falls back freely.
That is the wrong tool when the owner says "use NVIDIA's Llama Vision for image
checks" or "use AWS for reading documents". Then the provider and the model are
the point, and silently answering with something else would be a lie.

This module makes exactly one call to exactly the provider and model asked for,
and reports what it used. Callers (``model_roles.run_role``) decide what to do
when it fails — including saying so and falling back openly.

Supported:

* **OpenAI-compatible** chat (NVIDIA NIM, Groq, OpenAI, DeepSeek, Kimi, any
  provider the owner added) — text and ``image_url`` parts.
* **Gemini** — text, images, PDFs, and image generation models.
* **Anthropic** — text and images.
* **AWS Bedrock** — the Converse API, signed with SigV4 by hand so no AWS SDK is
  needed. Credentials: ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``,
  ``AWS_REGION`` (and ``AWS_SESSION_TOKEN`` for temporary credentials).
* **Ollama** — local models, including vision models such as llava.
* **Image generation** — NVIDIA genai (FLUX, Stable Diffusion), OpenAI images,
  Gemini image models.

Keys never appear in errors: every message is scrubbed before it leaves.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import requests

#: Signup / key pages shown next to each provider in the key manager.
SIGNUP_URLS: Dict[str, str] = {
    "nvidia": "https://build.nvidia.com/models",
    "gemini": "https://aistudio.google.com/apikey",
    "groq": "https://console.groq.com/keys",
    "openai": "https://platform.openai.com/api-keys",
    "claude": "https://console.anthropic.com/settings/keys",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "kimi": "https://platform.moonshot.ai/console/api-keys",
    "aws": "https://console.aws.amazon.com/iam/home#/security_credentials",
    "qwen": "https://modelstudio.console.alibabacloud.com/model/settings/api-key",
}

#: OpenAI-compatible chat endpoints for the shipped providers.
OPENAI_CHAT_URLS: Dict[str, str] = {
    "nvidia": "https://integrate.api.nvidia.com/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/chat/completions",
    "kimi": "https://api.moonshot.cn/v1/chat/completions",
}

#: Settings attribute holding each shipped provider's key.
KEY_FIELDS: Dict[str, str] = {
    "nvidia": "nvidia_api_key",
    "groq": "groq_api_key",
    "openai": "openai_api_key",
    "deepseek": "deepseek_api_key",
    "kimi": "kimi_api_key",
    "qwen": "qwen_api_key",
    "gemini": "gemini_api_key",
    "claude": "anthropic_api_key",
}

#: Sensible models per provider and job, used when the owner names only a provider.
DEFAULT_MODELS: Dict[str, Dict[str, str]] = {
    # Big Kahuna (Request S): "auto" = it picks the best member for the job itself.
    "identity0": {"text": "auto"},
    "nvidia": {"text": "nvidia/nemotron-3-super-120b-a12b", "vision": "meta/llama-3.2-11b-vision-instruct",
               "image": "black-forest-labs/flux.1-schnell"},
    "gemini": {"text": "gemini-flash-lite-latest", "vision": "gemini-flash-lite-latest",
               "image": "gemini-2.5-flash-image"},
    "groq": {"text": "llama-3.3-70b-versatile", "vision": "meta-llama/llama-4-scout-17b-16e-instruct"},
    "openai": {"text": "gpt-4o-mini", "vision": "gpt-4o-mini", "image": "gpt-image-1"},
    "claude": {"text": "claude-haiku-4-5-20251001", "vision": "claude-haiku-4-5-20251001"},
    "deepseek": {"text": "deepseek-chat"},
    "kimi": {"text": "moonshot-v1-8k"},
    "qwen": {"text": "qwen-plus", "vision": "qwen-vl-plus"},
    "aws": {"text": "amazon.nova-lite-v1:0", "vision": "amazon.nova-lite-v1:0",
            "image": "amazon.nova-canvas-v1:0"},
    "ollama": {"text": "llama3.1", "vision": "llava"},
    # Free and keyless: the last-resort picture maker when no keyed provider can
    # draw right now. Its images carry a small watermark.
    "pollinations": {"image": "flux"},
}

#: Providers that only make images (never offered for text or vision jobs).
IMAGE_ONLY_PROVIDERS = frozenset({"pollinations"})

#: NVIDIA chat models worth offering first — all free with a build.nvidia.com key.
#: Nemotron 3 Ultra (550B total, 55B active) is NVIDIA's biggest open reasoning model.
#: Measured 2026-09-14 for a short JSON reply: Super 1.0 s (the default), Lightning 10 s, Ultra 27 s.
#: (meta/llama-3.3-70b-instruct, the old default, was retired on 2026-08-26 and now answers 410.)
NVIDIA_FEATURED_MODELS: List[str] = [
    "nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia/nemotron-3-super-120b-a12b",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
]

#: Image models NVIDIA serves on its genai endpoint (not listed by /v1/models).
NVIDIA_IMAGE_MODELS: List[str] = [
    "black-forest-labs/flux.1-schnell",
    "black-forest-labs/flux.1-dev",
    "stabilityai/stable-diffusion-3-medium",
    "stabilityai/stable-diffusion-xl",
]

_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
_TIMEOUT = 120


class ModelCallError(RuntimeError):
    """A named model could not answer. The message is safe to show the user."""


@dataclass
class ModelReply:
    text: str
    provider: str
    model: str
    ms: int
    usage: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GeneratedImage:
    data: bytes
    mime: str
    provider: str
    model: str
    ms: int
    revised_prompt: str = ""


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------


def _secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        from secret_store import get_keys

        keys = get_keys(name)
        return keys[0] if keys else ""
    except Exception:
        return ""


def aws_credentials() -> Dict[str, str]:
    return {
        "access_key_id": _secret("AWS_ACCESS_KEY_ID"),
        "secret_access_key": _secret("AWS_SECRET_ACCESS_KEY"),
        "session_token": _secret("AWS_SESSION_TOKEN"),
        "region": _secret("AWS_REGION") or "us-east-1",
    }


def _custom_spec(provider: str) -> Any:
    try:
        from provider_specs import PROVIDER_SPECS

        return PROVIDER_SPECS.get(provider)
    except Exception:
        return None


def api_key_for(provider: str) -> str:
    """The configured key for ``provider`` ("" when none)."""
    name = (provider or "").strip().lower()
    if name == "aws":
        return aws_credentials()["access_key_id"]
    if name == "ollama":
        return ""
    field_name = KEY_FIELDS.get(name)
    if field_name:
        try:
            from config import SETTINGS

            return str(getattr(SETTINGS, field_name, "") or "").strip()
        except Exception:
            return ""
    spec = _custom_spec(name)
    if spec is not None:
        return _secret(spec.api_key_name) if spec.api_key_name else ""
    return ""


def is_configured(provider: str) -> bool:
    name = (provider or "").strip().lower()
    if name == "identity0":
        try:
            from identity0.state import get_settings

            return bool(get_settings().get("enabled"))
        except Exception:  # noqa: BLE001
            return False
    if name == "aws":
        creds = aws_credentials()
        return bool(creds["access_key_id"] and creds["secret_access_key"])
    if name == "ollama":
        try:
            requests.get(_ollama_host() + "/api/tags", timeout=0.5).raise_for_status()
            return True
        except Exception:
            return False
    if name in IMAGE_ONLY_PROVIDERS:
        return True
    spec = _custom_spec(name)
    if spec is not None and not spec.api_key_name:
        return True
    return bool(api_key_for(name))


def known_providers() -> List[str]:
    names = ["identity0", "gemini", "nvidia", "groq", "openai", "claude", "deepseek", "kimi", "qwen", "aws", "ollama",
             "pollinations"]
    try:
        from provider_specs import PROVIDER_SPECS

        names += [n for n in PROVIDER_SPECS.names() if n not in names]
    except Exception:
        pass
    return names


def default_model(provider: str, job: str = "text") -> str:
    name = (provider or "").strip().lower()
    models = DEFAULT_MODELS.get(name, {})
    if job in models:
        return models[job]
    spec = _custom_spec(name)
    if spec is not None and job == "text":
        return spec.model
    return models.get("text", "")


def _scrub(text: str, *secrets: str) -> str:
    cleaned = str(text or "")
    for secret in secrets:
        if secret and len(secret) >= 6:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    cleaned = re.sub(r"([?&]key=)[^&\s]+", r"\1[REDACTED]", cleaned)
    return cleaned[:500]


def _qwen_chat_url() -> str:
    """Qwen's address follows the region saved with its key (Request R17)."""
    from providers.qwen_provider import chat_url_from

    try:
        from config import SETTINGS

        return chat_url_from(getattr(SETTINGS, "qwen_base_url", ""))
    except Exception:
        return chat_url_from("")


def _ollama_host() -> str:
    try:
        from config import SETTINGS

        host = SETTINGS.ollama_host or "http://127.0.0.1:11434"
    except Exception:
        host = "http://127.0.0.1:11434"
    return host.replace("//localhost:", "//127.0.0.1:").rstrip("/")


# ---------------------------------------------------------------------------
# AWS SigV4
# ---------------------------------------------------------------------------


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def sigv4_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """AWS's derived signing key (Signature Version 4)."""
    k_date = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region = hmac.new(k_date, region.encode("utf-8"), hashlib.sha256).digest()
    k_service = hmac.new(k_region, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(k_service, b"aws4_request", hashlib.sha256).digest()


def sigv4_headers(
    method: str,
    url: str,
    body: bytes,
    *,
    region: str,
    service: str,
    access_key: str,
    secret_key: str,
    session_token: str = "",
    now: Optional[_dt.datetime] = None,
    content_type: str = "application/json",
) -> Dict[str, str]:
    """Headers that authenticate one request to an AWS service."""
    moment = now or _dt.datetime.now(_dt.timezone.utc)
    amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = moment.strftime("%Y%m%d")
    parsed = urllib.parse.urlsplit(url)
    host = parsed.netloc
    # Each path segment is URI-encoded once more for SigV4 (model ids contain ":").
    canonical_uri = "/".join(urllib.parse.quote(urllib.parse.unquote(seg), safe="-_.~") for seg in parsed.path.split("/")) or "/"
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    canonical_query = "&".join(
        f"{urllib.parse.quote(k, safe='-_.~')}={urllib.parse.quote(v, safe='-_.~')}" for k, v in sorted(query)
    )
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {"content-type": content_type, "host": host, "x-amz-date": amz_date}
    if session_token:
        headers["x-amz-security-token"] = session_token
    signed_names = sorted(headers)
    canonical_headers = "".join(f"{name}:{headers[name].strip()}\n" for name in signed_names)
    signed_headers = ";".join(signed_names)
    canonical_request = "\n".join(
        [method.upper(), canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()]
    )
    signature = hmac.new(
        sigv4_signing_key(secret_key, date_stamp, region, service), string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    result = {
        "Content-Type": content_type,
        "X-Amz-Date": amz_date,
        "X-Amz-Content-Sha256": payload_hash,
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }
    if session_token:
        result["X-Amz-Security-Token"] = session_token
    return result


def _image_format(mime: str) -> str:
    return {"image/png": "png", "image/jpeg": "jpeg", "image/jpg": "jpeg", "image/gif": "gif",
            "image/webp": "webp"}.get((mime or "").lower(), "png")


def _bedrock_converse(model: str, prompt: str, images: Sequence[Tuple[bytes, str]], system: str,
                      max_tokens: int, timeout: float) -> Tuple[str, Dict[str, Any]]:
    creds = aws_credentials()
    if not (creds["access_key_id"] and creds["secret_access_key"]):
        raise ModelCallError("AWS is not set up: add an access key ID, secret access key and region in Keys.")
    region = creds["region"]
    url = f"https://bedrock-runtime.{region}.amazonaws.com/model/{urllib.parse.quote(model, safe='')}/converse"
    content: List[Dict[str, Any]] = [
        {"image": {"format": _image_format(mime), "source": {"bytes": base64.b64encode(data).decode("ascii")}}}
        for data, mime in images
    ]
    content.append({"text": prompt})
    payload: Dict[str, Any] = {
        "messages": [{"role": "user", "content": content}],
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system:
        payload["system"] = [{"text": system}]
    body = json.dumps(payload).encode("utf-8")
    headers = sigv4_headers("POST", url, body, region=region, service="bedrock",
                            access_key=creds["access_key_id"], secret_key=creds["secret_access_key"],
                            session_token=creds["session_token"])
    try:
        response = requests.post(url, data=body, headers=headers, timeout=timeout)
    except requests.RequestException as error:
        raise ModelCallError(f"AWS Bedrock could not be reached: {_scrub(error, creds['secret_access_key'])}") from error
    if response.status_code != 200:
        detail = _scrub(response.text, creds["secret_access_key"], creds["access_key_id"])
        raise ModelCallError(f"AWS Bedrock ({model}) answered {response.status_code}: {detail}")
    data = response.json()
    parts = data.get("output", {}).get("message", {}).get("content", [])
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    return text, data.get("usage", {})


# ---------------------------------------------------------------------------
# One call to one model
# ---------------------------------------------------------------------------


def complete(
    provider: str,
    model: str = "",
    prompt: str = "",
    *,
    images: Sequence[Tuple[bytes, str]] = (),
    system: str = "",
    max_tokens: int = 1024,
    timeout: float = _TIMEOUT,
) -> ModelReply:
    """Ask exactly ``provider``/``model``. Raises ModelCallError with a safe message."""
    name = (provider or "").strip().lower()
    job = "vision" if images else "text"
    chosen = (model or "").strip() or default_model(name, job)
    if not chosen:
        raise ModelCallError(f"No model named for {name}, and there is no default for it.")
    started = time.perf_counter()
    try:
        text, usage = _complete_with(name, chosen, prompt, images, system, max_tokens, timeout)
    except ModelCallError as error:
        _record(name, chosen, started, False, str(error))
        raise
    _record(name, chosen, started, True, "", usage)
    return ModelReply(text=(text or "").strip(), provider=name, model=chosen,
                      ms=round((time.perf_counter() - started) * 1000), usage=usage or {})


def _record(provider: str, model: str, started: float, ok: bool, error: str = "", usage: Any = None) -> None:
    """Model-role calls count in the API usage gauges too, not only chat streams (Request J8)."""
    try:
        from metrics import GLOBAL_METRICS

        tokens = None
        if isinstance(usage, dict):
            tokens = usage.get("total_tokens") or usage.get("totalTokenCount") or (
                (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0)) or None
        GLOBAL_METRICS.record(provider=provider, latency_seconds=time.perf_counter() - started, success=ok, mode="role",
                              tokens_total=tokens, error_message=error[:200] or None, metadata={"model": model})
    except Exception:  # pragma: no cover - measuring never breaks a call
        pass


def _complete_with(name: str, chosen: str, prompt: str, images: Sequence[Tuple[bytes, str]], system: str,
                   max_tokens: int, timeout: float) -> Tuple[str, Dict[str, Any]]:
    if name == "identity0":
        text, usage = _identity0_complete(prompt, system)
    elif name == "aws":
        text, usage = _bedrock_converse(chosen, prompt, images, system, max_tokens, timeout)
    elif name == "gemini":
        text, usage = _gemini_complete(chosen, prompt, images, system, max_tokens, timeout)
    elif name == "claude":
        text, usage = _anthropic_complete(chosen, prompt, images, system, max_tokens, timeout)
    elif name == "ollama":
        text, usage = _ollama_complete(chosen, prompt, images, system, timeout)
    else:
        url = _qwen_chat_url() if name == "qwen" else OPENAI_CHAT_URLS.get(name)
        spec = _custom_spec(name) if url is None else None
        if url is None and spec is not None:
            url = spec.chat_url
        if url is None:
            raise ModelCallError(f"Unknown provider {name!r}. Add it in Keys first.")
        text, usage = _openai_complete(name, url, chosen, prompt, images, system, max_tokens, timeout)
    return text, usage


def _identity0_complete(prompt: str, system: str) -> Tuple[str, Dict[str, Any]]:
    """Any model role can run through Big Kahuna ("changes are run through it", Request S8).

    It never answers on a thread that is already doing Identity 0's work — that would be a loop.
    """
    try:
        from identity0 import collab
        from identity0.provider import shared_router
    except Exception as error:  # noqa: BLE001
        raise ModelCallError(f"Big Kahuna is not available: {type(error).__name__}") from error
    if collab.inside():
        raise ModelCallError("Big Kahuna cannot call itself.")
    router = shared_router()
    provider = (getattr(router, "providers", {}) or {}).get("identity0") if router is not None else None
    if provider is None or not provider.is_available():
        raise ModelCallError("Big Kahuna is switched off or has no model to work with.")
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    try:
        return provider.chat(messages), {}
    except Exception as error:  # noqa: BLE001
        raise ModelCallError(f"Big Kahuna could not answer: {str(error)[:200]}") from error


def _openai_complete(name: str, url: str, model: str, prompt: str, images: Sequence[Tuple[bytes, str]],
                     system: str, max_tokens: int, timeout: float) -> Tuple[str, Dict[str, Any]]:
    key = api_key_for(name)
    spec = _custom_spec(name)
    if not key and not (spec is not None and not spec.api_key_name):
        raise ModelCallError(f"{name} has no API key yet. Add one in Keys" +
                             (f" (free keys: {SIGNUP_URLS[name]})." if name in SIGNUP_URLS else "."))
    content: Any = prompt
    if images:
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:{mime or 'image/png'};base64,{base64.b64encode(data).decode('ascii')}"}}
            for data, mime in images
        ]
    messages: List[Dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        response = requests.post(url, headers=headers, timeout=timeout,
                                 json={"model": model, "messages": messages, "max_tokens": max_tokens})
    except requests.RequestException as error:
        raise ModelCallError(f"{name} could not be reached: {_scrub(error, key)}") from error
    _observe(name, response, model)
    if response.status_code != 200:
        raise ModelCallError(f"{name} ({model}) answered {response.status_code}: {_scrub(response.text, key)}")
    try:
        data = response.json()
        text = data["choices"][0]["message"].get("content") or ""
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise ModelCallError(f"{name} ({model}) returned an unreadable reply.") from error
    return str(text), data.get("usage", {})


def _observe(provider: str, response: Any, model: str) -> None:
    try:
        import usage_limits

        usage_limits.observe(provider, response, model)
    except Exception:  # pragma: no cover - measuring never breaks a call
        pass


def _gemini_complete(model: str, prompt: str, images: Sequence[Tuple[bytes, str]], system: str,
                     max_tokens: int, timeout: float) -> Tuple[str, Dict[str, Any]]:
    key = api_key_for("gemini")
    if not key:
        raise ModelCallError(f"Gemini has no API key yet. Add one in Keys (free keys: {SIGNUP_URLS['gemini']}).")
    parts: List[Dict[str, Any]] = [
        {"inlineData": {"mimeType": mime or "image/png", "data": base64.b64encode(data).decode("ascii")}}
        for data, mime in images
    ]
    parts.append({"text": prompt})
    payload: Dict[str, Any] = {"contents": [{"role": "user", "parts": parts}],
                               "generationConfig": {"maxOutputTokens": max_tokens}}
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    try:
        response = requests.post(_GEMINI_BASE + model + ":generateContent", params={"key": key},
                                 json=payload, timeout=timeout)
    except requests.RequestException as error:
        raise ModelCallError(f"Gemini could not be reached: {_scrub(error, key)}") from error
    _observe("gemini", response, model)
    if response.status_code != 200:
        raise ModelCallError(f"Gemini ({model}) answered {response.status_code}: {_scrub(response.text, key)}")
    data = response.json()
    try:
        candidate_parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, TypeError) as error:
        raise ModelCallError(f"Gemini ({model}) returned no answer.") from error
    text = "".join(p.get("text", "") for p in candidate_parts if not p.get("thought"))
    return text, data.get("usageMetadata", {})


def _anthropic_complete(model: str, prompt: str, images: Sequence[Tuple[bytes, str]], system: str,
                        max_tokens: int, timeout: float) -> Tuple[str, Dict[str, Any]]:
    key = api_key_for("claude")
    if not key:
        raise ModelCallError(f"Claude has no API key yet. Add one in Keys ({SIGNUP_URLS['claude']}).")
    content: List[Dict[str, Any]] = [
        {"type": "image", "source": {"type": "base64", "media_type": mime or "image/png",
                                     "data": base64.b64encode(data).decode("ascii")}}
        for data, mime in images
    ]
    content.append({"type": "text", "text": prompt})
    payload: Dict[str, Any] = {"model": model, "max_tokens": max_tokens,
                               "messages": [{"role": "user", "content": content}]}
    if system:
        payload["system"] = system
    try:
        response = requests.post("https://api.anthropic.com/v1/messages", json=payload, timeout=timeout,
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"})
    except requests.RequestException as error:
        raise ModelCallError(f"Claude could not be reached: {_scrub(error, key)}") from error
    if response.status_code != 200:
        raise ModelCallError(f"Claude ({model}) answered {response.status_code}: {_scrub(response.text, key)}")
    data = response.json()
    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    return text, data.get("usage", {})


def _ollama_complete(model: str, prompt: str, images: Sequence[Tuple[bytes, str]], system: str,
                     timeout: float) -> Tuple[str, Dict[str, Any]]:
    message: Dict[str, Any] = {"role": "user", "content": prompt}
    if images:
        message["images"] = [base64.b64encode(data).decode("ascii") for data, _mime in images]
    messages = ([{"role": "system", "content": system}] if system else []) + [message]
    try:
        response = requests.post(_ollama_host() + "/api/chat", timeout=timeout,
                                 json={"model": model, "messages": messages, "stream": False})
    except requests.RequestException as error:
        raise ModelCallError(f"Ollama is not running on this computer ({error.__class__.__name__}).") from error
    if response.status_code != 200:
        raise ModelCallError(f"Ollama ({model}) answered {response.status_code}: {response.text[:300]}")
    return str(response.json().get("message", {}).get("content", "")), {}


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------


def _size(size: str) -> Tuple[int, int]:
    match = re.match(r"^\s*(\d{3,4})\s*[x×]\s*(\d{3,4})\s*$", size or "")
    if not match:
        return 1024, 1024
    return int(match.group(1)), int(match.group(2))


def _snap_nvidia(value: int) -> int:
    """FLUX on NVIDIA accepts 768–1344 in steps of 64."""
    allowed = list(range(768, 1345, 64))
    return min(allowed, key=lambda option: abs(option - value))


def generate_image(provider: str, model: str = "", prompt: str = "", size: str = "1024x1024",
                   timeout: float = 180) -> GeneratedImage:
    """Make one picture with exactly this provider and model."""
    name = (provider or "").strip().lower()
    chosen = (model or "").strip() or default_model(name, "image")
    clean = (prompt or "").strip()
    if not clean:
        raise ModelCallError("Describe the picture to generate.")
    if not chosen:
        raise ModelCallError(f"{name} has no image model configured.")
    width, height = _size(size)
    started = time.perf_counter()

    if name == "nvidia":
        key = api_key_for("nvidia")
        if not key:
            raise ModelCallError(f"NVIDIA has no API key yet. Get a free one at {SIGNUP_URLS['nvidia']}.")
        payload: Dict[str, Any] = {"prompt": clean, "seed": 0}
        if "flux" in chosen:
            payload.update(width=_snap_nvidia(width), height=_snap_nvidia(height),
                           steps=4 if "schnell" in chosen else 30)
        else:
            payload.update(aspect_ratio="1:1" if width == height else ("16:9" if width > height else "9:16"),
                           cfg_scale=5, steps=30)
        headers = {"Authorization": f"Bearer {key}", "Accept": "application/json", "NVCF-POLL-SECONDS": "20"}
        try:
            response = requests.post(f"https://ai.api.nvidia.com/v1/genai/{chosen}", json=payload, timeout=60,
                                     headers=headers)
            # NVIDIA queues image jobs. A 202 carries a request id to poll rather
            # than holding the connection open until a proxy times it out.
            deadline = time.monotonic() + timeout
            request_id = response.headers.get("NVCF-REQID", "")
            while response.status_code == 202 and request_id and time.monotonic() < deadline:
                try:
                    from tool_context import progress

                    progress(f"NVIDIA is still drawing ({round(time.perf_counter() - started)}s)")
                except Exception:
                    pass
                response = requests.get(f"https://api.nvcf.nvidia.com/v2/nvcf/pexec/status/{request_id}",
                                        headers=headers, timeout=60)
        except requests.RequestException as error:
            raise ModelCallError(f"NVIDIA image service could not be reached: {_scrub(error, key)}") from error
        if response.status_code == 202:
            raise ModelCallError(f"NVIDIA ({chosen}) was still queued after {round(timeout)}s.")
        if response.status_code != 200:
            raise ModelCallError(f"NVIDIA ({chosen}) answered {response.status_code}: {_scrub(response.text, key)}")
        data = response.json()
        artifacts = data.get("artifacts") or []
        encoded = artifacts[0].get("base64") if artifacts else data.get("image")
        if not encoded:
            reason = artifacts[0].get("finishReason") if artifacts else "no image returned"
            raise ModelCallError(f"NVIDIA ({chosen}) produced no image ({reason}).")
        image_bytes = base64.b64decode(encoded)
        mime = "image/jpeg" if image_bytes[:3] == b"\xff\xd8\xff" else "image/png"
        return GeneratedImage(image_bytes, mime, name, chosen, round((time.perf_counter() - started) * 1000))

    if name == "openai":
        key = api_key_for("openai")
        if not key:
            raise ModelCallError("OpenAI has no API key yet. Add one in Keys.")
        body: Dict[str, Any] = {"model": chosen, "prompt": clean, "size": f"{width}x{height}", "n": 1}
        if chosen.startswith("dall-e"):
            body["response_format"] = "b64_json"
        try:
            response = requests.post("https://api.openai.com/v1/images/generations", json=body, timeout=timeout,
                                     headers={"Authorization": f"Bearer {key}"})
        except requests.RequestException as error:
            raise ModelCallError(f"OpenAI images could not be reached: {_scrub(error, key)}") from error
        if response.status_code != 200:
            raise ModelCallError(f"OpenAI ({chosen}) answered {response.status_code}: {_scrub(response.text, key)}")
        item = (response.json().get("data") or [{}])[0]
        if not item.get("b64_json"):
            raise ModelCallError(f"OpenAI ({chosen}) returned no image data.")
        return GeneratedImage(base64.b64decode(item["b64_json"]), "image/png", name, chosen,
                              round((time.perf_counter() - started) * 1000), item.get("revised_prompt", ""))

    if name == "gemini":
        key = api_key_for("gemini")
        if not key:
            raise ModelCallError("Gemini has no API key yet. Add one in Keys.")
        payload = {"contents": [{"role": "user", "parts": [{"text": clean}]}],
                   "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}
        try:
            response = requests.post(_GEMINI_BASE + chosen + ":generateContent", params={"key": key},
                                     json=payload, timeout=timeout)
        except requests.RequestException as error:
            raise ModelCallError(f"Gemini could not be reached: {_scrub(error, key)}") from error
        if response.status_code != 200:
            raise ModelCallError(f"Gemini ({chosen}) answered {response.status_code}: {_scrub(response.text, key)}")
        for part in (response.json().get("candidates") or [{}])[0].get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return GeneratedImage(base64.b64decode(inline["data"]), inline.get("mimeType", "image/png"),
                                      name, chosen, round((time.perf_counter() - started) * 1000))
        raise ModelCallError(f"Gemini ({chosen}) returned no image.")

    if name == "aws":
        creds = aws_credentials()
        if not (creds["access_key_id"] and creds["secret_access_key"]):
            raise ModelCallError("AWS is not set up: add an access key ID, secret access key and region in Keys.")
        url = f"https://bedrock-runtime.{creds['region']}.amazonaws.com/model/{urllib.parse.quote(chosen, safe='')}/invoke"
        body_bytes = json.dumps({
            "taskType": "TEXT_IMAGE",
            "textToImageParams": {"text": clean},
            "imageGenerationConfig": {"numberOfImages": 1, "width": width, "height": height},
        }).encode("utf-8")
        headers = sigv4_headers("POST", url, body_bytes, region=creds["region"], service="bedrock",
                                access_key=creds["access_key_id"], secret_key=creds["secret_access_key"],
                                session_token=creds["session_token"])
        try:
            response = requests.post(url, data=body_bytes, headers=headers, timeout=timeout)
        except requests.RequestException as error:
            raise ModelCallError(f"AWS Bedrock could not be reached: {_scrub(error, creds['secret_access_key'])}") from error
        if response.status_code != 200:
            raise ModelCallError(f"AWS ({chosen}) answered {response.status_code}: "
                                 f"{_scrub(response.text, creds['secret_access_key'])}")
        images_out = response.json().get("images") or []
        if not images_out:
            raise ModelCallError(f"AWS ({chosen}) returned no image.")
        return GeneratedImage(base64.b64decode(images_out[0]), "image/png", name, chosen,
                              round((time.perf_counter() - started) * 1000))

    if name == "pollinations":
        try:
            response = requests.get(
                "https://image.pollinations.ai/prompt/" + urllib.parse.quote(clean[:900], safe=""),
                params={"width": min(width, 1024), "height": min(height, 1024), "nologo": "true",
                        "model": chosen, "seed": int(time.time()) % 100000},
                timeout=min(timeout, 120),
            )
        except requests.RequestException as error:
            raise ModelCallError(f"Pollinations could not be reached ({error.__class__.__name__}).") from error
        kind = response.headers.get("content-type", "")
        if response.status_code != 200 or not kind.startswith("image"):
            raise ModelCallError(f"Pollinations answered {response.status_code}: {response.text[:200]}")
        return GeneratedImage(response.content, kind.split(";")[0], name, chosen,
                              round((time.perf_counter() - started) * 1000))

    raise ModelCallError(f"{name} cannot generate images here. Use nvidia, gemini, openai, aws or pollinations.")


# ---------------------------------------------------------------------------
# Model catalogues (for the pickers)
# ---------------------------------------------------------------------------

_catalog_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_catalog_lock = threading.Lock()
_CATALOG_TTL = 3600.0


def _classify(model_id: str) -> List[str]:
    lowered = model_id.lower()
    jobs: List[str] = []
    if any(w in lowered for w in ("vision", "-vl", "llava", "pixtral", "gpt-4o", "gemini", "nova-lite", "nova-pro",
                                   "llama-4", "phi-3-vision", "phi-4-multimodal", "claude")):
        jobs.append("vision")
    if any(w in lowered for w in ("flux", "stable-diffusion", "sdxl", "imagen", "-image", "canvas", "dall-e", "gpt-image")):
        jobs.append("image")
    if "embed" in lowered or "rerank" in lowered:
        jobs.append("embedding")
    elif "image" not in jobs or "gemini" in lowered:
        jobs.append("text")
    return jobs


def list_models(provider: str, refresh: bool = False) -> List[Dict[str, Any]]:
    """Models a provider offers, tagged by job (text / vision / image / embedding)."""
    name = (provider or "").strip().lower()
    with _catalog_lock:
        cached = _catalog_cache.get(name)
    if cached and not refresh and time.time() - cached[0] < _CATALOG_TTL:
        return cached[1]

    ids: List[str] = []
    try:
        if name == "nvidia" and api_key_for("nvidia"):
            response = requests.get("https://integrate.api.nvidia.com/v1/models", timeout=15,
                                    headers={"Authorization": f"Bearer {api_key_for('nvidia')}"})
            ids = NVIDIA_FEATURED_MODELS + [m["id"] for m in response.json().get("data", [])] + NVIDIA_IMAGE_MODELS
        elif name == "gemini" and api_key_for("gemini"):
            response = requests.get(_GEMINI_BASE.rstrip("/"), params={"key": api_key_for("gemini"), "pageSize": 200},
                                    timeout=15)
            ids = [m["name"].split("/")[-1] for m in response.json().get("models", [])
                   if "generateContent" in m.get("supportedGenerationMethods", [])]
        elif (name in OPENAI_CHAT_URLS or name == "qwen") and api_key_for(name):
            base = (_qwen_chat_url() if name == "qwen" else OPENAI_CHAT_URLS[name]).rsplit("/chat/completions", 1)[0]
            response = requests.get(base + "/models", timeout=15, headers={"Authorization": f"Bearer {api_key_for(name)}"})
            ids = [m["id"] for m in response.json().get("data", [])]
        elif name == "ollama":
            response = requests.get(_ollama_host() + "/api/tags", timeout=1.5)
            ids = [m.get("name", "") for m in response.json().get("models", [])]
    except Exception:
        ids = []

    if not ids:
        ids = sorted(set(DEFAULT_MODELS.get(name, {}).values()))
        if name == "nvidia":
            ids = NVIDIA_FEATURED_MODELS + sorted(set(ids) | set(NVIDIA_IMAGE_MODELS))
        if name == "aws":
            ids = ["amazon.nova-micro-v1:0", "amazon.nova-lite-v1:0", "amazon.nova-pro-v1:0",
                   "amazon.nova-canvas-v1:0", "anthropic.claude-3-5-haiku-20241022-v1:0",
                   "meta.llama3-2-11b-instruct-v1:0"]

    catalog = [{"id": model_id, "jobs": _classify(model_id)} for model_id in dict.fromkeys(ids) if model_id]
    with _catalog_lock:
        _catalog_cache[name] = (time.time(), catalog)
    return catalog
