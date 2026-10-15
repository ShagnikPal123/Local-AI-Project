"""Max, the manager: looks after the whole team every few cycles.

The owner: "Manager bots and advisor bots and more should be on the internal helping. If the
analysis sees it should add bots or add more things then it should be able to. Fully adaptable."

Every ``EVERY`` cycles Max:

1. **Scores each trader** from its own fills: money made or lost, wins and losses.
2. **Moves money to what works**: a slice of share from the worst trader to the best, never below
   5% or above 60%, so money drifts to what is working without abandoning the rest on a bad day.
   (The same rule as the main app's trading desk, ``trading/desk.py``.)
3. **Hires** a trader for a kind of market that has several strong picks and nobody covering it.
4. **Retires** a trader that keeps losing (enough closed trades, mostly losses, money down). Its
   holdings are sold.
5. **Tunes the settings** in auto mode: the risk dial leans careful after a drawdown or a losing
   streak and a little bolder while it is winning. Anything the owner pinned is left alone.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..models import Order

EVERY = 5
MIN_SHARE, MAX_SHARE, SHIFT = 0.05, 0.60, 0.05


def scores(team: Any, fills: List[Dict[str, Any]], positions: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Per trader: realized and open money, closed trades, wins."""
    out: Dict[str, Dict[str, float]] = {t["name"]: {"realized": 0.0, "open": 0.0, "closed": 0, "wins": 0, "trades": 0}
                                       for t in team.traders()}
    for fill in fills:
        row = out.get(fill.get("bot"))
        if row is None:
            continue
        row["trades"] += 1
        if fill.get("realized") is not None:
            row["realized"] += float(fill["realized"])
            row["closed"] += 1
            row["wins"] += 1 if float(fill["realized"]) > 0 else 0
    for pos in positions:
        if pos.get("bot") in out:
            out[pos["bot"]]["open"] += float(pos["pl"])
    return out


def review(team: Any, fills: List[Dict[str, Any]], positions: List[Dict[str, Any]], account: Dict[str, Any],
           rows: Dict[str, Dict[str, Any]], settings: Dict[str, Any]) -> Tuple[List[Order], Dict[str, Any]]:
    """One look at the team. Returns sell orders (for retired traders) and the settings it chose."""
    max_bot = team.one("manager")
    equity = float(account.get("equity") or 1)
    perf = scores(team, fills, positions)
    for trader in team.traders():
        p = perf[trader["name"]]
        trader["pl"] = round(p["realized"] + p["open"], 2)
        trader["pl_pct"] = round(trader["pl"] / max(trader["share"] * equity, 1) * 100, 2)
        trader["trades"] = int(p["trades"])
    orders: List[Order] = []

    traders = sorted(team.traders(), key=lambda t: t["pl_pct"])
    if len(traders) >= 2:
        worst, best = traders[0], traders[-1]
        gap = best["pl_pct"] - worst["pl_pct"]
        amount = min(SHIFT, worst["share"] - MIN_SHARE, MAX_SHARE - best["share"])
        if gap >= 2.0 and amount > 0.0001:
            worst["share"] = round(worst["share"] - amount, 4)
            best["share"] = round(best["share"] + amount, 4)
            team.roster["shifts"] = (team.roster.get("shifts") or [])[-19:] + [
                {"from": worst["name"], "to": best["name"], "share": amount}]
            team.notes.add(max_bot, f"Moved {amount:.0%} of the money from {worst['name']} to {best['name']}: "
                                    f"{best['name']} is ahead by {gap:.1f} points.", "info")

    for trader in team.traders():
        p = perf[trader["name"]]
        if p["closed"] >= 6 and p["wins"] / p["closed"] < 0.3 and trader["pl"] < 0 and len(team.traders()) > 1:
            team.retire(trader, f"Retired: {int(p['wins'])} wins in {int(p['closed'])} trades.")
            team.notes.add(max_bot, f"Retired {trader['name']} after {int(p['wins'])} wins in {int(p['closed'])} trades; "
                                    "selling what it held.", "warn")
            for pos in positions:
                if pos.get("bot") == trader["name"]:
                    orders.append(Order(pos["symbol"], "sell", pos["qty"], pos["asset_class"], max_bot["name"],
                                        f"{trader['name']} was retired."))

    enabled = [k for k, on in (settings.get("markets") or {}).items() if on]
    covered = {c for t in team.traders() for c in t["classes"]}
    groups = {"crypto": ["crypto"], "stocks": ["stock", "etf"], "fx": ["fx"]}
    for market in enabled:
        classes = groups.get(market, [market])
        strong = [r for r in rows.values() if r["asset_class"] in classes and r["signal"] == "buy" and r["score"] >= 0.6]
        if not covered.intersection(classes) and len(strong) >= 3 and len(team.active()) < int(settings.get("max_bots", 12)):
            hired = team.hire(classes, f"{len(strong)} strong {market} picks and nobody covering them.")
            team.notes.add(max_bot, f"Hired {hired['name']} for {market}: {len(strong)} strong picks and nobody on them.",
                           "idea")

    chosen = choose_settings(account, perf, settings)
    team.set_doing(max_bot, f"Watching {len(team.traders())} traders; " +
                   (f"risk set to {chosen['risk']['value']:.2f}." if "risk" in chosen else "settings pinned by you."))
    return orders, chosen


def choose_settings(account: Dict[str, Any], perf: Dict[str, Dict[str, float]], settings: Dict[str, Any]) -> Dict[str, Any]:
    """Auto mode's choices for values the owner has not pinned, each with a sentence of why."""
    if not settings.get("auto") or "risk" in (settings.get("pins") or {}):
        return {}
    equity, peak = float(account.get("equity") or 0), float(account.get("peak") or 0)
    drawdown = (peak - equity) / peak * 100 if peak else 0.0
    closed = sum(p["closed"] for p in perf.values())
    wins = sum(p["wins"] for p in perf.values())
    risk, why = 0.5, []
    if drawdown > 2:
        risk -= min(0.3, drawdown * 0.04)
        why.append(f"down {drawdown:.1f}% from its best")
    if closed >= 5:
        rate = wins / closed
        risk += (rate - 0.5) * 0.4
        why.append(f"{rate:.0%} of {closed} closed trades won")
    risk = round(max(0.2, min(0.8, risk)), 2)
    return {"risk": {"value": risk, "why": ("Leaning careful: " if risk < 0.5 else "Steady: " if risk == 0.5 else
                                            "Leaning bolder: ") + (", ".join(why) if why else "no track record yet") + "."}}
