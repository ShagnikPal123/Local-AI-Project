"""The genetic code: every bot, skill and model as a short number code (U40).

The owner: *"Make sure the type of bot, skills, laws, and more are easy to store and are basically assigned via number
combos and genetic code which makes it smaller."* So a bot is not a record of words — it is one short string::

    1 07 2 F 03 : 0A 0B 11
    │ │  │ │ │    └ skills, two hex digits each (``SKILLS`` first, then the world's own words)
    │ │  │ │ └ model: an index into the world's table of models ("provider:model")
    │ │  │ └ employment: F full time, P part time
    │ │  └ rank + 1: 0 junior, 1 normal, 2 senior, 3 lead
    │ └ role: an index into the world's table of roles
    └ generation: 0 for the founders, parent's + 1 for a child

Role and model names are stored once per world file in its tables; a hundred coders share one "coder".

Reproduction (U35): *"a finance and coder bot coming together to make a finance coder"*. A child gets the next
generation, a role named from both parents, the union of their skills and the better parent's model.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

#: Fixed so a code means the same thing in every world. New words go after these, per world.
SKILLS = (
    "general", "code", "research", "writing", "design", "data", "finance", "testing", "review", "planning",
    "ops", "security", "web", "math", "marketing", "legal", "product", "ui", "backend", "frontend",
    "ml", "devops", "docs", "sales", "support", "hiring", "strategy", "art", "audio", "video",
    "game", "3d", "mobile", "cloud", "database", "api", "science", "health", "education", "trading",
)

#: Words in a role's name or domain → the skills it brings.
_SKILL_WORDS = {
    "code": "code", "coder": "code", "coders": "code", "developer": "code", "engineer": "code", "programmer": "code",
    "research": "research", "researcher": "research", "analyst": "data", "analysis": "data", "data": "data",
    "writer": "writing", "writing": "writing", "copy": "writing", "chat": "general", "knowledge": "research",
    "design": "design", "designer": "design", "ui": "ui", "ux": "ui", "web": "web", "frontend": "frontend",
    "backend": "backend", "finance": "finance", "financial": "finance", "money": "finance", "trader": "trading",
    "trading": "trading", "tester": "testing", "test": "testing", "qa": "testing", "reviewer": "review",
    "review": "review", "planner": "planning", "planning": "planning", "organizer": "planning", "manager": "planning",
    "agents": "planning", "ops": "ops", "system": "ops", "hardware": "ops", "security": "security",
    "math": "math", "marketing": "marketing", "growth": "marketing", "legal": "legal", "product": "product",
    "ml": "ml", "ai": "ml", "devops": "devops", "documenter": "docs", "docs": "docs", "documentation": "docs",
    "sales": "sales", "support": "support", "hiring": "hiring", "strategy": "strategy", "strategist": "strategy",
    "art": "art", "artist": "art", "audio": "audio", "music": "audio", "video": "video", "game": "game",
    "3d": "3d", "mobile": "mobile", "app": "mobile", "cloud": "cloud", "database": "database", "sql": "database",
    "api": "api", "science": "science", "scientist": "science", "health": "health", "education": "education",
    "educator": "education", "teacher": "education", "email": "writing", "files": "data", "optimizer": "code",
    "liaison": "general", "messenger": "general", "news": "research",
}

#: Domains a qualifier may be taken from when naming a child ("finance" → "Finance Coder").
_PLAIN_DOMAINS = {"chat", "agents", "general", ""}

MAX_SKILLS = 8
_CODE_RE = re.compile(r"^([0-9A-F])([0-9A-F]{2})([0-9A-F])([FP])([0-9A-F]{2}):((?:[0-9A-F]{2})*)$")


def code_of(table: List[str], value: str) -> int:
    """The index of ``value`` in a world table, adding it when it is new. Tables only ever grow."""
    text = (value or "").strip()
    if text in table:
        return table.index(text)
    table.append(text)
    return len(table) - 1


def skill_code(word: str, extra: List[str]) -> int:
    """A skill word's code: the fixed table first, then the world's own words after it."""
    text = (word or "").strip().lower()
    if text in SKILLS:
        return SKILLS.index(text)
    if text not in extra:
        extra.append(text)
    return len(SKILLS) + extra.index(text)


def skill_word(code: int, extra: Sequence[str]) -> str:
    if 0 <= code < len(SKILLS):
        return SKILLS[code]
    index = code - len(SKILLS)
    return extra[index] if 0 <= index < len(extra) else f"skill {code}"


def skills_for(title: str, domain: str = "") -> List[str]:
    """What a role brings, read from its own name and the domain it thinks in."""
    words = re.findall(r"[a-z0-9]+", f"{title} {domain}".lower())
    found: List[str] = []
    for word in words:
        skill = _SKILL_WORDS.get(word) or _SKILL_WORDS.get(word.rstrip("s"))
        if skill and skill not in found:
            found.append(skill)
    return found[:MAX_SKILLS] or ["general"]


def encode(*, generation: int, role: int, rank: int = 0, part_time: bool = False, model: int = 0,
           skills: Iterable[int] = ()) -> str:
    gen = max(0, min(15, int(generation)))
    role_code = max(0, min(255, int(role)))
    rank_code = max(0, min(3, int(rank) + 1))
    model_code = max(0, min(255, int(model)))
    skill_codes = []
    for code in skills:
        value = max(0, min(255, int(code)))
        if value not in skill_codes:
            skill_codes.append(value)
    body = "".join(f"{c:02X}" for c in sorted(skill_codes)[:MAX_SKILLS])
    return f"{gen:X}{role_code:02X}{rank_code:X}{'P' if part_time else 'F'}{model_code:02X}:{body}"


def decode(code: str) -> Optional[Dict[str, Any]]:
    """The parts of a genetic code, or None when it is not one."""
    match = _CODE_RE.match((code or "").strip().upper())
    if not match:
        return None
    gen, role, rank, employment, model, skills = match.groups()
    return {"generation": int(gen, 16), "role": int(role, 16), "rank": int(rank, 16) - 1,
            "part_time": employment == "P", "model": int(model, 16),
            "skills": [int(skills[i:i + 2], 16) for i in range(0, len(skills), 2)]}


def pretty(code: str) -> str:
    """How the details card shows a code: ``G1 · R07 · K2 · F · M03 · S0A.0B.11``."""
    parts = decode(code)
    if parts is None:
        return code or "—"
    skills = ".".join(f"{s:02X}" for s in parts["skills"]) or "—"
    return (f"G{parts['generation']:X} · R{parts['role']:02X} · K{parts['rank'] + 1:X} · "
            f"{'P' if parts['part_time'] else 'F'} · M{parts['model']:02X} · S{skills}")


def child_title(a_title: str, a_domain: str, b_title: str) -> str:
    """Name a child from both parents: a qualifier from the first, the trade of the second.

    "Finance Analyst" (finance) + "Coder" → "Finance Coder"; "Researcher" (web) + "Writer" → "Research Writer".
    """
    a_words = (a_title or "").split()
    b_words = (b_title or "").split()
    noun = (b_words[-1] if b_words else "Specialist").strip("#0123456789 ") or "Specialist"
    domain = (a_domain or "").strip().lower()
    candidates: List[str] = []
    if len(a_words) > 1:
        candidates.append(a_words[0])
    if domain not in _PLAIN_DOMAINS and domain not in ("web", "system", "files", "email", "knowledge"):
        candidates.append(domain.title())
    candidates.append(_trade(a_words[0] if a_words else "General"))
    for qualifier in candidates:
        qualifier = qualifier[:1].upper() + qualifier[1:]
        # "Code" + "Coder" says nothing new; try the next way of naming the first parent's trade.
        if not noun.lower().startswith(qualifier.lower()) and not qualifier.lower().startswith(noun.lower()[:4]):
            return f"{qualifier} {noun}"[:40]
    return noun              # two coders make a coder


def _trade(word: str) -> str:
    """"Reviewer" → "Review", "Researcher" → "Research", "Planner" → "Planning", "Manager" → "Management"."""
    for ending, swap in (("searcher", "search"), ("ager", "agement"), ("izer", "ization"), ("ner", "ning"),
                         ("ter", "ting"), ("er", "")):
        if word.lower().endswith(ending) and len(word) > len(ending) + 2:
            return word[: len(word) - len(ending)] + swap
    return word


def child(a_code: str, b_code: str, *, role: int, model: int) -> str:
    """The genetic code of what two bots make together."""
    a = decode(a_code) or {"generation": 0, "skills": []}
    b = decode(b_code) or {"generation": 0, "skills": []}
    skills: List[int] = []
    for code in list(a["skills"]) + list(b["skills"]):
        if code not in skills:
            skills.append(code)
    return encode(generation=max(a["generation"], b["generation"]) + 1, role=role, rank=0, part_time=False,
                  model=model, skills=skills[:MAX_SKILLS])


def with_employment(code: str, *, rank: int, part_time: bool, model: Optional[int] = None) -> str:
    """The same bot after a promotion, a demotion or a move to part time — the rest of its code unchanged."""
    parts = decode(code)
    if parts is None:
        return code
    return encode(generation=parts["generation"], role=parts["role"], rank=rank, part_time=part_time,
                  model=parts["model"] if model is None else model, skills=parts["skills"])
