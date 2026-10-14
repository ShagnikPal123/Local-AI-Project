"""Tell the owner when a chat is done, needs them, or wrote to them — on the PC and, when they are away, on the phone.

Owner (2026-10-13): "When a chat is done either on the top left, right or middle, or on the bottom right I want a
notification it's done, or a chat needs help, or a chat texts the user that something is done … Also using the new
phone numbers … which allows the user to be texted if they are done as well if the AI marks them as gone."

Four kinds of notice, each can be switched off on its own:
  done      a chat finished a turn that took a while (shorter ones are not worth a ping)
  help      a chat needs you: it asked a question, wants an approval, or stopped on an error
  message   a chat or avatar wrote to you on purpose (the ``notify_owner`` tool)
  schedule  a scheduled task ran

Three places a notice can go:
  toast     the small box in the app, in the corner the owner picked (top left / middle / right, bottom left / right)
  desktop   a Windows notification, for when the app is minimised or closed
  phone     a WhatsApp text to the owner's own phone: never / when away / always

"Away" is either the owner's own switch (``away = on``, also ``/away`` from the phone) or, on automatic, the owner
having done nothing in Nyx for ``away_minutes``. A chat the owner connected to WhatsApp always reaches the phone.

Nothing leaves this PC except a WhatsApp text to the one linked phone, and that stays off until the owner turns it on.
Delivery never raises and never waits: a notice is a convenience and must not cost the turn it is about.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from paths import data_path

log = logging.getLogger("nyx.notifications")

KINDS = ("done", "help", "message", "schedule")
POSITIONS = ("top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right")
PHONE_MODES = ("off", "away", "always")
AWAY_MODES = ("auto", "on", "off")
LEVELS = ("info", "ok", "warn", "error")
RECENT_KEEP = 30
#: The same notice twice within this many seconds is one notice (a turn that ends and an approval that times out).
DEDUPE_SECONDS = 4.0
_LEVEL_FOR = {"done": "ok", "help": "warn", "message": "info", "schedule": "info"}

DEFAULTS: Dict[str, Any] = {
    "position": "bottom-right",
    "kinds": {kind: True for kind in KINDS},
    "channels": {"toast": True, "desktop": False},
    "phone": "off",
    "away": "auto",
    "away_minutes": 10,
    "min_seconds": 15,
}

_lock = threading.RLock()
_recent_keys: Dict[str, float] = {}
_phone_times: List[float] = []
#: A hard ceiling on phone texts per hour, whatever the settings say.
PHONE_PER_HOUR = 12


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _path():
    return data_path("notifications.json")


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def _int(value: Any, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def settings() -> Dict[str, Any]:
    """What is saved, with every missing or invalid value replaced by its default."""
    saved = _read().get("settings") or {}
    kinds = saved.get("kinds") if isinstance(saved.get("kinds"), dict) else {}
    channels = saved.get("channels") if isinstance(saved.get("channels"), dict) else {}
    position = saved.get("position")
    return {
        "position": position if position in POSITIONS else DEFAULTS["position"],
        "kinds": {kind: bool(kinds.get(kind, True)) for kind in KINDS},
        "channels": {name: bool(channels.get(name, default)) for name, default in DEFAULTS["channels"].items()},
        "phone": saved.get("phone") if saved.get("phone") in PHONE_MODES else DEFAULTS["phone"],
        "away": saved.get("away") if saved.get("away") in AWAY_MODES else DEFAULTS["away"],
        "away_minutes": _int(saved.get("away_minutes"), DEFAULTS["away_minutes"], 1, 24 * 60),
        "min_seconds": _int(saved.get("min_seconds"), DEFAULTS["min_seconds"], 0, 3600),
    }


def update(changes: Dict[str, Any]) -> Dict[str, Any]:
    """Change some settings; anything that is not a valid value for its setting is refused, not guessed at."""
    current = settings()
    if "position" in changes:
        if changes["position"] not in POSITIONS:
            raise ValueError(f"Pick a corner: {', '.join(POSITIONS)}.")
        current["position"] = changes["position"]
    for key, allowed in (("phone", PHONE_MODES), ("away", AWAY_MODES)):
        if key in changes:
            if changes[key] not in allowed:
                raise ValueError(f"{key} is one of: {', '.join(allowed)}.")
            current[key] = changes[key]
    for key, low, high in (("away_minutes", 1, 24 * 60), ("min_seconds", 0, 3600)):
        if key in changes:
            current[key] = _int(changes[key], current[key], low, high)
    for group, names in (("kinds", KINDS), ("channels", tuple(DEFAULTS["channels"]))):
        if isinstance(changes.get(group), dict):
            unknown = [name for name in changes[group] if name not in names]
            if unknown:
                raise ValueError(f"Unknown {group[:-1]}: {', '.join(map(str, unknown))}.")
            current[group] = {**current[group], **{name: bool(value) for name, value in changes[group].items()}}
    with _lock:
        data = _read()
        data["settings"] = current
        _write(data)
    _announce()
    return current


def _announce() -> None:
    """Tell every open window, so a new corner takes effect without a reload."""
    try:
        from agent_events import publish_ui

        publish_ui("notifications.settings", settings=settings())
    except Exception:  # noqa: BLE001
        pass


def is_away(now: Optional[float] = None) -> bool:
    """Whether the owner counts as gone: their own switch, or (on automatic) idle for ``away_minutes``."""
    current = settings()
    if current["away"] == "on":
        return True
    if current["away"] == "off":
        return False
    try:
        import presence

        return presence.idle_seconds(now) >= current["away_minutes"] * 60
    except Exception:  # noqa: BLE001
        return False


def set_away(mode: str) -> Dict[str, Any]:
    """The owner's switch: ``on`` (I am gone: text me), ``off``, or ``auto`` (go by how long I have been idle)."""
    return update({"away": mode})


# ---------------------------------------------------------------------------
# Delivery (each replaced in tests; none may raise)
# ---------------------------------------------------------------------------


def _deliver_toast(kind: str, title: str, text: str, level: str, chat_id: str) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("notify", text=text[:300], level=level, kind=kind, title=title[:80], chat_id=chat_id)
    except Exception:  # noqa: BLE001
        log.info("toast not shown", exc_info=True)


def _deliver_desktop(title: str, text: str) -> None:
    def show() -> None:
        try:
            import machine_tools

            machine_tools.notify(title or "Nyx", text)
        except Exception:  # noqa: BLE001
            log.info("desktop notice not shown", exc_info=True)

    threading.Thread(target=show, name="nyx-desktop-notice", daemon=True).start()


def _deliver_phone(text: str, origin: str) -> bool:
    try:
        import whatsapp_link

        return whatsapp_link.push(text, origin=origin)
    except Exception:  # noqa: BLE001
        log.info("phone notice not sent", exc_info=True)
        return False


def _chat_linked_to_phone(chat_id: str) -> bool:
    if not chat_id:
        return False
    try:
        import whatsapp_link

        current = whatsapp_link._LINK
        return bool(current is not None and current.is_chat_linked(chat_id))
    except Exception:  # noqa: BLE001
        return False


def chat_title(chat_id: str) -> str:
    """The chat's name as the owner sees it; a plain fallback when it cannot be found."""
    try:
        import server

        for chat in server._shared_chat_store().summaries():
            if chat["id"] == chat_id:
                return str(chat.get("title") or "A chat")
    except Exception:  # noqa: BLE001
        pass
    return "A chat"


# ---------------------------------------------------------------------------
# Notifying
# ---------------------------------------------------------------------------


def _fresh(key: str, now: float) -> bool:
    """False when this exact notice was just sent."""
    with _lock:
        for old in [k for k, at in _recent_keys.items() if now - at > DEDUPE_SECONDS * 4]:
            _recent_keys.pop(old, None)
        if now - _recent_keys.get(key, float("-inf")) < DEDUPE_SECONDS:
            return False
        _recent_keys[key] = now
        return True


def _remember(entry: Dict[str, Any]) -> None:
    with _lock:
        data = _read()
        data["recent"] = ((data.get("recent") or []) + [entry])[-RECENT_KEEP:]
        _write(data)


def recent(limit: int = 20) -> List[Dict[str, Any]]:
    return list(_read().get("recent") or [])[-limit:][::-1]


def phone_wanted(kind: str, chat_id: str = "", urgent: bool = False, now: Optional[float] = None) -> bool:
    """Whether this notice should also be texted to the owner's phone.

    A chat the owner connected to WhatsApp always reaches it. Otherwise nothing is texted while the setting is "off"
    (unless the owner said they are gone); "always" texts everything; "away" texts when the owner is away, and an
    urgent notice from the AI counts as "now" but never overrides "off".
    """
    if chat_id and _chat_linked_to_phone(chat_id):
        return True
    current = settings()
    if current["phone"] == "off" and current["away"] != "on":
        return False
    if current["phone"] == "always" or urgent:
        return True
    return is_away(now)


def _phone_budget_ok(now: float) -> bool:
    """At most ``PHONE_PER_HOUR`` texts an hour, so a loop in a chat can never flood the owner's phone."""
    with _lock:
        _phone_times[:] = [t for t in _phone_times if now - t < 3600]
        if len(_phone_times) >= PHONE_PER_HOUR:
            return False
        _phone_times.append(now)
        return True


def notify(kind: str, text: str, *, title: str = "", chat_id: str = "", level: str = "", source: str = "",
           urgent: bool = False, now: Optional[float] = None) -> Dict[str, Any]:
    """Send one notice to the places the owner chose. Returns what happened (``sent`` lists the channels)."""
    if kind not in KINDS:
        raise ValueError(f"A notice is one of: {', '.join(KINDS)}.")
    text = " ".join(str(text or "").split())[:400]
    if not text:
        return {"sent": [], "skipped": "empty"}
    current = settings()
    if not current["kinds"][kind] and not urgent:
        return {"sent": [], "skipped": "switched off"}
    moment = time.time() if now is None else now
    if not _fresh(f"{kind}|{chat_id}|{text[:60]}", moment):
        return {"sent": [], "skipped": "just sent"}
    level = level if level in LEVELS else _LEVEL_FOR[kind]
    title = title or (chat_title(chat_id) if chat_id else "")
    sent: List[str] = []
    if current["channels"]["toast"]:
        _deliver_toast(kind, title, text, level, chat_id)
        sent.append("toast")
    if current["channels"]["desktop"]:
        _deliver_desktop(title or "Nyx", text)
        sent.append("desktop")
    if phone_wanted(kind, chat_id, urgent, moment) and _phone_budget_ok(moment):
        if _deliver_phone(f"{title}: {text}" if title else text, f"notice:{kind}"):
            sent.append("phone")
    _remember({"at": moment, "kind": kind, "title": title, "text": text, "chat_id": chat_id, "source": source,
               "sent": sent})
    return {"sent": sent}


def help_needed(summary: str, chat_id: str = "") -> Dict[str, Any]:
    """A chat is waiting on the owner (an approval, a question). Never raises."""
    try:
        return notify("help", f"Needs you: {summary}", chat_id=chat_id, source="approval")
    except Exception:  # noqa: BLE001
        return {"sent": [], "skipped": "error"}


def turn_finished(chat_id: str, state: str, reply: str = "", seconds: float = 0.0) -> Dict[str, Any]:
    """A chat turn on the PC ended. Called from the chat stream route; decides whether it deserves a notice.

    ``state`` is done, stopped (the owner pressed stop) or error. A turn that ends with a question card, or an error,
    needs the owner; a long turn that simply finished is "done"; a short one is not worth a ping.
    """
    try:
        if state == "stopped":
            return {"sent": [], "skipped": "stopped by the owner"}
        if state == "error":
            return notify("help", "It stopped on an error. Open it to see what happened.", chat_id=chat_id, source="turn")
        import question_cards

        if question_cards.BLOCK_RE.search(reply or ""):
            return notify("help", "It has a question for you.", chat_id=chat_id, source="turn")
        if seconds < settings()["min_seconds"]:
            return {"sent": [], "skipped": "short turn"}
        preview = " ".join((reply or "").split())[:140]
        return notify("done", "Done." + (f" {preview}" if preview else ""), chat_id=chat_id, source="turn")
    except Exception:  # noqa: BLE001 - a missed notice never costs the turn
        log.info("turn notice failed", exc_info=True)
        return {"sent": [], "skipped": "error"}


def task_ran(title: str, ok: bool, reply: str = "") -> Dict[str, Any]:
    """A scheduled task ran (scheduled.py). Never raises."""
    try:
        preview = " ".join((reply or "").split())[:140]
        return notify("schedule" if ok else "help", f"{title} " + ("ran." if ok else "did not work.") +
                      (f" {preview}" if preview else ""), title="Schedule", level="ok" if ok else "warn",
                      source="schedule")
    except Exception:  # noqa: BLE001
        return {"sent": [], "skipped": "error"}


# ---------------------------------------------------------------------------
# The tool the AI uses
# ---------------------------------------------------------------------------


def tool_notify_owner(text: str, title: str = "", urgent: bool = False) -> str:
    result = notify("message", text, title=title or "Nyx", source="tool", urgent=bool(urgent))
    if result.get("skipped"):
        return f"Nothing shown ({result['skipped']})."
    where = ", ".join(result["sent"]) or "nowhere (every channel is switched off)"
    return f"The owner was notified: {where}."


def register_notification_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register(
        "notify_owner",
        "Tell the owner something now: a box in the app and, when they are away or you mark it urgent, a text on their "
        "phone. Use it when a long job finishes, when you need them, or when they asked to be pinged. You CAN reach them "
        "this way from any chat; do not say you cannot.",
        [P("text", "string", "What to tell them, one or two sentences"),
         P("title", "string", "Who or what it is about, e.g. the task name", required=False),
         P("urgent", "boolean", "True to text their phone even if they are at the PC", required=False)],
        tool_notify_owner, category="general", label="Notifying you")
