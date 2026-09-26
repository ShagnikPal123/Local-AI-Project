"""HTTP routes for the finance lab (Project Null N104–N110).

Owner-only and blocked on a hosted build, exactly like `/api/trading`: this
decides what to do with the owner's money, even though it never places an order
itself.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> None:
    import server

    server.require_local_owner(request, request.headers.get("authorization"))


@router.get("/api/finance-lab")
def overview(request: Request) -> Dict[str, Any]:
    """Everything the panel draws: the pot, the pipeline, what it has learned."""
    _owner(request)
    from finance_lab import capital_guard, focus_mode, memory, model_policy, node_map, strategies

    return {
        "pot": capital_guard.pot(),
        "settings": capital_guard.settings(),
        "nodes": node_map.map_now(),
        "memory": memory.table()[:24],
        "trained_at": memory.trained_at(),
        "strategies": [{"name": name, **{k: v for k, v in entry.items() if k != "fn"}}
                       for name, entry in strategies.STRATEGIES.items()],
        "focus": focus_mode.state(),
        "models": model_policy.advice(),
    }


class MoneyBody(BaseModel):
    allocated: Optional[float] = None
    loss_stop_pct: Optional[float] = None
    max_position_pct: Optional[float] = None
    mode: Optional[str] = None


@router.put("/api/finance-lab/money")
def set_money(body: MoneyBody, request: Request) -> Dict[str, Any]:
    """How much the AI may work with, and the brakes on it."""
    _owner(request)
    from finance_lab import capital_guard

    changes = body.model_dump(exclude_none=True)
    if changes.get("mode") not in (None, "practice", "real"):
        raise HTTPException(status_code=400, detail="Mode is practice or real.")
    capital_guard.update_settings(**changes)
    return {"pot": capital_guard.pot(), "settings": capital_guard.settings()}


@router.post("/api/finance-lab/reset-stop")
def reset_stop(request: Request) -> Dict[str, Any]:
    _owner(request)
    from finance_lab import capital_guard

    return {"pot": capital_guard.reset_stop()}


class ForecastBody(BaseModel):
    symbol: str
    horizon: int = 20
    allow_web: bool = False


@router.post("/api/finance-lab/forecast")
def forecast(body: ForecastBody, request: Request) -> Dict[str, Any]:
    """A price cone worked out on this PC. No key, no quota."""
    _owner(request)
    from finance_lab import forecast as engine
    from finance_lab import node_map, strategies
    from trading import market

    symbol = body.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="Which symbol?")
    try:
        history = market.history(symbol, "1y")
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"No price history for {symbol}: {error}") from error
    node_map.light("market", symbol)
    row = engine.predict(history, max(5, min(120, body.horizon)))
    if body.allow_web:
        row = engine.with_search(symbol, row)
    return {"symbol": symbol, "forecast": row, "signals": strategies.read_all(history)[:6],
            "history": [{"date": r.get("date"), "close": r.get("close")} for r in history[-180:]]}


class TrainBody(BaseModel):
    symbols: List[str] = []
    range: str = "2y"
    background: bool = True


@router.post("/api/finance-lab/train")
def train(body: TrainBody, request: Request) -> Dict[str, Any]:
    """Practice on history, then remember what worked where."""
    _owner(request)
    from finance_lab import simulator

    symbols = [s.strip().upper() for s in body.symbols if s.strip()][:12]
    if not symbols:
        try:
            from trading import store

            symbols = list(store.read("settings", lambda: {"watchlist": []}).get("watchlist") or [])[:6]
        except Exception:  # noqa: BLE001
            symbols = []
    if not symbols:
        raise HTTPException(status_code=400, detail="Give it some symbols to practise on.")
    if body.background:
        return simulator.train_in_background(symbols, body.range)
    return simulator.train(symbols, range_=body.range)


class AdviseBody(BaseModel):
    symbol: str
    allow_web: bool = False


@router.post("/api/finance-lab/advise")
def advise(body: AdviseBody, request: Request) -> Dict[str, Any]:
    """What it would do with this symbol now, from what it practised."""
    _owner(request)
    from finance_lab import simulator

    return simulator.advise(body.symbol.strip().upper(), allow_web=body.allow_web)


@router.get("/api/finance-lab/backtest")
def backtest(symbol: str, request: Request) -> Dict[str, Any]:
    _owner(request)
    from finance_lab import strategies
    from trading import market

    try:
        history = market.history(symbol.strip().upper(), "2y")
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"symbol": symbol.upper(), "results": strategies.backtest_all(history)}


class FocusBody(BaseModel):
    action: str = "warning"          # warning | enter | leave
    reason: str = ""


@router.post("/api/finance-lab/focus")
def focus(body: FocusBody, request: Request) -> Dict[str, Any]:
    """The high-finance switch: the warning first, then everything else stops."""
    _owner(request)
    from finance_lab import focus_mode

    if body.action == "enter":
        return focus_mode.enter(body.reason)
    if body.action == "leave":
        return focus_mode.leave()
    return focus_mode.warning()


@router.get("/api/finance-lab/nodes")
def nodes(request: Request) -> Dict[str, Any]:
    """The pipeline picture, polled while the owner watches it light up."""
    _owner(request)
    from finance_lab import node_map

    return node_map.map_now()
