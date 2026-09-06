"""Tests for the performance and reliability metrics tracker."""

import time

from metrics import MetricsTracker, RequestMetric


def test_metrics_tracker_records_requests(tmp_path):
    tracker = MetricsTracker(storage_path=tmp_path / "test_metrics.json")
    m1 = tracker.record(provider="ollama", latency_seconds=0.45, success=True, mode="quick")
    m2 = tracker.record(provider="claude", latency_seconds=1.20, success=True, mode="deep", tokens_total=150)
    m3 = tracker.record(provider="ollama", latency_seconds=0.80, success=False, error_message="timeout")

    assert m1.provider == "ollama"
    assert m2.tokens_total == 150
    assert m3.success is False

    summary = tracker.get_summary()
    assert summary["total_requests"] == 3
    assert summary["successful_requests"] == 2
    assert summary["failed_requests"] == 1
    assert summary["success_rate"] == 0.667

    ollama_stats = summary["provider_breakdown"]["ollama"]
    assert ollama_stats["requests"] == 2
    assert ollama_stats["success_rate"] == 0.5


def test_metrics_tracker_clear():
    tracker = MetricsTracker()
    tracker.record(provider="openai", latency_seconds=0.5, success=True)
    assert tracker.get_summary()["total_requests"] == 1
    tracker.clear()
    assert tracker.get_summary()["total_requests"] == 0
