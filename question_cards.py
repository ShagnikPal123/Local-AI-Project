"""Questions the owner can answer with a click (Project Null N85).

The owner: "add questions that the user can click and send to the ai so the ai
basically makes a question and a list of answers and what each means as well as a
box for typing if the user had a different approach they thought of".

So a question is part of the answer, not a separate mechanism: the model writes a
fenced ```question block of JSON, the chat renders it as a card with one button per
answer — each with what choosing it would mean — plus a box for an approach the
model did not think of. Clicking sends the answer as the next message, so nothing
new is needed on the wire and it works in every mode, including the quick path.

This module owns the shape of that block: the rule the model is given, and the
parser both the tests and any backend reader use. The card itself is
``components/chat/QuestionCard.tsx``.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

#: The block as it appears in an answer. Some models write <question>…</question>
#: instead of the fenced form; the chat renders both, so both are read here too.
BLOCK_RE = re.compile(r"```(?:question|ask)\s*\n(.*?)```|<questions?>\s*(.*?)\s*</questions?>",
                      re.DOTALL | re.IGNORECASE)

MAX_OPTIONS = 6

#: Added to the system prompt (chat_service). It is inserted as a value, not as part of
#: that f-string literal, so the braces here are single — doubling them would put
#: "{{" in front of the model.
FORMAT_RULE = (
    "11. When a choice is genuinely the user's to make — and only then — ask it as a card instead of a paragraph: "
    "a fenced block with the language `question` containing only JSON:\n"
    '   {"question": "...", "options": [{"label": "short answer", "means": "what picking this leads to", '
    '"recommended": true}], "multi": false, "other": "what the free-text box invites"}\n'
    "   Two to four options, the one you would pick first and marked recommended, each with what it means in plain "
    "words. The chat shows buttons and a box for an approach you did not list; the user's click comes back as their "
    "next message. Never ask about something you can look up or sensibly assume, and never put more than two cards "
    "in one answer."
)


def _clean_option(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        label, means = raw, ""
    elif isinstance(raw, dict):
        label = str(raw.get("label") or raw.get("answer") or raw.get("title") or "").strip()
        means = str(raw.get("means") or raw.get("meaning") or raw.get("detail") or raw.get("description") or "").strip()
    else:
        return None
    label = str(label).strip()
    if not label:
        return None
    option: Dict[str, Any] = {"label": label[:120], "means": means[:400]}
    if isinstance(raw, dict) and raw.get("recommended"):
        option["recommended"] = True
    return option


def parse(source: str) -> Optional[Dict[str, Any]]:
    """One question block's JSON as a validated card, or None when it is unusable."""
    try:
        data = json.loads(source)
    except ValueError:
        return None
    if isinstance(data, list):  # some models send a list of questions
        return next((card for card in (_card(item) for item in data) if card), None)
    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        return next((card for card in (_card(item) for item in data["questions"]) if card), None)
    return _card(data)


def _card(data: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict):
        return None
    question = str(data.get("question") or data.get("title") or "").strip()
    options: List[Dict[str, Any]] = []
    for raw in list(data.get("options") or data.get("answers") or [])[:MAX_OPTIONS]:
        option = _clean_option(raw)
        if option and option["label"].lower() not in {o["label"].lower() for o in options}:
            options.append(option)
    if not question or len(options) < 2:
        return None
    return {
        "question": question[:400],
        "options": options,
        "multi": bool(data.get("multi") or data.get("multiple")),
        "other": str(data.get("other") or "Something else — tell me your approach")[:160],
    }


def find_all(text: str) -> List[Dict[str, Any]]:
    """Every usable question card in an answer, whichever form the model wrote."""
    cards = []
    for match in BLOCK_RE.finditer(text or ""):
        card = parse(match.group(1) or match.group(2) or "")
        if card:
            cards.append(card)
    return cards


def answer_message(card: Dict[str, Any], chosen: List[str], other: str = "") -> str:
    """The message a click sends back — the question, the choice, and anything typed."""
    lines = [f"**{card['question']}**"]
    picked = [label for label in chosen if label]
    if picked:
        meanings = {o["label"]: o.get("means", "") for o in card["options"]}
        for label in picked:
            means = meanings.get(label, "")
            lines.append(f"→ {label}" + (f" ({means})" if means else ""))
    if other.strip():
        lines.append(f"→ My own approach: {other.strip()}")
    return "\n".join(lines)
