"""Which sub-agent a message needs — so Nyx brings it in without being asked (Request J7).

The owner (2026-09-16): "AI should now auto use the sub agent it needs without me having to manually do this."

The Manager's prompt already lists the team, but models under-delegate: they answer themselves unless told.
This is the telling. Before a turn, the message is scored against every specialist's name, expertise, goal
and purpose (offline, a few milliseconds). A clear match adds a short system note naming the agent and why,
and the turn takes the full pipeline so the delegation tools are there. Agents the owner or Nyx made get a
small bonus: someone made them for exactly this kind of work.

Small talk and short questions never match (a greeting should not wake the News agent).
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

PREFIX = "[Sub-agent match]"
MIN_WORDS = 5
THRESHOLD = 1.6

_STOP = frozenset("""a an and the to of in for on with by from into at or as is are be this that it its i me my you your we
our can could would should will please help want need make do does did get give show tell about what how why when
where which who some any all more most just like also then than so if not no yes ok okay hi hello hey thanks thank
new use using work working agent agents nyx task tasks something thing things good best really very""".split())

_ALIASES = {
    "code": {"coder", "programming", "python", "javascript", "typescript", "bug", "debug", "function", "script", "refactor", "api"},
    "design": {"ui", "ux", "layout", "figma", "css", "style", "logo", "mockup"},
    "finance": {"stock", "stocks", "invest", "budget", "money", "price", "prices", "crypto", "portfolio"},
    "news": {"headlines", "latest", "today", "breaking"},
    "research": {"research", "sources", "compare", "study", "paper", "papers", "find"},
    "email": {"email", "emails", "inbox", "reply", "draft", "gmail", "outlook"},
    "travel": {"trip", "flight", "flights", "hotel", "itinerary", "vacation"},
    "game": {"game", "games", "level", "unity", "sprite", "player"},
    "hardware": {"arduino", "raspberry", "pi", "circuit", "sensor", "3d", "print", "solder"},
    "security": {"secure", "vulnerability", "password", "attack", "privacy", "malware"},
    "data": {"csv", "spreadsheet", "chart", "graph", "dataset", "analyze", "analysis", "statistics"},
    "tech": {"slow", "crash", "crashing", "install", "uninstall", "settings", "cleanup", "windows", "driver", "wifi", "freeze"},
    "educator": {"explain", "exam", "homework", "learn", "teach", "quiz", "lesson", "tutor", "biology", "chemistry", "physics"},
    "writer": {"essay", "rewrite", "proofread", "resume", "grammar", "tone", "paragraph", "letter"},
}


def _words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9+#.-]*", (text or "").lower()) if w not in _STOP and len(w) > 1]


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ers", "er", "ed", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix) and not word.endswith("ss"):
            return word[: -len(suffix)]
    return word


def _expand(words: List[str]) -> set:
    out = {_stem(w) for w in words}
    for key, group in _ALIASES.items():
        if any(w in group for w in words) or key in words:
            out |= {_stem(key)} | {_stem(g) for g in group}
    return out


def profile(agent: Dict[str, Any]) -> Dict[str, set]:
    return {
        "name": _expand(_words(agent.get("name", ""))),
        "expertise": _expand(_words(" ".join(agent.get("expertise", []) or []))),
        "goal": {_stem(w) for w in _words(f"{agent.get('goal', '')} {agent.get('purpose', '')}")},
    }


def score(message: str, agent: Dict[str, Any]) -> Dict[str, Any]:
    words = _words(message)
    said = {_stem(w) for w in words}
    parts = profile(agent)
    hits = {"name": sorted(said & parts["name"]), "expertise": sorted(said & parts["expertise"]),
            "goal": sorted(said & parts["goal"])}
    raw = 3.0 * len(hits["name"]) + 2.0 * len(hits["expertise"]) + 1.0 * len(hits["goal"])
    size = len(parts["name"] | parts["expertise"] | parts["goal"]) or 1
    value = raw / math.sqrt(max(4.0, size / 3))
    if agent.get("origin", "roster") != "roster" or agent.get("made_by") in ("owner", "nyx"):
        value *= 1.25
    why = sorted(set(hits["name"] + hits["expertise"] + hits["goal"]))[:5]
    return {"name": agent.get("name", ""), "emoji": agent.get("emoji", ""), "score": round(value, 2), "why": why}


def match(message: str, roster: Optional[List[Dict[str, Any]]] = None, limit: int = 2) -> List[Dict[str, Any]]:
    """The specialists this message clearly needs, best first (usually none)."""
    if len(_words(message)) < MIN_WORDS - 2 or len(re.findall(r"\w+", message or "")) < MIN_WORDS:
        return []
    if roster is None:
        from agent_runtime import load_roster

        roster = load_roster()
    scored = [score(message, a) for a in roster if a.get("role") != "master"]
    good = sorted((s for s in scored if s["score"] >= THRESHOLD and s["why"]), key=lambda s: -s["score"])
    if not good:
        return []
    top = good[0]["score"]
    # A second agent only when it is nearly as clear as the first (a mixed request).
    return [s for s in good[:limit] if s["score"] >= top * 0.75]


def brief(matches: List[Dict[str, Any]]) -> str:
    if not matches:
        return ""
    lines = [PREFIX, "These specialists on your team fit this request — bring them in yourself, the owner should not "
                     "have to ask:"]
    for m in matches:
        lines.append(f"- {m['emoji']} {m['name']} (matched: {', '.join(m['why'])})")
    lines.append("Hand each the part it is best at with delegate_task (dispatch_agents when several copies can split the "
                 "work), with all the context it needs, then combine the reports. Answer directly only if the request "
                 "turns out to be trivial.")
    return "\n".join(lines)
