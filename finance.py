"""Finance advisor support: permanent financial knowledge, live market data, and mode context.

The finance tab/mode combines three things:
1. Permanent financial literacy (finance_knowledge.md) — always available, so the
   assistant knows how to reason about valuation, indicators, risk, and when to
   invest or sell.
2. Live market data through the FinanceConnector (keyless Stooq/Yahoo feeds).
3. Personal permanent memory — any important memories the user saved (portfolio,
   goals, risk tolerance) are pulled in when giving advice, so guidance is
   grounded in the user's own situation.

All output is educational and includes a risk disclaimer; it is never
personalized financial advice without the user's own context.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from knowledge import GeneralKnowledge

_FINANCE_KNOWLEDGE_FILE = "finance_knowledge.md"
_DISCLAIMER = (
    "Educational information only — not personalized financial advice. "
    "Markets involve risk, including loss of principal. Do your own research "
    "and consult a licensed financial professional before investing."
)

_knowledge: Optional[GeneralKnowledge] = None


def get_finance_knowledge(path: Optional[str] = None) -> GeneralKnowledge:
    """Get or create the singleton permanent financial knowledge store."""
    global _knowledge
    if _knowledge is None:
        _knowledge = GeneralKnowledge(path=path or _FINANCE_KNOWLEDGE_FILE)
    return _knowledge


def finance_system_prompt() -> str:
    """System-guidance block for the finance advisor mode."""
    knowledge = get_finance_knowledge()
    sections = ", ".join(knowledge.sections) if knowledge.sections else "financial literacy"
    return (
        "[Finance Advisor Mode]\n"
        f"You are acting as a financial literacy advisor. Your permanent financial "
        f"knowledge covers: {sections}.\n"
        "1. Ground answers in that knowledge — consult search_finance_knowledge and "
        "fetch live data with stock_quote / stock_history before answering market questions.\n"
        "2. Reason about valuation, indicators, risk, and strategy; explain the 'why' behind any advice.\n"
        "3. Consider any personal context the user saved (portfolio, goals, risk tolerance).\n"
        "4. Be balanced: mention risks and both sides. Never guarantee returns.\n"
        f"5. End market-sensitive advice with: {_DISCLAIMER}"
    )


def advisor_context(question: str, memory=None, limit: int = 3) -> str:
    """Build grounded context for a finance question: knowledge + personal memory.

    Args:
        question: The user's finance question.
        memory: Optional MemoryStore to pull personal permanent memories from.
        limit: Max knowledge chunks to include.
    """
    parts: List[str] = []

    knowledge = get_finance_knowledge()
    chunks = knowledge.search(question, limit=limit)
    if chunks:
        parts.append("Relevant financial knowledge:")
        for chunk in chunks:
            parts.append(f"[{chunk['section']}]\n{chunk['text']}")

    if memory is not None:
        try:
            important = memory.get_important()
        except Exception:  # pragma: no cover - defensive
            important = []
        personal = [
            item for item in important
            if any(
                token in f"{item.get('topic', '')} {item.get('content', '')}".lower()
                for token in (
                    "portfolio", "stock", "invest", "share", "holding", "budget",
                    "retirement", "risk", "dividend", "etf", "fund", "crypto", "money",
                )
            )
        ]
        if personal:
            parts.append("User's saved financial context:")
            for item in personal[-5:]:
                parts.append(f"- {item.get('topic')}: {item.get('content')}")

    return "\n\n".join(parts)


def quote_text(symbols: str) -> str:
    """Human-readable live quotes via the finance connector."""
    from connectors import CONNECTOR_REGISTRY

    result = CONNECTOR_REGISTRY.execute("finance", "quote", symbols=symbols)
    if not result.get("success"):
        return f"Error: {result.get('error', 'unknown')}"
    lines = [f"Live quotes ({result.get('source', 'unknown')}):"]
    for quote in result.get("quotes", []):
        close = quote.get("close")
        change = ""
        if close is not None and quote.get("open"):
            change = f" (vs open {quote['open']:g})"
        lines.append(
            f"  {quote.get('symbol', '?').upper()}: {close:g}{change} — {quote.get('date', '')}"
        )
    return "\n".join(lines)


def history_text(symbol: str, range: str = "3mo") -> str:
    """Human-readable price history via the finance connector."""
    from connectors import CONNECTOR_REGISTRY

    result = CONNECTOR_REGISTRY.execute("finance", "history", symbol=symbol, range=range)
    if not result.get("success"):
        return f"Error: {result.get('error', 'unknown')}"
    rows = result.get("rows", [])
    if not rows:
        return f"No history for {symbol.upper()} ({range})."
    closes = [row["close"] for row in rows if row.get("close") is not None]
    if not closes:
        return f"No closing prices for {symbol.upper()}."
    first, last = closes[0], closes[-1]
    change_pct = ((last - first) / first * 100) if first else 0.0
    summary = [
        f"{symbol.upper()} {range} history: {len(rows)} sessions",
        f"  Start: {rows[0]['date']} @ {first:g}",
        f"  End:   {rows[-1]['date']} @ {last:g}",
        f"  Change over period: {change_pct:+.2f}%",
        f"  High: {max(closes):g} | Low: {min(closes):g}",
        "  Last 10 closes: " + ", ".join(f"{c:g}" for c in closes[-10:]),
    ]
    return "\n".join(summary)
