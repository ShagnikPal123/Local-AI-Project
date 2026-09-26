"""The auto stock adder: finds stocks that are doing well or look set to, researches them, adds them.

The owner: "an auto stock adder to make sure it researches and adds stocks that do well
or are predicted to do well".

Where candidates come from:

* a built-in universe of ~90 liquid US stocks and sector ETFs, looked at a slice at a
  time so every run sees different names without hammering the price feed;
* today's news — "top gainers", "analyst upgrades", "most active" searches — with the
  tickers pulled out of the results (only real, priced symbols survive the scoring).

Each candidate is scored with the same signals the trader uses (``rank_watchlist``);
buys above the confidence bar, priced at $2 or more, not on a loss cool-down, are the
ones considered. The best few get a news + model check (``research_fn``) and are added
if nothing is flagged. Symbols the AI added are dropped again once they turn bad and it
doesn't hold them. **It never removes a symbol the owner put on the watchlist.**
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional, Set

from trading import lessons, signals, store

UNIVERSE = [
    # Broad market and sector ETFs
    "SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "SMH", "XLC", "XLB",
    # Technology and semiconductors
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX", "CRM", "ORCL", "ADBE", "INTC",
    "QCOM", "TXN", "MU", "PLTR", "SHOP", "UBER", "ABNB", "PYPL", "COIN", "CRWD", "PANW", "NOW", "ANET", "TSM",
    "ASML", "ARM", "AMAT", "LRCX", "SNOW", "DDOG", "NET",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "SCHW", "BLK",
    # Energy, industrials, materials
    "XOM", "CVX", "COP", "CAT", "DE", "BA", "GE", "HON", "LMT", "RTX", "UPS", "FCX",
    # Health care
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ISRG",
    # Consumer
    "HD", "LOW", "COST", "WMT", "TGT", "NKE", "MCD", "SBUX", "KO", "PEP", "PG", "DIS",
    # Telecom and utilities
    "T", "VZ", "TMUS", "NEE", "DUK",
]

WEB_QUERIES = ("top stock gainers today", "stocks analysts upgraded this week", "most active stocks today")

#: Capitalised words that look like tickers in news text but aren't.
_NOT_TICKERS = {
    "A", "I", "AI", "CEO", "CFO", "ETF", "ETFS", "USA", "US", "IPO", "SEC", "GDP", "EPS", "USD", "NYSE", "NASDAQ",
    "AMEX", "FED", "FOMC", "CPI", "PPI", "EV", "EVS", "Q1", "Q2", "Q3", "Q4", "YOY", "ATH", "PM", "AM", "ET", "PT",
    "UK", "EU", "OK", "TV", "API", "IT", "PE", "YTD", "DOW", "SP", "NEW", "TOP", "BUY", "SELL", "HOLD", "NEWS",
}
_TICKER_PATTERNS = (
    re.compile(r"\((?:NASDAQ|NYSE|NYSEARCA|AMEX|NYSEAMERICAN)\s*:\s*([A-Z]{1,5})\)"),
    re.compile(r"\b(?:NASDAQ|NYSE|NYSEARCA|AMEX)\s*:\s*([A-Z]{1,5})\b"),
    re.compile(r"\(([A-Z]{2,5})\)"),
    re.compile(r"\$([A-Z]{1,5})\b"),
)

SLICE = 20
MIN_PRICE = 2.0
KEEP_ADDED_DAYS = 2.0


def _state() -> Dict[str, Any]:
    return store.read("discovery", lambda: {"added": {}, "cursor": 0, "last_run": 0.0, "runs": []})


def tickers_in(text: str) -> List[str]:
    """Ticker-looking symbols in news text, most-mentioned first. Pure; unit tested."""
    counts: Dict[str, int] = {}
    for pattern in _TICKER_PATTERNS:
        for match in pattern.findall(text or ""):
            symbol = match.upper()
            if symbol not in _NOT_TICKERS:
                counts[symbol] = counts.get(symbol, 0) + 1
    return [s for s, _ in sorted(counts.items(), key=lambda item: -item[1])]


def _from_web(limit: int = 15) -> List[str]:
    try:
        from tools import TOOL_REGISTRY
    except Exception:  # noqa: BLE001 - no tool registry (tests, CLI): the universe is enough
        return []
    found: List[str] = []
    for query in WEB_QUERIES:
        try:
            text = str(TOOL_REGISTRY.call_tool("search_web", query=query, engine="all", freshness="day"))
        except Exception:  # noqa: BLE001 - one failed search shouldn't stop the others
            continue
        for symbol in tickers_in(text):
            if symbol not in found:
                found.append(symbol)
    return found[:limit]


def _universe_slice(cursor: int, exclude: Set[str]) -> List[str]:
    pool = [s for s in UNIVERSE if s not in exclude]
    if not pool:
        return []
    start = cursor % len(pool)
    return (pool[start:] + pool[:start])[:SLICE]


def due(ai: Dict[str, Any], now: Optional[float] = None) -> bool:
    now = now or time.time()
    return now - float(_state().get("last_run") or 0) >= float(ai.get("discover_minutes") or 90) * 60


def discover(rules: Dict[str, Any], ai: Dict[str, Any], held: Set[str], force: bool = False,
             research_fn: Optional[Callable[[str, Dict[str, Any]], Dict[str, Any]]] = None, web: bool = True,
             now: Optional[float] = None) -> Dict[str, Any]:
    """One discovery pass: prune what it added that went bad, then add the best new candidates."""
    from trading import guard

    now = now or time.time()
    if not force and not due(ai, now):
        return {"ran": False}
    state = _state()
    watch = list(rules["watchlist"])
    added: Dict[str, Any] = dict(state.get("added") or {})
    added = {s: info for s, info in added.items() if s in watch}  # the owner may have removed some by hand
    limit = int(ai.get("watchlist_max") or 25)
    removed: List[Dict[str, str]] = []

    # 1) Drop symbols it added that have turned bad (never the owner's, never ones it holds).
    stale = [s for s, info in added.items() if s not in held and now - float(info.get("at") or 0) > KEEP_ADDED_DAYS * 86400]
    if stale:
        for signal in signals.rank_watchlist(stale, record=False):
            if "error" in signal or signal.get("signal") == "sell" or signal.get("expected_value", 0) <= 0:
                why = signal.get("error") or f"signal now {signal.get('signal')} — no longer worth watching"
                watch.remove(signal["symbol"])
                added.pop(signal["symbol"], None)
                removed.append({"symbol": signal["symbol"], "why": why})

    # 2) Score new candidates.
    exclude = set(watch)
    pool = _universe_slice(int(state.get("cursor") or 0), exclude)
    web_symbols: List[str] = []
    if web and guard.note_research():
        web_symbols = [s for s in _from_web() if s not in exclude and s not in pool]
    pool += web_symbols
    ranked = signals.rank_watchlist(pool, record=False) if pool else []
    cooling = lessons.cooldowns(now)
    good = [s for s in ranked if "error" not in s and s.get("signal") == "buy" and s["confidence"] >= ai["min_confidence"]
            and s.get("expected_value", 0) > 0 and float((s.get("indicators") or {}).get("price") or 0) >= MIN_PRICE
            and s["symbol"] not in cooling]
    good.sort(key=lambda s: (s["expected_value"], (s.get("indicators") or {}).get("return_20d") or 0), reverse=True)

    # 3) Make room if the list is full: the weakest symbol the AI itself added goes first.
    max_add = int(ai.get("discover_max_add") or 0)
    added_now: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    for signal in good:
        if len(added_now) >= max_add:
            break
        if len(watch) >= limit:
            replaceable = [s for s in added if s not in held and s in watch]
            if not replaceable:
                skipped.append({"symbol": signal["symbol"], "why": "Watchlist is full of your own picks and its holdings."})
                break
            weakest = min(replaceable, key=lambda s: float(added[s].get("ev") or 0))
            if float(added[weakest].get("ev") or 0) >= signal["expected_value"]:
                break
            watch.remove(weakest)
            added.pop(weakest, None)
            removed.append({"symbol": weakest, "why": f"made room for {signal['symbol']}, a stronger pick"})
        notes: Dict[str, Any] = {}
        if research_fn is not None:  # the function spends (and caches) the research budget itself
            notes = research_fn(signal["symbol"], signal)
            if notes.get("avoid"):
                skipped.append({"symbol": signal["symbol"], "why": f"research flagged it: {notes.get('thesis', '')[:160]}"})
                continue
        source = "news" if signal["symbol"] in web_symbols else "universe"
        why = (f"{signal['confidence']:.0%} buy signal, 20-day {((signal.get('indicators') or {}).get('return_20d') or 0):+.1f}%, "
               f"found in {'today’s market news' if source == 'news' else 'its stock universe'}. " + " ".join(signal.get("reasons", [])[:2]))
        watch.append(signal["symbol"])
        added[signal["symbol"]] = {"at": now, "why": why.strip(), "ev": signal["expected_value"], "source": source,
                                   "thesis": (notes.get("thesis") or "")[:300]}
        added_now.append({"symbol": signal["symbol"], "why": why.strip(), "source": source})

    if watch != list(rules["watchlist"]):
        guard.save_settings({"watchlist": watch}, actor="ai")
    summary = {"ran": True, "at": now, "considered": len(pool), "from_news": len(web_symbols), "candidates": len(good),
               "added": added_now, "removed": removed, "skipped": skipped}

    def change(data: Dict[str, Any]) -> None:
        data["added"] = added
        data["cursor"] = int(data.get("cursor") or 0) + SLICE
        data["last_run"] = now
        data["runs"] = (list(data.get("runs") or []) + [summary])[-20:]

    store.update("discovery", lambda: {"added": {}, "cursor": 0, "last_run": 0.0, "runs": []}, change)
    return summary


def status() -> Dict[str, Any]:
    state = _state()
    runs = list(reversed(state.get("runs") or []))
    return {"added": state.get("added") or {}, "last_run": state.get("last_run") or 0.0, "last": runs[0] if runs else None,
            "runs": runs[:5], "universe_size": len(UNIVERSE)}
