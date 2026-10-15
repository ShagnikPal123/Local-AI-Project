"""The roster: who is on the team, what each one is doing, and what each one is thinking.

The owner asked for "its own big team", with front bots that trade and "background agents [that] can
be seen and shown that they are making strategies, working hard, and actually doing their job".
So every bot has a name, a role, a status and a one-line "doing", and every bot writes its
reasoning into one shared feed (``Notes``) that the dashboard shows live.

The roster is saved (``team.json``) so hires, retirements and each trader's share of the money
survive a restart. The thinking feed is kept in memory and saved with each cycle.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from .. import store
from ..models import BotNote

#: Names for traders the manager hires, in order. Stars, so they are easy to tell apart.
TRADER_NAMES = ["Vega", "Nova", "Orion", "Lyra", "Rigel", "Altair", "Deneb", "Sirius", "Capella", "Polaris"]

ROLES = {
    "scout": "Looks at hundreds of markets each cycle and ranks them.",
    "strategist": "Studies history in the background and learns which strategy works in which kind of market.",
    "advisor": "Tells each trader which strategy fits each market right now.",
    "trader": "Owns a pot of money and a set of markets; buys and sells.",
    "skeptic": "Reads every buy before it goes; stops the ones very likely to fail, shrinks the doubtful ones.",
    "manager": "Moves money to the traders that are working, hires and retires traders, tunes the settings.",
    "researcher": "Writes a short note on why the top markets are moving.",
}


def _default_roster() -> Dict[str, Any]:
    now = time.time()

    def bot(name: str, role: str, front: bool = False, classes: Optional[List[str]] = None, share: float = 0.0,
            style: str = "spread") -> Dict[str, Any]:
        return {"id": f"bot-{name.lower()}", "name": name, "role": role, "front": front, "classes": classes or [],
                "share": share, "style": style, "status": "idle", "doing": "", "hired_at": now, "retired": False}

    return {"bots": [
        bot("Iris", "scout"), bot("Sage", "strategist"), bot("Atlas", "advisor"), bot("Mira", "skeptic"),
        bot("Max", "manager"), bot("Echo", "researcher"),
        bot("Vega", "trader", True, ["crypto"], 0.35),
        bot("Nova", "trader", True, ["stock", "etf"], 0.35),
        # The rotator: holds one or two of the strongest coins and swaps into whichever leads
        # (the owner: "rotate between bitcoin, etherium, and more markets that are similar").
        bot("Orion", "trader", True, ["crypto"], 0.30, style="rotate"),
    ], "shifts": [], "hires": []}


class Notes:
    """The shared thinking feed. Newest first when read; capped so it never grows without end."""

    def __init__(self, keep: int = 200):
        saved = store.read("notes", lambda: {"notes": []}).get("notes", [])
        self._items: Deque[Dict[str, Any]] = deque(saved[-keep:], maxlen=keep)
        self._lock = threading.Lock()

    def add(self, bot: Dict[str, Any], text: str, level: str = "info", symbol: str = "") -> None:
        with self._lock:
            self._items.append(BotNote(bot["name"], bot["role"], text, level, symbol).to_dict())

    def latest(self, limit: int = 60) -> List[Dict[str, Any]]:
        with self._lock:
            return list(reversed(list(self._items)[-limit:]))

    def save(self) -> None:
        with self._lock:
            store.write("notes", {"notes": list(self._items)})


class Team:
    """The roster plus the feed, with small helpers the bots and the engine share."""

    def __init__(self) -> None:
        self.roster = store.read("team", _default_roster)
        self.notes = Notes()

    def save(self) -> None:
        store.write("team", self.roster)
        self.notes.save()

    def active(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        return [b for b in self.roster["bots"] if not b.get("retired") and (role is None or b["role"] == role)]

    def one(self, role: str) -> Dict[str, Any]:
        return self.active(role)[0]

    def traders(self) -> List[Dict[str, Any]]:
        return self.active("trader")

    def set_doing(self, bot: Dict[str, Any], doing: str, status: str = "working") -> None:
        bot["doing"], bot["status"] = doing, status

    def normalise_shares(self) -> None:
        """Traders' shares of the money add up to 1."""
        traders = self.traders()
        total = sum(t["share"] for t in traders)
        for t in traders:
            t["share"] = round(t["share"] / total, 4) if total > 0 else round(1 / len(traders), 4)

    def hire(self, classes: List[str], why: str, share: float = 0.12, style: str = "spread") -> Dict[str, Any]:
        used = {b["name"] for b in self.roster["bots"]}
        name = next((n for n in TRADER_NAMES if n not in used), f"Trader {len(used) + 1}")
        bot = {"id": f"bot-{name.lower()}", "name": name, "role": "trader", "front": True, "classes": classes,
               "share": share, "style": style, "status": "idle", "doing": "Just hired", "hired_at": time.time(),
               "retired": False}
        self.roster["bots"].append(bot)
        self.roster["hires"] = (self.roster.get("hires") or [])[-19:] + [{"at": time.time(), "name": name, "why": why}]
        self.normalise_shares()
        return bot

    def retire(self, bot: Dict[str, Any], why: str) -> None:
        bot["retired"], bot["status"], bot["doing"] = True, "retired", why
        bot["share"] = 0.0
        self.normalise_shares()
