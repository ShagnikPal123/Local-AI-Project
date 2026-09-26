"""Big Kahuna as a router provider: the main brain every chat turn goes through first.

For each model call it:

1. **classifies** the request (Nyx Core's domain head + consult's heaviness score) — offline, ~ms;
2. **plans**: the lead is the member with the best competence for that domain; hard requests in a
   weak domain get a small panel of helpers whose drafts the lead reads first; some turns also get a
   shadow answer for comparison (budgeted); in *twin* stage the own model shadows the teacher, in
   *solo* stage it leads and the teacher is sampled;
3. **streams** the lead through the router (key failover, metrics, image routing all kept);
4. **records** the experience; the shadow runs after the answer, off the turn's clock.

It sits in front of the router's old chain, not in place of it: when it raises ``ProviderError``
the router simply carries on with the next provider, so a bug here costs one retry, never a turn.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

import identity0
from identity0 import collab, competence, experience, members as members_module
from identity0.members import Member
from providers.base import Provider, ProviderError

_LOG = logging.getLogger("nyx.identity0")
_shared: List["weakref.ReferenceType[Any]"] = []
_turn = threading.local()
# Plain-word signals for the domains Nyx Core's small head still files under "chat" (checked in order).
_KEYWORD_DOMAINS = (
    ("code", re.compile(r"```|\b(python|javascript|typescript|java|c\+\+|c#|rust|golang|kotlin|swift|sql|regex|html|"
                        r"css|react|vue|node(js)?|django|flask|fastapi|api|function|method|variable|bug|debug|"
                        r"traceback|stack ?trace|exception|compile[sd]?|refactor|script|code|coding|repo|git|npm|"
                        r"pip|dockerfile|json|yaml|unit tests?)\b", re.I)),
    ("email", re.compile(r"\b(e-?mail|gmail|inbox|outlook)\b", re.I)),
    ("design", re.compile(r"\b(logo|ui|ux|mock-?up|wireframe|colou?r palette|typography|figma|landing page design)\b", re.I)),
    ("web", re.compile(r"\b(search (for|the web)|look up|google|latest|news|today'?s|this week|weather|price of|"
                       r"stock price|website|url)\b", re.I)),
    ("files", re.compile(r"\b(pdf|docx|csv|spreadsheet|excel|folder|directory|my files?)\b", re.I)),
    ("knowledge", re.compile(r"^(what|who|when|where|why|how) (is|are|was|were|did|does|do)\b|\b(explain|history of|"
                             r"define|definition of|summari[sz]e)\b", re.I)),
)


def set_current_turn(turn_id: str) -> None:
    """TurnRunner tells us which turn the next model calls belong to (same thread)."""
    _turn.id = turn_id or ""


def current_turn() -> str:
    return getattr(_turn, "id", "")


def shared_router() -> Any:
    """The most recently made router that is still alive (tests and tools can make several)."""
    for ref in reversed(_shared):
        router = ref()
        if router is not None:
            return router
    return None


def _remember(router: Any) -> "weakref.ReferenceType[Any]":
    ref = weakref.ref(router)
    _shared[:] = [r for r in _shared if r() is not None][-7:] + [ref]
    return ref


@dataclass
class Plan:
    domain: str
    difficulty: float
    stage: str
    lead: Member
    shadow: Optional[Member] = None
    helpers: List[Member] = field(default_factory=list)
    ranked: List[Member] = field(default_factory=list)
    speed: Optional[str] = None  # "voice" / "trading": the fastest good member, no helpers, no reasoning
    tool_step: bool = False  # this call is mid-turn, reading tool results

    @property
    def protocol(self) -> str:
        return "panel" if self.helpers else "solo"


def _settings() -> Dict[str, Any]:
    try:
        from identity0.state import get_settings

        return get_settings()
    except Exception:  # noqa: BLE001
        return {"enabled": False}


def classify(text: str) -> tuple:
    domain, confidence = "chat", 0.0
    try:
        import nyx_core

        guess = nyx_core.CORE.predict(text or "")
        domain, confidence = str(guess.get("domain") or "chat"), float(guess.get("domain_p") or 0.0)
    except Exception:  # noqa: BLE001 - an untrained or missing head means "chat"
        pass
    if domain == "chat" or confidence < 0.5:
        # The learned head is young: plain words decide until it is sure ("fix this Python bug" is code).
        for name, pattern in _KEYWORD_DOMAINS:
            if pattern.search(text or ""):
                domain = name
                break
    try:
        import consult

        difficulty = min(1.0, consult.heaviness(text or "") / 4.0)
    except Exception:  # noqa: BLE001
        difficulty = 0.0
    return domain, difficulty


def _last_user(messages: List[Dict[str, Any]]) -> str:
    """The owner's own last words — not a tool result, which TurnRunner also sends with role "user"."""
    for message in reversed(messages):
        if message.get("role") == "user" and not message.get("_tool_results"):
            return str(message.get("content", "") or "")
    return ""


def _tool_step(messages: List[Dict[str, Any]]) -> bool:
    """This call continues a turn after tools ran (the newest user-role message carries their results)."""
    for message in reversed(messages):
        if message.get("role") == "user":
            return bool(message.get("_tool_results"))
    return False


def _picked() -> str:
    try:
        import model_choice

        name = str(model_choice.load().get("provider") or "")
        return "" if name == identity0.PROVIDER_ID else name
    except Exception:  # noqa: BLE001
        return ""


def _consulted(messages: List[Dict[str, Any]]) -> bool:
    try:
        import consult

        return any(str(m.get("content", "")).startswith(consult.PREFIX) for m in messages if m.get("role") == "system")
    except Exception:  # noqa: BLE001
        return False


def make_plan(messages: List[Dict[str, Any]], pool: List[Member], *, rng: Optional[random.Random] = None) -> Plan:
    rng = rng or random
    settings = _settings()
    text = _last_user(messages)
    domain, difficulty = classify(text)
    needs_vision = any(m.get("images") for m in messages if isinstance(m, dict))
    ranked = competence.rank(domain, pool, needs_vision=needs_vision, picked=_picked())
    own = next((m for m in pool if m.provider == "self"), None)
    stage = competence.stage(domain, own is not None)
    try:
        from identity0 import predict

        speed = predict.speed_mode(messages, text)
    except Exception:  # noqa: BLE001
        speed = None
    if speed:
        # Spoken answers and trading can't wait: among members nearly as good as the best, take the fastest.
        best = competence.score(domain, ranked[0])
        close = [m for m in ranked if competence.score(domain, m) >= best - 0.08]
        fastest = min(close, key=lambda m: (0 if m.local else 1, competence.avg_ms(domain, m)))
        ranked = [fastest] + [m for m in ranked if m.id != fastest.id]
    lead = ranked[0]
    plan = Plan(domain=domain, difficulty=difficulty, stage=stage, lead=lead, ranked=ranked, speed=speed)
    if _tool_step(messages):
        # Reading tool results mid-turn: one quick lead, no shadow or panel (their answers can't use tools).
        plan.tool_step = True
        return plan
    others = [m for m in ranked if m.id != lead.id and m.provider != "self"]
    local_only = bool(settings.get("shadow_local_only", False))
    usable = [m for m in others if m.local or not local_only]

    if stage == "twin" and own is not None and lead.id != own.id and not needs_vision:
        plan.shadow = own  # "two models at once": the own model answers alongside the teacher
    elif stage == "solo" and lead.provider == "self" and usable and rng.random() < 0.1:
        plan.shadow = usable[0]  # keep checking the graduate against the teacher now and then
    elif usable and rng.random() < float(settings.get("shadow_rate", 0.25)):
        plan.shadow = usable[0]

    weak = competence.score(domain, lead) < 0.6
    if (settings.get("panel_on_hard", True) and difficulty >= 0.5 and weak and usable and not speed
            and not _consulted(messages)):
        plan.helpers = usable[:2]
        if plan.shadow in plan.helpers:
            plan.shadow = None  # a helper's draft is already part of the answer
    return plan


class Identity0Provider(Provider):
    """The router's view of Big Kahuna. ``supports_vision``: it routes pictures to a member that can see."""

    name = identity0.PROVIDER_ID
    label = identity0.NAME
    supports_vision = True

    def __init__(self, router: Any) -> None:
        self._router = _remember(router)
        self.last_plan: Optional[Plan] = None

    # --- Provider contract -----------------------------------------------------------------

    def is_available(self) -> bool:
        if collab.inside() or not _settings().get("enabled", False):
            return False
        router = self._router()
        if router is None:
            return False
        try:
            return bool(members_module.available(router))
        except Exception:  # noqa: BLE001
            return False

    def chat(self, messages: List[Dict[str, Any]]) -> str:
        return "".join(e.get("text", "") for e in self.stream_events(messages) if e.get("type") == "text")

    def stream_events(self, messages: List[Dict[str, Any]], *, model: Optional[str] = None,
                      thinking: bool = False) -> Iterator[Dict[str, Any]]:
        if collab.inside():
            raise ProviderError("Big Kahuna cannot call itself.")
        router = self._router()
        if router is None:
            raise ProviderError("Big Kahuna lost its router.")
        pool = members_module.available(router)
        if not pool:
            raise ProviderError("Big Kahuna has no model to work with right now.")
        try:
            plan = make_plan(messages, pool)
        except Exception as error:  # noqa: BLE001 - planning bugs must not cost the turn
            raise ProviderError(f"Big Kahuna could not plan: {error}") from error
        if not current_turn():
            # Internal calls (titles, summaries, prompt refining) answer solo: no shadows, no helpers.
            plan.shadow, plan.helpers = None, []
        self.last_plan = plan
        # Reasoning costs local models many seconds; spend it where the request is hard.
        thinking = bool(thinking) and plan.difficulty >= 0.5 and not plan.speed and not plan.tool_step
        record = _quietly(experience.begin, turn_id=current_turn(), prompt=_last_user(messages), messages=messages,
                          domain=plan.domain, difficulty=plan.difficulty, protocol=plan.protocol) or {
            "turn_id": current_turn(), "lead": {"member": plan.lead.id}}
        yield {"type": "member", "model": plan.lead.id, "stage": plan.stage}

        prepared = list(messages)
        if plan.helpers:
            # Helpers cost the same as a shadow when they are online: they come out of the same hourly budget.
            plan.helpers = [h for h in plan.helpers if h.local or collab.API_BUDGET.spend()]
        if plan.helpers:
            names = ", ".join(h.label for h in plan.helpers)
            yield {"type": "thought", "text": f"{identity0.NAME} is asking {names} first.\n"}
            result = collab.panel(messages, [h.id for h in plan.helpers], budget_s=25, max_tokens=700)
            record["helpers"] = [{"member": a["member"], "ok": a["ok"], "ms": a["ms"]} for a in result["answers"]]
            good = [a for a in result["answers"] if a["ok"]]
            if good:
                note = {"role": "system", "content": collab.helpers_note(good)}
                last = max((i for i, m in enumerate(prepared) if m.get("role") == "user"), default=len(prepared))
                prepared.insert(last, note)

        started = time.perf_counter()
        parts: List[str] = []
        used = plan.lead.id
        error = ""
        if plan.lead.provider == "self":
            try:
                from identity0.model import client

                for chunk in client.stream_chat(prepared):
                    parts.append(chunk)
                    yield {"type": "text", "text": chunk}
            except Exception as own_error:  # noqa: BLE001 - the teacher takes over
                error = str(own_error)[:300]
                if parts:
                    yield {"type": "reset"}
                    parts.clear()
                fallback = next((m for m in plan.ranked if m.provider != "self"), None)
                if fallback is None:
                    raise ProviderError(f"Big Kahuna's own model failed: {error}") from own_error
                used = fallback.id
        if not parts:
            for event in collab.stream(router, used, prepared, thinking=thinking):
                kind = event.get("type")
                if kind == "text":
                    parts.append(event.get("text", ""))
                    yield event
                elif kind == "thought":
                    yield event
                elif kind == "reset":
                    parts.clear()
                    yield {"type": "reset"}
                elif kind == "provider" and event.get("name"):
                    # The router fell back to another provider: credit the member that really answers.
                    name = str(event["name"])
                    if not used.startswith(name + ":"):
                        model = str(event.get("model") or "")
                        known = next((m.id for m in pool if m.provider == name and (not model or m.model == model)), None)
                        used = known or members_module.member_id(name, model)
                        yield {"type": "member", "model": used, "stage": plan.stage}
                elif kind == "done":
                    error = str(event.get("error") or "")
        text = "".join(parts)
        ms = (time.perf_counter() - started) * 1000
        if not text.strip():
            _quietly(experience.lead_done, record, used, "", ms, False, error or "no answer")
            _quietly(experience.write, record)
            failure = ProviderError(error or "Big Kahuna's members gave no answer.")
            # When the router behind the lead already tried every provider, say so: the outer chain stops too.
            # (An empty answer is different: another provider may still answer, so the outer chain carries on.)
            failure.chain_exhausted = error.startswith(("Every available provider failed",  # type: ignore[attr-defined]
                                                        "No chat provider is available"))
            raise failure
        # Everything below is bookkeeping: the answer has streamed, so nothing here may fail the turn.
        _quietly(experience.lead_done, record, used, text, ms, True)
        _quietly(self._after, record, plan, messages, text)
        if record.get("turn_id"):
            from identity0 import companion

            _quietly(companion.after_answer, record, plan)

    # --- after the answer --------------------------------------------------------------------

    def _after(self, record: Dict[str, Any], plan: Plan, messages: List[Dict[str, Any]], text: str) -> None:
        shadow = plan.shadow
        if shadow is None or plan.tool_step or "<tool_call>" in text or shadow.id == record["lead"]["member"]:
            experience.write(record)
            return
        if not shadow.local and not collab.API_BUDGET.spend():
            experience.write(record)
            return

        def run() -> None:
            with collab.guard():
                answer = collab.complete(shadow.id, messages, max_tokens=1500, temperature=0.3, timeout=120)
                try:
                    experience.shadow_done(record, answer)
                except Exception as error:  # noqa: BLE001
                    _LOG.warning("identity0 shadow bookkeeping failed: %s", error)

        threading.Thread(target=run, name="kahuna-shadow", daemon=True).start()


def _quietly(work: Any, *args: Any, **kwargs: Any) -> Any:
    """Run bookkeeping that must never cost a turn (a full disk, a locked file, a bug in a counter)."""
    try:
        return work(*args, **kwargs)
    except Exception as error:  # noqa: BLE001
        _LOG.warning("identity0 bookkeeping failed in %s: %s", getattr(work, "__name__", work), error)
        return None


def status(router: Any) -> Dict[str, Any]:
    """What the Big Kahuna tab and ``kahuna_status`` show: members, stages, the last plan."""
    pool = members_module.available(router) if router is not None else []
    own = any(m.provider == "self" for m in pool)
    try:
        import nyx_core

        domains = list(nyx_core.DOMAINS)
    except Exception:  # noqa: BLE001
        domains = ["chat"]
    leads = {}
    for domain in domains:
        ranked = competence.rank(domain, pool) if pool else []
        leads[domain] = {"stage": competence.stage(domain, own), "lead": ranked[0].id if ranked else None}
    provider = getattr(router, "providers", {}).get(identity0.PROVIDER_ID) if router is not None else None
    last = getattr(provider, "last_plan", None)
    return {
        "name": identity0.NAME, "codename": identity0.CODENAME, "version": identity0.VERSION,
        "settings": _settings(), "available": bool(provider and provider.is_available()),
        "members": [m.as_dict() for m in pool], "domains": leads,
        "last_plan": None if last is None else {"domain": last.domain, "stage": last.stage, "lead": last.lead.id,
                                                "protocol": last.protocol, "difficulty": round(last.difficulty, 2),
                                                "speed": last.speed,
                                                "shadow": last.shadow.id if last.shadow else None,
                                                "helpers": [h.id for h in last.helpers]},
        "experiences": experience.stats(),
        "budgets": {"api_left": collab.API_BUDGET.left(), "judge_left": collab.JUDGE_BUDGET.left()},
    }
