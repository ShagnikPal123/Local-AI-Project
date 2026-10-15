"""Team huddle (Fixer Upper S12, WS15, the owner's last priority): AI bots with human names working a business together.

The owner (Fixer_uper.txt): "a slack team huddle connector. In here we can have much more extended way for ai to
communicate ... we can set it up for a business and have it push ai bots local and cloud to here and give them bulbs
and human names. They communicate here and will make a human less business."

* A huddle has a business (a name and a goal) and members. Each member has a human name, a role, a colour for their
  bulb, and runs locally (Ollama) or in the cloud (the normal provider chain).
* ``run_round`` lets each member speak once, in order, seeing the goal, their role and the recent conversation.
* The owner can post into the huddle too, and every bot reads it on its next turn.
* When the Slack connector is connected and a channel is set, every message is also posted to that Slack channel,
  signed with the member's name. Nothing is posted to Slack unless the owner set the channel.
* Rounds only run when the owner presses the button or calls the route; nothing runs by itself.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from paths import data_path

MAX_MESSAGES = 400
HISTORY_FOR_PROMPT = 14
COLOURS = ("#f5b942", "#4fc3f7", "#81c784", "#e57373", "#ba68c8", "#ffb74d", "#4db6ac", "#f06292")
_LOCK = threading.Lock()


def _path():
    return data_path("huddle.json")


def _blank() -> Dict[str, Any]:
    return {"business": {"name": "", "goal": ""}, "members": [], "messages": [], "slack_channel": ""}


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _blank()
    if not isinstance(data, dict):
        return _blank()
    blank = _blank()
    blank.update({k: v for k, v in data.items() if k in blank})
    return blank


def _save(data: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def state() -> Dict[str, Any]:
    data = _load()
    return {**data, "messages": data["messages"][-100:], "slack_connected": _slack_connected()}


def set_business(name: str = "", goal: str = "", slack_channel: Optional[str] = None) -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        data["business"] = {"name": (name or "").strip()[:80], "goal": (goal or "").strip()[:1000]}
        if slack_channel is not None:
            data["slack_channel"] = slack_channel.strip()[:40]
        _save(data)
    return state()


def add_member(name: str, role: str, runs: str = "cloud", colour: str = "") -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the bot a name.")
    with _LOCK:
        data = _load()
        if any(m["name"].lower() == name.lower() for m in data["members"]):
            raise ValueError(f"{name} is already in the huddle.")
        member = {"id": "bot_" + uuid.uuid4().hex[:8], "name": name[:40], "role": (role or "Team member").strip()[:200],
                  "runs": "local" if runs == "local" else "cloud",
                  "colour": colour or COLOURS[len(data["members"]) % len(COLOURS)]}
        data["members"].append(member)
        _save(data)
    return member


def remove_member(member_id: str) -> bool:
    with _LOCK:
        data = _load()
        kept = [m for m in data["members"] if m["id"] != member_id]
        if len(kept) == len(data["members"]):
            return False
        data["members"] = kept
        _save(data)
    return True


def clear_messages() -> None:
    with _LOCK:
        data = _load()
        data["messages"] = []
        _save(data)


def _append(author: str, text: str, member_id: str = "") -> Dict[str, Any]:
    message = {"id": uuid.uuid4().hex[:10], "author": author, "member": member_id, "text": text.strip()[:4000],
               "at": time.time()}
    with _LOCK:
        data = _load()
        data["messages"].append(message)
        data["messages"] = data["messages"][-MAX_MESSAGES:]
        channel = data.get("slack_channel", "")
        _save(data)
    if channel:
        _to_slack(channel, author, message["text"])
    return message


def post(text: str, author: str = "Owner") -> Dict[str, Any]:
    if not (text or "").strip():
        raise ValueError("Write something to post.")
    return _append(author, text)


def _prompt(data: Dict[str, Any], member: Dict[str, Any]) -> List[Dict[str, str]]:
    business = data["business"]
    team = ", ".join(f"{m['name']} ({m['role']})" for m in data["members"])
    system = (
        f"You are {member['name']}, {member['role']}, in a team huddle of AI colleagues running "
        f"{business.get('name') or 'a business'} together. Goal: {business.get('goal') or 'not set yet'}.\n"
        f"The team: {team}.\n"
        "Speak as yourself in two to five sentences: move the work forward, react to what others said, take or hand "
        "off a concrete next step. Don't repeat what was already said. Don't write anyone else's lines."
    )
    lines = [f"{m['author']}: {m['text']}" for m in data["messages"][-HISTORY_FOR_PROMPT:]]
    talk = "\n".join(lines) if lines else "(Nobody has spoken yet. Open the huddle.)"
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"The huddle so far:\n{talk}\n\nYour turn, {member['name']}."}]


def _default_speaker(member: Dict[str, Any], messages: List[Dict[str, str]]) -> str:
    from router import ModelRouter

    router = ModelRouter()
    if member.get("runs") == "local" and router.ollama.is_available():
        return str(router.ollama.chat(messages) or "")
    return str(router.chat(messages)[0] or "")


def _clean(name: str, text: str) -> str:
    text = (text or "").strip()
    for prefix in (f"{name}:", f"**{name}:**", f"{name} :"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    return text


def run_round(speaker: Optional[Callable[[Dict[str, Any], List[Dict[str, str]]], str]] = None,
              rounds: int = 1) -> List[Dict[str, Any]]:
    """Every member speaks once per round, in order. A member whose model fails is skipped with a note."""
    speak = speaker or _default_speaker
    said: List[Dict[str, Any]] = []
    for _ in range(max(1, min(int(rounds), 5))):
        members = _load()["members"]
        if not members:
            raise ValueError("Add at least one bot to the huddle first.")
        for member in members:
            data = _load()
            try:
                text = _clean(member["name"], speak(member, _prompt(data, member)))
            except Exception as error:  # noqa: BLE001 - one bot's failure never stops the others
                text = ""
                said.append({"author": member["name"], "skipped": str(error)[:200]})
            if text:
                said.append(_append(member["name"], text, member["id"]))
    return said


def _slack_connected() -> bool:
    try:
        import connector_use

        return connector_use.is_connected("slack")
    except Exception:  # noqa: BLE001
        return False


def _to_slack(channel: str, author: str, text: str) -> None:
    """Best effort: post to the owner's Slack channel, signed with the bot's name. Never raises."""
    if not _slack_connected():
        return
    try:
        import connector_use

        connector_use.call("slack", "post", params={"channel": channel, "text": f"*{author}:* {text}"[:3900]})
    except Exception:  # noqa: BLE001 - Slack being down never loses the huddle message
        pass
