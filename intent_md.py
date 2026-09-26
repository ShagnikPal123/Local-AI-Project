"""intent.md — Anthropic's "capture intent first" artifact, understood by Nyx (Request H14).

"Add intent.md from Anthropocene and make sure the AI understands." Anthropic's AI-native SDLC
playbook starts every feature or fix with a short, version-controlled ``intent.md``: the ask, why it
matters, and its limits, written *before* anyone designs or builds. The person with the idea drafts it
with the AI (the AI acts as an analyst and asks questions), the product owner corrects and accepts it,
and only then does design begin. CLAUDE.md / AGENTS.md tell an agent how to work; intent.md tells it
what the work is for.

Nyx uses it in three places:

* the built-in skill **Capture intent** (``skills.BUILTIN_SKILLS``) and the ``/intent`` command, so
  asking "write an intent.md for…" gets the analyst questions first and the template after;
* the Code tab: :func:`read_for` finds the nearest ``intent.md`` for a file or folder, and every edit
  or new-files proposal is written against it; Start From Scratch folders get the template;
* :data:`TEMPLATE`, the sections in the order the playbook uses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

SECTIONS = ("Problem", "Proposed outcome", "Affected users and systems", "Constraints", "Open questions")

TEMPLATE = """# Intent: {title}

- **Author:** {author}
- **Status:** draft

## Problem
What is happening today, who it hurts, and how we know.

## Proposed outcome
What is true once this is done — described as a result, not a design.

## Affected users and systems
Who will notice the change, and which parts of the product or code it touches.

## Constraints
Limits it has to respect: time, money, privacy, platforms, things that must not change.

## Open questions
What still needs an answer before design starts.
"""

SKILL_INSTRUCTIONS = (
    "intent.md is the first artifact of a change: what is being asked, why, and within what limits, before any "
    "design or code. Work as an analyst first. Ask short questions until you know: the problem today and who feels "
    "it; the outcome that would count as success; which users and systems are affected; the constraints (time, "
    "budget, privacy, platforms, what must not change); and what is still unknown. Do not put a design or solution "
    "in it. Then write the file with exactly these parts: '# Intent: <title>', Author, Status (draft), ## Problem, "
    "## Proposed outcome, ## Affected users and systems, ## Constraints, ## Open questions. Keep it under a page, in "
    "the originator's plain words. Say that the product owner (usually the user) should correct and accept it before "
    "design starts, and that later changes to it should be rare and noted. When an intent.md exists for the work you "
    "are doing, read it first, keep every proposal inside its constraints, and point out a request that contradicts "
    "it instead of silently following either."
)


def template(title: str = "", author: str = "") -> str:
    return TEMPLATE.format(title=(title or "What this is").strip()[:80], author=(author or "you").strip()[:60])


def read_for(path: str, stop_at: Optional[str] = None, limit: int = 6000) -> str:
    """The nearest intent.md at or above ``path`` (never above ``stop_at``), or an empty string."""
    try:
        current = Path(path).resolve()
    except OSError:
        return ""
    folder = current if current.is_dir() else current.parent
    boundary = Path(stop_at).resolve() if stop_at else None
    for candidate in [folder, *folder.parents]:
        for name in ("intent.md", "INTENT.md", "Intent.md"):
            file = candidate / name
            if file.is_file():
                try:
                    return file.read_text(encoding="utf-8", errors="replace")[:limit]
                except OSError:
                    return ""
        if boundary is not None and candidate == boundary:
            break
    return ""
