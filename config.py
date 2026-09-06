"""Centralized application settings loaded from local environment files."""

import os
from secret_store import get_keys
from dataclasses import dataclass

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
    gemini_model: str
    deepseek_model: str
    kimi_model: str
    groq_model: str
    ollama_host: str
    ollama_model: str
    preferred_online_provider: str
    free_only: bool
    folder_registry_path: str


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
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip(),
        kimi_model=os.getenv("KIMI_MODEL", "moonshot-v1-8k").strip(),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip(),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").strip(),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1").strip(),
        preferred_online_provider=os.getenv(
            "PREFERRED_ONLINE_PROVIDER", "gemini"
        ).strip().lower(),
        free_only=os.getenv("FREE_ONLY", "true").strip().lower() in ("1", "true", "yes", "on"),
        folder_registry_path=os.getenv("FOLDER_REGISTRY_PATH", "folder_registry.json").strip(),
    )


SETTINGS = load_settings()

