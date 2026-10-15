"""Atlas, the advisor: for each market, which strategy fits right now, and what it says.

The advisor joins two things: what kind of market this is today (``forecast.regime``) and what the
strategist learned works in that kind of market (the playbook). It hands the traders the best
strategy's current read: buy, sell or hold, how strongly, and why. With no playbook row yet it falls
back to the trend follower, the oldest and plainest strategy there is, and says so.

The baselines ("buy and hold", "little and often") are never advised: they always say buy, so they
would turn the advisor into a yes-man.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..core import clock, forecast, strategies
from ..models import Snapshot
from . import strategist

BASELINES = ("buy_and_hold", "dca")


def advise(snap: Snapshot) -> Dict[str, Any]:
    years = clock.periods_per_year(snap.instrument.asset_class)
    mood = forecast.regime(snap.closes, years)
    choices = [r for r in strategist.best_for(mood) if r["strategy"] not in BASELINES and r["edge_pct"] > 0]
    name = choices[0]["strategy"] if choices else "trend_sma"
    read = strategies.read(name, snap.closes)
    because = (f"in {mood} markets it beat holding by {choices[0]['edge_pct']:.1f}% over {choices[0]['runs']} studies"
               if choices else "nothing has a proven edge here yet, so the plain trend follower")
    return {"symbol": snap.symbol, "strategy": name, "title": read.get("title", name), "regime": mood,
            "action": read["action"], "strength": read["strength"], "why": f"{read['why']} ({because})"}


def advise_all(snaps: List[Snapshot], team: Any) -> Dict[str, Dict[str, Any]]:
    atlas = team.one("advisor")
    advice = {s.symbol: advise(s) for s in snaps if len(s.closes) >= 30}
    buys = sum(1 for a in advice.values() if a["action"] == "buy")
    team.set_doing(atlas, f"Matched a strategy to {len(advice)} markets; {buys} say buy.")
    return advice
