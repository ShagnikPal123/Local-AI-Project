"""Clap: sounds Nyx answers to when nobody is typing (Project Null N86).

The owner: "Add a feature to voice where if offline or away or when using the
background voice … a feature called clap. In here we can tell the AI a certain
gesture like clapping, whistling, a phrase, or something more which the AI
responds to and talks back. When first turning the voice on, regardless of mode
have it say, NYX here."

Two halves. The **sounds** are heard in the browser (`src/voice/clapDetector.ts`)
because that is where the microphone is, and it works with no internet: claps and
whistles are recognised from their shape, and anything else — a rhythm, a knock,
a spoken phrase — is taught by example and matched against what was taught. This
module holds the part that must survive a restart: what has been taught, when it
is allowed to listen, and what Nyx does when it hears it.

Nothing here records audio. A taught sound is kept as a short list of numbers
describing its shape, from which nothing can be played back or transcribed.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from paths import atomic_replace, data_path

#: How a gesture is recognised.
KINDS = ("clap", "double_clap", "whistle", "taught")

#: What Nyx does when it hears one.
ACTIONS = ("say", "listen", "status", "command")

#: When the ear is open. The owner asked for "offline or away or … background voice".
WHEN = ("away", "offline", "proto", "talk", "always")

MAX_GESTURES = 12
#: A taught sound is at most this many frames of 12 numbers — a shape, not a recording.
MAX_TEMPLATE_FRAMES = 120
TEMPLATE_WIDTH = 12

#: Said once when listening starts, whichever mode it is. Short, and not a butler.
GREETINGS = [
    "Nyx here. Listening.",
    "Nyx here — go ahead.",
    "Nyx here. I've got the mic.",
    "Nyx here, ears on.",
]


def _path():
    return data_path("voice_gestures.json")


def _default() -> Dict[str, Any]:
    return {
        "enabled": True,
        "greeting": {"enabled": True, "text": "", "when": "every"},   # every | first | off
        "sensitivity": 0.6,
        "gestures": [
            {"id": "clap2", "name": "Two claps", "kind": "double_clap", "enabled": True,
             "when": ["away", "offline", "proto"], "action": "listen",
             "say": "I'm here — what do you need?", "text": "", "template": [], "heard": 0, "last": 0.0},
            {"id": "whistle", "name": "Whistle", "kind": "whistle", "enabled": False,
             "when": ["away", "offline", "proto"], "action": "status",
             "say": "", "text": "", "template": [], "heard": 0, "last": 0.0},
        ],
    }


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _default()
    if not isinstance(data, dict) or not isinstance(data.get("gestures"), list):
        return _default()
    merged = _default()
    merged.update({k: v for k, v in data.items() if k in merged})
    merged["greeting"] = {**_default()["greeting"], **(data.get("greeting") or {})}
    return merged


def _write(data: Dict[str, Any]) -> Dict[str, Any]:
    target = _path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    atomic_replace(temp, target)
    return data


def state() -> Dict[str, Any]:
    """Everything the Clap panel and the listener need."""
    return _read()


def settings(changes: Dict[str, Any]) -> Dict[str, Any]:
    data = _read()
    if "enabled" in changes:
        data["enabled"] = bool(changes["enabled"])
    if "sensitivity" in changes:
        data["sensitivity"] = min(0.95, max(0.2, float(changes["sensitivity"])))
    greeting = changes.get("greeting")
    if isinstance(greeting, dict):
        if "enabled" in greeting:
            data["greeting"]["enabled"] = bool(greeting["enabled"])
        if "text" in greeting:
            data["greeting"]["text"] = str(greeting["text"]).strip()[:160]
        if greeting.get("when") in ("every", "first", "off"):
            data["greeting"]["when"] = greeting["when"]
    return _write(data)


def _clean_template(raw: Any) -> List[List[float]]:
    """A taught sound: frames of small numbers, and nothing else."""
    frames: List[List[float]] = []
    for frame in list(raw or [])[:MAX_TEMPLATE_FRAMES]:
        try:
            values = [round(float(v), 4) for v in list(frame)[:TEMPLATE_WIDTH]]
        except (TypeError, ValueError):
            continue
        if len(values) == TEMPLATE_WIDTH:
            frames.append(values)
    return frames


def _clean(gesture: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    base = existing or {"id": uuid.uuid4().hex[:8], "heard": 0, "last": 0.0, "template": []}
    name = str(gesture.get("name") or base.get("name") or "Sound").strip()[:60]
    kind = gesture.get("kind") or base.get("kind") or "taught"
    if kind not in KINDS:
        raise ValueError(f"A gesture is one of: {', '.join(KINDS)}.")
    action = gesture.get("action") or base.get("action") or "say"
    if action not in ACTIONS:
        raise ValueError(f"What it does must be one of: {', '.join(ACTIONS)}.")
    when = [w for w in (gesture.get("when") or base.get("when") or ["away", "offline", "proto"]) if w in WHEN]
    out = {
        **base,
        "name": name or "Sound",
        "kind": kind,
        "enabled": bool(gesture.get("enabled", base.get("enabled", True))),
        "when": when or ["away"],
        "action": action,
        "say": str(gesture.get("say", base.get("say", "")))[:300],
        "text": str(gesture.get("text", base.get("text", "")))[:600],
    }
    if "template" in gesture:
        out["template"] = _clean_template(gesture["template"])
    if out["kind"] == "taught" and not out["template"]:
        raise ValueError("Teach the sound first — make it three times so Nyx knows its shape.")
    if out["action"] == "command" and not out["text"].strip():
        raise ValueError("Say what Nyx should do when it hears this.")
    return out


def add(gesture: Dict[str, Any]) -> Dict[str, Any]:
    data = _read()
    if len(data["gestures"]) >= MAX_GESTURES:
        raise ValueError(f"That is {MAX_GESTURES} sounds already — remove one first.")
    clean = _clean(gesture)
    data["gestures"].append(clean)
    _write(data)
    return clean


def update(gesture_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    data = _read()
    for index, gesture in enumerate(data["gestures"]):
        if gesture["id"] == gesture_id:
            clean = _clean(changes, existing=dict(gesture))
            data["gestures"][index] = clean
            _write(data)
            return clean
    raise KeyError(gesture_id)


def remove(gesture_id: str) -> bool:
    data = _read()
    before = len(data["gestures"])
    data["gestures"] = [g for g in data["gestures"] if g["id"] != gesture_id]
    _write(data)
    return len(data["gestures"]) < before


def greeting(first_today: bool = False) -> str:
    """What it says when listening starts. Empty when the owner turned it off."""
    data = _read()
    setting = data["greeting"]
    if not setting["enabled"] or setting["when"] == "off":
        return ""
    if setting["when"] == "first" and not first_today:
        return ""
    if setting["text"].strip():
        return setting["text"].strip()
    return GREETINGS[int(time.time() // 60) % len(GREETINGS)]


def _spoken_status() -> str:
    """A few words about what is going on, for the "tell me where things are" gesture."""
    parts = [f"It's {time.strftime('%I:%M %p').lstrip('0').lower()}."]
    try:
        from turn_registry import TURNS

        running = [t for t in TURNS.active(include_recent=False)]
        parts.append(f"{len(running)} thing{'s' if len(running) != 1 else ''} running." if running else "Nothing running.")
    except Exception:  # pragma: no cover - status is best effort
        pass
    try:
        from trading import autopilot

        run = autopilot.run_status()
        if run.get("enabled"):
            parts.append(f"The AI trader is {run['summary'][0].lower()}{run['summary'][1:]}")
    except Exception:  # pragma: no cover
        pass
    return " ".join(parts)


def heard(gesture_id: str) -> Dict[str, Any]:
    """Record that a gesture fired, and say what Nyx should do about it.

    Returns ``{"gesture", "speak", "action", "text"}`` — the browser speaks
    ``speak`` and carries out ``action`` (start listening, send ``text`` to the
    chat, or nothing).
    """
    data = _read()
    found: Optional[Dict[str, Any]] = None
    for gesture in data["gestures"]:
        if gesture["id"] == gesture_id:
            gesture["heard"] = int(gesture.get("heard") or 0) + 1
            gesture["last"] = time.time()
            found = gesture
            break
    if found is None:
        raise KeyError(gesture_id)
    _write(data)

    speak = str(found.get("say") or "").strip()
    if found["action"] == "status":
        speak = (speak + " " if speak else "") + _spoken_status()
    elif found["action"] == "listen" and not speak:
        speak = "I'm listening."
    return {"gesture": found, "speak": speak[:400], "action": found["action"], "text": found.get("text", "")}


_WORD_RE = re.compile(r"[a-z0-9']+")


def suggest_name(text: str) -> str:
    """A tidy name for a taught sound, from whatever the owner typed."""
    words = _WORD_RE.findall((text or "").lower())[:4]
    return " ".join(words).title() or "My Sound"
