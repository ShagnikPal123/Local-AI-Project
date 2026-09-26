"""The finance pipeline as a picture, where each node lights up as it is used.

The owner sent a photo of a node graph with the note "each node lights up as it
gets used". The photo did not arrive with the message, so this is built from the
pipeline that actually runs — which is the honest version of that picture anyway:
every module calls ``light(...)`` when it does its part, and the panel draws what
is warm.

Nothing here decides anything. It is a record of what ran, and when.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

#: A node counts as "hot" in the UI for this long after it was used.
HOT_SECONDS = 12.0

#: The pipeline, in the order money-affecting work happens.
NODES: List[Dict[str, str]] = [
    {"id": "market", "label": "Market data", "what": "Prices and volume for the watchlist", "group": "in"},
    {"id": "search", "label": "News & search", "what": "What is being said about the symbol", "group": "in"},
    {"id": "forecast", "label": "Forecast", "what": "Where the price could go, with a band", "group": "think"},
    {"id": "strategies", "label": "Strategies", "what": "Every strategy's read of right now", "group": "think"},
    {"id": "memory", "label": "Memory", "what": "Which strategy worked in this kind of market before", "group": "think"},
    {"id": "simulator", "label": "Simulator", "what": "Practice runs over history", "group": "think"},
    {"id": "decision", "label": "Decision", "what": "What it would do, and why", "group": "act"},
    {"id": "capital", "label": "Capital guard", "what": "Only its own money; brakes as it loses", "group": "act"},
    {"id": "risk", "label": "Trading rules", "what": "Your budgets, hours and approvals", "group": "act"},
    {"id": "broker", "label": "Broker", "what": "Practice money by default", "group": "act"},
    {"id": "audit", "label": "Log", "what": "Everything it did, kept", "group": "act"},
]

#: Which node feeds which.
EDGES: List[List[str]] = [
    ["market", "forecast"], ["market", "strategies"], ["search", "forecast"], ["search", "decision"],
    ["forecast", "decision"], ["strategies", "decision"], ["memory", "decision"], ["simulator", "memory"],
    ["market", "simulator"], ["decision", "capital"], ["capital", "risk"], ["risk", "broker"],
    ["broker", "audit"], ["capital", "audit"],
]

_lock = threading.Lock()
_used: Dict[str, Dict[str, Any]] = {}


def light(node: str, detail: str = "") -> None:
    """This part of the pipeline just did something."""
    if not node:
        return
    with _lock:
        row = _used.setdefault(node, {"count": 0, "last": 0.0, "detail": ""})
        row["count"] += 1
        row["last"] = time.time()
        if detail:
            row["detail"] = detail[:120]


def map_now() -> Dict[str, Any]:
    """Nodes and edges with their heat, for the panel to draw."""
    now = time.time()
    with _lock:
        used = {key: dict(value) for key, value in _used.items()}
    nodes = []
    for node in NODES:
        row = used.get(node["id"], {"count": 0, "last": 0.0, "detail": ""})
        since = now - row["last"] if row["last"] else None
        nodes.append({
            **node,
            "count": row["count"],
            "last": row["last"],
            "detail": row["detail"],
            "hot": bool(since is not None and since <= HOT_SECONDS),
            "warm": bool(since is not None and since <= 600),
        })
    return {"nodes": nodes, "edges": EDGES, "hot_seconds": HOT_SECONDS}


def reset() -> None:
    with _lock:
        _used.clear()
