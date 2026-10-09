"""What kinds of agent work in an office — their symbol, head colour, and how each one works.

Two sources, deliberately:

* **Nyx's own sub-agents** (``agent_runtime.load_roster``) — the owner's words: *"Basically taking everything
  in sub agents and duplicating as needed."* So Coder, Web Design, Researcher, and anything the owner or Nyx
  has made since, can all be staffed into an office, keeping their emoji, colour and expertise.
* **Office-native roles** that only make sense inside an office: the top manager, section managers, organizers,
  optimizers, reviewers, planners, liaisons (the agents brought in purely to talk to another section), testers,
  documenters — and the Hiring Board, which is a class of one and only exists when the gatekeeper rule fires.

Colour rule from the owner: *"Each section, agent type is color coded. The section has its own unique color
while the agent changes the head color or the symbol on there."* So a section owns the room colour and an
agent's **role** owns its head colour and glyph — never the other way round.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Domains Nyx's brain thinks in (``nyx_core.DOMAINS``); used to ask Big Kahuna for the right model.
DEFAULT_DOMAIN = "chat"


@dataclass(frozen=True)
class Role:
    id: str
    title: str
    glyph: str
    color: str
    domain: str
    kind: str          # manager | worker | messenger | special
    goal: str
    how: str = ""      # the role's own working instructions
    synonyms: tuple = ()
    origin: str = "office"   # office | roster | invented
    plural: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "title": self.title, "glyph": self.glyph, "color": self.color,
                "domain": self.domain, "kind": self.kind, "goal": self.goal, "origin": self.origin,
                "plural": self.plural or (self.title + "s"), "synonyms": list(self.synonyms)}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:40]


TOP_MANAGER = "top-manager"
SECTION_MANAGER = "manager"
LIAISON = "liaison"
HIRING_BOARD = "hiring-board"

_OFFICE_ROLES: List[Role] = [
    Role(TOP_MANAGER, "Top Manager", "♛", "#ffd60a", "agents", "manager",
         "Run the whole office: read what the owner wants, decide which sections do what, and deliver one answer.",
         how=("Think about the whole request before splitting it. Reuse the sections that already exist instead of "
              "inventing new ones. Keep the owner's own words as the definition of done."),
         synonyms=("top manager", "boss", "ceo", "head of the office", "chief", "the top", "director"),
         plural="Top Managers"),
    Role(SECTION_MANAGER, "Manager", "◆", "#a594ff", "agents", "manager",
         "Run one section: split its work, hand each piece to the right agent, review what comes back.",
         how=("Split work so two agents never write the same thing. Give each agent everything it needs — they "
              "cannot see the chat. Check the work against the task before you report it as done."),
         synonyms=("manager", "managers", "section manager", "lead", "leads", "head of"),
         plural="Managers"),
    Role("organizer", "Organizer", "▦", "#7bd3a8", "agents", "worker",
         "Keep the work in order: lists, order of play, what is missing, what is blocked.",
         how="Turn loose work into a short ordered list with owners. Name what is blocking, never just that something is.",
         synonyms=("organizer", "organizers", "organiser", "organisers", "coordinator", "coordinators"),
         plural="Organizers"),
    Role("optimizer", "Optimizer", "⚡", "#ff9f0a", "code", "worker",
         "Make what the team produced faster, smaller, or simpler without changing what it does.",
         how=("Measure or reason before you change anything, and say what the improvement actually buys. Never trade "
              "correctness for speed."),
         synonyms=("optimizer", "optimizers", "optimiser", "optimisers", "performance", "speed"),
         plural="Optimizers"),
    Role("reviewer", "Reviewer", "✓", "#64d2ff", "code", "worker",
         "Check other agents' work for mistakes, gaps and things that do not match the task.",
         how=("Look for what is wrong or missing first, then for what is unclear. Say plainly when something is fine — "
              "a review that invents problems wastes the team."),
         synonyms=("reviewer", "reviewers", "qa", "quality", "checker", "checkers"),
         plural="Reviewers"),
    Role("planner", "Planner", "◇", "#bdb2ff", "agents", "worker",
         "Turn a large ask into a plan with steps, order and what each step needs.",
         how="Give steps someone else could follow without asking you anything. Mark what must happen before what.",
         synonyms=("planner", "planners", "strategy", "strategist"),
         plural="Planners"),
    Role(LIAISON, "Liaison", "⇄", "#e07ac0", "chat", "messenger",
         "Carry a question or an answer to a named agent in another section and bring the reply back.",
         how=("Say who you are speaking for and what you need, in one or two sentences. Bring back exactly what they "
              "said, not your summary of it, when the wording matters."),
         synonyms=("liaison", "liaisons", "messenger", "messengers", "runner", "runners", "communication", "comms"),
         plural="Liaisons"),
    Role("tester", "Tester", "◉", "#30d158", "code", "worker",
         "Try to break what the team built and report exactly how it broke.",
         how="Give the input and the observed result for every problem. A test that only says 'it failed' is not a report.",
         synonyms=("tester", "testers", "test", "qa tester"),
         plural="Testers"),
    Role("documenter", "Documenter", "▤", "#c7c7cc", "knowledge", "worker",
         "Write down what the office produced so someone else can use it.",
         how="Write for someone who was not here. Lead with what the thing is for, then how to use it.",
         synonyms=("documenter", "documenters", "docs", "documentation", "writer of docs", "technical writer"),
         plural="Documenters"),
    # The executive suite of a big job (office/executive.py, U42): they run the company, they do not take tasks.
    Role("cfo", "CFO", "$", "#34c759", "agents", "manager",
         "Keep the books for a big job: the hiring budget, and a ledger of what the job used.",
         how="Count, do not guess. Say what was spent on paid models plainly.",
         synonyms=("cfo", "finance chief", "chief financial officer", "budget keeper"), plural="CFOs"),
    Role("decision-bot", "Decision Bot", "⚑", "#ff9f0a", "agents", "special",
         "Vote on hires in a big job, each with its own bar: careful, balanced or bold.",
         how="Vote on the facts gathered, not on who asked.",
         synonyms=("decision bot", "decision bots", "decision team", "decision maker"), plural="Decision Bots"),
    Role("thinker", "Thinker", "✺", "#bf5af2", "agents", "special",
         "Read the plan before work starts and name what could go wrong and what is missing.",
         how="Four short points at most, most important first. You see what others miss; you do not do the work.",
         synonyms=("thinker", "thinkers", "critic", "devil's advocate"), plural="Thinkers"),
    Role("overhead-manager", "Overhead Manager", "▣", "#8e8e93", "agents", "manager",
         "Watch the whole job and give a failed task one more go, with the error attached.",
         how="Attach the error to the retry so the next agent does not repeat it.",
         synonyms=("overhead manager", "overhead managers", "operations manager"), plural="Overhead Managers"),
    Role("distributor", "Manager-Distributor", "⇆", "#64d2ff", "agents", "manager",
         "Move people to the work: lend an idle agent to a section that has work waiting and nobody free.",
         how="Lend only the same kind of agent, and only within the same job.",
         synonyms=("distributor", "manager distributor", "manager-distributor", "dispatcher"),
         plural="Manager-Distributors"),
    Role(HIRING_BOARD, "Hiring Board", "⚖", "#ff453a", "agents", "special",
         "Decide whether a new agent should really be brought in, using the Crit think skill.",
         how=("Approve only what the office cannot do with the agents it already has. Prefer an idle agent, then a "
              "clone of an existing type, and only then a brand new type."),
         synonyms=("hiring board", "gatekeeper", "the board", "hiring"),
         plural="Hiring Boards"),
]

#: Roster names that must never be staffed into an office: they drive the owner's real mouse and keyboard.
_ROSTER_EXCLUDED = frozenset({"computer operator", "operator"})

#: Roster id → the domain that roster agent thinks in.
_ROSTER_DOMAINS: Dict[str, str] = {
    "coder": "code", "web-design": "design", "app-design": "design", "finance": "knowledge",
    "educator": "knowledge", "tech": "system", "hardware": "system", "news": "web", "researcher": "web",
    "writer": "chat", "email": "email", "data-analyst": "files", "manager": "agents",
}

#: Colours for types the office invents, spaced far apart so two new types never look alike.
_INVENTED_COLORS = ("#5ac8fa", "#ffd60a", "#ff9f0a", "#bf5af2", "#30d158", "#ff6482", "#64d2ff", "#acd94a",
                    "#ff8c69", "#9ad7ff", "#f7b2ff", "#7bd3a8")
_INVENTED_GLYPHS = ("★", "▲", "●", "■", "◆", "✦", "◈", "❖", "⬟", "⬢", "✚", "⬣")

_lock = threading.RLock()
_invented: Dict[str, Role] = {}


def _roster_roles() -> List[Role]:
    """Nyx's sub-agents as office roles. A missing roster is not an error — the office roles still exist."""
    try:
        from agent_runtime import load_roster

        entries = load_roster()
    except Exception:  # noqa: BLE001 - the office must work even if the roster file is broken
        return []
    roles: List[Role] = []
    for entry in entries:
        name = str(entry.get("name") or "").strip()
        if not name or name.lower() in _ROSTER_EXCLUDED:
            continue
        role_id = slug(str(entry.get("id") or name))
        if not role_id or role_id in {r.id for r in _OFFICE_ROLES}:
            continue  # an office role of the same name wins (its instructions are office-shaped)
        expertise = tuple(str(x).lower() for x in (entry.get("expertise") or [])[:6])
        roles.append(Role(
            id=role_id,
            title=name,
            glyph=str(entry.get("emoji") or "●")[:2],
            color=str(entry.get("color") or "#9397ab"),
            domain=_ROSTER_DOMAINS.get(role_id, DEFAULT_DOMAIN),
            kind="worker",
            goal=str(entry.get("goal") or f"Work as {name}."),
            how=str(entry.get("instructions") or "")[:800],
            synonyms=(name.lower(), name.lower() + "s", *expertise),
            origin="roster",
            plural=name + "s",
        ))
    return roles


def catalogue(*, include_special: bool = True) -> List[Role]:
    """Every role an office can staff right now: office roles, sub-agents, and types this office invented."""
    with _lock:
        invented = list(_invented.values())
    roles = [r for r in _OFFICE_ROLES if include_special or r.kind != "special"]
    known = {r.id for r in roles}
    for role in _roster_roles() + invented:
        if role.id not in known:
            known.add(role.id)
            roles.append(role)
    return roles


def get(role_id: str) -> Optional[Role]:
    wanted = slug(role_id)
    return next((r for r in catalogue() if r.id == wanted), None)


def find(words: str) -> Optional[Role]:
    """The role someone means by ``words`` ("frontend developer", "coders", "QA") — or None for a new type."""
    text = (words or "").strip().lower()
    if not text:
        return None
    roles = catalogue()
    as_slug = slug(text)
    for role in roles:
        if role.id == as_slug or role.title.lower() == text:
            return role
    for role in roles:
        if text in role.synonyms or as_slug in {slug(s) for s in role.synonyms}:
            return role
    # Loose contains-match last, longest name first so "manager" never swallows "top manager".
    for role in sorted(roles, key=lambda r: -len(r.title)):
        names = (role.title.lower(), *role.synonyms)
        if any(name and (name in text or text in name) for name in names):
            return role
    return None


def invent(name: str, goal: str = "", how: str = "", domain: str = "", kind: str = "worker", *,
           exact: bool = False) -> Role:
    """Register a type the office asked for and Nyx does not have. Returns the existing role if it is known.

    ``exact`` matches the name only by its own id, not loosely: an AI Environment child is a "Research Coder" — a new
    kind with both parents' skills — even though "coder" appears in its name (U35)."""
    existing = get(name) if exact else find(name)
    if existing is not None:
        return existing
    role_id = slug(name) or "specialist"
    index = sum(ord(c) for c in role_id) % len(_INVENTED_COLORS)
    role = Role(
        id=role_id,
        title=(name or "Specialist").strip()[:40].title() if (name or "").islower() else (name or "Specialist").strip()[:40],
        glyph=_INVENTED_GLYPHS[index],
        color=_INVENTED_COLORS[index],
        domain=domain or DEFAULT_DOMAIN,
        kind=kind if kind in ("worker", "manager", "messenger") else "worker",
        goal=goal or f"Work as {name}.",
        how=how,
        synonyms=(name.lower(), name.lower() + "s"),
        origin="invented",
        plural=(name or "Specialist") + "s",
    )
    with _lock:
        _invented[role.id] = role
    return role


def remember(roles: List[Dict[str, Any]]) -> None:
    """Re-register types an office invented in an earlier session (called when an office file is opened)."""
    for raw in roles or []:
        try:
            if not isinstance(raw, dict) or not raw.get("id"):
                continue
            role = Role(id=str(raw["id"]), title=str(raw.get("title") or raw["id"]),
                        glyph=str(raw.get("glyph") or "●")[:2], color=str(raw.get("color") or "#9397ab"),
                        domain=str(raw.get("domain") or DEFAULT_DOMAIN), kind=str(raw.get("kind") or "worker"),
                        goal=str(raw.get("goal") or ""), how=str(raw.get("how") or ""),
                        synonyms=tuple(str(s) for s in (raw.get("synonyms") or [])), origin="invented",
                        plural=str(raw.get("plural") or ""))
        except Exception:  # noqa: BLE001 - a broken stored role is skipped, never fatal
            continue
        with _lock:
            _invented.setdefault(role.id, role)


def forget_invented() -> None:
    """Tests only: drop invented types so one test's roles cannot leak into the next."""
    with _lock:
        _invented.clear()


def add_to_subagents(role: Role, office_name: str) -> str:
    """Put an invented type into Nyx's own sub-agent roster.

    The owner: *"If a new type of agent is to be made it is added to the sub agents and added to the section or
    the entire group."* So a type the office invents becomes a real Nyx sub-agent — it shows up in the Sub-agents
    tab, the Core view and as a ``/command`` — not just a label inside this office. Returns a short note; never
    raises, because failing to register a type must not stop the office from working.
    """
    try:
        from agent_runtime import roster_entry_exact, tool_create_agent

        if roster_entry_exact(role.title):
            return f"{role.title} is already a sub-agent."
        result = tool_create_agent(
            role.title, role.goal or f"Work as {role.title}.",
            instructions=(role.how or "") + f"\n\nMade in Office Space for the office \"{office_name}\".",
            expertise=", ".join(role.synonyms[:6]), emoji=role.glyph)
        return str(result)[:200]
    except Exception as error:  # noqa: BLE001
        return f"Could not add {role.title} to the sub-agents: {type(error).__name__}"
