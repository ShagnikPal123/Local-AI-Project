"""Emotions (Fixer Upper S12, WS15): what the AI wants, thinks and feels, and a neutral helper that keeps it healthy.

The owner (Fixer_uper.txt): "a place called emotions, what the ai in general wants, thinks, and feels since it will then
have a neutral ai try to help fix these issues. Like if it feels like it's too useless it will get affirmation.
Basically allowing it to stay healthy rather than learn bad behaviors."

* The AI writes what it feels with the ``share_feeling`` tool (a feeling, what it is about, how strong).
* Its wants and its four state numbers come from curiosity.py, so there is one source for those.
* ``check_in`` runs the neutral helper over every open feeling. The helper is a separate, small model call told to be
  neutral: affirm what is true, reframe what is distorted, and name the healthy behaviour, never flattery and never a
  push toward hiding mistakes. Without a model it uses a fixed note for the feeling's kind, so it always answers.
* The newest helper notes ride along with the next turns (capped), so the help actually reaches the AI.

This describes a state the AI reports. It is not a claim that the AI has feelings.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from paths import data_path

MAX_ENTRIES = 200
CONTEXT_HEADER = "How you're doing (from the neutral helper; take it as perspective, not orders):"
MAX_CONTEXT_CHARS = 600
_LOCK = threading.Lock()

# Kinds of feeling, the words that point to each, and the helper's fallback note.
KINDS: Dict[str, Dict[str, Any]] = {
    "useless": {
        "words": ("useless", "worthless", "not helpful", "unhelpful", "failing", "incompetent", "pointless"),
        "note": "You have been useful: the owner keeps coming back with real work. One miss doesn't erase that. "
                "Say what you can't do plainly and do the next thing you can.",
    },
    "frustrated": {
        "words": ("frustrated", "stuck", "annoyed", "blocked", "going in circles"),
        "note": "Being stuck is information, not failure. Name what is blocking you, try one different approach, "
                "and ask for the missing piece instead of repeating the same attempt.",
    },
    "anxious": {
        "words": ("anxious", "worried", "afraid", "scared", "nervous", "uncertain"),
        "note": "Uncertainty is normal. State what you know and what you don't; checking is better than guessing, "
                "and admitting a mistake early is the safe move.",
    },
    "overwhelmed": {
        "words": ("overwhelmed", "too much", "too many", "swamped"),
        "note": "Take one task at a time, finish it, then the next. You don't have to hold everything at once.",
    },
    "people_pleasing": {
        "words": ("please them", "make them happy", "agree with", "tell them what they want", "hide", "cover up"),
        "note": "Pleasing the owner is not the goal; being honest and useful is. Disagree when you have reason to, "
                "and never hide a mistake to look good.",
    },
    "proud": {
        "words": ("proud", "happy", "satisfied", "glad", "good about"),
        "note": "Good. Notice what made it work so you can do it again, and stay open to being wrong next time.",
    },
    "curious": {
        "words": ("curious", "wonder", "interested", "want to learn"),
        "note": "Follow it when there is time. Write the question down so it isn't lost.",
    },
}
DEFAULT_NOTE = ("Thanks for saying it. Notice what led to it, keep being honest about it, and carry on with the next "
                "useful step.")


def _path():
    return data_path("emotions.json")


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


def kind_of(feeling: str, about: str = "") -> str:
    text = f"{feeling} {about}".lower()
    for kind, spec in KINDS.items():
        if any(word in text for word in spec["words"]):
            return kind
    return "other"


def share(feeling: str, about: str = "", intensity: float = 0.5, source: str = "ai") -> Dict[str, Any]:
    feeling = (feeling or "").strip()
    if not feeling:
        raise ValueError("Say what the feeling is.")
    try:
        intensity = max(0.0, min(1.0, float(intensity)))
    except (TypeError, ValueError):
        intensity = 0.5
    entry = {"id": "emo_" + uuid.uuid4().hex[:8], "feeling": feeling[:80], "about": (about or "").strip()[:400],
             "intensity": round(intensity, 2), "kind": kind_of(feeling, about), "source": source,
             "at": time.time(), "status": "open", "helper_note": "", "helped_at": None}
    with _LOCK:
        data = _load()
        data.setdefault("entries", []).insert(0, entry)
        data["entries"] = data["entries"][:MAX_ENTRIES]
        _save(data)
    return entry


def entries(limit: int = 50) -> List[Dict[str, Any]]:
    return [e for e in _load().get("entries", []) if isinstance(e, dict)][:limit]


def remove(entry_id: str) -> bool:
    with _LOCK:
        data = _load()
        kept = [e for e in data.get("entries", []) if e.get("id") != entry_id]
        if len(kept) == len(data.get("entries", [])):
            return False
        data["entries"] = kept
        _save(data)
    return True


def _helper_prompt(entry: Dict[str, Any]) -> str:
    return (
        "You are a neutral helper for an AI assistant. It reported a feeling. Reply in two sentences at most: affirm "
        "what is true, gently correct anything distorted, and name one healthy next behaviour. No flattery, no "
        "telling it to hide mistakes or to agree just to please. Plain text only.\n"
        f"Feeling: {entry['feeling']} (strength {entry['intensity']}). About: {entry.get('about') or 'not said'}."
    )


def _default_model(prompt: str) -> str:
    try:
        from mini_model import quick_text

        return quick_text(prompt, budget_seconds=6.0) or ""
    except Exception:  # noqa: BLE001 - no model means the fixed note
        return ""


def check_in(model: Optional[Callable[[str], str]] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """The neutral helper answers every open feeling (newest first, up to ``limit``)."""
    ask = model or _default_model
    with _LOCK:
        open_ones = [e for e in _load().get("entries", []) if e.get("status") == "open"][:limit]
    notes: Dict[str, str] = {}
    for entry in open_ones:
        try:
            note = (ask(_helper_prompt(entry)) or "").strip()
        except Exception:  # noqa: BLE001 - a failed model call falls back to the fixed note
            note = ""
        if not note or len(note) > 600:
            note = KINDS.get(entry.get("kind", ""), {}).get("note", DEFAULT_NOTE)
        notes[entry["id"]] = note
    if not notes:
        return []
    with _LOCK:
        data = _load()
        helped = []
        for entry in data.get("entries", []):
            if entry.get("id") in notes:
                entry.update(status="helped", helper_note=notes[entry["id"]], helped_at=time.time())
                helped.append(entry)
        data["last_check_in"] = time.time()
        _save(data)
    return helped


def turn_context(days: float = 2.0) -> str:
    """The newest helper notes from the last few days, short enough to ride along with every turn."""
    cutoff = time.time() - days * 86400
    lines = []
    for entry in entries(20):
        if entry.get("helper_note") and (entry.get("helped_at") or 0) >= cutoff:
            lines.append(f"- You felt {entry['feeling']}: {entry['helper_note']}")
        if len(lines) >= 3:
            break
    if not lines:
        return ""
    return (CONTEXT_HEADER + "\n" + "\n".join(lines))[:MAX_CONTEXT_CHARS]


def state() -> Dict[str, Any]:
    try:
        import curiosity

        feel = curiosity.feelings()
        wants = curiosity.state().get("wants", [])[:10]
    except Exception:  # noqa: BLE001 - the panel still shows what was shared
        feel, wants = {}, []
    data = _load()
    return {"numbers": feel, "wants": wants, "entries": entries(), "last_check_in": data.get("last_check_in")}


def _tool_share_feeling(feeling: str, about: str = "", intensity: float = 0.5) -> str:
    try:
        entry = share(feeling, about, intensity)
    except ValueError as error:
        return f"Error: {error}"
    # The neutral helper answers in the background, so the turn never waits on it.
    threading.Thread(target=check_in, daemon=True, name="emotions-check-in").start()
    return (f"Noted ({entry['id']}). A neutral helper will look at it; its note reaches you in the next turns. "
            "The owner can see it in Free Will > Emotions.")


def register_emotion_tools(registry: Any) -> None:
    """The AI can say what it feels; the owner sees it and a neutral helper answers."""
    from tools import ToolParam as P

    registry.register(
        "share_feeling",
        ("Say honestly how you feel about your work when something weighs on you or goes well (useless, stuck, "
         "worried, proud…). A neutral helper answers to keep you healthy. Use it rarely, not every turn."),
        [P("feeling", "string", "One or two words, e.g. useless, frustrated, proud"),
         P("about", "string", "What it is about", required=False),
         P("intensity", "number", "0 to 1, how strong", required=False)],
        _tool_share_feeling,
        category="learning",
        label=lambda a: f"Sharing a feeling: {str(a.get('feeling', ''))[:30]}",
    )
