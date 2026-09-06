"""DeepSeek API provider (deepseek-chat / deepseek-reasoner)."""

from __future__ import annotations

from providers.compat import OpenAICompatibleProvider


class DeepSeekProvider(OpenAICompatibleProvider):
    """Access DeepSeek models via their OpenAI-compatible chat endpoint."""

    name = "deepseek"
    chat_url = "https://api.deepseek.com/chat/completions"
    model = "deepseek-chat"
    api_key_field = "deepseek_api_key"
    model_field = "deepseek_model"
