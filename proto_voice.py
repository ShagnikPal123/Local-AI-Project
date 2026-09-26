"""Proto Voice: always listening, and allowed to do things.

The owner (2026-09-22): "For the voice add another slider or part of the voice
listening and talking where it is called proto voice. It always listens as allows
the ai to understand and do things just better. This model allows it to turn on,
off the computer and itself, can navigate the computer and the app itself by
saying open files or open this tab in nyx… Maybe it can also add sub agents to
its chat and it acts as the manager giving every command. It can do simulations.
Basically free will but with voice."

How it is built:

* **Rules before models.** Every action comes from a pattern match on this PC —
  no model decides to shut anything down. A sentence that matches nothing is
  just a message for the chat.
* **Three tiers, deny by default.** `NOW` runs (open an app, a folder, a Nyx
  tab, volume, media, standby). `ASK` needs the owner to say yes, out loud or
  by clicking, and the request expires after 25 seconds (shutdown, restart,
  sleep, stopping Nyx, closing a program). `NEVER` is refused with a reason:
  typing a password, buying, sending mail, deleting files, running code.
* **Always listening is not always acting.** Out of standby it acts on anything
  that matches an action and sends the rest to the chat; in standby it only
  listens for its name. It goes to standby by itself when the owner says so, and
  wakes on "Nyx".

Two things the owner asked for that are *not* built, with the reason in the
answer it speaks:

* **Unlocking Windows with a spoken password.** The lock screen is a separate
  secure desktop; no program running as the owner can type into it, by design.
  Nyx also never stores a password. Windows Hello does this properly.
* **Turning the computer on.** Nothing on a PC that is off can hear anything.
  It can sleep, lock and restart, and it starts itself with Windows.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from paths import data_path

#: How long an "are you sure?" waits for a yes.
CONFIRM_SECONDS = 25.0

#: Tiers.
NOW, ASK, NEVER = "now", "ask", "never"

DEFAULTS: Dict[str, Any] = {
    #: Proto Voice may act at all (asked once, like Free Will).
    "allowed": False,
    #: Only listening for its name.
    "standby": False,
    #: What wakes it out of standby.
    "wake_words": ["nyx", "hey nyx", "okay nyx"],
    #: Say out loud what it is about to do.
    "speak_actions": True,
    #: Power actions (shutdown, restart, sleep) need a spoken yes.
    "confirm_power": True,
    #: It may bring sub-agents into the chat and give them work.
    "agents": True,
}

_lock = threading.Lock()
_settings: Optional[Dict[str, Any]] = None


def _path():
    return data_path("proto_voice.json")


def settings() -> Dict[str, Any]:
    global _settings
    if _settings is None:
        data: Dict[str, Any] = {}
        try:
            raw = json.loads(_path().read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, ValueError):
            data = {}
        _settings = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    return dict(_settings)


def update_settings(**changes: Any) -> Dict[str, Any]:
    global _settings
    current = settings()
    for key, value in changes.items():
        if key in DEFAULTS and value is not None:
            current[key] = value
    with _lock:
        _settings = current
        try:
            _path().write_text(json.dumps(current, indent=2), encoding="utf-8")
        except OSError:
            pass
    return dict(current)


# ---------------------------------------------------------------------------
# What was asked for
# ---------------------------------------------------------------------------


@dataclass
class Intent:
    """One thing to do, and how much permission it needs."""

    kind: str = "ask_chat"
    tier: str = NOW
    #: What it will say before or instead of acting.
    say: str = ""
    #: Whatever the action needs: an app name, a path, a tab id, a count.
    target: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)
    #: The words this came from.
    text: str = ""
    #: Set when the tier is NEVER.
    refusal: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "tier": self.tier, "say": self.say, "target": self.target,
                "extra": dict(self.extra), "text": self.text, "refusal": self.refusal}


#: Folders people ask for by name.
_FOLDERS = {
    "downloads": "%USERPROFILE%\\Downloads", "download": "%USERPROFILE%\\Downloads",
    "documents": "%USERPROFILE%\\Documents", "docs": "%USERPROFILE%\\Documents",
    "desktop": "%USERPROFILE%\\Desktop", "pictures": "%USERPROFILE%\\Pictures",
    "photos": "%USERPROFILE%\\Pictures", "music": "%USERPROFILE%\\Music",
    "videos": "%USERPROFILE%\\Videos", "home": "%USERPROFILE%",
    "recycle bin": "shell:RecycleBinFolder", "trash": "shell:RecycleBinFolder",
}
#: "open files" means the file manager.
_FILE_MANAGER = {"files", "file explorer", "explorer", "finder", "my files", "file manager"}

#: Sites by name, so "open youtube" does not become a web search.
_SITES = {
    "youtube": "https://www.youtube.com", "gmail": "https://mail.google.com",
    "google": "https://www.google.com", "github": "https://github.com",
    "drive": "https://drive.google.com", "calendar": "https://calendar.google.com",
    "maps": "https://maps.google.com", "reddit": "https://www.reddit.com",
    "twitter": "https://twitter.com", "x": "https://twitter.com",
    "instagram": "https://www.instagram.com", "netflix": "https://www.netflix.com",
    "amazon": "https://www.amazon.com", "wikipedia": "https://en.wikipedia.org",
    "chatgpt": "https://chat.openai.com", "claude": "https://claude.ai",
}

_NEVER_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(my |the )?(password|passcode|pin|card number|credit card|cvv|social security)\b", re.I),
     "I will not type a password or a card number. The lock screen is a separate secure desktop that no "
     "program can type into anyway — Windows Hello is the way to do this."),
    (re.compile(r"\b(unlock|log ?in to|sign in to)\b.*\b(computer|pc|windows|machine)\b", re.I),
     "I can't unlock Windows. The lock screen runs on its own secure desktop that nothing running as you "
     "can reach, and I never keep your password. Windows Hello does this properly."),
    (re.compile(r"\b(buy|purchase|order|pay|transfer|send money|wire)\b", re.I),
     "I don't spend money by voice. Tell me what you want and I'll get it ready for you to confirm yourself."),
    (re.compile(r"\b(send|fire off)\b.*\b(email|e-mail|message|text)\b", re.I),
     "I'll write it and leave it as a draft — sending is yours to press."),
    (re.compile(r"\b(delete|wipe|format|erase)\b.*\b(drive|disk|everything|all my|system32|windows)\b", re.I),
     "I won't delete that by voice."),
]

_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "a": 1, "an": 1, "another": 1, "a couple of": 2, "a few": 3}


def _count_in(text: str) -> int:
    match = re.search(r"\b(\d{1,2})\b", text)
    if match:
        return max(1, min(8, int(match.group(1))))
    for word, value in _WORD_NUMBERS.items():
        if re.search(rf"\b{re.escape(word)}\b", text, re.I):
            return value
    return 1


def strip_wake(text: str) -> Tuple[str, bool]:
    """Take "Nyx," off the front. Returns (rest, was_addressed)."""
    cleaned = (text or "").strip()
    for wake in sorted(settings()["wake_words"], key=len, reverse=True):
        pattern = re.compile(rf"^\s*(hey\s+|ok(?:ay)?\s+)?{re.escape(wake)}\b[\s,.!:-]*", re.I)
        if pattern.match(cleaned):
            return pattern.sub("", cleaned).strip(), True
    return cleaned, False


def interpret(text: str, tabs: Optional[List[Dict[str, str]]] = None) -> Intent:
    """What the owner asked for, from patterns only — no model decides to act."""
    raw = (text or "").strip()
    body, addressed = strip_wake(raw)
    low = body.lower().strip(" .!?,")
    if not low:
        return Intent(kind="nothing", text=raw)

    for pattern, reason in _NEVER_PATTERNS:
        if pattern.search(low):
            return Intent(kind="refused", tier=NEVER, say=reason, refusal=reason, text=raw)

    # --- Nyx itself ---------------------------------------------------------------
    if re.search(r"\b(go to sleep|stop listening|standby|that'?s all for now|quiet mode)\b", low):
        return Intent(kind="standby", say="Going quiet. Say my name when you want me.", text=raw)
    if re.search(r"\b(wake up|start listening|i'?m back|are you there)\b", low):
        return Intent(kind="wake", say="I'm here.", text=raw)
    if re.search(r"\b(turn|shut) (yourself|nyx) (off|down)\b|\bclose nyx\b|\bquit nyx\b", low):
        return Intent(kind="nyx_off", tier=ASK, say="Stop Nyx? Say yes and I'll shut myself down.", text=raw)

    # --- the computer -------------------------------------------------------------
    if re.search(r"\block (the )?(screen|computer|pc)\b|\block up\b", low):
        return Intent(kind="lock", say="Locking the screen.", text=raw)
    if re.search(r"\b(go to sleep|sleep)\b.*\b(computer|pc|machine)\b|\bput the (computer|pc) to sleep\b", low):
        return Intent(kind="sleep", tier=ASK, say="Put the computer to sleep? Say yes.", text=raw)
    if re.search(r"\b(shut ?down|turn off|power off)\b.*\b(computer|pc|machine|windows)?\b", low) and \
            re.search(r"\b(shut ?down|turn off|power off)\b", low) and "nyx" not in low and "yourself" not in low:
        return Intent(kind="shutdown", tier=ASK,
                      say="Shut the computer down? Say yes and it goes down in thirty seconds.", text=raw)
    if re.search(r"\b(restart|reboot)\b.*\b(computer|pc|machine|windows)\b|\breboot\b", low):
        return Intent(kind="restart", tier=ASK, say="Restart the computer? Say yes.", text=raw)
    if re.search(r"\bturn (the )?(computer|pc|machine) on\b|\bwake (the )?(computer|pc)\b", low):
        return Intent(kind="cannot_power_on", tier=NEVER, text=raw,
                      say="Nothing on the PC can hear me while it is off, so I can't turn it on. I can lock it, "
                          "sleep it or restart it, and I start myself with Windows.",
                      refusal="A powered-off PC has nothing listening.")

    # --- volume and media ---------------------------------------------------------
    if re.search(r"\b(mute|unmute|volume|louder|quieter|turn it (up|down))\b", low):
        if "unmute" in low:
            return Intent(kind="volume", say="Sound back on.", extra={"mute": "off"}, text=raw)
        if "mute" in low:
            return Intent(kind="volume", say="Muted.", extra={"mute": "on"}, text=raw)
        number = re.search(r"\b(\d{1,3})\s*(percent|%)?\b", low)
        if number:
            return Intent(kind="volume", say=f"Volume {number.group(1)}.",
                          extra={"percent": int(number.group(1))}, text=raw)
        up = bool(re.search(r"\b(up|louder|higher|increase)\b", low))
        return Intent(kind="volume", say="Louder." if up else "Quieter.", extra={"step": 10 if up else -10}, text=raw)
    if re.search(r"\b(play|pause|next track|skip|previous track|stop the music)\b", low):
        key = "next" if re.search(r"\b(next|skip)\b", low) else "previous" if "previous" in low else "play_pause"
        return Intent(kind="media", say="", extra={"key": key}, text=raw)

    # --- dictation ("open notes and type what I say") ------------------------------
    dictate = re.search(r"\b(take notes|write this down|type what i say|start typing|dictate)\b", low)
    open_notes = re.search(r"\bopen (notes?|notepad|word|a document)\b.*\b(and|then)\b.*\b(typ(e|ing)|writ(e|ing)|dictat)", low)
    if dictate or open_notes:
        target = "notepad"
        if re.search(r"\bword\b", low):
            target = "winword"
        rest = re.sub(r".*\b(type what i say|start typing|take notes|write this down|dictate)\b", "", low).strip(" .,:")
        return Intent(kind="dictate", say="Ready — I'll type what you say.", target=target,
                      extra={"first": rest}, text=raw)

    # --- Nyx's own tabs -----------------------------------------------------------
    tab = _tab_in(low, tabs or [])
    if tab:
        return Intent(kind="open_tab", say=f"Opening {tab['label']}.", target=str(tab["id"]), text=raw)

    # --- the file manager, folders, apps, sites ------------------------------------
    opener = re.search(r"\b(open|launch|start|show me|bring up|go to)\b\s+(.*)$", low)
    if opener:
        what = opener.group(2).strip(" .!?").removeprefix("the ").removeprefix("my ").strip()
        if what in _FILE_MANAGER:
            return Intent(kind="open_path", say="Opening your files.", target="%USERPROFILE%", text=raw)
        for name, path in _FOLDERS.items():
            if what == name or what == f"{name} folder":
                return Intent(kind="open_path", say=f"Opening {name}.", target=path, text=raw)
        site = _SITES.get(what.removesuffix(".com"))
        if site:
            return Intent(kind="open_url", say=f"Opening {what}.", target=site, text=raw)
        url = re.match(r"^(https?://\S+|[\w-]+\.(com|org|net|io|dev|ai|gov|edu)(/\S*)?)$", what)
        if url:
            address = what if what.startswith("http") else f"https://{what}"
            return Intent(kind="open_url", say=f"Opening {what}.", target=address, text=raw)
        if what and len(what) < 40:
            return Intent(kind="open_app", say=f"Opening {what}.", target=what, text=raw)

    if re.search(r"\b(close|quit|kill)\b\s+(.*)$", low):
        what = re.sub(r".*\b(close|quit|kill)\b\s+", "", low).strip(" .!?")
        if what and "nyx" not in what:
            return Intent(kind="close_app", tier=ASK, say=f"Close {what}? Say yes.", target=what, text=raw)

    # --- agents -------------------------------------------------------------------
    if settings()["agents"]:
        agent = re.search(r"\b(bring in|add|get me|spin up|call in)\b\s+(.*?)\b(agents?|sub ?agents?)?\s*$", low)
        if agent and re.search(r"\bagents?\b|\bsub ?agents?\b|\b(coder|designer|researcher|writer|finance|tester)s?\b", low):
            return Intent(kind="agents", say="", target=agent.group(2).strip(), extra={"count": _count_in(low)}, text=raw)
        tell = re.search(r"\btell (the )?(office|team|coders?|managers?|everyone)\b\s*(.*)$", low)
        if tell:
            return Intent(kind="office", say="", target=tell.group(2).strip(), extra={"message": tell.group(3).strip()}, text=raw)

    # --- simulations ---------------------------------------------------------------
    if re.search(r"\b(simulate|what would happen if|dry ?run|practice run|walk me through what you'd do)\b", low):
        return Intent(kind="simulate", say="", target=body, text=raw)

    return Intent(kind="ask_chat", text=raw, extra={"addressed": addressed})


def _tab_in(low: str, tabs: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """"open the finance tab", "go to settings in nyx"."""
    if not re.search(r"\b(open|go to|switch to|show)\b", low):
        return None
    wants_tab = "tab" in low or "in nyx" in low or "nyx" in low
    for tab in tabs:
        label = str(tab.get("label", "")).lower()
        ident = str(tab.get("id", "")).lower()
        if not label and not ident:
            continue
        for name in {label, ident}:
            if name and re.search(rf"\b{re.escape(name)}\b", low):
                if wants_tab or name == ident:
                    return {"id": str(tab.get("id", "")), "label": str(tab.get("label") or tab.get("id"))}
    return None


# ---------------------------------------------------------------------------
# Doing it
# ---------------------------------------------------------------------------


@dataclass
class Pending:
    intent: Intent
    at: float = field(default_factory=time.time)
    token: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


_pending: Dict[str, Pending] = {}

_YES = re.compile(r"^\s*(yes|yeah|yep|yup|do it|go ahead|confirm|ok|okay|please do|sure)\b", re.I)
_NO = re.compile(r"^\s*(no|nope|stop|cancel|don'?t|never mind|forget it)\b", re.I)


def _say(text: str) -> None:
    """Speak, when speaking is on. Never raises."""
    if not text or not settings()["speak_actions"]:
        return
    try:
        import tts

        tts.say(text, role="reply")
    except Exception:  # pragma: no cover - a silent Nyx still works
        pass


def _publish(event: str, **payload: Any) -> None:
    try:
        from agent_events import publish_ui

        publish_ui(event, **payload)
    except Exception:  # pragma: no cover
        pass


def handle(text: str, *, session_id: str = "default", tabs: Optional[List[Dict[str, str]]] = None,
           chat_id: str = "") -> Dict[str, Any]:
    """One heard sentence, from listening to done.

    Returns ``{"kind", "said", "done", "needs_confirm", "token", "to_chat"}``.
    ``to_chat`` is True when the words were not a command and belong in the chat.
    """
    config = settings()
    body, addressed = strip_wake(text or "")

    # An answer to a question Nyx asked a moment ago.
    answer = _resolve_pending(session_id, text or "")
    if answer is not None:
        return answer

    if not config["allowed"]:
        return {"kind": "not_allowed", "said": "", "done": False, "needs_confirm": False, "to_chat": False,
                "note": "Proto Voice has not been allowed yet."}

    if config["standby"]:
        if not addressed:
            return {"kind": "standby", "said": "", "done": False, "needs_confirm": False, "to_chat": False}
        update_settings(standby=False)
        _publish("voice.proto", standby=False)

    intent = interpret(text or "", tabs)
    if intent.kind == "nothing":
        return {"kind": "nothing", "said": "", "done": False, "needs_confirm": False, "to_chat": False}
    if intent.kind == "ask_chat":
        # Not a command. In standby-free listening, only speech aimed at Nyx becomes a message.
        return {"kind": "ask_chat", "said": "", "done": False, "needs_confirm": False,
                "to_chat": True, "text": body}
    if intent.tier == NEVER:
        _say(intent.say)
        return {"kind": intent.kind, "said": intent.say, "done": False, "needs_confirm": False,
                "to_chat": False, "refused": intent.refusal}
    if intent.tier == ASK and config["confirm_power"]:
        pending = Pending(intent)
        _pending[session_id] = pending
        _say(intent.say)
        _publish("voice.proto", asking=intent.say, kind=intent.kind, token=pending.token)
        return {"kind": intent.kind, "said": intent.say, "done": False, "needs_confirm": True,
                "token": pending.token, "to_chat": False}
    return _do(intent, chat_id=chat_id)


def _resolve_pending(session_id: str, text: str) -> Optional[Dict[str, Any]]:
    pending = _pending.get(session_id)
    if pending is None:
        return None
    if time.time() - pending.at > CONFIRM_SECONDS:
        _pending.pop(session_id, None)
        return None
    if _NO.match(text):
        _pending.pop(session_id, None)
        _say("Left it alone.")
        return {"kind": "cancelled", "said": "Left it alone.", "done": False, "needs_confirm": False, "to_chat": False}
    if _YES.match(text):
        _pending.pop(session_id, None)
        return _do(pending.intent)
    return None


def confirm(token: str, *, session_id: str = "default", yes: bool = True) -> Dict[str, Any]:
    """The owner pressed the button instead of saying yes."""
    pending = _pending.get(session_id)
    if pending is None or pending.token != token:
        return {"kind": "expired", "said": "", "done": False, "needs_confirm": False, "to_chat": False}
    _pending.pop(session_id, None)
    if not yes:
        return {"kind": "cancelled", "said": "", "done": False, "needs_confirm": False, "to_chat": False}
    return _do(pending.intent)


#: Each action, so the table can be read at a glance. Every one returns what to say.
def _do(intent: Intent, *, chat_id: str = "") -> Dict[str, Any]:
    handler: Callable[[Intent, str], str] = _ACTIONS.get(intent.kind, _unknown)
    try:
        said = handler(intent, chat_id)
        done = True
    except Exception as error:  # noqa: BLE001 - a failed action is spoken, never raised at the microphone
        said = f"That didn't work: {type(error).__name__}."
        done = False
    if intent.say and intent.tier == NOW and intent.kind not in {"media", "agents", "office", "simulate"}:
        _say(intent.say)
    elif said:
        _say(said)
    _publish("voice.proto", did=intent.kind, said=said or intent.say)
    return {"kind": intent.kind, "said": said or intent.say, "done": done, "needs_confirm": False, "to_chat": False}


def _machine():
    import machine_tools

    return machine_tools


def _open_app(intent: Intent, _chat: str) -> str:
    return _machine().open_app(intent.target)


def _open_path(intent: Intent, _chat: str) -> str:
    import os

    return _machine().open_path(os.path.expandvars(intent.target))


def _open_url(intent: Intent, _chat: str) -> str:
    return _machine().open_url(intent.target)


def _close_app(intent: Intent, _chat: str) -> str:
    return _machine().kill_process(intent.target)


def _lock_screen(_intent: Intent, _chat: str) -> str:
    return _machine().lock_screen()


def _sleep(_intent: Intent, _chat: str) -> str:
    return _machine().system_power("sleep")


def _shutdown(_intent: Intent, _chat: str) -> str:
    return _machine().system_power("shutdown", 30)


def _restart(_intent: Intent, _chat: str) -> str:
    return _machine().system_power("restart", 30)


def _volume(intent: Intent, _chat: str) -> str:
    extra = intent.extra
    if extra.get("mute"):
        return _machine().set_volume(mute=extra["mute"])
    if "percent" in extra:
        return _machine().set_volume(percent=int(extra["percent"]))
    step = int(extra.get("step", 0))
    for _ in range(abs(step) // 2):
        _machine().media_key("volume_up" if step > 0 else "volume_down")
    return ""


def _media(intent: Intent, _chat: str) -> str:
    return _machine().media_key(str(intent.extra.get("key", "play_pause")))


def _open_tab(intent: Intent, _chat: str) -> str:
    _publish("ui.open_tab", tab_id=intent.target)
    return ""


def _standby(_intent: Intent, _chat: str) -> str:
    update_settings(standby=True)
    _publish("voice.proto", standby=True)
    return ""


def _wake(_intent: Intent, _chat: str) -> str:
    update_settings(standby=False)
    _publish("voice.proto", standby=False)
    return ""


def _nyx_off(_intent: Intent, _chat: str) -> str:
    _say("Shutting down. See you.")
    threading.Timer(1.5, _stop_engine).start()
    return ""


def _stop_engine() -> None:
    """The launcher's own stop hook, the same one the tray's Quit uses."""
    try:
        import server

        stop = server.ENGINE_HOOKS.get("stop")
        if callable(stop):
            stop()
            return
    except Exception:  # pragma: no cover
        pass
    try:
        import os
        import signal

        os.kill(os.getpid(), signal.SIGTERM)
    except Exception:  # pragma: no cover
        pass


def _dictate(intent: Intent, _chat: str) -> str:
    """Hand over to the hands-off bar's dictation (c69db1's super_control)."""
    try:
        import super_control

        result = super_control.start_dictation(intent.target or "notepad", str(intent.extra.get("first", "")))
        note = result.get("note") if isinstance(result, dict) else ""
        return str(note or "")
    except ImportError:
        said = _machine().open_app(intent.target or "notepad")
        return f"{said} Dictation into the window is not installed yet, so say it and I'll put it in the chat."


def _agents(intent: Intent, chat_id: str) -> str:
    """Bring sub-agents into this chat, with Proto Voice as the manager."""
    count = int(intent.extra.get("count", 1))
    wanted = (intent.target or "coder").strip()
    try:
        from agent_dispatch import DISPATCHES

        items = [{"agent": wanted, "task": ""} for _ in range(count)]
        view = DISPATCHES.start(items, chat_id=chat_id or "", origin="nyx",
                                context="Brought in by voice; the owner is speaking and will say what to do next.")
        labels = ", ".join(str(i.get("label", wanted)) for i in view.get("instances", [])) or wanted
        return f"{labels} {'is' if count == 1 else 'are'} in this chat. Tell me what they should do."
    except Exception as error:  # noqa: BLE001 - the reason is spoken
        return f"I couldn't bring in {wanted}: {error}"


def _office(intent: Intent, _chat: str) -> str:
    try:
        import office.api as office_api

        result = office_api.say(str(intent.extra.get("message", "")), to=intent.target)
        return str(result.get("note") or "Passed it on.")
    except Exception:
        return "There is no office running to tell."


def _simulate(intent: Intent, _chat: str) -> str:
    """A dry run: say what it would do, and change nothing."""
    plan = describe_plan(intent.target)
    return plan


def describe_plan(request: str) -> str:
    """The steps Proto Voice *would* take, without taking any of them."""
    intent = interpret(request)
    if intent.kind in {"ask_chat", "nothing", "simulate"}:
        return "That one goes to the chat rather than to the computer, so nothing would happen on this PC."
    tier = {NOW: "straight away", ASK: "after you say yes", NEVER: "not at all"}[intent.tier]
    what = {
        "open_app": f"open {intent.target}", "open_path": f"open the folder {intent.target}",
        "open_url": f"open {intent.target} in the browser", "open_tab": f"switch Nyx to {intent.target}",
        "close_app": f"close {intent.target}", "lock": "lock the screen", "sleep": "put the PC to sleep",
        "shutdown": "shut the PC down", "restart": "restart the PC", "nyx_off": "stop Nyx",
        "volume": "change the volume", "media": "press a media key", "dictate": "start typing what you say",
        "agents": f"bring in {intent.extra.get('count', 1)} {intent.target or 'agent'}",
        "office": "pass a message to the office", "standby": "go quiet", "wake": "start listening again",
    }.get(intent.kind, intent.kind.replace("_", " "))
    return f"I would {what}, {tier}. Nothing has happened."


def _unknown(intent: Intent, _chat: str) -> str:
    return f"I don't have an action for {intent.kind}."


_ACTIONS: Dict[str, Callable[[Intent, str], str]] = {
    "open_app": _open_app, "open_path": _open_path, "open_url": _open_url, "close_app": _close_app,
    "lock": _lock_screen, "sleep": _sleep, "shutdown": _shutdown, "restart": _restart, "volume": _volume,
    "media": _media, "open_tab": _open_tab, "standby": _standby, "wake": _wake, "nyx_off": _nyx_off,
    "dictate": _dictate, "agents": _agents, "office": _office, "simulate": _simulate,
}


def state() -> Dict[str, Any]:
    """What the dock shows: the switches, and whether something is waiting for a yes."""
    config = settings()
    asking = ""
    token = ""
    for pending in _pending.values():
        if time.time() - pending.at <= CONFIRM_SECONDS:
            asking, token = pending.intent.say, pending.token
            break
    return {"settings": config, "asking": asking, "token": token,
            "can_act": bool(config["allowed"]) and not config["standby"]}
