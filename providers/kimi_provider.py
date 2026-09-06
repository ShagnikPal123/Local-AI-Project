"""Moonshot (Kimi) API provider — OpenAI-compatible chat endpoint."""

from __future__ import annotations

from providers.compat import OpenAICompatibleProvider


class KimiProvider(OpenAICompatibleProvider):
    """Access Moonshot's Kimi models via their OpenAI-compatible endpoint."""

    name = "kimi"
    chat_url = "https://api.moonshot.cn/v1/chat/completions"
    model = "moonshot-v1-8k"
    api_key_field = "kimi_api_key"
    model_field = "kimi_model"
