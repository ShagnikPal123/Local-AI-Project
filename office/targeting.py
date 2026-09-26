"""Who the owner means — "optimizers of only these specific groups" → the actual agents, offline and instantly.

The owner asked for two ways to aim the second chat box, and for them to work together:

* **clicking** — sections picked in the bar at the top or the dock at the bottom, agents picked inside a section;
* **saying it** — *"only the front end design, coder agents in every group, managers, manger of this one group,
  top manager, optimizers of all groups, optimizers of only these specific groups. These are all just examples
  and should have more freedom of who I refer to."*

So this resolves words against the live office: agent names, section names, role names and their plurals and
synonyms, the special crowds (everyone, the managers, the workers, the idle ones), "every group", "this section",
and exclusions ("everyone except QA"). It runs on every keystroke in the composer to show who will receive the
message, so it is pure string work — no model call, no I/O.

When the owner has clicked a selection *and* typed a role, the two combine the way a person would expect:
clicked sections narrow the role ("the coders" + Frontend, Backend selected → the coders in those two).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from office import roles as role_module
from office.roles import LIAISON, SECTION_MANAGER, TOP_MANAGER

_SPLIT_EXCEPT = re.compile(r"\b(?:except|excluding|but not|apart from|other than|besides)\b", re.IGNORECASE)
_EVERY_GROUP = re.compile(r"\b(?:every|all|each)\s+(?:group|section|team|department|floor)s?\b|\beverywhere\b"
                          r"|\bacross the (?:office|floor|board)\b|\bin every (?:group|section|team)\b", re.IGNORECASE)
_THIS_GROUP = re.compile(r"\bthis (?:group|section|team|department|room)\b|\bmy (?:group|section|team)\b"
                         r"|\bthe (?:open|current|selected) (?:group|section|team)\b", re.IGNORECASE)
_EVERYONE = re.compile(r"\b(?:everyone|everybody|all agents|all of you|whole office|entire office|the floor"
                       r"|all staff|the whole team)\b", re.IGNORECASE)
_WORKERS = re.compile(r"\b(?:workers?|the teams?|staff|non[- ]managers?|everyone working)\b", re.IGNORECASE)
_IDLE = re.compile(r"\b(?:idle|free|not busy|waiting|available) (?:agents?|ones?|people)\b|\bwhoever is free\b",
                   re.IGNORECASE)
_BUSY = re.compile(r"\b(?:busy|working|active) (?:agents?|ones?|people)\b", re.IGNORECASE)

#: Ways the owner might open a message with who it is for.
_PREFIX_PATTERNS = (
    re.compile(r"^\s*(?:to|for)\s+(?P<addr>[^:\n]{2,120}?)\s*:\s*(?P<msg>.+)$", re.DOTALL | re.IGNORECASE),
    re.compile(r"^\s*@(?P<addr>[^:\n,]{2,120}?)\s*[,:]\s*(?P<msg>.+)$", re.DOTALL),
    re.compile(r"^\s*(?P<addr>[^:\n]{2,120}?)\s*:\s*(?P<msg>.+)$", re.DOTALL),
    re.compile(r"^\s*(?:tell|ask|have|get|remind|nudge)\s+(?P<addr>.{2,90}?)\s+(?:to|that|about|they should)\s+"
               r"(?P<msg>.+)$", re.DOTALL | re.IGNORECASE),
    re.compile(r"^\s*(?P<addr>[^\n]{2,90}?)\s*[—–]\s*(?P<msg>.+)$", re.DOTALL),
)


@dataclass
class Aim:
    agent_ids: List[str] = field(default_factory=list)
    label: str = ""
    message: str = ""
    addressing: str = ""
    sections: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    unknown: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"agents": list(self.agent_ids), "label": self.label, "message": self.message,
                "addressing": self.addressing, "sections": list(self.sections), "roles": list(self.roles),
                "unknown": list(self.unknown), "count": len(self.agent_ids)}


def _span(text: str, term: str) -> Optional[tuple]:
    """Where ``term`` appears as whole words, or None."""
    term = (term or "").strip().lower()
    if len(term) < 2:
        return None
    pattern = r"(?<![\w#])" + re.escape(term).replace(r"\ ", r"\s+") + r"(?![\w])"
    match = re.search(pattern, text, re.IGNORECASE)
    return match.span() if match else None


def _contains(text: str, term: str) -> bool:
    return _span(text, term) is not None


def _claim(text: str, terms: Sequence[str], claimed: List[tuple]) -> bool:
    """True when one of ``terms`` matches on words nothing longer has already taken.

    Longest names are offered first, so "top manager" takes those words before the Manager role sees them, and
    "Coder #2" takes them before "coder" does. Without this, one phrase would select two different crowds.
    """
    for term in terms:
        span = _span(text, term)
        if span is None:
            continue
        if any(span[0] >= start and span[1] <= end for start, end in claimed):
            continue
        claimed.append(span)
        return True
    return False


def _label_for(office: Any, agent_ids: Sequence[str], sections: Sequence[str], role_ids: Sequence[str]) -> str:
    """A recipient line a person would actually say: "4 Coders in Frontend and Backend"."""
    if not agent_ids:
        return ""
    if len(agent_ids) == 1:
        agent = office.agent(agent_ids[0])
        if agent is not None:
            section = office.section(agent.section_id)
            where = f" · {section.name}" if section else ""
            return f"{agent.name}{where}"
    names = [office.section(s).name for s in sections if office.section(s)]
    role_titles = []
    for role_id in role_ids:
        role = role_module.get(role_id)
        if role:
            role_titles.append(role.plural or (role.title + "s"))
    where = ""
    if names and len(names) <= 3:
        where = " in " + (" and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1])
    elif names:
        where = f" in {len(names)} sections"
    if role_titles:
        what = " and ".join(role_titles[:2]) + (f" +{len(role_titles) - 2} more" if len(role_titles) > 2 else "")
        return f"{len(agent_ids)} × {what}{where}".replace("1 × ", "")
    if names:
        return f"everyone{where} ({len(agent_ids)})"
    return f"{len(agent_ids)} agents"


def _sorted_ids(office: Any, agents: Sequence[Any]) -> List[str]:
    """Section order, then desk — the order they sit in on the floor. Records are deduplicated by id."""
    order = {s.id: s.order for s in office.sections.values()}
    unique = {a.id: a for a in agents}
    return [a.id for a in sorted(unique.values(), key=lambda a: (order.get(a.section_id, 99), a.desk, a.name))]


def _match_terms(office: Any, text: str, focus_section: str) -> Dict[str, Any]:
    """Every section, role and named agent this text mentions, longest name first."""
    claimed: List[tuple] = []

    named: List[Any] = []
    for agent in sorted(office.agents.values(), key=lambda a: -len(a.name)):
        if _claim(text, [agent.name, agent.name.replace("#", "")], claimed):
            named.append(agent)

    sections: List[str] = []
    for section in sorted(office.sections.values(), key=lambda s: -len(s.name)):
        words = [w for w in section.name.split() if len(w) > 4]
        if _claim(text, [section.name, *words], claimed):
            sections.append(section.id)
    if _THIS_GROUP.search(text) and focus_section and focus_section in office.sections:
        sections.append(focus_section)

    role_ids: List[str] = []
    for role in sorted(role_module.catalogue(), key=lambda r: -len(r.title)):
        terms = sorted([role.title, role.plural or role.title + "s", *role.synonyms], key=len, reverse=True)
        if _claim(text, terms, claimed):
            role_ids.append(role.id)
    if re.search(r"\b(?:all|every|the)\s+managers\b", text, re.IGNORECASE) and SECTION_MANAGER not in role_ids:
        role_ids.append(SECTION_MANAGER)
    return {"sections": list(dict.fromkeys(sections)), "roles": list(dict.fromkeys(role_ids)), "named": named}


def _agents_for(office: Any, text: str, focus_section: str) -> Dict[str, Any]:
    """The crowd this piece of text picks out, with the sections and roles it used."""
    hits = _match_terms(office, text, focus_section)
    sections, role_ids, named = hits["sections"], hits["roles"], hits["named"]
    everywhere = bool(_EVERY_GROUP.search(text))
    chosen: List[Any] = list(named)

    if _EVERYONE.search(text):
        chosen.extend(office.agents.values())
    if _WORKERS.search(text):
        chosen.extend(a for a in office.agents.values()
                      if a.role not in (TOP_MANAGER, SECTION_MANAGER))
    if role_ids:
        pool = [a for a in office.agents.values() if a.role in role_ids]
        if sections and not everywhere:
            pool = [a for a in pool if a.section_id in sections]
        chosen.extend(pool)
    elif sections:
        chosen.extend(a for a in office.agents.values() if a.section_id in sections)

    if _IDLE.search(text):
        chosen = [a for a in (chosen or office.agents.values()) if a.status in ("idle", "waiting")]
    elif _BUSY.search(text):
        chosen = [a for a in (chosen or office.agents.values()) if a.status == "working"]

    return {"agents": chosen, "sections": sections, "roles": role_ids}


def resolve(office: Any, text: str, *, selection: Optional[Dict[str, Any]] = None,
            focus_section: str = "") -> Aim:
    """Who this message is for, and what is left of it once the addressing is taken off the front."""
    raw = (text or "").strip()
    selection = selection or {}
    picked_agents = [str(a) for a in selection.get("agents", []) if str(a) in office.agents]
    picked_sections = [str(s) for s in selection.get("sections", []) if str(s) in office.sections]
    picked_roles = [str(r) for r in selection.get("roles", []) if r]

    aim = Aim(message=raw)

    # 1. Words. Try "addressing: message" shapes first so the message keeps only what was actually said.
    words_agents: List[Any] = []
    words_sections: List[str] = []
    words_roles: List[str] = []
    for pattern in _PREFIX_PATTERNS:
        match = pattern.match(raw)
        if not match:
            continue
        addr, rest = match.group("addr").strip(), match.group("msg").strip()
        if not addr or not rest or len(addr.split()) > 12:
            continue
        found = _agents_for(office, addr, focus_section)
        if found["agents"]:
            words_agents, words_sections, words_roles = found["agents"], found["sections"], found["roles"]
            aim.addressing, aim.message = addr, rest
            break
    if not words_agents:
        found = _agents_for(office, raw, focus_section)
        words_agents, words_sections, words_roles = found["agents"], found["sections"], found["roles"]
        if words_agents:
            aim.addressing = raw[:120]

    # 2. Exclusions: "everyone except QA".
    excluded: set = set()
    split = _SPLIT_EXCEPT.split(aim.addressing or raw, maxsplit=1)
    if len(split) == 2 and split[1].strip():
        out = _agents_for(office, split[1], focus_section)
        excluded = {a.id for a in out["agents"]}
        keep = _agents_for(office, split[0], focus_section)
        if keep["agents"]:
            words_agents, words_sections, words_roles = keep["agents"], keep["sections"], keep["roles"]

    # 3. Clicks. A selection wins over words, except that typed roles narrow selected sections.
    chosen: List[Any] = []
    sections_used, roles_used = list(words_sections), list(words_roles)
    if picked_agents or picked_sections or picked_roles:
        chosen.extend(office.agents[a] for a in picked_agents)
        pool = [a for a in office.agents.values() if a.section_id in picked_sections] if picked_sections else []
        narrow = [r for r in (words_roles or picked_roles) if r]
        if picked_sections and narrow:
            pool = [a for a in pool if a.role in narrow]
            roles_used = narrow
        elif picked_roles and not picked_sections:
            pool = [a for a in office.agents.values() if a.role in picked_roles]
            roles_used = picked_roles
        chosen.extend(pool)
        sections_used = picked_sections or sections_used
        if not chosen:
            chosen = list(words_agents)
    else:
        chosen = list(words_agents)

    agents = [a for a in chosen if a.id not in excluded]
    aim.agent_ids = _sorted_ids(office, agents)
    aim.sections = list(dict.fromkeys(sections_used))
    aim.roles = list(dict.fromkeys(roles_used))
    aim.label = _label_for(office, aim.agent_ids, aim.sections, aim.roles)
    if not aim.agent_ids and (aim.addressing or raw):
        aim.unknown = [w for w in re.findall(r"[A-Za-z][\w'#-]{2,}", (aim.addressing or raw))[:4]]
    return aim


def describe(office: Any, agent_ids: Sequence[str]) -> str:
    """Label for a set of agents chosen by clicking alone."""
    agents = [office.agent(a) for a in agent_ids if office.agent(a)]
    sections = list(dict.fromkeys(a.section_id for a in agents))
    role_ids = list(dict.fromkeys(a.role for a in agents))
    return _label_for(office, [a.id for a in agents], sections, role_ids)


def liaison_targets(office: Any, words: str) -> List[str]:
    """Who a liaison agent is being asked to talk to (same rules, no selection, no message split)."""
    return _sorted_ids(office, _agents_for(office, words or "", "")["agents"])


__all__ = ["Aim", "resolve", "describe", "liaison_targets", "LIAISON"]
