"""What Identity 0 has learned about who is good at what — and when its own model takes over.

One row per (domain, member): answers, successes, time, judged wins/losses/ties and the owner's
ratings. The score blends them with Laplace priors, so a member with no history is neither trusted
nor shut out, and one lucky answer cannot outrank fifty good ones.

Graduation ("2 models running at once, then 1") is decided per domain from the own model's judged
results against the others: its Wilson lower bound on the win rate (ties count half) must reach 0.50
over at least 30 comparisons. It is demoted when the upper bound over its last 30 falls below 0.45,
so a regression hands the domain back to the teacher on its own.
"""

from __future__ import annotations

import math
import threading
from typing import Any, Dict, Iterable, List, Optional

from identity0 import state

GRADUATE_MIN = 30
GRADUATE_LB = 0.50
DEMOTE_UB = 0.45
_WINDOW = 60
_lock = threading.RLock()
_data: Optional[Dict[str, Any]] = None
_FILE = "competence.json"


def _load() -> Dict[str, Any]:
    global _data
    if _data is None:
        raw = state.read_json(_FILE, {})
        _data = raw if isinstance(raw, dict) else {}
        _data.setdefault("domains", {})
        _data.setdefault("self_vs", {})
        _data.setdefault("graduated", {})
        if not _data.get("seeded"):
            _seed(_data)
    return _data


def reset_cache() -> None:
    """Forget the in-memory copy (tests, or after the store directory changes)."""
    global _data
    with _lock:
        _data = None


def _save() -> None:
    if _data is not None:
        state.write_json(_FILE, _data)


def _row(data: Dict[str, Any], domain: str, member: str) -> Dict[str, Any]:
    return data["domains"].setdefault(domain or "chat", {}).setdefault(
        member, {"n": 0, "ok": 0, "ms": 0.0, "wins": 0, "losses": 0, "ties": 0, "rating": 0})


def _seed(data: Dict[str, Any]) -> None:
    """Start from what Nyx Core's crutch ledger already knows (capped, so it is a prior, not a verdict)."""
    data["seeded"] = True
    try:
        import nyx_core

        ledger = dict(nyx_core.CORE._state.get("ledger", {})) if getattr(nyx_core.CORE, "_state", None) else {}
    except Exception:  # noqa: BLE001 - no ledger is fine
        return
    for key, entry in ledger.items():
        try:
            domain, provider, model = key.split("|", 2)
            n = min(int(entry.get("n", 0)), 20)
            if not n:
                continue
            ratio = n / max(1, int(entry.get("n", 0)))
            row = _row(data, domain, f"{provider}:{model or 'default'}")
            row["n"] += n
            row["ok"] += int(round(int(entry.get("ok", 0)) * ratio))
            row["ms"] += float(entry.get("ms", 0.0)) * ratio
            row["rating"] += int(entry.get("rating", 0))
        except (ValueError, TypeError, AttributeError):
            continue


def record_answer(domain: str, member: str, ok: bool, ms: float) -> None:
    with _lock:
        data = _load()
        row = _row(data, domain, member)
        row["n"] += 1
        row["ok"] += int(bool(ok))
        row["ms"] += max(0.0, float(ms or 0.0))
        _save()


def record_rating(domain: str, member: str, rating: int) -> None:
    with _lock:
        data = _load()
        _row(data, domain, member)["rating"] += int(max(-1, min(1, rating)))
        _save()


def record_verdict(domain: str, winner: str, loser: str, tie: bool = False) -> Optional[str]:
    """Count one judged comparison; returns "graduated"/"demoted" when the own model's standing changed."""
    with _lock:
        data = _load()
        a, b = _row(data, domain, winner), _row(data, domain, loser)
        if tie:
            a["ties"] += 1
            b["ties"] += 1
        else:
            a["wins"] += 1
            b["losses"] += 1
        change = None
        own = [m for m in (winner, loser) if m.startswith("self:")]
        if len(own) == 1:
            result = 0.5 if tie else (1.0 if winner == own[0] else 0.0)
            history = data["self_vs"].setdefault(domain, [])
            history.append(result)
            del history[:-_WINDOW]
            change = _update_graduation(data, domain)
        _save()
        return change


def record_exam(domain: str, member: str, score: float) -> None:
    """A scoreboard result for this member in this domain (0..1), blended into what it already knew.

    The fixed suite is the one signal that needs no judge and no owner: it says outright that a model
    gets the code questions right and the facts wrong. Big Kahuna should not have to learn that again,
    one judged turn at a time.
    """
    value = max(0.0, min(1.0, float(score)))
    with _lock:
        data = _load()
        row = _row(data, domain or "chat", member)
        previous = row.get("exam")
        row["exam"] = round(value if previous is None else 0.5 * float(previous) + 0.5 * value, 4)
        row["exams"] = int(row.get("exams", 0)) + 1
        _save()


def wilson(results: List[float], z: float = 1.96) -> tuple:
    """(lower, upper) 95% Wilson bounds for a win rate where ties are 0.5."""
    n = len(results)
    if not n:
        return 0.0, 1.0
    p = sum(results) / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    denominator = 1 + z * z / n
    return max(0.0, (centre - spread) / denominator), min(1.0, (centre + spread) / denominator)


def _update_graduation(data: Dict[str, Any], domain: str) -> Optional[str]:
    history = data["self_vs"].get(domain, [])
    was = bool(data["graduated"].get(domain))
    if not was and len(history) >= GRADUATE_MIN and wilson(history)[0] >= GRADUATE_LB:
        data["graduated"][domain] = True
        return "graduated"
    if was and len(history) >= GRADUATE_MIN and wilson(history[-GRADUATE_MIN:])[1] < DEMOTE_UB:
        data["graduated"][domain] = False
        # Start the count again from the recent record only: otherwise the old wins that earned the
        # graduation are still in the window and the own model flips back and forth the next few turns.
        data["self_vs"][domain] = history[-GRADUATE_MIN:]
        return "demoted"
    return None


def score(domain: str, member: Any, *, picked: str = "") -> float:
    """0..1-ish desirability of ``member`` for ``domain`` (higher is better)."""
    with _lock:
        row = _load()["domains"].get(domain or "chat", {}).get(member.id)
        general = _load()["domains"].get("chat", {}).get(member.id) if domain != "chat" else None
    row = row or general or {"n": 0, "ok": 0, "ms": 0.0, "wins": 0, "losses": 0, "ties": 0, "rating": 0}
    success = (row["ok"] + 1) / (row["n"] + 2)
    judged = row["wins"] + row["losses"] + row["ties"]
    quality = (row["wins"] + 0.5 * row["ties"] + 1) / (judged + 2)
    avg_ms = row["ms"] / row["n"] if row["n"] else (1500.0 if member.local else 4000.0)
    speed = 1.0 / (1.0 + avg_ms / 8000.0)
    value = 0.45 * quality + 0.35 * success + 0.15 * speed + 0.1 * math.tanh(row["rating"] / 3)
    if row.get("exam") is not None:
        value = 0.8 * value + 0.2 * float(row["exam"])  # what it actually got right on the fixed suite
    if member.local:
        value += 0.04  # private, free and never rate-limited
    if picked and member.provider == picked:
        value += 0.05  # the owner's own pick is a signal too
    if member.provider == "self" and not graduated(domain):
        value -= 1.0   # the own model only leads a domain it has graduated in
    return round(value, 4)


def avg_ms(domain: str, member: Any) -> float:
    """Average answer time for ``member`` in ``domain`` (the general row when the domain has none)."""
    with _lock:
        rows = _load()["domains"]
        row = rows.get(domain or "chat", {}).get(member.id) or rows.get("chat", {}).get(member.id)
    if row and row.get("n"):
        return row["ms"] / row["n"]
    return 1500.0 if getattr(member, "local", False) else 4000.0


def rank(domain: str, members: Iterable[Any], *, needs_vision: bool = False, picked: str = "") -> List[Any]:
    members = list(members)
    pool = [m for m in members if m.vision or not needs_vision] or members
    return sorted(pool, key=lambda m: score(domain, m, picked=picked), reverse=True)


def graduated(domain: str) -> bool:
    with _lock:
        return bool(_load()["graduated"].get(domain))


def stage(domain: str, has_own_model: bool) -> str:
    if not has_own_model:
        return "collaborate"
    return "solo" if graduated(domain) else "twin"


def table() -> Dict[str, Any]:
    """Everything the Big Kahuna tab shows: per-domain rows, the own model's record, graduations."""
    with _lock:
        data = _load()
        domains = {}
        for domain, rows in data["domains"].items():
            domains[domain] = {member: {**row, "avg_ms": round(row["ms"] / row["n"]) if row["n"] else None}
                               for member, row in rows.items()}
        own = {domain: {"n": len(h), "win_rate": round(sum(h) / len(h), 3) if h else None,
                        "bounds": [round(x, 3) for x in wilson(h)]} for domain, h in data["self_vs"].items()}
        return {"domains": domains, "own_model": own, "graduated": dict(data["graduated"]),
                "rule": {"min": GRADUATE_MIN, "lower_bound": GRADUATE_LB, "demote_upper": DEMOTE_UB}}
