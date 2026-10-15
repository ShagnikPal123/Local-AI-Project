"""The watchdog: shuts the trader down by itself when it is slow or losing.

Shagnik: "It should be able to run 24/7 [and] has auto shut down when it sees the ai is maybe
running slow or has not made money and might be losing."

``check`` looks at the run so far and returns a reason to stop, or "" to carry on:

* **Slow** - ``slow_cycles`` cycles in a row slower than ``slow_cycle_ms``. A trader that cannot
  keep up with its own pace is trading on old prices.
* **Losing** - equity has fallen ``max_drawdown_pct`` below its best point.
* **Not making money** - it has run for ``losing_hours`` and is still below where this run started.
* **Stale prices** pause rather than stop (``stale`` returns a reason): the internet coming back
  should not need Shagnik.

Pure functions over numbers the engine passes in, so every rule is tested on its own.
"""

from __future__ import annotations

from typing import Any, Dict, List


def check(*, recent_cycle_ms: List[float], equity: float, peak: float, run_start_equity: float,
          run_hours: float, rules: Dict[str, Any]) -> str:
    slow_ms = float(rules.get("slow_cycle_ms", 5_000))
    slow_n = int(rules.get("slow_cycles", 5))
    tail = recent_cycle_ms[-slow_n:]
    if len(tail) >= slow_n and all(ms > slow_ms for ms in tail):
        return (f"Shut down: the last {slow_n} cycles each took over {slow_ms / 1000:.0f} s "
                f"(slowest {max(tail) / 1000:.1f} s), so it was trading on old prices.")
    limit = float(rules.get("max_drawdown_pct", 10.0))
    if peak > 0 and equity < peak * (1 - limit / 100):
        return (f"Shut down: the money fell {(peak - equity) / peak * 100:.1f}% from its best "
                f"({peak:,.2f} to {equity:,.2f}); the limit is {limit:.0f}%.")
    hours = float(rules.get("losing_hours", 24))
    if run_hours >= hours and run_start_equity > 0 and equity < run_start_equity:
        return (f"Shut down: after {run_hours:.0f} hours it is still below where it started "
                f"({equity:,.2f} vs {run_start_equity:,.2f}), so it is not making money.")
    return ""


def stale(quote_ages: List[float], rules: Dict[str, Any]) -> str:
    """A reason to pause when every price is old (the internet or the feeds are down)."""
    limit = float(rules.get("stale_data_s", 300))
    if quote_ages and min(quote_ages) > limit:
        return f"Paused: the newest price is {min(quote_ages) / 60:.0f} minutes old. It resumes when prices are fresh."
    return ""
