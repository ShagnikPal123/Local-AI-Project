"""The AI trader: scans the watchlist on the owner's schedule and budget, and trades only through the guard.

What the owner controls ("the AI devotes the resources the user wants"): how often it
scans, how many symbols, how many model research calls a day, how confident a signal
must be, and every money limit in ``guard``. With approval set to "always" (the
default) the autopilot only ever proposes — each order waits for the owner.

**Run modes** (Project Null N80 — "allow a mode for active 24/7 or until stop so the
user doesnt ahve to manually start when US markets open"):

* ``market`` — works the regular session and sleeps until the next opening bell,
  which it works out itself from the NYSE calendar. Nobody has to start it at 9:30.
* ``always`` — keeps watching around the clock until the owner stops it. Out of
  hours it scans at a slower pace (fewer API calls while nothing trades) and orders
  queue for the next open instead of filling on a stale price.
* ``until`` — the same, and it switches itself off at the time the owner picked.

The mode lives in the saved settings, so a restart picks it up again: ``ensure_running``
runs when the engine starts.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any, Dict, List, Optional

from trading import adaptive, allocator, brokers, discovery, guard, lessons, market, signals, store
from trading.brokers import BrokerError, OrderRequest

_THREAD: Optional[threading.Thread] = None
_WAKE = threading.Event()
_LOCK = threading.Lock()
#: One scan at a time. Two at once (the schedule plus "Scan now") would both see the same
#: empty slots and buy the same stocks twice.
_SCAN_LOCK = threading.Lock()

RUN_MODES = ("market", "always", "until")

#: How long the loop may sleep in one go. It wakes on any settings change anyway
#: (``wake()``); the cap only keeps the countdown and the calendar fresh.
_MAX_SLEEP = 30 * 60.0

#: Out of hours in a 24/7 run: scan this much less often, and never faster than 15 minutes.
_CLOSED_SLOWDOWN = 2.0
_CLOSED_MIN_MINUTES = 15.0

#: What the schedule is doing, for the Trading tab (not saved: it describes this process).
_STATE: Dict[str, Any] = {"started_at": 0.0, "last_scan_at": 0.0, "next_scan_at": 0.0, "resting": "",
                          "scans": 0, "stopped_reason": ""}


def run_mode(rules: Optional[Dict[str, Any]] = None) -> str:
    """The saved run mode, falling back to the old ``market_hours_only`` flag."""
    ai = (rules or guard.settings())["ai"]
    mode = str(ai.get("run_mode") or "")
    if mode not in RUN_MODES:
        mode = "market" if ai.get("market_hours_only", True) else "always"
    return mode


_VERDICT = re.compile(r"VERDICT\s*[:\-]\s*\**\s*(OK|AVOID)\b", re.IGNORECASE)
#: The instruction itself says "VERDICT: OK or VERDICT: AVOID"; a model that thinks out loud
#: repeats it, and the old substring check read that echo as a red flag on every stock.
_ECHO = re.compile(r"VERDICT\s*:\s*OK\s*(?:or|/)\s*VERDICT\s*:\s*AVOID", re.IGNORECASE)
RESEARCH_TTL = 6 * 3600


def read_verdict(text: str) -> Dict[str, Any]:
    """The model's own final verdict — its last VERDICT line, never the echoed instruction. Pure."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL | re.IGNORECASE)
    text = _ECHO.sub("", text).strip()
    matches = list(_VERDICT.finditer(text))
    if not matches:
        return {"thesis": (text[:400] + " (No clear verdict — not treated as a red flag.)").strip(), "avoid": False}
    last = matches[-1]
    thesis = text[:last.start()].strip() or text[last.end():].strip()
    return {"thesis": thesis[-600:], "avoid": last.group(1).upper() == "AVOID"}


def research(symbol: str, signal: Dict[str, Any]) -> Dict[str, Any]:
    """Recent news and a short model read on it. Returns {"thesis", "avoid", "model"}; never raises."""
    try:
        from tools import TOOL_REGISTRY

        news = TOOL_REGISTRY.call_tool("search_web", query=f"{symbol} stock news this week", engine="all", freshness="week")
    except Exception as error:  # noqa: BLE001 - research is optional
        news = f"(search unavailable: {error})"
    try:
        from model_roles import MODEL_ROLES

        run = MODEL_ROLES.run(
            "fast_chat",
            f"Ticker {symbol}. Indicator signal: {signal['signal']} (score {signal['score']}, reasons: {'; '.join(signal['reasons'])}).\n"
            f"Recent news search results:\n{str(news)[:6000]}\n\n"
            "In at most three sentences: what is moving this stock and is there a specific red flag (fraud, bankruptcy, "
            "trading halt, pending acquisition, earnings in the next 2 days)? Then write one last line that is either "
            "VERDICT: OK or VERDICT: AVOID — AVOID only for a specific red flag you named.",
            system="detailed thinking off\nYou are a careful equity analyst. Be brief and factual.",
            max_tokens=300,
        )
        return {**read_verdict(run.text), "model": run.label}
    except Exception as error:  # noqa: BLE001
        return {"thesis": f"No model research: {error}", "avoid": False, "model": ""}


def researched(symbol: str, signal: Dict[str, Any]) -> Dict[str, Any]:
    """``research`` with a 6-hour memory and the daily research budget — a 5-minute scan pace
    must not re-read the same news (and spend a model call) for the same stock every scan."""
    cached = store.read("research_cache", lambda: {}).get(symbol)
    if cached and time.time() - float(cached.get("at") or 0) < RESEARCH_TTL:
        return {**cached["result"], "cached": True}
    if not guard.note_research():
        return {"thesis": "Research budget for today is used up.", "avoid": False}
    result = research(symbol, signal)
    if result.get("model"):
        def change(data: Dict[str, Any]) -> None:
            data[symbol] = {"at": time.time(), "result": result}
            for old in [s for s, v in data.items() if time.time() - float(v.get("at") or 0) > RESEARCH_TTL]:
                data.pop(old, None)

        store.update("research_cache", lambda: {}, change)
    return result


def _owned() -> Dict[str, float]:
    return dict(store.read("ai_positions", lambda: {"symbols": {}})["symbols"])


_WAITING = ("queued", "open", "new", "accepted", "pending_new", "partially_filled")


def _pending_ai_orders(broker: brokers.Broker) -> List[Dict[str, Any]]:
    """AI orders placed but not filled yet (e.g. queued for the opening bell)."""
    try:
        orders = broker.orders()
    except BrokerError:
        return []
    return [o for o in orders if o.get("status") in _WAITING
            and (o.get("requested_by") == "ai" or str(o.get("client_order_id", "")).startswith("nyx-ai-"))]


def _free_room(ai: Dict[str, Any], broker: brokers.Broker) -> float:
    """Dollars the AI may still put to work: its budget minus what it holds and what it has already
    ordered, never more than the cash there is."""
    pending = sum(float(o.get("notional") or 0) or float(o.get("qty") or 0) * float(o.get("limit_price") or 0)
                  for o in _pending_ai_orders(broker) if o.get("side") == "buy")
    room = ai["max_invested"] - guard.ai_invested(broker) - pending
    try:
        cash = float(broker.account().get("cash") or 0)
        room = min(room, cash * 0.99 - pending)  # spread and fees come out of cash too
    except BrokerError:
        pass
    return max(0.0, round(room, 2))


def _reconcile(broker: brokers.Broker, positions: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the AI's record of what it owns true to the broker's.

    An order queued overnight can be rejected at the open (not enough cash after the price
    moved); without this the AI would go on believing it owns shares it never got.
    """
    waiting = {o["symbol"] for o in _pending_ai_orders(broker)}
    fixed: List[Dict[str, Any]] = []

    def change(data: Dict[str, Any]) -> None:
        for symbol, qty in list(data["symbols"].items()):
            held = float((positions.get(symbol) or {}).get("qty") or 0)
            if symbol in waiting:
                continue
            if held <= 1e-9:
                data["symbols"].pop(symbol, None)
                fixed.append({"symbol": symbol, "action": "fix", "why": "Its order never filled — no longer counted as held."})
            elif qty > held + 1e-6:
                data["symbols"][symbol] = held
                fixed.append({"symbol": symbol, "action": "fix", "why": f"Only {held:g} shares actually filled — record corrected."})

    store.update("ai_positions", lambda: {"symbols": {}}, change)
    return fixed


def _sell(summary: Dict[str, Any], symbol: str, qty: float, why: str, kind: str,
          position: Dict[str, Any], signal: Optional[Dict[str, Any]]) -> bool:
    entry: Dict[str, Any] = {"symbol": symbol, "signal": (signal or {}).get("signal", "n/a"),
                             "confidence": (signal or {}).get("confidence", 0), "action": "sell", "qty": qty}
    result = guard.submit(OrderRequest(symbol=symbol, side="sell", qty=round(qty, 6), requested_by="ai", reason=why))
    status = result["status"]
    entry.update(result=status, why=f"{why} {result['reasons'][-1] if status == 'refused' and result.get('reasons') else ''}".strip())
    summary["actions"].append(entry)
    sold = status not in ("refused", "rejected", "canceled", "awaiting_approval")
    if sold:
        entry["lesson"] = lessons.record_exit(symbol, position.get("pl_pct") or 0.0, why, kind)["lesson"]
    return sold


def run_once(force: bool = False) -> Dict[str, Any]:
    """One scan: find new stocks, choose the values (adaptive), sell what should go, buy the best picks spread out.

    Safe to call from a button ("Scan now") or the schedule. Selling comes first: it protects
    what's there and frees money before anything new is bought.
    """
    with _SCAN_LOCK:
        return _scan(force)


def _scan(force: bool) -> Dict[str, Any]:
    rules = guard.settings()
    saved = rules["ai"]
    summary: Dict[str, Any] = {"at": time.time(), "actions": [], "skipped": None, "adaptive": bool(saved.get("adaptive"))}
    if not force and (not saved["enabled"] or rules["halted"]):
        summary["skipped"] = "The AI trader is off." if not saved["enabled"] else "Halted."
        return _remember(summary)
    state = market.session()
    summary["market"] = {"phase": state["phase"], "reason": state["reason"]}
    if run_mode(rules) == "market" and not market.us_market_open() and not force:
        summary["skipped"] = state["reason"]
        return _remember(summary)
    broker = brokers.get(rules["active_broker"])
    try:
        positions = {p["symbol"]: p for p in broker.positions()}
    except BrokerError as error:
        summary["skipped"] = str(error)
        return _remember(summary)
    summary["actions"].extend(_reconcile(broker, positions))
    queued = {o["symbol"] for o in _pending_ai_orders(broker)}
    owned = _owned()
    ai = guard.effective_ai(rules)
    waiting = {a["order"]["symbol"] for a in guard.pending_approvals()}

    # 0) The auto stock adder.
    if ai.get("auto_discover"):
        try:
            found = discovery.discover(rules, ai, held=set(owned), research_fn=researched)
            if found.get("ran"):
                summary["discovery"] = {k: found.get(k) for k in ("added", "removed", "skipped", "considered", "from_news")}
                rules = guard.settings()
        except Exception as error:  # noqa: BLE001 - finding new stocks is extra; trading goes on without it
            summary["discovery"] = {"error": f"{type(error).__name__}: {error}"}

    watch = list(dict.fromkeys([s.upper() for s in rules["watchlist"][:40]] + list(owned)))
    ranked = signals.rank_watchlist(watch, record=True)
    by_symbol = {s["symbol"]: s for s in ranked}

    # 0b) Adaptive mode: choose this scan's values from what it can measure right now.
    if saved.get("adaptive"):
        try:
            summary["adaptive_choice"] = adaptive.refresh(ranked)["values"]
        except (BrokerError, market.MarketDataError) as error:
            summary["adaptive_choice"] = {"error": str(error)}
        ai = guard.effective_ai(rules)

    # 1) Sell: stop-loss, take-profit, or a sell signal — on everything the AI holds.
    for symbol in list(owned):
        position = positions.get(symbol)
        if not position:
            if symbol in queued:
                summary["actions"].append({"symbol": symbol, "action": "hold",
                                           "why": "Bought — the order waits for the market to open to fill."})
            continue
        signal = by_symbol.get(symbol)
        if symbol in waiting:
            summary["actions"].append({"symbol": symbol, "action": "hold", "why": "An order for it is already waiting for your approval."})
            continue
        decision = allocator.review_position(ai, position, signal)
        if decision is None:
            summary["actions"].append({"symbol": symbol, "signal": (signal or {}).get("signal", "n/a"),
                                       "confidence": (signal or {}).get("confidence", 0), "action": "hold",
                                       "why": f"Holding at {position.get('pl_pct') or 0:+.1f}% — no stop, target or sell signal."})
            continue
        _sell(summary, symbol, min(float(decision["qty"]), owned[symbol]), decision["why"], decision["kind"], position, signal)

    owned = _owned()
    cooling = lessons.cooldowns()
    candidates = [s for s in ranked if s["symbol"] not in cooling and s["symbol"] not in waiting]
    room = _free_room(ai, broker)

    # 2) Rotate: budget full, and a clearly better pick is waiting → swap out the weakest holding.
    if ai.get("rotate") and room < max(1.0, allocator.position_cap(ai) * 0.25):
        best = next((s for s in candidates if "error" not in s and s.get("signal") == "buy" and s["symbol"] not in owned
                     and s["confidence"] >= ai["min_confidence"]), None)
        held = [by_symbol[s] for s in owned if s in by_symbol and "error" not in by_symbol[s] and s not in waiting]
        weakest = min(held, key=lambda s: s.get("expected_value", 0), default=None)
        if best and weakest and allocator.should_rotate(weakest, best):
            why = (f"Rotating out of {weakest['symbol']} (expected value {weakest.get('expected_value', 0):+.2f}) into "
                   f"{best['symbol']} ({best['expected_value']:+.2f}) — a clearly better use of the money.")
            if _sell(summary, weakest["symbol"], owned[weakest["symbol"]], why, "rotate", positions.get(weakest["symbol"], {}), weakest):
                owned = _owned()
                room = _free_room(ai, broker)

    # 3) Buy: best-ranked first, sized so the money is spread across several stocks. When a
    #    pick is turned down (red flag, or the rules refuse it) its slot and money go to the
    #    next-best pick in the same scan instead of sitting idle until the next one.
    excluded: set = set()
    for _ in range(len(candidates) + 1):
        pool = [s for s in candidates if s["symbol"] not in excluded]
        replan = False
        for plan in allocator.plan_buys(ai, pool, owned, room):
            signal = plan["signal"]
            if plan["notional"] < 1:
                continue
            entry: Dict[str, Any] = {"symbol": signal["symbol"], "signal": signal["signal"], "confidence": signal["confidence"]}
            notes = researched(signal["symbol"], signal)
            entry["research"] = notes
            excluded.add(signal["symbol"])
            if notes.get("avoid"):
                entry.update(action="avoid", why=f"Research found a red flag: {notes.get('thesis', '')[:200]}")
                summary["actions"].append(entry)
                replan = True
                break
            reason = f"{plan['why']} {' '.join(signal['reasons'][:2])} {notes.get('thesis', '')}".strip()
            result = guard.submit(OrderRequest(symbol=signal["symbol"], side="buy", notional=plan["notional"], requested_by="ai", reason=reason))
            entry.update(action="buy", notional=plan["notional"], result=result["status"],
                         why=plan["why"] if result["status"] != "refused" else result["reasons"][-1])
            summary["actions"].append(entry)
            if result["status"] in ("refused", "rejected", "canceled"):
                replan = True
                break
            owned = _owned()
            room = _free_room(ai, broker)
            replan = True  # re-split what's left across the remaining slots
            break
        if not replan:
            break
    for plan in allocator.plan_buys(ai, [s for s in candidates if s["symbol"] not in excluded], owned, room):
        summary["actions"].append({"symbol": plan["symbol"], "signal": "buy", "confidence": plan["signal"]["confidence"],
                                   "action": "watch", "why": plan["why"] if plan["notional"] < 1 else
                                   "Budget and open slots are already spoken for by better-ranked picks this scan."})

    # 4) Everything else it looked at, so the log shows every symbol and why nothing happened.
    seen = {a["symbol"] for a in summary["actions"]}
    for signal in ranked:
        if signal["symbol"] in seen:
            continue
        if "error" in signal:
            summary["actions"].append({"symbol": signal["symbol"], "action": "skip", "why": signal["error"]})
        elif signal["symbol"] in cooling and signal.get("signal") == "buy":
            summary["actions"].append({"symbol": signal["symbol"], "signal": "buy", "confidence": signal["confidence"],
                                       "action": "cooldown", "why": cooling[signal["symbol"]]["why"]})
        else:
            summary["actions"].append({"symbol": signal["symbol"], "signal": signal.get("signal", "hold"),
                                       "confidence": signal.get("confidence", 0), "action": "watch",
                                       "why": "Signal not strong enough." if signal.get("confidence", 0) < ai["min_confidence"]
                                       else "Nothing to do for this signal."})
    return _remember(summary)


def _remember(summary: Dict[str, Any]) -> Dict[str, Any]:
    def change(data: Dict[str, Any]) -> None:
        data["runs"] = (data["runs"] + [summary])[-50:]

    store.update("autopilot", lambda: {"runs": []}, change)
    return summary


def runs(limit: int = 10) -> List[Dict[str, Any]]:
    return list(reversed(store.read("autopilot", lambda: {"runs": []})["runs"][-limit:]))


def _plan_next(rules: Dict[str, Any], now: Optional[float] = None) -> Dict[str, Any]:
    """Whether to scan now, and how long to wait afterwards.

    Pure, so the schedule can be tested without threads or a clock: returns
    ``{"scan": bool, "sleep": seconds, "resting": words}``.
    """
    now = now or time.time()
    ai = rules["ai"]
    mode = run_mode(rules)
    # Adaptive mode picks its own pace (every 5 minutes while the market is open).
    every = max(60.0, float(guard.effective_ai(rules).get("scan_minutes") or 30) * 60)
    state = market.session()
    is_open = market.us_market_open()

    if mode == "until" and ai.get("run_until") and now >= float(ai["run_until"]):
        return {"scan": False, "sleep": 0.0, "resting": "The time you set has passed.", "finished": True}

    # The owner's on/off hours: outside them the trader stays switched on but rests.
    schedule = adaptive.schedule_state(ai.get("schedule"), now)
    if schedule["active"] and not schedule["inside"]:
        wait = max(30.0, float(schedule["next_start"] or now + _MAX_SLEEP) - now)
        return {"scan": False, "sleep": min(wait, _MAX_SLEEP), "resting": schedule["words"]}

    if mode == "market" and not is_open:
        # Sleep to the opening bell (in capped chunks) instead of waking every
        # half hour to find the market shut. This is what makes "it starts by
        # itself when the market opens" true.
        wait = max(30.0, float(state["next_open"]) - now)
        opens_in = _words_for(wait)
        return {"scan": False, "sleep": min(wait, _MAX_SLEEP),
                "resting": f"{state['reason']} Next scan when the market opens, in {opens_in}."}

    sleep = every
    resting = ""
    if not is_open:
        sleep = max(every * _CLOSED_SLOWDOWN, _CLOSED_MIN_MINUTES * 60)
        resting = f"{state['reason']} Watching anyway (24/7 mode), more slowly."
    if mode == "until" and ai.get("run_until"):
        sleep = min(sleep, max(30.0, float(ai["run_until"]) - now))
    return {"scan": True, "sleep": min(sleep, _MAX_SLEEP), "resting": resting}


def _words_for(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes / 60
    if hours < 24:
        return f"{hours:.0f} h {minutes % 60} min" if minutes % 60 else f"{hours:.0f} h"
    return f"{hours / 24:.0f} days"


def _loop() -> None:
    _STATE.update(started_at=time.time(), stopped_reason="", scans=0)
    while True:
        rules = guard.settings()
        if not rules["ai"]["enabled"] or rules["halted"]:
            _STATE.update(next_scan_at=0.0, resting="", stopped_reason=_STATE.get("stopped_reason") or
                          ("Halted." if rules["halted"] else "The AI trader is off."))
            return
        plan = _plan_next(rules)
        if plan.get("finished"):
            stop("The time you set for the AI trader has passed.")
            return
        if plan["scan"]:
            try:
                run_once()
            except Exception as error:  # noqa: BLE001 - one bad scan must not end the schedule
                guard.audit("autopilot_error", "ai", {"error": f"{type(error).__name__}: {error}"})
            _STATE.update(last_scan_at=time.time(), scans=int(_STATE.get("scans") or 0) + 1)
        _STATE.update(next_scan_at=time.time() + plan["sleep"], resting=plan["resting"])
        _WAKE.wait(timeout=plan["sleep"])
        _WAKE.clear()


def ensure_running() -> bool:
    """Start the schedule if the owner switched the AI trader on; no-op otherwise.

    Called when the engine starts, so a run mode survives a restart without the
    owner pressing anything.
    """
    global _THREAD
    rules = guard.settings()
    if not rules["ai"]["enabled"] or rules["halted"]:
        return False
    with _LOCK:
        if _THREAD is None or not _THREAD.is_alive():
            _THREAD = threading.Thread(target=_loop, name="nyx-trading-autopilot", daemon=True)
            _THREAD.start()
    return True


def _check_mode(mode: str, until_ts: Optional[float]) -> None:
    if mode not in RUN_MODES:
        raise BrokerError(f"Run mode must be one of: {', '.join(RUN_MODES)}.")
    if mode == "until":
        if not until_ts or float(until_ts) <= time.time():
            raise BrokerError("Say when it should stop — a time in the future.")
        if float(until_ts) > time.time() + 90 * 86400:
            raise BrokerError("Pick a stopping time within the next 90 days.")


def set_adaptive(on: bool, *, budget: Optional[float] = None, starting_cash: Optional[float] = None,
                 mode: Optional[str] = None, until_ts: Optional[float] = None, schedule: Optional[Dict[str, Any]] = None,
                 pins: Optional[Dict[str, Any]] = None, actor: str = "owner") -> Dict[str, Any]:
    """The one button. On: hands-off — the AI chooses every value the owner doesn't give, each scan.

    ``budget`` (dollars the AI may have invested) and ``pins`` are the only values it will
    not choose itself; everything left out is adaptive. Turning on resumes a halt and starts
    the schedule (default: around the clock until stopped). Off stops the trader and leaves
    the owner's own rules exactly as they were.
    """
    if not on:
        guard.save_settings({"ai": {"adaptive": False}}, actor=actor)
        guard.audit("adaptive_off", actor, {})
        stop("Adaptive mode is off, so the trader stopped. Your own rules are unchanged.")
        return {"adaptive": adaptive.status(), "run": run_status()}
    mode = mode or "always"
    _check_mode(mode, until_ts)
    rules = guard.settings()
    if starting_cash:
        if rules["active_broker"] != "paper":
            raise BrokerError("A starting amount only applies to the practice account — your real account's money is what it is.")
        brokers.get("paper").reset(max(1.0, min(10_000_000.0, float(starting_cash))))
        store.write("ai_positions", {"symbols": {}})
        guard.audit("paper_reset", actor, {"cash": starting_cash, "via": "adaptive"})
    new_pins = {k: v for k, v in (pins or {}).items() if v not in (None, "", 0)}
    if budget:
        new_pins["max_invested"] = float(budget)
    changes: Dict[str, Any] = {"adaptive": True, "enabled": True, "adaptive_pins": new_pins, "run_mode": mode,
                               "run_until": float(until_ts) if mode == "until" else None}
    if schedule is not None:
        changes["schedule"] = schedule
    rules = guard.save_settings({"ai": changes}, actor=actor)
    if rules["halted"]:
        guard.resume()
    try:
        adaptive.refresh([])
    except (BrokerError, market.MarketDataError):
        pass  # the first scan chooses instead
    _STATE["stopped_reason"] = ""
    ensure_running()
    wake()
    guard.audit("adaptive_on", actor, {"pins": new_pins, "mode": mode, "starting_cash": starting_cash})
    return {"adaptive": adaptive.status(), "run": run_status()}


def set_run_mode(mode: str, until_ts: Optional[float] = None) -> Dict[str, Any]:
    """Pick when the AI trader works. Switching to a mode also starts it."""
    _check_mode(mode, until_ts)
    changes: Dict[str, Any] = {"run_mode": mode, "run_until": float(until_ts) if mode == "until" else None,
                               "enabled": True}
    rules = guard.save_settings({"ai": changes})
    if rules["halted"]:
        guard.resume()
    _STATE["stopped_reason"] = ""
    ensure_running()
    wake()
    guard.audit("autopilot_mode", "owner", {"mode": mode, "until": changes["run_until"]})
    return run_status()


def stop(reason: str = "") -> Dict[str, Any]:
    """Stop the schedule. Positions stay; only the AI's own working stops."""
    guard.save_settings({"ai": {"enabled": False}})
    _STATE.update(stopped_reason=reason or "You stopped the AI trader.", next_scan_at=0.0, resting="")
    wake()
    guard.audit("autopilot_stop", "owner", {"reason": reason})
    return run_status()


def wake() -> None:
    _WAKE.set()


def run_status() -> Dict[str, Any]:
    """The schedule in words and numbers: mode, whether it is working, and what happens next."""
    rules = guard.settings()
    ai = rules["ai"]
    mode = run_mode(rules)
    state = market.session()
    running = bool(_THREAD and _THREAD.is_alive()) and ai["enabled"] and not rules["halted"]
    schedule = adaptive.schedule_state(ai.get("schedule"))
    if not ai["enabled"]:
        summary = _STATE.get("stopped_reason") or "Off — the AI trader is not working."
    elif rules["halted"]:
        summary = "Halted — nothing until you resume."
    elif schedule["active"] and not schedule["inside"]:
        summary = schedule["words"]
    elif mode == "market" and not market.us_market_open():
        summary = f"Waiting for the opening bell ({_words_for(max(0.0, state['next_open'] - time.time()))} away)."
    elif mode == "until" and ai.get("run_until"):
        summary = f"Working around the clock until {time.strftime('%a %d %b %H:%M', time.localtime(float(ai['run_until'])))}."
    elif mode == "always":
        summary = "Working around the clock until you stop it."
    else:
        summary = "Working the US session."
    return {
        "mode": mode, "until": ai.get("run_until"), "enabled": bool(ai["enabled"]), "halted": bool(rules["halted"]),
        "running": running, "summary": summary, "session": state, "scan_minutes": ai.get("scan_minutes"),
        "last_scan_at": _STATE.get("last_scan_at") or 0.0, "next_scan_at": _STATE.get("next_scan_at") or 0.0,
        "resting": _STATE.get("resting") or "", "scans_this_run": int(_STATE.get("scans") or 0),
        "started_at": _STATE.get("started_at") or 0.0,
        "adaptive": bool(ai.get("adaptive")), "schedule": schedule,
    }


def status() -> Dict[str, Any]:
    return {"running": bool(_THREAD and _THREAD.is_alive()), "last": (runs(1) or [None])[0], "today": guard.ai_day(),
            "run": run_status()}
