"""Qwen (Alibaba Cloud Model Studio, "DashScope") — OpenAI-compatible chat endpoint.

The owner asked (Request R17): "Allow me to add qwen as a provider in key if not already done."

Keys come from https://modelstudio.console.alibabacloud.com/model/settings/api-key and live in
``QWEN_API_KEY`` (``DASHSCOPE_API_KEY`` is read too, since that is the name Alibaba's own docs use).

The address depends on the region the key belongs to, so it is a setting rather than a constant:
``QWEN_BASE_URL`` may be the Singapore default below, ``https://dashscope-us.aliyuncs.com/compatible-mode/v1``
(Virginia), a workspace address (``https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1``)
or Beijing's ``https://dashscope.aliyuncs.com/compatible-mode/v1``. A base URL is completed to
``…/chat/completions`` here, so the owner can paste whatever the console shows.

New accounts get a free token quota per model; after that it bills, so free-only mode keeps Qwen out of
*automatic* fallback while picking it by hand still works (router ``_paid_names``).
"""

from __future__ import annotations

from config import SETTINGS
from providers.compat import OpenAICompatibleProvider

#: Singapore (international). Alibaba calls these hostnames "legacy", but they need no workspace id and still answer.
DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen-plus"
SIGNUP_URL = "https://modelstudio.console.alibabacloud.com/model/settings/api-key"


def chat_url_from(base: str) -> str:
    """Whatever the owner pasted (a base URL or the full endpoint) → the chat-completions URL."""
    clean = (base or "").strip().rstrip("/") or DEFAULT_BASE_URL
    if clean.endswith("/chat/completions"):
        return clean
    return clean + "/chat/completions"


class QwenProvider(OpenAICompatibleProvider):
    """Qwen models (qwen-plus, qwen-max, qwen-flash, qwen3-coder-plus, qwen-vl-plus…) on Model Studio."""

    name = "qwen"
    model = DEFAULT_MODEL
    api_key_field = "qwen_api_key"
    model_field = "qwen_model"

    @property  # type: ignore[override]
    def chat_url(self) -> str:  # read at call time so a region change in Keys applies at once
        return chat_url_from(getattr(SETTINGS, "qwen_base_url", "") or DEFAULT_BASE_URL)
