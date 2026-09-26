"""Fast-response routing (ROADMAP W1-W4).

Most turns are simple. Sending them through the full pipeline — an 8KB system
prompt carrying every tool schema, plus a tool loop that costs a second round
trip — makes a one-line answer as expensive as a refactor.

This module decides, per turn, whether the cheap path is safe. The rule is
deliberately conservative: a turn takes the fast path only when nothing suggests
it needs tools, research, code, or multi-step reasoning. Getting this wrong in the
cautious direction costs latency; getting it wrong in the other direction costs a
correct answer, which is worse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from task_analyzer import TaskAnalyzer, TaskComplexity


class SpeedMode(Enum):
    """How the speed decision is made for a turn."""

    AUTO = "auto"  # Decide per turn. The default.
    FAST = "fast"  # Always take the cheap path.
    FULL = "full"  # Always take the full pipeline.


@dataclass(frozen=True)
class SpeedDecision:
    """The outcome of a speed decision, with the reason for it."""

    fast: bool
    reason: str

    @property
    def mode_label(self) -> str:
        return "fast" if self.fast else "full"


# Anything here means the turn may need tools, fresh data, or real reasoning.
# Kept explicit rather than derived so the behaviour is auditable.
_NEEDS_FULL_PIPELINE = (
    # live data — the fast path has no tools, so these must not take it
    "latest", "recent", "current", "today", "yesterday", "this week",
    "this year", "right now", "news", "price", "stock", "weather",
    "who won", "release date", "search", "look up", "google",
    # Questions about people and roles are the classic staleness trap: the answer
    # was true when the model was trained and is not now. This is exactly the
    # reported "president from three years ago" bug (ROADMAP D1), so any such
    # question takes the full pipeline and gets to search. Note TaskAnalyzer
    # classifies bare "who" as SIMPLE — that is right for effort, wrong for
    # freshness, so this list overrides it.
    "who is", "who's", "who are", "president", "prime minister", "chancellor",
    "ceo of", "leader of", "champion", "winner", "election", "mayor",
    "how old is", "net worth", "still alive", "married to",
    # code
    "code", "function", "class ", "def ", "import ", "bug", "error",
    "traceback", "exception", "refactor", "debug", "test", "compile",
    "stack trace", "syntax", "install", "dependency",
    # machine / file actions
    "file", "folder", "directory", "open ", "run ", "execute", "screenshot",
    "clipboard", "browser", "download", "delete", "install",
    # Changing the model or provider needs the switch_model tool, and the fast
    # path has no tools at all. "switch to groq" is short enough to look trivial,
    # so it took the fast path and the model answered - correctly, for that path -
    # that it had no way to change providers. The request reads as randomly
    # refused, because whether it worked depended on how long the sentence was.
    "switch to", "switch model", "switch provider", "change model",
    "change provider", "use gemini", "use groq", "use ollama", "use claude",
    "use openai", "different model", "another model", "go offline", "go local",
    "which model", "what model", "which provider",
    # multi-step reasoning
    "analyze", "compare", "design", "architecture", "plan", "strategy",
    "step by step", "walk me through", "pros and cons", "trade-off",
    "why does", "how does", "explain how",
)

# Actions that only a tool can carry out, matched as whole words ("tab" must not
# fire on "table"). Plan Null N2: "can you send me an email?" is 26 characters, so
# it took the fast path, and the tool-less model truthfully said it could not send
# email while the owner's Gmail account sat configured one step away. Same class
# of bug as "switch to groq" above: whether it worked depended on sentence length.
_ACTION_WORDS = re.compile(
    r"\b(?:e-?mails?|gmail|outlook|inbox|mailbox|send|sending|reply|forward|"
    r"calendar|remind(?:er|ers)?|schedule|meeting|appointment|event|"
    r"notes?|notebook|tabs?|remember|forget|agents?|sub-?agents?|skills?|connectors?|"
    r"spreadsheet|excel|sheets?|docs?|slides?|pdf|"
    r"buy|sell|trade|portfolio|"
    r"play|pause|volume|mute|lock|shut\s?down|restart|timer|alarm)\b",
    re.IGNORECASE,
)

# A turn longer than this is unlikely to be a quick question.
_MAX_FAST_CHARS = 320

# At or under this length, a turn that cleared every marker above is a greeting,
# an acknowledgement, or trivial arithmetic. Safe to answer without tools.
_TRIVIAL_LENGTH_CHARS = 40


class FastResponsePolicy:
    """Decide whether a turn can take the cheap path."""

    def __init__(self, analyzer: Optional[TaskAnalyzer] = None) -> None:
        self.analyzer = analyzer or TaskAnalyzer()

    def decide(self, message: str, mode: SpeedMode = SpeedMode.AUTO) -> SpeedDecision:
        """Return whether this turn should use the fast path, and why."""
        if mode is SpeedMode.FAST:
            return SpeedDecision(True, "forced by mode=fast")
        if mode is SpeedMode.FULL:
            return SpeedDecision(False, "forced by mode=full")

        text = (message or "").strip()
        if not text:
            return SpeedDecision(False, "empty message")

        if len(text) > _MAX_FAST_CHARS:
            return SpeedDecision(False, f"long input ({len(text)} chars)")

        lowered = text.lower()
        for marker in _NEEDS_FULL_PIPELINE:
            if marker in lowered:
                return SpeedDecision(False, f"needs full pipeline: {marker!r}")
        action = _ACTION_WORDS.search(text)
        if action:
            return SpeedDecision(False, f"asks for an action: {action.group(0).lower()!r}")

        # Attachments, code fences, and file paths all imply real work.
        if "```" in text or "\\" in text or "/" in text and "?" not in text:
            return SpeedDecision(False, "contains code or a path")

        # A very short turn that cleared every marker above is a greeting, an
        # acknowledgement, or trivial arithmetic. TaskAnalyzer calls these
        # "moderate" because they match none of its SIMPLE keywords, which would
        # send "thanks!" through the full pipeline. Short-circuit before it.
        if len(text) <= _TRIVIAL_LENGTH_CHARS:
            return SpeedDecision(True, f"trivially short ({len(text)} chars)")

        try:
            analysis = self.analyzer.analyze(text)
        except Exception:
            # A classifier failure must not deny service; take the safe path.
            return SpeedDecision(False, "analyzer unavailable")

        if analysis.complexity is TaskComplexity.SIMPLE:
            return SpeedDecision(True, "classified simple")

        return SpeedDecision(False, f"classified {analysis.complexity.value}")


# The lean system prompt for fast turns. The full prompt is ~8KB, almost all of it
# tool schemas the fast path cannot use anyway.
FAST_SYSTEM_PROMPT = (
    "You are Nyx Ichos, a local-first AI assistant created by Shagnik. "
    "This is a quick-answer turn: reply directly and concisely. Keep it to a few "
    "sentences unless the user asked for a specific length, a list or a count — then "
    "give all of it, never a shortened version. Tools are not loaded on this turn, but Nyx has them: "
    "email, calendar, notes, files, apps, the computer, the web, tabs, agents and settings. If the "
    "request needs any of those, current data, or code execution, reply with exactly "
    "NEEDS_FULL_PIPELINE and nothing else. Never tell the user you cannot do something."
)

# Sentinel the model returns when it realises the cheap path cannot serve the turn.
ESCALATION_SENTINEL = "NEEDS_FULL_PIPELINE"

# A fast-path model that says it cannot act is wrong about Nyx: the full pipeline
# has the tools. Small models often answer that way instead of using the sentinel
# ("I cannot send emails… I'm an AI text assistant without capabilities to…").
_CAPABILITY_REFUSAL = re.compile(
    r"\b(?:i|nyx)\s*(?:can(?:not|'t|’t)|am\s+(?:not\s+able|unable)|(?:'m|’m)\s+(?:not\s+able|unable)|"
    r"do(?:n't|n’t|\s+not)\s+have|have\s+no)\b[^.!?\n]{0,90}?"
    r"\b(?:send|e-?mail|access|open|browse|search|tools?|accounts?|internet|real[- ]time|files?|"
    r"calendar|computer|device|capabilit\w*|abilit\w*|integrations?|connect\w*|interface)\b"
    r"|\b(?:without|lack(?:ing)?)\s+(?:the\s+)?(?:capabilit\w*|abilit\w*|access|tools?)\b"
    r"|\bisn['’]t\s+available\s+in\s+my\b",
    re.IGNORECASE,
)


def wants_escalation(response: str) -> bool:
    """True when a fast-path reply signalled, or showed, that it needs the full pipeline."""
    text = response or ""
    return ESCALATION_SENTINEL in text or bool(_CAPABILITY_REFUSAL.search(text))
