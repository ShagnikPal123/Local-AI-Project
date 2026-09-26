"""Which model does which job — set by the owner or by the AI, and said out loud.

The owner's request: "make sure I can input different models and have both me
and the AI say its use, like if I give an AI model from NVIDIA for image check
or an AWS one for reading text."

A *role* is a job ("image check", "reading text", "image generation"…) bound to
one provider and one model. When Nyx does that job it calls exactly that model
through ``model_hub``, emits a ``model.role`` event so the UI shows
"NVIDIA · Llama 3.2 Vision · image check", and hands the model a one-line
announcement so the reply says which model did the work.

If the assigned model fails (no key, quota, outage) the job is not silently
done by something else: the fallback is recorded and announced — "NVIDIA was
unavailable (401), so Gemini checked the image instead."

Roles are data in ``data_path("model_roles.json")``. Built-in roles can be
re-pointed but not deleted (deleting resets them); the owner or the AI can add
custom roles for any job.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from paths import atomic_replace, data_path

_LOG = logging.getLogger("nyx.model_roles")

JOBS = ("text", "vision", "image")

DEFAULT_ROLES: Dict[str, Dict[str, Any]] = {
    "image_check": {
        "title": "Image check",
        "description": "Look at pictures, screenshots and photos and say what is in them.",
        "job": "vision",
        "provider": "gemini",
        "model": "gemini-flash-lite-latest",
    },
    "reading_text": {
        "title": "Reading text",
        "description": "Read documents, PDFs and long files and answer questions about them.",
        "job": "text",
        "provider": "gemini",
        "model": "gemini-flash-lite-latest",
    },
    "image_gen": {
        "title": "Image generation",
        "description": "Create pictures, artwork and diagrams from a description.",
        "job": "image",
        "provider": "nvidia",
        "model": "black-forest-labs/flux.1-schnell",
    },
    "ui_pointing": {
        "title": "Finding things on screen",
        "description": "Find buttons and fields on a screenshot so the AI cursor can click them.",
        "job": "vision",
        "provider": "gemini",
        "model": "gemini-flash-lite-latest",
    },
    "code_generation": {
        "title": "Code",
        "description": "Write, refactor and review code when a specialist model is wanted.",
        "job": "text",
        "provider": "nvidia",
        "model": "nvidia/nemotron-3-super-120b-a12b",
    },
    "study_notes": {
        "title": "Study notes",
        "description": "Turn lectures and notes into study material: detail, summaries, quizzes, flashcards, step-by-step.",
        "job": "text",
        "provider": "gemini",
        "model": "gemini-flash-lite-latest",
    },
    "build_studio": {
        "title": "3D build studio",
        "description": "Design parts, circuits and assemblies in the Build tab, and explain them step by step.",
        "job": "text",
        "provider": "nvidia",
        "model": "nvidia/nemotron-3-super-120b-a12b",
    },
    "research": {
        "title": "Research",
        "description": "Plan research, read web pages and papers, and write cited reports and academic papers.",
        "job": "text",
        "provider": "nvidia",
        "model": "nvidia/nemotron-3-super-120b-a12b",
    },
    "fast_chat": {
        "title": "Quick answers",
        "description": "Short everyday answers from a fast model.",
        "job": "text",
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
    },
    # Request R: pick Ollama here once a local model is installed and study runs cost nothing online.
    "data_absorption": {
        "title": "Data absorption & analysis",
        "description": "Pull facts out of documents while Nyx studies, write study reports, and analyse data you give it.",
        "job": "text",
        "provider": "nvidia",
        "model": "nvidia/nemotron-3-super-120b-a12b",
    },
}

#: Model ids other tools wrote that the provider does not accept.
_MODEL_ALIASES = {
    ("nvidia", "flux-1-schnell"): "black-forest-labs/flux.1-schnell",
    ("nvidia", "flux.1-schnell"): "black-forest-labs/flux.1-schnell",
    ("nvidia", "flux-1-dev"): "black-forest-labs/flux.1-dev",
    ("nvidia", "nemotron-3-ultra-550b-a55b"): "nvidia/nemotron-3-ultra-550b-a55b",
    ("nvidia", "nemotron-3-ultra"): "nvidia/nemotron-3-ultra-550b-a55b",
    ("nvidia", "nemotron-ultra"): "nvidia/nemotron-3-ultra-550b-a55b",
    ("nvidia", "nemotron-3-super"): "nvidia/nemotron-3-super-120b-a12b",
    # Retired by NVIDIA on 2026-08-26 (answers 410 Gone); saved assignments move to its successor.
    ("nvidia", "meta/llama-3.3-70b-instruct"): "nvidia/nemotron-3-super-120b-a12b",
}

#: Providers tried, in order, when an assigned model fails.
_FALLBACKS = {
    "vision": ("gemini", "nvidia", "openai", "claude", "aws", "qwen", "ollama"),
    "text": ("gemini", "groq", "nvidia", "openai", "claude", "aws", "deepseek", "qwen", "ollama"),
    "image": ("nvidia", "gemini", "openai", "aws", "pollinations"),
}

#: Other models worth trying on the same provider before giving up (owner, 2026-09-16: "make sure it fully
#: checks and uses another model"). Free-tier limits are per model, so a Gemini 429 on one model says nothing
#: about the next, and NVIDIA serves several strong free code models besides the default.
_ALTERNATES: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "nvidia": {"text": ("nvidia/nemotron-3-super-120b-a12b", "qwen/qwen3-coder-480b-a35b-instruct",
                        "deepseek-ai/deepseek-v3.1", "openai/gpt-oss-120b", "nvidia/nemotron-3-ultra-550b-a55b",
                        "nvidia/nemotron-3.5-lightning-30b-a3b"),
               "vision": ("meta/llama-3.2-11b-vision-instruct", "meta/llama-4-maverick-17b-128e-instruct")},
    "gemini": {"text": ("gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.5-flash"),
               "vision": ("gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.5-flash")},
    "groq": {"text": ("llama-3.3-70b-versatile", "openai/gpt-oss-120b", "qwen/qwen3-32b")},
    "openai": {"text": ("gpt-4o-mini", "gpt-4.1-mini")},
    "qwen": {"text": ("qwen-plus", "qwen-flash", "qwen-max", "qwen3-coder-plus"), "vision": ("qwen-vl-plus", "qwen-vl-max")},
}
#: At most this many model calls for one job, so a bad hour cannot turn one request into minutes of retries.
_MAX_ATTEMPTS = 10
#: A quota answer (429) on one model: try the others first for a minute.
_QUOTA_SECONDS = 60
_QUOTA_MARKERS = ("answered 429", "RESOURCE_EXHAUSTED", "rate limit", "quota")

_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")

#: (provider, model) pairs that just failed with an outage, and until when they
#: are skipped. An NVIDIA image job that 504s takes ~25 s to fail; paying that on
#: every picture while the service is down would make every request slow.
_OUTAGE_COOLDOWN: Dict[Tuple[str, str], float] = {}
_OUTAGE_SECONDS = 90  # a "high demand" 503 usually clears within a minute or two
_OUTAGE_MARKERS = ("answered 5", "timed out", "could not be reached", "still queued", "Read timed out")
#: A retired model does not come back: skip it for a day and use the provider's current default instead.
_RETIRED_SECONDS = 24 * 3600
_RETIRED_MARKERS = ("answered 410", "end of life", "no longer available", "has been deprecated", "decommissioned",
                    "answered 404")  # a model id the provider doesn't have (gemini-2.5-flash on 2026-09-16)


def _cooling(provider: str, model: str) -> bool:
    return _OUTAGE_COOLDOWN.get((provider, model), 0.0) > time.time()


def _note_failure(provider: str, model: str, message: str) -> None:
    if any(marker in message for marker in _RETIRED_MARKERS):
        _OUTAGE_COOLDOWN[(provider, model)] = time.time() + _RETIRED_SECONDS
    elif any(marker in message for marker in _OUTAGE_MARKERS):
        _OUTAGE_COOLDOWN[(provider, model)] = time.time() + _OUTAGE_SECONDS
    elif any(marker in message for marker in _QUOTA_MARKERS):
        _OUTAGE_COOLDOWN[(provider, model)] = time.time() + _QUOTA_SECONDS


def _alternates(provider: str, job: str) -> List[str]:
    """Same-provider models to try, filtered by the provider's live catalog when one is already cached."""
    models = list(_ALTERNATES.get(provider, {}).get(job, ()))
    try:
        import model_hub

        with model_hub._catalog_lock:
            cached = model_hub._catalog_cache.get(provider)
        if cached and cached[1]:
            live = {m["id"] for m in cached[1]}
            models = [m for m in models if m in live] or models[:2]
    except Exception:  # noqa: BLE001 - no catalog: try the static list
        pass
    return models


def fallback_candidates(provider: str, model: str, job: str) -> List[Tuple[str, str]]:
    """Every (provider, model) worth trying for a job, best first, cooling ones moved to the end — never dropped.

    Before 2026-09-16 a model that had failed in the last 90 s was *skipped*, so one NVIDIA hiccup plus a Gemini
    quota ended the job with "No model could do it" while other models were fine.
    """
    from model_hub import default_model, known_providers

    ordered: List[Tuple[str, str]] = [(provider, model)]

    def add(p: str, m: str) -> None:
        if m and (p, m) not in ordered:
            ordered.append((p, m))

    try:
        add(provider, default_model(provider, job))
    except Exception:  # noqa: BLE001 - unknown provider: no same-provider default
        pass
    for alt in _alternates(provider, job):
        add(provider, alt)
    others = [p for p in _FALLBACKS[job] if p != provider]
    for other in others:
        try:
            add(other, default_model(other, job))
        except Exception:  # noqa: BLE001
            continue
    if job == "text":
        # Models the owner added in Keys & Models (OpenAI-compatible) are as good a fallback as any built-in one.
        builtin = set(_FALLBACKS["text"]) | set(_FALLBACKS["vision"]) | {"pollinations"}
        for name in known_providers():
            if name not in builtin and name != provider:
                try:
                    add(name, default_model(name, "text"))
                except Exception:  # noqa: BLE001
                    continue
    for other in others:
        for alt in _alternates(other, job)[1:]:
            add(other, alt)
    fresh = [pair for pair in ordered if not _cooling(*pair)]
    cooling = [pair for pair in ordered if _cooling(*pair)]
    return (fresh + cooling)[: _MAX_ATTEMPTS * 3]


class RoleError(ValueError):
    """An assignment that cannot be stored (unknown provider, bad name)."""


def normalize_role(role: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", (role or "").strip().lower().replace(" ", "_").replace("-", "_"))


def _label_for(provider: str, model: str) -> str:
    names = {"nvidia": "NVIDIA", "gemini": "Gemini", "groq": "Groq", "openai": "OpenAI", "claude": "Claude",
             "aws": "AWS", "deepseek": "DeepSeek", "kimi": "Kimi", "ollama": "Ollama", "qwen": "Qwen",
             "pollinations": "Pollinations (free)"}
    short = model.split("/")[-1] if model else ""
    return f"{names.get(provider, provider.title())} {short}".strip()


@dataclass
class RoleRun:
    """What happened when a role was used."""

    role: str
    title: str
    job: str
    provider: str
    model: str
    label: str
    ms: int
    text: str = ""
    fell_back: bool = False
    note: str = ""
    attempts: List[Dict[str, str]] = field(default_factory=list)

    def announcement(self) -> str:
        line = f"[{self.label} · {self.title.lower()}]"
        if self.fell_back and self.note:
            line += f" ({self.note})"
        return line

    def as_event(self) -> Dict[str, Any]:
        return {"role": self.role, "title": self.title, "job": self.job, "provider": self.provider,
                "model": self.model, "label": self.label, "ms": self.ms, "fell_back": self.fell_back,
                "note": self.note}


class ModelRoleStore:
    """Persisted role → provider/model assignments."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path is not None else data_path("model_roles.json")
        self._lock = threading.Lock()
        self._roles: Dict[str, Dict[str, Any]] = {k: self._with_defaults(k, dict(v)) for k, v in DEFAULT_ROLES.items()}
        self._load()

    # --- persistence ----------------------------------------------------------

    @staticmethod
    def _with_defaults(key: str, entry: Dict[str, Any]) -> Dict[str, Any]:
        base = DEFAULT_ROLES.get(key, {})
        provider = str(entry.get("provider") or base.get("provider") or "gemini").strip().lower()
        model = str(entry.get("model") or base.get("model") or "").strip()
        model = _MODEL_ALIASES.get((provider, model), model)
        job = entry.get("job") or base.get("job") or "text"
        return {
            "title": str(entry.get("title") or base.get("title") or key.replace("_", " ").capitalize()),
            "description": str(entry.get("description") or base.get("description") or ""),
            "job": job if job in JOBS else "text",
            "provider": provider,
            "model": model,
            "label": str(entry.get("label") or entry.get("announced_label") or _label_for(provider, model)),
            "assigned_by": str(entry.get("assigned_by") or ("default" if key in DEFAULT_ROLES else "owner")),
            "updated_at": float(entry.get("updated_at") or 0),
            "builtin": key in DEFAULT_ROLES,
        }

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        roles = data.get("roles", data)
        for key, value in roles.items():
            clean = normalize_role(key)
            if isinstance(value, dict) and _ROLE_RE.match(clean):
                base = dict(self._roles.get(clean, {}))
                # The default's label names the default model; a stored entry
                # that changed the model must not keep announcing the old one.
                base.pop("label", None)
                self._roles[clean] = self._with_defaults(clean, {**base, **value})

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"roles": self._roles}, indent=2), encoding="utf-8")
            atomic_replace(tmp, self.path)
        except OSError as error:
            _LOG.warning("Could not save model roles: %s", error)

    # --- reads ------------------------------------------------------------------

    def get_role(self, role: str) -> Dict[str, Any]:
        key = normalize_role(role)
        with self._lock:
            entry = self._roles.get(key)
            return dict(entry) if entry else {}

    def list_all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._roles.items()}

    def snapshot(self) -> Dict[str, Any]:
        from model_hub import SIGNUP_URLS, is_configured, known_providers

        roles = []
        for key, entry in self.list_all().items():
            roles.append({"id": key, **entry, "configured": _safe(is_configured, entry["provider"])})
        providers = [{"name": name, "configured": _safe(is_configured, name), "signup_url": SIGNUP_URLS.get(name, "")}
                     for name in known_providers()]
        return {"roles": roles, "providers": providers, "jobs": list(JOBS)}

    # --- writes -----------------------------------------------------------------

    def assign_role(
        self,
        role: str,
        provider: str,
        model: str = "",
        title: str = "",
        announced_label: str = "",
        description: str = "",
        job: str = "",
        assigned_by: str = "owner",
    ) -> Dict[str, Any]:
        """Point a role at a provider and model (creating the role if it is new)."""
        from model_hub import default_model, known_providers

        key = normalize_role(role)
        if not _ROLE_RE.match(key):
            raise RoleError("Give the role a short name, like image_check or reading_text.")
        name = (provider or "").strip().lower()
        if name in ("anthropic",):
            name = "claude"
        if name in ("amazon", "bedrock", "aws_bedrock"):
            name = "aws"
        if name not in known_providers():
            raise RoleError(f"Unknown provider {provider!r}. Known: {', '.join(known_providers())}.")
        with self._lock:
            existing = self._roles.get(key, {})
            chosen_job = job if job in JOBS else existing.get("job") or "text"
            chosen_model = (model or "").strip() or default_model(name, chosen_job)
            chosen_model = _MODEL_ALIASES.get((name, chosen_model), chosen_model)
            entry = self._with_defaults(key, {
                **existing,
                "provider": name,
                "model": chosen_model,
                "job": chosen_job,
                "title": title.strip() or existing.get("title", ""),
                "description": description.strip() or existing.get("description", ""),
                "label": announced_label.strip() or _label_for(name, chosen_model),
                "assigned_by": assigned_by,
                "updated_at": time.time(),
            })
            self._roles[key] = entry
            self._save()
        _announce_change(key, entry)
        return dict(entry)

    def reset_role(self, role: str) -> Optional[Dict[str, Any]]:
        """Built-in roles go back to their defaults; custom roles are removed."""
        key = normalize_role(role)
        with self._lock:
            if key in DEFAULT_ROLES:
                self._roles[key] = self._with_defaults(key, dict(DEFAULT_ROLES[key]))
                entry: Optional[Dict[str, Any]] = dict(self._roles[key])
            else:
                entry = None
                if self._roles.pop(key, None) is None:
                    return None
            self._save()
        _announce_change(key, entry)
        return entry

    def announce_use(self, role: str) -> str:
        """Compatibility: the one-line announcement for a role's current model."""
        info = self.get_role(role)
        if not info:
            return f"[No model is assigned to {role}]"
        return f"[Using {info['label']} for {info['title'].lower()}]"

    def summary_for_prompt(self) -> str:
        """The model team, as the assistant's system prompt states it."""
        from model_hub import is_configured

        lines = ["## Models assigned to jobs (say which one you used when you use it)"]
        for key, entry in self.list_all().items():
            state = "ready" if _safe(is_configured, entry["provider"]) else "no key yet"
            lines.append(f"- {entry['title']} ({key}): {entry['label']} — {entry['provider']}/{entry['model']} [{state}]")
        lines.append(
            "Use analyze_image for image checks, read_document for reading files, generate_image for pictures: "
            "they run on these models. Change an assignment with set_model_purpose when the user asks."
        )
        return "\n".join(lines)

    # --- use ----------------------------------------------------------------------

    def run(
        self,
        role: str,
        prompt: str,
        *,
        images: Sequence[Tuple[bytes, str]] = (),
        system: str = "",
        max_tokens: int = 1200,
        allow_fallback: bool = True,
    ) -> RoleRun:
        """Do a text or vision job with the role's model, announcing what was used."""
        from model_hub import ModelCallError, complete, is_configured

        key = normalize_role(role)
        entry = self.get_role(key) or self._with_defaults(key, {"job": "vision" if images else "text"})
        job = "vision" if images else entry["job"] if entry["job"] != "image" else "text"
        attempts: List[Dict[str, str]] = []
        assigned = (entry["provider"], entry["model"])
        # Same provider's other models first (a busy pick shouldn't jump straight to another company), then
        # every other configured provider and the owner's own models. Cooling models go last, not away.
        candidates = fallback_candidates(entry["provider"], entry["model"], job) if allow_fallback else [assigned]
        configured: Dict[str, bool] = {}
        tried = 0

        for provider, model in candidates:
            if (provider, model) != assigned:
                if provider not in configured:
                    configured[provider] = _safe(is_configured, provider)
                if not configured[provider]:
                    continue
            if tried >= _MAX_ATTEMPTS:
                break
            tried += 1
            try:
                reply = complete(provider, model, prompt, images=images, system=system, max_tokens=max_tokens)
            except ModelCallError as error:
                _note_failure(provider, model, str(error))
                attempts.append({"provider": provider, "model": model, "error": str(error)[:240]})
                if any(m in str(error) for m in ("answered 401", "answered 402", "insufficient_quota", "no API key")):
                    configured[provider] = False  # a refused key refuses every model on that provider
                continue
            fell_back = (reply.provider, reply.model) != assigned
            note = ""
            if fell_back and attempts:
                first = attempts[0]
                note = f"{_label_for(first['provider'], first['model'])} was unavailable — {first['error'][:120]}"
            run = RoleRun(role=key, title=entry["title"], job=job, provider=reply.provider, model=reply.model,
                          label=entry["label"] if not fell_back else _label_for(reply.provider, reply.model),
                          ms=reply.ms, text=reply.text, fell_back=fell_back, note=note, attempts=attempts)
            _emit_run(run)
            return run

        details = "; ".join(f"{a['provider']}: {a['error']}" for a in attempts) or "no provider is configured"
        raise ModelCallError(f"No model could do '{entry['title']}' — {details}")

    def generate(self, prompt: str, size: str = "1024x1024", role: str = "image_gen",
                 allow_fallback: bool = True) -> Tuple[Any, RoleRun]:
        """Make a picture with the role's image model. Returns (GeneratedImage, RoleRun)."""
        from model_hub import ModelCallError, default_model, generate_image, is_configured

        key = normalize_role(role)
        entry = self.get_role(key) or self.get_role("image_gen")
        candidates = [(entry["provider"], entry["model"])]
        if allow_fallback:
            candidates += [(p, default_model(p, "image")) for p in _FALLBACKS["image"] if p != entry["provider"]]
        attempts: List[Dict[str, str]] = []
        for index, (provider, model) in enumerate(candidates):
            if index > 0 and not _safe(is_configured, provider):
                continue
            if allow_fallback and _cooling(provider, model) and index < len(candidates) - 1:
                # Pictures skip a provider that just timed out (a 504 costs ~25 s); the last one is always tried.
                attempts.append({"provider": provider, "model": model, "error": "skipped: it failed moments ago"})
                continue
            try:
                image = generate_image(provider, model, prompt, size)
            except ModelCallError as error:
                _note_failure(provider, model, str(error))
                attempts.append({"provider": provider, "model": model, "error": str(error)[:240]})
                continue
            fell_back = index > 0
            note = ""
            if fell_back and attempts:
                note = f"{_label_for(attempts[0]['provider'], attempts[0]['model'])} was unavailable — {attempts[0]['error'][:120]}"
            run = RoleRun(role=key, title=entry["title"], job="image", provider=image.provider, model=image.model,
                          label=entry["label"] if not fell_back else _label_for(image.provider, image.model),
                          ms=image.ms, fell_back=fell_back, note=note, attempts=attempts)
            _emit_run(run)
            return image, run
        details = "; ".join(f"{a['provider']}: {a['error']}" for a in attempts) or "no image provider is configured"
        raise ModelCallError(f"No model could generate the image — {details}")


def _safe(fn: Any, *args: Any) -> bool:
    try:
        return bool(fn(*args))
    except Exception:
        return False


def _emit_run(run: RoleRun) -> None:
    try:
        from tool_context import emit

        emit("model.role", **run.as_event())
    except Exception:
        pass
    try:
        from agent_events import publish_activity

        publish_activity("model.role", **run.as_event())
    except Exception:
        pass


def _announce_change(key: str, entry: Optional[Dict[str, Any]]) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("model_roles.changed", role=key, entry=entry)
    except Exception:
        pass


MODEL_ROLES = ModelRoleStore()
