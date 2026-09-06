"""Tests for the intelligent request router."""

from unittest.mock import MagicMock, patch

import pytest

from providers.base import ProviderError
from router import Router


@pytest.fixture
def mock_device_profile():
    """Mock device profile for testing."""
    from device_profile import DeviceProfile

    return DeviceProfile(
        operating_system="Windows",
        cpu_name="Intel Core i7",
        cpu_cores=8,
        ram_gb=16.0,
        gpu_name="NVIDIA GeForce RTX 4070",
        vram_gb=12.0,
    )


@patch("router.get_device_profile")
@patch("router.select_tier")
def test_router_initialization(mock_tier, mock_profile):
    """Test that router initializes with device profile."""
    from device_profile import Tier

    mock_profile.return_value = MagicMock()
    mock_tier.return_value = Tier(name="large", model_tag="qwen2.5-coder:14b")

    router = Router()
    assert router.device_profile is not None
    assert router.device_tier.name == "large"


@patch("router.is_online")
@patch("router.get_device_profile")
@patch("router.select_tier")
@patch("router.OllamaProvider")
@patch("router.PerplexityProvider")
def test_local_preferred_when_both_available(
    mock_perplexity_class, mock_ollama_class, mock_tier, mock_profile, mock_online
):
    """Test that local provider is preferred when device is capable and both are available."""
    from device_profile import Tier

    mock_profile.return_value = MagicMock()
    mock_tier.return_value = Tier(name="large", model_tag="qwen2.5-coder:14b")
    mock_online.return_value = True

    mock_ollama = MagicMock()
    mock_ollama.is_available.return_value = True
    mock_ollama.name = "ollama"
    mock_ollama_class.return_value = mock_ollama

    mock_perplexity = MagicMock()
    mock_perplexity.is_available.return_value = True
    mock_perplexity.name = "perplexity"
    mock_perplexity_class.return_value = mock_perplexity

    router = Router()
    primary = router._get_primary_provider()

    # Local should be primary (privacy/speed preference)
    assert primary.name == "ollama"


@patch("router.is_online", return_value=True)
@patch("router.get_device_profile")
@patch("router.select_tier")
@patch("router.SAFETY_MONITOR")
def test_free_only_skips_paid_even_when_preferred(mock_safety, mock_tier, mock_profile, mock_online):
    """Free-only mode must never pick a paid provider, even when it is the preferred one."""
    from types import SimpleNamespace

    from device_profile import Tier

    mock_profile.return_value = MagicMock()
    mock_tier.return_value = Tier(name="tiny", model_tag="llama3.2:1b")  # local not suitable
    mock_safety.is_safe_to_run.return_value = (True, "ok")

    with patch("router.SETTINGS", SimpleNamespace(free_only=True, preferred_online_provider="claude")):
        router = Router(web_access=True)
        order = router._online_order()
        primary = router._get_primary_provider()

    assert "claude" not in order
    assert primary.name == "gemini"  # first free provider after paid preference is filtered out


@patch("router.SETTINGS")
def test_direct_chat_blocks_paid_in_free_only(mock_settings):
    """Explicit paid calls are refused while free-only mode is on."""
    mock_settings.free_only = True
    router = Router(web_access=False)
    with pytest.raises(ProviderError, match="free-only"):
        router.direct_chat([{"role": "user", "content": "hi"}], "claude")


@patch("router.SETTINGS")
def test_online_order_free_first_with_paid_retained_when_opted_out(mock_settings):
    """Turning free-only off restores paid providers at the back of the order."""
    mock_settings.free_only = False
    mock_settings.preferred_online_provider = "gemini"
    router = Router(web_access=False)
    order = router._online_order()
    assert order == ["gemini", "groq", "claude", "openai", "kimi", "deepseek", "perplexity"]


@patch("router.is_online")
@patch("router.get_device_profile")
@patch("router.select_tier")
@patch("router.OllamaProvider")
@patch("router.GeminiProvider")
def test_fallback_to_gemini_when_local_unavailable(
    mock_gemini_class, mock_ollama_class, mock_tier, mock_profile, mock_online
):
    """Free-first fallback to Gemini when local Ollama is down."""
    from device_profile import Tier

    mock_profile.return_value = MagicMock()
    mock_tier.return_value = Tier(name="large", model_tag="qwen3.6:35b")
    mock_online.return_value = True

    mock_ollama = MagicMock()
    mock_ollama.is_available.return_value = False
    mock_ollama.name = "ollama"
    mock_ollama_class.return_value = mock_ollama

    mock_gemini = MagicMock()
    mock_gemini.is_available.return_value = True
    mock_gemini.name = "gemini"
    mock_gemini_class.return_value = mock_gemini

    router = Router()
    primary = router._get_primary_provider()

    # Free-only mode makes Gemini the first online option
    assert primary.name == "gemini"


@patch("router.is_online")
@patch("router.get_device_profile")
@patch("router.select_tier")
@patch("router.OllamaProvider")
@patch("router.GeminiProvider")
def test_tiny_device_prefers_online(
    mock_gemini_class, mock_ollama_class, mock_tier, mock_profile, mock_online
):
    """Tiny-tier devices prefer the first free online provider."""
    from device_profile import Tier

    mock_profile.return_value = MagicMock()
    mock_tier.return_value = Tier(name="tiny", model_tag="llama3.2:1b")
    mock_online.return_value = True

    mock_ollama = MagicMock()
    mock_ollama.is_available.return_value = True
    mock_ollama.name = "ollama"
    mock_ollama_class.return_value = mock_ollama

    mock_gemini = MagicMock()
    mock_gemini.is_available.return_value = True
    mock_gemini.name = "gemini"
    mock_gemini_class.return_value = mock_gemini

    router = Router()
    primary = router._get_primary_provider()

    # Tiny tier skips local; free-only picks Gemini first
    assert primary.name == "gemini"


@patch("router.is_online")
@patch("router.get_device_profile")
@patch("router.select_tier")
@patch("router.OllamaProvider")
@patch("router.GeminiProvider")
def test_chat_with_provider_fallback(
    mock_gemini_class, mock_ollama_class, mock_tier, mock_profile, mock_online
):
    """Free-first fallback fires on primary failure."""
    from device_profile import Tier

    mock_profile.return_value = MagicMock()
    mock_tier.return_value = Tier(name="large", model_tag="qwen3.6:35b")
    mock_online.return_value = True

    messages = [{"role": "user", "content": "Hello"}]

    mock_ollama = MagicMock()
    mock_ollama.is_available.return_value = True
    mock_ollama.chat.side_effect = ProviderError("Ollama error")
    mock_ollama.name = "ollama"
    mock_ollama_class.return_value = mock_ollama

    mock_gemini = MagicMock()
    mock_gemini.is_available.return_value = True
    mock_gemini.chat.return_value = "Hello from Gemini"
    mock_gemini.name = "gemini"
    mock_gemini_class.return_value = mock_gemini

    router = Router()
    response, provider = router.chat(messages)

    assert response == "Hello from Gemini"
    assert provider == "gemini"


@patch("router.is_online")
@patch("router.get_device_profile")
@patch("router.select_tier")
@patch("router.OllamaProvider")
@patch("router.GeminiProvider")
def test_all_providers_fail(
    mock_gemini_class, mock_ollama_class, mock_tier, mock_profile, mock_online
):
    """ProviderError is raised when every free provider fails (no real network)."""
    from device_profile import Tier

    mock_profile.return_value = MagicMock()
    mock_tier.return_value = Tier(name="large", model_tag="qwen3.6:35b")
    mock_online.return_value = True

    messages = [{"role": "user", "content": "Hello"}]

    mock_ollama = MagicMock()
    mock_ollama.is_available.return_value = True
    mock_ollama.chat.side_effect = ProviderError("Ollama error")
    mock_ollama.name = "ollama"
    mock_ollama_class.return_value = mock_ollama

    mock_gemini = MagicMock()
    mock_gemini.is_available.return_value = True
    mock_gemini.chat.side_effect = ProviderError("Gemini error")
    mock_gemini.name = "gemini"
    mock_gemini_class.return_value = mock_gemini

    router = Router()

    with pytest.raises(ProviderError):
        router.chat(messages)


@patch("router.is_online")
@patch("router.get_device_profile")
@patch("router.select_tier")
@patch("router.OllamaProvider")
@patch("router.PerplexityProvider")
def test_get_status(
    mock_perplexity_class, mock_ollama_class, mock_tier, mock_profile, mock_online
):
    """Test that router returns accurate status information."""
    from device_profile import DeviceProfile, Tier

    mock_profile.return_value = DeviceProfile(
        operating_system="Windows",
        cpu_name="Intel Core i7",
        cpu_cores=8,
        ram_gb=16.0,
        gpu_name="RTX 4070",
        vram_gb=12.0,
    )
    mock_tier.return_value = Tier(name="large", model_tag="qwen2.5-coder:14b")
    mock_online.return_value = True

    mock_ollama = MagicMock()
    mock_ollama.is_available.return_value = True
    mock_ollama.name = "ollama"
    mock_ollama_class.return_value = mock_ollama

    mock_perplexity = MagicMock()
    mock_perplexity.is_available.return_value = True
    mock_perplexity.name = "perplexity"
    mock_perplexity_class.return_value = mock_perplexity

    router = Router()
    status = router.get_status()

    assert status["device_tier"] == "large"
    assert status["online"] is True
    assert status["ollama_available"] is True
    assert status["perplexity_available"] is True
    assert status["device_profile"]["cpu_cores"] == 8

