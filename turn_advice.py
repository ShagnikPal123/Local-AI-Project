"""What to do with a message typed while Nyx is still answering (Request G12).

The owner: "if I type something while another prompt is going then… make a
second button which I can click to queue or make it run or interrupt or have
another AI run at the same time or branch it. Make the AI decide."

Four choices, one recommended:

* **queue** — send it when the current answer finishes (a follow-up that needs that answer).
* **interrupt** — stop the current answer and send this now (a correction: "no, instead…").
* **parallel** — another AI answers it at the same time, in a side chat (an unrelated task).
* **branch** — a branch chat with this message, while the current one keeps going
  (another way to do the same thing: "what if we tried…").
* **fold** — add it to the task running now ("also make it blue", "make sure it covers…"), so one answer
  covers both (active_speech.py). Only a turn that is still listening can take it; otherwise it queues.

Rules decide first; they are instant and work offline. When they are unsure a
small model call gets 3 seconds to decide, and the rules' pick stands if it is slow.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

MODES = ("queue", "interrupt", "parallel", "branch", "fold")

REASONS = {
    "queue": "Sounds like a follow-up, so it waits for the current answer.",
    "interrupt": "Sounds like a correction, so the current answer stops.",
    "parallel": "A separate task, so another AI can do it at the same time.",
    "branch": "Another way to do the same thing, so it gets its own branch.",
    "fold": "Adds to what it is doing now, so it is folded into the current task.",
}

_INTERRUPT = re.compile(r"^\s*(stop|wait|no\b|nope|cancel|hold on|never ?mind|actually|wrong|not that|don'?t|scratch that)"
                        r"|\b(instead|i meant|that'?s wrong|you misunderstood|forget (it|that))\b", re.I)
_QUEUE = re.compile(r"^\s*(then|after( that)?|and then|next|once (you'?re|it'?s) done|when (you'?re|it'?s) done|"
                    r"afterwards|after you finish)\b|\b(when you'?re done|after that|once finished|with (that|the result))\b", re.I)
_FOLD = re.compile(r"^\s*(also|plus|and also|oh,? and|and make|make sure|don'?t forget|remember to|be sure|but make|"
                   r"include|and include|add)\b|\b(as well|too)\s*[.!]?\s*$", re.I)
_FOLD_SURE = re.compile(r"^\s*(make sure|don'?t forget|remember to|be sure|and also|also)\b", re.I)  # checked before "don't…" interrupts
_BRANCH = re.compile(r"\b(what if|alternatively|another (way|version|approach)|try (it )?(with|using|a different)|"
                     r"compare (it )?(with|to)|in parallel version|other option)\b", re.I)
_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {"the", "and", "for", "with", "that", "this", "you", "your", "can", "please", "make", "what", "how", "are", "was"}


def _overlap(a: str, b: str) -> float:
    wa = {w for w in _WORD.findall(a.lower()) if w not in _STOP}
    wb = {w for w in _WORD.findall(b.lower()) if w not in _STOP}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def rule_advice(text: str, running: str) -> Dict[str, Any]:
    """Instant, offline decision with a confidence the caller can act on."""
    text = (text or "").strip()
    overlap = _overlap(text, running or "")
    if _FOLD_SURE.search(text):
        return {"mode": "fold", "confidence": 0.8}
    if _INTERRUPT.search(text):
        return {"mode": "interrupt", "confidence": 0.85}
    if _FOLD.search(text) and not _QUEUE.search(text):
        return {"mode": "fold", "confidence": 0.8 if (overlap >= 0.1 or _FOLD_SURE.search(text)) else 0.6}
    if _QUEUE.search(text):
        return {"mode": "queue", "confidence": 0.8}
    if _BRANCH.search(text):
        return {"mode": "branch", "confidence": 0.75 if overlap >= 0.2 else 0.55}
    words = len(text.split())
    if overlap < 0.12 and words >= 4:
        return {"mode": "parallel", "confidence": 0.65}
    if overlap >= 0.35:
        return {"mode": "queue", "confidence": 0.55}
    return {"mode": "queue", "confidence": 0.4}


def _model_advice(text: str, running: str, budget_seconds: float) -> Optional[str]:
    prompt = (
        "An assistant is still answering request A. The user just typed B. Choose what to do with B:\n"
        "queue = B needs A's answer first; interrupt = B corrects or replaces A; "
        "parallel = B is unrelated and can run at the same time; branch = B is another way to do A; "
        "fold = B adds a detail or requirement to A, so one answer should cover both.\n"
        f"A: {running[:600]!r}\nB: {text[:600]!r}\nReply with one word: queue, interrupt, parallel, branch or fold."
    )

    from mini_model import quick_text

    found = re.search(r"(queue|interrupt|parallel|branch)", (quick_text(prompt, budget_seconds, max_tokens=10) or "").lower())
    return found.group(1) if found else None


def advise(text: str, running: str, use_model: bool = True, budget_seconds: float = 3.0,
           listening: bool = True) -> Dict[str, Any]:
    """``listening`` is whether the running turn can still take a note; when it can't, "fold" becomes "queue"."""
    decision = rule_advice(text, running)
    source = "rules"
    if use_model and decision["confidence"] < 0.7 and (text or "").strip():
        picked = _model_advice(text, running, budget_seconds)
        if picked in MODES:
            decision = {"mode": picked, "confidence": 0.75}
            source = "model"
    if decision["mode"] == "fold" and not listening:
        decision = {"mode": "queue", "confidence": decision["confidence"]}
    return {**decision, "source": source, "reason": REASONS[decision["mode"]]}
