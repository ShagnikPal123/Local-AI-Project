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

A chat holds 1M tokens, like Claude's long-context window (owner, 2026-10-11: "context fills up fast and has too few
of it — at least 1M"). Before, the meter and auto-compact used the answering model's own window, and Big Kahuna — the
default brain — fell through to 32k, so a chat compacted itself after a few long answers. Now:

* :data:`CHAT_WINDOW` is what one chat keeps before it needs compacting, whatever model answers.
* :func:`fit` hands each model call what that model can read: the instructions and the turn in progress always, the
  newest messages, and older ones that share words with the latest question. Nothing is thrown away.
* ``recall_chat`` lets the model search the whole saved chat for anything it doesn't see.
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
#: What one chat holds before it needs compacting — the same as Claude's 1M-token window.
CHAT_WINDOW = 1_048_576
#: Routers that pick a different model per turn: no single model window to show.
PLANNERS = ("", "auto", "identity0")
#: Share of a model's free room spent on older messages recalled because they match the latest question.
RECALL_SHARE = 0.25

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


def _ollama_window(model: str = "") -> int:
    """What Nyx really asks of a local model: ``num_ctx`` on every Ollama call (providers.ollama_provider).

    This was a fixed 8,192 while the provider asked for 32,768, so a fresh local chat — Nyx's instructions alone
    are ~15k tokens — read "186 % · almost full", and past six messages every turn auto-compacted for nothing.
    """
    try:
        from providers.ollama_provider import num_ctx

        return int(num_ctx(model or None))
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
        return _ollama_window(model)
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


def model_window(provider: str, model: str = "") -> int:
    """What one call to this provider reads. With no model named, its default one (Kimi's default has 8k, not 128k)."""
    name = (provider or "").strip().lower()
    if not model and name != "ollama":
        try:
            from model_hub import default_model

            model = default_model(name, "text") or ""
        except Exception:  # noqa: BLE001
            model = ""
    return window_for(name, model)


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
    reads = 0 if (provider or "").strip().lower() in PLANNERS else window_for(provider, model)
    window = max(CHAT_WINDOW, reads)
    percent = round(100 * used / window, 1) if window else 0.0
    config = settings()
    return {
        "used": used, "window": window, "percent": percent, "parts": parts, "messages": messages,
        # What the answering model reads in one call (0: Big Kahuna or Auto pick a model per turn). Past it, older
        # messages are recalled by relevance instead of sent whole (see fit).
        "model_window": reads, "fits_model": not reads or used <= reads,
        "provider": provider, "model": model, "compacted": parts["summary"] > 0,
        "level": "full" if percent >= config["threshold"] else "warn" if percent >= 70 else "ok",
        "can_compact": messages > config["keep_last"] + 1, "auto_compact": config["auto_compact"],
        "threshold": config["threshold"], "keep_last": config["keep_last"], "estimate": True,
    }


# ---------------------------------------------------------------------------
# Fitting one model call
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./\\:-]{2,}")
_STOP = frozenset("the and for are but not you your with this that have from was were what when where which who why how "
                  "can could would should will just about into than then them they there their here also some any all "
                  "out its our ours yes okay please thanks thank like make made more most very much does did done "
                  "has had been being use used using get got let lets need want".split())


def _cost(message: Dict[str, Any]) -> int:
    return estimate_tokens(message.get("content", "")) + IMAGE_TOKENS * len(message.get("images") or [])


def _clip(message: Dict[str, Any], tokens: int) -> Dict[str, Any]:
    """The start and end of a long message (a pasted file, a page of tool output), with a note where the middle was."""
    text = str(message.get("content", ""))
    chars = max(400, int(tokens * CHARS_PER_TOKEN) - 80)
    if len(text) <= chars:
        return message
    head = int(chars * 0.6)
    return {**message, "content": f"{text[:head]}\n[… {len(text) - chars:,} characters left out here to fit this model's "
                                  f"context …]\n{text[-(chars - head):]}"}


def _terms(text: str) -> set:
    return {w.lower().strip(".:-") for w in _WORD.findall(text)} - _STOP


def _k(tokens: int) -> str:
    return f"{tokens / 1_048_576:.0f}M" if tokens >= 1_000_000 else f"{tokens / 1000:.0f}k"


def fit(messages: List[Dict[str, Any]], window: int, *, reserve: Optional[int] = None) -> List[Dict[str, Any]]:
    """What one model call gets when the chat holds more than that model reads at once.

    Always kept: every system message (instructions, memory, skills, a summary) and the turn in progress — the latest
    question and any tool steps after it; very long ones are clipped in the middle only if they alone overflow. Then
    the newest messages word for word (about three quarters of the room, starting on a question), then older messages
    that share the most uncommon words with the latest question, in one recalled note. The model is told how much it
    isn't seeing and that ``recall_chat`` searches all of it. A chat that fits is returned unchanged.
    """
    if not messages or window <= 0:
        return messages
    reserve = reserve if reserve is not None else min(16_384, window // 8)
    budget = max(1024, window - reserve)
    costs = [_cost(m) for m in messages]
    if sum(costs) <= budget:
        return messages
    last_user = max((i for i, m in enumerate(messages) if m.get("role") == "user" and not m.get("_tool_results")),
                    default=len(messages) - 1)
    pinned = {i for i, m in enumerate(messages) if m.get("role") == "system" or i >= last_user}
    out: Dict[int, Dict[str, Any]] = {i: messages[i] for i in pinned}
    pinned_cost = sum(costs[i] for i in pinned)
    note_room = 400
    for i in sorted(pinned, key=lambda i: -costs[i]):
        if pinned_cost + note_room <= budget:
            break
        target = max(costs[i] - (pinned_cost + note_room - budget), 300)
        out[i] = _clip(messages[i], target)
        pinned_cost -= costs[i] - _cost(out[i])
    room = max(0, budget - pinned_cost - note_room)

    history = [i for i in range(len(messages)) if i not in pinned]
    keep: List[int] = []
    used = 0
    for i in reversed(history):
        if used + costs[i] > room * (1 - RECALL_SHARE):
            break
        keep.append(i)
        used += costs[i]
    keep.sort()
    while keep and messages[keep[0]].get("role") != "user":
        used -= costs[keep.pop(0)]
    first_kept = keep[0] if keep else last_user
    older = [i for i in history if i < first_kept]

    recalled: List[Tuple[int, str]] = []
    question = _terms(str(messages[last_user].get("content", ""))) if 0 <= last_user < len(messages) else set()
    if older and question:
        words = {i: _terms(str(messages[i].get("content", ""))) for i in older}
        seen: Dict[str, int] = {}
        for found in words.values():
            for word in found & question:
                seen[word] = seen.get(word, 0) + 1
        rarity = {word: 1.0 / (1 + count) for word, count in seen.items()}
        ranked = sorted(((sum(rarity[w] for w in words[i] & question), i) for i in older), reverse=True)
        left = room - used
        for score, i in ranked:
            if score <= 0 or left <= 200:
                break
            piece = str(_clip(messages[i], min(costs[i], 1500)).get("content", ""))
            cost = estimate_tokens(piece) + 6
            if cost <= left:
                role = "Tool results" if messages[i].get("_tool_results") else str(messages[i].get("role", "")).capitalize()
                recalled.append((i, f"[{role}, message {i}] {piece}"))
                left -= cost

    hidden = sum(costs[i] for i in older)
    note = (f"[Earlier in this chat] {len(older)} older messages (about {_k(hidden)} tokens) are saved but not shown in "
            f"full: this model reads {_k(window)} tokens at a time and the chat holds up to {_k(CHAT_WINDOW)}. Use "
            "recall_chat to search all of it before saying something wasn't discussed.")
    if recalled:
        note += "\nOlder parts that match the latest message:\n\n" + "\n\n".join(text for _, text in sorted(recalled))
    result: List[Dict[str, Any]] = []
    chosen = set(keep) | pinned
    for i, message in enumerate(messages):
        if i == first_kept and older:
            result.append({"role": "system", "content": note})
        if i in chosen:
            result.append(out.get(i, message))
    return result


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
    "A chat holds up to 1M tokens. Use compact_context when the context bar says it is getting full (about 70 % or "
    "more), when the person asks to "
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


def search_messages(messages: List[Dict[str, Any]], query: str, limit: int = 6) -> List[Tuple[int, Dict[str, Any]]]:
    """The saved messages sharing the most uncommon words with ``query``, best first (an exact phrase counts double)."""
    wanted = _terms(query)
    phrase = query.strip().lower()
    if not wanted and not phrase:
        return []
    words = [_terms(str(m.get("content", ""))) for m in messages]
    seen: Dict[str, int] = {}
    for found in words:
        for word in found & wanted:
            seen[word] = seen.get(word, 0) + 1
    scored = []
    for index, message in enumerate(messages):
        score = sum(1.0 / (1 + seen[w]) for w in words[index] & wanted)
        if len(phrase) >= 4 and phrase in str(message.get("content", "")).lower():
            score = score * 2 + 1
        if score > 0:
            scored.append((score, index))
    scored.sort(key=lambda pair: (-pair[0], -pair[1]))
    return [(index, messages[index]) for _, index in scored[:max(1, min(20, int(limit)))]]


def tool_recall_chat(query: str, limit: int = 6) -> str:
    from tool_context import current

    ctx = current()
    if ctx is None:
        return "Error: recall_chat only works inside a chat."
    try:
        import server

        stored = [m for m in server._shared_chat_store().messages(ctx.chat_id) if m.get("role") in ("user", "assistant")]
    except Exception as error:  # noqa: BLE001
        return f"Error: could not read this chat ({type(error).__name__})."
    hits = search_messages(stored, query, limit)
    if not hits:
        return f"Nothing in this chat's {len(stored)} saved messages matches {query!r}."
    lines = [f"{len(hits)} of {len(stored)} saved messages match {query!r} (best first):"]
    for index, message in hits:
        text = str(_clip(message, 900).get("content", ""))
        lines.append(f"\n[message {index + 1} of {len(stored)}, {message.get('role')}] {text}")
    return "\n".join(lines)


def register_context_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="recall_chat",
        description="Search everything said earlier in this chat — including parts the model no longer sees in full or "
                    "that were compacted into a summary — and return the matching messages word for word.",
        parameters=[ToolParam("query", "string", "Words or a phrase to look for"),
                    ToolParam("limit", "integer", "How many messages to return (1-20, default 6)", required=False)],
        handler=tool_recall_chat,
        category="general",
        label="Looking back through this chat",
    )

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
