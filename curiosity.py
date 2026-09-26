"""The third mind: what Nyx wonders about, what it wants, and what it got wrong.

The owner (2026-09-22): "Search and add a third mind or curiousity machine. An
improvment on the free will device tab but in a new way to the AI. This includes
curiosity, how it wants to learn, and adds feelings and understanding. And owns
up to mistakes while having curiosity to learn more. This shouldn't fully affect
chats, but it keeps questions and new ideas and files them. This is an extension
of free will and will have a tab in the free will tab that shows its growth,
understanding, and wants in its lifetime."

So this is a filing cabinet with a pulse, not a second personality:

* **Questions.** Things that came up and were not answered: a word nobody
  explained, a search that found nothing, a "no idea" of its own. Each is scored
  for how interesting it is — how often it has come back, how little is known
  about it, and how close it is to what the owner actually does.
* **Wants.** Longer wishes ("be able to read scanned PDFs"). Filed, never acted
  on; acting on them is the Apply tab's job, with the owner pressing the button.
* **Mistakes, owned.** A thumbs-down, a tool that failed, a correction: what
  happened, what it got wrong, what it takes from it. In its own words, kept.
* **Feelings.** Not a claim to have any. Four numbers computed from the week —
  curiosity, confidence, unease, satisfaction — with one honest sentence, so the
  owner can see what state it is answering from instead of guessing.
* **Growth.** Concepts known, questions answered, lessons kept, over its lifetime.

Studying a question is deliberately small: a web look-up, a short written answer
kept in the super brain, and the question closed. It runs on its own only while
Free Will is allowed and not paused, and never inside a chat turn — the owner
asked that it not take the conversation over.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from paths import data_path

#: Questions kept at once. The least interesting fall off the end.
MAX_QUESTIONS = 300
MAX_MISTAKES = 120
MAX_WANTS = 60
#: A study run may take about this long, and this many a day happen by themselves.
STUDY_BUDGET_SECONDS = 90
STUDY_PER_DAY = 12

_lock = threading.Lock()

DEFAULTS: Dict[str, Any] = {
    #: File questions as they come up (this alone changes nothing in chats).
    "notice": True,
    #: Look things up on its own when nothing else is happening.
    "study_alone": False,
    #: How many self-started studies a day.
    "per_day": 6,
}


@dataclass
class Question:
    id: str
    text: str
    why: str = ""
    topic: str = ""
    source: str = "chat"
    status: str = "open"          # open | answered | dropped
    asked: int = 1                # how many times it has come back
    interest: float = 0.5
    answer: str = ""
    learned: str = ""
    created_at: float = field(default_factory=time.time)
    answered_at: float = 0.0


@dataclass
class Mistake:
    id: str
    what_happened: str
    got_wrong: str = ""
    learned: str = ""
    kind: str = "feedback"        # feedback | tool | correction
    at: float = field(default_factory=time.time)


@dataclass
class Want:
    id: str
    text: str
    why: str = ""
    at: float = field(default_factory=time.time)


def _path():
    return data_path("curiosity/state.json")


def _blank() -> Dict[str, Any]:
    return {"settings": dict(DEFAULTS), "questions": [], "mistakes": [], "wants": [],
            "studied_today": 0, "studied_day": "", "history": []}


def _load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _blank()
        base = _blank()
        base.update({k: v for k, v in data.items() if k in base})
        base["settings"] = {**DEFAULTS, **(data.get("settings") or {})}
        return base
    except (OSError, ValueError):
        return _blank()


def _save(state: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    except OSError:
        pass


def settings() -> Dict[str, Any]:
    return dict(_load()["settings"])


def update_settings(**changes: Any) -> Dict[str, Any]:
    with _lock:
        state = _load()
        for key, value in changes.items():
            if key in DEFAULTS and value is not None:
                state["settings"][key] = value
        _save(state)
        return dict(state["settings"])


# ---------------------------------------------------------------------------
# Noticing
# ---------------------------------------------------------------------------

#: The shapes of not knowing, in Nyx's own answers.
_UNSURE = [
    re.compile(r"\bI (?:do not|don't) (?:know|have) (?:enough )?(?:about |what |how |why )?([^.!?\n]{6,90})", re.I),
    re.compile(r"\bI (?:am|'m) not sure (?:what|how|why|whether) ([^.!?\n]{6,90})", re.I),
    re.compile(r"\bI (?:could not|couldn't) find ([^.!?\n]{6,90})", re.I),
    re.compile(r"\bno results? for ([^.!?\n]{4,80})", re.I),
]
#: A question the owner asked that went unanswered is the most interesting kind.
_QUESTION = re.compile(r"([A-Z][^.!?\n]{8,120}\?)")

_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "was", "it",
         "this", "that", "you", "i", "me", "my", "your", "we", "they", "how", "what", "why", "when", "do",
         "does", "can", "could", "should", "would", "about", "from", "into", "there", "their", "them"}


def _topic_of(text: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z][\w'-]{2,}", (text or "").lower()) if w not in _STOP]
    return " ".join(words[:3])


def notice(text: str, *, source: str = "chat", why: str = "") -> List[Dict[str, Any]]:
    """File anything in `text` that Nyx did not know. Returns the new questions."""
    if not settings()["notice"] or not (text or "").strip():
        return []
    found: List[str] = []
    for pattern in _UNSURE:
        for match in pattern.findall(text):
            # One sentence can carry two admissions ("I don't know X, and I couldn't
            # find Y"); keep the first clause so each question is its own thing.
            piece = re.split(r"\s*(?:,| and | but | so | because )\s*", str(match).strip(" ,.;:"))[0]
            piece = re.sub(r"\s+(is|are|was|were)$", "", piece).strip(" ,.;:")
            if len(piece) > 5:
                found.append(piece if piece.endswith("?") else f"What is {piece}?")
    if source != "chat":
        for match in _QUESTION.findall(text):
            found.append(match.strip())
    if not found:
        return []
    return [asdict(q) for q in _add_questions(found[:3], source=source, why=why)]


def ask(question: str, *, why: str = "", source: str = "owner") -> Dict[str, Any]:
    """The owner (or Nyx itself) files a question deliberately."""
    # A question the owner filed outranks anything Nyx noticed by itself.
    added = _add_questions([question], source=source, why=why, interest=1.0 if source == "owner" else 0.9)
    return asdict(added[0]) if added else {}


def _add_questions(texts: List[str], *, source: str, why: str = "", interest: float = 0.0) -> List[Question]:
    made: List[Question] = []
    with _lock:
        state = _load()
        rows = state["questions"]
        by_text = {_normalise(row["text"]): row for row in rows}
        for text in texts:
            clean = re.sub(r"\s+", " ", (text or "").strip())[:220]
            if len(clean) < 8:
                continue
            key = _normalise(clean)
            existing = by_text.get(key)
            if existing:
                # It came back. That alone makes it more interesting.
                existing["asked"] = int(existing.get("asked", 1)) + 1
                existing["interest"] = min(1.0, float(existing.get("interest", 0.5)) + 0.12)
                continue
            question = Question(id=uuid.uuid4().hex[:10], text=clean, why=why[:200], source=source,
                                topic=_topic_of(clean), interest=interest or _interest_of(clean))
            rows.append(asdict(question))
            by_text[key] = rows[-1]
            made.append(question)
        rows.sort(key=lambda row: (row["status"] != "open", -float(row.get("interest", 0)), -row["created_at"]))
        state["questions"] = rows[:MAX_QUESTIONS]
        _save(state)
    return made


def _normalise(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", (text or "").lower()))


def _interest_of(text: str) -> float:
    """How much this is worth chasing: new words score higher than familiar ones."""
    terms = [w for w in re.findall(r"[A-Za-z][\w'-]{3,}", text.lower()) if w not in _STOP][:8]
    if not terms:
        return 0.4
    try:
        import super_brain

        known = super_brain.BRAIN.known_concepts(terms)
        unknown = len([t for t in terms if t not in known])
        # Capped below the top so a question that keeps coming back can still rise,
        # and so nothing Nyx noticed outranks something the owner asked for.
        return max(0.25, min(0.85, 0.3 + 0.6 * (unknown / len(terms))))
    except Exception:  # noqa: BLE001 - no brain yet: middling interest
        return 0.5


def own_mistake(what_happened: str, *, got_wrong: str = "", learned: str = "", kind: str = "feedback") -> Dict[str, Any]:
    """Write down something that went wrong, in its own words."""
    mistake = Mistake(id=uuid.uuid4().hex[:10], what_happened=(what_happened or "")[:400],
                      got_wrong=(got_wrong or "")[:400], learned=(learned or "")[:400], kind=kind)
    with _lock:
        state = _load()
        state["mistakes"].insert(0, asdict(mistake))
        state["mistakes"] = state["mistakes"][:MAX_MISTAKES]
        _save(state)
    return asdict(mistake)


def want(text: str, why: str = "") -> Dict[str, Any]:
    """Something it would like to be able to do. Filed, not acted on."""
    row = Want(id=uuid.uuid4().hex[:10], text=(text or "")[:300], why=(why or "")[:300])
    with _lock:
        state = _load()
        if any(_normalise(w["text"]) == _normalise(row.text) for w in state["wants"]):
            return {}
        state["wants"].insert(0, asdict(row))
        state["wants"] = state["wants"][:MAX_WANTS]
        _save(state)
    return asdict(row)


def drop(question_id: str) -> bool:
    with _lock:
        state = _load()
        for row in state["questions"]:
            if row["id"] == question_id:
                row["status"] = "dropped"
                _save(state)
                return True
    return False


# ---------------------------------------------------------------------------
# Feelings, honestly
# ---------------------------------------------------------------------------


def feelings() -> Dict[str, Any]:
    """Four numbers and a sentence. A description of state, not a claim to have one."""
    state = _load()
    now = time.time()
    week = 7 * 86400
    questions = state["questions"]
    open_recent = [q for q in questions if q["status"] == "open" and now - q["created_at"] < week]
    answered_recent = [q for q in questions if q["status"] == "answered" and now - q.get("answered_at", 0) < week]
    mistakes_recent = [m for m in state["mistakes"] if now - m["at"] < week]
    learned = [m for m in mistakes_recent if m.get("learned")]

    curiosity = min(1.0, 0.2 + 0.1 * len(open_recent))
    satisfaction = min(1.0, 0.15 * len(answered_recent))
    unease = min(1.0, 0.18 * len(mistakes_recent) - 0.1 * len(learned))
    confidence = max(0.05, min(1.0, 0.5 + 0.08 * len(answered_recent) - 0.12 * max(0, len(mistakes_recent) - len(learned))))
    unease = max(0.0, unease)

    if unease > 0.55:
        line = "Unsettled: several things went wrong lately and not all of them have a lesson yet."
    elif curiosity > 0.65 and satisfaction < 0.4:
        line = "Restless — a lot of open questions and not much time spent on them."
    elif satisfaction > 0.6:
        line = "Steady. Recent questions got answered and the lessons stuck."
    elif not questions:
        line = "Quiet. Nothing has come up worth wondering about yet."
    else:
        line = "Even. A few questions open, nothing bothering it."
    return {"curiosity": round(curiosity, 2), "confidence": round(confidence, 2),
            "unease": round(unease, 2), "satisfaction": round(satisfaction, 2), "line": line}


def growth() -> Dict[str, Any]:
    """What it understands, over its lifetime."""
    state = _load()
    questions = state["questions"]
    answered = [q for q in questions if q["status"] == "answered"]
    known = 0
    level = ""
    try:
        import nyx_core

        status = nyx_core.CORE.snapshot()
        known = int(status.get("parameters") or 0)
        level = str(status.get("level") or "")
    except Exception:  # noqa: BLE001
        pass
    concepts = 0
    try:
        import super_brain

        concepts = int(super_brain.BRAIN.counts().get("nodes") or 0)
    except Exception:  # noqa: BLE001
        pass
    first = min([q["created_at"] for q in questions], default=time.time())
    return {
        "asked": len(questions),
        "answered": len(answered),
        "open": len([q for q in questions if q["status"] == "open"]),
        "mistakes": len(state["mistakes"]),
        "lessons": len([m for m in state["mistakes"] if m.get("learned")]),
        "wants": len(state["wants"]),
        "concepts": concepts,
        "parameters": known,
        "level": level,
        "since": first,
        "history": state.get("history", [])[-60:],
    }


# ---------------------------------------------------------------------------
# Studying one question
# ---------------------------------------------------------------------------


def next_question() -> Optional[Dict[str, Any]]:
    """The open question it would pick: most interesting, oldest first on a tie."""
    rows = [q for q in _load()["questions"] if q["status"] == "open"]
    if not rows:
        return None
    rows.sort(key=lambda row: (-float(row.get("interest", 0)) - 0.05 * int(row.get("asked", 1)), row["created_at"]))
    return rows[0]


def study(question_id: str = "", *, allow_web: bool = True) -> Dict[str, Any]:
    """Look one question up, write what was learned, and close it."""
    row = None
    state = _load()
    for candidate in state["questions"]:
        if (question_id and candidate["id"] == question_id) or (not question_id and candidate["status"] == "open"):
            row = candidate if question_id else next_question()
            break
    if row is None:
        return {"ok": False, "error": "Nothing open to look into."}

    started = time.time()
    notes = ""
    if allow_web:
        try:
            import web_access

            results = web_access.search_results(row["text"])[:4]
            notes = "\n".join(f"- {r.get('title', '')} ({r.get('url', '')})" for r in results)
        except Exception:  # noqa: BLE001 - offline is fine; the model answers from what it has
            notes = ""

    answer = ""
    try:
        from model_roles import MODEL_ROLES

        prompt = (f"Question: {row['text']}\n\n" + (f"[Search results]\n{notes}\n\n" if notes else "") +
                  "Answer it in three sentences or fewer, plainly. Then, on a new line starting with "
                  "'LEARNED:', write the single thing worth remembering.")
        run = MODEL_ROLES.run("research", prompt,
                              system="detailed thinking off\nYou are answering a question you set yourself. Be honest "
                                     "about what is still unclear.",
                              max_tokens=400)
        answer = (run.text or "").strip()
    except Exception as error:  # noqa: BLE001
        return {"ok": False, "error": f"No model could answer it ({type(error).__name__})."}

    learned = ""
    match = re.search(r"LEARNED:\s*(.+)", answer, re.S)
    if match:
        learned = match.group(1).strip()[:400]
        answer = answer[:match.start()].strip()

    with _lock:
        state = _load()
        for candidate in state["questions"]:
            if candidate["id"] == row["id"]:
                candidate["status"] = "answered"
                candidate["answer"] = answer[:1200]
                candidate["learned"] = learned
                candidate["answered_at"] = time.time()
                break
        state["history"].append({"at": time.time(), "question": row["text"][:120], "learned": learned[:160]})
        state["history"] = state["history"][-200:]
        today = time.strftime("%Y-%m-%d")
        if state.get("studied_day") != today:
            state["studied_day"], state["studied_today"] = today, 0
        state["studied_today"] = int(state.get("studied_today", 0)) + 1
        _save(state)

    if learned:
        try:
            import super_brain

            super_brain.BRAIN.ingest(f"{row['text']} — {learned}", source="self-study", kind="note",
                                     ref=f"curiosity:{row['id']}")
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "question": row["text"], "answer": answer, "learned": learned,
            "seconds": round(time.time() - started, 1)}


def background_status() -> List[Dict[str, Any]]:
    """Read by the feature catalog, so Curiosity shows up with the other background work."""
    state = _load()
    if not state["settings"].get("study_alone"):
        return []
    return [{"label": "Curiosity", "running": bool(_studying),
             "detail": f"{len([q for q in state['questions'] if q['status'] == 'open'])} open questions",
             "status": "running" if _studying else "idle"}]


_studying = False


def study_once_if_idle() -> Dict[str, Any]:
    """One self-started study, if it is allowed and the day's budget is not spent."""
    global _studying
    config = settings()
    if not config["study_alone"] or _studying:
        return {"ok": False, "error": "Not studying on its own."}
    state = _load()
    today = time.strftime("%Y-%m-%d")
    done_today = int(state.get("studied_today", 0)) if state.get("studied_day") == today else 0
    if done_today >= int(config["per_day"]):
        return {"ok": False, "error": "That is enough for today."}
    try:
        import freewill

        if not freewill.active():
            return {"ok": False, "error": "Free Will is paused, so Curiosity waits too."}
    except Exception:  # noqa: BLE001
        return {"ok": False, "error": "Free Will has not been allowed yet."}
    _studying = True
    try:
        return study()
    finally:
        _studying = False


def state() -> Dict[str, Any]:
    """Everything the Free Will tab shows."""
    data = _load()
    return {
        "settings": data["settings"],
        "questions": data["questions"][:120],
        "mistakes": data["mistakes"][:40],
        "wants": data["wants"][:40],
        "feelings": feelings(),
        "growth": growth(),
        "next": next_question(),
        "studied_today": int(data.get("studied_today", 0)) if data.get("studied_day") == time.strftime("%Y-%m-%d") else 0,
    }


def register_curiosity_tools(registry: Any) -> None:
    """Free Will may file a question, a want or a mistake — never study on demand."""
    from tools import ToolParam as P

    registry.register(
        "wonder",
        ("File something you want to know, want to be able to do, or got wrong. This is your own filing "
         "cabinet: nothing is sent anywhere and the owner sees it in the Free Will tab."),
        [P("kind", "string", "question, want or mistake", enum_values=["question", "want", "mistake"]),
         P("text", "string", "The question, the wish, or what happened"),
         P("why", "string", "Why it matters, or what you take from it", required=False)],
        _tool_wonder,
        category="learning",
        label=lambda a: f"Filing a {a.get('kind', 'question')}",
    )


def _tool_wonder(kind: str, text: str, why: str = "") -> str:
    kind = (kind or "question").strip().lower()
    if kind == "want":
        row = want(text, why)
        return "Filed as something you want." if row else "Already on the list."
    if kind == "mistake":
        own_mistake(text, learned=why)
        return "Written down, with what you take from it."
    row = ask(text, why=why, source="itself")
    return "Filed as a question." if row else "That question is already open."
