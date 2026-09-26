"""What worked, in which kind of market, remembered between sessions.

The owner: "Add a finance memory simulator and feature so it trains and then
does that."

The memory is deliberately small and legible: for every (market regime,
strategy) pair it keeps how many practice runs there were, the average return,
how often it beat simply holding, and the worst drawdown. Picking a strategy is
then a lookup, not a guess, and the reason it gives is the row itself.

Regimes come from ``forecast.regime``: quiet, rising, falling, wild.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional

from paths import data_path

from . import node_map

#: A pair needs at least this many runs before it is trusted over a baseline.
ENOUGH_RUNS = 3

_lock = threading.Lock()


def _path():
    return data_path("finance_lab/memory.json")


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"pairs": data.get("pairs", {}), "runs": data.get("runs", []), "trained_at": data.get("trained_at", 0)}
    except (OSError, ValueError):
        pass
    return {"pairs": {}, "runs": [], "trained_at": 0}


def _save(state: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def remember(regime: str, strategy: str, result: Dict[str, Any]) -> None:
    """One practice run's outcome."""
    key = f"{regime}|{strategy}"
    with _lock:
        state = _load()
        row = state["pairs"].setdefault(key, {"regime": regime, "strategy": strategy, "runs": 0,
                                              "return_pct": 0.0, "beat": 0, "worst_drawdown_pct": 0.0})
        runs = row["runs"] + 1
        row["return_pct"] = (row["return_pct"] * row["runs"] + float(result.get("return_pct", 0.0))) / runs
        row["worst_drawdown_pct"] = max(float(row["worst_drawdown_pct"]), float(result.get("worst_drawdown_pct", 0.0)))
        row["beat"] += 1 if float(result.get("beat_holding_pct", 0.0)) > 0 else 0
        row["runs"] = runs
        row["last"] = time.time()
        state["trained_at"] = time.time()
        _save(state)


def note_run(row: Dict[str, Any]) -> None:
    with _lock:
        state = _load()
        state["runs"] = ([{**row, "at": time.time()}] + list(state.get("runs", [])))[:60]
        _save(state)


def table() -> List[Dict[str, Any]]:
    """Everything it has learned, best first."""
    rows = list(_load()["pairs"].values())
    for row in rows:
        row["beat_rate"] = round(row["beat"] / row["runs"], 2) if row["runs"] else 0.0
        row["return_pct"] = round(row["return_pct"], 2)
        row["worst_drawdown_pct"] = round(row["worst_drawdown_pct"], 2)
    rows.sort(key=lambda row: (-row["beat_rate"], -row["return_pct"]))
    return rows


def best_for(regime: str) -> Optional[Dict[str, Any]]:
    """The strategy it would use in this kind of market, if it has learned one."""
    node_map.light("memory", regime)
    rows = [row for row in table() if row["regime"] == regime and row["runs"] >= ENOUGH_RUNS]
    if not rows:
        return None
    # Beating buy-and-hold matters more than the raw return: a strategy that only
    # wins when everything wins has not earned the trades it costs.
    rows.sort(key=lambda row: (-(row["beat_rate"]), -row["return_pct"], row["worst_drawdown_pct"]))
    return rows[0]


def trained_at() -> float:
    return float(_load().get("trained_at") or 0)


def runs() -> List[Dict[str, Any]]:
    return list(_load().get("runs", []))


def forget() -> None:
    _save({"pairs": {}, "runs": [], "trained_at": 0})
