"""NVIDIA NIM provider — high-performance inference via OpenAI-compatible endpoints.

NVIDIA provides zero-cost API trial credits and keys at:
    https://build.nvidia.com/models

Supported models include:
    - nvidia/nemotron-3-super-120b-a12b (default; ~1 s)
    - nvidia/nemotron-3-ultra-550b-a55b (largest; slower, strongest reasoning)
    - nvidia/nemotron-3.5-lightning-30b-a3b
    (meta/llama-3.3-70b-instruct was retired by NVIDIA on 2026-08-26.)
    - deepseek-ai/deepseek-r1
    - mistralai/mixtral-8x7b-instruct-v0.1
"""

from __future__ import annotations

from providers.compat import OpenAICompatibleProvider


class NvidiaProvider(OpenAICompatibleProvider):
    """Access NVIDIA NIM hosted models with free tier API keys from build.nvidia.com/models."""

    name = "nvidia"
    chat_url = "https://integrate.api.nvidia.com/v1/chat/completions"
    model = "nvidia/nemotron-3-super-120b-a12b"
    api_key_field = "nvidia_api_key"
    model_field = "nvidia_model"
