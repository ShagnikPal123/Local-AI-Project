"""Which model may be trusted with money, given that limits run out.

The owner: "make sure if it does use an api and a non local as a collab or as a
backup or just as the main make sure it has either reinforce like qwen or has
enough use to the point where it wouldn't matter over the course of use."

Read plainly: a finance session runs for hours, so the model behind it must not
stop halfway. The rule this encodes:

1. **Local first, always.** A model on this PC has no quota at all, so a session
   that runs all day can only really be built on one.
2. **Then the reinforced families the owner named** (Qwen, and the other
   instruction-tuned workhorses that are cheap to run), *if* their key has room.
3. **Then anything whose remaining quota covers the whole session** — worked out
   from calls per hour times hours, not from hope.
4. **Never** a provider that is already rate limited, out of credit, or whose
   remaining calls would run out before the session ends. It is better to answer
   from arithmetic than to stop mid-day with a position open.

Nothing here calls a model. It answers "who should do this, and why".
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import node_map

#: Families the owner called out as reinforced: preferred among cloud models.
REINFORCED = ("qwen", "deepseek", "nvidia")
#: A finance session makes roughly this many model calls an hour.
CALLS_PER_HOUR = 40


def _local() -> Optional[Dict[str, Any]]:
    """The model on this PC, if there is one."""
    try:
        from config import SETTINGS

        host = getattr(SETTINGS, "ollama_host", "")
        model = getattr(SETTINGS, "ollama_model", "")
        if host and model:
            return {"provider": "ollama", "model": model, "why": "On this PC — no limit to run out of.",
                    "local": True, "headroom": None}
    except Exception:  # noqa: BLE001
        pass
    try:
        from identity0 import api as kahuna

        if kahuna.own_model_ready():                     # type: ignore[attr-defined]
            return {"provider": "identity0", "model": "big-kahuna", "local": True, "headroom": None,
                    "why": "Big Kahuna's own model, on this PC."}
    except Exception:  # noqa: BLE001
        pass
    return None


def _limits(provider: str) -> Dict[str, Any]:
    """The day (or hour) request limit a provider reports, flattened.

    ``usage_limits.snapshot`` returns every window it knows about; what matters
    for a long session is the request budget with the longest window, so that is
    the one taken.
    """
    try:
        import usage_limits

        snapshot = usage_limits.snapshot(provider)
    except Exception:  # noqa: BLE001
        return {}
    rows = [row for row in snapshot.get("limits", []) if row.get("kind") == "requests"] or snapshot.get("limits", [])
    if not rows:
        balance = snapshot.get("balance") or {}
        return {"balance": balance.get("amount")} if balance else {}
    row = rows[0]
    return {"remaining": row.get("remaining"), "limit": row.get("limit"), "window": row.get("window"),
            "reset_seconds": (row.get("reset_at") - time.time()) if row.get("reset_at") else None}


def _configured() -> List[str]:
    try:
        from router import Router

        status = Router().status()
        return [name for name, ok in status.items() if ok and isinstance(ok, bool)]
    except Exception:  # noqa: BLE001
        try:
            from model_hub import known_providers

            return list(known_providers())
        except Exception:  # noqa: BLE001
            return []


def headroom(provider: str, hours: float = 6.0) -> Dict[str, Any]:
    """Would this provider last the session? Numbers where there are numbers."""
    needed = int(CALLS_PER_HOUR * max(hours, 0.5))
    limits = _limits(provider)
    remaining = limits.get("remaining") or limits.get("requests_remaining")
    resets = limits.get("reset_seconds") or limits.get("resets_in")
    if remaining is None:
        return {"provider": provider, "known": False, "needed": needed,
                "verdict": "unknown", "why": "That provider does not say how much is left."}
    remaining = int(remaining)
    enough = remaining >= needed
    return {
        "provider": provider,
        "known": True,
        "remaining": remaining,
        "needed": needed,
        "resets_in": resets,
        "verdict": "enough" if enough else "short",
        "why": (f"{remaining} calls left, about {needed} needed for {hours:.0f} hours."
                if enough else f"Only {remaining} calls left and about {needed} are needed — it would stop mid-session."),
    }


def pick(job: str = "decide", hours: float = 6.0) -> Dict[str, Any]:
    """Who should do this piece of finance work, and why."""
    node_map.light("decision", f"model for {job}")
    local = _local()
    if local:
        return {**local, "job": job, "picked_at": time.time(), "fallbacks": _cloud_order(hours)[:2]}

    order = _cloud_order(hours)
    if order:
        best = order[0]
        return {**best, "job": job, "local": False, "picked_at": time.time(), "fallbacks": order[1:3]}
    return {"provider": "", "model": "", "local": False, "job": job,
            "why": ("Nothing can be trusted with a long finance session: there is no local model and no cloud key "
                    "with enough left. Install a local model, or add a key, before letting it run all day."),
            "fallbacks": []}


def _cloud_order(hours: float) -> List[Dict[str, Any]]:
    """Cloud providers that could carry a session, best first."""
    rows: List[Dict[str, Any]] = []
    for provider in _configured():
        if provider in ("ollama", "identity0"):
            continue
        room = headroom(provider, hours)
        if room["verdict"] == "short":
            continue
        reinforced = any(family in provider for family in REINFORCED)
        rows.append({
            "provider": provider,
            "model": "",
            "reinforced": reinforced,
            "headroom": room,
            "why": ("A reinforced model the owner named" if reinforced else "Enough quota for the session")
                   + f" — {room['why']}",
        })
    rows.sort(key=lambda row: (not row["reinforced"], row["headroom"].get("verdict") != "enough"))
    return rows


def advice(hours: float = 6.0) -> Dict[str, Any]:
    """The whole picture for the panel: who would answer, and what the limits look like."""
    chosen = pick("decide", hours)
    return {
        "picked": chosen,
        "local_available": bool(_local()),
        "calls_per_hour": CALLS_PER_HOUR,
        "hours": hours,
        "providers": [{"provider": p, **headroom(p, hours)} for p in _configured() if p not in ("ollama", "identity0")][:8],
        "rule": ("Local first, because it has no limit. Then the reinforced models the owner named, if their key has "
                 "room. Then anything with enough quota left for the whole session. Never one that would stop halfway."),
    }
