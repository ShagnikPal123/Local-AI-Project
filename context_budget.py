"""How full the model's context is, and compacting a chat so it keeps going (Request Q, 2026-09-17).

The owner: "Add a context bar and compact context skill."

What was wrong: every turn sent the chat's whole history — system prompt, memory, the last 40 stored messages and
every tool result since — to the model, and nothing ever trimmed it. A long chat got slower and dearer each turn and
could overflow a small context window (Kimi 8k, a local Ollama model) with a confusing provider error.

* :func:`measure` estimates the tokens in a conversation (about four characters per token; images count extra),
  splits them into what fills the window — Nyx's instructions, memory and skills, the conversation, tool results, an
  earlier summary — and compares that to the answering model's context window.
* :func:`compact` replaces the older part of the conversation with one short summary written by a fast model (an
  offline extract when no model answers), keeps the most recent messages word for word, and records the compaction on
  the stored chat so a restart doesn't undo it. The chat transcript the owner reads is never changed.
* :func:`undo` puts the full history back.
* :func:`maybe_auto_compact` runs before a turn: past the owner's threshold (85 % by default) the chat compacts
  itself and says so.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from paths import data_path

SUMMARY_PREFIX = "[Earlier in this chat — summary]"
CHARS_PER_TOKEN = 3.8
IMAGE_TOKENS = 1100
MESSAGE_OVERHEAD = 4
DEFAULT_WINDOW = 32_000

#: Context windows in tokens: (provider, model prefix) → size. The first match wins; "" matches any model.
WINDOWS: List[Tuple[str, str, int]] = [
    ("gemini", "", 1_048_576),
    ("openai", "gpt-4.1", 1_047_576),
    ("openai", "", 128_000),
    ("claude", "", 200_000),
    ("groq", "", 131_072),
    ("nvidia", "meta/llama-3.2", 128_000),
    ("nvidia", "", 128_000),
    ("deepseek", "", 128_000),
    ("kimi", "moonshot-v1-8k", 8_000),
    ("kimi", "moonshot-v1-32k", 32_000),
    ("kimi", "", 128_000),
    ("perplexity", "", 128_000),
    ("aws", "amazon.nova", 300_000),
    ("aws", "", 128_000),
]


def _ollama_window() -> int:
    """What Nyx really asks of a local model: ``num_ctx`` on every Ollama call (providers.ollama_provider).

    This was a fixed 8,192 while the provider asked for 32,768, so a fresh local chat — Nyx's instructions alone
    are ~15k tokens — read "186 % · almost full", and past six messages every turn auto-compacted for nothing.
    """
    try:
        from providers.ollama_provider import NUM_CTX

        return int(NUM_CTX)
    except Exception:  # noqa: BLE001 - the meter never fails because the provider would not import
        return 32_768

_LOCK = threading.Lock()
_UNDO: Dict[int, List[Dict[str, Any]]] = {}


class ContextError(RuntimeError):
    """Why a compaction didn't happen, in words for the owner."""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _settings_path() -> Path:
    return data_path("context_settings.json")


def settings() -> Dict[str, Any]:
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {
        "auto_compact": bool(data.get("auto_compact", True)),
        "threshold": int(min(98, max(50, int(data.get("threshold", 85) or 85)))),
        "keep_last": int(min(20, max(2, int(data.get("keep_last", 6) or 6)))),
        "windows": {str(k): int(v) for k, v in (data.get("windows") or {}).items() if str(v).isdigit()},
    }


def save_settings(**changes: Any) -> Dict[str, Any]:
    current = settings()
    for key in ("auto_compact", "threshold", "keep_last"):
        if changes.get(key) is not None:
            current[key] = changes[key]
    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(current, indent=1), encoding="utf-8")
    return settings()


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------


def window_for(provider: str, model: str = "") -> int:
    name = (provider or "").strip().lower()
    model = (model or "").strip().lower()
    override = settings()["windows"]
    for key in (f"{name}:{model}", name):
        if key in override:
            return override[key]
    if name == "ollama":
        return _ollama_window()
    for prov, prefix, size in WINDOWS:
        if name == prov and model.startswith(prefix):
            return size
    try:
        from provider_specs import PROVIDER_SPECS

        if PROVIDER_SPECS.get(name) is not None:
            return 128_000 if not getattr(PROVIDER_SPECS.get(name), "allow_local", False) else 8_192
    except Exception:  # noqa: BLE001
        pass
    return DEFAULT_WINDOW


def estimate_tokens(text: Any) -> int:
    return int(len(str(text or "")) / CHARS_PER_TOKEN) + MESSAGE_OVERHEAD


def _part(message: Dict[str, Any], index: int, first_conversation: int) -> str:
    content = str(message.get("content", ""))
    if content.startswith(SUMMARY_PREFIX):
        return "summary"
    if message.get("role") == "system":
        return "instructions" if index < first_conversation and index == 0 else "memory"
    if message.get("_tool_results") or content.startswith(("Tool results:", "Tool '")):
        return "tools"
    return "conversation"


def measure(history: List[Dict[str, Any]], provider: str = "", model: str = "") -> Dict[str, Any]:
    first_conversation = next((i for i, m in enumerate(history) if m.get("role") != "system"), len(history))
    parts = {"instructions": 0, "memory": 0, "summary": 0, "conversation": 0, "tools": 0, "images": 0}
    messages = 0
    for index, message in enumerate(history):
        parts[_part(message, index, first_conversation)] += estimate_tokens(message.get("content", ""))
        parts["images"] += IMAGE_TOKENS * len(message.get("images") or [])
        if message.get("role") in ("user", "assistant") and not message.get("_tool_results"):
            messages += 1
    used = sum(parts.values())
    window = window_for(provider, model)
    percent = round(100 * used / window, 1) if window else 0.0
    config = settings()
    return {
        "used": used, "window": window, "percent": percent, "parts": parts, "messages": messages,
        "provider": provider, "model": model, "compacted": parts["summary"] > 0,
        "level": "full" if percent >= config["threshold"] else "warn" if percent >= 70 else "ok",
        "can_compact": messages > config["keep_last"] + 1, "auto_compact": config["auto_compact"],
        "threshold": config["threshold"], "keep_last": config["keep_last"], "estimate": True,
    }


# ---------------------------------------------------------------------------
# Compacting
# ---------------------------------------------------------------------------


def _split(history: List[Dict[str, Any]], keep_last: int) -> Tuple[List[Dict[str, Any]], str, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(leading system messages, previous summary text, older messages, recent messages kept word for word)."""
    first = next((i for i, m in enumerate(history) if m.get("role") != "system"), len(history))
    head = [m for m in history[:first] if not str(m.get("content", "")).startswith(SUMMARY_PREFIX)]
    previous = "\n".join(str(m.get("content", ""))[len(SUMMARY_PREFIX):].strip() for m in history[:first]
                         if str(m.get("content", "")).startswith(SUMMARY_PREFIX))
    body = history[first:]
    conversational = [i for i, m in enumerate(body) if m.get("role") in ("user", "assistant") and not m.get("_tool_results")]
    if len(conversational) <= keep_last:
        return head, previous, [], body
    cut = conversational[-keep_last]
    # Recent messages start on a user message, so the model never sees an answer without its question.
    while cut > 0 and body[cut].get("role") != "user":
        cut -= 1
    return head, previous, body[:cut], body[cut:]


def _transcript(messages: List[Dict[str, Any]], limit: int = 24_000) -> str:
    lines = []
    for message in messages:
        role = "Tool results" if message.get("_tool_results") else str(message.get("role", "")).capitalize()
        content = re.sub(r"\s+", " ", str(message.get("content", "")))
        if message.get("role") == "system":
            continue
        lines.append(f"{role}: {content[:1500 if role != 'Tool results' else 400]}")
    text = "\n".join(lines)
    return text if len(text) <= limit else "[…the very earliest part is left out]\n" + text[-limit:]


def summary_prompt(previous: str, transcript: str, focus: str = "") -> str:
    return (
        "Summarize the earlier part of a conversation between a person and their AI assistant, so the assistant can "
        "continue without the full text. Keep, as short bullets: what the person wants and their preferences; decisions "
        "made; facts, names, numbers, dates, file paths and code identifiers that matter; what the assistant promised or "
        "already did; open questions and unfinished tasks. Drop greetings, repetition and anything settled that no longer "
        "matters. Never invent anything. At most 300 words."
        + (f"\nThe person asked to keep especially: {focus.strip()[:300]}" if focus.strip() else "")
        + (f"\n\nSummary of what came before that:\n{previous}" if previous else "")
        + f"\n\nConversation:\n{transcript}\n\nReply with the bullet summary only."
    )


def offline_summary(previous: str, messages: List[Dict[str, Any]]) -> str:
    """No model answered: keep what the person asked, in order, and the first line of each answer."""
    bullets = [line for line in previous.splitlines() if line.strip()][:12]
    for message in messages:
        text = re.sub(r"\s+", " ", str(message.get("content", ""))).strip()
        if not text or message.get("_tool_results"):
            continue
        if message.get("role") == "user":
            bullets.append(f"- Asked: {text[:220]}")
        elif message.get("role") == "assistant":
            bullets.append(f"- Answered: {re.split(r'(?<=[.!?])\s', text)[0][:220]}")
    return "\n".join(bullets[-40:])


def _default_model(prompt: str) -> Tuple[str, str]:
    from model_roles import MODEL_ROLES

    run = MODEL_ROLES.run("fast_chat", prompt, system="detailed thinking off\nYou write faithful, compact summaries.", max_tokens=700)
    return run.text, run.label


def compact(service: Any, *, provider: str = "", model: str = "", keep_last: Optional[int] = None, focus: str = "",
            model_fn: Optional[Callable[[str], Tuple[str, str]]] = None, chat_store: Any = None, chat_id: str = "",
            reason: str = "owner") -> Dict[str, Any]:
    """Summarize the older part of this chat's model history. The stored transcript is untouched."""
    keep = keep_last if keep_last is not None else settings()["keep_last"]
    with _LOCK:
        history = service.conversation_history
        before = measure(history, provider, model)
        head, previous, older, recent = _split(history, max(2, int(keep)))
        if not older:
            raise ContextError(f"Nothing to compact yet — the chat is shorter than the {keep} most recent messages Nyx keeps word for word.")
        transcript = _transcript(older)
        source = "offline"
        try:
            text, source = (model_fn or _default_model)(summary_prompt(previous, transcript, focus))
            text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
            if len(text) < 20:
                raise ValueError("empty summary")
        except Exception:  # noqa: BLE001 - compaction must work without a model
            text, source = offline_summary(previous, older), "offline"
        summary = text[:6000]
        _UNDO[id(service)] = [dict(m) for m in history]
        service.conversation_history[:] = head + [{"role": "system", "content": f"{SUMMARY_PREFIX}\n{summary}"}] + recent
        after = measure(service.conversation_history, provider, model)
    kept = sum(1 for m in recent if m.get("role") in ("user", "assistant") and not m.get("_tool_results"))
    if chat_store is not None and chat_id and hasattr(chat_store, "set_compaction"):
        try:
            stored = [m for m in chat_store.messages(chat_id) if m.get("role") in ("user", "assistant")]
            chat_store.set_compaction(chat_id, summary, max(0, len(stored) - kept))
        except Exception:  # noqa: BLE001 - the live chat is compacted even if saving the note fails
            pass
    compacted = sum(1 for m in older if m.get("role") in ("user", "assistant") and not m.get("_tool_results"))
    result = {"before": before, "after": after, "summary": summary, "compacted_messages": compacted, "kept_messages": kept,
              "saved_tokens": max(0, before["used"] - after["used"]), "source": source, "reason": reason, "at": time.time()}
    _publish(chat_id, result)
    return result


def undo(service: Any, *, chat_store: Any = None, chat_id: str = "", provider: str = "", model: str = "") -> Dict[str, Any]:
    with _LOCK:
        snapshot = _UNDO.pop(id(service), None)
        if snapshot is None:
            raise ContextError("There's no compaction to undo in this chat since Nyx started.")
        service.conversation_history[:] = snapshot
    if chat_store is not None and chat_id and hasattr(chat_store, "clear_compaction"):
        try:
            chat_store.clear_compaction(chat_id)
        except Exception:  # noqa: BLE001
            pass
    after = measure(service.conversation_history, provider, model)
    _publish(chat_id, {"undone": True, "after": after})
    return {"after": after, "undone": True}


def can_undo(service: Any) -> bool:
    return id(service) in _UNDO


def maybe_auto_compact(service: Any, *, provider: str = "", model: str = "", chat_store: Any = None, chat_id: str = "",
                       emit: Optional[Callable[..., None]] = None) -> Optional[Dict[str, Any]]:
    """Before a turn: past the threshold, compact and say so. Never raises."""
    config = settings()
    try:
        if not config["auto_compact"]:
            return None
        current = measure(service.conversation_history, provider, model)
        if current["percent"] < config["threshold"] or not current["can_compact"]:
            return None
        if emit:
            emit("status", phase="think", text=f"Context is {current['percent']:.0f}% full — summarizing earlier messages to make room")
        result = compact(service, provider=provider, model=model, chat_store=chat_store, chat_id=chat_id, reason="auto")
        if emit:
            emit("context.compacted", compacted_messages=result["compacted_messages"], saved_tokens=result["saved_tokens"],
                 percent_before=result["before"]["percent"], percent_after=result["after"]["percent"], source=result["source"])
        return result
    except Exception:  # noqa: BLE001 - a turn never fails because compaction did
        return None


def _publish(chat_id: str, payload: Dict[str, Any]) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("context.changed", chat_id=chat_id, **{k: v for k, v in payload.items() if k in ("after", "undone", "reason", "compacted_messages", "saved_tokens")})
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# The tool and the skill
# ---------------------------------------------------------------------------

SKILL_INSTRUCTIONS = (
    "Use compact_context when the context bar says the chat is getting full (about 70 % or more), when the person asks to "
    "compact, tidy up or start fresh without losing the thread, or before a long new task in an old chat. Pass focus with "
    "anything that must survive word for word (a decision, a file path, a number). Afterwards tell the person in one "
    "sentence how many earlier messages became a summary and that Undo in the context bar brings them back. Never compact "
    "in the middle of a multi-step task you are still carrying out."
)


def tool_compact_context(focus: str = "", keep_last: int = 0) -> str:
    from tool_context import current

    ctx = current()
    if ctx is None:
        return "Error: compact_context only works inside a chat."
    try:
        import server

        service = server._get_service(ctx.chat_id)
        result = compact(service, keep_last=int(keep_last) if keep_last else None, focus=focus,
                         chat_store=server._shared_chat_store(), chat_id=ctx.chat_id, reason="nyx")
    except ContextError as error:
        return str(error)
    except Exception as error:  # noqa: BLE001
        return f"Error: could not compact ({type(error).__name__})."
    ctx.emit("context.compacted", compacted_messages=result["compacted_messages"], saved_tokens=result["saved_tokens"],
             percent_before=result["before"]["percent"], percent_after=result["after"]["percent"], source=result["source"])
    return (f"Compacted {result['compacted_messages']} earlier messages into a summary ({result['source']}); context went from "
            f"{result['before']['percent']:.0f}% to {result['after']['percent']:.0f}%. The last {result['kept_messages']} messages are "
            "kept word for word, and Undo in the context bar restores everything.")


def register_context_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="compact_context",
        description="Summarize the earlier part of this chat so the model's context has room again. Keeps recent messages "
                    "word for word; the person's transcript is not changed; undoable.",
        parameters=[ToolParam("focus", "string", "What must survive exactly (decisions, paths, numbers)", required=False),
                    ToolParam("keep_last", "integer", "How many recent messages to keep word for word (2-20)", required=False)],
        handler=tool_compact_context,
        category="general",
        label="Compacting the conversation",
    )
