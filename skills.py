"""Skills — packaged capability the agent loads on demand (ROADMAP U1-U5).

A skill is a named set of instructions plus the triggers that say when it is
relevant. When a turn matches, the skill's instructions are attached to the
prompt; when it does not, the skill costs nothing. That is what makes a large
library affordable — the agent carries the index, not the contents.

**A skill is instructions, not code.** It tells the model how to approach
something; it never contains anything executed. A skill the user described in
conversation is written by the agent and stored as text, so an untrusted
description can at worst produce bad advice, never arbitrary execution. This is
the same line drawn for tabs (section CC), widgets, and the overlay.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from paths import data_path

_WORD_RE = re.compile(r"[a-z][a-z0-9_+-]{1,}")

# A skill needs this many trigger hits before it is attached. One incidental word
# match is not evidence the skill is relevant, and attaching the wrong skill is
# worse than attaching none — it steers the answer in the wrong direction.
_MIN_TRIGGER_HITS = 1

# Never attach more than this in one turn. Skills compete for the model's
# attention, and five sets of instructions cancel each other out.
_MAX_ATTACHED = 3


class SkillError(Exception):
    """Raised when a skill is malformed."""


@dataclass
class Skill:
    skill_id: str
    name: str
    description: str
    instructions: str
    # Words or phrases that make this skill relevant to a turn.
    triggers: List[str] = field(default_factory=list)
    # "builtin" ships with the app; "conversation" was written by the agent for
    # this user; "imported" came from a file.
    source: str = "builtin"
    enabled: bool = True
    author: str = ""
    uses: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "instructions": self.instructions,
            "triggers": list(self.triggers),
            "source": self.source,
            "enabled": self.enabled,
            "author": self.author,
            "uses": self.uses,
        }

    def match_score(self, text: str) -> int:
        """How many distinct triggers this turn hits."""
        lowered = (text or "").lower()
        return sum(1 for trigger in self.triggers if trigger.lower() in lowered)


BUILTIN_SKILLS: List[Dict[str, Any]] = [
    {
        "name": "Debugging",
        "description": "Reproduce, isolate, and fix a bug rather than guessing at it.",
        "triggers": ["bug", "error", "traceback", "exception", "crash", "broken",
                     "not working", "fails", "stack trace"],
        "instructions": (
            "Reproduce the problem before proposing a fix. State what you observed, "
            "what you expected, and the smallest change that closes the gap. If you "
            "cannot reproduce it, say so rather than guessing. Add a regression test "
            "that fails before the fix and passes after."
        ),
    },
    {
        "name": "Code review",
        "description": "Review a change for correctness, security, and clarity.",
        "triggers": ["review", "look over", "check my code", "feedback on", "pull request"],
        "instructions": (
            "Look for correctness bugs first, then security issues, then clarity. "
            "For each finding give the concrete failure: the input or state that "
            "produces the wrong result. Do not pad the list with style preferences, "
            "and say plainly when something is fine."
        ),
    },
    {
        "name": "Explaining",
        "description": "Explain a concept at the right level without condescending.",
        "triggers": ["explain", "what is", "how does", "help me understand", "eli5",
                     "what does", "why does"],
        "instructions": (
            "Start with the one-sentence answer, then build up. Use a concrete "
            "example before the abstraction. Name what the thing is NOT, where that "
            "is a common confusion. Do not pad with caveats."
        ),
    },
    {
        "name": "Maths",
        "description": "Work a mathematical problem carefully and show the steps.",
        "triggers": ["solve", "calculate", "equation", "integral", "derivative",
                     "algebra", "geometry", "probability", "sqrt", "factor"],
        "instructions": (
            "Show the working, not just the answer. State any assumption you had to "
            "make. Check the result by a second route where one is cheap. If the "
            "problem is ambiguous, solve the most likely reading and say which you chose."
        ),
    },
    {
        "name": "Writing",
        "description": "Draft or edit prose with a specific audience in mind.",
        "triggers": ["write", "draft", "essay", "email", "rewrite", "edit this",
                     "proofread", "summarise", "summarize"],
        "instructions": (
            "Ask who it is for if that is unclear and it changes the draft. Prefer "
            "concrete nouns and active verbs. Cut hedging. Match the length to the "
            "purpose rather than filling space."
        ),
    },
    {
        "name": "Research",
        "description": "Answer from current sources rather than memory.",
        "triggers": ["latest", "current", "recent", "today", "news", "who is",
                     "look up", "find out", "search for"],
        "instructions": (
            "Search before answering anything time-sensitive; your training data is "
            "stale by definition. Cite what you found. Where sources disagree, say so "
            "rather than picking one silently. Give the date of the information."
        ),
    },
]


class SkillStore:
    """The skill library: built-ins plus whatever the user has added."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_path("skills.json")
        self._skills: Dict[str, Skill] = {}
        self._lock = threading.Lock()
        self._install_builtins()
        self._load()

    # --- setup --------------------------------------------------------------

    def _install_builtins(self) -> None:
        for spec in BUILTIN_SKILLS:
            skill = Skill(
                skill_id=f"builtin-{spec['name'].lower().replace(' ', '-')}",
                name=spec["name"],
                description=spec["description"],
                instructions=spec["instructions"],
                triggers=list(spec["triggers"]),
                source="builtin",
            )
            self._skills[skill.skill_id] = skill

    def _load(self) -> None:
        """Load user skills, and any enable/disable state for built-ins."""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        for entry in raw.get("skills", []):
            try:
                skill = Skill(
                    skill_id=str(entry["id"]),
                    name=str(entry["name"]),
                    description=str(entry.get("description", "")),
                    instructions=str(entry.get("instructions", "")),
                    triggers=[str(t) for t in entry.get("triggers", [])],
                    source=str(entry.get("source", "imported")),
                    enabled=bool(entry.get("enabled", True)),
                    author=str(entry.get("author", "")),
                    uses=int(entry.get("uses", 0)),
                )
            except Exception:
                continue
            # A stored built-in only carries its enabled state and use count; the
            # shipped text always wins, so an app update can improve a built-in.
            existing = self._skills.get(skill.skill_id)
            if existing is not None and existing.source == "builtin":
                existing.enabled = skill.enabled
                existing.uses = skill.uses
            else:
                self._skills[skill.skill_id] = skill

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"skills": [s.as_dict() for s in self._skills.values()]}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    # --- reads --------------------------------------------------------------

    def list_skills(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [s.as_dict() for s in
                    sorted(self._skills.values(), key=lambda s: (s.source != "builtin", s.name))]

    def get(self, skill_id: str) -> Optional[Skill]:
        with self._lock:
            return self._skills.get(skill_id)

    # --- the point: automatic attachment (U3) --------------------------------

    def select_for(self, message: str, limit: int = _MAX_ATTACHED) -> List[Skill]:
        """Skills relevant to this turn, best match first.

        Nothing is attached when nothing matches — an unhelpful skill steers the
        answer wrong, which is worse than no skill at all.
        """
        with self._lock:
            candidates = [s for s in self._skills.values() if s.enabled]

        scored = [(s.match_score(message), s) for s in candidates]
        relevant = [(score, s) for score, s in scored if score >= _MIN_TRIGGER_HITS]
        relevant.sort(key=lambda pair: (-pair[0], pair[1].name))
        return [s for _score, s in relevant[:max(0, limit)]]

    def build_context(self, message: str, limit: int = _MAX_ATTACHED) -> str:
        """The prompt fragment for whichever skills this turn needs."""
        selected = self.select_for(message, limit)
        if not selected:
            return ""

        with self._lock:
            for skill in selected:
                skill.uses += 1
            self._save()

        parts = ["[Skills active for this turn]"]
        for skill in selected:
            parts.append(f"\n{skill.name}: {skill.instructions}")
        return "\n".join(parts)

    # --- writes -------------------------------------------------------------

    def add(
        self,
        name: str,
        description: str,
        instructions: str,
        triggers: Optional[List[str]] = None,
        source: str = "conversation",
        author: str = "",
    ) -> Skill:
        """Add a skill, typically one the agent wrote from a description (U2)."""
        if not name.strip():
            raise SkillError("A skill needs a name.")
        if not instructions.strip():
            raise SkillError("A skill needs instructions — what should it tell the agent to do?")

        cleaned = [t.strip().lower() for t in (triggers or []) if t.strip()]
        if not cleaned:
            # Fall back to significant words from the name and description, so a
            # skill without explicit triggers can still be found.
            cleaned = sorted(_derive_triggers(f"{name} {description}"))
        if not cleaned:
            raise SkillError("A skill needs at least one trigger, or a longer description.")

        skill = Skill(
            skill_id=uuid.uuid4().hex[:10],
            name=name.strip(),
            description=description.strip(),
            instructions=instructions.strip(),
            triggers=cleaned,
            source=source,
            author=author,
        )
        with self._lock:
            self._skills[skill.skill_id] = skill
            self._save()
        return skill

    def set_enabled(self, skill_id: str, enabled: bool) -> Skill:
        with self._lock:
            skill = self._skills.get(skill_id)
            if skill is None:
                raise SkillError("No such skill.")
            skill.enabled = enabled
            self._save()
            return skill

    def remove(self, skill_id: str) -> bool:
        """Remove a user skill. Built-ins can only be disabled, never deleted."""
        with self._lock:
            skill = self._skills.get(skill_id)
            if skill is None:
                return False
            if skill.source == "builtin":
                raise SkillError(
                    "Built-in skills cannot be deleted — disable it instead, so an "
                    "app update can still improve it."
                )
            del self._skills[skill_id]
            self._save()
            return True


def _derive_triggers(text: str) -> Set[str]:
    """Significant words usable as fallback triggers."""
    common = {
        "the", "and", "for", "with", "that", "this", "from", "into", "when",
        "skill", "should", "user", "help", "make", "using", "your", "you",
    }
    return {w for w in _WORD_RE.findall((text or "").lower())
            if len(w) > 3 and w not in common}


def build_skill_prompt(description: str) -> str:
    """Prompt for asking the model to write a skill from a description (U2)."""
    return (
        "Write a reusable skill for an AI assistant from this description:\n\n"
        f"{description}\n\n"
        "Reply with exactly three sections and nothing else:\n"
        "NAME: a short name, two or three words\n"
        "TRIGGERS: comma-separated words or phrases that mean this skill applies\n"
        "INSTRUCTIONS: how the assistant should approach this kind of task. Write "
        "guidance, not code. Be specific and short — a paragraph at most."
    )


def parse_skill_reply(reply: str) -> Dict[str, Any]:
    """Parse a model reply produced by `build_skill_prompt`.

    Tolerant of formatting drift, since models vary. Raises rather than returning
    something half-formed — a malformed skill would be attached to real turns.
    """
    sections: Dict[str, str] = {}
    current: Optional[str] = None
    for line in (reply or "").splitlines():
        match = re.match(r"^\s*(NAME|TRIGGERS|INSTRUCTIONS)\s*:\s*(.*)$", line, re.IGNORECASE)
        if match:
            current = match.group(1).lower()
            sections[current] = match.group(2).strip()
        elif current:
            sections[current] = (sections[current] + " " + line.strip()).strip()

    name = sections.get("name", "").strip()
    instructions = sections.get("instructions", "").strip()
    if not name or not instructions:
        raise SkillError("The model did not return a usable skill.")

    triggers = [t.strip().lower() for t in sections.get("triggers", "").split(",") if t.strip()]
    return {"name": name, "triggers": triggers, "instructions": instructions}


SKILL_STORE = SkillStore()
