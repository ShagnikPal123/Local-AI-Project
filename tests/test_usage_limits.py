"""The usage bar shows only limits a provider actually reported (Request G6)."""

from __future__ import annotations

import json

import pytest

import usage_limits


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(usage_limits, "_path", lambda: tmp_path / "usage_limits.json")
    monkeypatch.setitem(usage_limits._STATE, "loaded", False)
    monkeypatch.setitem(usage_limits._STATE, "providers", {})


def test_groq_style_headers_become_limits_with_a_reset_time():
    now = 1_800_000_000.0
    found = usage_limits.record_headers("groq", {
        "x-ratelimit-limit-requests": "14400", "x-ratelimit-remaining-requests": "14370",
        "x-ratelimit-reset-requests": "2m59.56s", "x-ratelimit-limit-tokens": "6000",
        "x-ratelimit-remaining-tokens": "5997", "x-ratelimit-reset-tokens": "7.66s",
    }, "llama-3.1-8b-instant", now=now)
    assert {f["kind"] for f in found} == {"requests", "tokens"}
    requests_limit = next(f for f in found if f["kind"] == "requests")
    assert requests_limit["remaining"] == 14370 and round(requests_limit["reset_at"] - now) == 180
    assert usage_limits.snapshot("groq", now=now)["limits"]


def test_a_provider_that_reports_nothing_gets_no_bar():
    usage_limits.record_headers("nvidia", {"content-type": "application/json"})
    assert usage_limits.snapshot("nvidia") == {"provider": "nvidia", "limits": [], "balance": None}


def test_a_gemini_quota_error_teaches_the_daily_limit_and_requests_are_counted_after_reset():
    body = json.dumps({"error": {"code": 429, "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{
            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
            "quotaDimensions": {"model": "gemini-flash-lite"}, "quotaValue": "1000"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "33s"}]}})
    now = 1_800_000_000.0
    learned = usage_limits.record_quota_error("gemini", body, now=now)
    assert learned["limit"] == 1000 and learned["window"] == "day" and learned["remaining"] == 0

    tomorrow = learned["reset_at"] + 60
    usage_limits.count_request("gemini", "gemini-flash-lite", now=tomorrow)
    usage_limits.count_request("gemini", "gemini-flash-lite", now=tomorrow + 1)
    limit = usage_limits.snapshot("gemini", now=tomorrow + 2)["limits"][0]
    assert (limit["remaining"], limit["source"]) == (998, "counted")
