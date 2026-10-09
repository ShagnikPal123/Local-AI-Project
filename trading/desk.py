"""The trading desk (UPDATE_IDEAS U16): several AI traders, each with its own share of the money, its own way of
reading prices and its own market.

The owner: *"To the trader tab, [it] can make multiple agents and split money between them to trade in different
ways in different markets and make more money."*

How it fits the trader that already exists:

* It is a **mode of the AI trader**, not a second trader. With the desk on, each scan runs the desk's agents instead
  of the single picker, so two systems never spend the same budget.
* Every order still goes through ``guard.submit`` as ``requested_by="ai"``: the owner's rules, approvals, the daily
  limits and the finance lab's capital guard all apply to every agent. Practice money stays the default.
* An agent's **pot** is its share of the AI's budget (``max_invested``). The desk keeps a ledger per agent — what it
  holds, what it paid, what it made — so each agent's result is its own.
* **Splitting the money to make more:** every few runs the desk moves a slice of share from the agent doing worst
  to the one doing best, never below 5% or above 60%, so the money drifts to what is working without abandoning the
  rest on one bad week.

The strategies are ``finance_lab.strategies`` (long or flat only — no shorting, no leverage).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from finance_lab import strategies
from trading import allocator, market, store
from trading.brokers import BrokerError, OrderRequest

MARKETS: Dict[str, Dict[str, Any]] = {
    "us_large": {"title": "US large caps",
                 "symbols": ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "JPM", "V", "UNH", "XOM"]},
    "etfs": {"title": "Index funds", "symbols": ["SPY", "QQQ", "IWM", "DIA", "VTI", "EFA", "TLT", "GLD"]},
    "tech": {"title": "Tech growth", "symbols": ["NVDA", "AMD", "AVGO", "CRM", "ADBE", "NOW", "SHOP", "PLTR"]},
    "dividend": {"title": "Dividend payers", "symbols": ["KO", "PEP", "JNJ", "PG", "VZ", "T", "O", "MO"]},
    "watchlist": {"title": "Your watchlist", "symbols": []},
}

DEFAULT_AGENTS: List[Dict[str, Any]] = [
    {"name": "Trend Rider", "strategy": "trend_sma", "market": "us_large", "share": 0.3},
    {"name": "Index Steady", "strategy": "volatility_target", "market": "etfs", "share": 0.3},
    {"name": "Dip Buyer", "strategy": "mean_reversion", "market": "dividend", "share": 0.2},
    {"name": "Breakout Hunter", "strategy": "breakout", "market": "tech", "share": 0.2},
]

MIN_SHARE, MAX_SHARE, SHIFT = 0.05, 0.60, 0.05
MAX_AGENTS = 8
MAX_HOLDINGS = 3          # an agent spreads its pot over at most this many symbols
MIN_STRENGTH = 0.5        # how sure a strategy must be before its agent buys
REBALANCE_EVERY = 12      # desk runs between share shifts
SYMBOLS_PER_AGENT = 8

History = Callable[[str], List[Dict[str, Any]]]
Quote = Callable[[str], float]
Submit = Callable[[OrderRequest], Dict[str, Any]]


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def _agent(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": raw.get("id") or "dsk-" + uuid.uuid4().hex[:8], "name": str(raw.get("name") or "Trader")[:40],
            "strategy": raw.get("strategy") if raw.get("strategy") in strategies.STRATEGIES else "trend_sma",
            "market": raw.get("market") if raw.get("market") in MARKETS else "us_large",
            "share": max(0.0, float(raw.get("share") or 0)), "enabled": bool(raw.get("enabled", True))}


def _default() -> Dict[str, Any]:
    return {"enabled": False, "agents": [_agent(a) for a in DEFAULT_AGENTS], "ledger": {}, "runs": 0,
            "shifts": [], "last": {}}


def state() -> Dict[str, Any]:
    return store.read("desk", _default)


def _save(data: Dict[str, Any]) -> None:
    store.write("desk", data)


def _normalise(agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Shares of the enabled agents add up to 1, each between the bounds."""
    live = [a for a in agents if a["enabled"]]
    total = sum(a["share"] for a in live)
    for agent in live:
        agent["share"] = round(agent["share"] / total, 4) if total > 0 else round(1 / len(live), 4)
    return agents


def configure(*, enabled: Optional[bool] = None, agents: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The owner's edits: switch the desk on or off, add, change or remove agents."""
    data = state()
    if agents is not None:
        cleaned = [_agent(a) for a in agents if isinstance(a, dict)][:MAX_AGENTS]
        if not cleaned:
            raise ValueError("The desk needs at least one trader.")
        data["agents"] = _normalise(cleaned)
        known = {a["id"] for a in cleaned}
        data["ledger"] = {k: v for k, v in data.get("ledger", {}).items() if k in known or _holds(v)}
    if enabled is not None:
        data["enabled"] = bool(enabled)
    _save(data)
    return view()


def _holds(book: Dict[str, Any]) -> bool:
    return any(q > 1e-9 for q in (book.get("holdings") or {}).values())


def _book(data: Dict[str, Any], agent_id: str) -> Dict[str, Any]:
    return data.setdefault("ledger", {}).setdefault(agent_id, {"holdings": {}, "cost": {}, "realized": 0.0,
                                                               "trades": 0})


def symbols_for(agent: Dict[str, Any], watchlist: List[str]) -> List[str]:
    pool = watchlist if agent["market"] == "watchlist" else MARKETS[agent["market"]]["symbols"]
    return [s.upper() for s in pool][:SYMBOLS_PER_AGENT]


# ---------------------------------------------------------------------------
# One run
# ---------------------------------------------------------------------------


def _value(book: Dict[str, Any], quote: Quote) -> float:
    total = 0.0
    for symbol, qty in (book.get("holdings") or {}).items():
        if qty > 1e-9:
            try:
                total += qty * quote(symbol)
            except Exception:  # noqa: BLE001 - an unpriced holding counts at what was paid
                total += float((book.get("cost") or {}).get(symbol, 0.0))
    return total


def performance(book: Dict[str, Any], quote: Quote) -> Dict[str, float]:
    cost = sum(float(v) for v in (book.get("cost") or {}).values())
    value = _value(book, quote)
    realized = float(book.get("realized") or 0.0)
    gain = value - cost + realized
    base = cost if cost > 0 else 0.0
    return {"value": round(value, 2), "cost": round(cost, 2), "realized": round(realized, 2), "gain": round(gain, 2),
            "pct": round(gain / base * 100, 2) if base else 0.0}


#: Results after which the trader's book does not change: nothing was bought or sold (yet).
_NOT_DONE = ("refused", "rejected", "canceled", "awaiting_approval", "error")


def _try(submit: Submit, order: OrderRequest) -> Dict[str, Any]:
    """One order; a failure (no price, broker down, a bad order) costs this order, not the rest of the desk's run."""
    try:
        return submit(order)
    except Exception as error:  # noqa: BLE001 - recorded on the action, and the next trader still runs
        return {"status": "error", "reasons": [f"{type(error).__name__}: {error}"[:200]]}


def run(ai: Dict[str, Any], *, watchlist: List[str], submit: Submit, history: History, quote: Quote,
        ai_owned: Dict[str, float]) -> Dict[str, Any]:
    """Every enabled agent: sell what its strategy says to leave, then buy its strongest picks within its pot.

    The callables are the trader's own (``guard.submit``, ``market.history``…) and are passed in so a test can run a
    whole desk without a network or a broker.
    """
    data = state()
    budget = float(ai.get("max_invested") or 0)
    actions: List[Dict[str, Any]] = []
    held_by_desk: Dict[str, float] = {}
    for book in data.get("ledger", {}).values():
        for symbol, qty in (book.get("holdings") or {}).items():
            held_by_desk[symbol] = held_by_desk.get(symbol, 0.0) + qty
    cache: Dict[str, List[Dict[str, Any]]] = {}

    def read(strategy: str, symbol: str) -> Dict[str, Any]:
        if symbol not in cache:
            try:
                cache[symbol] = history(symbol)
            except Exception:  # noqa: BLE001 - one unreadable symbol is skipped, not the run
                cache[symbol] = []
        return strategies.read(strategy, cache[symbol])

    for agent in [a for a in data["agents"] if a["enabled"]]:
        book = _book(data, agent["id"])
        tag = {"agent": agent["name"], "agent_id": agent["id"], "strategy": agent["strategy"]}
        # 1) Sell what this agent's strategy no longer wants.
        for symbol, qty in list(book["holdings"].items()):
            if qty <= 1e-9:
                continue
            signal = read(agent["strategy"], symbol)
            if signal["action"] != "sell":
                actions.append({**tag, "symbol": symbol, "action": "hold", "why": signal["why"]})
                continue
            qty = min(qty, float(ai_owned.get(symbol, 0.0)))
            if qty <= 1e-9:
                # The AI's account no longer holds it (sold by hand, or the broker's record changed): nothing to
                # sell, so the trader's book lets it go instead of placing a zero-share order every scan.
                book["holdings"].pop(symbol, None)
                book["cost"].pop(symbol, None)
                actions.append({**tag, "symbol": symbol, "action": "gone", "why": "No longer held in the account."})
                continue
            result = _try(submit, OrderRequest(symbol=symbol, side="sell", qty=round(qty, 6), requested_by="ai",
                                               reason=f"{agent['name']} ({signal.get('title', agent['strategy'])}): {signal['why']}"))
            actions.append({**tag, "symbol": symbol, "action": "sell", "result": result["status"], "why": signal["why"]})
            if result["status"] not in _NOT_DONE:
                price = float(result.get("price_at_request") or 0) or quote(symbol)
                share_of_cost = book["cost"].get(symbol, 0.0) * (qty / book["holdings"][symbol])
                book["realized"] = round(book["realized"] + qty * price - share_of_cost, 2)
                book["holdings"][symbol] = round(book["holdings"][symbol] - qty, 6)
                book["cost"][symbol] = round(book["cost"].get(symbol, 0.0) - share_of_cost, 2)
                book["trades"] += 1
                if book["holdings"][symbol] <= 1e-9:
                    book["holdings"].pop(symbol, None)
                    book["cost"].pop(symbol, None)
        # 2) Buy its strongest picks inside its own pot.
        pot = round(agent["share"] * budget, 2)
        free = pot - sum(book["cost"].values())
        slots = MAX_HOLDINGS - len([q for q in book["holdings"].values() if q > 1e-9])
        picks = []
        for symbol in symbols_for(agent, watchlist):
            if symbol in book["holdings"]:
                continue
            signal = read(agent["strategy"], symbol)
            if signal["action"] == "buy" and signal["strength"] >= MIN_STRENGTH:
                picks.append((signal["strength"], symbol, signal))
        picks.sort(key=lambda item: -item[0])
        for strength, symbol, signal in picks:
            if slots <= 0 or free < 1:
                actions.append({**tag, "symbol": symbol, "action": "watch",
                                "why": f"Its pot (${pot:,.0f}) is already spread over {MAX_HOLDINGS} holdings."})
                continue
            notional = round(min(free / slots, allocator.position_cap(ai)), 2)
            if notional < 1:
                continue
            result = _try(submit, OrderRequest(symbol=symbol, side="buy", notional=notional, requested_by="ai",
                                               reason=f"{agent['name']} ({signal.get('title', agent['strategy'])}): {signal['why']}"))
            actions.append({**tag, "symbol": symbol, "action": "buy", "notional": notional, "result": result["status"],
                            "why": signal["why"] if result["status"] not in ("refused", "error") else (result.get("reasons") or [""])[-1]})
            if result["status"] in _NOT_DONE:
                continue
            price = float(result.get("price_at_request") or 0) or quote(symbol)
            book["holdings"][symbol] = round(book["holdings"].get(symbol, 0.0) + notional / max(price, 0.01), 6)
            book["cost"][symbol] = round(book["cost"].get(symbol, 0.0) + notional, 2)
            book["trades"] += 1
            free -= notional
            slots -= 1

    data["runs"] = int(data.get("runs") or 0) + 1
    shift = rebalance(data, quote) if data["runs"] % REBALANCE_EVERY == 0 else None
    data["last"] = {"at": time.time(), "actions": len(actions)}
    _save(data)
    return {"actions": actions, "shift": shift, "agents": _rows(data, quote, budget)}


def rebalance(data: Dict[str, Any], quote: Quote) -> Optional[Dict[str, Any]]:
    """Move a slice of share from the worst agent to the best one, inside the bounds. Returns what moved."""
    live = [a for a in data["agents"] if a["enabled"]]
    if len(live) < 2:
        return None
    scored = sorted(live, key=lambda a: performance(_book(data, a["id"]), quote)["pct"])
    worst, best = scored[0], scored[-1]
    gap = performance(_book(data, best["id"]), quote)["pct"] - performance(_book(data, worst["id"]), quote)["pct"]
    if gap < 2.0:
        return None
    amount = min(SHIFT, worst["share"] - MIN_SHARE, MAX_SHARE - best["share"])
    if amount <= 0.0001:
        return None
    worst["share"] = round(worst["share"] - amount, 4)
    best["share"] = round(best["share"] + amount, 4)
    moved = {"at": time.time(), "from": worst["name"], "to": best["name"], "share": round(amount, 4),
             "why": f"{best['name']} is ahead of {worst['name']} by {gap:.1f} points."}
    data["shifts"] = (data.get("shifts") or [])[-19:] + [moved]
    return moved


def _rows(data: Dict[str, Any], quote: Quote, budget: float) -> List[Dict[str, Any]]:
    rows = []
    for agent in data["agents"]:
        book = _book(data, agent["id"])
        rows.append({**agent, "pot": round(agent["share"] * budget, 2), "holdings": dict(book["holdings"]),
                     "trades": book.get("trades", 0), **performance(book, quote),
                     "strategy_title": strategies.STRATEGIES[agent["strategy"]]["title"],
                     "market_title": MARKETS[agent["market"]]["title"]})
    return rows


def _safe_quote(symbol: str) -> float:
    return float(market.quote(symbol)["price"])


def view(budget: Optional[float] = None, quote: Quote = _safe_quote) -> Dict[str, Any]:
    """What the Trading tab draws: the agents, their pots and results, the last shifts, the choices."""
    data = state()
    if budget is None:
        try:
            from trading import guard

            budget = float(guard.effective_ai(guard.settings()).get("max_invested") or 0)
        except Exception:  # noqa: BLE001
            budget = 0.0
    return {"enabled": bool(data.get("enabled")), "agents": _rows(data, quote, budget), "budget": budget,
            "shifts": list(data.get("shifts") or [])[-8:], "runs": data.get("runs", 0), "last": data.get("last", {}),
            "strategies": [{"id": k, "title": v["title"], "family": v["family"]} for k, v in strategies.STRATEGIES.items()],
            "markets": [{"id": k, "title": v["title"]} for k, v in MARKETS.items()],
            "limits": {"max_agents": MAX_AGENTS, "min_share": MIN_SHARE, "max_share": MAX_SHARE}}


def scan(rules: Dict[str, Any], ai: Dict[str, Any], summary: Dict[str, Any], ai_owned: Dict[str, float]) -> Dict[str, Any]:
    """The autopilot's scan when the desk is on (``autopilot._scan`` hands over after reconciling)."""
    from trading import guard

    try:
        outcome = run(ai, watchlist=list(rules.get("watchlist") or []), submit=guard.submit,
                      history=lambda s: market.history(s, "6mo"), quote=_safe_quote, ai_owned=ai_owned)
    except BrokerError as error:
        summary["skipped"] = str(error)
        return summary
    summary["actions"].extend(outcome["actions"])
    summary["desk"] = {"agents": [{k: r[k] for k in ("name", "pot", "gain", "pct", "trades")} for r in outcome["agents"]],
                       "shift": outcome["shift"]}
    return summary
