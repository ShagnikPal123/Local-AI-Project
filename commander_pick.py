"""Commander's pick: which kind of model, how much effort and which sector a piece of work gets.

The owner (Fixer Upper, 2026-10-13): "tasks are assigned to different models and can auto assign based on what was
assigned before", and for the Commander: "the ai will determine the best ai model for this whether cloud or local and
the best effort".

Two layers, so it is right on day one and gets better with use:

* **Rules** read the words: code work goes to the code models, research to the heavy ones, a short question to a light
  one, everything else to the general one. How much there is to do (length, how many separate parts) sets the effort.
* **Learning** remembers every assignment (``learn``) and, for a new task, finds the earlier tasks that read most alike
  (IDF-weighted word overlap, a nearest-neighbour vote). When enough of them agree, their choice wins over the rules.
  When the owner changes a thread's model or effort by hand, that correction counts three times, so the next similar
  task is assigned the way he wanted. This is the machine-learning part he asked for: it is trained on his own use and
  needs no model call.

``model_for`` then turns the kind of model into a real one that can run now, cloud or local, by reusing
``model_autoassign``'s scoring (which never picks a paid provider unless it is the owner's own pick in the model menu).

The kinds are the owner's model families from ``model_lineup`` (Pico for lighter work, Monolith for general work,
Crescendo for power-hungry work, Zencode for code) and the efforts are its effort dial (Low to Aleph), so a thread's
pick reads the same as the model picker. Aleph can split a job across a swarm, so only the owner or the Commander's
explicit choice gives it; the rules stop at Super.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from paths import atomic_replace, data_path

TIERS = ("pico", "monolith", "crescendo", "zencode")
EFFORTS = ("low", "mid", "normal", "high", "higher", "super", "aleph")
SECTORS = ("Updates", "Fixes", "Questions", "Research")

# Owner's ask (Drive doc 1, item 1.30): threads work like a team where each has one job, the way the modern AI tools
# coordinate agents. The job goes in the thread's brief, so a research thread reports instead of changing things and a
# test thread tries to break the work instead of rebuilding it.
JOBS = ("research", "plan", "build", "test", "review")
JOB_HINTS = {
    "research": "find out and compare; report what you found and where it came from, and change nothing",
    "plan": "work out the steps, their order and the risks; write the plan and do not build it",
    "build": "make the change, run the checks you can, and say what changed",
    "test": "try to break it: run the tests, reproduce the problem, and report what passed and what failed",
    "review": "read the work critically: list the real problems with where they are, then what is fine",
}
_JOB_WORDS = {
    "research": {"research", "compare", "comparison", "find", "investigate", "look", "explore", "survey", "option",
                 "alternative", "which", "learn", "source", "read"},
    "plan": {"plan", "design", "spec", "outline", "architecture", "roadmap", "approach", "strategy", "steps", "split"},
    "test": {"test", "verify", "check", "reproduce", "qa", "regression", "coverage", "try", "break", "confirm"},
    "review": {"review", "audit", "critique", "proofread", "inspect", "assess", "feedback", "pr", "diff"},
}


def job_for(text: str) -> str:
    """The thread's job from the words alone: the job whose words appear most, and build when none do."""
    found = set(words(text))
    hits = {job: len(found & vocab) for job, vocab in _JOB_WORDS.items()}
    best = max(hits, key=lambda job: hits[job])
    return best if hits[best] else "build"


def _family_names() -> Dict[str, str]:
    """The families' display names from the lineup, so a rename there shows here too."""
    names = {"pico": "Pico", "monolith": "Monolith", "crescendo": "Crescendo", "zencode": "Zencode"}
    try:
        import model_lineup

        for tier in TIERS:
            found = model_lineup.family(tier)
            if found is not None:
                names[tier] = found.name
    except Exception:  # noqa: BLE001 - the lineup is optional here; the names above are its own
        pass
    return names


TIER_LABELS = _family_names()

#: Which built-in job's needs a kind borrows when a real model is scored (model_autoassign.ROLE_NEEDS). Monolith is
#: not a built-in job, so it gets auto-assign's default weighting (mostly quality, some speed and reading length).
TIER_ROLE = {"pico": "fast_chat", "zencode": "code_generation", "crescendo": "research", "monolith": "commander_general"}

#: How many earlier tasks get a vote, how alike they must read, and how much they must agree before they win.
NEIGHBOURS = 5
MIN_SIMILARITY = 0.25
MIN_AGREEMENT = 0.6
#: A correction the owner made by hand outweighs an assignment the Commander made itself.
OWNER_WEIGHT = 3.0
MAX_EXAMPLES = 400

_WORD = re.compile(r"[a-z0-9][a-z0-9+#.]*[a-z0-9+#]|[a-z0-9]")
_STOP = frozenset("""a an the and or but if then so to of in on at by for with from into onto about as is are was were be
been being it its this that these those there here i me my we our you your he she they them their what which who whom
whose please can could would should will shall may might must do does did done have has had just also too very really
let lets get got make made want need like some any all more most much many few lot thing things way""".split())

_CODE = frozenset("""code coding coder bug bugs fix fixes fixing error errors crash crashes function functions class
method test tests testing pytest refactor build builds compile compiler repo repository commit commits branch merge python
typescript javascript react vite tsx jsx api endpoint route routes script scripts css html frontend backend deploy stack
traceback lint linter module modules import package npm pip git github sql database schema json regex""".split())
_RESEARCH = frozenset("""research compare comparison analyse analyze analysis study studies sources report reports
investigate investigation survey market markets evaluate evaluation review overview deep pros cons options alternatives
landscape benchmark benchmarks""".split())
_FIX = frozenset("""fix fixes fixing bug bugs broken error errors crash crashes fails failing failure issue issues wrong
doesn't won't isn't cannot can't stuck""".split())
_QUESTION_STARTS = frozenset("what why how when where who which is are can could does do should would will".split())


def words(text: str) -> List[str]:
    """The words that carry meaning, in order, lower case. Light stemming so "tests" and "test" meet."""
    out: List[str] = []
    for word in _WORD.findall(str(text or "").lower()):
        if word in _STOP or len(word) > 40:
            continue
        if len(word) > 4 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.append(word)
    return out


def _parts(text: str) -> int:
    """How many separate pieces of work a message holds: list lines, or "and then" / "also" joins."""
    lines = [line for line in str(text or "").splitlines() if re.match(r"\s*([-*•]|\d+[.)])\s+\S", line)]
    if len(lines) >= 2:
        return len(lines)
    joins = len(re.findall(r"\b(and then|after that|also|then)\b", str(text or "").lower()))
    return 1 + min(joins, 4)


def rule_pick(text: str) -> Dict[str, Any]:
    """The pick from the words alone, with the reason in a sentence."""
    raw = str(text or "").strip()
    found = set(words(raw))
    plain = re.findall(r"[a-z']+", raw.lower())
    count = len(plain)
    parts = _parts(raw)
    vocab = found | set(plain)
    code_hits = len(vocab & _CODE)
    research_hits = len(vocab & _RESEARCH)
    fixing = bool(vocab & _FIX)
    asking = raw.endswith("?") or (bool(plain) and plain[0] in _QUESTION_STARTS)

    if code_hits >= 1 and code_hits >= research_hits:
        tier, why = "zencode", "it reads like code work"
    elif research_hits >= 1:
        tier, why = "crescendo", "it is research that reads and compares a lot"
    elif asking and count <= 25 and parts == 1:
        tier, why = "pico", "it is a short question"
    else:
        tier, why = "monolith", "it is everyday work"

    size = count / 40 + (parts - 1)
    if tier == "pico":
        effort = "low"
    elif size < 0.6:
        effort = "mid" if asking else "normal"
    elif size < 1.5:
        effort = "normal"
    elif size < 3.5:
        effort = "high"
    elif size < 6:
        effort = "higher"
    else:
        effort = "super"
    if tier == "crescendo" and EFFORTS.index(effort) < EFFORTS.index("high"):
        effort = "high"  # research that stops early is worse than no research

    if fixing and tier == "zencode":
        sector = "Fixes"
    elif tier == "crescendo":
        sector = "Research"
    elif asking and parts == 1:
        sector = "Questions"
    else:
        sector = "Updates"
    return {"tier": tier, "effort": effort, "sector": sector, "why": why, "source": "rules", "confidence": 1.0}


class Picker:
    """Remembers what each task was given, and predicts the next one from the closest earlier tasks."""

    def __init__(self, path: Optional[Path] = None, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self.clock = clock
        self._lock = threading.RLock()
        self._examples: Optional[List[Dict[str, Any]]] = None

    def _file(self) -> Path:
        return self._path or data_path("commander_picks.json")

    def _load(self) -> List[Dict[str, Any]]:
        if self._examples is None:
            try:
                raw = json.loads(self._file().read_text(encoding="utf-8"))
                self._examples = [e for e in raw.get("examples", []) if isinstance(e, dict) and e.get("words")]
            except (OSError, ValueError, AttributeError):
                self._examples = []
        return self._examples

    def _save(self) -> None:
        target = self._file()
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps({"examples": self._examples}, indent=0), encoding="utf-8")
        atomic_replace(tmp, target)

    def learn(self, text: str, tier: str, effort: str, sector: str, *, by_owner: bool = False, title: str = "") -> None:
        """Keep one assignment as a training example. Unknown values are not learned (they would teach nonsense)."""
        if tier not in TIERS or effort not in EFFORTS or sector not in SECTORS:
            return
        found = sorted(set(words(text)))[:80]
        if not found:
            return
        with self._lock:
            examples = self._load()
            examples.append({"words": found, "tier": tier, "effort": effort, "sector": sector,
                             "weight": OWNER_WEIGHT if by_owner else 1.0, "title": str(title or "")[:80],
                             "ts": self.clock()})
            del examples[:-MAX_EXAMPLES]
            self._save()

    def count(self) -> int:
        with self._lock:
            return len(self._load())

    def neighbours(self, text: str, limit: int = NEIGHBOURS) -> List[Tuple[float, Dict[str, Any]]]:
        """The earlier tasks that read most like this one, with how alike (0–1). Rare shared words count most."""
        query = set(words(text))
        with self._lock:
            examples = list(self._load())
        if not query or not examples:
            return []
        total = len(examples)
        df: Dict[str, int] = {}
        for example in examples:
            for word in example["words"]:
                df[word] = df.get(word, 0) + 1

        def idf(word: str) -> float:
            return math.log((total + 1) / (df.get(word, 0) + 1)) + 1.0

        q_norm = math.sqrt(sum(idf(w) ** 2 for w in query))
        scored = []
        for example in examples:
            shared = query.intersection(example["words"])
            if not shared:
                continue
            e_norm = math.sqrt(sum(idf(w) ** 2 for w in example["words"]))
            similarity = sum(idf(w) ** 2 for w in shared) / (q_norm * e_norm)
            if similarity >= MIN_SIMILARITY:
                scored.append((round(similarity, 4), example))
        scored.sort(key=lambda pair: (-pair[0], -pair[1].get("ts", 0)))
        return scored[:limit]

    def suggest(self, text: str) -> Dict[str, Any]:
        """Rules first, then each field the earlier tasks agree on is taken from them instead, and the reason says so."""
        pick = rule_pick(text)
        near = self.neighbours(text)
        if not near:
            return pick
        learned: List[str] = []
        confidence = 1.0
        for field in ("tier", "effort", "sector"):
            votes: Dict[str, float] = {}
            for similarity, example in near:
                votes[example[field]] = votes.get(example[field], 0.0) + similarity * float(example.get("weight", 1.0))
            best, weight = max(votes.items(), key=lambda kv: kv[1])
            agreement = weight / sum(votes.values())
            strong = sum(1 for s, e in near if e[field] == best) >= 2 or any(
                e[field] == best and e.get("weight", 1.0) >= OWNER_WEIGHT and s >= 0.5 for s, e in near)
            if agreement >= MIN_AGREEMENT and strong:
                if best != pick[field]:
                    learned.append(field)
                pick[field] = best
                confidence = min(confidence, round(agreement, 2))
        if learned or confidence < 1.0:
            like = [e.get("title") for _s, e in near if e.get("title")][:2]
            example = f" (like “{like[0]}”)" if like else ""
            pick["why"] = f"earlier tasks that read like this one were given the same{example}"
            pick["source"] = "learned"
            pick["confidence"] = confidence
            pick["learned"] = learned
        return pick


PICKER = Picker()


def model_for(tier: str, *, configured: Optional[Dict[str, bool]] = None,
              table: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A real (provider, model) for a kind of model, cloud or local, or an empty pick that lets the router decide.

    Reuses auto-assign's scoring so a thread can never start a bill: paid providers only count when they are the
    owner's own pick in the model menu.
    """
    empty = {"provider": "", "model": "", "label": "Router decides", "local": False,
             "why": "no model fits right now, so the router picks for each message"}
    try:
        import model_autoassign

        pool = model_autoassign.candidates(configured)
        if table is None:
            try:
                from identity0 import api as kahuna

                table = kahuna.competence()
            except Exception:
                table = {}
        role_id = TIER_ROLE.get(tier, "commander_general")
        role = {"job": "text", "title": "General work", "description": ""}
        scored = [s for s in (model_autoassign.score(role_id, role, c, table) for c in pool) if s]
    except Exception:  # noqa: BLE001 - a broken catalog must not stop work being handed out
        return empty
    if not scored:
        return empty
    best = max(scored, key=lambda s: (s["score"], s.get("local", False)))
    return {"provider": best["provider"], "model": best["model"], "label": best.get("label") or best["model"],
            "local": bool(best.get("local")), "why": f"{best.get('label') or best['model']} {', '.join(best.get('reasons', []))}"}


def pick(text: str, *, picker: Optional[Picker] = None, with_model: bool = True) -> Dict[str, Any]:
    """Everything a new thread needs: kind of model, effort, sector, a real model, and one line saying why."""
    chosen = (picker or PICKER).suggest(text)
    model = model_for(chosen["tier"]) if with_model else {"provider": "", "model": "", "label": "", "local": False, "why": ""}
    return {**chosen, "tier_label": TIER_LABELS.get(chosen["tier"], chosen["tier"]), "provider": model["provider"],
            "model": model["model"], "model_label": model["label"], "local": model["local"], "model_why": model["why"]}
