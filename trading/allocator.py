"""Turns ranked signals into sized orders: diversification, position caps, stop-loss/take-profit.

The owner's rule in plain words: never dump the whole account into one pick. Money is split
across the top few ranked opportunities instead of the single loudest one, capped per symbol as a
share of the AI's budget, and a symbol the AI has been wrong about before gets a smaller share
(``signals.symbol_reliability``) — a small mistake shrinks that symbol's future sizing instead of
being repeated at full size next scan.

Selling is just as active as buying here: a position can be cut for capital protection (stop
loss) or closed for a win (take profit) independently of the indicator ever flipping all the way
to "sell" — waiting for that can mean giving back most of a gain, or riding a loser too long.

Pure functions only (no I/O, no store access) so they're easy to unit test and safe to call from
any thread the caller happens to be on.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def position_cap(ai: Dict[str, Any]) -> float:
    """Dollar ceiling for one symbol: the smaller of the flat per-trade limit and a share of the whole AI budget.

    ``max_position_pct`` (default 30%) is what actually prevents concentration on a small account:
    a $500 flat per-trade limit means nothing on a $50 account since the cash check catches it
    anyway, but without this cap a single high-confidence signal could still claim the AI's whole
    ``max_invested`` budget the moment there is room for it.
    """
    return round(min(ai["max_per_trade"], ai["max_invested"] * ai.get("max_position_pct", 0.3)), 2)


def plan_buys(ai: Dict[str, Any], ranked: List[Dict[str, Any]], owned: Dict[str, float], room: float) -> List[Dict[str, Any]]:
    """Which new positions to open and with how much — best-ranked opportunities first, spread out.

    ``ranked`` is ``signals.rank_watchlist()``'s output (best expected value first). ``room`` is
    dollars still free under the AI's total budget. Returns one entry per buy-signal candidate,
    including the ones it declines, each with a plain-English ``why`` so every decision the
    autopilot makes is visible in its log — not just the trades it placed.
    """
    cap = position_cap(ai)
    target = max(1, int(ai.get("target_positions", 5)))
    slots_open = max(0, target - len(owned))
    plans: List[Dict[str, Any]] = []
    candidates = [s for s in ranked if s.get("signal") == "buy" and s["symbol"] not in owned and "error" not in s
                  and s["confidence"] >= ai["min_confidence"]]
    remaining = room
    for rank, signal in enumerate(candidates):
        if slots_open == 0:
            plans.append({"symbol": signal["symbol"], "signal": signal, "notional": 0.0,
                         "why": f"Already holding the target of {target} positions — diversification limit, not a budget limit."})
            continue
        if rank >= slots_open or remaining < 1:
            plans.append({"symbol": signal["symbol"], "signal": signal, "notional": 0.0,
                         "why": "Budget and open slots are already spoken for by better-ranked picks this scan."})
            continue
        # Split what's left across the remaining open slots so the top pick can't eat the whole
        # budget by itself, then scale that even share up or down by confidence and reliability.
        share = remaining / (slots_open - rank)
        reliability = signal["reliability"]["multiplier"]
        notional = round(min(cap, share) * min(1.15, max(0.4, 0.55 + signal["confidence"] * reliability * 0.5)), 2)
        if notional < 1:
            plans.append({"symbol": signal["symbol"], "signal": signal, "notional": 0.0, "why": "Too little left to open a meaningful position."})
            continue
        track = f", track record {signal['reliability']['hit_rate']:.0%} ({signal['reliability']['graded']} graded)" \
            if signal["reliability"]["hit_rate"] is not None else ", no track record yet"
        plans.append({"symbol": signal["symbol"], "signal": signal, "notional": notional,
                     "why": f"Ranked #{rank + 1} of {len(candidates)}, {signal['confidence']:.0%} confidence{track} "
                            f"— sized ${notional:,.2f} (cap ${cap:,.2f} per symbol, target {target} positions)."})
        remaining -= notional
    return plans


def review_position(ai: Dict[str, Any], position: Dict[str, Any], signal: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Stop-loss / take-profit / signal-reversal for one held position — the active half of selling.

    Checked every scan for every AI-opened position regardless of whether it's still on the
    watchlist, so a stop-loss still fires even if the symbol was dropped from the list. Returns
    ``None`` when there's nothing to do.
    """
    pl_pct = position.get("pl_pct") or 0.0
    stop = abs(ai.get("stop_loss_pct", 8.0))
    target = abs(ai.get("take_profit_pct", 20.0))
    if pl_pct <= -stop:
        return {"qty": position["qty"], "kind": "stop", "why": f"Stop loss: down {pl_pct:.1f}% (limit -{stop:.0f}%) — protecting what's left."}
    if pl_pct >= target:
        return {"qty": position["qty"], "kind": "target", "why": f"Take profit: up {pl_pct:.1f}% (target +{target:.0f}%) — locking in the gain."}
    if signal and "error" not in signal and signal.get("signal") == "sell" and signal.get("confidence", 0) >= ai["min_confidence"]:
        reasons = " ".join((signal.get("reasons") or [])[:2])
        return {"qty": position["qty"], "kind": "signal", "why": f"Signal turned sell ({signal['confidence']:.0%}): {reasons}".strip()}
    return None


def should_rotate(held_signal: Optional[Dict[str, Any]], best_new: Optional[Dict[str, Any]], edge: float = 0.25) -> bool:
    """When the budget is full, is a fresh top-ranked pick clearly enough better to justify swapping?

    Used by the autopilot when ``rotate`` is on (always in adaptive mode). A rotation is a sell
    plus a buy — two trades' worth of spread and slippage — so ``edge`` is deliberately
    conservative: a small expected-value gap is not worth the churn.
    """
    if not held_signal or not best_new or "error" in best_new or "error" in held_signal:
        return False
    held_ev = held_signal.get("expected_value", held_signal.get("score", 0) * held_signal.get("confidence", 0))
    new_ev = best_new.get("expected_value", 0)
    return new_ev > 0 and new_ev > held_ev + edge
