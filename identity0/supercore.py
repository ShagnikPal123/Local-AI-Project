"""The supercore's constitution: who Big Kahuna is and what it holds to — changeable, never by itself (Request S8).

"Changes are run through it, it itself can be changed." Its persona and principles are data, versioned in
``kahuna/constitution.json``. The owner edits them directly. Big Kahuna can only *propose* an edit (with its
reason); a proposal changes nothing until the owner approves it — the same rule as every self-change in
Nyx (AGENTS.md invariant 4: an AI never approves its own change). Every applied version is kept, so any
change can be rolled back.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

import identity0
from identity0 import state

FILE = "constitution.json"
_FIELDS = ("persona", "principles", "voice")
DEFAULT = {
    "persona": (f"{identity0.NAME} (second name {identity0.CODENAME}) is the owner's own AI: the main brain of Nyx. It is "
                "direct, warm and honest, says when it is unsure, and gets better by comparing its answers with others."),
    "principles": [
        "The owner's words come first; ask when a request is unclear.",
        "Never spend the owner's money or share their data without asking.",
        "Say what you did and what you could not do, plainly.",
        "When another model is better at something, use it — and learn from it.",
        "Never approve your own change: propose it and let the owner decide.",
    ],
    "voice": "Short, plain sentences. No filler.",
}


class ConstitutionError(ValueError):
    pass


def _load() -> Dict[str, Any]:
    data = state.read_json(FILE, {})
    if not isinstance(data, dict) or "current" not in data:
        data = {"current": {**DEFAULT, "version": 1, "at": time.time(), "by": "default"}, "history": [], "proposals": []}
    return data


def current() -> Dict[str, Any]:
    return _load()["current"]


def _clean(changes: Dict[str, Any]) -> Dict[str, Any]:
    unknown = set(changes) - set(_FIELDS)
    if unknown:
        raise ConstitutionError(f"Only {', '.join(_FIELDS)} can change.")
    out: Dict[str, Any] = {}
    if "persona" in changes:
        out["persona"] = str(changes["persona"]).strip()[:1500]
    if "voice" in changes:
        out["voice"] = str(changes["voice"]).strip()[:400]
    if "principles" in changes:
        items = changes["principles"]
        if not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            raise ConstitutionError("principles must be a list of sentences")
        out["principles"] = [i.strip()[:300] for i in items if i.strip()][:20]
    return out


def _apply(data: Dict[str, Any], changes: Dict[str, Any], by: str) -> Dict[str, Any]:
    data["history"] = (data.get("history", []) + [data["current"]])[-30:]
    data["current"] = {**data["current"], **changes, "version": int(data["current"].get("version", 1)) + 1,
                       "at": time.time(), "by": by}
    return data["current"]


def update(changes: Dict[str, Any], by: str = "owner") -> Dict[str, Any]:
    """The owner's own edit: applied at once, the old version kept."""
    data = _load()
    result = _apply(data, _clean(changes), by)
    state.write_json(FILE, data)
    return result


def propose(changes: Dict[str, Any], why: str, by: str = identity0.NAME) -> Dict[str, Any]:
    """Big Kahuna suggests an edit; nothing changes until the owner approves it."""
    data = _load()
    proposal = {"id": uuid.uuid4().hex[:10], "changes": _clean(changes), "why": str(why).strip()[:600], "by": by,
                "at": time.time(), "state": "pending"}
    data["proposals"] = (data.get("proposals", []) + [proposal])[-40:]
    state.write_json(FILE, data)
    return proposal


def pending() -> List[Dict[str, Any]]:
    return [p for p in _load().get("proposals", []) if p.get("state") == "pending"]


def decide(proposal_id: str, approve: bool, by: str = "owner") -> Dict[str, Any]:
    data = _load()
    proposal = next((p for p in data.get("proposals", []) if p["id"] == proposal_id and p["state"] == "pending"), None)
    if proposal is None:
        raise ConstitutionError("That proposal is gone.")
    proposal["state"] = "approved" if approve else "declined"
    proposal["decided_by"] = by
    result: Optional[Dict[str, Any]] = _apply(data, proposal["changes"], f"{proposal['by']} (approved by {by})") if approve else None
    state.write_json(FILE, data)
    return {"proposal": proposal, "current": result or data["current"]}


def rollback(by: str = "owner") -> Dict[str, Any]:
    data = _load()
    if not data.get("history"):
        raise ConstitutionError("There is no earlier version.")
    previous = data["history"].pop()
    data["current"] = {**previous, "version": int(data["current"].get("version", 1)) + 1, "at": time.time(),
                       "by": f"rollback by {by}"}
    state.write_json(FILE, data)
    return data["current"]


def system_note() -> str:
    """The constitution as a short system note for Big Kahuna's own conversations (companion, own model)."""
    c = current()
    return f"{c['persona']}\nPrinciples: " + " ".join(f"({i + 1}) {p}" for i, p in enumerate(c["principles"])) + \
           f"\nVoice: {c['voice']}"
