"""Auto-assign: Nyx decides which model does which job (Update 1, U29).

Owner: "an auto assign for the keys and models tab since in there it seems that it can be difficult to determine which
models are really a good idea to put to which task and the ai determines it".

The decision is deterministic and spends nothing: no model is asked. It weighs

* **what is actually usable** — providers with a key (``model_hub.is_configured``), models installed in Ollama, and
  models the owner added; a provider's live model list when one is already cached;
* **what each model is good at** — ``MODEL_FACTS``, Nyx's own notes on the models it ships with (answer quality, code,
  speed, how much text it reads at once, pictures in, pictures out). These are hand-kept priors, said as such;
* **what each job needs** — ``ROLE_NEEDS`` weights those qualities per job ("Quick answers" is mostly speed,
  "Reading text" mostly long context);
* **what Nyx has seen** — Big Kahuna's competence table (``identity0.api.competence``): a model that has answered at
  least five times in the job's domain has its real success rate blended in;
* **money** — a paid provider is never picked unless it is the owner's own current pick in the model menu, so
  auto-assign cannot start a bill (identity0.members applies the same rule).

Every proposal says *why* in a sentence. Nothing changes until the owner applies it (the preview is the default), roles
the owner set by hand are left alone unless he includes them, and the previous assignments are saved so one press
undoes the whole batch.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

from paths import data_path

FACETS = ("quality", "code", "speed", "context", "vision", "image")

#: What each built-in job values. Weights per facet; ``needs`` is the capability a model must have at all.
ROLE_NEEDS: Dict[str, Dict[str, Any]] = {
    "image_check": {"needs": "vision", "weights": {"vision": 0.6, "quality": 0.2, "speed": 0.2}},
    "ui_pointing": {"needs": "vision", "weights": {"vision": 0.55, "speed": 0.45}},
    "reading_text": {"weights": {"context": 0.5, "quality": 0.3, "speed": 0.2}},
    "image_gen": {"needs": "image", "weights": {"image": 0.8, "speed": 0.2}},
    "code_generation": {"weights": {"code": 0.65, "quality": 0.25, "speed": 0.1}},
    "study_notes": {"weights": {"quality": 0.5, "context": 0.3, "speed": 0.2}},
    "build_studio": {"weights": {"quality": 0.45, "code": 0.35, "speed": 0.2}},
    "research": {"weights": {"quality": 0.55, "context": 0.35, "speed": 0.1}},
    "fast_chat": {"weights": {"speed": 0.7, "quality": 0.3}},
    # Request R: studying runs for hours, so a model on this PC (free, unlimited, private) is worth a lot here.
    "data_absorption": {"weights": {"quality": 0.4, "context": 0.3, "speed": 0.3}, "local_bonus": 0.25},
}

#: Big Kahuna files turns under these domains; a role borrows the matching record.
ROLE_DOMAIN = {"code_generation": "code", "build_studio": "code", "research": "web", "reading_text": "files",
               "study_notes": "knowledge", "fast_chat": "chat", "data_absorption": "self-study"}

#: Nyx's notes on the models it knows (0–1). Missing facets fall back to the model's general quality.
MODEL_FACTS: Dict[Tuple[str, str], Dict[str, float]] = {
    ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"): {"quality": 0.92, "code": 0.88, "speed": 0.35, "context": 0.8},
    ("nvidia", "nvidia/nemotron-3-super-120b-a12b"): {"quality": 0.86, "code": 0.84, "speed": 0.6, "context": 0.8},
    ("nvidia", "qwen/qwen3-coder-480b-a35b-instruct"): {"quality": 0.84, "code": 0.93, "speed": 0.5, "context": 0.8},
    ("nvidia", "deepseek-ai/deepseek-v3.1"): {"quality": 0.86, "code": 0.86, "speed": 0.5, "context": 0.7},
    ("nvidia", "openai/gpt-oss-120b"): {"quality": 0.82, "code": 0.8, "speed": 0.65, "context": 0.7},
    ("nvidia", "nvidia/nemotron-3.5-lightning-30b-a3b"): {"quality": 0.7, "code": 0.68, "speed": 0.85, "context": 0.7},
    ("nvidia", "meta/llama-3.2-11b-vision-instruct"): {"quality": 0.55, "vision": 0.6, "speed": 0.7},
    ("nvidia", "meta/llama-4-maverick-17b-128e-instruct"): {"quality": 0.75, "vision": 0.78, "speed": 0.65},
    ("nvidia", "black-forest-labs/flux.1-schnell"): {"image": 0.78, "speed": 0.85},
    ("nvidia", "black-forest-labs/flux.1-dev"): {"image": 0.86, "speed": 0.5},
    ("gemini", "gemini-3.5-flash"): {"quality": 0.88, "code": 0.82, "speed": 0.75, "context": 0.97, "vision": 0.88},
    ("gemini", "gemini-flash-latest"): {"quality": 0.84, "code": 0.78, "speed": 0.8, "context": 0.97, "vision": 0.86},
    ("gemini", "gemini-flash-lite-latest"): {"quality": 0.74, "code": 0.68, "speed": 0.92, "context": 0.95, "vision": 0.78},
    # Gemini's picture model has no free tier: it bills even on a "free" key, so it counts as paid.
    ("gemini", "gemini-2.5-flash-image"): {"image": 0.86, "speed": 0.7, "bills": 1.0},
    ("groq", "llama-3.3-70b-versatile"): {"quality": 0.72, "code": 0.66, "speed": 0.97, "context": 0.5},
    ("groq", "openai/gpt-oss-120b"): {"quality": 0.82, "code": 0.8, "speed": 0.93, "context": 0.6},
    ("groq", "qwen/qwen3-32b"): {"quality": 0.74, "code": 0.75, "speed": 0.92, "context": 0.55},
    ("groq", "meta-llama/llama-4-scout-17b-16e-instruct"): {"quality": 0.7, "vision": 0.7, "speed": 0.95},
    ("openai", "gpt-4o-mini"): {"quality": 0.78, "code": 0.75, "speed": 0.8, "context": 0.6, "vision": 0.78},
    ("openai", "gpt-4.1-mini"): {"quality": 0.82, "code": 0.8, "speed": 0.78, "context": 0.9, "vision": 0.8},
    ("openai", "gpt-image-1"): {"image": 0.92, "speed": 0.5},
    ("claude", "claude-haiku-4-5-20251001"): {"quality": 0.84, "code": 0.84, "speed": 0.8, "context": 0.8, "vision": 0.8},
    ("deepseek", "deepseek-chat"): {"quality": 0.85, "code": 0.86, "speed": 0.6, "context": 0.6},
    ("kimi", "moonshot-v1-8k"): {"quality": 0.7, "code": 0.65, "speed": 0.7, "context": 0.3},
    ("qwen", "qwen-max"): {"quality": 0.86, "code": 0.82, "speed": 0.6, "context": 0.7},
    ("qwen", "qwen-plus"): {"quality": 0.8, "code": 0.78, "speed": 0.75, "context": 0.8},
    ("qwen", "qwen-flash"): {"quality": 0.7, "code": 0.66, "speed": 0.9, "context": 0.8},
    ("qwen", "qwen3-coder-plus"): {"quality": 0.8, "code": 0.9, "speed": 0.65, "context": 0.8},
    ("qwen", "qwen-vl-plus"): {"quality": 0.7, "vision": 0.75, "speed": 0.7},
    ("aws", "amazon.nova-lite-v1:0"): {"quality": 0.66, "code": 0.6, "speed": 0.8, "context": 0.8, "vision": 0.68},
    ("aws", "amazon.nova-canvas-v1:0"): {"image": 0.75, "speed": 0.6},
    ("pollinations", "flux"): {"image": 0.55, "speed": 0.6},
}

_FACET_WORDS = {"quality": "gives strong answers", "code": "is strong at code", "speed": "is fast",
                "context": "reads very long documents at once", "vision": "reads pictures well",
                "image": "draws good pictures"}
_PROVIDER_NAMES = {"nvidia": "NVIDIA", "gemini": "Gemini", "groq": "Groq", "openai": "OpenAI", "claude": "Claude",
                   "aws": "AWS", "deepseek": "DeepSeek", "kimi": "Kimi", "ollama": "Ollama", "qwen": "Qwen",
                   "pollinations": "Pollinations"}
_VISION_NAMES = re.compile(r"llava|vision|-vl|vl:|qwen2\.5vl|qwen3-vl|gemma3|minicpm-v|moondream|bakllava|llama4", re.I)
_UNDO_FILE = "model_roles_auto_undo.json"
_EVIDENCE_MIN = 5
_SPREAD = 0.03


# ---------------------------------------------------------------------------
# What is usable right now
# ---------------------------------------------------------------------------

def _paid() -> set:
    try:
        import router

        return set(router._PAID_PROVIDERS) | {"aws"}
    except Exception:  # pragma: no cover
        return {"claude", "openai", "kimi", "deepseek", "perplexity", "qwen", "aws"}


def _owner_pick() -> str:
    try:
        import model_choice

        return str(model_choice.load().get("provider") or "")
    except Exception:
        return ""


def _ollama_facts(name: str) -> Dict[str, float]:
    """Rough facts for a local model from its name: bigger is better, slower; "coder" codes; vision tags see."""
    lowered = name.lower()
    size = re.search(r"(\d+(?:\.\d+)?)b\b", lowered)
    billions = float(size.group(1)) if size else 8.0
    quality = 0.5 if billions < 5 else 0.6 if billions < 10 else 0.68 if billions < 20 else 0.74 if billions < 40 else 0.8
    facts = {"quality": quality, "code": quality + (0.1 if "coder" in lowered or "code" in lowered else -0.04),
             "speed": 0.75 if billions < 10 else 0.6 if billions < 20 else 0.45, "context": 0.5}
    if _VISION_NAMES.search(lowered):
        facts["vision"] = quality - 0.05
    return facts


def _live_ids(provider: str) -> Optional[set]:
    """Model ids the provider really offers: its cached catalogue, else one free model listing (cached an hour).

    Listing models costs nothing and asks no model anything; it stops Nyx proposing a model the provider retired.
    None means "unknown" (no listing for this provider), and then Nyx's notes are trusted as they are.
    """
    if provider in ("pollinations", "aws"):
        return None
    try:
        import model_hub

        with model_hub._catalog_lock:
            cached = model_hub._catalog_cache.get(provider)
        listed = cached[1] if cached and cached[1] else model_hub.list_models(provider)
        ids = {m["id"] for m in listed}
        defaults = set((model_hub.DEFAULT_MODELS.get(provider) or {}).values())
        return ids if ids - defaults else None  # only the defaults came back: the listing failed, know nothing
    except Exception:
        return None


def candidates(configured: Optional[Dict[str, bool]] = None) -> List[Dict[str, Any]]:
    """Every (provider, model) that could take a job now, with its facts. ``configured`` overrides key checks (tests)."""
    import model_hub

    providers = [p for p in model_hub.known_providers() if p != "identity0"]
    if configured is None:
        configured = {p: _safe(model_hub.is_configured, p) for p in providers}
    paid, pick = _paid(), _owner_pick()
    out: List[Dict[str, Any]] = []
    for provider in providers:
        if not configured.get(provider):
            continue
        is_paid = provider in paid
        if is_paid and provider != pick:
            continue  # never start a bill on the owner's behalf
        models: Dict[str, Dict[str, float]] = {}
        if provider == "ollama":
            try:
                ids = [m["id"] for m in model_hub.list_models("ollama") if "embedding" not in m.get("jobs", [])]
            except Exception:
                ids = []
            models = {i: _ollama_facts(i) for i in ids if i and "embed" not in i.lower()}
        else:
            live = _live_ids(provider)
            for (p, model), facts in MODEL_FACTS.items():
                if p == provider and (live is None or model in live or provider == "pollinations"):
                    models[model] = dict(facts)
            for job, model in (model_hub.DEFAULT_MODELS.get(provider) or {}).items():
                if model and model not in models and model != "auto":
                    models[model] = {"image": 0.6, "speed": 0.6} if job == "image" else                         {"quality": 0.6, "vision": 0.6} if job == "vision" else {"quality": 0.6}
            spec = _custom_spec(provider)
            if spec is not None and spec.model and spec.model not in models:
                models[spec.model] = {"quality": 0.65, "code": 0.6, "speed": 0.7, "context": 0.5}
        for model, facts in models.items():
            if facts.get("bills") and provider != pick:
                continue
            out.append({"provider": provider, "model": model, "facts": facts, "local": provider == "ollama",
                        "paid": is_paid, "label": _label(provider, model)})
    return out


def _custom_spec(provider: str) -> Any:
    try:
        from provider_specs import BUILTIN_NAMES, PROVIDER_SPECS

        return None if provider in BUILTIN_NAMES else PROVIDER_SPECS.get(provider)
    except Exception:
        return None


def _label(provider: str, model: str) -> str:
    try:
        from model_roles import _label_for

        return _label_for(provider, model)
    except Exception:  # pragma: no cover
        return f"{provider} {model}"


def _safe(fn: Any, *args: Any) -> bool:
    try:
        return bool(fn(*args))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def needs_for(role_id: str, role: Dict[str, Any]) -> Dict[str, Any]:
    """The built-in needs, or a guess for an owner-made job from its kind and words."""
    if role_id in ROLE_NEEDS:
        return ROLE_NEEDS[role_id]
    job = str(role.get("job") or "text")
    if job == "vision":
        return {"needs": "vision", "weights": {"vision": 0.6, "quality": 0.25, "speed": 0.15}}
    if job == "image":
        return {"needs": "image", "weights": {"image": 0.8, "speed": 0.2}}
    words = f"{role.get('title', '')} {role.get('description', '')}".lower()
    if re.search(r"\bcod(e|ing)|program|script|debug", words):
        return {"weights": {"code": 0.6, "quality": 0.3, "speed": 0.1}}
    if re.search(r"quick|fast|short|chat", words):
        return {"weights": {"speed": 0.65, "quality": 0.35}}
    if re.search(r"read|document|pdf|summar|long|book|transcript", words):
        return {"weights": {"context": 0.45, "quality": 0.35, "speed": 0.2}}
    return {"weights": {"quality": 0.6, "speed": 0.25, "context": 0.15}}


def _facet(facts: Dict[str, float], name: str) -> float:
    if name in facts:
        return float(facts[name])
    if name in ("vision", "image"):
        return 0.0
    quality = float(facts.get("quality", 0.55))
    return quality - 0.05 if name == "code" else 0.6 if name == "speed" else 0.5 if name == "context" else quality


def _evidence(domain: str, candidate: Dict[str, Any], table: Dict[str, Any]) -> Optional[Tuple[float, int]]:
    """(success rate, answers) from Big Kahuna's record for this model in this domain, when there is enough of it."""
    if not domain:
        return None
    rows = (table.get("domains") or {}).get(domain) or {}
    provider, model = candidate["provider"], candidate["model"]
    try:
        import model_hub

        default = model_hub.default_model(provider, "text")
    except Exception:
        default = ""
    row = rows.get(f"{provider}:{model}") or (rows.get(f"{provider}:default") if model == default else None)
    if not row or int(row.get("n", 0)) < _EVIDENCE_MIN:
        return None
    return (int(row.get("ok", 0)) + 1) / (int(row["n"]) + 2), int(row["n"])


def _bench_state(provider: str, model: str) -> str:
    """"retired" (skip it), "cooling" (just failed: count it down) or ""."""
    try:
        import model_roles

        until = model_roles._OUTAGE_COOLDOWN.get((provider, model), 0.0)
    except Exception:
        return ""
    left = until - time.time()
    return "retired" if left > 3600 else "cooling" if left > 0 else ""


def score(role_id: str, role: Dict[str, Any], candidate: Dict[str, Any], table: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """How well one model fits one job, with the reasons. None when it cannot do the job at all."""
    need = needs_for(role_id, role)
    facts = candidate["facts"]
    required = need.get("needs")
    if required and _facet(facts, required) <= 0:
        return None
    if not required and "image" in facts and "quality" not in facts:
        return None  # a picture model cannot write text
    state = _bench_state(candidate["provider"], candidate["model"])
    if state == "retired":
        return None
    weights = need["weights"]
    value = sum(w * _facet(facts, f) for f, w in weights.items()) / max(1e-9, sum(weights.values()))
    reasons: List[str] = []
    strong = sorted(weights, key=lambda f: -weights[f] * _facet(facts, f))
    reasons.append(" and ".join(_FACET_WORDS[f] for f in strong[:2] if _facet(facts, f) >= 0.7) or "can do this job")
    if candidate["local"]:
        value += 0.04 + float(need.get("local_bonus", 0.0))
        reasons.append("runs on this PC — free, private and unlimited")
    elif candidate["paid"]:
        reasons.append("paid, but it is your own pick in the model menu")
    else:
        reasons.append("free")
    evidence = _evidence(ROLE_DOMAIN.get(role_id, ""), candidate, table)
    if evidence is not None:
        rate, answers = evidence
        value = 0.8 * value + 0.2 * rate
        reasons.append(f"worked {round(rate * 100)}% of {answers} times for Big Kahuna")
    if state == "cooling":
        value -= 0.1
        reasons.append("failed a few minutes ago, so it is counted down")
    return {**candidate, "score": round(value, 4), "reasons": reasons}


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def plan(*, include_owner: bool = False, configured: Optional[Dict[str, bool]] = None,
         table: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What auto-assign would do now. Changes nothing."""
    from model_roles import MODEL_ROLES

    pool = candidates(configured)
    if table is None:
        try:
            from identity0 import api as kahuna

            table = kahuna.competence()
        except Exception:
            table = {}
    roles = []
    given: Dict[Tuple[str, str], int] = {}
    for role_id, role in MODEL_ROLES.list_all().items():
        scored = list(filter(None, (score(role_id, role, c, table) for c in pool)))
        for item in scored:
            # Free limits are per model, so every job already handed to a model counts it down a little.
            item["score"] = round(item["score"] - _SPREAD * given.get((item["provider"], item["model"]), 0), 4)
        ranked = sorted(scored, key=lambda s: (-s["score"], s["provider"], s["model"]))
        current = {"provider": role["provider"], "model": role["model"], "label": role["label"],
                   "assigned_by": role.get("assigned_by", "")}
        row: Dict[str, Any] = {"id": role_id, "title": role["title"], "job": role["job"], "current": current,
                               "alternatives": []}
        if not ranked:
            row.update(proposed=None, change=False, apply=False,
                       why=_nothing_for(role.get("job", "text"), needs_for(role_id, role)))
            roles.append(row)
            continue
        best = ranked[0]
        here = next((r for r in ranked if r["provider"] == current["provider"] and r["model"] == current["model"]), None)
        if here is not None and here["score"] >= best["score"] - 0.03:
            best = here  # within a hair of the best: keep it rather than churn
        given[(best["provider"], best["model"])] = given.get((best["provider"], best["model"]), 0) + 1
        row["alternatives"] = [_brief(r) for r in ranked if r is not best][:3]
        change = (best["provider"], best["model"]) != (current["provider"], current["model"])
        owner_set = current["assigned_by"] == "owner"
        why = f"{best['label']} {', '.join(best['reasons'])}."
        if not change:
            why = f"Keep {best['label']}: it is already as good a fit as any here — it {', '.join(best['reasons'])}."
        elif here is None:
            why += " " + _why_not_current(current, pool)
        else:
            why += f" It fits better than {current['label']} ({best['score']:.2f} vs {here['score']:.2f})."
        if change and owner_set:
            why += " You chose the current model yourself, so this is only applied if you tick it."
        row.update(proposed=_brief(best), change=change, apply=change and (include_owner or not owner_set), why=why)
        roles.append(row)
    usable = sorted({c["provider"] for c in pool})
    return {"roles": roles, "providers": usable, "changes": sum(1 for r in roles if r["apply"]),
            "undo": undo_available(), "notes": _notes(pool, usable)}


def _brief(scored: Dict[str, Any]) -> Dict[str, Any]:
    return {"provider": scored["provider"], "model": scored["model"], "label": scored["label"],
            "score": scored["score"], "local": scored["local"], "paid": scored["paid"],
            "why": ", ".join(scored["reasons"])}


def _usable(current: Dict[str, Any], pool: List[Dict[str, Any]]) -> bool:
    return any(c["provider"] == current["provider"] for c in pool)


def _why_not_current(current: Dict[str, Any], pool: List[Dict[str, Any]]) -> str:
    provider = current["provider"]
    if provider == "identity0":
        return "Now Big Kahuna picks a model itself each time; this names one model for the job instead."
    if provider in _paid() and provider != _owner_pick():
        return f"The current model ({current['label']}) is paid and is not your pick in the model menu."
    if not _usable(current, pool):
        return f"The current model ({current['label']}) has no key yet."
    return f"The current model ({current['label']}) can't do this job."


def _nothing_for(job: str, need: Dict[str, Any]) -> str:
    wanted = need.get("needs") or job
    if wanted == "vision":
        return "No free model that can look at pictures is set up — a free Gemini or NVIDIA key would cover it."
    if wanted == "image":
        return "No picture model is set up — a free NVIDIA key adds FLUX."
    return "No free model is set up for this — add a free Gemini, Groq or NVIDIA key, or install a local model."


def _notes(pool: List[Dict[str, Any]], usable: List[str]) -> List[str]:
    notes = []
    if not pool:
        notes.append("No model is usable yet: add a free key below (Gemini, Groq or NVIDIA) or install a local model.")
    skipped = sorted(p for p in _paid() if p not in usable and _owner_pick() != p)
    if skipped:
        notes.append("Paid providers are only used when they are your own pick in the model menu, so auto-assign "
                     "never starts a bill.")
    if len(pool) > 1:
        notes.append("Jobs are spread over several models a little, because free limits are counted per model.")
    if "ollama" in usable:
        notes.append("Local models are rated from their size and name; the more Nyx uses them, the more Big Kahuna's "
                     "record counts.")
    return notes


# ---------------------------------------------------------------------------
# Applying and undoing
# ---------------------------------------------------------------------------

def _undo_path():
    return data_path(_UNDO_FILE)


def undo_available() -> Optional[Dict[str, Any]]:
    try:
        saved = json.loads(_undo_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(saved, dict) or not saved.get("roles"):
        return None
    return {"at": saved.get("at"), "roles": sorted(saved["roles"])}


def apply(assignments: Optional[Iterable[Dict[str, Any]]] = None, *, include_owner: bool = False) -> Dict[str, Any]:
    """Apply the preview the owner saw (``assignments``), or the fresh plan's ticked rows. Saves an undo first."""
    from model_roles import MODEL_ROLES, RoleError

    fresh = plan(include_owner=include_owner)
    if assignments is None:
        chosen = [{"role": r["id"], "provider": r["proposed"]["provider"], "model": r["proposed"]["model"]}
                  for r in fresh["roles"] if r["apply"] and r["proposed"]]
    else:
        chosen = [{"role": str(a.get("role") or a.get("id") or ""), "provider": str(a.get("provider") or ""),
                   "model": str(a.get("model") or "")} for a in assignments]
    usable = {(c["provider"], c["model"]) for c in candidates()}
    usable_providers = {p for p, _ in usable}
    before = MODEL_ROLES.list_all()
    snapshot: Dict[str, Any] = {}
    applied, skipped = [], []
    for item in chosen:
        role = item["role"]
        if role not in before:
            skipped.append({"role": role, "why": "no such job"})
            continue
        if item["provider"] not in usable_providers:
            skipped.append({"role": role, "why": f"{item['provider']} is not usable now (no key, or paid)"})
            continue
        snapshot.setdefault(role, {k: before[role].get(k) for k in ("provider", "model", "label", "assigned_by",
                                                                    "title", "description", "job")})
        try:
            entry = MODEL_ROLES.assign_role(role, item["provider"], model=item["model"], assigned_by="auto")
        except RoleError as error:
            snapshot.pop(role, None)
            skipped.append({"role": role, "why": str(error)})
            continue
        applied.append({"role": role, "provider": entry["provider"], "model": entry["model"], "label": entry["label"]})
    if snapshot:
        _undo_path().write_text(json.dumps({"at": time.time(), "roles": snapshot}, indent=1), encoding="utf-8")
    return {"applied": applied, "skipped": skipped, "undo": undo_available()}


def undo() -> Dict[str, Any]:
    """Put back every role the last auto-assign changed, exactly as it was."""
    from model_roles import DEFAULT_ROLES, MODEL_ROLES

    try:
        saved = json.loads(_undo_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    restored = []
    for role, previous in (saved.get("roles") or {}).items():
        base = DEFAULT_ROLES.get(role)
        if previous.get("assigned_by") == "default" and base and (previous.get("provider"), previous.get("model")) == (
                base["provider"], base["model"]):
            MODEL_ROLES.reset_role(role)
        else:
            MODEL_ROLES.assign_role(role, str(previous.get("provider")), model=str(previous.get("model") or ""),
                                    title=str(previous.get("title") or ""), announced_label=str(previous.get("label") or ""),
                                    description=str(previous.get("description") or ""),
                                    job=str(previous.get("job") or ""),
                                    assigned_by=str(previous.get("assigned_by") or "owner"))
        restored.append(role)
    try:
        _undo_path().unlink()
    except OSError:
        pass
    return {"restored": restored}


# ---------------------------------------------------------------------------
# The chat tool
# ---------------------------------------------------------------------------

def tool_auto_assign_models(apply_now: bool = False, include_owner: bool = False) -> str:
    """Preview (default) or apply the automatic model-for-each-job choice."""
    if apply_now:
        done = apply(include_owner=include_owner)
        if not done["applied"]:
            return "Nothing needed changing — every job already has the best usable model."
        lines = [f"Auto-assigned {len(done['applied'])} job(s) (undo in Keys & Models, or ask me to undo):"]
        lines += [f"- {a['role']}: {a['label']}" for a in done["applied"]]
        lines += [f"- skipped {s['role']}: {s['why']}" for s in done["skipped"]]
        return "\n".join(lines)
    preview = plan(include_owner=include_owner)
    lines = ["Auto-assign preview (nothing changed yet; call again with apply_now=true after the owner agrees):"]
    for row in preview["roles"]:
        mark = "→ change" if row["apply"] else ("(kept: owner's choice)" if row["change"] else "keep")
        target = row["proposed"]["label"] if row.get("proposed") else "nothing usable"
        lines.append(f"- {row['title']}: {row['current']['label']} {mark} {target}. {row['why']}")
    lines += preview["notes"]
    return "\n".join(lines)


def tool_undo_auto_assign() -> str:
    done = undo()
    return f"Put back {len(done['restored'])} job(s) as they were." if done["restored"] else "There is nothing to undo."


def register_autoassign_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="auto_assign_models",
        description=("Decide which configured model is best for each job (image check, reading, code, quick answers…) "
                     "from what is installed and keyed, with a reason for each. Previews by default; apply_now=true "
                     "only after the owner says yes. Never picks a paid provider the owner hasn't chosen."),
        parameters=[ToolParam("apply_now", "boolean", "Apply the plan (only after the owner agreed)", required=False),
                    ToolParam("include_owner", "boolean", "Also change jobs the owner set by hand", required=False)],
        handler=tool_auto_assign_models,
        category="general",
        label=lambda a: "Assigning models to jobs" if a.get("apply_now") else "Working out the best model for each job",
    )
    registry.register(
        name="undo_auto_assign",
        description="Undo the last automatic model assignment, restoring every job exactly as it was.",
        parameters=[],
        handler=tool_undo_auto_assign,
        category="general",
        label=lambda a: "Undoing the automatic model choice",
    )
