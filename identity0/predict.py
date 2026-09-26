"""What Big Kahuna expects the owner needs next: skills, sub-agents, tabs, and what they are about to ask.

Request S15–S18: "high adaption, prediction … prediction on what skills to use and auto apply … which
sub agents to use … predict and create tabs automatically if user switches on". Every prediction here
is offline and fast (keyword scores, Nyx Core's heads, the tab predictor), because it runs on every
turn and on every few words of speech; a model is only asked when the owner asks for suggestions.

Skills are already attached to each turn by ``skills.SkillStore.build_context`` — this module adds
what was *learned*: skills and agents whose turns the owner rated well get a boost, ones rated badly
lose it (``learn``), so the prediction adapts to how the owner actually works.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional

from identity0 import state

_lock = threading.Lock()
_FILE = "adapt.json"

#: Phrases that mean "be quick": voice turns and trading work get the speed plan.
_VOICE = "[Hands-free voice]"
_TRADING = re.compile(r"\b(trade|trading|stock|stocks|ticker|buy|sell|position|portfolio|market|options|crypto|"
                      r"shares|price of|rsi|sma|candle|earnings)\b", re.I)


def _weights() -> Dict[str, Any]:
    data = state.read_json(_FILE, {})
    return data if isinstance(data, dict) else {}


def learn(kind: str, name: str, rating: int) -> None:
    """A rated turn moves the weight of the skill/agent that took part (bounded, so one vote is not a verdict)."""
    if not name:
        return
    with _lock:
        data = _weights()
        bucket = data.setdefault(kind, {})
        bucket[name] = round(max(-3.0, min(3.0, float(bucket.get(name, 0.0)) + 0.5 * max(-1, min(1, rating)))), 2)
        state.write_json(_FILE, data)


def speed_mode(messages: List[Dict[str, Any]], text: str) -> Optional[str]:
    """"voice" or "trading" when the answer must come fast; None otherwise."""
    if any(_VOICE in str(m.get("content", "")) for m in messages if m.get("role") == "system"):
        return "voice"
    if _TRADING.search(text or ""):
        return "trading"
    return None


def skills(text: str, limit: int = 3) -> List[Dict[str, Any]]:
    try:
        store = _skill_store()
        picked = store.select_for(text, limit=limit + 2) if store else []
    except Exception:  # noqa: BLE001
        return []
    weights = _weights().get("skill", {})
    rows = [{"id": s.skill_id, "name": s.name, "score": s.match_score(text) + weights.get(s.skill_id, 0.0)}
            for s in picked]
    rows = [r for r in rows if r["score"] > 0]
    return sorted(rows, key=lambda r: r["score"], reverse=True)[:limit]


_STORE: Any = None


def _skill_store() -> Any:
    global _STORE
    if _STORE is None:
        try:
            import skills as skills_module

            _STORE = skills_module.SKILL_STORE
        except Exception:  # noqa: BLE001
            _STORE = None
    return _STORE


def agents(text: str, limit: int = 2) -> List[Dict[str, Any]]:
    try:
        import agent_match

        found = agent_match.match(text, limit=limit + 2)
    except Exception:  # noqa: BLE001
        return []
    weights = _weights().get("agent", {})
    rows = []
    for item in found:
        name = str(item.get("name") or "")
        rows.append({"name": name, "emoji": item.get("emoji", ""), "why": item.get("why", []),
                     "score": round(float(item.get("score", 0)) + weights.get(name, 0.0), 2)})
    return sorted([r for r in rows if r["name"] and r["score"] > 0], key=lambda r: r["score"], reverse=True)[:limit]


def next_tab(current: str = "") -> Optional[Dict[str, Any]]:
    try:
        import predictor

        return predictor.PREDICTOR.next_tab(current)
    except Exception:  # noqa: BLE001
        return None


def domain(text: str) -> Dict[str, Any]:
    try:
        import nyx_core

        guess = nyx_core.CORE.predict(text or "")
        return {"domain": guess.get("domain"), "confidence": round(float(guess.get("domain_p", 0.0)), 3),
                "route": guess.get("route"), "tools": guess.get("tools", [])}
    except Exception:  # noqa: BLE001
        return {"domain": "chat", "confidence": 0.0, "route": "fast", "tools": []}


def everything(text: str, current_tab: str = "") -> Dict[str, Any]:
    """One call for the companion and the Big Kahuna tab: all predictions for this text."""
    return {"domain": domain(text), "skills": skills(text), "agents": agents(text), "next_tab": next_tab(current_tab),
            "speed": speed_mode([], text)}
