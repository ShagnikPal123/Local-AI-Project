"""The agent team, actually at work.

Before this, Nyx had an Agents panel full of named agents that never did
anything — the panel itself said "nothing drives them from the chat loop yet".
The owner's words: "The agents don't show", "make subagents better … make sure
they listen and understand", "actively show the agents created".

How it works now
----------------
* **The Manager is the assistant you talk to.** Every turn goes through it. It
  answers simple things itself and hands focused work to a specialist with
  ``delegate_task`` (or several at once with ``delegate_parallel``).
* **A specialist is a real sub-run**: its own instructions from the roster, the
  same tools (minus delegation, so work cannot bounce around forever), its own
  step budget. It must begin with ``Understood: …`` — a one-line restatement the
  UI shows, so a misunderstanding is visible before any work is wasted.
* **Everything it does is visible**: ``agent.update`` events (working → step →
  done, with the restatement and a result preview), and its tool calls appear in
  the same timeline tagged with the agent's name.
* **Skills are searchable and can be made on the spot.** ``search_skills`` ranks
  the library; ``create_temp_skill`` writes a task-specific skill that is shown to
  the user, applies immediately, and expires in a week unless kept.

The roster is data (``agent_roster.json``, written by the Idea Maker), with a
built-in fallback so the team exists even before that file does.
"""

from __future__ import annotations

import contextvars
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import data_path, project_path

#: A specialist's own tool-step budget. Enough for real work, small enough that
#: a confused specialist hands back to the Manager instead of spinning.
SPECIALIST_MAX_STEPS = 10

#: Tools a specialist may not call: delegation stays with the Manager.
_MANAGER_ONLY_TOOLS = frozenset({"delegate_task", "delegate_parallel", "create_agent"})

_DEFAULT_ROSTER: List[Dict[str, Any]] = [
    {"id": "manager", "name": "Manager", "role": "master", "emoji": "🧭", "color": "#9184d9",
     "goal": "Understand what you want, route it to the right specialist, and deliver one verified answer.",
     "expertise": ["planning", "routing", "review"], "tools": ["*"]},
    {"id": "coder", "name": "Coder", "role": "worker", "emoji": "💻", "color": "#5a9ce0",
     "goal": "Write, run, and debug code and scripts on this computer.",
     "expertise": ["python", "javascript", "debugging", "scripts", "git"],
     "tools": ["run_command", "run_python", "read_file", "write_file", "search_files", "list_folder", "search_web"]},
    {"id": "web-design", "name": "Web Design", "role": "worker", "emoji": "🌐", "color": "#5ad6e0",
     "goal": "Design and build websites and landing pages that look great and load fast.",
     "expertise": ["html", "css", "react", "layout", "accessibility"], "tools": ["write_file", "read_file", "search_web", "open_url"]},
    {"id": "app-design", "name": "App Design", "role": "worker", "emoji": "📱", "color": "#e07ac0",
     "goal": "Design app interfaces, flows, and Nyx's own look — themes, tabs, and layout.",
     "expertise": ["ui", "ux", "themes", "tabs", "motion"], "tools": ["ui_set_theme", "ui_create_tab", "ui_edit_tab", "ui_open_tab"]},
    {"id": "finance", "name": "Finance", "role": "worker", "emoji": "📈", "color": "#5ac08a",
     "goal": "Explain markets, analyse stocks and budgets — education and analysis, never personalised investment advice.",
     "expertise": ["stocks", "budgets", "valuation", "risk"], "tools": ["stock_quote", "stock_history", "market_status", "search_finance_knowledge", "search_web"]},
    {"id": "educator", "name": "Educator", "role": "worker", "emoji": "🎓", "color": "#e0b45a",
     "goal": "Teach clearly — explain concepts, build study plans, and check understanding.",
     "expertise": ["teaching", "study", "math", "science", "history"], "tools": ["solve_math", "search_knowledge", "search_web"]},
    {"id": "tech", "name": "Tech", "role": "worker", "emoji": "🛠️", "color": "#75a8ff",
     "goal": "Fix and explain software, settings, networks, and anything misbehaving on this PC.",
     "expertise": ["windows", "troubleshooting", "networking", "software"], "tools": ["system_specs", "system_live", "run_command", "list_processes", "search_web"]},
    {"id": "hardware", "name": "Hardware", "role": "worker", "emoji": "🔧", "color": "#e0954a",
     "goal": "Read this machine's real specs and live temperatures, and advise on hardware.",
     "expertise": ["cpu", "gpu", "ram", "thermals", "upgrades"], "tools": ["system_specs", "system_live", "search_web"]},
    {"id": "news", "name": "News", "role": "worker", "emoji": "📰", "color": "#e07a7a",
     "goal": "Find what is happening now from current, dated sources — and say when sources disagree.",
     "expertise": ["current events", "briefings", "fact checking"], "tools": ["search_web", "open_link"]},
    {"id": "researcher", "name": "Researcher", "role": "worker", "emoji": "🔎", "color": "#a7a1db",
     "goal": "Dig into a question across many sources and return a cited, balanced summary.",
     "expertise": ["research", "citations", "comparison"], "tools": ["search_web", "open_link", "read_file"]},
    {"id": "writer", "name": "Writer", "role": "worker", "emoji": "✍️", "color": "#d2cefd",
     "goal": "Draft and polish writing for the right audience and tone.",
     "expertise": ["essays", "emails", "editing", "tone"], "tools": ["write_file", "read_file"]},
    {"id": "email", "name": "Email & Comms", "role": "worker", "emoji": "✉️", "color": "#7bd3a8",
     "goal": "Read, write, and send email for you — and never claim to have sent something it did not.",
     "expertise": ["email", "inbox", "replies", "scheduling"], "tools": ["email_send", "email_list", "email_read", "email_reply", "email_compose"]},
    {"id": "operator", "name": "Computer Operator", "role": "worker", "emoji": "🖱️", "color": "#b5abfc",
     "goal": "Use the mouse and keyboard on this computer, with a cursor you can watch, verifying every step.",
     "expertise": ["clicking", "typing", "apps", "windows"], "tools": ["screen_view", "find_on_screen", "mouse_click", "mouse_move", "mouse_scroll", "keyboard_type", "keyboard_keys", "open_app", "focus_window", "list_windows"]},
    {"id": "data-analyst", "name": "Data Analyst", "role": "worker", "emoji": "📊", "color": "#5ab8e0",
     "goal": "Turn spreadsheets, CSVs, and JSON into clear findings and charts.",
     "expertise": ["csv", "excel", "statistics", "charts"], "tools": ["summarize_data", "run_python", "read_file", "create_graph"]},
]

_LISTEN_RULES = (
    "How you work, as a specialist on Nyx's team:\n"
    "1. Begin your reply with one line: `Understood: <the task in your own words, including the definition of done>`.\n"
    "2. Note any constraint that matters. Ask a question only if you truly cannot proceed; otherwise make a sensible "
    "assumption and state it.\n"
    "3. Do the work with your tools. Check each result before moving on.\n"
    "4. Finish with a short report for the Manager: what you did, what you found or produced (paths, links, numbers), "
    "anything you could not do and why. Self-check it against the task before handing back."
)

_roster_cache: Dict[str, Any] = {"mtime": None, "agents": None}
_roster_lock = threading.Lock()


def _custom_agents_path() -> Path:
    return data_path("custom_agents.json")


def _overrides_path() -> Path:
    """Owner edits to built-in agents — a delta over the shipped roster (invariant 3)."""
    return data_path("agent_overrides.json")


#: What the Properties sheet (and the update_agent tool) may change.
EDITABLE_AGENT_FIELDS = ("name", "emoji", "color", "goal", "instructions", "expertise", "tools", "provider", "model",
                         # Request H2: what it is for, and whether/with whom it consults on heavy work.
                         "purpose", "consult", "consult_with", "consult_models")


def load_roster() -> List[Dict[str, Any]]:
    """The shipped roster (agent_roster.json, else the built-in team) plus user-made agents."""
    path = project_path("agent_roster.json")
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    custom_path = _custom_agents_path()
    try:
        custom_mtime = custom_path.stat().st_mtime
    except OSError:
        custom_mtime = None
    try:
        overrides_mtime = _overrides_path().stat().st_mtime
    except OSError:
        overrides_mtime = None

    with _roster_lock:
        stamp = (mtime, custom_mtime, overrides_mtime)
        if _roster_cache["agents"] is not None and _roster_cache["mtime"] == stamp:
            return _roster_cache["agents"]

        agents: List[Dict[str, Any]] = []
        if mtime is not None:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                agents = [a for a in raw.get("agents", []) if isinstance(a, dict) and a.get("name")]
            except (OSError, ValueError):
                agents = []
        if not agents or not any(a.get("role") == "master" for a in agents):
            agents = [dict(a) for a in _DEFAULT_ROSTER] if not agents else agents + [dict(_DEFAULT_ROSTER[0])]

        try:
            custom = json.loads(custom_path.read_text(encoding="utf-8")).get("agents", [])
            known = {a["name"].lower() for a in agents}
            agents += [dict(a, origin="assistant") for a in custom
                       if isinstance(a, dict) and a.get("name") and a["name"].lower() not in known]
        except (OSError, ValueError):
            pass

        try:
            overrides = json.loads(_overrides_path().read_text(encoding="utf-8")).get("agents", {})
        except (OSError, ValueError):
            overrides = {}
        for agent in agents:
            delta = overrides.get(str(agent.get("id") or agent["name"]).lower())
            if isinstance(delta, dict):
                agent.update({k: v for k, v in delta.items() if k in EDITABLE_AGENT_FIELDS})
                agent["edited"] = True

        _roster_cache.update(mtime=stamp, agents=agents)
        return agents


def _clean_agent_changes(changes: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an edit. Raises ValueError with a sentence the owner can act on."""
    import re as _re

    from tools import TOOL_REGISTRY

    clean: Dict[str, Any] = {}
    for key, value in changes.items():
        if key not in EDITABLE_AGENT_FIELDS or value is None:
            continue
        if key == "name":
            name = str(value).strip()[:40]
            if not name:
                raise ValueError("An agent needs a name.")
            if name.lower() != str(current.get("name", "")).lower() and roster_entry_exact(name):
                raise ValueError(f"There is already an agent called {name}.")
            clean[key] = name
        elif key == "emoji":
            clean[key] = str(value).strip()[:4] or "🤖"
        elif key == "color":
            if not _re.fullmatch(r"#[0-9a-fA-F]{6}", str(value).strip()):
                raise ValueError("Colour must look like #5a9ce0.")
            clean[key] = str(value).strip()
        elif key == "goal":
            if not str(value).strip():
                raise ValueError("The objective cannot be empty.")
            clean[key] = str(value).strip()[:300]
        elif key == "instructions":
            clean[key] = str(value).strip()[:4000]
        elif key == "expertise":
            items = value if isinstance(value, list) else str(value).split(",")
            clean[key] = [str(i).strip()[:40] for i in items if str(i).strip()][:8]
        elif key == "tools":
            items = value if isinstance(value, list) else [t for t in str(value).split(",")]
            items = [str(t).strip() for t in items if str(t).strip()]
            if not items or "*" in items:
                clean[key] = ["*"]
            else:
                unknown = [t for t in items if t not in TOOL_REGISTRY.tools]
                if unknown:
                    raise ValueError(f"Unknown tool(s): {', '.join(unknown[:5])}.")
                clean[key] = items[:60]
        elif key == "provider":
            provider = str(value).strip().lower()
            if provider in ("", "auto"):
                clean[key] = ""
            else:
                known = set(getattr(_router(), "providers", {}))
                if provider not in known:
                    raise ValueError(f"Unknown provider {provider!r}. Choose one of: {', '.join(sorted(known))}.")
                clean[key] = provider
        elif key == "model":
            clean[key] = str(value).strip()[:120]
        elif key == "purpose":
            clean[key] = str(value).strip()[:600]
        elif key == "consult":
            mode = str(value).strip().lower()
            if mode not in ("off", "heavy", "always"):
                raise ValueError("Consults must be off, heavy (hard tasks only) or always.")
            clean[key] = mode
        elif key == "consult_models":
            mode = str(value).strip().lower()
            if mode not in ("same", "other", "both"):
                raise ValueError("Consult models must be same, other or both.")
            clean[key] = mode
        elif key == "consult_with":
            items = value if isinstance(value, list) else str(value).split(",")
            names = [str(i).strip() for i in items if str(i).strip()]
            unknown = [n for n in names if not roster_entry_exact(n)]
            if unknown:
                raise ValueError(f"No agent called {', '.join(unknown[:3])}.")
            own = str(current.get("name", "")).lower()
            clean[key] = [roster_entry_exact(n)["name"] for n in names if n.lower() != own][:4]
    return clean


def roster_entry_exact(name: str) -> Optional[Dict[str, Any]]:
    wanted = (name or "").strip().lower()
    return next((a for a in load_roster() if a["name"].lower() == wanted), None)


def agent_properties(name: str) -> Optional[Dict[str, Any]]:
    """Everything the Properties sheet shows for one agent: settings, live status, recent work."""
    from agent_team import AGENT_TEAM

    entry = roster_entry_exact(name) or roster_entry(name)
    if entry is None:
        return None
    sync_team(AGENT_TEAM)
    member = AGENT_TEAM.find(entry["name"])
    live = member.snapshot() if member else {}
    return {
        "name": entry["name"],
        "id": entry.get("id", ""),
        "role": entry.get("role", "worker"),
        "emoji": entry.get("emoji", ""),
        "color": entry.get("color", ""),
        "goal": entry.get("goal", ""),
        "instructions": entry.get("instructions", ""),
        "expertise": list(entry.get("expertise", []) or []),
        "tools": list(entry.get("tools", ["*"]) or ["*"]),
        "provider": entry.get("provider", ""),
        "model": entry.get("model", ""),
        "purpose": entry.get("purpose", ""),
        "consult": entry.get("consult") or "heavy",
        "consult_with": list(entry.get("consult_with", []) or []),
        "consult_models": entry.get("consult_models") or "both",
        "origin": entry.get("origin", "roster"),
        "builtin": entry.get("origin", "roster") == "roster",
        "made_by": entry.get("made_by") or ("nyx" if entry.get("created_in_chat") else
                                            "builtin" if entry.get("origin", "roster") == "roster" else "owner"),
        "edited": bool(entry.get("edited")),
        "created_in_chat": entry.get("created_in_chat", ""),
        "live": live,
    }


def update_agent(name: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    """Change an agent's properties. Built-in agents keep the edit as an override."""
    from agent_team import AGENT_TEAM

    current = roster_entry_exact(name) or roster_entry(name)
    if current is None:
        raise KeyError(f"No agent called {name!r}.")
    clean = _clean_agent_changes(changes, current)
    if not clean:
        return agent_properties(current["name"]) or {}
    if current.get("role") == "master" and "name" in clean:
        clean.pop("name")  # the Manager is addressed by that name throughout the prompt

    custom_path = _custom_agents_path()
    try:
        custom = json.loads(custom_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        custom = {"agents": []}
    own = next((a for a in custom.get("agents", []) if a.get("name", "").lower() == current["name"].lower()), None)
    if own is not None and current.get("origin") != "roster":
        own.update(clean)
        custom_path.write_text(json.dumps(custom, indent=2), encoding="utf-8")
    else:
        path = _overrides_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"agents": {}}
        key = str(current.get("id") or current["name"]).lower()
        data.setdefault("agents", {}).setdefault(key, {}).update(clean)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    with _roster_lock:
        _roster_cache["agents"] = None
    member = AGENT_TEAM.find(current["name"])
    if member is not None:
        if "name" in clean:
            member.name = clean["name"]
        if "goal" in clean:
            member.goal = clean["goal"]
        member.meta.update({k: v for k, v in clean.items() if k in ("emoji", "color", "expertise", "tools", "provider", "model")})
    new_name = clean.get("name", current["name"])
    try:
        from agent_events import publish_ui

        publish_ui("agents.changed")
        publish_ui("agent.updated", name=new_name, changes=sorted(clean))
    except Exception:
        pass
    return agent_properties(new_name) or {}


def all_agent_details() -> List[Dict[str, Any]]:
    """Every agent's properties and live status at once — the Team details sheet (Request H2)."""
    return [props for props in (agent_properties(a["name"]) for a in load_roster()) if props]


def create_subagent(fields: Dict[str, Any]) -> Dict[str, Any]:
    """A new sub-agent with its model and consult settings, from the Sub-agents tab."""
    name = str(fields.get("name") or "").strip()
    goal = str(fields.get("goal") or "").strip()
    if not name or not goal:
        raise ValueError("A sub-agent needs a name and a goal.")
    result = tool_create_agent(name, goal, instructions=str(fields.get("instructions") or ""),
                               expertise=str(fields.get("expertise") or ""), emoji=str(fields.get("emoji") or "🤖"))
    if result.startswith("Error") or result.startswith("There is already"):
        raise ValueError(result.replace("Error: ", ""))
    extra = {k: fields[k] for k in ("provider", "model", "purpose", "consult", "consult_with", "consult_models")
             if fields.get(k) not in (None, "", [])}
    try:
        return update_agent(name, extra) if extra else (agent_properties(name) or {})
    except ValueError:
        remove_custom_agent(name)
        raise


def remove_custom_agent(name: str) -> bool:
    """Delete an agent someone made (never a built-in one). Its past work stays in chats."""
    from agent_team import AGENT_TEAM

    path = _custom_agents_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    before = len(data.get("agents", []))
    data["agents"] = [a for a in data.get("agents", []) if a.get("name", "").lower() != (name or "").strip().lower()]
    if len(data["agents"]) == before:
        return False
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with _roster_lock:
        _roster_cache["agents"] = None
    member = AGENT_TEAM.find(name)
    if member is not None and getattr(member, "name", "").lower() == name.strip().lower():
        AGENT_TEAM.dismiss(member.agent_id)
    try:
        from agent_events import publish_ui

        publish_ui("agents.changed")
    except Exception:
        pass
    return True


def roster_entry(name: str) -> Optional[Dict[str, Any]]:
    wanted = (name or "").strip().lower()
    roster = load_roster()
    for agent in roster:
        if agent["name"].lower() == wanted or str(agent.get("id", "")).lower() == wanted:
            return agent
    for agent in roster:
        if wanted and (wanted in agent["name"].lower() or agent["name"].lower() in wanted):
            return agent
    return None


def roster_summary() -> str:
    """The team as the Manager's system prompt describes it."""
    lines = ["You are the Manager. Specialists you can hand work to with delegate_task:"]
    for agent in load_roster():
        if agent.get("role") == "master":
            continue
        expertise = ", ".join(agent.get("expertise", [])[:5])
        lines.append(f"- {agent.get('emoji', '')} {agent['name']}: {agent.get('goal', '')}"
                     + (f" ({expertise})" if expertise else ""))
    lines.append("Delegate when a specialist's focus clearly improves the result or when parts can run in "
                 "parallel (delegate_parallel, or dispatch_agents for several copies of one specialist). Give them the "
                 "whole context they need — they do not see this chat.")
    lines.append("Use them on your own: the owner should never have to ask you to bring in the right agent. When a "
                 "substantial or recurring kind of work has no fitting specialist, create one with create_agent (it "
                 "appears in the Sub-agents tab, the Core view and as a / command) and hand it the work.")
    return "\n".join(lines)


def sync_team(team: Any) -> None:
    """Make the live team match the roster, without touching agents people made.

    Retires the two placeholder names the previous seeding created ("Site/Web
    Dev", "Checker") only while they have never done any work.
    """
    for legacy in ("Site/Web Dev", "Checker"):
        agent = team.find(legacy)
        if agent is not None and agent.name == legacy and agent.steps_completed == 0 and not agent.recent:
            with team._lock:
                team._agents.pop(agent.agent_id, None)

    from agent_team import AgentRole

    for entry in load_roster():
        existing = next((a for a in team.members() if a.name.lower() == entry["name"].lower()), None)
        role = AgentRole.MASTER if entry.get("role") == "master" else AgentRole.WORKER
        meta = {k: entry.get(k) for k in ("emoji", "color", "expertise", "voice_hint", "tools", "id",
                                          "created_in_chat", "created_at")}
        if existing is None:
            if role is AgentRole.MASTER:
                master = next((a for a in team.members() if a.role is AgentRole.MASTER), None)
                if master is not None and master.name.lower() in ("manager", "master"):
                    master.name = entry["name"]
                    master.goal = entry.get("goal", master.goal)
                    master.meta.update(meta)
                    master.origin = "roster"
                    continue
            existing = team.spawn(entry["name"], goal=entry.get("goal", ""), role=role, auto_created=False)
        existing.meta.update({k: v for k, v in meta.items() if v})
        existing.origin = entry.get("origin", "roster")
        if not existing.goal and entry.get("goal"):
            existing.goal = entry["goal"]


# ---------------------------------------------------------------------------
# Running a specialist
# ---------------------------------------------------------------------------

_router_lock = threading.Lock()
_shared_router: Any = None


def _router() -> Any:
    global _shared_router
    with _router_lock:
        if _shared_router is None:
            from router import Router

            _shared_router = Router()
        return _shared_router


def _specialist_prompt(entry: Dict[str, Any]) -> str:
    from chat_service import ChatService
    from tools import TOOL_REGISTRY

    allowed = entry.get("tools") or ["*"]
    names = sorted(TOOL_REGISTRY.tools) if "*" in allowed else [n for n in allowed if n in TOOL_REGISTRY.tools]
    names = [n for n in names if n not in _MANAGER_ONLY_TOOLS]
    # Every agent can file an idea or a tab for the owner, whatever its own tool list (Command Zone).
    for helper in ("search_web", "read_file", "get_time", "propose_idea", "suggest_tab"):
        if helper in TOOL_REGISTRY.tools and helper not in names:
            names.append(helper)
    tool_lines = []
    for name in names:
        tool = TOOL_REGISTRY.tools[name]
        params = ", ".join(f"{p.name}{'' if p.required else '?'}" for p in tool.parameters)
        tool_lines.append(f"- {name}({params}): {tool.description}")

    instructions = entry.get("instructions") or f"You are {entry['name']}. {entry.get('goal', '')}"
    return (
        f"You are {entry['name']} {entry.get('emoji', '')} — a specialist on Nyx Ichos's agent team, working for "
        f"the Manager on the user's own Windows PC.\nYour focus: {entry.get('goal', '')}\n\n{instructions}\n\n"
        f"{_LISTEN_RULES}\n\n## This computer\n{ChatService._environment_note()}\n\n"
        "## Tools\nUse a tool by writing exactly:\n<tool_call>\nname: tool_name\narguments: {\"param\": \"value\"}\n"
        "</tool_call>\nThe result comes back to you. Before a tool call, write one short line in <thinking> tags "
        "saying what you are doing. Tools available to you:\n" + "\n".join(tool_lines)
    )


def run_specialist(name: str, task: str, context: str = "", max_steps: int = SPECIALIST_MAX_STEPS) -> str:
    """Hand ``task`` to one specialist and return its report for the Manager."""
    import re

    from agent_team import AGENT_TEAM
    from tool_context import ToolContext, current, use_context
    from tools import TOOL_REGISTRY
    from turn_runner import StreamFilter, thinking_lines, visible_answer

    sync_team(AGENT_TEAM)
    entry = roster_entry(name)
    member = AGENT_TEAM.find(name)
    if entry is None or member is None:
        names = ", ".join(a["name"] for a in load_roster() if a.get("role") != "master")
        return f"No agent called {name!r}. The team is: {names}. Try one of those, or create_agent."
    if entry.get("role") == "master":
        return "The Manager is you — handle this directly, or pick a specialist."

    parent = current()
    started = time.perf_counter()
    base = {"agent_id": member.agent_id, "name": member.name, "emoji": entry.get("emoji", ""),
            "color": entry.get("color", "")}

    origin_chat = parent.chat_id if parent else ""
    origin_turn = parent.turn_id if parent else ""

    def parent_emit(event: Dict[str, Any]) -> None:
        kind = event.pop("type")
        if kind == "agent.update":
            # Agent status goes workspace-wide as well as into the turn, so the
            # Agents tab, the agent dock and every other open window move with
            # it. Before, only the chat that started the work could see it —
            # and that chat's UI was not listening — so agents looked frozen.
            try:
                from agent_events import publish_ui

                publish_ui("agent.update", chat_id=origin_chat, turn_id=origin_turn, **event)
            except Exception:
                pass
        if parent is not None:
            parent.emit(kind, **event)

    def child_sink(event: Dict[str, Any]) -> None:
        event = dict(event)
        event.setdefault("agent", member.name)
        event.setdefault("agent_id", member.agent_id)
        parent_emit(event)

    child = ToolContext(
        turn_id=parent.turn_id if parent else "",
        chat_id=parent.chat_id if parent else "default",
        role=parent.role if parent else "local",
        sink=child_sink if parent else None,
    )
    if parent is not None:
        child.cancelled = parent.cancelled

    AGENT_TEAM.begin(member.agent_id, "Reading the task")
    parent_emit({"type": "agent.update", **base, "status": "working", "step": "Reading the task", "task": task[:300]})

    history: List[Dict[str, Any]] = [
        {"role": "system", "content": _specialist_prompt(entry)},
        {"role": "user", "content": f"Task from the Manager:\n{task}" + (f"\n\nContext:\n{context}" if context else "")},
    ]
    mode = entry.get("consult") or "heavy"
    try:
        import consult as consult_module

        if mode == "always" or (mode == "heavy" and consult_module.is_heavy(f"{task}\n{context}")):
            parent_emit({"type": "agent.update", **base, "status": "working", "step": "Getting second opinions"})
            notes = consult_module.consult(
                task, primary=entry.get("provider") or "", primary_model=entry.get("model") or "",
                models=entry.get("consult_models") or "both",
                agents=consult_module.agents_named(list(entry.get("consult_with") or [])), budget=20)
            for note in notes:
                parent_emit({"type": "thought", "text": f"{note['by']}: {note['text']}", "source": "consult",
                             "agent": member.name})
            if notes:
                history.insert(1, {"role": "system", "content": consult_module.as_context(notes)})
    except Exception:  # noqa: BLE001 - consulting is optional; the specialist still works
        pass
    report = ""
    understanding_sent = False
    ok = True

    with use_context(child):
        try:
            for step in range(1, max_steps + 1):
                if child.cancelled.is_set():
                    report = "Stopped before finishing."
                    break
                collected: List[str] = []

                def on_event(event: Dict[str, Any]) -> None:
                    if event.get("type") == "text":
                        collected.append(event.get("text", ""))
                    elif event.get("type") == "thought" and parent is not None:
                        parent_emit({"type": "thought.delta", "text": event.get("text", ""), "source": "model",
                                     "agent": member.name})

                text, used_provider = _router().stream(history, on_event, smart=True, thinking=True,
                                                       cancelled=child.cancelled.is_set,
                                                       prefer=entry.get("provider") or None,
                                                       prefer_model=entry.get("model") or None)
                if used_provider and used_provider != base.get("provider"):
                    base["provider"] = used_provider
                    base["model"] = entry.get("model", "") if used_provider == entry.get("provider") else ""
                    AGENT_TEAM.set_step(member.agent_id, f"Thinking with {used_provider}")
                understood = re.search(r"Understood:\s*(.+)", text)
                if understood and not understanding_sent:
                    understanding_sent = True
                    line = understood.group(1).strip().splitlines()[0][:300]
                    AGENT_TEAM.set_step(member.agent_id, "Working")
                    parent_emit({"type": "agent.update", **base, "status": "working", "step": "Working",
                                 "understanding": line})
                for plan in thinking_lines(text):
                    parent_emit({"type": "agent.update", **base, "status": "working", "step": plan[:160]})
                    AGENT_TEAM.set_step(member.agent_id, plan[:160])

                calls = [(n, a) for n, a in TOOL_REGISTRY.parse_tool_calls(text) if n not in _MANAGER_ONLY_TOOLS]
                if not calls:
                    report = visible_answer(text)
                    break
                history.append({"role": "assistant", "content": text})
                outputs = [f"Tool '{n}' returned:\n{TOOL_REGISTRY.call_tool(n, **a)}" for n, a in calls[:6]]
                follow: Dict[str, Any] = {"role": "user", "content": "Tool results:\n" + "\n\n".join(outputs)
                                          + "\n\nContinue, or give your final report."}
                images = child.take_images()
                if images:
                    follow["images"] = images
                history.append(follow)
            else:
                history.append({"role": "system", "content": "Step budget used. Give your final report now, no tools."})
                text, _ = _router().stream(history, None, smart=True, thinking=False,
                                           prefer=entry.get("provider") or None,
                                           prefer_model=entry.get("model") or None)
                report = visible_answer(text)
        except Exception as error:  # noqa: BLE001 - a failed specialist is reported, not fatal
            ok = False
            report = f"{member.name} could not finish: {type(error).__name__}: {error}"

    seconds = time.perf_counter() - started
    report = report or f"{member.name} returned no report."
    if ok:
        AGENT_TEAM.finish_step(member.agent_id)
    else:
        AGENT_TEAM.fail(member.agent_id, report[:200])
    AGENT_TEAM.record_task(member.agent_id, task, report, seconds, ok=ok, chat_id=origin_chat, turn_id=origin_turn)
    parent_emit({"type": "agent.update", **base, "status": "done" if ok else "error",
                 "step": "Reported back" if ok else "Failed", "result_preview": report[:400],
                 "seconds": round(seconds, 1)})
    try:
        from agent_events import publish_ui

        publish_ui("agents.changed")
    except Exception:
        pass
    return f"Report from {member.name} ({seconds:.0f}s):\n{report}"


def start_agent_task(name: str, task: str, context: str = "", role: str = "local") -> Dict[str, Any]:
    """Run one specialist on a task in the background, watchable like a chat turn.

    Used when the user gives an agent work directly (Agents tab, "Create and
    start"). The run is a registered turn, so its steps stream to anyone who
    opens /api/turns/{id}/stream and it keeps going if that page is closed.
    """
    import uuid as _uuid

    from tool_context import ToolContext, use_context
    from turn_registry import TURNS

    turn_id = _uuid.uuid4().hex[:12]
    chat_id = f"agent:{(name or '').strip().lower()}"
    record = TURNS.start(turn_id, chat_id, task)

    def sink(event: Dict[str, Any]) -> None:
        event.setdefault("turn_id", turn_id)
        TURNS.append(turn_id, event)

    def work() -> None:
        started = time.perf_counter()
        ctx = ToolContext(turn_id=turn_id, chat_id=chat_id, role=role, sink=sink)
        ctx.cancelled = record.cancel
        state = "done"
        with use_context(ctx):
            sink({"type": "turn.start", "chat_id": chat_id, "mode": "agent", "agent": name})
            sink({"type": "status", "phase": "agents", "text": f"{name} is working"})
            try:
                report = run_specialist(name, task, context=context)
            except Exception as error:  # noqa: BLE001 - reported to viewers
                state = "error"
                sink({"type": "error", "message": f"{type(error).__name__}: {error}"})
                report = ""
        if state == "done":
            sink({"type": "answer.delta", "text": report})
            sink({"type": "done", "reply": report, "provider": "agent", "chat_id": chat_id, "turn_id": turn_id,
                  "elapsed_ms": round((time.perf_counter() - started) * 1000), "stopped": record.cancel.is_set()})
        TURNS.finish(turn_id, "stopped" if record.cancel.is_set() else state)

    threading.Thread(target=work, name=f"nyx-agent-{turn_id}", daemon=True).start()
    return {"turn_id": turn_id, "chat_id": chat_id, "agent": name}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def tool_delegate_task(agent: str, task: str, context: str = "") -> str:
    if not (task or "").strip():
        return "Error: say what the agent should do."
    return run_specialist(agent, task, context)


def tool_delegate_parallel(tasks: Any) -> str:
    """Several specialists at once, bounded by the owner's Power setting."""
    if isinstance(tasks, str):
        try:
            tasks = json.loads(tasks)
        except ValueError:
            return 'Error: tasks must be a list like [{"agent": "News", "task": "..."}].'
    if not isinstance(tasks, list) or not tasks:
        return "Error: give at least one {agent, task}."
    try:
        from resource_governor import GOVERNOR

        workers = max(1, min(len(tasks), GOVERNOR.ceiling().max_agents, 6))
    except Exception:
        workers = min(len(tasks), 3)

    def run_one(item: Dict[str, Any]) -> str:
        return run_specialist(str(item.get("agent", "")), str(item.get("task", "")), str(item.get("context", "")))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(contextvars.copy_context().run, run_one, item) for item in tasks[:8]
                   if isinstance(item, dict)]
        reports = []
        for f in futures:
            try:
                reports.append(f.result(timeout=300))  # 5-minute guard per specialist
            except Exception as error:
                reports.append(f"Task failed or timed out: {type(error).__name__}: {error}")
    return "\n\n---\n\n".join(reports)


def tool_list_agents() -> str:
    from agent_team import AGENT_TEAM

    sync_team(AGENT_TEAM)
    lines = []
    for agent in AGENT_TEAM.snapshot()["agents"]:
        lines.append(f"- {agent['emoji']} {agent['name']} ({agent['role']}, {agent['status']}): {agent['goal']}")
    return "The team:\n" + "\n".join(lines)


def _current_context() -> Any:
    try:
        from tool_context import current

        return current()
    except Exception:
        return None


def tool_create_agent(name: str, goal: str, instructions: str = "", expertise: str = "", emoji: str = "🤖") -> str:
    """The assistant (or the user through it) adds a specialist to the team."""
    from agent_team import AGENT_TEAM

    clean = (name or "").strip()[:40]
    if not clean or not (goal or "").strip():
        return "Error: an agent needs a name and a goal."
    path = _custom_agents_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"agents": []}
    # Exact names only. roster_entry() is deliberately forgiving ("research"
    # finds Researcher) for delegation, but using it here refused to create a
    # distinct "research" agent and handed back a different one.
    taken = {a.get("name", "").lower() for a in load_roster()} | {a.get("name", "").lower() for a in data["agents"]}
    if clean.lower() in taken:
        return f"There is already an agent called {clean}."
    ctx_for_origin = _current_context()
    entry = {
        "id": clean.lower().replace(" ", "-"), "name": clean, "role": "worker", "emoji": (emoji or "🤖")[:4],
        # Nyx made it in a chat turn, or the owner made it in the Sub-agents tab / Core view.
        "made_by": "nyx" if ctx_for_origin is not None and getattr(ctx_for_origin, "sink", None) is not None else "owner",
        "color": "#9397ab", "goal": goal.strip()[:300], "instructions": (instructions or "").strip()[:2000],
        "expertise": [e.strip() for e in (expertise or "").split(",") if e.strip()][:8], "tools": ["*"],
        "created_at": time.time(),
    }
    ctx = _current_context()
    if ctx is not None:
        # Where the agent was born, so the Agents tab can say "created in chat
        # Trip planning" and link back — agents are made in conversation.
        entry["created_in_chat"] = ctx.chat_id
        entry["created_in_turn"] = ctx.turn_id
    data["agents"].append(entry)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    sync_team(AGENT_TEAM)
    try:
        from agent_events import publish_ui

        publish_ui("agents.changed")
        publish_ui("agent.created", name=clean, emoji=entry["emoji"], goal=entry["goal"],
                   chat_id=entry.get("created_in_chat", ""), turn_id=entry.get("created_in_turn", ""))
        publish_ui("notify", text=f"New agent on the team: {entry['emoji']} {clean}", level="ok")
    except Exception:
        pass
    if ctx is not None:
        member = AGENT_TEAM.find(clean)
        ctx.emit("agent.created", name=clean, emoji=entry["emoji"], goal=entry["goal"], color=entry["color"],
                 agent_id=member.agent_id if member else "", chat_id=ctx.chat_id)
    return f"Created {entry['emoji']} {clean}. Delegate to it with delegate_task(agent='{clean}', task=...)."


def tool_create_agent_in_chat(name: str, goal: str, instructions: str = "", expertise: str = "", emoji: str = "🤖",
                              provider: str = "", model: str = "", purpose: str = "", consult: str = "") -> str:
    """create_agent as the chat uses it: the agent plus the model and consult settings the user asked for."""
    result = tool_create_agent(name, goal, instructions=instructions, expertise=expertise, emoji=emoji or "🤖")
    extra = {k: v for k, v in {"provider": provider, "model": model, "purpose": purpose, "consult": consult}.items()
             if str(v or "").strip() and str(v).strip().lower() != "auto"}
    if not extra or not result.startswith("Created"):
        return result
    try:
        props = update_agent(name.strip()[:40], extra)
    except (KeyError, ValueError) as error:
        return f"{result} (Its settings were not applied: {str(error).strip(chr(39))})"
    uses = (props.get("provider") or "auto") + (f" · {props['model']}" if props.get("model") else "")
    return f"{result} It thinks with {uses}; consults: {props.get('consult', 'heavy')}."


def tool_update_agent(name: str, goal: str = "", instructions: str = "", provider: str = "", model: str = "",
                      expertise: str = "", emoji: str = "", tools: str = "", new_name: str = "", purpose: str = "",
                      consult: str = "", consult_with: str = "", consult_models: str = "") -> str:
    """The update_agent tool: the same edit as the Properties sheet, by asking."""
    changes: Dict[str, Any] = {k: v for k, v in {
        "goal": goal, "instructions": instructions, "provider": provider, "model": model,
        "expertise": expertise, "emoji": emoji, "tools": tools, "name": new_name, "purpose": purpose,
        "consult": consult, "consult_with": consult_with, "consult_models": consult_models,
    }.items() if str(v).strip()}
    if not changes:
        return "Say what to change: goal, instructions, provider, model, expertise, emoji, tools or new_name."
    try:
        props = update_agent(name, changes)
    except (KeyError, ValueError) as error:
        return f"Could not update {name}: {str(error).strip(chr(39))}"
    ctx = _current_context()
    if ctx is not None:
        ctx.emit("agent.updated", name=props.get("name", name), changes=sorted(changes))
    uses = f"{props.get('provider') or 'auto'}" + (f" · {props['model']}" if props.get("model") else "")
    return f"Updated {props.get('emoji', '')} {props.get('name', name)} ({', '.join(sorted(changes))}). It now thinks with {uses}."


def tool_search_skills(query: str) -> str:
    from skills import SKILL_STORE

    results = SKILL_STORE.search(query, limit=6)
    if not results:
        return f"No skills match {query!r}. If this task needs a focused procedure, create_temp_skill."
    lines = [f"Skills matching {query!r}:"]
    for r in results:
        tag = " [temporary]" if r["temp"] else ""
        lines.append(f"- {r['name']} (id {r['id']}){tag}: {r['description']} — matched {r['why'] or 'loosely'}")
    lines.append("Apply one with use_skill(skill='id or name').")
    return "\n".join(lines)


def tool_use_skill(skill: str) -> str:
    from skills import SKILL_STORE
    from tool_context import emit

    found = SKILL_STORE.get(skill)
    if found is None:
        matches = SKILL_STORE.search(skill, limit=1)
        found = SKILL_STORE.get(matches[0]["id"]) if matches else None
    if found is None:
        return f"No skill called {skill!r}. Use search_skills to find one."
    emit("skill.used", skills=[{"id": found.skill_id, "name": found.name, "source": found.source,
                                "temp": found.source == "temp", "why": "chosen by the assistant"}])
    return f"Skill '{found.name}' — follow these instructions for this task:\n{found.instructions}"


def tool_create_temp_skill(name: str, instructions: str, description: str = "", triggers: str = "") -> str:
    from skills import SKILL_STORE, SkillError
    from tool_context import current, emit

    ctx = current()
    trigger_list = [t.strip() for t in (triggers or "").split(",") if t.strip()]
    try:
        skill = SKILL_STORE.add(name, description or name, instructions, trigger_list, source="temp",
                                author="assistant", chat_id=ctx.chat_id if ctx else "")
    except SkillError as error:
        return f"Error: {error}"
    emit("skill.created", skill=skill.as_dict())
    try:
        from agent_events import publish_ui

        publish_ui("skills.changed")
    except Exception:
        pass
    return (f"Temporary skill '{skill.name}' created and shown to the user (they can keep it). "
            f"Apply it now:\n{skill.instructions}")


def register_agent_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="delegate_task",
        description="Hand a focused task to a specialist agent on your team and get their report back. "
                    "They do not see the chat, so include everything they need in task/context.",
        parameters=[
            ToolParam("agent", "string", "Specialist name, e.g. Coder, News, Finance, Computer Operator"),
            ToolParam("task", "string", "What they should do, with the definition of done"),
            ToolParam("context", "string", "Facts from the conversation they need", required=False),
        ],
        handler=tool_delegate_task,
        category="agents",
        label=lambda a: f"Asking {a.get('agent', 'a specialist')}: {str(a.get('task', ''))[:70]}",
    )
    registry.register(
        name="delegate_parallel",
        description="Run several specialists at the same time. tasks is a JSON list of {\"agent\", \"task\", \"context\"}.",
        parameters=[ToolParam("tasks", "array", "List of {agent, task, context} objects")],
        handler=tool_delegate_parallel,
        category="agents",
        label=lambda a: f"Running {len(a.get('tasks') or []) if isinstance(a.get('tasks'), list) else 'several'} specialists in parallel",
    )
    registry.register(
        name="list_agents",
        description="List the agent team with each agent's focus and status.",
        parameters=[],
        handler=tool_list_agents,
        category="general",
        label="Checking the team",
    )
    registry.register(
        name="create_agent",
        description="Add a new specialist agent to the team (persists). Use when the user asks for one or a recurring need has no specialist.",
        parameters=[
            ToolParam("name", "string", "Short name"),
            ToolParam("goal", "string", "What it is for"),
            ToolParam("instructions", "string", "How it should work", required=False),
            ToolParam("expertise", "string", "Comma-separated strengths", required=False),
            ToolParam("emoji", "string", "One emoji", required=False),
            ToolParam("provider", "string", "Provider it thinks with if the user named one (nvidia, groq, gemini…)", required=False),
            ToolParam("model", "string", "Model id if the user named one", required=False),
            ToolParam("purpose", "string", "Why it exists / what success looks like", required=False),
            ToolParam("consult", "string", "off, heavy (consult others on hard tasks) or always", required=False,
                      enum_values=["off", "heavy", "always"]),
        ],
        handler=tool_create_agent_in_chat,
        category="agents",
        label=lambda a: f"Creating agent {a.get('name', '')}",
    )
    registry.register(
        name="update_agent",
        description=("Change an agent's properties: its objective (goal), instructions, the provider and model it "
                     "thinks with, expertise, emoji or allowed tools. Use when the user asks to change an agent, "
                     "e.g. 'make Coder use nvidia' or 'give Researcher a new objective'."),
        parameters=[
            ToolParam("name", "string", "The agent to change"),
            ToolParam("goal", "string", "New objective", required=False),
            ToolParam("instructions", "string", "New instructions", required=False),
            ToolParam("provider", "string", "Provider it should use (gemini, nvidia, groq…; 'auto' for the router)", required=False),
            ToolParam("model", "string", "Model id for that provider", required=False),
            ToolParam("expertise", "string", "Comma-separated strengths", required=False),
            ToolParam("emoji", "string", "One emoji", required=False),
            ToolParam("tools", "string", "Comma-separated tool names, or * for all", required=False),
            ToolParam("new_name", "string", "Rename the agent", required=False),
            ToolParam("purpose", "string", "What it is for / what success looks like", required=False),
            ToolParam("consult", "string", "off, heavy or always", required=False, enum_values=["off", "heavy", "always"]),
            ToolParam("consult_with", "string", "Comma-separated agent names it should ask", required=False),
            ToolParam("consult_models", "string", "same, other or both", required=False, enum_values=["same", "other", "both"]),
        ],
        handler=tool_update_agent,
        category="agents",
        label=lambda a: f"Updating agent {a.get('name', '')}",
    )
    registry.register(
        name="search_skills",
        description="Search the skill library for procedures that fit the current task.",
        parameters=[ToolParam("query", "string", "What the task is about")],
        handler=tool_search_skills,
        category="general",
        label=lambda a: f"Looking for skills: {str(a.get('query', ''))[:60]}",
    )
    registry.register(
        name="use_skill",
        description="Apply a skill from the library to this task (by id or name).",
        parameters=[ToolParam("skill", "string", "Skill id or name")],
        handler=tool_use_skill,
        category="general",
        label=lambda a: f"Using skill {a.get('skill', '')}",
    )
    registry.register(
        name="create_temp_skill",
        description="Write a temporary, task-specific skill (a focused procedure) when no existing skill fits. "
                    "It is shown to the user, applies now, and expires in a week unless they keep it.",
        parameters=[
            ToolParam("name", "string", "Short name"),
            ToolParam("instructions", "string", "The procedure, 60-150 words"),
            ToolParam("description", "string", "One line on what it is for", required=False),
            ToolParam("triggers", "string", "Comma-separated phrases that mean it applies", required=False),
        ],
        handler=tool_create_temp_skill,
        category="general",
        label=lambda a: f"Creating a skill: {a.get('name', '')}",
    )
