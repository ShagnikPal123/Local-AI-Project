"""The finance lab: the part of trading that does not depend on anyone's API quota.

The owner (2026-09-22): "Build a new system so for this since most ai need the
usage limits while a local ai and a few unlimited use ai are needed make sure to
make a new one basically local with search so it can predict changes and plot
properly. Make sure there is a don't go broke situation… Essentially it can only
access the money it has and the money it earns to make more money. If it [fails]
it needs to lea[rn]. Add a finance memory simulator and feature so it trains and
then does that."

Six pieces, each usable on its own:

* ``capital_guard`` — it can only spend the money it was given plus what it has
  earned. No debt, no margin, no shorting, and a brake that tightens as it loses.
* ``forecast`` — prediction with arithmetic, not an API: drift, volatility,
  regression and a Monte Carlo cone, so a plot exists with no key and no limit.
* ``strategies`` — the strategy library, each one backtestable.
* ``simulator`` + ``memory`` — it trains on history first, remembers which
  strategy works in which kind of market, and only then acts.
* ``model_policy`` — if a cloud model is used at all, it must be one whose limits
  will not run out mid-session; local first, always.
* ``focus_mode`` — high-finance mode: everything else stops, with a warning.
* ``node_map`` — the picture of that pipeline, where each node lights up as it
  is used.

Nothing here places an order. Orders stay with ``trading/`` and its approvals;
this is the part that decides what is worth asking for, and refuses what would
spend money the AI does not have.
"""

from __future__ import annotations

__all__ = ["capital_guard", "forecast", "strategies", "simulator", "memory", "model_policy",
           "focus_mode", "node_map"]
