"""The small, stable surface the rest of Nyx calls.

Other parts of the app (voice, Proto Voice, a chat turn, a tool) should reach an office through here and nowhere
else: everything below this module is free to change. Nothing raises — a caller that is only *trying* to reach
an office should get an answer it can read out, not an exception.
"""

from __future__ import annotations

from typing import Any, Dict, List

from office import engine as engine_module
from office import library


def running() -> str:
    """The office that is working right now, or ""."""
    try:
        return engine_module.ENGINE.running_office()
    except Exception:  # noqa: BLE001
        return ""


def offices() -> List[Dict[str, Any]]:
    """Every office file, newest first."""
    try:
        rows = [i.as_dict() for i in library.scan() if i.kind == "office"]
        return sorted(rows, key=lambda r: -float(r.get("updated_at") or 0))
    except Exception:  # noqa: BLE001
        return []


def latest_office_id() -> str:
    rows = offices()
    return str(rows[0]["id"]) if rows else ""


def say(text: str, *, to: str = "", office_id: str = "") -> Dict[str, Any]:
    """Send something to an office: the main chat by default, or to whoever ``to`` names.

    ``to`` takes the same plain words the targeted chat box does — "managers", "the coders in every group",
    "Coder #2", "the Frontend section". Returns at once; the office answers in its own tab.
    """
    body = (text or "").strip()
    if not body:
        return {"ok": False, "note": "Nothing to say."}
    target_office = office_id or running() or latest_office_id()
    if not target_office:
        return {"ok": False, "note": "There is no office yet — make one in the Office Space tab."}
    try:
        if to.strip():
            result = engine_module.ENGINE.target(target_office, body, selection=None)
            return {"ok": True, "office_id": target_office, "recipients": result.get("label", ""),
                    "note": f"Sent to {result.get('label', 'the office')}."}
        result = engine_module.ENGINE.say(target_office, body)
        return {"ok": True, "office_id": target_office, "recipients": "the top manager",
                "note": "The top manager has it." if not result.get("queued")
                        else "Passed to the top manager while the office works."}
    except Exception as error:  # noqa: BLE001 - callers read this out loud; never throw at them
        return {"ok": False, "office_id": target_office, "note": str(error)[:300]}


def summary() -> Dict[str, Any]:
    """One line's worth of state for a status line or a spoken answer."""
    office_id = running()
    if not office_id:
        rows = offices()
        return {"running": False, "offices": len(rows),
                "note": f"{len(rows)} office file(s); none working right now." if rows else "No offices yet."}
    try:
        snapshot = engine_module.ENGINE.snapshot(office_id)
        counts = snapshot["office"]["counts"]
        return {"running": True, "office_id": office_id, "name": snapshot["office"]["name"],
                "phase": snapshot["office"]["phase"], "counts": counts,
                "note": (f"{snapshot['office']['name']}: {counts['working']} of {counts['agents']} agents working, "
                         f"{counts['tasks_done']} of {counts['tasks']} tasks done.")}
    except Exception as error:  # noqa: BLE001
        return {"running": True, "office_id": office_id, "note": str(error)[:200]}


__all__ = ["say", "running", "offices", "latest_office_id", "summary"]
