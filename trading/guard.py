"""The owner's rules for every order — the part of trading that protects the money.

Order of checks (the first that fails decides):

1. **Halt** stops everything the AI would do until the owner resumes.
2. **Live money is opt-in.** A live broker account refuses orders until the owner
   switches live trading on in Trading → Rules and types the confirmation.
3. **The AI's budget.** An AI order must fit: max per trade, max invested by the
   AI, trades per day, allowed symbols, market hours, and the daily loss stop.
4. **Approval.** Owner orders go straight through. AI orders wait for the owner's
   Approve unless the owner chose "trade within budget without asking" — and on a
   live account an AI order above the "always ask above" amount still waits.

Every request and decision lands in the audit log, including refusals.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import Any, Dict, List, Optional, Tuple

from trading import brokers, market, store
from trading.brokers import BrokerError, OrderRequest

LIVE_CONFIRMATION = "I understand this uses real money"
APPROVAL_TTL = 15 * 60


def default_settings() -> Dict[str, Any]:
    return {
        "active_broker": "paper",
        "live_enabled": False,
        "halted": False,
        "ai": {
            "enabled": False,
            "approval": "always",          # always | above | never (within budget)
            "ask_above": 250.0,            # dollars; used with "above", and always on live accounts
            "max_per_trade": 500.0,
            "max_invested": 2000.0,
            "max_trades_per_day": 5,
            "daily_loss_stop_pct": 3.0,
            # When the AI trader runs (Project Null N80). "market" starts itself at
            # the opening bell and rests overnight; "always" keeps watching around
            # the clock until the owner stops it; "until" stops by itself at
            # ``run_until``. ``market_hours_only`` is kept in step for older code.
            "run_mode": "market",
            "run_until": None,
            "market_hours_only": True,
            "allowed_symbols": [],
            "scan_minutes": 30,
            "research_per_day": 10,        # model analyses the autopilot may spend each day
            "min_confidence": 0.65,
            # Diversification (owner: "should not dump all the money in a dead stock" —
            # trading/allocator.py reads these). max_position_pct is what actually caps
            # concentration on a small account: max_per_trade alone means nothing once the
            # account is smaller than it. target_positions is how many different symbols the
            # allocator tries to keep the budget spread across at once.
            "max_position_pct": 0.3,
            "target_positions": 5,
            # Active selling independent of the indicator ever flipping to "sell" — cut a
            # loser, or lock in a winner, instead of only reacting to a changed signal.
            "stop_loss_pct": 8.0,
            "take_profit_pct": 20.0,
            # Adaptive mode (owner: "a single button … it goes hands off … chooses all values").
            # When on, every key in ADAPTIVE_KEYS the owner hasn't pinned is re-chosen each scan
            # by trading/adaptive.py; ``adaptive_pins`` holds the values the owner did give.
            "adaptive": False,
            "adaptive_pins": {},
            # Rotate out of the weakest holding when a clearly better pick is waiting and the
            # budget is full. Always on in adaptive mode.
            "rotate": False,
            # Auto stock adder (trading/discovery.py): finds promising symbols and adds them to
            # the watchlist; only ever removes symbols it added itself.
            "auto_discover": True,
            "discover_minutes": 90,
            "discover_max_add": 3,
            "watchlist_max": 25,
            # On/off hours on the owner's own clock (this PC's time). Off by default.
            "schedule": {"enabled": False, "days": [0, 1, 2, 3, 4], "start": "09:30", "end": "16:00"},
        },
        "watchlist": ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"],
    }


#: Owner-settable numbers and their sane ranges; adaptive pins are clamped the same way.
LIMITS: Dict[str, Tuple[float, float]] = {
    "max_per_trade": (1, 10_000_000), "max_invested": (1, 10_000_000), "max_trades_per_day": (0, 10_000),
    "daily_loss_stop_pct": (0.1, 90), "ask_above": (0, 1_000_000), "scan_minutes": (5, 1440),
    "research_per_day": (0, 500), "min_confidence": (0.5, 0.99), "max_position_pct": (0.05, 1.0),
    "target_positions": (1, 30), "stop_loss_pct": (0.5, 90), "take_profit_pct": (0.5, 500),
    "discover_minutes": (15, 1440), "discover_max_add": (0, 10), "watchlist_max": (5, 40),
}

#: What adaptive mode chooses for itself unless the owner pinned it.
ADAPTIVE_KEYS = ("max_invested", "max_per_trade", "max_position_pct", "target_positions", "min_confidence",
                 "stop_loss_pct", "take_profit_pct", "scan_minutes", "research_per_day", "daily_loss_stop_pct",
                 "max_trades_per_day", "discover_minutes", "discover_max_add")


def _clean_schedule(value: Any) -> Dict[str, Any]:
    schedule = default_settings()["ai"]["schedule"]
    if not isinstance(value, dict):
        return schedule
    days = [int(d) for d in value.get("days", schedule["days"]) if str(d).lstrip("-").isdigit() and 0 <= int(d) <= 6]
    out = {"enabled": bool(value.get("enabled", schedule["enabled"])), "days": sorted(set(days)) or schedule["days"]}
    for key in ("start", "end"):
        text = str(value.get(key, schedule[key])).strip()
        parts = text.split(":")
        if len(parts) == 2 and all(p.isdigit() for p in parts) and int(parts[0]) < 24 and int(parts[1]) < 60:
            out[key] = f"{int(parts[0]):02d}:{int(parts[1]):02d}"
        else:
            raise BrokerError(f"Schedule {key} must be a time like 09:30.")
    if out["start"] == out["end"]:
        raise BrokerError("The schedule's start and end can't be the same time.")
    return out


def settings() -> Dict[str, Any]:
    data = store.read("settings", default_settings)
    merged = default_settings()
    merged.update({k: v for k, v in data.items() if k != "ai"})
    merged["ai"].update(data.get("ai", {}))
    return merged


def save_settings(changes: Dict[str, Any], confirmation: str = "", actor: str = "owner") -> Dict[str, Any]:
    current = settings()
    if "live_enabled" in changes:
        wanted = bool(changes["live_enabled"])
        if wanted and not current["live_enabled"] and confirmation.strip() != LIVE_CONFIRMATION:
            raise BrokerError(f"To turn on live trading, type exactly: {LIVE_CONFIRMATION}")
        current["live_enabled"] = wanted
    if "active_broker" in changes:
        broker = brokers.get(changes["active_broker"])
        if not broker.connected():
            raise BrokerError(f"Connect {broker.label} first.")
        current["active_broker"] = broker.name
    if "watchlist" in changes:
        symbols = [str(s).strip().upper() for s in changes["watchlist"] if str(s).strip()]
        current["watchlist"] = list(dict.fromkeys(symbols))[:40]
    ai = changes.get("ai") or {}
    for key, (lo, hi) in LIMITS.items():
        if key in ai:
            current["ai"][key] = min(hi, max(lo, float(ai[key])))
    for key in ("enabled", "market_hours_only", "adaptive", "rotate", "auto_discover"):
        if key in ai:
            current["ai"][key] = bool(ai[key])
    if "adaptive_pins" in ai:
        pins = ai["adaptive_pins"] or {}
        current["ai"]["adaptive_pins"] = {k: min(LIMITS[k][1], max(LIMITS[k][0], float(v)))
                                          for k, v in pins.items() if k in ADAPTIVE_KEYS and v not in (None, "")}
    if "schedule" in ai:
        current["ai"]["schedule"] = _clean_schedule(ai["schedule"])
    if "run_mode" in ai and ai["run_mode"] in ("market", "always", "until"):
        current["ai"]["run_mode"] = ai["run_mode"]
        current["ai"]["market_hours_only"] = ai["run_mode"] == "market"
    if "run_until" in ai:
        stamp = ai["run_until"]
        current["ai"]["run_until"] = float(stamp) if stamp else None
    elif "market_hours_only" in ai and "run_mode" not in ai:
        # An older caller flipping the checkbox still means a run mode.
        current["ai"]["run_mode"] = "market" if current["ai"]["market_hours_only"] else "always"
    if "approval" in ai and ai["approval"] in ("always", "above", "never"):
        current["ai"]["approval"] = ai["approval"]
    if "allowed_symbols" in ai:
        current["ai"]["allowed_symbols"] = [str(s).strip().upper() for s in ai["allowed_symbols"] if str(s).strip()][:100]
    store.write("settings", current)
    audit("settings", actor, {"changed": sorted(set(changes) | {f"ai.{k}" for k in ai})})
    return current


def effective_ai(rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The AI rules in force right now: the saved ones, or in adaptive mode the values the AI chose.

    Adaptive mode is hands-off: approval is "never" (live accounts still ask above
    ``ask_above`` in ``check``), and anything the owner pinned wins over the AI's choice.
    """
    rules = rules or settings()
    ai = dict(rules["ai"])
    if not ai.get("adaptive"):
        return ai
    from trading import adaptive

    ai.update(adaptive.current())
    ai.update(ai.get("adaptive_pins") or {})
    ai["approval"] = "never"
    ai["rotate"] = True
    ai["auto_discover"] = True
    return ai


def audit(kind: str, actor: str, detail: Dict[str, Any]) -> None:
    entry = {"at": time.time(), "kind": kind, "actor": actor, **detail}

    def change(data: Dict[str, Any]) -> None:
        data["entries"] = (data["entries"] + [entry])[-1000:]

    store.update("audit", lambda: {"entries": []}, change)


def audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    return list(reversed(store.read("audit", lambda: {"entries": []})["entries"][-limit:]))


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def ai_day() -> Dict[str, Any]:
    """Today's AI counters: trades placed, research spent, starting equity for the loss stop."""
    data = store.read("ai_day", lambda: {"day": _today(), "trades": 0, "research": 0, "start_equity": None})
    if data.get("day") != _today():
        data = {"day": _today(), "trades": 0, "research": 0, "start_equity": None}
        store.write("ai_day", data)
    return data


def _bump_ai_day(field: str, amount: float = 1) -> None:
    def change(data: Dict[str, Any]) -> None:
        if data.get("day") != _today():
            data.clear()
            data.update({"day": _today(), "trades": 0, "research": 0, "start_equity": None})
        data[field] = (data.get(field) or 0) + amount

    store.update("ai_day", lambda: {"day": _today(), "trades": 0, "research": 0, "start_equity": None}, change)


def ai_invested(broker: brokers.Broker) -> float:
    """Dollars currently held in positions the AI opened (tracked by symbol from its own fills)."""
    owned = store.read("ai_positions", lambda: {"symbols": {}})["symbols"]
    total = 0.0
    for position in broker.positions():
        if position["symbol"] in owned:
            total += min(position["market_value"], owned[position["symbol"]] * position["price"])
    return round(total, 2)


def check(order: OrderRequest, broker: brokers.Broker, price: float) -> Tuple[bool, bool, List[str]]:
    """(allowed, needs_approval, reasons)."""
    rules = settings()
    reasons: List[str] = []
    cost = order.estimated_cost(price)
    is_ai = order.requested_by == "ai"

    if broker.live() and not rules["live_enabled"]:
        return False, False, ["Live trading is off. Turn it on in Trading → Rules (paper trading needs no switch)."]
    if not is_ai:
        return True, False, ["Your own order."]

    ai = effective_ai(rules)
    if rules["halted"]:
        return False, False, ["Halted — the AI can't trade until you resume."]
    if ai["allowed_symbols"] and order.symbol not in ai["allowed_symbols"]:
        return False, False, [f"{order.symbol} isn't on the AI's allowed list."]
    if ai["market_hours_only"] and not market.us_market_open():
        return False, False, ["Outside US market hours, and the AI is set to trade only during them."]
    if order.side == "sell":
        # The AI may only sell what it bought; the owner's own holdings are not its to trade.
        owned = store.read("ai_positions", lambda: {"symbols": {}})["symbols"].get(order.symbol, 0.0)
        wanted = order.qty or (order.notional or 0) / max(price, 0.01)
        if wanted > owned + 1e-6:
            return False, False, [f"The AI can only sell shares it bought ({owned:g} of {order.symbol})."]
    if order.side == "buy" and cost > ai["max_per_trade"] + 0.01:
        return False, False, [f"${cost:,.2f} is over the AI's per-trade limit of ${ai['max_per_trade']:,.2f}."]
    day = ai_day()
    if day["trades"] >= ai["max_trades_per_day"]:
        return False, False, [f"The AI already made its {int(ai['max_trades_per_day'])} trades for today."]
    if order.side == "buy":
        invested = ai_invested(broker)
        if invested + cost > ai["max_invested"] + 0.01:
            return False, False, [f"That would put ${invested + cost:,.2f} under AI control; the budget is ${ai['max_invested']:,.2f}."]
    try:
        equity = broker.account()["equity"]
        if day.get("start_equity") is None:
            store.update("ai_day", lambda: day, lambda data: data.__setitem__("start_equity", equity))
        elif equity < day["start_equity"] * (1 - ai["daily_loss_stop_pct"] / 100) and order.side == "buy":
            return False, False, [f"Down more than {ai['daily_loss_stop_pct']}% today — the loss stop blocks new AI buys."]
    except BrokerError as error:
        reasons.append(f"Couldn't check the loss stop: {error}")

    needs = ai["approval"] == "always" or (ai["approval"] == "above" and cost > ai["ask_above"]) \
        or (broker.live() and cost > ai["ask_above"])
    reasons.append("Waiting for your approval." if needs else "Within the AI's budget.")
    return True, needs, reasons


def submit(order: OrderRequest) -> Dict[str, Any]:
    """Run an order through the rules, then place it, queue it for approval, or refuse it."""
    order.validate()
    rules = settings()
    broker = brokers.get(rules["active_broker"])
    if not broker.connected():
        raise BrokerError(f"{broker.label} isn't connected.")
    price = market.quote(order.symbol)["price"]
    allowed, needs_approval, reasons = check(order, broker, price)
    if allowed and order.requested_by == "ai":
        # The finance lab's capital guard: once the owner has given the AI a pot of
        # its own, it may spend only that pot plus what it actually earned — never
        # debt, never margin. With no pot allocated it allows and says so, so an
        # unopened finance lab can never silently stop a trader that already works.
        # It fails open, so a bug there cannot block an order either.
        try:
            from finance_lab import capital_guard

            permitted, why = capital_guard.check_order(order, price, live=broker.live())
        except Exception as error:  # noqa: BLE001 - the guard is a safety net, not a gate
            permitted, why = True, f"(capital guard skipped: {type(error).__name__})"
        allowed = allowed and permitted
        if why:
            reasons = reasons + [why]
    record = {"order": asdict(order), "broker": broker.name, "live": broker.live(), "price_at_request": price,
              "estimated_cost": round(order.estimated_cost(price), 2), "reasons": reasons}
    if not allowed:
        audit("refused", order.requested_by, record)
        return {"status": "refused", **record}
    if needs_approval:
        approval = {"id": uuid.uuid4().hex[:10], "created_at": time.time(), "expires_at": time.time() + APPROVAL_TTL, **record}
        store.update("approvals", lambda: {"pending": []}, lambda data: data["pending"].append(approval))
        audit("approval_requested", order.requested_by, record)
        return {"status": "awaiting_approval", "approval_id": approval["id"], **record}
    return _place(order, broker, record)


def _place(order: OrderRequest, broker: brokers.Broker, record: Dict[str, Any]) -> Dict[str, Any]:
    placed = broker.place(order)
    if order.requested_by == "ai" and placed.get("status") not in ("rejected", "canceled"):
        _bump_ai_day("trades")
        qty = placed.get("filled_qty") or order.qty or (order.notional or 0) / max(record["price_at_request"], 0.01)

        def change(data: Dict[str, Any]) -> None:
            symbols = data["symbols"]
            symbols[order.symbol] = max(0.0, symbols.get(order.symbol, 0.0) + (qty if order.side == "buy" else -qty))
            if symbols[order.symbol] <= 1e-9:
                symbols.pop(order.symbol, None)

        store.update("ai_positions", lambda: {"symbols": {}}, change)
    audit("placed", order.requested_by, {**record, "result": placed})
    return {"status": placed.get("status", "submitted"), "order_result": placed, **record}


def pending_approvals() -> List[Dict[str, Any]]:
    now = time.time()
    data = store.read("approvals", lambda: {"pending": []})
    return [a for a in data["pending"] if a["expires_at"] > now]


def decide(approval_id: str, approve: bool) -> Dict[str, Any]:
    found: Dict[str, Any] = {}

    def change(data: Dict[str, Any]) -> None:
        for item in data["pending"]:
            if item["id"] == approval_id:
                found.update(item)
        data["pending"] = [a for a in data["pending"] if a["id"] != approval_id and a["expires_at"] > time.time()]

    store.update("approvals", lambda: {"pending": []}, change)
    if not found:
        raise BrokerError("That approval expired or was already decided.")
    if found["expires_at"] <= time.time():
        raise BrokerError("That approval expired — prices move; ask the AI again.")
    if not approve:
        audit("declined", "owner", found)
        return {"status": "declined"}
    order = OrderRequest(**found["order"])
    broker = brokers.get(found["broker"])
    if broker.live() and not settings()["live_enabled"]:
        raise BrokerError("Live trading was turned off since this was requested.")
    audit("approved", "owner", {"order": found["order"]})
    return _place(order, broker, {**found, "reasons": found["reasons"] + ["Approved by you."]})


def halt(reason: str = "") -> Dict[str, Any]:
    """Stop the AI now: autopilot off, pending AI approvals dropped, open orders cancelled on paper."""
    current = settings()
    current["halted"] = True
    current["ai"]["enabled"] = False
    store.write("settings", current)
    store.write("approvals", {"pending": []})
    cancelled = 0
    broker = brokers.get(current["active_broker"])
    try:
        for order in broker.orders():
            is_ai = order.get("requested_by") == "ai" or str(order.get("client_order_id", "")).startswith("nyx-ai-")
            if is_ai and order.get("status") in ("open", "new", "accepted", "pending_new", "partially_filled"):
                broker.cancel(order["id"])
                cancelled += 1
    except BrokerError:
        pass
    audit("halt", "owner", {"reason": reason, "cancelled": cancelled})
    return {"halted": True, "cancelled": cancelled}


def resume() -> Dict[str, Any]:
    current = settings()
    current["halted"] = False
    store.write("settings", current)
    audit("resume", "owner", {})
    return current


def note_research() -> bool:
    """Spend one unit of the day's research budget; False when it is used up."""
    ai = settings()["ai"]
    if ai_day()["research"] >= ai["research_per_day"]:
        return False
    _bump_ai_day("research")
    return True
