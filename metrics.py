"""Performance metrics tracking for latency, provider reliability, and token usage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any, Dict, List, Optional


@dataclass
class RequestMetric:
    """Performance and cost data for an individual assistant interaction."""

    metric_id: str
    timestamp: str
    provider: str
    mode: str
    latency_seconds: float
    success: bool
    tokens_prompt: Optional[int] = None
    tokens_completion: Optional[int] = None
    tokens_total: Optional[int] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class MetricsTracker:
    """Thread-safe collector for request performance and provider reliability."""

    def __init__(self, max_history: int = 1000, storage_path: Optional[Path | str] = None) -> None:
        self.max_history = max_history
        self.storage_path = Path(storage_path) if storage_path else None
        self._metrics: List[RequestMetric] = []
        self._lock = threading.Lock()
        if self.storage_path and self.storage_path.exists():
            self._load_from_storage()

    def record(
        self,
        provider: str,
        latency_seconds: float,
        success: bool,
        mode: str = "auto",
        tokens_prompt: Optional[int] = None,
        tokens_completion: Optional[int] = None,
        tokens_total: Optional[int] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RequestMetric:
        """Record a single interaction metric."""
        import uuid

        total_tokens = tokens_total
        if total_tokens is None and tokens_prompt is not None and tokens_completion is not None:
            total_tokens = tokens_prompt + tokens_completion

        metric = RequestMetric(
            metric_id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(timezone.utc).isoformat(),
            provider=provider,
            mode=mode,
            latency_seconds=round(max(0.0, latency_seconds), 4),
            success=success,
            tokens_prompt=tokens_prompt,
            tokens_completion=tokens_completion,
            tokens_total=total_tokens,
            error_message=error_message,
            metadata=metadata or {},
        )

        with self._lock:
            self._metrics.append(metric)
            if len(self._metrics) > self.max_history:
                self._metrics = self._metrics[-self.max_history :]
            if self.storage_path:
                self._save_to_storage()

        return metric

    def get_summary(self) -> Dict[str, Any]:
        """Aggregate statistics across recorded interactions."""
        with self._lock:
            if not self._metrics:
                return {
                    "total_requests": 0,
                    "avg_latency_seconds": 0.0,
                    "success_rate": 1.0,
                    "provider_breakdown": {},
                }

            total = len(self._metrics)
            successful = sum(1 for m in self._metrics if m.success)
            total_latency = sum(m.latency_seconds for m in self._metrics)

            provider_stats: Dict[str, Dict[str, Any]] = {}
            for m in self._metrics:
                if m.provider not in provider_stats:
                    provider_stats[m.provider] = {
                        "count": 0,
                        "successes": 0,
                        "total_latency": 0.0,
                        "total_tokens": 0,
                    }
                entry = provider_stats[m.provider]
                entry["count"] += 1
                if m.success:
                    entry["successes"] += 1
                entry["total_latency"] += m.latency_seconds
                if m.tokens_total:
                    entry["total_tokens"] += m.tokens_total

            breakdown = {}
            for name, data in provider_stats.items():
                count = data["count"]
                breakdown[name] = {
                    "requests": count,
                    "success_rate": round(data["successes"] / count, 3) if count else 0.0,
                    "avg_latency": round(data["total_latency"] / count, 3) if count else 0.0,
                    "total_tokens": data["total_tokens"],
                }

            return {
                "total_requests": total,
                "successful_requests": successful,
                "failed_requests": total - successful,
                "success_rate": round(successful / total, 3),
                "avg_latency_seconds": round(total_latency / total, 3),
                "provider_breakdown": breakdown,
            }

    def clear(self) -> None:
        """Clear all in-memory metrics."""
        with self._lock:
            self._metrics.clear()
            if self.storage_path and self.storage_path.exists():
                try:
                    self.storage_path.unlink()
                except OSError:
                    pass

    def _save_to_storage(self) -> None:
        if not self.storage_path:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(m) for m in self._metrics]
            self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load_from_storage(self) -> None:
        if not self.storage_path or not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._metrics = [RequestMetric(**item) for item in data]
        except (json.JSONDecodeError, TypeError, OSError):
            self._metrics = []


GLOBAL_METRICS = MetricsTracker()
