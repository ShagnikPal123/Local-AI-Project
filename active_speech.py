"""Active speech: Nyx says what it understood, what it is doing, and when it is done.

The owner (2026-10-14): "Same as when you read my message and respond and then work … respond in the
beginning, middle and end … so it shows confirmation that the AI knows what you are asking … if a new item
is added to the queue it reads it, responds, and can split or do what it needs to balance and answer each one."

Status lines already said *what* was happening ("Reading your message", a tool's label), but in the app's
words, not as talk to the owner, and nothing confirmed the request was understood until the answer itself
arrived. A turn now carries short ``speech`` events, shown in the chat and read aloud on voice turns, so
text and voice say the same thing:

* ``start``  — as soon as a message arrives: what Nyx understood it is being asked. Rules write it at once
  and offline; a small model may write a better one-liner if it answers fast (``replace`` swaps it in).
* ``middle`` — a few updates while it works (tools, agents, a long wait), never more than one every few
  seconds and none once the answer is being written.
* ``end``    — on a longer turn, one line saying it is done and what it took.
* ``heard``  — a message that arrived while it was busy: what happens to it (next, alongside, folded in…).

Speech is a courtesy: nothing here may fail or slow a turn.
"""

from __future__ import annotations

import json
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from paths import data_path

SETTINGS_FILE = "active_speech.json"

DEFAULTS: Dict[str, Any] = {
    #: Speak at all (start, middle, end and heard lines).
    "enabled": True,
    #: Let a small, fast model word the first line when it answers in time; rules otherwise.
    "model_ack": True,
    #: Say "done" at the end of a longer turn.
    "end_note": True,
}

#: Middle lines: at least this many seconds apart, and at most this many a turn.
MIDDLE_GAP_SECONDS = 6.0
MAX_MIDDLE = 4
#: With nothing else to say for this long, say it is still working.
STILL_WORKING_SECONDS = 25.0
#: The end line is only worth saying for a turn this long, or one that used tools or agents.
END_NOTE_SECONDS = 8.0
#: How long the rule line waits for the model's line before it is shown itself.
RULE_WAIT_SECONDS = 0.8
MODEL_BUDGET_SECONDS = 2.5


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _settings_path():
    return data_path(SETTINGS_FILE)


def settings() -> Dict[str, Any]:
    try:
        saved = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    return {key: bool(saved.get(key, default)) for key, default in DEFAULTS.items()}


def save_settings(**changes: Any) -> Dict[str, Any]:
    current = settings()
    current.update({key: bool(value) for key, value in changes.items() if key in DEFAULTS and value is not None})
    _settings_path().write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


# ---------------------------------------------------------------------------
# Understanding a message, in a sentence
# ---------------------------------------------------------------------------

_SMALL_TALK = re.compile(r"^\s*(hi|hey|hello|yo|thanks|thank you|thx|ty|ok|okay|cool|nice|great|good (morning|night|evening)"
                         r"|bye|see you|lol|haha|yes|no|yep|nope|sure)\b[\s!.?]*\w{0,8}[\s!.?]*$", re.I)
_NAME = re.compile(r"^\s*(?:(?:hey|hi|ok(?:ay)?|so|um+|yo)[\s,]+)?(?:(?:nyx|ichos)\b[\s,:]*)?", re.I)
_POLITE_ASK = re.compile(r"^(?:can|could|would|will) you(?: please)?\s+|^please\s+|^i (?:want|need|would like|'d like) you to\s+"
                         r"|^go ahead and\s+|^help me(?: to)?\s+", re.I)
_WANT = re.compile(r"^i (?:want|need|would like|'d like)\s+", re.I)
_QUESTION = re.compile(r"^(what|who|whom|whose|when|where|why|how|which|is|are|am|was|were|do|does|did|can|could|"
                       r"should|would|will|have|has|had)\b", re.I)
_VERBS = frozenset("""add analyse analyze book build calculate change check clean compare convert create delete design draft
draw edit email explain find fix generate get give go help list look make move open organise organize plan play post
read remind remove rename reply research rewrite run save schedule search send set show sort start stop summarise
summarize take teach tell test translate try turn update upload watch write""".split())
_YOU_SUBJECT = frozenset("are can could did do have know need should think want were will would".split())

_SWAP = {"my": "your", "mine": "yours", "me": "you", "myself": "yourself", "i": "you", "i'm": "you're",
         "i've": "you've", "i'll": "you'll", "i'd": "you'd",
         "your": "my", "yours": "mine", "yourself": "myself", "you're": "I'm", "you've": "I've", "you'll": "I'll"}
_WORDS = re.compile(r"[A-Za-z']+|[^A-Za-z']+")


def _swap_pronouns(text: str) -> str:
    """Their words as Nyx would say them back: "rename my photos" → "rename your photos"."""
    tokens = _WORDS.findall(text)
    out: List[str] = []
    previous = ""
    for index, token in enumerate(tokens):
        low = token.lower()
        if not token.strip() or not low[0].isalpha():
            out.append(token)
            continue
        if low == "you":
            following = next((t.lower() for t in tokens[index + 1:] if t.strip()), "")
            out.append("I" if following in _YOU_SUBJECT else "me")
        elif low == "am":
            out.append("are" if previous == "i" else token)
        elif low in _SWAP:
            out.append(_SWAP[low])
        else:
            out.append(token)
        previous = low
    return "".join(out)


def _first_sentence(text: str, limit: int = 90) -> str:
    text = " ".join((text or "").split())
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    sentence = match.group(1) if match else text
    if len(sentence) > limit:
        sentence = sentence[:limit].rsplit(" ", 1)[0] + "…"
    return sentence.rstrip(" .!?,;:")


def understand(text: str) -> Tuple[str, str]:
    """``(kind, phrase)``: do (a task, phrased as Nyx would do it), want, ask (a question), say, or chat."""
    raw = (text or "").strip()
    if raw.lower().startswith("[fresh]"):
        raw = raw[len("[fresh]"):].strip()
    if not raw or _SMALL_TALK.match(raw):
        return "chat", ""
    body = _NAME.sub("", raw, count=1) or raw
    if body.startswith("/"):
        return "do", _first_sentence(body)
    polite = _POLITE_ASK.match(body)
    if polite:
        rest = body[polite.end():]
        if rest.rstrip().endswith("?") and _QUESTION.match(rest):
            return "ask", _first_sentence(body)
        return "do", _swap_pronouns(_first_sentence(rest))
    want = _WANT.match(body)
    if want:
        return "want", _swap_pronouns(_first_sentence(body[want.end():]))
    if body.rstrip().endswith("?") or _QUESTION.match(body):
        return "ask", _first_sentence(body)
    first = body.split(" ", 1)[0].lower().strip(",.!:")
    if first in _VERBS:
        return "do", _swap_pronouns(_first_sentence(body[0].lower() + body[1:]))
    return "say", _first_sentence(body)


def acknowledge(text: str) -> str:
    """The instant, offline first line; empty for small talk, which needs an answer, not a receipt."""
    kind, phrase = understand(text)
    if kind == "chat" or not phrase:
        return ""
    if kind == "do":
        return f"Got it — I'll {phrase}."
    if kind == "want":
        return f"Got it — you want {phrase}. On it."
    if kind == "ask":
        return f"Good question — looking into it: {phrase}?"
    return f"Got it: “{phrase}”. Working on it."


def _default_ask(prompt: str, budget_seconds: float) -> Optional[str]:
    from mini_model import quick_text

    return quick_text(prompt, budget_seconds, max_tokens=60)


def model_acknowledge(text: str, budget_seconds: float = MODEL_BUDGET_SECONDS,
                      ask: Optional[Callable[[str, float], Optional[str]]] = None) -> str:
    """One short sentence from a small model, or "" when nothing answers in time (or offline)."""
    prompt = (
        "You are Nyx, a personal assistant. The owner just sent the message below. Reply with ONE short sentence "
        "(at most 18 words) that tells them what you understood they want and what you will do first. Speak to them "
        "directly. Do not answer the request, do not ask a question, no emoji, no quotes.\n\n"
        f"Message: {(text or '')[:800]}"
    )
    try:
        reply = (ask or _default_ask)(prompt, budget_seconds) or ""
    except Exception:  # noqa: BLE001 - the rule line stands
        return ""
    line = " ".join(reply.strip().splitlines()[0].split()) if reply.strip() else ""
    line = line.strip("\"'“” ")
    if not line or len(line) > 200 or "<" in line:
        return ""
    return line if line[-1] in ".!?" else line + "."


# ---------------------------------------------------------------------------
# A message that arrives while Nyx is busy
# ---------------------------------------------------------------------------


def busy_ack(text: str, mode: str) -> str:
    """What Nyx says the moment a mid-task message arrives, by what will happen to it (turn_advice modes)."""
    kind, phrase = understand(text)
    task = f"I'll {phrase}" if kind == "do" and phrase else ""
    quoted = f"“{phrase or _first_sentence(text, 70)}”"
    if mode == "fold":
        return f"Got it — I'm adding {quoted} to what I'm doing now."
    if mode == "interrupt":
        return f"Okay — stopping this to {phrase} instead." if task else f"Okay — stopping this; {quoted} goes now."
    if mode == "parallel":
        return f"On it — {quoted} runs alongside this in a side chat."
    if mode == "branch":
        return f"Trying {quoted} as its own branch while this keeps going."
    if task:
        return f"Got it — next, {task}, right after this."
    return f"Got it — {quoted} is next, right after this."


# ---------------------------------------------------------------------------
# The turn's narrator
# ---------------------------------------------------------------------------

#: Statuses that are already said better elsewhere, or say nothing to the owner.
_QUIET_STATUS = re.compile(r"^(reading your message|answering|writing the answer|planning how to do this|starting|done|"
                           r"reviewing what the tools returned|refining your request|routing this)", re.I)

_TOOL_LINES = {
    "search_web": "Searching the web now.",
    "web_search": "Searching the web now.",
    "fetch_url": "Reading a page I found.",
    "read_url": "Reading a page I found.",
    "browse": "Looking at a page.",
    "read_file": "Reading your file.",
    "list_files": "Looking through your files.",
    "search_files": "Looking through your files.",
    "dispatch_agents": "Handing parts of this to the team.",
    "delegate": "Handing part of this to an agent.",
    "run_python": "Running some code to work it out.",
    "remember": "Saving that to memory.",
    "send_email": "Getting the email ready.",
    "screenshot": "Looking at the screen.",
}


def _tool_line(name: str, label: str) -> str:
    if name in _TOOL_LINES:
        return _TOOL_LINES[name]
    label = " ".join((label or "").split()).rstrip(".…")
    if label:
        return f"Now: {label[0].lower() + label[1:]}."
    return f"Using {name.replace('_', ' ')}." if name else ""


class Narrator:
    """Watches one turn's events and adds its ``speech`` events. Every method swallows its own errors."""

    def __init__(self, message: str, emit: Callable[[Dict[str, Any]], None], *,
                 options: Optional[Dict[str, Any]] = None,
                 ask: Optional[Callable[[str, float], Optional[str]]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.message = message or ""
        self._emit = emit
        self.options = options if options is not None else settings()
        self._ask = ask
        self._clock = clock
        self._lock = threading.Lock()
        self.started = clock()
        self.last_spoken = self.started
        self.middle = 0
        self.said: List[str] = []
        self.tools = 0
        self.agents: set = set()
        self.answering = False
        self.finished = False
        self.start_text = ""

    @property
    def on(self) -> bool:
        return bool(self.options.get("enabled", True))

    def _say(self, phase: str, text: str, **extra: Any) -> None:
        if not text or (self.finished and phase != "end"):
            return
        with self._lock:
            self.last_spoken = self._clock()
            self.said.append(text)
        try:
            self._emit({"type": "speech", "phase": phase, "text": text, **extra})
        except Exception:  # pragma: no cover - a UI problem must not reach the turn
            pass

    # --- start ------------------------------------------------------------------

    def start(self, wait: bool = False) -> None:
        """Say what was understood. With a model allowed, its line is used if it comes in time.

        ``wait`` runs it all on this thread (tests); a turn passes False so nothing waits on the model.
        """
        if not self.on:
            return
        rule = acknowledge(self.message)
        if not rule:
            return
        if not self.options.get("model_ack", True):
            self.start_text = rule
            self._say("start", rule, source="rules")
            return
        state = {"rule_shown": False, "done": False}
        guard = threading.Lock()

        def show_rule() -> None:
            with guard:
                if state["done"] or state["rule_shown"]:
                    return
                state["rule_shown"] = True
            self.start_text = rule
            self._say("start", rule, source="rules")

        def ask_model() -> None:
            line = model_acknowledge(self.message, ask=self._ask)
            with guard:
                state["done"] = True
                shown = state["rule_shown"]
            if not line:
                if not shown:
                    show_rule()
                return
            if self.finished:
                return
            if not shown:
                self.start_text = line
                self._say("start", line, source="model")
            elif not self.answering:
                self.start_text = line
                self._say("start", line, source="model", replace=True)

        if wait:
            ask_model()
            return
        timer = threading.Timer(RULE_WAIT_SECONDS, show_rule)
        timer.daemon = True
        timer.start()
        threading.Thread(target=ask_model, name="nyx-speech-ack", daemon=True).start()

    # --- middle -----------------------------------------------------------------

    def _middle(self, text: str) -> None:
        now = self._clock()
        if (not text or self.answering or self.finished or self.middle >= MAX_MIDDLE
                or now - self.last_spoken < MIDDLE_GAP_SECONDS or text in self.said):
            return
        self.middle += 1
        self._say("middle", text)

    def observe(self, event: Dict[str, Any]) -> None:
        """Feed every event of the turn here, in order."""
        try:
            self._observe(event)
        except Exception:  # pragma: no cover
            pass

    def _observe(self, event: Dict[str, Any]) -> None:
        kind = event.get("type", "")
        if kind == "speech" or not self.on:
            return
        if kind == "answer.delta" and event.get("text"):
            self.answering = True
            return
        if kind == "answer.reset":
            self.answering = False
            return
        if kind == "tool.start":
            self.tools += 1
            self._middle(_tool_line(str(event.get("name") or ""), str(event.get("label") or "")))
            return
        if kind == "agent.update" and event.get("name"):
            name = str(event["name"])
            if name not in self.agents and event.get("status") == "working":
                self.agents.add(name)
                self._middle(f"{name} is helping with this now.")
            return
        if kind == "status" and event.get("phase") == "agents":
            text = str(event.get("text") or "")
            if text.lower().startswith("bringing in "):
                self._middle(f"Bringing in {text[len('bringing in '):]} to help.")
            return
        if kind == "status" and event.get("text") and not _QUIET_STATUS.match(str(event["text"])):
            if str(event["text"]).lower().startswith("not giving up"):
                self._middle("Not giving up — doing it instead of saying I can't.")
                return
        if kind in ("done", "error", "stopped"):
            self.finish(event)
            return
        if self._clock() - self.last_spoken >= STILL_WORKING_SECONDS and not self.answering:
            self._middle("Still on it — this one is taking a little longer.")

    # --- end --------------------------------------------------------------------

    def finish(self, event: Dict[str, Any]) -> None:
        if self.finished:
            return
        self.finished = True
        if not self.on:
            return
        kind = event.get("type")
        if kind == "error":
            self._say("end", "I hit a problem and couldn't finish — the details are on screen.")
            return
        if kind == "stopped" or event.get("stopped"):
            self._say("end", "Stopped — what I had so far is kept.")
            return
        if not self.options.get("end_note", True):
            return
        seconds = self._clock() - self.started
        if seconds < END_NOTE_SECONDS and not self.tools and not self.agents:
            return
        parts = []
        if self.tools:
            parts.append(f"{self.tools} step{'s' if self.tools != 1 else ''}")
        if self.agents:
            parts.append(f"help from {', '.join(sorted(self.agents))}")
        took = f"{round(seconds)} seconds" if seconds < 90 else f"{round(seconds / 60)} minutes"
        detail = f" — {took}, {' and '.join(parts)}" if parts else f" — that took {took}"
        self._say("end", f"Done{detail}.")
