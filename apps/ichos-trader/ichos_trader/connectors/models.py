"""Thinking help from language models: a free local one, and Claude only when the owner asks.

* **Ollama** runs on the PC, free and private. Nothing here calls it on a timer yet; it is listed so
  the Connectors page can show whether it is there.
* **Claude** is opt-in twice over: the connector must be switched on *and* the owner must press
  Ask. The trader never calls it by itself (Shagnik: "a claude connector that it will use only when
  asked"). The question goes with a short, key-free summary of the dashboard.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import requests

from ..access import secrets

OLLAMA_URL = "http://127.0.0.1:11434"
CLAUDE_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_MAX_TOKENS = 700


class ModelError(Exception):
    """A model call that could not be made, with a sentence the owner can read."""


def ollama_status(http: Optional[requests.Session] = None) -> str:
    try:
        tags = (http or requests.Session()).get(OLLAMA_URL + "/api/tags", timeout=2).json()
    except (requests.RequestException, ValueError):
        return "Not running on this PC."
    names = [m.get("name", "") for m in tags.get("models", [])]
    return f"Running with {len(names)} model(s)." if names else "Running, but no models are downloaded."


def context_for(dashboard: Dict[str, Any]) -> str:
    """What Claude is shown: numbers and the latest reasoning, never keys, emails or settings secrets."""
    keep = {
        "state": dashboard.get("state_words"),
        "money": dashboard.get("money"),
        "win_rate": dashboard.get("win_rate"),
        "positions": [{k: p.get(k) for k in ("symbol", "qty", "avg_price", "price", "pl_pct", "bot")}
                      for p in dashboard.get("positions", [])[:15]],
        "recent_trades": [{k: t.get(k) for k in ("symbol", "side", "price", "bot", "reason")}
                          for t in dashboard.get("trades", [])[:15]],
        "top_markets": [{k: m.get(k) for k in ("symbol", "score", "signal", "spread_bps", "flow")}
                        for m in dashboard.get("markets", [])[:10]],
        "thinking": [f"{n.get('bot')}: {n.get('text')}" for n in dashboard.get("thinking", [])[:25]],
    }
    return json.dumps(keep, default=str)[:12_000]


def ask_claude(question: str, dashboard: Dict[str, Any], enabled: bool, http: Optional[requests.Session] = None,
               model: str = CLAUDE_MODEL) -> Dict[str, Any]:
    question = (question or "").strip()[:2_000]
    if not enabled:
        raise ModelError("The Claude connector is off. Switch it on in Connectors first.")
    key = secrets.get("anthropic_api_key")
    if not key:
        raise ModelError("Claude has no key. Add one on the Connectors page.")
    if not question:
        raise ModelError("Ask a question first.")
    body = {"model": model, "max_tokens": CLAUDE_MAX_TOKENS,
            "system": "You explain a practice (paper money) trading bot's decisions to its owner in plain words. "
                      "Use only the data given. Say when the data does not answer the question.",
            "messages": [{"role": "user", "content": f"Trader data (JSON):\n{context_for(dashboard)}\n\nQuestion: {question}"}]}
    try:
        reply = (http or requests.Session()).post(CLAUDE_URL, json=body, timeout=60, headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    except requests.RequestException as error:
        raise ModelError("Could not reach Claude.") from error
    if reply.status_code == 401:
        raise ModelError("Claude refused the key.")
    if reply.status_code >= 400:
        raise ModelError(f"Claude said no ({reply.status_code}).")
    data = reply.json()
    text = "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
    return {"answer": text.strip(), "model": data.get("model", model), "used_context": ["dashboard"]}
