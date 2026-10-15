"""The local model's warm / cold chip and the optional keep-warm ping (doc 2 item 2.3)."""

import types

import pytest

import cache_warmth


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_warmth, "data_path", lambda name: tmp_path / name)
    monkeypatch.setattr(cache_warmth, "_last", {})


def test_only_ollama_answers_count_and_warmth_runs_down():
    cache_warmth.note("gemini", True, now=1000)
    assert cache_warmth.state(now=1000)["ollama"]["used"] is False
    cache_warmth.note("ollama", False, now=1000)
    assert cache_warmth.state(now=1000)["ollama"]["warm"] is False
    cache_warmth.note("ollama", True, now=1000)
    assert cache_warmth.state(now=1100)["ollama"]["seconds_left"] == 200
    assert cache_warmth.state(now=1400)["ollama"]["warm"] is False


def test_metrics_feed_the_chip():
    from metrics import GLOBAL_METRICS

    GLOBAL_METRICS.record(provider="ollama", latency_seconds=0.1, success=True)
    assert cache_warmth.state()["ollama"]["warm"] is True


def test_keep_warm_is_off_by_default_and_pings_with_keep_alive(monkeypatch):
    assert cache_warmth.keep_warm() is False
    sent = []
    ok = cache_warmth._ping(post=lambda url, json, timeout: sent.append((url, json)) or types.SimpleNamespace(status_code=200))
    from config import SETTINGS

    if not SETTINGS.ollama_model:
        assert ok is False
        return
    assert ok and sent[0][0].endswith("/api/generate") and sent[0][1]["keep_alive"] == "5m"
    assert cache_warmth.state()["ollama"]["warm"] is True
