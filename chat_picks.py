"""The chat's bottom bar: Skills · Agents · Connectors, picked by hand or left on Auto (Plan Null N36/N37).

Owner, 2026-09-22: "add a bottom bar to the chat which has 3 things, skills, agents/subagents, and connectors where
after I click one I can click auto which is default for all of them … (one click to select and one to deselect and
you can choose which ever you like) for agents it creates two options auto interpret and send an individual message
through a main agent who decoders and is able to organize and determine what to send each agent specifically or
normal option where each agent is given the same prompt and knows they can communicate."

A turn's picks come in with the request (``routes_live``) and wait here under the turn id until the TurnRunner running
that turn takes them. So no signature between the route and the runner has to change, and two turns in one chat never
see each other's picks.

Each category is ``"auto"`` (the default: what Nyx already did), ``"off"``, or a list the owner picked. A hand pick
replaces Auto for that category only:

* **Skills**: the picked skills' full instructions are read first, in place of the ones matched by trigger words.
* **Agents**: the picked agents run before the Manager answers. In *interpret* mode a main agent reads the one message
  and writes each agent its own instruction. In *normal* mode every agent gets the owner's words unchanged, is told
  who else is working on them, and after the first drafts each one sees the others' work and can answer it once.
  The Manager then writes the reply from their reports. Auto leaves the choice to ``agent_match``/``agent_grading``
  (they read ``runner.agent_choice``).
* **Connectors**: handed to ``connector_use``, which also reads ``&name`` mentions and predicts on Auto.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

_LOG = logging.getLogger("nyx.chat_picks")

AUTO = "auto"
OFF = "off"
AGENT_MODES = ("interpret", "normal")
SURFACES = ("chat", "nyx", "freewill", "kahuna", "voice", "agent", "office", "zone")
LIMITS = {"skills": 8, "agents": 6, "connectors": 8}

SKILLS_PREFIX = "[Skills picked in the chat bar]"
TEAM_PREFIX = "[Picked agents' work]"
#: What chat_service._attach_skills writes for trigger-matched skills (a hand pick replaces it).
AUTO_SKILLS_PREFIX = "[Skills active for this turn]"

_PENDING_TTL = 600.0
_PENDING_MAX = 200
_AGENT_TIMEOUT = 300.0
_lock = threading.Lock()
_pending: Dict[str, tuple] = {}


# ---------------------------------------------------------------------------
# What the request carried
# ---------------------------------------------------------------------------

def _choice(value: Any, limit: int) -> Any:
    """``"auto"``, ``"off"`` or a de-duplicated list of names (at most ``limit``)."""
    if value is None:
        return AUTO
    if isinstance(value, str):
        word = value.strip().lower()
        if word in ("", AUTO):
            return AUTO
        if word in (OFF, "none"):
            return OFF
        value = [part for part in re.split(r"[,\n]+", value) if part.strip()]
    if isinstance(value, (list, tuple)):
        items: List[str] = []
        for item in value:
            name = str(item or "").strip()[:80]
            if name and name.lower() not in {i.lower() for i in items}:
                items.append(name)
        return items[:limit] if items else AUTO
    return AUTO


def normalize(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    mode = str(raw.get("agent_mode") or "").strip().lower()
    surface = str(raw.get("surface") or "chat").strip().lower()
    return {
        "skills": _choice(raw.get("skills"), LIMITS["skills"]),
        "agents": _choice(raw.get("agents"), LIMITS["agents"]),
        "connectors": _choice(raw.get("connectors"), LIMITS["connectors"]),
        "agent_mode": mode if mode in AGENT_MODES else "interpret",
        "surface": surface if surface in SURFACES else "chat",
    }


def is_default(picks: Dict[str, Any]) -> bool:
    return all(picks.get(k) == AUTO for k in ("skills", "agents", "connectors"))


def remember(turn_id: str, raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Hold a turn's picks until its runner takes them."""
    picks = normalize(raw)
    now = time.time()
    with _lock:
        for key in [k for k, (at, _) in _pending.items() if now - at > _PENDING_TTL]:
            _pending.pop(key, None)
        while len(_pending) >= _PENDING_MAX:
            _pending.pop(next(iter(_pending)))
        _pending[str(turn_id)] = (now, picks)
    return picks


def take(turn_id: str) -> Dict[str, Any]:
    with _lock:
        held = _pending.pop(str(turn_id or ""), None)
    return held[1] if held else normalize(None)


# ---------------------------------------------------------------------------
# The one hook the TurnRunner calls
# ---------------------------------------------------------------------------

def apply(runner: Any, user_text: str) -> Dict[str, Any]:
    """Apply this turn's picks to the conversation. Returns ``{"full": bool}``.

    Runs every turn (Auto included) so the previous turn's notes never linger.
    Hand-picked agents are *not* run here; ``run_picked_agents`` does that just before the model loop,
    after the cache and the quick path have been decided.
    """
    service = runner.service
    picks = take(getattr(runner, "turn_id", ""))
    runner.picks = picks
    runner.picks_surface = picks["surface"]
    service.conversation_history = [
        m for m in service.conversation_history
        if not (m.get("role") == "system" and str(m.get("content", "")).startswith((SKILLS_PREFIX, TEAM_PREFIX)))
    ]
    full = False

    # Skills.
    choice = picks["skills"]
    if choice == OFF:
        service.conversation_history = [
            m for m in service.conversation_history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(AUTO_SKILLS_PREFIX))
        ]
        typed = [s for s in _typed_skills(runner)]
        runner.emit("skill.used", skills=typed)
        runner.skill_ids = [str(s.get("id")) for s in typed]
    elif isinstance(choice, list):
        found = skill_brief(choice)
        if found["context"]:
            service.conversation_history = [
                m for m in service.conversation_history
                if not (m.get("role") == "system" and str(m.get("content", "")).startswith(AUTO_SKILLS_PREFIX))
            ]
            insert_at = next((i for i, m in enumerate(service.conversation_history) if m.get("role") != "system"),
                             len(service.conversation_history))
            service.conversation_history.insert(insert_at, {"role": "system", "content": found["context"]})
            used = found["skills"] + [s for s in _typed_skills(runner) if s.get("id") not in {x["id"] for x in found["skills"]}]
            runner.emit("skill.used", skills=used)
            runner.skill_ids = [str(s.get("id")) for s in used]
            runner.emit("status", phase="route", text="Using " + ", ".join(s["name"] for s in found["skills"]))
            full = True

    # Agents: Auto is agent_match's (it reads agent_choice); a hand pick runs later in run_picked_agents.
    agents = picks["agents"]
    runner.agent_choice = agents if isinstance(agents, list) else agents
    if isinstance(agents, list):
        runner.picks_fresh = True  # the owner asked for these agents' work, never for a remembered reply
        full = True

    # Connectors (and "&name" mentions): connector_use decides and writes its own note.
    try:
        import connector_use

        plan = connector_use.plan_turn(user_text, picks["connectors"], surface=picks["surface"])
        service.conversation_history = [
            m for m in service.conversation_history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(connector_use.NOTE_PREFIX))
        ]
        if plan.get("note"):
            service.conversation_history.append({"role": "system", "content": plan["note"]})
        if plan.get("ids") or plan.get("missing"):
            runner.emit("connectors.used", connectors=plan.get("used", []), missing=plan.get("missing", []),
                        how=plan.get("how", "auto"))
        runner.connector_ids = list(plan.get("ids") or [])
        if plan.get("ids"):
            full = True
        if plan.get("explicit"):
            runner.picks_fresh = True
    except Exception:  # pragma: no cover - connectors never block a turn
        _LOG.debug("connector plan failed", exc_info=True)
    return {"full": full}


def _typed_skills(runner: Any) -> List[Dict[str, Any]]:
    """Skills the owner called with /name in the message: those are picks too, and stay."""
    ids = set(getattr(runner, "skill_ids", []) or [])
    try:
        from skills import SKILL_STORE
    except Exception:  # pragma: no cover
        return []
    out = []
    for skill_id in ids:
        skill = SKILL_STORE.get(skill_id)
        if skill is not None and _called_in_text(runner, skill):
            out.append({"id": skill.skill_id, "name": skill.name, "source": skill.source, "why": "typed"})
    return out


def _called_in_text(runner: Any, skill: Any) -> bool:
    text = str(getattr(runner, "user_text", "") or "").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", str(skill.name).lower()).strip("-")
    return f"/{slug}" in text or f"/{str(skill.skill_id).lower()}" in text


def skill_brief(picked: List[str]) -> Dict[str, Any]:
    """The picked skills in full, read before anything else. Unknown ids are skipped."""
    try:
        from skills import SKILL_STORE
    except Exception:  # pragma: no cover
        return {"skills": [], "context": ""}
    found = []
    for key in picked:
        skill = SKILL_STORE.get(key)
        if skill is None:
            wanted = key.strip().lower()
            skill = next((s for s in _all_skills() if s.name.lower() == wanted), None)
        if skill is not None and skill.skill_id not in {s.skill_id for s in found}:
            found.append(skill)
    if not found:
        return {"skills": [], "context": ""}
    lines = [SKILLS_PREFIX, "The owner picked these skills for this message in the chat bar. Read them first and follow "
             "each one wherever it applies:"]
    for skill in found:
        lines.append(f"\n{skill.name}: {skill.instructions}")
    return {"skills": [{"id": s.skill_id, "name": s.name, "source": s.source, "why": "picked"} for s in found],
            "context": "\n".join(lines)}


def _all_skills() -> List[Any]:
    try:
        from skills import SKILL_STORE

        return [SKILL_STORE.get(item["id"]) for item in SKILL_STORE.list_skills() if item.get("id")] or []
    except Exception:  # pragma: no cover
        return []


# ---------------------------------------------------------------------------
# Hand-picked agents
# ---------------------------------------------------------------------------

def roster() -> Dict[str, Dict[str, Any]]:
    """Every agent a turn can pick, by lower-case name (the Manager included; it is the one answering)."""
    try:
        import agent_runtime

        return {str(a["name"]).lower(): a for a in agent_runtime.load_roster() if a.get("name")}
    except Exception:  # pragma: no cover
        return {}


def _describe(entry: Dict[str, Any]) -> str:
    bits = [str(entry.get("goal") or entry.get("purpose") or "").strip(), str(entry.get("expertise") or "").strip()]
    return "; ".join(b for b in bits if b)[:240] or "a specialist"


def run_picked_agents(runner: Any, user_text: str, *, specialist: Optional[Callable[..., str]] = None,
                      decode: Optional[Callable[[str, str], str]] = None) -> Dict[str, Any]:
    """Run the agents the owner picked, then leave their work for the Manager as one system note.

    ``specialist(name, task, context)`` and ``decode(prompt, system)`` are injectable for tests; the real ones are
    ``agent_runtime.run_specialist`` and the fast model role.
    """
    picked = getattr(runner, "agent_choice", AUTO)
    if not isinstance(picked, list) or not picked:
        return {"ran": []}
    picks = getattr(runner, "picks", None) or normalize(None)
    mode = picks.get("agent_mode", "interpret")
    known = roster()
    team, skipped = [], []
    for name in picked:
        entry = known.get(name.lower())
        if entry is None:
            skipped.append(name)
        elif entry.get("role") == "master":
            continue  # the Manager is already the one answering
        elif entry["name"] not in [t["name"] for t in team]:
            team.append(entry)
    if not team:
        if skipped:
            runner.emit("status", phase="agents", text="No agent called " + ", ".join(skipped))
        return {"ran": [], "skipped": skipped}

    run_one = specialist or _real_specialist
    names = [t["name"] for t in team]
    runner.emit("status", phase="agents", text=("Planning each agent's part" if mode == "interpret" and len(team) > 1
                                                else "Bringing in " + ", ".join(names)))
    if mode == "interpret":
        plan = interpret(user_text, team, decode=decode)
    else:
        plan = {"summary": "", "tasks": {t["name"]: user_text for t in team}, "decoded": False}
    runner.emit("agents.picked", mode=mode, agents=names, plan=plan.get("summary", ""), tasks=plan["tasks"],
                decoded=plan.get("decoded", False))

    active = [t for t in team if plan["tasks"].get(t["name"], "").strip()]
    first = _parallel(runner, active, lambda t: (plan["tasks"][t["name"]],
                                                 team_context(t, active, plan, mode, user_text)), run_one)
    rounds = [first]
    if mode == "normal" and len(active) > 1 and not runner.cancelled():
        runner.emit("status", phase="agents", text="The agents are reading each other's work")
        rounds.append(_parallel(runner, active, lambda t: (exchange_task(t, first, user_text),
                                                           team_context(t, active, plan, mode, user_text)), run_one))
    note = team_note(mode, plan, active, rounds, skipped)
    runner.service.conversation_history.append({"role": "system", "content": note})
    return {"ran": [t["name"] for t in active], "skipped": skipped, "mode": mode, "rounds": len(rounds)}


def _real_specialist(name: str, task: str, context: str) -> str:
    import agent_runtime

    return agent_runtime.run_specialist(name, task, context)


def _parallel(runner: Any, team: List[Dict[str, Any]], build: Callable[[Dict[str, Any]], tuple],
              run_one: Callable[..., str]) -> Dict[str, str]:
    """One report per agent, run side by side (bounded by the Power setting)."""
    if not team:
        return {}
    try:
        from resource_governor import GOVERNOR

        workers = max(1, min(len(team), GOVERNOR.ceiling().max_agents, 6))
    except Exception:  # pragma: no cover
        workers = min(len(team), 3)
    reports: Dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for entry in team:
            task, context = build(entry)
            futures[entry["name"]] = pool.submit(contextvars.copy_context().run, run_one, entry["name"], task, context)
        for name, future in futures.items():
            if runner.cancelled():
                reports[name] = "(stopped)"
                continue
            try:
                reports[name] = str(future.result(timeout=_AGENT_TIMEOUT) or "").strip() or "(no report)"
            except Exception as error:  # noqa: BLE001 - one agent's failure is reported, not fatal
                reports[name] = f"(failed: {type(error).__name__}: {str(error)[:160]})"
    return reports


def interpret(user_text: str, team: List[Dict[str, Any]], *, decode: Optional[Callable[[str, str], str]] = None) -> Dict[str, Any]:
    """The main agent reads the one message and writes each agent its own instruction.

    If no model answers or the reply can't be read, every agent gets the owner's words (normal mode's split), so
    picking agents never fails because the planner was busy.
    """
    names = [t["name"] for t in team]
    if len(team) == 1:
        return {"summary": "", "tasks": {names[0]: user_text}, "decoded": False}
    roster_text = "\n".join(f"- {t['name']}: {_describe(t)}" for t in team)
    system = ("detailed thinking off\nYou are the main agent of a team. You read the owner's message, decide which "
              "agent does which part, and write each agent its own instruction. The agents cannot see the owner's "
              "message, so each instruction must carry all the context that agent needs. Reply with JSON only.")
    prompt = (f"The owner's message:\n\"\"\"\n{user_text[:4000]}\n\"\"\"\n\nThe agents the owner picked:\n{roster_text}\n\n"
              "Write JSON: {\"plan\": \"one sentence on how the work is split\", \"tasks\": {\"<agent name>\": "
              "\"<that agent's own instruction>\"}}. Use the agent names exactly as written. Give an agent \"\" only "
              "when there is truly nothing in the message for it.")
    try:
        reply = (decode or _decode)(prompt, system)
        data = _json_object(reply)
    except Exception:  # noqa: BLE001 - a busy planner falls back to the same words for everyone
        data = {}
    raw_tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
    lowered = {str(k).strip().lower(): str(v or "").strip() for k, v in raw_tasks.items()}
    tasks = {name: lowered.get(name.lower(), "")[:3000] for name in names}
    if not any(tasks.values()):
        return {"summary": "", "tasks": {name: user_text for name in names}, "decoded": False}
    return {"summary": str(data.get("plan") or "")[:300], "tasks": tasks, "decoded": True}


def _decode(prompt: str, system: str) -> str:
    from model_roles import MODEL_ROLES

    return MODEL_ROLES.run("fast_chat", prompt, system=system, max_tokens=900).text


def _json_object(text: str) -> Dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        value = json.loads(text[start:end + 1])
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def team_context(entry: Dict[str, Any], team: List[Dict[str, Any]], plan: Dict[str, Any], mode: str, user_text: str) -> str:
    others = [t for t in team if t["name"] != entry["name"]]
    if mode == "interpret":
        lines = ["The main agent split the owner's request between several agents. Your part is the task above."]
        if plan.get("summary"):
            lines.append(f"The plan: {plan['summary']}")
        if others:
            lines.append("The others are working on:")
            lines += [f"- {t['name']}: {plan['tasks'].get(t['name'], '')[:300] or 'nothing this time'}" for t in others]
        lines.append(f"The owner's own words, for context: {user_text[:1500]}")
        return "\n".join(lines)
    if not others:
        return ""
    lines = ["You are one of several agents working on this same message at the same time, and you can talk to each "
             "other: after everyone's first draft you will see the others' work and can answer it. Bring what your "
             "expertise adds instead of repeating what the others will cover. Working with you:"]
    lines += [f"- {t['name']}: {_describe(t)}" for t in others]
    return "\n".join(lines)


def exchange_task(entry: Dict[str, Any], first: Dict[str, str], user_text: str) -> str:
    """The second round of normal mode: each agent reads the others' drafts and answers them once."""
    others = "\n\n".join(f"### {name}\n{report[:2500]}" for name, report in first.items() if name != entry["name"])
    return (f"The owner's message was:\n{user_text[:1500]}\n\nYour first draft:\n{first.get(entry['name'], '')[:2500]}\n\n"
            f"Your teammates' first drafts:\n{others}\n\nReply to your teammates: correct anything wrong, fill gaps only "
            "you can fill, answer questions they raised, and give your final contribution. If you have nothing to add, "
            "say \"Nothing to add.\" Keep it short.")


def team_note(mode: str, plan: Dict[str, Any], team: List[Dict[str, Any]], rounds: List[Dict[str, str]],
              skipped: List[str]) -> str:
    how = ("Auto interpret: the main agent gave each agent its own part" if mode == "interpret"
           else "Normal: every agent got the same words and could answer the others")
    lines = [TEAM_PREFIX, f"The owner picked these agents in the chat bar ({how}). Their work is below. Write the final "
             "answer from it: combine it, settle disagreements, keep what is right, and say which agent found what when "
             "that helps. Don't hand the same work to them again unless something is missing."]
    if plan.get("summary"):
        lines.append(f"Plan: {plan['summary']}")
    for entry in team:
        name = entry["name"]
        lines.append(f"\n## {name}")
        if mode == "interpret":
            lines.append(f"Task: {plan['tasks'].get(name, '')[:600]}")
        lines.append(rounds[0].get(name, "(no report)")[:6000])
        if len(rounds) > 1:
            reply = rounds[1].get(name, "")
            if reply and "nothing to add" not in reply.lower()[:40]:
                lines.append(f"After reading the others: {reply[:3000]}")
    if skipped:
        lines.append(f"\nNot on the team (tell the owner): {', '.join(skipped)}")
    return "\n".join(lines)
