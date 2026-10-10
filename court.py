"""Court — agents argue the owner's question before judges (owner, 2026-10-10; UPDATE_IDEAS U51/U52).

The owner: "a skill called court and when active it makes a diagram of a court in the chat and we can see how bots
behave and fight on the question or questions I asked … make sure it works in world/office."

One engine for all three places. A *case* holds the question(s), two or three *sides* (each a counsel with a stance),
three *judges* (several, for fairness — U52), and a transcript. It runs in a thread, one model call at a time:

    framing (1 call) → openings → rebuttals → closings (one per side each) → judges vote (one each) → verdict

so a case costs at most 1 + 3·sides + judges calls (13 for two sides) — the budget cap U52 asked for. Every step
publishes ``court.update`` with the whole case, which the chat's court window draws as a courtroom. The owner can
stop a case, or pick the winner themselves at any time (U51: "the owner can click a side to win"). Office and World
open cases through the same ``start()`` with ``origin`` set, so their arguments land in the same court.

Nothing here executes anything a model wrote; it only stores and shows text.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from paths import atomic_replace, data_path

MAX_CASES = 30
MAX_SIDES = 3
JUDGES = ("Judge Vega", "Judge Okafor", "Judge Lindqvist")
ROUNDS = ("opening", "rebuttal", "closing")
WORDS = {"opening": 110, "rebuttal": 90, "closing": 60}

_lock = threading.Lock()
_cases: Dict[str, Dict[str, Any]] = {}
_loaded = False
_stops: Dict[str, threading.Event] = {}

#: Swappable for tests: (messages, max_tokens) -> text.
Ask = Callable[[List[Dict[str, str]], int], str]


def _path():
    return data_path("court_cases.json")


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
        for case in raw.get("cases", []):
            if case.get("status") in ("framing", "arguing", "deliberating"):
                case["status"] = "stopped"          # a restart ended it; say so instead of pretending it runs
                case["note"] = "Stopped when the engine restarted."
            _cases[case["id"]] = case
    except (OSError, ValueError):
        pass


def _save() -> None:
    cases = sorted(_cases.values(), key=lambda c: c.get("created", 0))[-MAX_CASES:]
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=1), encoding="utf-8")
    atomic_replace(tmp, path)


def _publish(case: Dict[str, Any]) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("court.update", case=case)
    except Exception:  # noqa: BLE001 - the court must run with no listeners
        pass


def _default_ask(messages: List[Dict[str, str]], max_tokens: int) -> str:
    from agent_runtime import _router

    reply, _provider = _router().chat(messages)
    return str(reply or "").strip()


def _clean_questions(questions: Any) -> List[str]:
    if isinstance(questions, str):
        parts = [q.strip() for q in re.split(r"\n+|(?<=\?)\s+", questions) if q.strip()]
    else:
        parts = [str(q).strip() for q in (questions or []) if str(q).strip()]
    return [p[:400] for p in parts][:4]


def _parse_sides(text: str, questions: List[str]) -> List[Dict[str, str]]:
    match = re.search(r"\{.*\}", text, re.S)
    sides: List[Dict[str, str]] = []
    if match:
        try:
            data = json.loads(match.group(0))
            for item in data.get("sides", [])[:MAX_SIDES]:
                name = str(item.get("name", "")).strip()[:40]
                stance = str(item.get("stance", "")).strip()[:300]
                if name and stance:
                    sides.append({"name": name, "stance": stance})
        except ValueError:
            pass
    if len(sides) < 2:
        q = questions[0] if questions else "the question"
        sides = [{"name": "For", "stance": f"Yes — argue in favour: {q}"},
                 {"name": "Against", "stance": f"No — argue against: {q}"}]
    for i, side in enumerate(sides):
        side["id"] = f"s{i + 1}"
        side["counsel"] = f"Counsel {side['name']}"
    return sides


def _brief(case: Dict[str, Any]) -> str:
    lines = [f"[{t['round']}] {t['speaker']}: {t['text']}" for t in case["transcript"] if t["role"] == "counsel"]
    return "\n".join(lines)[-6000:]


def _vote(text: str, sides: List[Dict[str, str]]) -> Dict[str, str]:
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            data = json.loads(match.group(0))
            pick = str(data.get("side", "")).strip().lower()
            for side in sides:
                if pick in (side["id"].lower(), side["name"].lower()):
                    return {"side": side["id"], "reason": str(data.get("reason", ""))[:400]}
        except ValueError:
            pass
    low = text.lower()
    for side in sides:
        if side["name"].lower() in low[:200]:
            return {"side": side["id"], "reason": text[:400]}
    return {"side": "", "reason": text[:400] or "No clear vote."}


def _snapshot(case: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(case))


def _step(case: Dict[str, Any], **changes: Any) -> None:
    with _lock:
        case.update(changes)
        case["updated"] = time.time()
        _save()
        snap = _snapshot(case)
    _publish(snap)


def _say(case: Dict[str, Any], speaker: str, role: str, round_: str, text: str, side: str = "") -> None:
    with _lock:
        case["transcript"].append({"speaker": speaker, "role": role, "round": round_, "side": side,
                                   "text": text.strip()[:1600], "at": time.time()})
        case["speaking"] = speaker
        case["updated"] = time.time()
        _save()
        snap = _snapshot(case)
    _publish(snap)


def _run(case_id: str, ask: Ask) -> None:
    case = _cases[case_id]
    stop = _stops[case_id]
    questions = case["questions"]
    qtext = "\n".join(f"- {q}" for q in questions)
    try:
        framing = ask([{"role": "user", "content": (
            "You are the clerk of a court that tests ideas by argument. Questions before the court:\n"
            f"{qtext}\n\nPropose the 2 or 3 strongest distinct positions someone could defend. Reply with JSON only: "
            '{"sides": [{"name": "<one or two words>", "stance": "<the position, one sentence>"}]}')}], 300)
        sides = _parse_sides(framing, questions)
        _step(case, sides=sides, status="arguing")
        for round_ in ROUNDS:
            for side in sides:
                if stop.is_set():
                    _step(case, status="stopped", speaking="")
                    return
                others = "; ".join(f"{s['name']}: {s['stance']}" for s in sides if s is not side)
                text = ask([{"role": "user", "content": (
                    f"You are {side['counsel']} in a court that tests ideas. Questions:\n{qtext}\n\n"
                    f"Your position: {side['stance']}\nOther positions: {others}\n\n"
                    f"Arguments so far:\n{_brief(case) or '(none yet)'}\n\n"
                    f"Give your {round_} in at most {WORDS[round_]} words. Use evidence and reasoning, answer the other "
                    "side's strongest point, no insults, no headings.")}], 400)
                _say(case, side["counsel"], "counsel", round_, text or "(no answer)", side["id"])
        _step(case, status="deliberating", speaking="")
        votes = []
        for judge in case["judges"]:
            if stop.is_set():
                _step(case, status="stopped", speaking="")
                return
            names = ", ".join(f"{s['id']} = {s['name']}" for s in sides)
            text = ask([{"role": "user", "content": (
                f"You are {judge}, an impartial judge. Questions:\n{qtext}\n\nThe arguments:\n{_brief(case)}\n\n"
                f"Decide which side argued best on evidence and reasoning (sides: {names}). Reply with JSON only: "
                '{"side": "<side id>", "reason": "<two sentences>"}')}], 250)
            vote = _vote(text, sides)
            votes.append({"judge": judge, **vote})
            name = next((s["name"] for s in sides if s["id"] == vote["side"]), "no side")
            _say(case, judge, "judge", "verdict", f"For {name}. {vote['reason']}", vote["side"])
        tally: Dict[str, int] = {}
        for v in votes:
            if v["side"]:
                tally[v["side"]] = tally.get(v["side"], 0) + 1
        best = max(tally.values()) if tally else 0
        winners = [s for s, n in tally.items() if n == best]
        winner = winners[0] if len(winners) == 1 else ""
        _step(case, status="verdict", speaking="", verdict={"winner": winner, "votes": votes, "tally": tally,
                                                           "split": not winner})
    except Exception as error:  # noqa: BLE001 - a failed call ends the case with a reason, never a crash
        _step(case, status="failed", speaking="", note=f"Stopped: {type(error).__name__}: {error}"[:300])
    finally:
        _stops.pop(case_id, None)


def start(questions: Any, *, origin: str = "chat", origin_id: str = "", ask: Optional[Ask] = None,
          background: bool = True) -> Dict[str, Any]:
    """Open a case and start arguing it. ``origin`` is chat, office or world."""
    cleaned = _clean_questions(questions)
    if not cleaned:
        raise ValueError("Give the court a question.")
    with _lock:
        _load()
        case = {"id": uuid.uuid4().hex[:10], "questions": cleaned, "origin": origin, "origin_id": origin_id,
                "status": "framing", "sides": [], "judges": list(JUDGES), "transcript": [], "speaking": "Clerk",
                "verdict": None, "owner_pick": "", "created": time.time(), "updated": time.time(), "note": ""}
        _cases[case["id"]] = case
        _save()
        _stops[case["id"]] = threading.Event()
        snap = _snapshot(case)
    _publish(snap)
    runner = ask or _default_ask
    if background:
        threading.Thread(target=_run, args=(case["id"], runner), name=f"court-{case['id']}", daemon=True).start()
    else:
        _run(case["id"], runner)
    return _snapshot(_cases[case["id"]])


def get(case_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        _load()
        case = _cases.get(case_id)
        return _snapshot(case) if case else None


def list_cases(origin: str = "") -> List[Dict[str, Any]]:
    with _lock:
        _load()
        cases = [c for c in _cases.values() if not origin or c.get("origin") == origin]
        return [{"id": c["id"], "questions": c["questions"], "status": c["status"], "origin": c.get("origin", ""),
                 "created": c["created"], "winner": (c.get("verdict") or {}).get("winner", ""),
                 "owner_pick": c.get("owner_pick", "")} for c in sorted(cases, key=lambda c: -c["created"])]


def stop(case_id: str) -> bool:
    event = _stops.get(case_id)
    if event is None:
        return False
    event.set()
    return True


def pick(case_id: str, side_id: str) -> Dict[str, Any]:
    """The owner decides (U51): their pick stands over the judges and ends the case."""
    with _lock:
        _load()
        case = _cases.get(case_id)
        if case is None:
            raise KeyError(case_id)
        if side_id and side_id not in {s["id"] for s in case.get("sides", [])}:
            raise ValueError("No such side.")
        case["owner_pick"] = side_id
    stop(case_id)
    _step(case, status=case["status"] if case["status"] == "verdict" else "decided", speaking="")
    return _snapshot(case)


# --- tools (chat, office, world) ------------------------------------------------------------------------------


def tool_court_case(question: str, origin: str = "chat") -> str:
    """Put a question (or several, one per line) before the court and open the court window beside the chat."""
    try:
        case = start(question, origin=origin if origin in ("chat", "office", "world") else "chat")
    except ValueError as error:
        return f"Error: {error}"
    try:
        from agent_events import publish_ui

        publish_ui("ui.open_window", kind="court", title="Court", props={"caseId": case["id"]})
    except Exception:  # noqa: BLE001
        pass
    return (f"Opened court case {case['id']} on {len(case['questions'])} question(s). Counsel argue in three rounds and "
            "three judges vote; the owner watches it in the Court window and can pick a winner. Do not repeat the "
            "arguments in chat — say the court is in session and that the verdict will appear there.")


def tool_open_window(kind: str, title: str = "") -> str:
    """Open a window beside the chat: game, brain, screen, computer, office, world."""
    kinds = ("game", "brain", "screen", "computer", "office", "world", "email", "whatsapp", "graph", "file")
    wanted = (kind or "").strip().lower()
    aliases = {"game studio": "game", "games": "game", "second brain": "brain", "memory": "brain",
               "screen share": "screen", "share screen": "screen", "office space": "office", "mail": "email",
               "inbox": "email", "texts": "whatsapp", "messages": "whatsapp", "plot": "graph", "chart": "graph"}
    wanted = aliases.get(wanted, wanted)
    if wanted not in kinds:
        return f"Error: no window called {kind!r}. Choose one of: {', '.join(kinds)}."
    try:
        from agent_events import publish_ui

        publish_ui("ui.open_window", kind=wanted, title=title)
    except Exception as error:  # noqa: BLE001
        return f"Error: could not open it: {error}"
    return f"Opened the {wanted} window beside the chat."


def register_court_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="court_case",
        description="Put a question before the court: agents take sides and argue it in rounds, three judges vote, and "
                    "the owner watches a courtroom diagram beside the chat. Use when the owner says 'court', 'put it on "
                    "trial', 'let the bots argue/fight it out', or the court skill is active. Several questions: one per line.",
        parameters=[ToolParam("question", "string", "The question(s) to argue, one per line"),
                    ToolParam("origin", "string", "chat, office or world", required=False,
                              enum_values=["chat", "office", "world"])],
        handler=tool_court_case, category="general", label="Opening a court case",
    )
    registry.register(
        name="ui_open_window",
        description="Open a window beside the chat: 'game' (Game Studio — make or play a game), 'brain' (the Second "
                    "Brain memory field), 'screen' (share a screen), 'computer' (Ichos's own computer), 'office' or "
                    "'world' (offices of agents and their worlds), 'email' (the inbox), 'whatsapp' (texts), 'graph' (an "
                    "empty plotter — use plot_function for a specific function). Use when the owner asks to make a "
                    "game, see the brain, share their screen, open mail or texts, or create/open an office or world.",
        parameters=[ToolParam("kind", "string", "game, brain, screen, computer, office, world, email, whatsapp or graph",
                              enum_values=["game", "brain", "screen", "computer", "office", "world", "email", "whatsapp", "graph"]),
                    ToolParam("title", "string", "Optional window title", required=False)],
        handler=tool_open_window, category="ui", label=lambda a: f"Opening {a.get('kind', '')}",
    )
