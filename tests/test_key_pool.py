"""Several keys per provider, failover, retry every 5th request, owner alerts, and "paid" only when the API says so (H8, H11)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import key_pool


@pytest.fixture()
def keys(monkeypatch):
    stored = {"GROQ_API_KEY": ["gsk-first-key-aaaa", "gsk-second-key-bbbb"]}
    settings = SimpleNamespace(groq_api_key="gsk-first-key-aaaa")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(key_pool, "_settings", lambda: settings)
    import secret_store

    monkeypatch.setattr(secret_store, "get_keys", lambda name: list(stored.get(name, [])))
    monkeypatch.setattr(secret_store, "set_keys", lambda name, values: stored.__setitem__(name, list(values)) or list(values))
    return stored, settings


def test_payment_is_only_what_the_api_said_and_a_free_tier_rate_limit_is_not_payment():
    assert key_pool.classify("deepseek request failed: HTTP 402: Insufficient Balance") == "payment"
    assert key_pool.classify("OpenAI request failed: HTTP 429: insufficient_quota You exceeded your current quota") == "payment"
    assert key_pool.classify("Claude request failed: HTTP 400: invalid_request_error Your credit balance is too low") == "payment"
    assert key_pool.classify("Gemini request failed: You exceeded your current quota, please check your plan and billing details. retry in 20s") == "quota"
    assert key_pool.classify("kimi request failed: HTTP 401: Invalid Authentication") == "auth"
    assert key_pool.classify("nvidia request failed: HTTP 503: overloaded") == "other"


def test_a_failed_key_is_skipped_retried_every_fifth_request_and_the_owner_is_asked_before_dropping_only_it(keys):
    stored, settings = keys
    first, second = stored["GROQ_API_KEY"]
    assert key_pool.plan("GROQ_API_KEY") == [first, second]

    assert key_pool.report("GROQ_API_KEY", first, ok=False, error="HTTP 401: invalid api key") == "auth"
    key_pool.report("GROQ_API_KEY", second, ok=True)
    plans = [key_pool.plan("GROQ_API_KEY") for _ in range(5)]
    assert plans[:4] == [[second]] * 4
    assert plans[4] == [second, first]          # the fifth request retries the failed key last

    # A timeout is the provider's problem, never the key's.
    assert key_pool.report("GROQ_API_KEY", second, ok=False, error="read timed out") == "other"
    assert key_pool.summary("groq")["keys"][1]["state"] == "working"

    for _ in range(3):
        key_pool.report("GROQ_API_KEY", first, ok=False, error="HTTP 401: invalid api key")
    assert key_pool.alerts() == []              # not long enough yet
    import time

    alerts = key_pool.alerts(now=time.time() + key_pool.ALERT_AFTER_SECONDS + 1)
    assert [a["last4"] for a in alerts] == ["aaaa"] and alerts[0]["others_working"] == 1
    assert "gsk-first" not in str(alerts) and "gsk-first" not in str(key_pool._load())

    settings.groq_api_key = first
    key_pool.resolve("GROQ_API_KEY", alerts[0]["fingerprint"], "drop")
    assert stored["GROQ_API_KEY"] == [second] and settings.groq_api_key == second


def test_a_provider_needs_payment_only_when_every_key_said_so(keys):
    stored, _settings = keys
    first, second = stored["GROQ_API_KEY"]
    key_pool.report("GROQ_API_KEY", first, ok=False, error="HTTP 402: Payment Required")
    assert key_pool.payment_problem("groq") is None
    key_pool.report("GROQ_API_KEY", second, ok=False, error="HTTP 402: Insufficient Balance")
    assert "402" in key_pool.payment_problem("groq")
    key_pool.report("GROQ_API_KEY", second, ok=True)
    assert key_pool.payment_problem("groq") is None


def test_the_router_fails_over_to_the_next_key_of_the_same_provider(keys, monkeypatch):
    from providers.base import ProviderError
    from router import Router

    stored, settings = keys
    first, second = stored["GROQ_API_KEY"]

    class Groq:
        name = "groq"
        supports_vision = False

        def stream_events(self, messages, model=None, thinking=False):
            if settings.groq_api_key == first:
                raise ProviderError("groq request failed: HTTP 401: Invalid API Key")
            yield {"type": "text", "text": "answered with the second key"}

    groq = Groq()
    router = object.__new__(Router)
    router.providers = {"groq": groq}
    router._candidate_chain = lambda: [groq]
    events = []
    text, used = router.stream([{"role": "user", "content": "hi"}], events.append)
    assert (text, used) == ("answered with the second key", "groq")
    assert any(e.get("type") == "key.failover" for e in events)
    assert settings.groq_api_key == second


def test_picking_a_billable_provider_yourself_is_allowed_in_free_only_mode(monkeypatch):
    from unittest.mock import patch

    import model_choice
    from router import Router

    with patch("router.SETTINGS", SimpleNamespace(free_only=True, preferred_online_provider="gemini")):
        router = object.__new__(Router)
        router.custom = {}
        router.providers = {"kimi": SimpleNamespace(is_available=lambda: True)}
        router._online_available = lambda: True
        assert "may bill" in router.unavailable_reason("kimi")
        assert router.unavailable_reason("kimi", explicit=True) is None
        model_choice.remember("kimi")
        assert "kimi" not in router._paid_names()
        assert model_choice.load()["provider"] == "kimi"
