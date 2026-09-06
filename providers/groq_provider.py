"""Groq provider — very fast open-model inference via an OpenAI-compatible endpoint."""

from __future__ import annotations

from providers.compat import OpenAICompatibleProvider


class GroqProvider(OpenAICompatibleProvider):
    """Access Groq's fast open-model endpoints (Llama, Mixtral, Qwen, ...)."""

    name = "groq"
    chat_url = "https://api.groq.com/openai/v1/chat/completions"
    model = "llama-3.3-70b-versatile"
    api_key_field = "groq_api_key"
    model_field = "groq_model"
