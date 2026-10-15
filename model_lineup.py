"""Nyx's own model lineup: Pico, Monolith, Crescendo and Zencode, plus how hard each one works (effort).

The owner (Fixer Upper S14, S5): "For our main agents let's do a similar naming to Claude, Gemini, and ChatGPT.
Something that shows how powerful each one is." Three levels, each with an Auto button and then its models:

* **Pico** — lighter work, for phones and lesser laptops: Pulse, Echo, Harmonic, Resonance, Overtone.
* **Monolith** — general work, the middle level: Argon, Boron, Carbon, Silicon, Xenon.
* **Crescendo** — power-hungry work: Photon, Azure, Radiance, Nexus, Abyss, Eclipse.
* **Zencode** — the code version: Bit, Byte, Decimal, Giga, Exa.

Effort is the second dial ("auto effort for how hard the selected model works"): Low (Jev) → Mid → Normal → High →
Higher → Super → Aleph. Aleph (ℵ, the maths symbol for the size of infinity) is the super max the owner asked to be
named after something in mathematics.

Why this is a module of data and one ``resolve`` function, not a set of new providers: the names are what the owner
picks, but the work is still done by the router, Big Kahuna and the quick path that already exist. A lineup name
turns into a ``TurnPlan`` — who answers first, whether the quick path is used, how many tool steps, whether second
opinions run — and ``turn_runner`` applies it. So a name is never decoration: every one changes what a turn does,
and every plan can be read back in plain words (``TurnPlan.describe``).

The picker sends a lineup id through the chat's existing model value ("carbon" instead of "gemini"), so the chat
screen needs no change to use it, and ``/api/models/switch`` remembers it like any other pick.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from paths import data_path

# ---------------------------------------------------------------------------
# The lineup itself — the owner's names, in his order
# ---------------------------------------------------------------------------

#: Every size a model can be. Crescendo is the only family with an Ultra Max.
SIZES: Tuple[Tuple[str, str], ...] = (
    ("small", "Small"),
    ("normal", "Normal"),
    ("middle", "Middle"),
    ("max", "Max"),
    ("ultra", "Ultra Max"),
    ("super", "Super Max"),
)
_SIZE_LABEL = dict(SIZES)


@dataclass(frozen=True)
class LineupModel:
    """One named model: what the owner sees, and its place in its family."""

    id: str
    name: str
    size: str
    tagline: str

    def view(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "size": self.size, "size_label": _SIZE_LABEL[self.size],
                "tagline": self.tagline, "runs_on": runs_on(self.id)}


@dataclass(frozen=True)
class Family:
    """A level of the lineup (Pico, Monolith, Crescendo) or a specialist family (Zencode)."""

    id: str
    name: str
    used_for: str
    blurb: str
    models: Tuple[LineupModel, ...]
    #: Places in the app that also use this family, shown next to it ("where each is used").
    also_used_in: Tuple[str, ...] = ()
    #: True for the three levels shown as Pico / Monolith / Crescendo; False for a specialist like Zencode.
    level: bool = True

    def view(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "used_for": self.used_for, "blurb": self.blurb,
                "also_used_in": list(self.also_used_in), "level": self.level,
                "models": [m.view() for m in self.models]}


def _m(model_id: str, name: str, size: str, tagline: str) -> LineupModel:
    return LineupModel(model_id, name, size, tagline)


FAMILIES: Tuple[Family, ...] = (
    Family("pico", "Pico", "Lighter work",
           "Light and quick, for phones and lesser laptops. Answers from the lightest model that runs here.",
           (_m("pulse", "Pulse", "small", "Quick responses"),
            _m("echo", "Echo", "normal", "Everyday use"),
            _m("harmonic", "Harmonic", "middle", "Deeper reasoning"),
            _m("resonance", "Resonance", "max", "Advanced capabilities"),
            _m("overtone", "Overtone", "super", "Flagship"))),
    Family("monolith", "Monolith", "General",
           "General focus, between Pico and Crescendo. Big Kahuna leads and picks the best model for each request.",
           (_m("argon", "Argon", "small", "Quick, general answers"),
            _m("boron", "Boron", "normal", "Everyday use"),
            _m("carbon", "Carbon", "middle", "Deeper reasoning"),
            _m("silicon", "Silicon", "max", "Advanced reasoning"),
            _m("xenon", "Xenon", "super", "Flagship general model")),
           also_used_in=("3D Build", "Design", "World")),
    Family("crescendo", "Crescendo", "Power-hungry work",
           "The heavyweights: stronger models first, second opinions on hard requests, more steps and helpers.",
           (_m("photon", "Photon", "small", "Lightweight, fast responses"),
            _m("azure", "Azure", "normal", "Everyday use"),
            _m("radiance", "Radiance", "middle", "Deeper reasoning and stronger capabilities"),
            _m("nexus", "Nexus", "max", "Advanced, intensive reasoning"),
            _m("abyss", "Abyss", "ultra", "Super-adaptive intelligence that adjusts to each task"),
            _m("eclipse", "Eclipse", "super", "Flagship model with the strongest overall capabilities"))),
    Family("zencode", "Zencode", "Coding",
           "The code version: the model you set for Code in Keys & Models, with the tools always on.",
           (_m("bit", "Bit", "small", "Quick fixes and snippets"),
            _m("byte", "Byte", "normal", "Everyday coding"),
            _m("decimal", "Decimal", "middle", "Bigger changes, more careful"),
            _m("giga", "Giga", "max", "Large features and refactors"),
            _m("exa", "Exa", "super", "Flagship coder for the hardest jobs")),
           level=False),
)

_BY_FAMILY: Dict[str, Family] = {f.id: f for f in FAMILIES}
_BY_MODEL: Dict[str, Tuple[Family, LineupModel]] = {m.id: (f, m) for f in FAMILIES for m in f.models}

#: The "main model" the collapsed picker shows for Auto: Big Kahuna is the brain that routes everything.
MAIN_MODEL_NAME = "Big Kahuna"


# ---------------------------------------------------------------------------
# Effort — how hard the picked model works
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Effort:
    """One stop on the effort slider, and the switches it sets on a turn.

    ``None`` means "leave it as the chat mode and Settings say", so Normal changes nothing about today's
    behaviour: the slider can only add speed or depth on top of what already works.
    """

    id: str
    name: str
    summary: str
    #: "fast" always takes the quick path, "full" always takes the tool pipeline, "auto" decides per message.
    speed: str = "auto"
    #: Show the model's own thinking (also costs time); None keeps the owner's Settings choice.
    thinking: Optional[bool] = None
    #: Run the prompt optimizer before the model reads the message; None keeps what the chat mode does.
    optimizer: Optional[bool] = None
    #: Second opinions: "off", "heavy" (only on hard requests), "always"; None keeps the chat mode's choice.
    consult: Optional[str] = None
    #: Most tool steps one turn may take; None keeps the chat mode's number.
    max_steps: Optional[int] = None
    #: Try the stronger version of a model first in the tool loop (Gemini's smart model).
    smart: bool = True
    #: Low: a desktop command is done by Ultra Fast (Jev's pattern) without any model.
    ultrafast: bool = False
    #: Aleph: a Normal chat is upgraded to Auto, which may hand a many-part job to a swarm.
    upgrade_mode: Optional[str] = None

    def view(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "summary": self.summary}


EFFORTS: Tuple[Effort, ...] = (
    Effort("low", "Low", "Jev speed: desktop commands with no model, everything else a short quick answer",
           speed="fast", thinking=False, optimizer=False, consult="off", max_steps=6, smart=False, ultrafast=True),
    Effort("mid", "Mid", "The normal model told to answer fast and keep it light",
           speed="auto", thinking=False, optimizer=False, consult="off", max_steps=12, smart=False),
    Effort("normal", "Normal", "The default: quick when it can be, tools when it needs them"),
    Effort("high", "High", "A step above: always the full toolset, more steps, second opinions on hard requests",
           speed="full", thinking=True, consult="heavy", max_steps=32),
    Effort("higher", "Higher", "More than High: the request is refined first and it can take longer",
           speed="full", thinking=True, optimizer=True, consult="heavy", max_steps=40),
    Effort("super", "Super", "Almost max effort: everything running heavy, second opinions every time",
           speed="full", thinking=True, optimizer=True, consult="always", max_steps=48),
    Effort("aleph", "Aleph", "ℵ, the absolute limit for extreme loads: Auto may split the job across a swarm",
           speed="full", thinking=True, optimizer=True, consult="always", max_steps=64, upgrade_mode="auto"),
)
_BY_EFFORT: Dict[str, Effort] = {e.id: e for e in EFFORTS}
AUTO = "auto"

#: What effort a model works at when the slider is on Auto: its size says how hard it was meant to work.
DEFAULT_EFFORT_FOR_SIZE: Dict[str, str] = {
    "small": "low",
    "normal": "normal",
    "middle": "high",
    "max": "higher",
    "ultra": AUTO,      # Abyss "adjusts to each task": effort is picked per message
    "super": "super",
}

#: The real model behind each Monolith and Crescendo name, best first. A turn uses the first one whose provider can
#: answer right now (key set, not paid-only in free mode, online); with none, Big Kahuna answers and routes it. So
#: Argon is a small fast model and Eclipse the strongest one there is, not the same brain with a different name.
#: An empty list means "Big Kahuna on purpose" (Abyss adjusts to each task, so the router picks per message).
BACKING: Dict[str, Tuple[Tuple[str, str], ...]] = {
    # Monolith: general work, balanced between speed and depth.
    "argon": (("groq", "llama-3.1-8b-instant"), ("gemini", "gemini-2.5-flash-lite")),
    "boron": (("gemini", "gemini-2.5-flash"), ("groq", "llama-3.3-70b-versatile")),
    "carbon": (("gemini", "gemini-3.5-flash"), ("deepseek", "deepseek-chat"), ("claude", "claude-haiku-5-5")),
    "silicon": (("claude", "claude-sonnet-5-5"), ("gemini", "gemini-2.5-pro"), ("deepseek", "deepseek-reasoner")),
    "xenon": (("claude", "claude-opus-5-5"), ("gemini", "gemini-2.5-pro"), ("openai", "gpt-4o")),
    # Crescendo: the heavyweights. Each size sits a step above Monolith's.
    "photon": (("gemini", "gemini-2.5-flash"), ("groq", "llama-3.3-70b-versatile")),
    "azure": (("gemini", "gemini-3.5-flash"), ("claude", "claude-haiku-5-5"), ("deepseek", "deepseek-chat")),
    "radiance": (("claude", "claude-sonnet-5-5"), ("gemini", "gemini-2.5-pro")),
    "nexus": (("claude", "claude-opus-5-5"), ("deepseek", "deepseek-reasoner"), ("gemini", "gemini-2.5-pro")),
    "abyss": (),
    "eclipse": (("claude", "claude-opus-5-5"), ("gemini", "gemini-2.5-pro"), ("openai", "gpt-4o")),
}

#: Pico's quick answers when no small local model is installed: the fastest cloud models.
PICO_CLOUD: Tuple[Tuple[str, str], ...] = (("groq", "llama-3.1-8b-instant"), ("gemini", "gemini-2.5-flash-lite"))

_PROVIDER_LABEL = {"groq": "Groq", "gemini": "Gemini", "deepseek": "DeepSeek", "claude": "Claude", "openai": "OpenAI",
                   "ollama": "Ollama"}


def runs_on(model_id: str) -> str:
    """What a name runs on, in words, for the picker ("Gemini gemini-2.5-flash, else Groq …")."""
    fam_model = _BY_MODEL.get(str(model_id or "").lower())
    if fam_model is None:
        return ""
    fam, _model = fam_model
    if fam.id == "pico":
        return "The lightest local model that fits this PC, else a fast cloud model"
    if fam.id == "zencode":
        return "The model set for Code in Keys & Models"
    chain = BACKING.get(model_id, ())
    if not chain:
        return "Big Kahuna picks the model for each message"
    first = ", else ".join(f"{_PROVIDER_LABEL.get(p, p)} {m}" for p, m in chain[:2])
    return f"{first} (Big Kahuna if none is set up)"


#: The biggest local model (GB on disk) each Pico size may load. Overtone (0) takes whatever fits this machine.
PICO_LOCAL_GB: Dict[str, float] = {"small": 2.0, "normal": 3.5, "middle": 6.0, "max": 10.0, "super": 0.0}


# ---------------------------------------------------------------------------
# The plan a turn follows
# ---------------------------------------------------------------------------


@dataclass
class TurnPlan:
    """Everything a lineup pick changes about one turn. ``turn_runner`` reads these and nothing else."""

    model_id: str = ""
    family_id: str = ""
    label: str = ""
    effort: str = "normal"
    effort_auto: bool = False
    #: Provider the tool loop tries first (None: the router's own order, Big Kahuna first).
    prefer: Optional[str] = None
    prefer_model: Optional[str] = None
    #: Provider and model the quick path tries first (Pico's light model); None uses ``prefer``.
    fast_prefer: Optional[str] = None
    fast_model: Optional[str] = None
    #: The real models behind the name, best first; ``turn_runner`` takes the first that can answer now and
    #: otherwise keeps ``prefer`` (Big Kahuna).
    candidates: List[Tuple[str, str]] = field(default_factory=list)
    #: Same for the quick path (Pico's cloud fallback).
    fast_candidates: List[Tuple[str, str]] = field(default_factory=list)
    speed: str = "auto"
    thinking: Optional[bool] = None
    optimizer: Optional[bool] = None
    consult: Optional[str] = None
    max_steps: Optional[int] = None
    smart: bool = True
    ultrafast: bool = False
    upgrade_mode: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def describe(self) -> str:
        """The plan in one line of plain words, for the status line and the turn's log."""
        who = self.label or "Auto"
        effort = _BY_EFFORT[self.effort].name if self.effort in _BY_EFFORT else self.effort
        auto = " (auto)" if self.effort_auto else ""
        parts = [f"{who} at {effort} effort{auto}"]
        parts.extend(self.notes)
        return " · ".join(parts)

    def as_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["summary"] = self.describe()
        return data


# ---------------------------------------------------------------------------
# Looking things up
# ---------------------------------------------------------------------------


def find(model_id: str) -> Optional[Tuple[Family, LineupModel]]:
    """The family and model for an id like "carbon" (any case), or None."""
    return _BY_MODEL.get(str(model_id or "").strip().lower())


def family(family_id: str) -> Optional[Family]:
    return _BY_FAMILY.get(str(family_id or "").strip().lower())


def is_lineup_id(text: str) -> bool:
    """True for a model ("carbon") or a family's Auto ("monolith"). Provider names never clash with these."""
    key = str(text or "").strip().lower()
    return key in _BY_MODEL or key in _BY_FAMILY


def effort(effort_id: str) -> Optional[Effort]:
    return _BY_EFFORT.get(str(effort_id or "").strip().lower())


def label(model_id: str) -> str:
    """ "Monolith · Carbon" for a model, "Monolith · Auto" for a family, "" for anything else."""
    key = str(model_id or "").strip().lower()
    found = _BY_MODEL.get(key)
    if found:
        return f"{found[0].name} · {found[1].name}"
    fam = _BY_FAMILY.get(key)
    return f"{fam.name} · Auto" if fam else ""


# ---------------------------------------------------------------------------
# What the owner picked, remembered across restarts
# ---------------------------------------------------------------------------

_lock = threading.Lock()
#: Surfaces that can follow their own pick; "" means "the same as the chat".
SURFACES = ("whatsapp", "voice")


def _path():
    return data_path("model_lineup.json")


def load() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(data: Dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def state() -> Dict[str, Any]:
    """The saved pick, effort and per-surface picks, with defaults filled in."""
    data = load()
    pick = str(data.get("pick") or "").lower()
    chosen_effort = str(data.get("effort") or AUTO).lower()
    surfaces = data.get("surfaces") if isinstance(data.get("surfaces"), dict) else {}
    return {
        "pick": pick if is_lineup_id(pick) else "",
        "effort": chosen_effort if chosen_effort == AUTO or chosen_effort in _BY_EFFORT else AUTO,
        "surfaces": {name: _clean_surface(surfaces.get(name)) for name in SURFACES},
    }


def _clean_surface(value: Any) -> Dict[str, str]:
    value = value if isinstance(value, dict) else {}
    model_id = str(value.get("model") or "").lower()
    effort_id = str(value.get("effort") or "").lower()
    return {"model": model_id if is_lineup_id(model_id) else "",
            "effort": effort_id if effort_id == AUTO or effort_id in _BY_EFFORT else ""}


def save_pick(model_id: str) -> Dict[str, Any]:
    """Remember a lineup pick ("" clears it back to Auto). Raises ValueError for a name that is not in the lineup."""
    key = str(model_id or "").strip().lower()
    if key and not is_lineup_id(key):
        raise ValueError(f"'{model_id}' is not a model in the lineup.")
    with _lock:
        data = load()
        data["pick"] = key
        _save(data)
    return state()


def save_effort(effort_id: str) -> Dict[str, Any]:
    key = str(effort_id or "").strip().lower() or AUTO
    if key != AUTO and key not in _BY_EFFORT:
        raise ValueError(f"'{effort_id}' is not an effort level. Use one of: auto, " + ", ".join(_BY_EFFORT) + ".")
    with _lock:
        data = load()
        data["effort"] = key
        _save(data)
    return state()


def save_surface(surface: str, model_id: str = "", effort_id: str = "") -> Dict[str, Any]:
    """Give WhatsApp or voice its own pick (for example a quick Pico model for texts); blanks follow the chat."""
    name = str(surface or "").strip().lower()
    if name not in SURFACES:
        raise ValueError(f"'{surface}' is not a surface. Use one of: {', '.join(SURFACES)}.")
    model_key = str(model_id or "").strip().lower()
    effort_key = str(effort_id or "").strip().lower()
    if model_key and not is_lineup_id(model_key):
        raise ValueError(f"'{model_id}' is not a model in the lineup.")
    if effort_key and effort_key != AUTO and effort_key not in _BY_EFFORT:
        raise ValueError(f"'{effort_id}' is not an effort level.")
    with _lock:
        data = load()
        surfaces = data.get("surfaces") if isinstance(data.get("surfaces"), dict) else {}
        surfaces[name] = {"model": model_key, "effort": effort_key}
        data["surfaces"] = surfaces
        _save(data)
    return state()


def surface_pick(surface: str) -> str:
    """The model id a turn from this surface should use: its own pick, else the chat's, else "" (Auto)."""
    current = state()
    own = current["surfaces"].get(str(surface or "").lower(), {})
    return own.get("model") or current["pick"]


def surface_effort(surface: str) -> str:
    current = state()
    own = current["surfaces"].get(str(surface or "").lower(), {})
    return own.get("effort") or current["effort"]


def switch_target(target: str) -> Optional[Dict[str, Any]]:
    """``/api/models/switch`` for a lineup name: remember it and answer like a provider switch, else None."""
    key = str(target or "").strip().lower()
    if not is_lineup_id(key):
        return None
    save_pick(key)
    return {"kind": "lineup", "model": key, "preferred": key, "label": label(key)}


# ---------------------------------------------------------------------------
# Turning a pick into a plan
# ---------------------------------------------------------------------------

#: How a family's Auto picks a size from the message (task_analyzer's complexity).
_SIZE_FOR_COMPLEXITY = {"simple": "small", "moderate": "normal", "complex": "middle", "parallel": "max"}


def _complexity(message: str) -> str:
    try:
        from task_analyzer import TaskAnalyzer

        return str(TaskAnalyzer().analyze(message or "").complexity.value)
    except Exception:  # noqa: BLE001 - an analyzer problem means "treat it as an ordinary request"
        return "moderate"


def _model_for_size(fam: Family, size: str) -> LineupModel:
    """The family's model for a size, or the nearest one it has (Pico has no Ultra Max)."""
    order = [s for s, _ in SIZES]
    want = order.index(size) if size in order else 1
    return min(fam.models, key=lambda m: (abs(order.index(m.size) - want), order.index(m.size)))


def _pick_auto_size(fam: Family, message: str) -> LineupModel:
    return _model_for_size(fam, _SIZE_FOR_COMPLEXITY.get(_complexity(message), "normal"))


#: Optional learned chooser for Auto effort (``lineup_learning``): (message, model id, default) -> (effort, why).
EffortChooser = Callable[[str, str, str], Tuple[str, str]]
#: Picks the light model for Pico: (max GB) -> (provider, model, why) or None.
LightPicker = Callable[[float], Optional[Tuple[str, str, str]]]


def _default_light_picker(max_gb: float) -> Optional[Tuple[str, str, str]]:
    try:
        import light_model

        return light_model.pick(max_gb)
    except Exception:  # noqa: BLE001 - no light model simply means the normal chain answers
        return None


def _default_effort_chooser(message: str, model_id: str, default: str) -> Tuple[str, str]:
    try:
        import lineup_learning

        return lineup_learning.choose_effort(message, model_id, default)
    except Exception:  # noqa: BLE001 - learning is a nudge; the size's default always works
        return default, ""


def _code_role() -> Tuple[Optional[str], Optional[str]]:
    """The provider and model the owner set for Code (Keys & Models → model roles)."""
    try:
        from model_roles import MODEL_ROLES

        entry = MODEL_ROLES.get_role("code_generation")
        provider = str(entry.get("provider") or "").strip().lower() or None
        model = str(entry.get("model") or "").strip() or None
        return provider, model
    except Exception:  # noqa: BLE001
        return None, None


def resolve(model_id: str = "", effort_id: str = AUTO, message: str = "", *,
            light_picker: Optional[LightPicker] = None,
            effort_chooser: Optional[EffortChooser] = None) -> TurnPlan:
    """Turn a pick ("carbon", "pico", "" for Auto) and an effort ("auto", "high"…) into this turn's plan.

    Never raises: anything unknown falls back to today's behaviour (the router decides, Normal effort), so a
    stale pick in a browser can never stop a chat.
    """
    light_picker = light_picker or _default_light_picker
    effort_chooser = effort_chooser or _default_effort_chooser
    key = str(model_id or "").strip().lower()
    plan = TurnPlan()

    found = _BY_MODEL.get(key)
    if found is None and key in _BY_FAMILY:
        fam = _BY_FAMILY[key]
        found = (fam, _pick_auto_size(fam, message))
        plan.notes.append(f"{fam.name} Auto picked {found[1].name}")
    if found is not None:
        fam, model = found
        plan.model_id, plan.family_id, plan.label = model.id, fam.id, f"{fam.name} · {model.name}"
        _route_family(plan, fam, model, light_picker)

    # Effort: the slider's choice, or (Auto) the model's own default, which learning may nudge.
    wanted = str(effort_id or AUTO).strip().lower()
    if wanted not in _BY_EFFORT:
        plan.effort_auto = True
        default = DEFAULT_EFFORT_FOR_SIZE.get(found[1].size, "normal") if found else "normal"
        chosen, why = effort_chooser(message, plan.model_id, default if default != AUTO else "normal")
        wanted = chosen if chosen in _BY_EFFORT else "normal"
        if why:
            plan.notes.append(why)
    _apply_effort(plan, _BY_EFFORT[wanted])

    # Zencode always works with its tools: a coding model on the tool-less quick path cannot edit anything.
    if plan.family_id == "zencode" and plan.speed == "fast":
        plan.speed = "auto"
    return plan


def _route_family(plan: TurnPlan, fam: Family, model: LineupModel, light_picker: LightPicker) -> None:
    """Who answers first, for each family."""
    if fam.id == "pico":
        picked = light_picker(PICO_LOCAL_GB.get(model.size, 0.0))
        if picked:
            plan.fast_prefer, plan.fast_model, why = picked
            plan.notes.append(why)
        else:
            plan.fast_candidates = list(PICO_CLOUD)
        # Pico stays light for quick answers; anything that needs tools goes to Big Kahuna, because small models
        # write tool calls badly and a failed tool call costs more time than it saved.
        plan.prefer = "identity0"
    elif fam.id in ("monolith", "crescendo"):
        plan.prefer = "identity0"
        plan.candidates = list(BACKING.get(model.id, ()))
    elif fam.id == "zencode":
        provider, model_name = _code_role()
        plan.prefer, plan.prefer_model = provider, model_name
        if provider:
            plan.notes.append(f"code model {provider}{'/' + model_name if model_name else ''}")


def _apply_effort(plan: TurnPlan, chosen: Effort) -> None:
    plan.effort = chosen.id
    plan.speed = chosen.speed
    plan.thinking = chosen.thinking
    plan.optimizer = chosen.optimizer
    plan.consult = chosen.consult
    plan.max_steps = chosen.max_steps
    plan.smart = chosen.smart
    plan.ultrafast = chosen.ultrafast
    plan.upgrade_mode = chosen.upgrade_mode
    # Crescendo is the heavy family: even at a light effort it may use the stronger model first.
    if plan.family_id == "crescendo":
        plan.smart = True


def plan_for_turn(provider: Optional[str], message: str = "", surface: str = "chat") -> Optional[TurnPlan]:
    """The plan for a turn whose model value is ``provider``; None when the lineup has nothing to say.

    A real provider ("gemini") gets no plan unless the owner moved the effort slider off Auto, so picking a
    provider by hand works exactly as before.
    """
    key = str(provider or "").strip().lower()
    if key and not is_lineup_id(key) and key != AUTO:
        chosen_effort = surface_effort(surface)
        if chosen_effort == AUTO:
            return None
        plan = resolve("", chosen_effort, message)
        plan.prefer = None  # the provider picked by hand still answers
        return plan
    if key in ("", AUTO):
        key = surface_pick(surface) if surface != "chat" else ""
    chosen_effort = surface_effort(surface)
    if not key and chosen_effort == AUTO:
        return None
    return resolve(key, chosen_effort, message)


def catalog() -> Dict[str, Any]:
    """Everything the picker draws: the three levels, the specialist families, the effort stops and the pick."""
    current = state()
    return {
        "main_model": MAIN_MODEL_NAME,
        "levels": [f.view() for f in FAMILIES if f.level],
        "specialists": [f.view() for f in FAMILIES if not f.level],
        "efforts": [e.view() for e in EFFORTS],
        "default_effort_for_size": dict(DEFAULT_EFFORT_FOR_SIZE),
        "sizes": [{"id": s, "label": l} for s, l in SIZES],
        "pick": current["pick"],
        "pick_label": label(current["pick"]) or "Auto",
        "effort": current["effort"],
        "surfaces": current["surfaces"],
    }
