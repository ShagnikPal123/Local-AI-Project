"""Conversational tab editing (ROADMAP CC9, CC10).

"Make it green." "Call it Scratchpad." "Add a checklist." The user says what they
want changed and the tab changes.

Two paths, in this order:

1. **A deterministic reading for the common cases.** Colour, rename, and adding
   a known block are the overwhelming majority of edits, and they are
   unambiguous. Handling them locally makes the edit instant, free, and
   available offline — a model round trip to turn "make it green" into
   `{"accent": "#5ac08a"}` is waste.
2. **The model for everything else**, with its output validated through exactly
   the same rules as any other tab write. A model reply is a *proposal*, never a
   spec — it goes through `build_spec` like anything a user typed.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from dynamic_tabs import ALLOWED_CONNECTORS, BlockType, TabSpec, TabSpecError

# Colour words to design tokens. Deliberately small — a wrong guess here produces
# a colour the user did not ask for, which is worse than falling through to the
# model and getting it right.
_COLOURS: Dict[str, str] = {
    "green": "#5ac08a",
    "red": "#e07a7a",
    "orange": "#e0954a",
    "yellow": "#e0b45a",
    "amber": "#e0b45a",
    "blue": "#5a9ce0",
    "cyan": "#5ad6e0",
    "teal": "#5ad6e0",
    "purple": "#9184d9",
    "violet": "#9184d9",
    "pink": "#e07ac0",
    "grey": "#75798c",
    "gray": "#75798c",
    "white": "#e9e9ed",
}

# "change the background to green" is the phrasing people actually reach for, and
# neither "change" nor "background" was in this list - so the commonest colour
# edit took the slow trip through the model to arrive at the same answer.
_COLOUR_RE = re.compile(
    r"\b(?:make|turn|colour|color|paint|set|change|background|accent|theme)\b"
    r"[^.]*?\b(" + "|".join(_COLOURS) + r")\b",
    re.IGNORECASE,
)
_HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")
# "rename the tab to X" used to capture "the tab to X" as the name: nothing
# consumed the filler between the verb and the name, so the words the user used
# to refer to the tab ended up *being* the tab's name. The filler group is
# explicit now, and `to` is required after it so a bare "rename the tab" cannot
# swallow the rest of the sentence.
_RENAME_RE = re.compile(
    r"\b(?:rename|call|name|title)\s+"
    r"(?:(?:it|this|the|that)\s+)?(?:tab\s+)?"
    r"(?:to\s+)?"
    r"[\"'“]?([A-Za-z0-9][A-Za-z0-9 &'-]{0,38})[\"'”]?",
    re.IGNORECASE,
)

# Detail the local path cannot represent. A block title, a list of items, or an
# explicit "with ..." clause all carry information the regexes silently drop, so
# they must go to the model instead. Applying half of a detailed instruction and
# reporting success is worse than taking the slower, correct route: it produced
# a block called "Checklist" when the user asked for "Daily Review" with three
# named items, and looked like the edit had simply been ignored.
_DETAIL_RE = re.compile(
    r"\b(?:titled|called|named|labell?ed|with\s+items?|containing|items?\s*:|"
    r"for\s+\w+\s*,|include|including)\b",
    re.IGNORECASE,
)

# A name capture runs on through anything that looks like a word, so
# "call it Journal and make it green" would otherwise name the tab
# "Journal and make it green". Cut at the point a new clause starts.
_LABEL_TERMINATORS = (" and ", " then ", " also ", " plus ", ", ", " but ")


def _trim_label(raw: str) -> str:
    """Cut a captured name at the start of the next clause."""
    label = raw.strip()
    lowered = label.lower()
    cut = len(label)
    for terminator in _LABEL_TERMINATORS:
        found = lowered.find(terminator)
        if found != -1:
            cut = min(cut, found)
    return label[:cut].strip(" ,.")
_ADD_BLOCK_RE = re.compile(
    r"\badd\b[^.]*?\b(" + "|".join(b.value for b in BlockType) + r")\b",
    re.IGNORECASE,
)
_REMOVE_BLOCK_RE = re.compile(
    r"\b(?:remove|delete|drop|get rid of)\b[^.]*?\b(" + "|".join(b.value for b in BlockType) + r")\b",
    re.IGNORECASE,
)


def interpret_locally(spec: TabSpec, instruction: str) -> Optional[Dict[str, Any]]:
    """Read an unambiguous edit without a model call.

    Returns the changes, or None when the instruction is not one of the simple
    cases. None is not a failure — it means "ask the model", and guessing here
    would be worse than the round trip.
    """
    text = (instruction or "").strip()
    if not text:
        return None

    # Anything carrying structure the regexes cannot hold goes to the model.
    # This check is the difference between "the edit did nothing" and "the edit
    # took a second and was right".
    if _DETAIL_RE.search(text):
        return None

    changes: Dict[str, Any] = {}

    hex_match = _HEX_RE.search(text)
    if hex_match:
        changes["accent"] = hex_match.group(0)
    else:
        colour_match = _COLOUR_RE.search(text)
        if colour_match:
            changes["accent"] = _COLOURS[colour_match.group(1).lower()]

    rename = _RENAME_RE.search(text)
    if rename:
        label = _trim_label(rename.group(1))
        if label:
            changes["label"] = label

    remove = _REMOVE_BLOCK_RE.search(text)
    if remove:
        target = remove.group(1).lower()
        remaining = [b.as_dict() for b in spec.blocks if b.type.value != target]
        # Refuse to empty the tab; a tab with no blocks shows nothing.
        if remaining and len(remaining) != len(spec.blocks):
            changes["blocks"] = remaining
    elif _ADD_BLOCK_RE.search(text):
        block_type = _ADD_BLOCK_RE.search(text).group(1).lower()
        changes["blocks"] = [b.as_dict() for b in spec.blocks] + [
            {"type": block_type, "title": block_type.title(), "config": {}}
        ]

    return changes or None


def build_edit_prompt(spec: TabSpec, instruction: str) -> str:
    """Prompt asking the model to express an edit as a patch."""
    return (
        "A user wants to change one tab of their assistant app. Express the change "
        "as JSON containing only the fields that should change.\n\n"
        f"Current tab:\n{json.dumps(spec.as_dict(), indent=2)[:2000]}\n\n"
        f"They said: {instruction}\n\n"
        "Reply with JSON only, no prose. Use only these keys: label, icon, "
        "description, accent, blocks, connectors, background, theme. Omit anything unchanged. "
        "blocks replaces the whole list, so keep existing blocks you are not removing.\n"
        f"Block types: {', '.join(b.value for b in BlockType)}.\n"
        "Block configs: list {items: [..]}; chart {chart: {type: line|bar|scatter|area|function, title, x: [..], "
        "series: [{name, values: [..]}]} or {type: function, expressions: [\"sin(x)\"], from, to}}; "
        "tracker {unit, goal, kind: number|yes_no}; timer {mode: countdown|stopwatch|pomodoro, minutes, "
        "ai_prompt (what Nyx should do when it ends)}; ai_task {prompt, every_minutes (0 = only on demand, else >= 5)}; "
        "competition {game: tictactoe|connect4, difficulty: easy|hard}; game {game: snake|memory|tictactoe}.\n"
        "background: {kind: none|color|gradient|image, value: #rrggbb or https picture link, colors: [#rrggbb, #rrggbb], "
        "angle, dim: 0-0.9}. theme (the text boxes): {surface: solid|glass|clear, font: system|rounded|serif|mono, "
        "text: #rrggbb, radius: 0-28}. A game request should add a game block and usually a matching background and theme.\n"
        f"Connectors: {', '.join(sorted(ALLOWED_CONNECTORS))}.\n"
        "accent must be #rrggbb. icon must be a Phosphor name like ph-note.\n"
        "If the request cannot be expressed as a change to this tab, reply "
        '{"error": "why not"}.'
    )


def parse_edit_reply(reply: str) -> Dict[str, Any]:
    """Parse a model edit reply into changes, or raise.

    A model reply is a proposal, not a spec. Whatever comes back here still goes
    through the same validation as any other tab write.
    """
    text = (reply or "").strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start:end + 1]

    try:
        data = json.loads(text)
    except Exception as error:
        raise TabSpecError("The model did not return a usable edit.") from error

    if not isinstance(data, dict):
        raise TabSpecError("The model did not return a usable edit.")
    if data.get("error"):
        raise TabSpecError(str(data["error"])[:200])

    allowed = {"label", "icon", "description", "accent", "blocks", "connectors", "background", "theme"}
    changes = {k: v for k, v in data.items() if k in allowed}
    if not changes:
        raise TabSpecError("The model did not name anything to change.")
    return changes
