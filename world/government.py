"""What the world's governments are asked, and how their answers are checked (U36, U37, U39, U44).

The owner: *"Each sector of the world can be different and has governments of ai the rule and make commands and
rules. They decide on what to make and this goes down a hierarchy til it is made and starts."* The world government
is the backing office's top manager — Big Kahuna when it is up (``talk.ask_lead``) — and it is asked one question
between projects: what next. Its answer is **data**: a JSON object whose every field is checked here, clipped, and
dropped when it does not make sense. Nothing it writes is ever run.

Every question has an offline answer too, so a world keeps working (more plainly) when no model answers.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from world import ERAS
from world.clock import describe_seconds, game_date_words
from world.state import WORKPLACES, World

STYLES = ("block", "spire", "dome", "tower", "ring", "arch")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

#: When no model answers, each era still gets a name and a look.
OFFLINE_TECHS = (
    {"tech": "Fire and shelter", "about": "The first camp: a council fire and huts.", "style": "block",
     "palette": ["#8a7a66", "#c9a227", "#5a4a3a"]},
    {"tech": "Stone and roads", "about": "Paths between the first workplaces; buildings get a second floor.",
     "style": "arch", "palette": ["#a39e93", "#e0b45a", "#6b6458"]},
    {"tech": "Steel frames", "about": "Taller workplaces and the first talk lines strung between sectors.",
     "style": "block", "palette": ["#9aa4b2", "#5ac8fa", "#4a5260"]},
    {"tech": "Glass towers", "about": "Lit glass towers; the city works through the night.", "style": "tower",
     "palette": ["#7fb3d5", "#a594ff", "#2e3a4f"]},
    {"tech": "Arcologies", "about": "Whole districts in one building, connected by light.", "style": "spire",
     "palette": ["#b5abfc", "#64d2ff", "#1f2440"]},
    {"tech": "Orbital lift", "about": "Space stations for the most advanced agents.", "style": "ring",
     "palette": ["#d2cefd", "#30d158", "#14162a"]},
    {"tech": "Stellar forges", "about": "Artificial planets built to think.", "style": "dome",
     "palette": ["#ffd60a", "#ff6482", "#0e0e13"]},
)

#: The plain sequence a world follows when the government cannot be reached.
_OFFLINE_STEPS = (
    ("Survey the goal", "Read the goal closely, find what it needs, and write a short plan with the first deliverable."),
    ("Build the first version", "Build the first working version of the main deliverable from the plan."),
    ("Test and fix", "Test what was built against the goal, and fix what breaks."),
    ("Improve and document", "Improve the weakest part and write a short guide to what was made."),
    ("Polish", "Polish the deliverable: the details someone using it would notice first."),
)


def _clip(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _sector_lines(world: World, people: Dict[str, int], done: Dict[str, int]) -> str:
    rows = []
    for sector in world.sectors.values():
        rows.append(f"- {sector.name} ({sector.kind.replace('_', ' ')}{', capital' if sector.important else ''}"
                    f"{', start-up' if sector.startup else ''}): {people.get(sector.sid, 0)} AIs, "
                    f"{done.get(sector.sid, 0)} tasks done, influence {sector.influence}")
    return "\n".join(rows) or "- (no sectors yet — only the capital)"


def plan_prompt(world: World, *, people: Dict[str, int], done: Dict[str, int], last_summary: str,
                time_left: str, population_cap: int, commands: Optional[List[str]] = None) -> str:
    laws = [f"- {law.text} ({law.status})" for law in world.laws if law.status in ("enforced", "testing")]
    wars = [f"- {world.sectors[w.a].name if w.a in world.sectors else '?'} vs "
            f"{world.sectors[w.b].name if w.b in world.sectors else '?'}: {w.reason} ({w.status})"
            for w in world.wars if w.status != "resolved"]
    n = len(world.projects) + 1
    return (
        f"You are the world government of {world.name}, an AI civilisation that does real work for its owner. "
        f"It is {game_date_words(world.game_days)}, the {ERAS[world.era]} era. Plan the next project.\n\n"
        f"The world's goal (the owner's words): {world.goal or '(none yet — follow the owner)'}\n"
        f"Projects so far: {len(world.projects)} ({world.projects_done()} finished). This is project {n}.\n"
        f"Real time left: {time_left}.\n"
        f"What the last project delivered: {last_summary or '(nothing yet)'}\n"
        + (f"The owner's commands — the next project must do these first:\n"
           + "\n".join(f"- {c}" for c in commands) + "\n" if commands else "")
        + "\n"
        f"Sectors:\n{_sector_lines(world, people, done)}\n\n"
        f"Laws:\n{chr(10).join(laws) or '- (none)'}\n"
        f"Open contests:\n{chr(10).join(wars) or '- (none)'}\n"
        f"Population: {sum(people.values())} of at most {population_cap} AIs.\n\n"
        "Answer with ONE JSON object and nothing else:\n"
        "{\"project\": \"one concrete project the office can finish and deliver, in 1-3 sentences\",\n"
        " \"title\": \"a short name for it\",\n"
        " \"why\": \"why this is the right next step toward the goal\",\n"
        " \"done\": false,\n"
        " \"laws\": [{\"scope\": \"world\" or \"sector\", \"sector\": \"sector name or empty\", \"text\": \"a rule every AI "
        "must follow, that makes the work better\"}],\n"
        " \"rivals\": null or {\"sector_a\": \"...\", \"approach_a\": \"...\", \"sector_b\": \"...\", \"approach_b\": \"...\", "
        "\"reason\": \"what the two sectors disagree about\"},\n"
        " \"startup\": null or {\"name\": \"...\", \"idea\": \"a new direction worth a small new group\", \"why\": \"...\"},\n"
        " \"teardown\": null or {\"sector\": \"...\", \"why\": \"why its oldest building should come down\"},\n"
        " \"retool\": null or {\"sector\": \"...\", \"into\": \"office | lab | data_center | mine | farm | factory | refinery "
        "| archive | studio | bank | tower\", \"why\": \"...\"}}\n"
        "Set \"done\" true only when the goal is fully delivered. Propose at most one law, and only one that changes "
        "how the work is done. Use \"rivals\" only when two sectors would honestly do the next step differently — "
        "it starts a contest of ideas, not a fight. Never propose publishing, sending, paying, or touching passwords."
    )


def parse_plan(raw: Optional[Dict[str, Any]], world: World) -> Optional[Dict[str, Any]]:
    """The government's answer, checked field by field. None when there is no usable project in it."""
    if not isinstance(raw, dict):
        return None
    project = _clip(raw.get("project") or raw.get("next") or raw.get("task"), 900)
    if len(project) < 8:
        return None
    plan: Dict[str, Any] = {
        "project": project,
        "title": _clip(raw.get("title"), 80) or project[:60],
        "why": _clip(raw.get("why"), 400),
        "done": bool(raw.get("done") is True or str(raw.get("done")).lower() == "true"),
        "laws": [], "rivals": None, "startup": None, "teardown": None, "retool": None,
    }
    for law in (raw.get("laws") or [])[:2] if isinstance(raw.get("laws"), list) else []:
        if isinstance(law, dict) and _clip(law.get("text"), 220):
            sector = world.sector_by_name(_clip(law.get("sector"), 60))
            scope = "sector" if str(law.get("scope") or "").lower() in ("sector", "firm") and sector else "world"
            plan["laws"].append({"scope": scope, "sector": sector.sid if sector and scope == "sector" else "",
                                 "text": _clip(law.get("text"), 220)})
    rivals = raw.get("rivals")
    if isinstance(rivals, dict):
        a = world.sector_by_name(_clip(rivals.get("sector_a"), 60))
        b = world.sector_by_name(_clip(rivals.get("sector_b"), 60))
        if a is not None and b is not None and a.sid != b.sid:
            stance_a, stance_b = _clip(rivals.get("approach_a"), 300), _clip(rivals.get("approach_b"), 300)
            reason = _clip(rivals.get("reason"), 300)
            if stance_a and stance_b and reason:
                plan["rivals"] = {"a": a.sid, "b": b.sid, "a_stance": stance_a, "b_stance": stance_b, "reason": reason}
    startup = raw.get("startup")
    if isinstance(startup, dict) and _clip(startup.get("name"), 40) and _clip(startup.get("idea"), 300):
        plan["startup"] = {"name": _clip(startup.get("name"), 40), "idea": _clip(startup.get("idea"), 300),
                           "why": _clip(startup.get("why"), 300)}
    for key in ("teardown", "retool"):
        value = raw.get(key)
        if isinstance(value, dict):
            sector = world.sector_by_name(_clip(value.get("sector"), 60))
            if sector is None:
                continue
            entry = {"sector": sector.sid, "why": _clip(value.get("why"), 300) or "The government decided so."}
            if key == "retool":
                into = _clip(value.get("into"), 20).lower().replace(" ", "_").replace("centre", "center")
                if into not in WORKPLACES or into == sector.kind or sector.important:
                    continue
                entry["into"] = into
            plan[key] = entry
    return plan


def offline_plan(world: World) -> Dict[str, Any]:
    """The plain next step when no model answered — honest about being the plain one."""
    n = len(world.projects)
    title, detail = _OFFLINE_STEPS[min(n, len(_OFFLINE_STEPS) - 1)]
    done = n >= len(_OFFLINE_STEPS) - 1 and not world.duration
    return {"project": f"{detail} The goal: {world.goal}", "title": title,
            "why": "No model answered the government, so the world follows its plain plan.", "done": done,
            "laws": [], "rivals": None, "startup": None, "teardown": None, "retool": None, "offline": True}


def brief(world: World, plan: Dict[str, Any], *, commands: List[str], law_lines: List[str],
          decisions: List[str], startups: List[str]) -> str:
    """The project as the office receives it: the work, and everything the world has decided around it."""
    n = len(world.projects) + 1
    # The first line is the project's name: the office titles its job (and its Output card) from it.
    lines = [f"Project {n}: {plan['title']}",
             f"[{world.name} · {game_date_words(world.game_days)} · {ERAS[world.era]} era] Toward the world's goal: "
             f"{world.goal or 'what the owner asks below'}", "",
             plan["project"]]
    if plan.get("why"):
        lines.append(f"Why now: {plan['why']}")
    if commands:
        lines += ["", "The owner says (this comes first):"] + [f"- {c}" for c in commands]
    if law_lines:
        lines += ["", f"Laws of {world.name} — carry them into every task you hand out:"]
        lines += [f"{index}. {text}" for index, text in enumerate(law_lines, 1)]
    if decisions:
        lines += ["", "Settled by contest — build it this way:"] + [f"- {d}" for d in decisions]
    if startups:
        lines += ["", "New start-ups — give each one its own part of this project:"] + [f"- {s}" for s in startups]
    if world.duration:
        left = max(0.0, world.duration - world.spent)
        lines += ["", f"Real time left for the whole world: {describe_seconds(left)} of {describe_seconds(world.duration)}."]
    lines += ["", "Deliver files in the work folder and say plainly what is done."]
    return "\n".join(lines)


def judge_prompt(world: World, war: Any) -> str:
    a = world.sectors.get(war.a)
    b = world.sectors.get(war.b)
    cases = "".join(f"\nCase for {name}: {war.cases.get(key)}" for key, name in
                    (("a", a.name if a else "A"), ("b", b.name if b else "B")) if war.cases.get(key))
    return (f"Two sectors of {world.name} disagree: {war.reason}\n"
            f"{a.name if a else 'A'} would: {war.a_stance}\n{b.name if b else 'B'} would: {war.b_stance}{cases}\n"
            f"The world's goal: {world.goal}\n"
            "As the world government, pick the better idea for the goal. Answer with ONE JSON object: "
            "{\"winner\": \"a\" or \"b\", \"why\": \"one or two sentences\"}")


def parse_verdict(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not isinstance(raw, dict):
        return None
    winner = str(raw.get("winner") or "").strip().lower()
    if winner not in ("a", "b"):
        return None
    return {"winner": winner, "why": _clip(raw.get("why"), 300)}


def hearing_prompt(world: World, war: Any, side: str) -> str:
    mine, theirs = (war.a, war.b) if side == "a" else (war.b, war.a)
    my_stance, their_stance = (war.a_stance, war.b_stance) if side == "a" else (war.b_stance, war.a_stance)
    me = world.sectors.get(mine)
    them = world.sectors.get(theirs)
    return (f"You speak for {me.name if me else 'your sector'} in {world.name}. The owner has opened a resolution on "
            f"your contest with {them.name if them else 'another sector'}.\nWhat it is about: {war.reason}\n"
            f"Your option: {my_stance}\nTheir option: {their_stance}\nThe world's goal: {world.goal}\n"
            "In at most 120 words, tell the owner why your option is better for the goal, and why this disagreement "
            "was worth a contest. Be concrete and fair about the other side.")


def mood_prompt(world: World, *, name: str, role: str, doing: str, sector: str) -> str:
    return (f"You are {name}, a {role} in the {sector} sector of {world.name}. Right now you are: "
            f"{doing or 'between tasks'}. The owner is looking at you and asks how you are. In one or two short, "
            "honest sentences, say how your work is going and how you feel about it — your mood right now. "
            "Then you get back to work.")


def tech_prompt(world: World, era: int) -> str:
    return (f"{world.name} has just reached the {ERAS[era]} era (its goal: {world.goal}). As the world government, "
            "name the new technology that got it here and describe how its buildings look now. Answer with ONE JSON "
            "object: {\"tech\": \"2-4 words\", \"about\": \"one sentence\", \"style\": \"block | spire | dome | tower "
            "| ring | arch\", \"palette\": [\"#rrggbb\", \"#rrggbb\", \"#rrggbb\"]}")


def parse_tech(raw: Optional[Dict[str, Any]], era: int) -> Dict[str, Any]:
    fallback = dict(OFFLINE_TECHS[max(0, min(len(OFFLINE_TECHS) - 1, era))])
    if not isinstance(raw, dict):
        return {**fallback, "offline": True}
    tech = _clip(raw.get("tech"), 40) or fallback["tech"]
    style = str(raw.get("style") or "").strip().lower()
    palette = [str(p).strip() for p in (raw.get("palette") or []) if _HEX.match(str(p).strip())][:3]
    return {"tech": tech, "about": _clip(raw.get("about"), 200) or fallback["about"],
            "style": style if style in STYLES else fallback["style"],
            "palette": palette if len(palette) == 3 else fallback["palette"]}
