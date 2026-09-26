"""Prompt optimizer: two agents that read and refine what the owner typed before the main model sees it.

The owner asked for "a complex super AI algorithm that takes in user text,
complexifies and makes it much better to read for the AI… both on and offline",
with a "use sensor" so simple things stay simple and big tasks are only lightly
touched, and with the main model reading the original *and* the optimized text so
nothing is lost. So a turn with the optimizer on is a three-agent operation:

1. **Sensor** (always local, instant) decides ``keep`` / ``expand`` / ``polish``:
   "what time is it" or "open notepad" → keep, untouched; "make this all" or
   "build me a site" → expand into a clear brief; a long, detailed request →
   polish (structure only; every specific kept verbatim). It learns from 👎 on
   optimized turns and becomes more conservative where rewrites went wrong.
2. **Optimizer** writes the refined request: the fast online model when it can,
   a local Ollama model next, and deterministic rules fully offline.
3. **Checker** (local) verifies every quote, number, path, URL, name and
   negation ("don't…") survived and the length fits the mode; a failed online
   rewrite falls back to the rules, and a failed rules rewrite leaves the
   original alone.

The main model then receives an **overlay**: the owner's original words, and
below them the optimized brief, with an explicit "if they conflict, the original
wins". The transcript always stores what the owner actually typed.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from paths import data_path

MODES = ("keep", "expand", "polish")

DEFAULT_SETTINGS: Dict[str, Any] = {
    "enabled": True,
    "online": True,          # use a model when one is reachable (else rules only)
    "strength": 2,           # 1 gentle · 2 balanced · 3 thorough
    "show_in_chat": True,
    "expand_short_tasks": True,
    "polish_long_requests": True,
    "online_timeout_seconds": 8,
}

_BIG_VERBS = {
    "build": "make", "make": "make", "create": "make", "develop": "make", "implement": "make", "setup": "make",
    "automate": "make", "code": "make", "program": "make", "generate": "make", "add": "make",
    "design": "design", "redesign": "design", "style": "design", "layout": "design",
    "write": "write", "draft": "write", "compose": "write", "rewrite": "write", "email": "write",
    "research": "research", "analyze": "research", "analyse": "research", "compare": "research", "investigate": "research",
    "evaluate": "research", "review": "research", "audit": "research",
    "fix": "fix", "improve": "fix", "optimize": "fix", "optimise": "fix", "refactor": "fix", "debug": "fix",
    "clean": "fix", "upgrade": "fix", "update": "fix", "speed": "fix",
    "plan": "plan", "organize": "plan", "organise": "plan", "prepare": "plan", "schedule": "plan", "outline": "plan",
    "explain": "explain", "teach": "explain", "summarize": "explain", "summarise": "explain", "describe": "explain",
}
_VAGUE = {"this", "that", "it", "these", "those", "all", "everything", "stuff", "things", "whatever", "something",
          "better", "nicer", "good", "nice", "cool", "proper", "properly", "etc"}
_SIMPLE = re.compile(
    r"^(?:hi|hey|hello|yo|thanks|thank you|ok|okay|yes|no|yep|nope|sure|cool|great|good (?:morning|night|evening)|bye)\b[\s!.?]*$"
    r"|^(?:open|launch|start|close|play|pause|stop|skip|mute|unmute|lock|set|turn|show|find|search|google|call|text|remind)\b"
    r"|^(?:what(?:'s| is)? (?:the )?(?:time|date|weather)|how (?:much|many|old|far|long)|who (?:is|was)|when (?:is|was|did)"
    r"|where (?:is|are)|define|convert|calculate)\b", re.I)
_STOP = set("""a an and are as at be but by can could did do does for from had has have he her his i if in into is it its
just me my of on or our she so than that the their them then there these they this to too up us was we were what when
where which who why will with would you your please want need like really basically make sure also about some any""".split())
_NEGATION = re.compile(r"\b(?:don'?t|do not|never|no|not|without|avoid|except|stop|shouldn'?t|mustn'?t|can'?t)\b", re.I)
_FILLER = re.compile(r"\b(?:basically|literally|pretty much|kind of|sort of|i mean|you know|like,)\s*", re.I)

_DELIVERABLES = {
    "make": "Produce a working result (files, code or configuration), not just a description; say where things were saved and how to use them.",
    "design": "Show the design itself — layout, components, colours, states — and explain the key choices briefly.",
    "write": "Write the finished text in the tone the owner would expect, with no placeholders.",
    "research": "Gather current facts, compare the options, and finish with a clear recommendation and sources.",
    "fix": "Find the cause, make the change, verify it works, and list what changed.",
    "plan": "Give an ordered plan with concrete steps and the very first action to take.",
    "explain": "Explain clearly from the basics up with one example, as briefly as the topic allows.",
}

ModelFn = Callable[..., Tuple[str, str]]


@dataclass
class Assessment:
    mode: str
    reason: str
    words: int
    big_verbs: List[str] = field(default_factory=list)
    vague: List[str] = field(default_factory=list)
    specifics: int = 0
    category: str = ""
    bucket: str = ""


@dataclass
class Optimization:
    mode: str
    original: str
    optimized: str
    model_text: str
    engine: str = "none"
    reason: str = ""
    checks: Dict[str, Any] = field(default_factory=dict)
    original_tokens: int = 0
    optimized_tokens: int = 0
    ms: int = 0
    assumptions: List[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.mode != "keep" and self.model_text != self.original

    def event(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("model_text", None)
        data["changed"] = self.changed
        return data


def tokens(text: str) -> int:
    return max(1, math.ceil(len(text or "") / 4))


def _words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’-]*", text or "")


def protected_spans(text: str) -> List[str]:
    """Things a rewrite must keep verbatim."""
    spans: List[str] = []
    spans += re.findall(r"```.*?```", text, re.S)
    spans += re.findall(r"`[^`\n]+`", text)
    spans += [m.group(0) for m in re.finditer(r"\"[^\"\n]{2,120}\"|“[^”\n]{2,120}”", text)]
    spans += re.findall(r"https?://\S+", text)
    spans += re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    spans += re.findall(r"(?:[A-Za-z]:)?(?:[\w.-]+[\\/])+[\w.-]+|\b[\w-]+\.(?:py|js|ts|tsx|jsx|json|md|txt|html|css|csv|pdf|docx|xlsx|png|jpg|svg|bat|ps1|sh|yaml|yml|toml)\b", text)
    spans += re.findall(r"\b\d+(?:[.,:]\d+)*\s*(?:%|px|pt|ms|s|sec|seconds?|min|minutes?|h|hours?|days?|gb|mb|kb|k|x|°c|°f|usd|\$)?(?!\w)", text, re.I)
    spans += re.findall(r"\$\d+(?:[.,]\d+)?", text)
    names = re.findall(r"\b(?:[A-Z][a-z0-9]+(?:\s+[A-Z][a-z0-9]+)+|[A-Z]{2,}[A-Za-z0-9]*)\b", text)
    spans += [n for n in names if n.lower() not in _STOP]
    seen, out = set(), []
    for span in (s.strip() for s in spans):
        if span and span.lower() not in seen and len(span) < 400:
            seen.add(span.lower())
            out.append(span)
    return out


def assess(text: str, settings: Optional[Dict[str, Any]] = None, penalties: Optional[Dict[str, List[int]]] = None) -> Assessment:
    """The use sensor. Pure and instant."""
    settings = {**DEFAULT_SETTINGS, **(settings or {})}
    clean = (text or "").strip()
    words = _words(clean)
    lower = [w.lower().strip("'’") for w in words]
    count = len(words)
    big = [w for w in lower if w in _BIG_VERBS]
    if re.search(r"\bset\s*up\b", clean, re.I):
        big.append("setup")
    vague = [w for w in lower if w in _VAGUE]
    specifics = len(protected_spans(clean))
    category = _BIG_VERBS.get(big[0], "") if big else ""
    bucket = f"{'s' if count <= 12 else 'm' if count <= 60 else 'l'}:{bool(big)}:{bool(vague)}"
    strength = int(settings.get("strength", 2))

    def decided(mode: str, reason: str) -> Assessment:
        if mode != "keep" and penalties:
            good, bad = penalties.get(f"{mode}|{bucket}", [0, 0])
            if bad >= 3 and bad > good:
                return Assessment("keep", f"rewrites like this were marked unhelpful before ({bad}×)", count, big, vague, specifics, category, bucket)
        return Assessment(mode, reason, count, big, vague, specifics, category, bucket)

    if not clean or clean.startswith(("/", "[fresh]")):
        return decided("keep", "command or empty")
    if "```" in clean and count < 40:
        return decided("keep", "mostly code")
    if _SIMPLE.search(clean) and count <= 14 and not (big and vague):
        return decided("keep", "a simple, direct request")
    if clean.endswith("?") and count <= 16 and not big:
        return decided("keep", "a short question")
    if count >= 90 or (specifics >= 6 and count >= 40):
        if not settings.get("polish_long_requests", True) or strength == 1 and count < 200:
            return decided("keep", "long and specific already")
        return decided("polish", "long request: structure it, keep every specific")
    if big and settings.get("expand_short_tasks", True):
        if count <= 12 or (vague and count <= 25):
            return decided("expand", "a short or vague request for a big task")
        if count <= 45 and strength >= 2:
            return decided("expand", "a task that benefits from a clear brief")
    if big and count > 45 and settings.get("polish_long_requests", True) and len(_sentences(clean)) >= 3:
        return decided("polish", "a detailed request: structure it, keep every specific")
    if count <= 6:
        return decided("keep", "short and clear")
    return decided("keep", "already clear")


# ---------------------------------------------------------------------------
# Offline optimizer (rules)
# ---------------------------------------------------------------------------


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def rules_optimize(text: str, assessment: Assessment, context: Dict[str, Any]) -> str:
    original = re.sub(r"[ \t]+", " ", text.strip())
    if assessment.mode == "expand":
        lines = [f"Goal: {original}"]
        topic = str(context.get("recent_topic") or "").strip()
        if assessment.vague and topic:
            lines.append(f"“{assessment.vague[0]}” most likely refers to the recent conversation: {topic[:220]}")
        if context.get("attachments"):
            lines.append("Use the attached: " + ", ".join(context["attachments"][:6]))
        if context.get("tab"):
            lines.append(f"The owner is on the {context['tab']} tab.")
        lines.append("A complete result:")
        lines.append(f"- {_DELIVERABLES.get(assessment.category, _DELIVERABLES['make'])}")
        lines.append("- Do the whole task end to end; ask one short question only if something essential is missing.")
        spans = protected_spans(original)
        if spans:
            lines.append("Keep exactly: " + "; ".join(spans[:12]))
        if context.get("style"):
            lines.append(f"Answer style: {context['style']}")
        return "\n".join(lines)
    # polish: goal, requirements (verbatim), details (verbatim), filler removed only between words
    sentences = [_FILLER.sub("", s).strip() for s in _sentences(original)]
    sentences = [s[0].upper() + s[1:] if s and s[0].islower() else s for s in sentences if s]
    if not sentences:
        return original
    requirement = re.compile(r"\b(must|should|need|needs|make sure|ensure|don'?t|do not|never|only|always|also|include|add|allow|without)\b", re.I)
    goal = sentences[0]
    reqs = [s for s in sentences[1:] if requirement.search(s)]
    details = [s for s in sentences[1:] if s not in reqs]
    lines = [f"Goal: {goal}"]
    if reqs:
        lines.append("Requirements:")
        lines += [f"- {s}" for s in reqs]
    if details:
        lines.append("Details:")
        lines += [f"- {s}" for s in details]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Checker
# ---------------------------------------------------------------------------


def _stem(word: str) -> str:
    return word.lower()[:5]


def check(original: str, optimized: str, mode: str) -> Dict[str, Any]:
    notes: List[str] = []
    lower_opt = optimized.lower()
    missing = [s for s in protected_spans(original) if s.lower() not in lower_opt]
    if missing:
        notes.append("lost: " + "; ".join(missing[:5]))
    content = {w.lower() for w in _words(original) if len(w) >= 4 and w.lower() not in _STOP}
    opt_stems = {_stem(w) for w in _words(optimized)}
    recall = (sum(1 for w in content if _stem(w) in opt_stems) / len(content)) if content else 1.0
    # Polish must keep nearly every word. An expansion may paraphrase ("better" → "improve"), and the
    # original always travels with it in the overlay, so a 2–3 word request is not held to recall at all.
    need = 0.85 if mode == "polish" else (0.0 if len(content) <= 3 else 0.5)
    if recall < need:
        notes.append(f"only {recall:.0%} of the owner's key words kept")
    negations_before = len(_NEGATION.findall(original))
    if negations_before and len(_NEGATION.findall(optimized)) < negations_before:
        notes.append("a 'don't / never / without' was dropped")
    words_before, words_after = len(_words(original)), len(_words(optimized))
    limit = max(150, words_before * 8) if mode == "expand" else int(words_before * 1.25) + 25
    if words_after > limit:
        notes.append(f"too long ({words_after} words, limit {limit})")
    if re.match(r"^\s*(?:sure|certainly|here(?:'s| is)|i (?:will|'ll|can))\b", optimized, re.I):
        notes.append("it started answering instead of restating the request")
    return {"passed": not notes, "notes": notes, "recall": round(recall, 3), "missing": missing[:10]}


# ---------------------------------------------------------------------------
# The optimizer
# ---------------------------------------------------------------------------


def online_prompt(text: str, assessment: Assessment, context: Dict[str, Any], strength: int) -> str:
    budget = ("at most about 140 words" if assessment.mode == "expand" else "no longer than the original")
    ctx = "\n".join(f"- {k}: {v}" for k, v in context.items() if v) or "- (none)"
    return (
        "Rewrite the owner's message into the clearest, most token-efficient instruction for another AI assistant.\n"
        f"Mode: {assessment.mode} ({assessment.reason}). Strength {strength}/3. Length: {budget}.\n"
        "Rules: never answer the request; never add requirements the owner did not state or clearly imply; keep every "
        "name, number, quote, file, URL and every 'don't/never/only' exactly; fix typos; resolve vague words like "
        "'this' or 'it' from the context when it is clear, otherwise leave them; for expand, state the goal, what a "
        "finished result includes, and constraints; for polish, restructure into Goal / Requirements / Details without "
        "losing anything.\n\n"
        f"Context:\n{ctx}\n\nOwner's message:\n<<<\n{text}\n>>>\n\n"
        'Reply with JSON only: {"optimized": "...", "assumptions": ["anything you inferred"]}'
    )


def overlay(original: str, optimized: str) -> str:
    return (
        f"{original}\n\n"
        "<optimized_request author=\"Nyx prompt optimizer\">\n"
        f"{optimized}\n"
        "</optimized_request>\n"
        "(The text above the tag is exactly what the owner typed; the tag is a clarified version. "
        "Follow both — if they ever conflict, the owner's own words win.)"
    )


class PromptOptimizer:
    def __init__(self, *, settings_path: Any = None, model_fn: Optional[ModelFn] = None) -> None:
        self._settings_path = settings_path
        self._model_fn = model_fn
        self._lock = threading.RLock()
        self._settings: Optional[Dict[str, Any]] = None
        self._recent: "OrderedDict[str, Tuple[str, str]]" = OrderedDict()
        self.stats = {"turns": 0, "kept": 0, "expanded": 0, "polished": 0, "fell_back": 0, "tokens_added": 0}

    # --- settings & learning ------------------------------------------------------

    def _path(self):
        return self._settings_path or data_path("prompt_optimizer.json")

    def _load(self) -> Dict[str, Any]:
        if self._settings is None:
            try:
                saved = json.loads(self._path().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = {}
            self._settings = {**DEFAULT_SETTINGS, **{k: v for k, v in saved.items() if k in DEFAULT_SETTINGS},
                              "penalties": saved.get("penalties", {}), "stats": saved.get("stats", {})}
            self.stats.update({k: int(v) for k, v in self._settings["stats"].items() if k in self.stats})
        return self._settings

    def _save(self) -> None:
        data = dict(self._load())
        data["stats"] = dict(self.stats)
        self._path().parent.mkdir(parents=True, exist_ok=True)
        self._path().write_text(json.dumps(data, indent=1), encoding="utf-8")

    def settings(self) -> Dict[str, Any]:
        with self._lock:
            data = self._load()
            return {**{k: data[k] for k in DEFAULT_SETTINGS}, "stats": dict(self.stats)}

    def update_settings(self, **changes: Any) -> Dict[str, Any]:
        with self._lock:
            data = self._load()
            for key, value in changes.items():
                if key not in DEFAULT_SETTINGS or value is None:
                    continue
                default = DEFAULT_SETTINGS[key]
                if isinstance(default, bool):
                    data[key] = bool(value)
                elif isinstance(default, int):
                    data[key] = int(max(1, min(3, int(value)))) if key == "strength" else int(max(2, min(30, int(value))))
            self._save()
        return self.settings()

    def feedback(self, turn_id: str, rating: int) -> bool:
        """👍/👎 on a turn whose request was optimized teaches the sensor."""
        with self._lock:
            entry = self._recent.get(turn_id)
            if not entry:
                return False
            mode, bucket = entry
            penalties = self._load().setdefault("penalties", {})
            good, bad = penalties.get(f"{mode}|{bucket}", [0, 0])
            penalties[f"{mode}|{bucket}"] = [good + (rating > 0), bad + (rating < 0)]
            self._save()
            return True

    # --- the pipeline -----------------------------------------------------------------

    def optimize(self, text: str, context: Optional[Dict[str, Any]] = None, turn_id: str = "",
                 force: bool = False) -> Optimization:
        started = time.perf_counter()
        context = {k: v for k, v in (context or {}).items() if v}
        with self._lock:
            settings = dict(self._load())
        result = Optimization(mode="keep", original=text, optimized=text, model_text=text, original_tokens=tokens(text))
        if not settings.get("enabled") and not force:
            result.reason = "optimizer off"
            return self._done(result, started, None, count=False)
        assessment = assess(text, settings, settings.get("penalties"))
        result.mode, result.reason = assessment.mode, assessment.reason
        if assessment.mode == "keep":
            return self._done(result, started, assessment)

        candidate, engine, assumptions = "", "rules", []
        if settings.get("online", True):
            candidate, engine, assumptions = self._online(text, assessment, context, settings)
        checks: Dict[str, Any] = {}
        if candidate:
            checks = check(text, candidate, assessment.mode)
            if not checks["passed"]:
                self.stats["fell_back"] += 1
                result.assumptions = [f"online rewrite rejected: {'; '.join(checks['notes'])}"]
                candidate = ""
        if not candidate:
            engine = "rules"
            candidate = rules_optimize(text, assessment, context)
            checks = check(text, candidate, assessment.mode)
            assumptions = []
        if not checks["passed"]:
            result.mode, result.reason = "keep", "the rewrite would have lost something: " + "; ".join(checks["notes"])
            result.checks = checks
            return self._done(result, started, assessment)
        result.optimized, result.engine, result.checks = candidate, engine, checks
        result.assumptions += assumptions
        result.model_text = overlay(text, candidate)
        return self._done(result, started, assessment, turn_id=turn_id)

    def _online(self, text: str, assessment: Assessment, context: Dict[str, Any], settings: Dict[str, Any]) -> Tuple[str, str, List[str]]:
        prompt = online_prompt(text, assessment, context, int(settings.get("strength", 2)))
        system = "You refine requests for another AI. JSON only."
        try:
            reply, engine = (self._model_fn or _default_model_fn)(prompt, system=system,
                                                                   timeout=float(settings.get("online_timeout_seconds", 8)))
        except Exception:  # noqa: BLE001 - offline or slow: the rules take over
            return "", "rules", []
        body = reply or ""
        fence = re.search(r"```(?:json)?\s*(.+?)```", body, re.S)
        body = fence.group(1) if fence else body
        start, end = body.find("{"), body.rfind("}")
        try:
            data = json.loads(body[start:end + 1]) if start != -1 and end > start else {}
        except ValueError:
            data = {}
        optimized = str(data.get("optimized") or "").strip()
        assumptions = [str(a)[:200] for a in (data.get("assumptions") or []) if str(a).strip()][:5]
        return optimized, engine, assumptions

    def _done(self, result: Optimization, started: float, assessment: Optional[Assessment], turn_id: str = "",
              count: bool = True) -> Optimization:
        result.ms = int((time.perf_counter() - started) * 1000)
        result.optimized_tokens = tokens(result.model_text)
        if count:
            with self._lock:
                self.stats["turns"] += 1
                key = {"keep": "kept", "expand": "expanded", "polish": "polished"}[result.mode]
                self.stats[key] += 1
                self.stats["tokens_added"] += max(0, result.optimized_tokens - result.original_tokens)
                if turn_id and assessment is not None and result.changed:
                    self._recent[turn_id] = (result.mode, assessment.bucket)
                    while len(self._recent) > 300:
                        self._recent.popitem(last=False)
                if self.stats["turns"] % 10 == 0 or result.changed:
                    try:
                        self._save()
                    except OSError:
                        pass
        return result


def _default_model_fn(prompt: str, *, system: str = "", timeout: float = 8.0) -> Tuple[str, str]:
    """Fast online models at once (first answer wins), then a local Ollama model; raises when none answers.

    One after another, a single slow free tier ate the whole budget — a simple
    request waited 10 s before the offline rules took over (2026-09-15).
    """
    import model_hub
    from mini_model import race

    reply = race([("gemini", ""), ("groq", ""), ("nvidia", "")], prompt, system=system,
                 budget_seconds=timeout, max_tokens=700)
    if reply is not None:
        return reply.text, f"{reply.provider} · {reply.model}"
    try:
        if model_hub.is_configured("ollama"):
            model = model_hub.default_model("ollama", "text")
            reply = model_hub.complete("ollama", model, prompt, system=system, max_tokens=700, timeout=timeout * 2)
            return reply.text, f"ollama · {model} (offline)"
    except Exception as error:  # noqa: BLE001
        raise RuntimeError(str(error)[:120]) from error
    raise RuntimeError("no model answered in time")


OPTIMIZER = PromptOptimizer()
