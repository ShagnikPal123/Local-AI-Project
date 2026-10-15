"""Where the trader keeps its data, and the settings it starts with.

Everything the trader saves (the practice account, settings, saved keys, what it learned) lives in
one data folder. By default that is ``data/`` next to this app; ``ICHOS_TRADER_DATA`` moves it,
which is how tests get a fresh empty folder and how a cloud copy points at a persistent disk.

The settings here are the defaults the dashboard's Tuning section edits. The owner asked for it to be
"auto for everything and not dependent on me other than turning on and off", so ``auto`` is on and
the manager bot re-chooses every value the owner has not pinned by hand.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict

APP_ROOT = Path(__file__).resolve().parents[1]

#: Where the server listens by default. Local only: a cloud copy sets ICHOS_TRADER_HOST itself.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8100


def data_dir() -> Path:
    """The data folder, created on first use. Read at call time so tests can swap it."""
    path = Path(os.environ.get("ICHOS_TRADER_DATA") or APP_ROOT / "data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def offline() -> bool:
    """True when the trader must not touch the internet: it uses the simulated market instead."""
    return os.environ.get("ICHOS_TRADER_OFFLINE", "").strip().lower() in ("1", "true", "yes", "on")


def default_settings() -> Dict[str, Any]:
    """The trader's starting settings. Every number has a plain reason next to it."""
    return {
        # Fully automatic: the manager picks every value below that is not in ``pins``.
        "auto": True,
        # The one switch the owner really needs. Saved, so a restart picks up where it was.
        "running": False,
        "base_currency": "USD",
        "start_cash": 10_000.0,
        # Which kinds of market the scout looks at. Currencies are off by default: tiny moves,
        # and they need more money to matter.
        "markets": {"crypto": True, "stocks": True, "fx": False},
        # How many markets the scout ranks each cycle ("instead of one market it can look at hundreds").
        "scan_limit": 300,
        # One cycle a minute. The watchdog checks that a cycle finishes well inside this.
        "pace_seconds": 60,
        # The big dial: 0 is careful, 1 is bold. It scales position size and how sure a pick must be.
        "risk": 0.5,
        "max_positions": 8,
        # No single market gets more than this share of the money.
        "max_position_pct": 0.2,
        "stop_loss_pct": 4.0,
        "take_profit_pct": 8.0,
        # How hard the mild skeptic pushes back: 0 easy-going, 1 strict. Mild by default.
        "skeptic": 0.5,
        # Study history before the first trade ("first understand how trading works").
        "learn_first": True,
        # The manager may hire bots up to this many.
        "max_bots": 12,
        # Auto shut-down ("when it sees the AI is maybe running slow or has not made money").
        "shutdown": {
            "max_drawdown_pct": 10.0,   # down this much from the best point: stop
            "slow_cycle_ms": 5_000,     # a cycle slower than this counts as slow...
            "slow_cycles": 5,           # ...and this many slow cycles in a row stops it
            "losing_hours": 24,         # running this long and still below where it started: stop
            "stale_data_s": 300,        # prices older than this: pause until fresh ones arrive
        },
        # Values the owner set by hand in Tuning. Auto mode never overrides these.
        "pins": {},
        # The look. ``sync`` "nyx" follows the colours chosen in the main Nyx app when it runs nearby.
        "theme": {"accent": "#7c6cff", "mode": "dark", "sync": "none"},
        # The Claude connector is only used when the owner asks (Fixer Upper doc, page 4).
        "claude": {"enabled": False},
        # Which broker executes orders. "sim" is the built-in practice account.
        "broker": "sim",
        # With a real broker: the most money the bots may use (0 = the whole practice account).
        "budget": 0.0,
        # Setup shows on first open and can be opened again any time.
        "setup_done": False,
    }


def merged(saved: Dict[str, Any]) -> Dict[str, Any]:
    """Saved settings laid over the defaults, so a settings file from an older version still loads."""
    out = default_settings()
    for key, value in (saved or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            inner = copy.deepcopy(out[key])
            inner.update(value)
            out[key] = inner
        else:
            out[key] = value
    return out
