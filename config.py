"""Centralized application settings loaded from local environment files."""

import os
from secret_store import get_keys
from dataclasses import dataclass, fields

from dotenv import load_dotenv

from paths import env_files

# Load every candidate dotenv, most specific first. These paths are anchored to
# the project (see paths.py), NOT to the current working directory: the previous
# `load_dotenv(".env.local")` silently loaded nothing whenever the process was
# started from the parent folder, so every provider reported "no API key
# configured" while a valid key sat one directory away.
#
# override=False means the first file to define a name wins, and a name already
# present in the real environment always beats a file.
for _env_file in env_files():
    load_dotenv(_env_file, override=False)


@dataclass
class Settings:
    """Settings shared by providers without exposing secret handling to them."""

    anthropic_api_key: str
    openai_api_key: str
    perplexity_api_key: str
    google_api_key: str
    google_cse_id: str
    bing_api_key: str
    gemini_api_key: str
    kimi_api_key: str
    deepseek_api_key: str
    groq_api_key: str
    nvidia_api_key: str
    gemini_model: str
    deepseek_model: str
    kimi_model: str
    groq_model: str
    nvidia_model: str
    ollama_host: str
    ollama_model: str
    preferred_online_provider: str
    free_only: bool
    folder_registry_path: str
    #: A stronger Gemini model for turns that plan, use tools, or delegate. The
    #: fast model stays the default for quick answers; the router falls back to it
    #: when the smart one is busy (gemini-3.8-flash answered 503 "high demand"
    #: during measurement) so a turn never fails because of this choice.
    gemini_smart_model: str = "gemini-3.5-flash"
    #: Ask models for their thought summaries so the UI can show real reasoning.
    show_thinking: bool = True
    #: Tool steps allowed in one turn. Computer control and multi-step jobs need
    #: far more than the old five; the loop still ends with a forced answer.
    max_tool_steps: int = 24
    #: Qwen on Alibaba Cloud Model Studio (Request R17). The address depends on the key's region, so it is
    #: saved next to the key in Keys & Models (empty = Singapore, see providers/qwen_provider.py).
    qwen_api_key: str = ""
    qwen_model: str = "qwen-plus"
    qwen_base_url: str = ""


#: Settings saved from the Keys tab that are not keys but must apply live all the same.
_KEY_LIKE_FIELDS = frozenset({"qwen_base_url"})


def _first_key(*names: str) -> str:
    """The first of several variable names that holds a key — environment first, then the secret store."""
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    for name in names:
        stored = (get_keys(name) or [""])[0]
        if stored:
            return stored
    return ""


def load_settings() -> Settings:
    """Read normalized settings once so providers share one configuration path."""

    return Settings(
        anthropic_api_key=(os.getenv("ANTHROPIC_API_KEY", "").strip() or (get_keys("ANTHROPIC_API_KEY") or [""])[0]),
        openai_api_key=(os.getenv("OPENAI_API_KEY", "").strip() or (get_keys("OPENAI_API_KEY") or [""])[0]),
        perplexity_api_key=(os.getenv("PERPLEXITY_API_KEY", "").strip() or (get_keys("PERPLEXITY_API_KEY") or [""])[0]),
        google_api_key=os.getenv("GOOGLE_API_KEY", "").strip(),
        google_cse_id=os.getenv("GOOGLE_CSE_ID", "").strip(),
        bing_api_key=os.getenv("BING_API_KEY", "").strip(),
        gemini_api_key=(os.getenv("GEMINI_API_KEY", "").strip() or (get_keys("GEMINI_API_KEY") or [""])[0]),
        kimi_api_key=(os.getenv("KIMI_API_KEY", "").strip() or (get_keys("KIMI_API_KEY") or [""])[0]),
        deepseek_api_key=(os.getenv("DEEPSEEK_API_KEY", "").strip() or (get_keys("DEEPSEEK_API_KEY") or [""])[0]),
        groq_api_key=(os.getenv("GROQ_API_KEY", "").strip() or (get_keys("GROQ_API_KEY") or [""])[0]),
        nvidia_api_key=(os.getenv("NVIDIA_API_KEY", "").strip() or (get_keys("NVIDIA_API_KEY") or [""])[0]),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
        kimi_model=os.getenv("KIMI_MODEL", "moonshot-v1-8k").strip(),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        nvidia_model=os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3-super-120b-a12b").strip(),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").strip(),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1").strip(),
        preferred_online_provider=os.getenv(
            "PREFERRED_ONLINE_PROVIDER", "gemini"
        ).strip().lower(),
        free_only=os.getenv("FREE_ONLY", "true").strip().lower() in ("1", "true", "yes", "on"),
        folder_registry_path=os.getenv("FOLDER_REGISTRY_PATH", "folder_registry.json").strip(),
        gemini_smart_model=os.getenv("GEMINI_SMART_MODEL", "gemini-3.5-flash").strip(),
        show_thinking=os.getenv("NYX_SHOW_THINKING", "true").strip().lower() in ("1", "true", "yes", "on"),
        max_tool_steps=_int_env("NYX_MAX_TOOL_STEPS", 24, low=3, high=80),
        qwen_api_key=_first_key("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
        qwen_model=os.getenv("QWEN_MODEL", "qwen-plus").strip() or "qwen-plus",
        qwen_base_url=_first_key("QWEN_BASE_URL", "DASHSCOPE_BASE_URL"),
    )


def _int_env(name: str, default: int, low: int, high: int) -> int:
    """An integer setting clamped to a sane range; junk falls back to the default."""
    try:
        return max(low, min(high, int(os.getenv(name, str(default)).strip())))
    except ValueError:
        return default


SETTINGS = load_settings()

if "pytest" not in __import__("sys").modules and os.getenv("NYX_IGNORE_MODEL_CHOICE", "") != "1":
    # The owner's last pick survives restarts (Request H6: it kept "going back to Gemini").
    try:
        from model_choice import apply as _apply_model_choice

        _apply_model_choice(SETTINGS)
    except Exception:  # pragma: no cover
        pass


def reload_keys() -> list[str]:
    """Re-read every API key into the live ``SETTINGS`` object, in place.

    ``SETTINGS`` is a mutable dataclass that providers read at call time, so a
    key saved through the UI or the CLI can take effect immediately. Without
    this, the app would have to tell the user to restart right after they typed
    their key in — the exact moment they will conclude it did not work.

    Only ``*_api_key`` fields are refreshed. A wholesale reload would also reset
    ``preferred_online_provider`` and ``ollama_model``, which ``/api/models/
    switch`` sets deliberately at runtime; that regression is why this is
    narrow rather than a plain ``SETTINGS = load_settings()``.

    Returns the names of the fields that actually changed.
    """
    fresh = load_settings()
    changed: list[str] = []
    for field in fields(Settings):
        if not (field.name.endswith("_api_key") or field.name in _KEY_LIKE_FIELDS):
            continue
        value = getattr(fresh, field.name)
        if value != getattr(SETTINGS, field.name):
            setattr(SETTINGS, field.name, value)
            changed.append(field.name)
    return changed

