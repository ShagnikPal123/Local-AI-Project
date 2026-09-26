"""Second opinions on hard requests: the answering model consults others before it works.

Request H2: "On heavy tasks auto consult with other agents both on same model and other."
Request H6: "the model keeps referring back to Gemini, try to make sure it does it only when needed
and on hard questions. Make it similar to collaboration or coordination."

So the owner's pick keeps answering. On a heavy request it first asks, in parallel and within a
time budget:

* **the same model**, in a fresh context and a critic's role (a second pass of the same mind);
* **another model** — the strongest other provider that can answer (Gemini's smart model when the
  owner's pick is not Gemini), which is where Gemini now earns its place: as a consultant;
* **agents the owner named** in an agent's "Consults" setting, each with its own model and focus.

Their short notes go into the turn as context the answering model is free to use or ignore, and
are shown in the Thinking section, so nothing happens out of sight. Nothing a consultant writes is
run; it is text for another model to read.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any, Dict, List, Optional

PREFIX = "[Second opinions]"
MODES = ("off", "heavy", "always")
MODEL_MODES = ("same", "other", "both")
#: Strongest-first order for the "other model" seat.
OTHER_ORDER = ("gemini", "nvidia", "deepseek", "claude", "openai", "groq", "kimi", "qwen")

_HEAVY_WORDS = re.compile(
    r"\b(design|architect\w*|strateg\w*|plan (?:out|for)|compare|trade-?offs?|prove|derive|optimi[sz]\w*|debug\w*|"
    r"refactor\w*|analy[sz]\w*|evaluate|in[- ]depth|step[- ]by[- ]step|pros and cons|best (?:way|approach)|"
    r"root cause|business plan|algorithm\w*|security (?:review|audit)|diagnos\w*|research)\b",
    re.IGNORECASE,
)
_EXPLICIT = re.compile(r"\b(think (?:hard|carefully|deeply)|thoroughly|deep dive|double[- ]check|be rigorous|second opinion)\b",
                       re.IGNORECASE)

ADVISOR_SYSTEM = (
    "You are advising another AI model that is about to handle a request for its user. You are not talking to "
    "the user. In at most 140 words of plain bullet points give: the key considerations, likely mistakes or "
    "traps, and the approach you would take. No preamble, no full answer."
)
CRITIC_SYSTEM = (
    "You are the same kind of model as the one about to answer, reading the request fresh as a critic. You are "
    "not talking to the user. In at most 120 words of bullet points: what is easy to get wrong here, what an "
    "excellent answer must include, and one thing to verify. No preamble."
)


def heaviness(text: str) -> float:
    """A rough 0–6 score of how much a request benefits from more than one mind."""
    body = text or ""
    score = 0.0
    if len(body) > 600:
        score += 1
    if len(body) > 1500:
        score += 1
    score += min(2.0, 0.5 * len(_HEAVY_WORDS.findall(body)))
    if body.count("?") >= 2:
        score += 0.5
    if "```" in body:
        score += 0.5
    if _EXPLICIT.search(body):
        score += 2
    return score


def is_heavy(text: str) -> bool:
    return heaviness(text) >= 2


def _router():
    from agent_runtime import _router as shared

    return shared()


def _available(provider: str) -> bool:
    try:
        return _router().unavailable_reason(provider, explicit=False) is None
    except Exception:  # pragma: no cover
        return False


def _default_model(provider: str) -> str:
    from config import SETTINGS

    if provider == "gemini":
        return getattr(SETTINGS, "gemini_smart_model", "") or getattr(SETTINGS, "gemini_model", "")
    return str(getattr(SETTINGS, f"{provider}_model", "") or "")


def seats(primary: str, primary_model: str = "", models: str = "both",
          agents: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, str]]:
    """Who to ask: the same model, another model, and named agents — only ones that can answer."""
    chosen: List[Dict[str, str]] = []
    primary = (primary or "").strip().lower()
    if models in ("same", "both") and primary and primary != "ollama":
        chosen.append({"kind": "same", "provider": primary, "model": primary_model or "", "system": CRITIC_SYSTEM,
                       "label": f"{primary}{' · ' + primary_model if primary_model else ''} (fresh look)"})
    if models in ("other", "both"):
        for name in OTHER_ORDER:
            if name != primary and _available(name):
                model = _default_model(name)
                chosen.append({"kind": "other", "provider": name, "model": model, "system": ADVISOR_SYSTEM,
                               "label": f"{name}{' · ' + model if model else ''}"})
                break
    for agent in (agents or [])[:2]:
        provider = (agent.get("provider") or primary or "").lower()
        if not provider or not _available(provider):
            continue
        focus = agent.get("goal") or ""
        expertise = ", ".join(agent.get("expertise") or [])
        chosen.append({"kind": "agent", "provider": provider, "model": agent.get("model") or "",
                       "system": f"You are {agent['name']}, a specialist: {focus}" + (f" ({expertise})" if expertise else "")
                       + ". " + ADVISOR_SYSTEM, "label": f"{agent.get('emoji', '')} {agent['name']}".strip()})
    return chosen


def consult(question: str, *, primary: str, primary_model: str = "", models: str = "both",
            agents: Optional[List[Dict[str, Any]]] = None, budget: float = 25.0,
            on_note=None) -> List[Dict[str, str]]:
    """Ask every seat in parallel; return the notes that arrived within ``budget`` seconds."""
    import model_hub

    todo = seats(primary, primary_model, models, agents)
    if not todo:
        return []
    prompt = f"The request:\n{(question or '').strip()[:6000]}"
    notes: List[Dict[str, str]] = []

    def ask(seat: Dict[str, str]) -> Optional[Dict[str, str]]:
        started = time.perf_counter()
        reply = model_hub.complete(seat["provider"], seat["model"], prompt, system=seat["system"],
                                   max_tokens=400, timeout=max(5.0, budget - 1))
        text = _bullets_only((getattr(reply, "text", "") or "").strip())
        if not text:
            return None
        return {"kind": seat["kind"], "by": seat["label"], "text": text[:1200],
                "seconds": round(time.perf_counter() - started, 1)}

    pool = ThreadPoolExecutor(max_workers=len(todo), thread_name_prefix="nyx-consult")
    futures = [pool.submit(ask, seat) for seat in todo]
    done, _pending = wait(futures, timeout=budget)
    for future in futures:
        if future not in done:
            continue
        try:
            note = future.result()
        except Exception:  # noqa: BLE001 - a consultant that fails is simply not heard
            note = None
        if note:
            notes.append(note)
            if on_note is not None:
                on_note(note)
    pool.shutdown(wait=False, cancel_futures=True)
    return notes


_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")


def _bullets_only(text: str) -> str:
    """Reasoning models sometimes think out loud first ("We need to output…"); keep the bullets."""
    lines = text.splitlines()
    bullets = [line.rstrip() for line in lines if _BULLET.match(line)]
    return "\n".join(bullets) if len(bullets) >= 2 else text


def as_context(notes: List[Dict[str, str]]) -> str:
    lines = [PREFIX, "Other models were asked about this request before you work on it. Use what is right, "
             "ignore what is not, and decide yourself. Do not mention them unless it helps the user."]
    for note in notes:
        lines.append(f"\n— {note['by']}:\n{note['text']}")
    return "\n".join(lines)


def manager_settings() -> Dict[str, Any]:
    """The Manager's own consult settings (editable in its Properties)."""
    try:
        from agent_runtime import load_roster

        manager = next((a for a in load_roster() if a.get("role") == "master"), {}) or {}
    except Exception:  # pragma: no cover
        manager = {}
    return {"consult": manager.get("consult") or "heavy", "consult_models": manager.get("consult_models") or "both",
            "consult_with": list(manager.get("consult_with") or [])}


def agents_named(names: List[str]) -> List[Dict[str, Any]]:
    try:
        from agent_runtime import roster_entry_exact

        return [entry for entry in (roster_entry_exact(n) for n in names) if entry]
    except Exception:  # pragma: no cover
        return []
