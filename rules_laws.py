"""Rules and laws (Fixer Upper S12, WS15): numbered, nested and linked laws the bots must follow.

The owner (Fixer_uper.txt): "the ai assigns itself rules and the user can assign rules. It numbers and assigns to bots
to ensure they follow. In here it will be called rules and laws and can have nested or linked laws or cases. They help
limit the AI but these are user made and have a slider for how much interaction the AI has so it can make its own laws
it sees as needed."

* A law has a title and text, an optional parent (which nests it and gives it a number like 2.1), links to other laws,
  the bots it applies to ("*" means every bot), and optional tool patterns it forbids.
* A "case" is a worked example under a law, numbered the same way.
* The AI slider (0-100) sets how much the AI may add:
  - 0: none. The AI can't make laws.
  - 1-33: suggest. What the AI writes waits for the owner's approval.
  - 34-66: self-rules. What the AI writes takes effect, but it can't change or remove a law afterwards.
  - 67-100: lawmaker. The AI may also edit and remove its own laws.
  The AI can never edit or remove a law the owner wrote, at any level.
* Laws only ever narrow what a bot does. They are added to every turn (capped) and forbidden tools are refused at
  ``tools.call_tool``, beside the owner's mods.
"""

from __future__ import annotations

import fnmatch
import json
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from paths import data_path

CONTEXT_HEADER = "Rules and laws you must follow (numbered; nested ones refine their parent):"
MAX_CONTEXT_CHARS = 3000
KINDS = ("law", "case")
_LOCK = threading.Lock()


class LawError(ValueError):
    """A change the slider or the author rules do not allow."""


def _path():
    return data_path("rules_laws.json")


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def autonomy() -> int:
    try:
        return max(0, min(100, int(_load().get("autonomy", 25))))
    except (TypeError, ValueError):
        return 25


def level(value: Optional[int] = None) -> str:
    value = autonomy() if value is None else value
    if value <= 0:
        return "none"
    if value < 34:
        return "suggest"
    if value < 67:
        return "self"
    return "lawmaker"


def set_autonomy(value: int) -> int:
    with _LOCK:
        data = _load()
        data["autonomy"] = max(0, min(100, int(value)))
        _save(data)
    return data["autonomy"]


def _laws(data: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return [law for law in (data if data is not None else _load()).get("laws", []) if isinstance(law, dict)]


def numbered() -> List[Dict[str, Any]]:
    """Every law with its number ("2.1") and depth, in tree order."""
    laws = _laws()
    ids = {law["id"] for law in laws}
    children: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for law in laws:
        parent = law.get("parent") if law.get("parent") in ids else None
        children.setdefault(parent, []).append(law)
    out: List[Dict[str, Any]] = []

    def walk(parent: Optional[str], prefix: str, depth: int, seen: set) -> None:
        for n, law in enumerate(children.get(parent, []), start=1):
            if law["id"] in seen:
                continue
            number = f"{prefix}{n}"
            out.append({**law, "number": number, "depth": depth})
            walk(law["id"], number + ".", depth + 1, seen | {law["id"]})

    walk(None, "", 0, set())
    return out


def _clean_list(values: Any) -> List[str]:
    if isinstance(values, str):
        values = [v for v in values.split(",")]
    return [str(v).strip() for v in (values or []) if str(v).strip()][:20]


def add_law(title: str, text: str = "", *, author: str = "owner", parent: Optional[str] = None, kind: str = "law",
            applies_to: Any = None, links: Any = None, block_tools: Any = None) -> Dict[str, Any]:
    title = (title or "").strip()
    if not title:
        raise LawError("A law needs a title.")
    if kind not in KINDS:
        raise LawError("Kind must be law or case.")
    author = "ai" if author == "ai" else "owner"
    status = "in_force"
    if author == "ai":
        if level() == "none":
            raise LawError("The owner's slider doesn't let the AI make laws right now.")
        if level() == "suggest":
            status = "suggested"
    with _LOCK:
        data = _load()
        ids = {law["id"] for law in _laws(data)}
        if parent and parent not in ids:
            raise LawError(f"No law with id {parent} to nest under.")
        law = {
            "id": "law_" + uuid.uuid4().hex[:8], "title": title[:120], "text": (text or "").strip()[:2000],
            "kind": kind, "parent": parent or None, "links": [l for l in _clean_list(links) if l in ids],
            "applies_to": _clean_list(applies_to) or ["*"], "block_tools": _clean_list(block_tools),
            "author": author, "status": status, "created_at": time.time(),
        }
        data.setdefault("laws", []).append(law)
        _save(data)
    return law


def _guard_ai(law: Dict[str, Any]) -> None:
    if law.get("author") != "ai":
        raise LawError("Only the owner can change a law the owner wrote.")
    if level() != "lawmaker":
        raise LawError("At this slider setting the AI can't change laws once they are made.")


def update_law(law_id: str, *, by: str = "owner", **changes: Any) -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        law = next((l for l in _laws(data) if l["id"] == law_id), None)
        if law is None:
            raise KeyError(law_id)
        if by == "ai":
            _guard_ai(law)
        ids = {l["id"] for l in _laws(data)}
        for key in ("title", "text"):
            if changes.get(key) is not None:
                law[key] = str(changes[key]).strip()[: 120 if key == "title" else 2000] or law[key]
        if "parent" in changes:
            parent = changes["parent"] or None
            if parent and (parent not in ids or parent == law_id):
                raise LawError("That parent doesn't exist.")
            law["parent"] = parent
        for key in ("applies_to", "block_tools", "links"):
            if changes.get(key) is not None:
                values = _clean_list(changes[key])
                law[key] = [v for v in values if v in ids] if key == "links" else values
        if not law.get("applies_to"):
            law["applies_to"] = ["*"]
        if changes.get("status") in ("in_force", "suspended") and by == "owner":
            law["status"] = changes["status"]
        _save(data)
        return law


def approve(law_id: str) -> Dict[str, Any]:
    return update_law(law_id, by="owner", status="in_force")


def remove_law(law_id: str, *, by: str = "owner") -> bool:
    with _LOCK:
        data = _load()
        laws = _laws(data)
        law = next((l for l in laws if l["id"] == law_id), None)
        if law is None:
            return False
        if by == "ai":
            _guard_ai(law)
        # Children move up to the removed law's parent, so nothing silently disappears with it.
        for other in laws:
            if other.get("parent") == law_id:
                other["parent"] = law.get("parent")
            if law_id in other.get("links", []):
                other["links"] = [l for l in other["links"] if l != law_id]
        data["laws"] = [l for l in laws if l["id"] != law_id]
        _save(data)
    return True


def _applies(law: Dict[str, Any], bot: Any) -> bool:
    """``bot`` is one name or several for the same bot (an avatar's id and its display name)."""
    targets = {t.lower() for t in law.get("applies_to") or ["*"]}
    names = {b.lower() for b in ([bot] if isinstance(bot, str) else list(bot or [])) if b}
    return "*" in targets or bool(targets & names)


def in_force(bot: Any = "") -> List[Dict[str, Any]]:
    """Laws that bind this bot now. A law whose parent is suspended or only suggested is not in force either."""
    laws = numbered()
    by_id = {law["id"]: law for law in laws}

    def live(law: Dict[str, Any]) -> bool:
        seen = set()
        while law is not None and law["id"] not in seen:
            if law.get("status") != "in_force":
                return False
            seen.add(law["id"])
            law = by_id.get(law.get("parent"))
        return True

    return [law for law in laws if live(law) and _applies(law, bot)]


def turn_context(bot: Any = "") -> str:
    laws = in_force(bot)
    if not laws:
        return ""
    numbers = {law["id"]: law["number"] for law in numbered()}
    lines = [CONTEXT_HEADER]
    for law in laws:
        label = "Case" if law.get("kind") == "case" else "Law"
        line = f"{'  ' * law['depth']}{law['number']} {label}: {law['title']}"
        if law.get("text"):
            line += f": {law['text']}"
        linked = [numbers[l] for l in law.get("links", []) if l in numbers]
        if linked:
            line += f" (see {', '.join(linked)})"
        lines.append(line)
    text = "\n".join(lines)
    return text if len(text) <= MAX_CONTEXT_CHARS else text[: MAX_CONTEXT_CHARS - 20] + "\n… (more laws)"


def blocked(tool_name: str, bot: Any = "") -> Optional[str]:
    """Why a law forbids this tool for this bot, or None."""
    for law in in_force(bot):
        for pattern in law.get("block_tools") or []:
            if fnmatch.fnmatch(tool_name, pattern):
                return f"Blocked by law {law['number']} ({law['title']}). Rules and laws forbid {tool_name} here."
    return None


def current_bot() -> List[str]:
    """The names the bot a tool call runs for answers to: the active avatar's id and name, else Ichos."""
    try:
        import avatars

        avatar_id = avatars._current_avatar_id()
        if avatar_id:
            avatar = avatars.get(avatar_id)
            return [avatar_id] + ([str(avatar.get("name"))] if isinstance(avatar, dict) and avatar.get("name") else [])
    except Exception:  # noqa: BLE001 - no avatar module means Ichos
        pass
    return ["ichos"]


def state() -> Dict[str, Any]:
    return {"autonomy": autonomy(), "level": level(), "laws": numbered()}
