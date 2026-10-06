"""Auto skill / Auto agent: "/auto" or "@auto" — Nyx picks and runs the best team for a job (Update 1, U21).

The owner (2026-10-04): "this skill and new agent are just called auto skill and auto agent. they work the same.
both when activated with @ and /auto either creates an agent or activates a skill this skill allows the ai to
select and properly choose the best skills and ai subagents and other agents to work on a project."

So both spellings do one thing. Before the turn, the job is scored offline (no model call) against every skill,
every agent on the team and every connector, and the Manager is handed a brief: the skills to follow (in full),
the agents that fit and why, a new agent to make when nobody fits, the connectors that could help — and how to
run it: one specific, self-contained task per agent through ``dispatch_agents``, so the owner sees exactly what
each agent was asked and what it answered (U46), then one merged answer.

The picks are a starting point, not a cage: the brief says the Manager may drop a pick that turns out not to fit,
and a tiny job gets no team at all.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

PREFIX = "[Auto team]"

#: "/auto" or "@auto" as a word of its own — not "/automation", not a path like "C:/auto/x".
_CALL = re.compile(r"(?<![\w/:.@])[/@]auto(?![\w/.-])", re.I)

MAX_SKILLS = 3
MAX_AGENTS = 4
#: Lower than agent_match.THRESHOLD: the owner asked for a team, so a reasonable fit is enough.
AGENT_FLOOR = 1.0

SKILL_NAME = "Auto"
SKILL_DESCRIPTION = ("Pick and run the best skills, agents and connectors for a job — or make the agent it needs. "
                     "Call it with /auto or @auto.")
SKILL_INSTRUCTIONS = (
    "You are running Auto: choose and run the best team for this job yourself. Use the skills, agents and "
    "connectors picked below where they fit and drop any that turn out not to. Split the work into parts, one per "
    "agent (several copies of one agent when the parts are alike). Hand them out with dispatch_agents "
    "(agents=[{\"agent\": \"…\", \"task\": \"…\"}], context=the facts every agent needs — they do not see this chat): "
    "each task specific and complete on its own, because the owner reads exactly what each agent was asked and what "
    "it answered. If a part needs a specialist the team does not have, make one with create_agent first (a clear "
    "name, goal and expertise), then hand it the part. Check the reports against each other, redo what is weak, and "
    "finish with one answer that says who did what. A one-line job needs no team: just do it."
)


def called(text: str) -> bool:
    return bool(_CALL.search(text or ""))


def strip(text: str) -> str:
    """The job without the /auto or @auto that asked for it."""
    return re.sub(r"\s{2,}", " ", _CALL.sub(" ", text or "")).strip()


def _skill_candidates() -> List[Any]:
    try:
        from skills import SKILL_STORE

        with SKILL_STORE._lock:  # noqa: SLF001 - a read of the live list, same as select_for
            return [s for s in SKILL_STORE._skills.values() if s.enabled and s.name != SKILL_NAME]  # noqa: SLF001
    except Exception:  # noqa: BLE001 - no skill store, no skills
        return []


def pick_skills(job: str, skills: Optional[List[Any]] = None, limit: int = MAX_SKILLS) -> List[Dict[str, Any]]:
    """Skills whose triggers the job hits, or whose name and description share its words."""
    from agent_match import _stem, _words

    said = {_stem(w) for w in _words(job)}
    scored = []
    for skill in skills if skills is not None else _skill_candidates():
        triggers = skill.match_score(job)
        about = {_stem(w) for w in _words(f"{skill.name} {skill.description}")}
        overlap = sorted(said & about)
        value = 3 * triggers + len(overlap)
        if triggers or len(overlap) >= 2:
            why = [t for t in skill.triggers if t.lower() in job.lower()][:3] or overlap[:4]
            scored.append({"id": skill.skill_id, "name": skill.name, "score": value, "why": why,
                           "instructions": skill.instructions})
    scored.sort(key=lambda s: (-s["score"], s["name"]))
    return scored[:limit]


def pick_agents(job: str, roster: Optional[List[Dict[str, Any]]] = None, limit: int = MAX_AGENTS) -> List[Dict[str, Any]]:
    """The team's specialists that fit, best first; a second-tier fit only when it is close to the best."""
    import agent_match

    if roster is None:
        try:
            from agent_runtime import load_roster

            roster = load_roster()
        except Exception:  # noqa: BLE001
            roster = []
    scored = [agent_match.score(job, a) for a in roster if a.get("role") != "master"]
    good = sorted((s for s in scored if s["score"] >= AGENT_FLOOR and s["why"]), key=lambda s: -s["score"])
    if not good:
        return []
    top = good[0]["score"]
    return [s for s in good[:limit] if s["score"] >= top * 0.5]


def pick_connectors(job: str, limit: int = 3) -> List[Dict[str, Any]]:
    try:
        import connector_use

        return connector_use.predict(job, limit=limit)
    except Exception:  # noqa: BLE001 - connectors are a bonus
        return []


def assemble(text: str, *, roster: Optional[List[Dict[str, Any]]] = None,
             skills: Optional[List[Any]] = None) -> Dict[str, Any]:
    """The team for this job: skills, agents (or a note to make one), connectors."""
    job = strip(text)
    agents = pick_agents(job, roster)
    return {
        "job": job,
        "skills": pick_skills(job, skills),
        "agents": agents,
        # Nobody on the team fits: "either creates an agent or activates a skill".
        "create_agent": not agents and len(job.split()) >= 4,
        "connectors": pick_connectors(job),
    }


def status_line(team: Dict[str, Any]) -> str:
    parts = []
    if team["skills"]:
        parts.append("skills " + ", ".join(s["name"] for s in team["skills"]))
    if team["agents"]:
        parts.append("agents " + ", ".join(a["name"] for a in team["agents"]))
    elif team["create_agent"]:
        parts.append("a new agent for this job")
    if team["connectors"]:
        parts.append("connectors " + ", ".join(c["name"] for c in team["connectors"]))
    return "Auto picked " + ("; ".join(parts) if parts else "no team — a quick job it can do itself")


def view(team: Dict[str, Any]) -> Dict[str, Any]:
    """What the chat shows: names and why, never a skill's whole instructions."""
    return {
        "skills": [{"id": s["id"], "name": s["name"], "why": s["why"]} for s in team["skills"]],
        "agents": [{"name": a["name"], "emoji": a.get("emoji", ""), "why": a["why"]} for a in team["agents"]],
        "create_agent": team["create_agent"],
        "connectors": [{"id": c["id"], "name": c["name"], "connected": c.get("connected", False)} for c in team["connectors"]],
    }


def brief(team: Dict[str, Any]) -> str:
    lines = [PREFIX, "The owner called on Auto (/auto or @auto) for this job. " + SKILL_INSTRUCTIONS]
    if team["skills"]:
        lines.append("\nSkills switched on for this job — follow them:")
        for skill in team["skills"]:
            lines.append(f"- {skill['name']}: {skill['instructions']}")
    if team["agents"]:
        lines.append("\nAgents on the team that fit:")
        for agent in team["agents"]:
            lines.append(f"- {agent.get('emoji', '')} {agent['name']} (matched: {', '.join(agent['why'])})".replace("-  ", "- "))
    elif team["create_agent"]:
        lines.append("\nNobody on the team fits this job well. Make the specialist it needs with create_agent, then hand "
                     "it the work with dispatch_agents.")
    if team["connectors"]:
        lines.append("\nConnectors that may help: " + ", ".join(
            f"{c['name']} ({'connected' if c.get('connected') else 'not connected — say so if it is needed'})"
            for c in team["connectors"]))
    return "\n".join(lines)
