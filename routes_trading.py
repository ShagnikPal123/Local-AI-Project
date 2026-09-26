"""HTTP routes for Trading (Request G1). Owner-only; absent from hosted builds (deploy_mode)."""

from __future__ import annotations

import functools
import os
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner_dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
    from server import require_local_owner

    return require_local_owner(http_request, authorization)


Owner = Depends(_owner_dependency)


def _broker_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from trading.brokers import BrokerError
        from trading.market import MarketDataError

        try:
            return fn(*args, **kwargs)
        except (BrokerError, MarketDataError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    return wrapper


class ConnectRequest(BaseModel):
    values: Dict[str, Any]


class SettingsRequest(BaseModel):
    changes: Dict[str, Any]
    confirmation: str = ""


class OrderBody(BaseModel):
    symbol: str
    side: str
    qty: Optional[float] = None
    notional: Optional[float] = None
    type: str = "market"
    limit_price: Optional[float] = None


class DecisionBody(BaseModel):
    approve: bool


class HaltBody(BaseModel):
    reason: str = ""


class PaperResetBody(BaseModel):
    cash: float = 100_000.0


class RunModeBody(BaseModel):
    #: market = the US session, starting itself at the opening bell;
    #: always = around the clock until stopped; until = around the clock until ``until``.
    mode: str = "market"
    #: Epoch seconds, for mode "until".
    until: Optional[float] = None


class StopBody(BaseModel):
    reason: str = ""


class PaperSettingsBody(BaseModel):
    changes: Dict[str, Any] = {}


class AdaptiveBody(BaseModel):
    on: bool
    #: Dollars the AI may have invested; blank = it decides each scan.
    budget: Optional[float] = None
    #: Practice account only: reset to this amount first.
    starting_cash: Optional[float] = None
    mode: Optional[str] = None
    until: Optional[float] = None
    schedule: Optional[Dict[str, Any]] = None
    pins: Optional[Dict[str, Any]] = None


def _safe(fn, fallback):
    try:
        return fn()
    except Exception as error:  # noqa: BLE001 - one broker call failing must not blank the whole page
        return {"error": str(error)} if isinstance(fallback, dict) else fallback


@router.get("/api/trading/state")
def trading_state(_owner=Owner) -> Dict[str, Any]:
    """Everything the Trading tab shows, in one call."""
    from trading import autopilot, brokers, guard, signals

    from trading import market

    rules = guard.settings()
    broker = brokers.get(rules["active_broker"])
    practice = broker.money() == "practice"
    return {
        "brokers": brokers.describe(),
        "settings": rules,
        # The rules actually in force — in adaptive mode, the values the AI chose this scan.
        "effective_ai": _safe(lambda: guard.effective_ai(rules), {}),
        "live_confirmation": guard.LIVE_CONFIRMATION,
        "account": _safe(broker.account, {}),
        "positions": _safe(broker.positions, []),
        "orders": _safe(broker.orders, [])[:30],
        "approvals": guard.pending_approvals(),
        "ai_invested": _safe(lambda: guard.ai_invested(broker), 0.0),
        "autopilot": autopilot.status(),
        "runs": autopilot.runs(5),
        "track_record": _safe(signals.score_track_record, {}),
        "audit": guard.audit_log(40),
        # Which money this account uses, said once, in one place, for the whole tab.
        "money": broker.money(),
        "money_label": "Practice money — nothing real is bought or sold" if practice else "REAL MONEY — this account is yours",
        "session": _safe(market.session, {}),
        "run": _safe(autopilot.run_status, {}),
        "paper": {"settings": brokers.paper_settings(), "stats": _safe(brokers.get("paper").stats, {})},
        **_ai_extras(),
        "disclaimer": "Signals are statistical estimates, not financial advice. Trading can lose money; practice money cannot.",
    }


@router.post("/api/trading/brokers/{name}/connect")
@_broker_errors
def connect_broker(name: str, body: ConnectRequest, _owner=Owner) -> Dict[str, Any]:
    from trading import brokers, guard

    broker = brokers.get(name)
    broker.connect({k: str(v) for k, v in body.values.items()})
    try:
        account = broker.account()
    except Exception as error:  # noqa: BLE001 - keys saved, but say it did not work
        guard.audit("connect_failed", "owner", {"broker": name, "error": str(error)[:200]})
        raise HTTPException(status_code=400, detail=f"Saved, but the test failed: {error}") from error
    guard.audit("connected", "owner", {"broker": name, "live": broker.live()})
    return {"broker": name, "account": account}


@router.delete("/api/trading/brokers/{name}")
@_broker_errors
def disconnect_broker(name: str, _owner=Owner) -> Dict[str, Any]:
    from trading import brokers, guard

    brokers.get(name).disconnect()
    rules = guard.settings()
    if rules["active_broker"] == name:
        guard.save_settings({"active_broker": "paper"})
    guard.audit("disconnected", "owner", {"broker": name})
    return {"ok": True}


@router.post("/api/trading/brokers/snaptrade/portal")
@_broker_errors
def snaptrade_portal(_owner=Owner) -> Dict[str, Any]:
    """The SnapTrade page where the owner signs in to their own brokerage (Robinhood, Schwab, Fidelity…)."""
    from trading import brokers

    return {"url": brokers.get("snaptrade").connection_portal()}


@router.put("/api/trading/settings")
@_broker_errors
def update_settings(body: SettingsRequest, _owner=Owner) -> Dict[str, Any]:
    from trading import autopilot, guard

    rules = guard.save_settings(body.changes, body.confirmation)
    if rules["ai"]["enabled"]:
        autopilot.ensure_running()
    return {"settings": rules}


@router.get("/api/trading/quote")
@_broker_errors
def quote(symbol: str, _owner=Owner) -> Dict[str, Any]:
    from trading import market

    return market.quote(symbol)


@router.get("/api/trading/signals")
@_broker_errors
def trading_signals(symbols: str = "", _owner=Owner) -> Dict[str, Any]:
    from trading import guard, market, signals

    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()] or guard.settings()["watchlist"]
    out: List[Dict[str, Any]] = []
    for symbol in wanted[:25]:
        try:
            out.append(signals.signal_for(symbol))
        except market.MarketDataError as error:
            out.append({"symbol": symbol, "error": str(error)})
    return {"signals": out, "market_open": market.us_market_open()}


@router.post("/api/trading/orders")
@_broker_errors
def place_order(body: OrderBody, _owner=Owner) -> Dict[str, Any]:
    """The owner's own order. It still passes the live-trading switch."""
    from trading import guard
    from trading.brokers import OrderRequest

    return guard.submit(OrderRequest(symbol=body.symbol, side=body.side, qty=body.qty, notional=body.notional, type=body.type,
                                     limit_price=body.limit_price, requested_by="owner"))


@router.delete("/api/trading/orders/{order_id}")
@_broker_errors
def cancel_order(order_id: str, _owner=Owner) -> Dict[str, Any]:
    from trading import brokers, guard

    broker = brokers.get(guard.settings()["active_broker"])
    broker.cancel(order_id)
    guard.audit("cancelled", "owner", {"order_id": order_id, "broker": broker.name})
    return {"ok": True}


@router.post("/api/trading/approvals/{approval_id}")
@_broker_errors
def decide_approval(approval_id: str, body: DecisionBody, _owner=Owner) -> Dict[str, Any]:
    from trading import guard

    return guard.decide(approval_id, body.approve)


@router.post("/api/trading/halt")
def halt(body: HaltBody, _owner=Owner) -> Dict[str, Any]:
    from trading import guard

    return guard.halt(body.reason)


@router.post("/api/trading/resume")
def resume(_owner=Owner) -> Dict[str, Any]:
    from trading import guard

    return {"settings": guard.resume()}


@router.post("/api/trading/autopilot/scan")
@_broker_errors
def scan_now(_owner=Owner) -> Dict[str, Any]:
    """Run one scan now, even with the schedule off — orders still obey every rule."""
    from trading import autopilot

    return autopilot.run_once(force=True)


@router.post("/api/trading/paper/reset")
def reset_paper(body: PaperResetBody, _owner=Owner) -> Dict[str, Any]:
    from trading import brokers, guard, store

    # $1 floor, not $100 — the owner may deliberately want a small, realistic starting
    # balance (e.g. "start with $50") to see how the AI grows a small amount, not just
    # a big pretend account.
    brokers.get("paper").reset(max(1.0, min(10_000_000.0, body.cash)))
    store.write("ai_positions", {"symbols": {}})
    guard.audit("paper_reset", "owner", {"cash": body.cash})
    return {"ok": True}


@router.post("/api/trading/run-mode")
@_broker_errors
def set_run_mode(body: RunModeBody, _owner=Owner) -> Dict[str, Any]:
    """When the AI trader works: the US session, around the clock, or until a time (N80).

    Picking a mode also switches the AI trader on, so nobody has to start it at
    the opening bell — that was the whole complaint.
    """
    from trading import autopilot

    return {"run": autopilot.set_run_mode(body.mode, body.until)}


@router.post("/api/trading/autopilot/stop")
@_broker_errors
def stop_autopilot(body: StopBody, _owner=Owner) -> Dict[str, Any]:
    """Stop the schedule (positions stay as they are)."""
    from trading import autopilot

    return {"run": autopilot.stop(body.reason or "You stopped the AI trader.")}


@router.get("/api/trading/run")
def run_state(_owner=Owner) -> Dict[str, Any]:
    """Just the schedule — cheap enough for a countdown that ticks."""
    from trading import autopilot

    return {"run": autopilot.run_status()}


@router.put("/api/trading/paper/settings")
@_broker_errors
def update_paper_settings(body: PaperSettingsBody, _owner=Owner) -> Dict[str, Any]:
    """How true to life the practice account is (spread, slippage, commission, queue when closed)."""
    from trading import brokers

    settings = brokers.save_paper_settings(body.changes)
    return {"settings": settings, "stats": _safe(brokers.get("paper").stats, {})}


def _ai_extras() -> Dict[str, Any]:
    """Adaptive mode, the auto stock adder and the AI's lessons — for /state and /adaptive."""
    from trading import adaptive, discovery, lessons

    return {
        "adaptive": _safe(adaptive.status, {}),
        "discovery": _safe(discovery.status, {}),
        "lessons": {"summary": _safe(lessons.summary, {}), "recent": _safe(lambda: lessons.exits(12), []),
                    "cooldowns": _safe(lessons.cooldowns, {})},
    }


@router.get("/api/trading/adaptive")
def adaptive_state(_owner=Owner) -> Dict[str, Any]:
    from trading import autopilot

    return {**_ai_extras(), "run": _safe(autopilot.run_status, {})}


@router.post("/api/trading/adaptive")
@_broker_errors
def set_adaptive(body: AdaptiveBody, _owner=Owner) -> Dict[str, Any]:
    """The one button: hands-off adaptive mode on (it chooses everything not given) or off (trader stops)."""
    from trading import autopilot

    result = autopilot.set_adaptive(body.on, budget=body.budget, starting_cash=body.starting_cash, mode=body.mode,
                                    until_ts=body.until, schedule=body.schedule, pins=body.pins)
    return {**result, **_ai_extras()}


@router.post("/api/trading/discover")
@_broker_errors
def discover_now(_owner=Owner) -> Dict[str, Any]:
    """Run the auto stock adder once now."""
    from trading import autopilot, discovery, guard, store

    rules = guard.settings()
    held = set(store.read("ai_positions", lambda: {"symbols": {}})["symbols"])
    found = discovery.discover(rules, guard.effective_ai(rules), held=held, force=True, research_fn=autopilot.researched)
    return {"result": found, "watchlist": guard.settings()["watchlist"], "discovery": discovery.status()}


@router.on_event("startup")
def _start_schedule() -> None:
    """Resume the owner's AI trader when a real engine starts.

    It used to run at import time, so anything that merely imported the server (pytest
    collecting tests/test_server.py, a look-only engine) resumed the owner's real trader
    and scanned their account. A test run and NYX_NO_BACKGROUND leave it alone, the same
    gates as server._resume_background_work.
    """
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("NYX_NO_BACKGROUND"):
        return
    try:
        from trading import autopilot

        autopilot.ensure_running()
    except Exception:  # pragma: no cover - trading must never stop the engine starting
        pass


# ---------------------------------------------------------------------------
# Chat tools
# ---------------------------------------------------------------------------


def tool_trading_status() -> str:
    from trading import brokers, guard

    rules = guard.settings()
    broker = brokers.get(rules["active_broker"])
    try:
        account = broker.account()
        positions = broker.positions()
    except Exception as error:  # noqa: BLE001
        return f"Could not read the {broker.name} account: {error}"
    money = "REAL MONEY" if broker.money() == "real" else "PRACTICE MONEY (simulated, nothing real is bought or sold)"
    lines = [f"Account: {broker.label} — {money} · equity ${account['equity']:,.2f} · cash ${account['cash']:,.2f}",
             f"AI trader: {'on' if rules['ai']['enabled'] else 'off'}{' (HALTED)' if rules['halted'] else ''}, approval {rules['ai']['approval']}, "
             f"budget ${rules['ai']['max_invested']:,.0f}, per trade ${rules['ai']['max_per_trade']:,.0f}"]
    lines += [f"- {p['symbol']}: {p['qty']:g} @ ${p['avg_price']:,.2f} → ${p['price']:,.2f} ({p['pl_pct']:+.2f}%)" for p in positions[:20]]
    pending = guard.pending_approvals()
    if pending:
        lines.append(f"{len(pending)} order(s) waiting for the owner's approval in the Trading tab.")
    return "\n".join(lines)


def tool_trading_signal(symbol: str) -> str:
    from trading import market, signals

    try:
        s = signals.signal_for(symbol)
    except market.MarketDataError as error:
        return f"Error: {error}"
    ind = s["indicators"]
    return (f"{s['symbol']} ${ind['price']:,.2f} ({s.get('change_pct') or 0:+.2f}% today) — signal {s['signal'].upper()} "
            f"(confidence {s['confidence']:.0%}). Reasons: {' '.join(s['reasons'])} RSI {ind['rsi14']}, 20-day {ind['return_20d']}%. "
            "Tell the owner this is a statistical signal, not financial advice.")


def tool_trading_order(symbol: str, side: str, qty: float = 0, dollars: float = 0, limit_price: float = 0) -> str:
    """An order the AI proposes in chat. It always goes through the owner's rules; usually it waits for approval."""
    from trading import guard
    from trading.brokers import BrokerError, OrderRequest

    try:
        result = guard.submit(OrderRequest(symbol=symbol, side=str(side).lower(), qty=qty or None, notional=dollars or None,
                                           type="limit" if limit_price else "market", limit_price=limit_price or None,
                                           requested_by="ai", reason="Asked for in chat"))
    except BrokerError as error:
        return f"Order not placed: {error}"
    status = result["status"]
    if status == "awaiting_approval":
        return "The order is waiting for the owner's approval in the Trading tab (it expires in 15 minutes). Tell the owner."
    if status == "refused":
        return f"The owner's rules refused it: {' '.join(result['reasons'])}"
    money = " with REAL MONEY" if result["live"] else " with practice money (simulated)"
    return f"Order {status} on {result['broker']}{money}: {result.get('order_result')}"


def tool_trading_opportunities() -> str:
    """The best-ranked buy/sell opportunities right now, out of the whole watchlist — not just one symbol."""
    from trading import guard, signals

    rules = guard.settings()
    ranked = signals.rank_watchlist(rules["watchlist"][:20], record=False)
    usable = [s for s in ranked if "error" not in s]
    if not usable:
        return "No usable signals right now (no price data for the watchlist)."
    lines = ["Ranked by expected value (score × confidence × how reliable that symbol's past signals were). Not financial advice:"]
    for s in usable[:10]:
        rel = s["reliability"]
        track = f", track record {rel['hit_rate']:.0%} over {rel['graded']} graded signals" if rel["hit_rate"] is not None else ", no track record yet"
        lines.append(f"- {s['symbol']}: {s['signal'].upper()} (confidence {s['confidence']:.0%}{track}) — {' '.join(s['reasons'][:2])}")
    return "\n".join(lines)


def tool_trading_configure(starting_cash: float = 0, enabled: Optional[bool] = None, approval: str = "",
                           max_per_trade: float = 0, max_invested: float = 0, target_positions: float = 0,
                           stop_loss_pct: float = 0, take_profit_pct: float = 0, min_confidence: float = 0) -> str:
    """Change the AI trader's PAPER practice settings from chat. Refuses to touch a live/real-money broker."""
    from trading import brokers, guard, store as trading_store

    if guard.settings()["active_broker"] != "paper":
        return "The active broker isn't Paper — switch to Paper in the Trading tab first. This tool only changes practice-money settings, never a live broker."
    lines: List[str] = []
    if starting_cash:
        amount = max(1.0, min(10_000_000.0, starting_cash))
        brokers.get("paper").reset(amount)
        trading_store.write("ai_positions", {"symbols": {}})
        guard.audit("paper_reset", "ai", {"cash": amount})
        lines.append(f"Practice account reset to ${amount:,.2f}.")
    ai: Dict[str, Any] = {}
    if enabled is not None:
        ai["enabled"] = bool(enabled)
    if approval in ("always", "above", "never"):
        ai["approval"] = approval
    for key, value in (("max_per_trade", max_per_trade), ("max_invested", max_invested), ("target_positions", target_positions),
                       ("stop_loss_pct", stop_loss_pct), ("take_profit_pct", take_profit_pct), ("min_confidence", min_confidence)):
        if value:
            ai[key] = value
    if ai:
        rules = guard.save_settings({"ai": ai})
        lines.append(f"AI trader: {'on' if rules['ai']['enabled'] else 'off'}, approval={rules['ai']['approval']}, "
                     f"budget ${rules['ai']['max_invested']:,.0f} across up to {int(rules['ai']['target_positions'])} positions, "
                     f"per-trade cap ${rules['ai']['max_per_trade']:,.0f}, stop-loss {rules['ai']['stop_loss_pct']:.0f}%, "
                     f"take-profit {rules['ai']['take_profit_pct']:.0f}%.")
        if rules["ai"]["enabled"]:
            from trading import autopilot

            autopilot.ensure_running()
    if not lines:
        return "Nothing to change — say a starting amount (e.g. 50) or a setting to update."
    return " ".join(lines)


def tool_trading_adaptive(on: bool = True, budget: float = 0, starting_cash: float = 0, mode: str = "") -> str:
    """Turn hands-off adaptive mode on or off from chat."""
    from trading import autopilot
    from trading.brokers import BrokerError

    try:
        result = autopilot.set_adaptive(bool(on), budget=budget or None, starting_cash=starting_cash or None,
                                        mode=mode or None, actor="ai")
    except BrokerError as error:
        return f"Not changed: {error}"
    status, run = result["adaptive"], result["run"]
    if not status["on"]:
        return "Adaptive mode is off and the AI trader has stopped. The owner's own rules are unchanged."
    chosen = status.get("chosen") or {}
    budget_words = f"${status['pins']['max_invested']:,.2f} (owner's)" if "max_invested" in status["pins"] \
        else f"${chosen.get('max_invested', 0):,.2f} (its own choice, re-chosen each scan)"
    return (f"Adaptive mode is ON — hands-off. Budget {budget_words}; spread across up to {int(chosen.get('target_positions') or 0)} "
            f"stocks; stop-loss {chosen.get('stop_loss_pct')}%, take-profit {chosen.get('take_profit_pct')}%; no daily trade limit; "
            f"it finds and researches new stocks itself. {run['summary']} The owner can Halt or Stop at any time.")


def tool_trading_discover() -> str:
    """Run the auto stock adder once."""
    from trading import autopilot, discovery, guard, store

    rules = guard.settings()
    held = set(store.read("ai_positions", lambda: {"symbols": {}})["symbols"])
    found = discovery.discover(rules, guard.effective_ai(rules), held=held, force=True, research_fn=autopilot.researched)
    added = ", ".join(f"{a['symbol']} ({a['why']})" for a in found.get("added") or []) or "nothing new worth adding"
    removed = ", ".join(f"{r['symbol']} ({r['why']})" for r in found.get("removed") or [])
    return f"Looked at {found.get('considered', 0)} stocks ({found.get('from_news', 0)} from today's news). Added: {added}." \
        + (f" Removed: {removed}." if removed else "")


def register_trading_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register("trading_status", "The owner's trading account: equity, cash, positions, AI trader state and pending approvals.",
                      [], tool_trading_status, category="finance", label=lambda a: "Reading the trading account")
    registry.register("trading_signal", "Nyx's indicator signal for a stock (trend, momentum, RSI, volume) with reasons. Not advice.",
                      [ToolParam("symbol", "string", "Ticker, e.g. NVDA")], tool_trading_signal, category="finance",
                      label=lambda a: f"Checking {str(a.get('symbol', '')).upper()}")
    registry.register("trading_opportunities", "Scan the whole watchlist and rank the best current buy/sell opportunities by expected "
                      "value, factoring in how reliable each symbol's past signals were. Use this instead of trading_signal when the "
                      "owner asks what looks good right now rather than about one specific stock.",
                      [], tool_trading_opportunities, category="finance", label=lambda a: "Scanning for the best opportunities")
    registry.register("trading_order", "Propose a stock order for the owner's account. It passes the owner's trading rules and "
                      "normally waits for their approval; never claim it filled unless the result says so.",
                      [ToolParam("symbol", "string", "Ticker"), ToolParam("side", "string", "buy or sell", enum_values=["buy", "sell"]),
                       ToolParam("qty", "number", "Shares", required=False), ToolParam("dollars", "number", "Dollar amount instead of shares", required=False),
                       ToolParam("limit_price", "number", "Limit price (omit for market)", required=False)],
                      tool_trading_order, category="finance", label=lambda a: f"Proposing {a.get('side', '')} {str(a.get('symbol', '')).upper()}")
    registry.register("trading_configure", "Change the AI trader's PAPER practice settings: starting cash (e.g. 'start with $50'), "
                      "on/off, approval mode (always ask / ask above an amount / trade automatically within budget), per-trade and "
                      "total budget, how many positions to diversify across, stop-loss/take-profit percentages, and the confidence "
                      "bar. Never touches a live broker or real money.",
                      [ToolParam("starting_cash", "number", "Reset the practice account to this many dollars, e.g. 50", required=False),
                       ToolParam("enabled", "boolean", "Turn the AI trader on or off", required=False),
                       ToolParam("approval", "string", "always = ask every time, above = ask above ask_above, never = trade within budget automatically",
                                 required=False, enum_values=["always", "above", "never"]),
                       ToolParam("max_per_trade", "number", "Dollar ceiling for one order", required=False),
                       ToolParam("max_invested", "number", "Total dollars the AI may have invested at once", required=False),
                       ToolParam("target_positions", "number", "How many different stocks to spread the budget across", required=False),
                       ToolParam("stop_loss_pct", "number", "Sell a position automatically if it falls this many percent", required=False),
                       ToolParam("take_profit_pct", "number", "Sell a position automatically once it gains this many percent", required=False),
                       ToolParam("min_confidence", "number", "0.5-0.99, how sure a signal must be before acting", required=False)],
                      tool_trading_configure, category="finance", label=lambda a: "Updating the AI trader's settings")
    registry.register("trading_adaptive", "Turn the AI trader's hands-off ADAPTIVE mode on or off. On: it chooses its own budget "
                      "(unless given), position sizes, stops, pace and stocks every scan, finds and researches new stocks, no daily "
                      "trade limit; the owner can only Halt or Stop. Off: the trader stops. Use when the owner asks to go hands-off.",
                      [ToolParam("on", "boolean", "true = turn on, false = turn off"),
                       ToolParam("budget", "number", "Dollars it may have invested; omit to let it decide", required=False),
                       ToolParam("starting_cash", "number", "Practice account only: reset to this amount first, e.g. 50", required=False),
                       ToolParam("mode", "string", "always = until stopped (default), market = US market hours only",
                                 required=False, enum_values=["always", "market"])],
                      tool_trading_adaptive, category="finance",
                      label=lambda a: "Turning adaptive trading " + ("on" if a.get("on", True) else "off"))
    registry.register("trading_discover", "Run the auto stock adder now: scan its stock universe and today's market news for "
                      "stocks doing well or predicted to, research the best, and add them to the watchlist.",
                      [], tool_trading_discover, category="finance", label=lambda a: "Looking for new stocks")
