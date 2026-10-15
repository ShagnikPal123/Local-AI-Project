"""Timing every step, and judging it against what "fast" means for a retail trader.

Shagnik: "test the response of the agent a while to ensure it is fast. Judge what fast means in
the trading and stocks industry since it can be dependent." The judgment (see docs/DESIGN.md):
high-frequency firms work in microseconds from servers inside the exchange; a trader on the
internet pays 50-300 ms for every exchange round trip, so that is the league this app plays in.
It judges only the part it controls:

* **decision** (one market's snapshot in, order out): fast <= 100 ms, ok <= 500 ms
* **cycle** (fetch and rank every market, decide, place orders): fast <= 5 s, ok <= 15 s

Model calls (seconds) are never on the order path, so they are not timed here.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from statistics import median
from typing import Deque, Dict, Iterator, Tuple
from collections import deque

TARGETS: Dict[str, Tuple[float, float]] = {"decision_ms": (100.0, 500.0), "cycle_ms": (5_000.0, 15_000.0)}


def grade(kind: str, ms: float) -> str:
    fast, ok = TARGETS[kind]
    return "fast" if ms <= fast else "ok" if ms <= ok else "slow"


class Stopwatch:
    """Times named stages of one cycle: ``with watch.stage("fetch"): ...``."""

    def __init__(self) -> None:
        self.stages: Dict[str, float] = {}
        self._start = time.perf_counter()

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        began = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0.0) + (time.perf_counter() - began) * 1000

    @property
    def total_ms(self) -> float:
        return (time.perf_counter() - self._start) * 1000


class Recorder:
    """The last few hundred cycles, for the dashboard's speed card and the watchdog."""

    def __init__(self, keep: int = 300) -> None:
        self._cycles: Deque[Dict[str, float]] = deque(maxlen=keep)
        self._lock = threading.Lock()

    def add(self, cycle_ms: float, decision_ms: float, stages: Dict[str, float], markets: int) -> None:
        with self._lock:
            self._cycles.append({"cycle_ms": cycle_ms, "decision_ms": decision_ms, "markets": markets, **stages})

    def summary(self) -> Dict[str, object]:
        with self._lock:
            rows = list(self._cycles)
        if not rows:
            return {"last_cycle_ms": None, "p50_ms": None, "p95_ms": None, "decision_ms": None, "grade": "unknown",
                    "words": "No cycles timed yet.", "stages": {}, "targets": TARGETS}
        cycles = sorted(r["cycle_ms"] for r in rows)
        last = rows[-1]
        p95 = cycles[min(len(cycles) - 1, int(0.95 * len(cycles)))]
        worst = max((grade("cycle_ms", p95), grade("decision_ms", last["decision_ms"])),
                    key=["fast", "ok", "slow"].index)
        stages = {k: round(v, 1) for k, v in last.items() if k not in ("cycle_ms", "decision_ms", "markets")}
        return {"last_cycle_ms": round(last["cycle_ms"], 1), "p50_ms": round(median(cycles), 1), "p95_ms": round(p95, 1),
                "decision_ms": round(last["decision_ms"], 2), "grade": worst, "stages": stages, "targets": TARGETS,
                "words": f"Decisions take {last['decision_ms']:.1f} ms per market; a full {int(last['markets'])}-market "
                         f"cycle {last['cycle_ms'] / 1000:.1f} s. That is {worst} for a trader on the internet."}
