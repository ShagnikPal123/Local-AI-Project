"""Regression cover for the chat outage and latency fixes (ROADMAP D/N7).

Session 2 symptom: chat always replied with the canned offline text. Causes were
(a) Gemini pinned to a retired model, (b) the router giving up after a single
fallback, and (c) a 4s Ollama probe paid twice per turn.
"""

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from providers.base import ProviderError
from providers.gemini_provider import GeminiProvider, _scrub_key
from providers.ollama_provider import OllamaProvider


# --- Gemini: retired-model and key-leak handling -------------------------------

def test_gemini_default_model_is_not_a_retired_one():
    """gemini-2.0/2.5-flash return 404 for keys issued after their sunset."""
    assert GeminiProvider._MODEL not in {"gemini-2.0-flash", "gemini-2.5-flash"}


def test_gemini_error_surfaces_api_message_not_status_code():
    """The API explains retired models; a bare status code does not."""
    with patch("providers.gemini_provider.SETTINGS") as settings:
        settings.gemini_api_key = "test-key"
        settings.gemini_model = "gemini-flash-lite-latest"
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("404 Client Error")
        response.json.return_value = {
            "error": {"message": "This model is no longer available to new users."}
        }
        with patch("providers.gemini_provider.requests.post", return_value=response):
            with pytest.raises(ProviderError) as excinfo:
                GeminiProvider().chat([{"role": "user", "content": "hi"}])
    assert "no longer available" in str(excinfo.value)


def test_gemini_does_not_retry_permanent_failures():
    """A 404 will never succeed on retry; retrying it just added dead latency."""
    with patch("providers.gemini_provider.SETTINGS") as settings:
        settings.gemini_api_key = "test-key"
        settings.gemini_model = "gemini-flash-lite-latest"
        response = MagicMock()
        response.raise_for_status.side_effect = requests.HTTPError("404")
        response.json.return_value = {"error": {"message": "gone"}}
        with patch(
            "providers.gemini_provider.requests.post", return_value=response
        ) as post:
            with pytest.raises(ProviderError):
                GeminiProvider().chat([{"role": "user", "content": "hi"}])
    assert post.call_count == 1


def test_api_key_is_scrubbed_from_error_text():
    """requests embeds the key-bearing URL in exceptions; it must not escape."""
    leaked = (
        "404 Client Error for url: https://generativelanguage.googleapis.com/"
        "v1beta/models/x:generateContent?key=SUPERSECRETVALUE"
    )
    scrubbed = _scrub_key(leaked)
    assert "SUPERSECRETVALUE" not in scrubbed
    assert "[REDACTED]" in scrubbed


# --- Ollama: the probe that cost ~8s per turn ----------------------------------

def test_ollama_probe_is_cached():
    """The router asks more than once per turn; only one probe should happen."""
    provider = OllamaProvider()
    with patch(
        "providers.ollama_provider.requests.get",
        side_effect=requests.ConnectionError("refused"),
    ) as get:
        assert provider.is_available() is False
        assert provider.is_available() is False
        assert provider.is_available() is False
    assert get.call_count == 1


def test_ollama_probe_cache_can_be_reset():
    provider = OllamaProvider()
    with patch(
        "providers.ollama_provider.requests.get",
        side_effect=requests.ConnectionError("refused"),
    ) as get:
        provider.is_available()
        provider.reset_availability_cache()
        provider.is_available()
    assert get.call_count == 2


def test_ollama_probe_timeout_is_short():
    """A loopback health check must not hold the turn for seconds."""
    assert OllamaProvider._PROBE_TIMEOUT_SECONDS <= 2.0


# --- Router: cascade through the whole chain, not primary + 1 ------------------

@patch("router.is_online")
@patch("router.get_device_profile")
@patch("router.select_tier")
def test_router_walks_past_a_broken_provider(mock_tier, mock_profile, mock_online):
    """One misconfigured provider must not end the request.

    This is the outage: Gemini was pinned to a retired model, the router tried it
    plus exactly one fallback, and the whole turn collapsed into the offline reply
    while a working provider sat unused behind it.
    """
    from device_profile import Tier
    from router import Router

    mock_profile.return_value = MagicMock()
    mock_tier.return_value = Tier(name="large", model_tag="qwen3.6:35b")
    mock_online.return_value = True

    router = Router()

    broken = MagicMock()
    broken.name = "broken"
    broken.is_available.return_value = True
    broken.chat.side_effect = ProviderError("retired model")

    working = MagicMock()
    working.name = "working"
    working.is_available.return_value = True
    working.chat.return_value = "real answer"

    with patch.object(router, "_candidate_chain", return_value=[broken, working]):
        response, provider = router.chat([{"role": "user", "content": "hi"}])

    assert response == "real answer"
    assert provider == "working"
    assert broken.chat.call_count == 1


@patch("router.is_online")
@patch("router.get_device_profile")
@patch("router.select_tier")
def test_router_reports_every_failure_when_all_fail(mock_tier, mock_profile, mock_online):
    """The aggregated error should name each provider so the cause is diagnosable."""
    from device_profile import Tier
    from router import Router

    mock_profile.return_value = MagicMock()
    mock_tier.return_value = Tier(name="large", model_tag="qwen3.6:35b")
    mock_online.return_value = True

    router = Router()

    def dead(name, message):
        p = MagicMock()
        p.name = name
        p.is_available.return_value = True
        p.chat.side_effect = ProviderError(message)
        return p

    chain = [dead("alpha", "bad key"), dead("beta", "retired model")]
    with patch.object(router, "_candidate_chain", return_value=chain):
        with pytest.raises(ProviderError) as excinfo:
            router.chat([{"role": "user", "content": "hi"}])

    text = str(excinfo.value)
    assert "alpha" in text and "bad key" in text
    assert "beta" in text and "retired model" in text


# --- the probe must not silently double its own timeout ------------------------------

def test_the_probe_pins_the_ipv4_loopback():
    """"localhost" resolves to ::1 AND 127.0.0.1, and requests tries each in turn.

    A timeout written as 0.5s then costs 1s when the service is absent. Pinning
    the literal keeps the budget honest — this is why /api/status took 2.2s and
    /api/models took 4.1s for anyone without Ollama running.
    """
    with patch("providers.ollama_provider.SETTINGS") as settings:
        settings.ollama_host = "http://localhost:11434"
        url = OllamaProvider._probe_url("/api/tags")
    assert "localhost" not in url
    assert url == "http://127.0.0.1:11434/api/tags"


def test_a_non_localhost_host_is_left_alone():
    """A remote Ollama must not be rewritten to point at this machine."""
    with patch("providers.ollama_provider.SETTINGS") as settings:
        settings.ollama_host = "http://192.168.1.50:11434"
        url = OllamaProvider._probe_url("/api/tags")
    assert url == "http://192.168.1.50:11434/api/tags"


def test_listing_models_short_circuits_when_the_server_is_down():
    """Otherwise it pays a second full timeout after availability already failed."""
    provider = OllamaProvider()
    with patch(
        "providers.ollama_provider.requests.get",
        side_effect=requests.ConnectionError("refused"),
    ) as get:
        assert provider.list_models() == []
        assert provider.list_models() == []
    # One probe total: the availability check, cached thereafter.
    assert get.call_count == 1


def test_is_model_installed_reuses_the_same_short_circuit():
    provider = OllamaProvider()
    with patch(
        "providers.ollama_provider.requests.get",
        side_effect=requests.ConnectionError("refused"),
    ) as get:
        assert provider.is_model_installed("llama3.1") is False
    assert get.call_count == 1


def test_connectivity_is_probed_once_per_status_call():
    """get_status used to call is_online() twice for the same fact."""
    from unittest.mock import MagicMock

    with patch("router.is_online", return_value=True) as online, \
         patch("router.get_device_profile", return_value=MagicMock()), \
         patch("router.select_tier", return_value=MagicMock(name_="large")) as tier:
        tier.return_value.name = "large"
        from router import Router

        Router().get_status()
    assert online.call_count == 1
