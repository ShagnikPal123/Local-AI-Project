"""Thinking while the owner is still speaking.

The owner (2026-09-22): "as I talk it listens and thinks of how to answer and
then instantly responds … by the end it ids the fact they stopped with that
pause and can instantly talk … Use a separate model for voice, text, listening,
and active listening as well a interpretation."

So a spoken turn is five jobs, not one, and each has its own model:

    listening        the words:      the browser's speech model, or a local one
    active listening is it finished: this module, helped by a small fast model
    interpretation   what they mean: a model that cleans the words into a request
    text             the answer:     the chat model (a fast one for voice)
    voice            the sound:      an edge-tts / Windows voice per role (tts.py)

The part that makes it feel instant is here. While the owner is mid-sentence the
browser sends what it has heard so far; every call does three things:

1. **Scores whether the sentence is finished.** Rules first (a trailing "and" is
   not an ending, a question that parses is), and the active-listening model when
   the rules are unsure. The score decides how long the pause has to be before
   the turn is sent — about 0.4 s for a clean ending, up to 1.6 s for a trailing
   "and", instead of one fixed wait for everything.
2. **Fetches what the answer will need.** A question that clearly needs the web
   starts searching before the owner has finished asking.
3. **Writes the answer early.** Once the sentence looks complete, a draft is
   generated in the background. If the final words match what was drafted, the
   turn answers from it at once instead of starting a model call from cold.

A draft is only ever used for a question or small talk. Anything that asks Nyx
to *do* something goes through the normal pipeline with its tools and its
approvals: a spoken shortcut must never send an email that nothing checked.
"""

from __future__ import annotations

import difflib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from paths import data_path

#: How long a draft is worth using. Past this the conversation has moved on.
DRAFT_TTL_SECONDS = 30.0
#: Longest a session sits in memory with nothing happening.
SESSION_TTL_SECONDS = 900.0
#: The active-listening model is asked again at most this often, per session.
THINK_EVERY_SECONDS = 0.55
#: A draft is this short — it is going to be read aloud.
DRAFT_MAX_TOKENS = 240

DEFAULTS: Dict[str, Any] = {
    # Which speech-to-text does the listening. "browser" is the recognizer built
    # into Chrome and Edge; "local" is a model on this PC once one is installed.
    "listening": "browser",
    # Think, fetch and draft while the owner talks.
    "think_ahead": True,
    # Keep listening while Nyx speaks, so talking over it interrupts.
    "listen_while_speaking": True,
    # Shrink the chat sheet while voice is on, so the room is the brain.
    "smaller_panel": True,
    # Speak each sentence as it is written instead of waiting for the whole answer.
    "speak_as_written": True,
    # Milliseconds of silence needed before sending, by how finished it sounded.
    "wait_done": 420,
    "wait_unsure": 800,
    "wait_open": 1500,
}

#: Model roles this module drives. They are created in model_roles on first use.
ROLE_ACTIVE = "voice_active"
ROLE_INTERPRET = "voice_interpret"
ROLE_REPLY = "voice_reply"

_lock = threading.Lock()
_settings_cache: Optional[Dict[str, Any]] = None


def _settings_path():
    return data_path("voice_pipeline.json")


def settings() -> Dict[str, Any]:
    global _settings_cache
    if _settings_cache is None:
        data: Dict[str, Any] = {}
        try:
            raw = json.loads(_settings_path().read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, ValueError):
            data = {}
        _settings_cache = {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}
    return dict(_settings_cache)


def update_settings(**changes: Any) -> Dict[str, Any]:
    global _settings_cache
    current = settings()
    for key, value in changes.items():
        if key in DEFAULTS and value is not None:
            current[key] = value
    with _lock:
        _settings_cache = current
        try:
            _settings_path().write_text(json.dumps(current, indent=2), encoding="utf-8")
        except OSError:
            pass
    return dict(current)


# ---------------------------------------------------------------------------
# Is the sentence finished?
# ---------------------------------------------------------------------------

#: Words nobody ends a sentence on: the next word is still coming.
_OPEN_ENDINGS = {
    "and", "or", "but", "so", "because", "if", "when", "while", "that", "which", "who", "to", "for",
    "with", "about", "of", "in", "on", "at", "from", "the", "a", "an", "my", "your", "their", "is",
    "are", "was", "were", "can", "could", "should", "would", "will", "um", "uh", "er", "like", "just",
    "then", "than", "into", "over", "under", "very", "really", "kind", "sort",
}
#: A request that starts like this is an instruction, complete as soon as it has an object.
_COMMAND_STARTS = {
    "open", "close", "play", "pause", "stop", "start", "search", "find", "show", "make", "write",
    "send", "call", "read", "turn", "go", "switch", "put", "set", "add", "remove", "delete", "run",
    "take", "bring", "give", "tell", "remind", "lock", "sleep", "shut", "mute", "unmute", "copy",
}
_QUESTION_STARTS = {
    "what", "who", "when", "where", "why", "how", "which", "can", "could", "would", "should", "do",
    "does", "did", "is", "are", "was", "were", "will", "tell", "explain", "show", "help",
}
#: Things a draft must never answer for: they change something in the world.
_ACTION_WORDS = re.compile(
    r"\b(send|email|e-mail|reply|buy|sell|order|pay|transfer|delete|remove|uninstall|shut\s*down|"
    r"restart|schedule|book|post|publish|commit|push|install|move|rename|open|close|run|execute|"
    r"click|type|call|text|message|remind|set\s+a|turn\s+(on|off))\b",
    re.IGNORECASE,
)


def completeness(text: str) -> float:
    """0–1: how finished the sentence sounds, from the words alone."""
    words = re.findall(r"[\w']+", (text or "").lower())
    if not words:
        return 0.0
    score = 0.5 if len(words) >= 3 else 0.3
    if words[-1] in _OPEN_ENDINGS:
        return 0.12 if len(words) > 1 else 0.1
    stripped = (text or "").strip()
    if stripped.endswith(("?", ".", "!")):
        score += 0.3
    if words[0] in _COMMAND_STARTS and len(words) >= 2:
        score += 0.3
    elif words[0] in _QUESTION_STARTS and len(words) >= 4:
        score += 0.28
    if len(words) >= 8:
        score += 0.1
    if len(words) <= 2 and words[0] not in _COMMAND_STARTS:
        score -= 0.15
    return max(0.0, min(1.0, score))


def wait_for(score: float, config: Optional[Dict[str, Any]] = None) -> int:
    """Milliseconds of silence to wait before deciding the owner has stopped."""
    config = config or settings()
    if score >= 0.78:
        return int(config["wait_done"])
    if score >= 0.5:
        return int(config["wait_unsure"])
    return int(config["wait_open"])


def kind_of(text: str) -> str:
    """question | command | chat — what this utterance is for."""
    words = re.findall(r"[\w']+", (text or "").lower())
    if not words:
        return "chat"
    if words[0] in _COMMAND_STARTS or _ACTION_WORDS.search(text or ""):
        return "command"
    if (text or "").strip().endswith("?") or words[0] in _QUESTION_STARTS:
        return "question"
    return "chat"


def draftable(text: str) -> bool:
    """Only questions and small talk may be answered from a draft."""
    return kind_of(text) != "command" and len(re.findall(r"[\w']+", text or "")) >= 2


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@dataclass
class VoiceSession:
    session_id: str
    chat_id: str = ""
    heard: str = ""
    utterance_id: str = ""
    score: float = 0.0
    kind: str = "chat"
    means: str = ""
    model_said_done: Optional[bool] = None
    last_model_call: float = 0.0
    thinking: bool = False
    prefetch: Dict[str, Any] = field(default_factory=dict)
    prefetching: str = ""
    draft: str = ""
    draft_for: str = ""
    draft_at: float = 0.0
    draft_provider: str = ""
    draft_model: str = ""
    drafting_for: str = ""
    touched: float = field(default_factory=time.time)


_sessions: Dict[str, VoiceSession] = {}


def session(session_id: str, chat_id: str = "") -> VoiceSession:
    with _lock:
        now = time.time()
        for key, value in list(_sessions.items()):
            if now - value.touched > SESSION_TTL_SECONDS:
                _sessions.pop(key, None)
        current = _sessions.get(session_id)
        if current is None:
            current = VoiceSession(session_id=session_id, chat_id=chat_id)
            _sessions[session_id] = current
        if chat_id:
            current.chat_id = chat_id
        current.touched = now
        return current


def forget(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)


# ---------------------------------------------------------------------------
# The models
# ---------------------------------------------------------------------------


def _fastest_local_first() -> Dict[str, str]:
    """A provider/model pair for voice work: the local model if there is one."""
    try:
        from config import SETTINGS

        host = getattr(SETTINGS, "ollama_host", "")
        model = getattr(SETTINGS, "ollama_model", "") or "llama3.1"
        if host:
            return {"provider": "ollama", "model": model}
    except Exception:  # pragma: no cover - config is always there in practice
        pass
    return {"provider": "groq", "model": "llama-3.3-70b-versatile"}


def ensure_roles() -> Dict[str, Dict[str, Any]]:
    """Create the three voice roles the first time, and return all five slots."""
    from model_roles import MODEL_ROLES

    local = _fastest_local_first()
    wanted = {
        ROLE_ACTIVE: {
            "title": "Active listening",
            "description": "Follows the words while you are still speaking: is the sentence finished, and what will the answer need?",
            "job": "text",
            **local,
        },
        ROLE_INTERPRET: {
            "title": "Interpretation",
            "description": "Turns what was heard into what was meant, and says whether it is a question or an instruction.",
            "job": "text",
            **local,
        },
        ROLE_REPLY: {
            "title": "Spoken answers",
            "description": "Writes the answer that gets read aloud. Speed matters more than length here.",
            "job": "text",
            **local,
        },
    }
    out: Dict[str, Dict[str, Any]] = {}
    for role, entry in wanted.items():
        try:
            existing = MODEL_ROLES.get_role(role)
            if not existing:
                MODEL_ROLES.assign_role(role, entry["provider"], entry["model"], title=entry["title"],
                                        description=entry["description"], job="text", assigned_by="nyx")
                existing = MODEL_ROLES.get_role(role)
            out[role] = existing or entry
        except Exception:  # pragma: no cover - roles are a nicety, never a blocker
            out[role] = entry
    return out


def roles() -> Dict[str, Any]:
    """What is doing each of the five voice jobs, for the Settings panel."""
    config = settings()
    out: Dict[str, Any] = {
        "listening": {
            "title": "Listening",
            "what": "Turns your voice into words",
            "engine": config["listening"],
            "label": "Your browser's speech model" if config["listening"] == "browser" else "A model on this PC",
            "local": config["listening"] != "browser",
            "note": ("Chrome and Edge send the audio to their own speech service. "
                     "A local listening model can replace it once one is installed."
                     if config["listening"] == "browser" else ""),
        },
    }
    try:
        entries = ensure_roles()
        from model_roles import MODEL_ROLES

        for key, title, what in (
            (ROLE_ACTIVE, "Active listening", "Decides when you have finished and what to get ready"),
            (ROLE_INTERPRET, "Interpretation", "Works out what you meant"),
            (ROLE_REPLY, "Answering", "Writes what gets spoken back"),
        ):
            entry = MODEL_ROLES.get_role(key) or entries.get(key) or {}
            out[key] = {"title": title, "what": what, "provider": entry.get("provider", ""),
                        "model": entry.get("model", ""), "label": entry.get("label", "")}
    except Exception:  # pragma: no cover
        pass
    try:
        import tts

        out["voice"] = {"title": "Voice", "what": "The voice it speaks in", "roles": tts.role_voices()}
    except Exception:  # pragma: no cover - the voice list is a nicety
        out["voice"] = {"title": "Voice", "what": "The voice it speaks in", "roles": {}}
    return out


def _ask_model(role: str, prompt: str, system: str, max_tokens: int) -> str:
    from model_roles import MODEL_ROLES

    ensure_roles()
    run = MODEL_ROLES.run(role, prompt, system=system, max_tokens=max_tokens)
    return run.text or ""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _json_from(text: str) -> Dict[str, Any]:
    match = _JSON_RE.search(text or "")
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


_ACTIVE_SYSTEM = (
    "detailed thinking off\n"
    "You are the listening part of a voice assistant. You are given what the speaker has said SO FAR; "
    "they may still be talking. Answer with JSON only, no prose:\n"
    '{"done": true|false, "means": "<what they are asking, in one line>", '
    '"kind": "question|command|chat", "search": "<web search that would help, or empty>"}\n'
    '"done" is true only when the sentence is finished and nothing is obviously missing.'
)


def _think_with_model(state: VoiceSession, text: str) -> None:
    """Ask the active-listening model about a half-finished sentence."""
    try:
        reply = _ask_model(ROLE_ACTIVE, f"So far: {text}", _ACTIVE_SYSTEM, 160)
        data = _json_from(reply)
        if not data:
            return
        if isinstance(data.get("done"), bool):
            state.model_said_done = data["done"]
        means = str(data.get("means") or "").strip()
        if means and len(means) < 400:
            state.means = means
        kind = str(data.get("kind") or "").strip().lower()
        if kind in {"question", "command", "chat"}:
            state.kind = kind
        query = str(data.get("search") or "").strip()
        if query and state.prefetching != query and settings()["think_ahead"]:
            _prefetch(state, query)
    except Exception:  # pragma: no cover - a slow or missing model must not break listening
        pass
    finally:
        state.thinking = False


def _prefetch(state: VoiceSession, query: str) -> None:
    """Start the web search the answer is going to want."""
    state.prefetching = query

    def work() -> None:
        try:
            import web_access

            results = web_access.search_results(query)[:4]
            state.prefetch = {
                "query": query,
                "at": time.time(),
                "text": "\n".join(f"- {r.get('title', '')} ({r.get('url', '')})" for r in results),
            }
        except Exception:  # pragma: no cover - no web, no prefetch
            state.prefetch = {}

    threading.Thread(target=work, name="voice-prefetch", daemon=True).start()


_DRAFT_SYSTEM = (
    "detailed thinking off\n"
    "You are Nyx, answering out loud. The answer is going to be SPOKEN, so: at most three short "
    "sentences of plain English, no markdown, no lists, no code, no links. If you do not know "
    "something, say so in one line. Never claim to have done anything."
)


def _draft(state: VoiceSession, text: str) -> None:
    """Write the answer before the owner has finished asking for it."""
    state.drafting_for = text

    def work() -> None:
        try:
            history = _recent_history(state.chat_id)
            notes = state.prefetch.get("text") or ""
            prompt = text if not notes else f"{text}\n\n[From a web search just now]\n{notes}"
            if history:
                prompt = f"[Earlier in this conversation]\n{history}\n\n[They just said]\n{prompt}"
            from model_roles import MODEL_ROLES

            ensure_roles()
            run = MODEL_ROLES.run(ROLE_REPLY, prompt, system=_DRAFT_SYSTEM, max_tokens=DRAFT_MAX_TOKENS)
            answer = (run.text or "").strip()
            if answer:
                state.draft = answer
                state.draft_for = text
                state.draft_at = time.time()
                state.draft_provider = run.provider
                state.draft_model = run.model
        except Exception:  # pragma: no cover - a failed draft just means the normal path answers
            pass
        finally:
            state.drafting_for = ""

    threading.Thread(target=work, name="voice-draft", daemon=True).start()


def _recent_history(chat_id: str, turns: int = 4) -> str:
    if not chat_id:
        return ""
    try:
        import chat_sessions

        store = chat_sessions.ChatSessionStore()
        messages = store.messages(chat_id)[-turns * 2:]
        lines = []
        for message in messages:
            role = "You" if message.get("role") == "user" else "Nyx"
            content = str(message.get("content", ""))[:400]
            if content:
                lines.append(f"{role}: {content}")
        return "\n".join(lines)
    except Exception:  # pragma: no cover - no history is fine
        return ""


# ---------------------------------------------------------------------------
# What the browser calls while the owner talks
# ---------------------------------------------------------------------------


def think(session_id: str, text: str, *, final: bool = False, chat_id: str = "",
          utterance_id: str = "", tabs: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    """One step of listening. Fast, and safe to call every few hundred ms."""
    state = session(session_id or "default", chat_id)
    text = (text or "").strip()
    state.heard = text
    state.utterance_id = utterance_id or state.utterance_id or uuid.uuid4().hex[:8]
    config = settings()

    score = completeness(text)
    if state.model_said_done is True and text:
        score = max(score, 0.85)
    elif state.model_said_done is False:
        score = min(score, 0.45)
    state.score = score
    state.kind = state.kind if state.model_said_done is not None else kind_of(text)

    # Big Kahuna's own reading of the words: "open gmail" acts before the sentence ends.
    actions: List[Dict[str, Any]] = []
    handled = False
    try:
        from identity0 import api as kahuna_api

        intent = kahuna_api.voice_intent(text, final=final, tabs=tabs or [])
        actions = list(intent.get("actions") or [])
        handled = bool(intent.get("handled"))
    except Exception:  # pragma: no cover - Big Kahuna is optional
        pass

    now = time.time()
    words = len(re.findall(r"[\w']+", text))
    if (config["think_ahead"] and not final and words >= 4 and not state.thinking
            and now - state.last_model_call >= THINK_EVERY_SECONDS and 0.2 < score < 0.92):
        state.thinking = True
        state.last_model_call = now
        threading.Thread(target=_think_with_model, args=(state, text), name="voice-active", daemon=True).start()

    # The answer starts being written as soon as the sentence looks finished.
    if (config["think_ahead"] and text and draftable(text) and not handled
            and (final or score >= 0.8) and state.drafting_for != text
            and not (state.draft_for == text and now - state.draft_at < DRAFT_TTL_SECONDS)):
        _draft(state, state.means or text)

    _publish_transcript(text, final, state)

    return {
        "utterance_id": state.utterance_id,
        "complete": round(score, 3),
        "wait_ms": wait_for(score, config),
        "kind": state.kind,
        "means": state.means,
        "actions": actions,
        "handled": handled,
        "draft_ready": bool(state.draft and now - state.draft_at < DRAFT_TTL_SECONDS),
        "prefetched": bool(state.prefetch.get("text")),
    }


def _publish_transcript(text: str, final: bool, state: VoiceSession) -> None:
    """Tell the rest of Nyx what was heard (the hands-off bar listens for this)."""
    try:
        from agent_events import publish_ui

        publish_ui("voice.transcript", text=text[:600], final=bool(final),
                   utterance_id=state.utterance_id, mode="voice", complete=round(state.score, 3))
    except Exception:  # pragma: no cover - events are best effort
        pass


def take_draft(session_id: str, text: str) -> Optional[Dict[str, Any]]:
    """The early answer, if one was written for (near enough) these words."""
    if not session_id or not text:
        return None
    state = _sessions.get(session_id)
    if state is None or not state.draft:
        return None
    if time.time() - state.draft_at > DRAFT_TTL_SECONDS:
        return None
    if not draftable(text):
        return None
    wanted = _normalize(text)
    drafted = _normalize(state.draft_for)
    if not wanted or not drafted:
        return None
    same = wanted == drafted or difflib.SequenceMatcher(None, wanted, drafted).ratio() >= 0.88
    if not same:
        return None
    draft = {"text": state.draft, "provider": state.draft_provider, "model": state.draft_model,
             "drafted_for": state.draft_for}
    state.draft = ""
    state.draft_for = ""
    return draft


def _normalize(text: str) -> str:
    return " ".join(re.findall(r"[\w']+", (text or "").lower()))


def interpret(text: str, *, context: str = "") -> Dict[str, Any]:
    """What the owner meant, cleaned up. Used when the words came out mangled."""
    system = (
        "detailed thinking off\n"
        "Speech-to-text output is given to you. Fix obvious mis-hearings and say what was meant. "
        'JSON only: {"means": "<one line>", "kind": "question|command|chat", "confident": true|false}'
    )
    prompt = text if not context else f"[Context]\n{context}\n\n[Heard]\n{text}"
    try:
        data = _json_from(_ask_model(ROLE_INTERPRET, prompt, system, 200))
    except Exception:  # pragma: no cover
        data = {}
    return {
        "means": str(data.get("means") or text).strip(),
        "kind": str(data.get("kind") or kind_of(text)).lower(),
        "confident": bool(data.get("confident", False)),
    }
