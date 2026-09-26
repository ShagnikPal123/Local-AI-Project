"""High finance: everything else stops, and the owner is told why.

The owner: "For high finance use it should have a warning and turn off all other
features as and keep only the finance if memory allocated to finance is very
high."

Two halves:

* **The warning.** Before anything stops, the owner sees what will stop, what is
  running that would be interrupted, and how much of their money the AI is about
  to be working with. Entering is always a decision, never a side effect.
* **The stopping.** Background work is paused through whatever each part offers —
  the shared background-jobs switch when it exists, and the Improve autopilot,
  Data Absorption, Curiosity and Big Kahuna's training directly when it does not.
  Everything that paused is written down so leaving focus mode puts back exactly
  what was taken away, and nothing else.

"Memory allocated to finance is very high" is read as: a big share of the pot is
committed, or the owner asked for it outright. Both routes end here.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List

from paths import data_path

from . import capital_guard, node_map

#: Commit more than this share of the pot and focus mode is worth offering.
HIGH_SHARE = 0.6


def _path():
    return data_path("finance_lab/focus.json")


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {"on": False, "since": 0.0, "paused": [], "note": ""}


def _save(state: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def should_offer() -> Dict[str, Any]:
    """Is this a high-finance session? The warning the owner reads comes from here."""
    money = capital_guard.pot()
    share = 0.0 if money["total"] <= 0 else money["invested"] / money["total"]
    high = share >= HIGH_SHARE or money["total"] >= 10_000
    return {
        "high": bool(high),
        "share": round(share, 2),
        "invested": money["invested"],
        "total": money["total"],
        "why": (f"${money['invested']:,.0f} of the AI's ${money['total']:,.0f} is committed "
                f"({share * 100:.0f}%). At that size everything else on this PC is a distraction."
                if high else "Nothing like enough is committed to need it."),
    }


def warning() -> Dict[str, Any]:
    """Exactly what entering would do, before it does it."""
    running = []
    try:
        import feature_catalog

        running = [row["label"] for row in feature_catalog.live_processes() if row["source"] != "thread"]
    except Exception:  # noqa: BLE001
        pass
    return {
        "title": "Give the whole machine to finance?",
        "stops": ["Improve autopilot", "Data Absorption", "Curiosity", "Big Kahuna training", "Scheduled jobs"],
        "keeps": ["Trading and its approvals", "The finance lab", "The chat, so you can still ask it things"],
        "running_now": running,
        "money": should_offer(),
        "reversible": "Leaving focus mode starts again exactly what it paused, and nothing else.",
        "real_money": capital_guard.settings()["mode"] == "real",
    }


def _try(label: str, action: Any, undo_label: str) -> Dict[str, Any] | None:
    """Run one pause, and remember how to undo it. A part that is not here is skipped."""
    try:
        action()
        return {"what": label, "undo": undo_label}
    except Exception:  # noqa: BLE001 - a missing feature is not an error here
        return None


def enter(reason: str = "") -> Dict[str, Any]:
    """Pause the rest of Nyx. Everything paused is written down."""
    state = _load()
    if state.get("on"):
        return {"ok": True, "already": True, **state}
    node_map.light("risk", "focus mode")
    paused: List[Dict[str, Any]] = []

    def add(row):
        if row:
            paused.append(row)

    # The shared switch first, when the background-jobs registry exists.
    def pause_all():
        import background_jobs

        background_jobs.pause_all(reason="finance focus")

    add(_try("Background jobs", pause_all, "background_jobs.resume"))

    def stop_improve():
        from improve_autopilot import AUTOPILOT

        AUTOPILOT.stop("finance focus")

    add(_try("Improve autopilot", stop_improve, "owner restarts it"))

    def pause_absorb():
        import absorb_engine

        absorb_engine.ENGINE.pause()

    add(_try("Data Absorption", pause_absorb, "absorb_engine.ENGINE.resume"))

    def quiet_curiosity():
        import curiosity

        curiosity.update_settings(study_alone=False)

    add(_try("Curiosity", quiet_curiosity, "curiosity.update_settings(study_alone=True)"))

    def pause_training():
        from identity0 import jobs

        jobs.pause_all()

    add(_try("Big Kahuna training", pause_training, "identity0.jobs.resume_all"))

    # And the trading side goes to always-on, since that is the point of focus mode.
    def always_on():
        from trading import autopilot

        autopilot.set_run_mode("always")

    add(_try("Trading set to 24/7", always_on, "trading.autopilot.set_run_mode('market')"))

    state = {"on": True, "since": time.time(), "paused": paused, "note": reason[:200]}
    _save(state)
    return {"ok": True, **state, "warning": warning()}


def leave() -> Dict[str, Any]:
    """Put back exactly what was taken away."""
    state = _load()
    if not state.get("on"):
        return {"ok": True, "on": False, "restored": []}
    restored: List[str] = []

    def resume_all():
        import background_jobs

        background_jobs.resume(reason="finance focus over")

    for row in state.get("paused", []):
        what = row.get("what")
        try:
            if what == "Background jobs":
                resume_all()
            elif what == "Data Absorption":
                import absorb_engine

                absorb_engine.ENGINE.resume()
            elif what == "Curiosity":
                import curiosity

                curiosity.update_settings(study_alone=True)
            elif what == "Big Kahuna training":
                from identity0 import jobs

                jobs.resume_all()
            elif what == "Trading set to 24/7":
                from trading import autopilot

                autopilot.set_run_mode("market")
            else:
                continue
            restored.append(str(what))
        except Exception:  # noqa: BLE001
            continue
    _save({"on": False, "since": 0.0, "paused": [], "note": ""})
    return {"ok": True, "on": False, "restored": restored,
            "note": "The Improve autopilot is left off on purpose — start it when you want it back."}


def state() -> Dict[str, Any]:
    """What the panel shows: on or off, since when, and what is paused."""
    current = _load()
    return {**current, "offer": should_offer(), "warning": warning() if not current.get("on") else None}


def background_status() -> List[Dict[str, Any]]:
    current = _load()
    if not current.get("on"):
        return []
    return [{"label": "Finance focus mode", "running": True, "status": "running",
             "detail": f"{len(current.get('paused', []))} other things paused"}]
