"""Improvement autopilot: self-improvement on a schedule the owner describes in words.

"Improve and auto-approve everything for 22 hours." "Study for an hour, improve
for an hour, and loop until I stop you." "Take a detox hour tonight." Each of
those becomes a **run**: a list of timed phases, optionally looping, optionally
bounded by an end time, optionally with an **auto-approve window**.

Phases
    ``study``   — read what happened (recent chats, 👎 feedback, engine errors, the
                  code map, optionally the web) and write **lessons**.
    ``improve`` — run improvement-engine sessions steered by those lessons. Every
                  finding is a change in the review gate. Inside an auto-approve
                  window each one is checked for duplicates, researched (the target
                  file is read; the idea is judged), approved on the owner's standing
                  authorisation, written and tested in a sandbox by ``self_patch``,
                  reviewed by a critic that reads the *real* diff, and applied only
                  then (``improve_review.implement_change``). Outside a window the
                  findings wait for the owner in the Improve tab's review queue.
    ``detox``   — the quiet hour: consolidate what was learned, then a light,
                  reliability-first improve pass.
    ``rest``    — do nothing for a while (useful inside loops).

Controls
    The Improve tab's sliders, toggles and pickers are *data* (``controls.json``).
    The owner changes values there or in chat; Nyx can add new controls
    (``improve_add_control``) with a sentence saying what each one affects, and
    every value — built-in or added — is handed to the study and improve prompts,
    so a new slider changes behaviour without new code.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import data_path

_LOG = logging.getLogger("nyx.autopilot")

PHASE_KINDS = ("study", "improve", "detox", "rest")
CONTROL_KINDS = ("slider", "toggle", "select", "multiselect", "text")
_MAX_LOG = 120
_MAX_RUNS_KEPT = 25

DEFAULT_CONTROLS: List[Dict[str, Any]] = [
    {"key": "aggressiveness", "label": "How bold", "kind": "slider", "min": 1, "max": 5, "step": 1, "value": 3,
     "description": "1 = tiny safe fixes · 5 = bigger refactors with four analysis angles"},
    {"key": "max_changes_per_hour", "label": "Changes per hour", "kind": "slider", "min": 0, "max": 20, "step": 1, "value": 4,
     "description": "Auto-approved changes above this wait for you"},
    {"key": "max_patch_lines", "label": "Largest single edit (lines)", "kind": "slider", "min": 10, "max": 400, "step": 10, "value": 150,
     "description": "Edits bigger than this are rejected"},
    {"key": "test_depth", "label": "Tests before applying", "kind": "select", "options": ["quick", "full"], "value": "quick",
     "description": "quick = tests for the changed module · full = the whole suite"},
    {"key": "implement_approved", "label": "Implement approved changes", "kind": "toggle", "value": True,
     "description": "Off = approve only; the code is left for you"},
    {"key": "restart_when_idle", "label": "Restart to load changes when idle", "kind": "toggle", "value": True,
     "description": "Applied Python changes take effect after a restart"},
    {"key": "only_when_idle", "label": "Only work while I'm away", "kind": "toggle", "value": False,
     "description": "Pauses whenever you're using Nyx"},
    {"key": "idle_minutes", "label": "Away after (minutes)", "kind": "slider", "min": 1, "max": 120, "step": 1, "value": 10,
     "description": "How long without input counts as away"},
    {"key": "active_from_hour", "label": "Work from (hour)", "kind": "slider", "min": 0, "max": 23, "step": 1, "value": 0,
     "description": "Local time the autopilot may start working"},
    {"key": "active_to_hour", "label": "Work until (hour)", "kind": "slider", "min": 1, "max": 24, "step": 1, "value": 24,
     "description": "Local time it stops (24 = midnight)"},
    {"key": "study_cycle_minutes", "label": "Study cycle (minutes)", "kind": "slider", "min": 2, "max": 60, "step": 1, "value": 10,
     "description": "How often a study phase reads new material"},
    {"key": "research_queries", "label": "Web searches per study cycle", "kind": "slider", "min": 0, "max": 5, "step": 1, "value": 1,
     "description": "0 = never search the web while studying"},
    {"key": "focus_areas", "label": "Focus on", "kind": "multiselect",
     "options": ["speed", "reliability", "tests", "ui", "learning", "security", "features"], "value": ["reliability", "speed"],
     "description": "What improvements should aim at"},
    {"key": "study_sources", "label": "Study from", "kind": "multiselect",
     "options": ["recent chats", "feedback", "errors", "codebase", "web"], "value": ["recent chats", "feedback", "errors", "codebase"],
     "description": "Where lessons come from"},
]
_BUILTIN_KEYS = {c["key"] for c in DEFAULT_CONTROLS}

ModelFn = Callable[..., str]


class AutopilotError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Plans from words
# ---------------------------------------------------------------------------

_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|d|day|days)\b", re.I)


def _minutes(amount: str, unit: str) -> float:
    value = float(amount)
    unit = unit.lower()
    if unit.startswith("d"):
        return value * 24 * 60
    if unit.startswith("h"):
        return value * 60
    return value


def parse_instruction(text: str) -> Dict[str, Any]:
    """Offline parser for the common phrasings; the model can also pass structure directly.

    Returns ``{"phases": [{"kind", "minutes"}], "loop": bool, "hours": float|None, "auto_approve": bool, "focus": str}``.
    """
    raw = (text or "").strip()
    lower = raw.lower()
    auto = bool(re.search(r"auto[\s-]?(?:approv|apply)|(?:approve|apply) (?:all|every)|without asking|don'?t ask|self[\s-]?check", lower))
    loop = bool(re.search(r"\bloop|\brepeat|until i stop|until stopped|forever|keep going|over and over|\bcycle", lower))

    # A duration written right after a phase word belongs to that phase: "study for 1 hour", "improve 2h",
    # "a detox hour", "rest 30 min". Any other duration ("for the next 22 hours") is the run's window.
    phases: List[Dict[str, Any]] = []
    claimed: List[range] = []
    unit = r"(h|hrs?|hours?|m|mins?|minutes?|d|days?)\b"
    for match in re.finditer(r"\b(study|learn|research|improv|detox|rest\b|break\b)\w*(?:\s+(?:for|during))?"
                             rf"(?:\s+(?:(an?|one)\s+(hour|minute)|(\d+(?:\.\d+)?)\s*{unit}))?", lower):
        word = match.group(1)
        kind = ("study" if word in ("study", "learn", "research") else "improve" if word == "improv"
                else "detox" if word == "detox" else "rest")
        minutes = 0.0
        if match.group(3):
            minutes = 60.0 if match.group(3) == "hour" else 1.0
        elif match.group(4):
            minutes = _minutes(match.group(4), match.group(5))
            claimed.append(range(match.start(4), match.end(5)))
        if phases and phases[-1]["kind"] == kind and not (phases[-1]["minutes"] and minutes):
            phases[-1]["minutes"] = phases[-1]["minutes"] or minutes  # "improve … improvements for 22 hours"
            continue
        phases.append({"kind": kind, "minutes": minutes})
    if re.search(r"\b(?:a|an|one)\s+detox\s+hour\b|\bdetox\s+hour\b", lower):
        for phase in phases:
            if phase["kind"] == "detox" and not phase["minutes"]:
                phase["minutes"] = 60.0

    hours: Optional[float] = None
    for match in re.finditer(rf"(\d+(?:\.\d+)?)\s*{unit}", lower):
        if not any(match.start() in span for span in claimed):
            hours = _minutes(match.group(1), match.group(2)) / 60
            break

    if not phases:
        phases = [{"kind": "improve", "minutes": 0.0}]
    if len(phases) == 1 and not phases[0]["minutes"]:
        phases[0]["minutes"] = hours * 60 if hours else 60.0
    for phase in phases:
        phase["minutes"] = phase["minutes"] or 60.0
    if hours is None and len(phases) == 1 and not loop:
        hours = phases[0]["minutes"] / 60
    focus = re.sub(r"\s+", " ", raw)[:300]
    return {"phases": phases, "loop": loop, "hours": hours, "auto_approve": auto, "focus": focus}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------


@dataclass
class Run:
    run_id: str
    instruction: str
    phases: List[Dict[str, Any]]
    loop: bool = False
    auto_approve: bool = False
    focus: str = ""
    created_at: float = field(default_factory=time.time)
    ends_at: Optional[float] = None
    status: str = "active"            # active | paused | waiting | stopped | done | error
    phase_index: int = 0
    phase_started_at: float = field(default_factory=time.time)
    cycles: int = 0
    work: str = "Starting"
    started_by: str = "owner"
    stats: Dict[str, int] = field(default_factory=lambda: {
        "study_cycles": 0, "lessons": 0, "research": 0, "sessions": 0, "proposals": 0, "approved": 0,
        "applied": 0, "rejected": 0, "failed": 0, "waiting_for_owner": 0, "duplicates": 0, "approved_only": 0})
    log: List[Dict[str, Any]] = field(default_factory=list)
    paused_at: Optional[float] = None

    def phase(self) -> Dict[str, Any]:
        return self.phases[min(self.phase_index, len(self.phases) - 1)]

    def phase_ends_at(self) -> float:
        return self.phase_started_at + float(self.phase().get("minutes", 60)) * 60

    def view(self, now: Optional[float] = None) -> Dict[str, Any]:
        now = now or time.time()
        data = asdict(self)
        data["phase"] = self.phase()
        data["phase_remaining_seconds"] = max(0.0, round(self.phase_ends_at() - now, 1)) if self.status in ("active", "waiting") else None
        data["remaining_seconds"] = max(0.0, round(self.ends_at - now, 1)) if self.ends_at else None
        data["log"] = self.log[-40:]
        return data


class AutopilotManager:
    def __init__(self, *, model_fn: Optional[ModelFn] = None, engine: Any = None, preparer: Optional[Callable[..., Any]] = None,
                 committer: Optional[Callable[..., Any]] = None,
                 change_log: Any = None, clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
                 store_dir: Optional[Path] = None, threaded: bool = True, idle_fn: Optional[Callable[[], float]] = None,
                 hour_fn: Optional[Callable[[], int]] = None, web_fn: Optional[Callable[[str], str]] = None) -> None:
        self._model_fn = model_fn
        self._engine = engine
        self._preparer = preparer
        self._committer = committer
        self._web_fn = web_fn
        self._change_log = change_log
        self.clock = clock
        self._sleep = sleep
        self._store_dir = store_dir
        self._threaded = threaded
        self._idle_fn = idle_fn
        self._hour_fn = hour_fn
        self._lock = threading.RLock()
        self._runs: Dict[str, Run] = {}
        self._controls: List[Dict[str, Any]] = []
        self._workers: Dict[str, threading.Thread] = {}
        self._stops: Dict[str, threading.Event] = {}
        self._loaded = False
        self._approval_times: List[float] = []
        self.restart_pending = False

    # --- storage -----------------------------------------------------------------

    def _dir(self) -> Path:
        path = self._store_dir or data_path("autopilot")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            data = json.loads((self._dir() / "runs.json").read_text(encoding="utf-8"))
            for item in data.get("runs", []):
                run = Run(**{k: v for k, v in item.items() if k in Run.__dataclass_fields__})
                self._runs[run.run_id] = run
        except (OSError, ValueError, TypeError):
            pass
        try:
            saved = json.loads((self._dir() / "controls.json").read_text(encoding="utf-8"))
            saved = saved.get("controls", []) if isinstance(saved, dict) else []
        except (OSError, ValueError):
            saved = []
        by_key = {c.get("key"): c for c in saved if isinstance(c, dict)}
        controls = []
        for default in DEFAULT_CONTROLS:
            merged = dict(default)
            if default["key"] in by_key:
                merged["value"] = _coerce(default, by_key[default["key"]].get("value", default["value"]))
            controls.append(merged)
        controls += [c for c in saved if isinstance(c, dict) and c.get("key") not in _BUILTIN_KEYS]
        self._controls = controls

    def _save(self) -> None:
        runs = sorted(self._runs.values(), key=lambda r: -r.created_at)[:_MAX_RUNS_KEPT]
        (self._dir() / "runs.json").write_text(json.dumps({"runs": [asdict(r) for r in runs]}, indent=1), encoding="utf-8")
        (self._dir() / "controls.json").write_text(json.dumps({"controls": self._controls}, indent=1), encoding="utf-8")

    # --- public API ---------------------------------------------------------------

    def start(self, instruction: str = "", *, phases: Optional[List[Dict[str, Any]]] = None, loop: Optional[bool] = None,
              hours: Optional[float] = None, auto_approve: Optional[bool] = None, focus: str = "",
              started_by: str = "owner", replace: bool = True) -> Dict[str, Any]:
        parsed = parse_instruction(instruction) if instruction else {"phases": [], "loop": False, "hours": None, "auto_approve": False, "focus": ""}
        plan_phases = [p for p in (phases or parsed["phases"]) if isinstance(p, dict)]
        clean = []
        for phase in plan_phases:
            kind = str(phase.get("kind", "")).lower()
            if kind not in PHASE_KINDS:
                raise AutopilotError(f"Unknown phase {kind!r}; use study, improve, detox or rest.")
            minutes = float(phase.get("minutes") or 0)
            if not 1 <= minutes <= 14 * 24 * 60:
                raise AutopilotError("Each phase must be between 1 minute and 14 days.")
            clean.append({"kind": kind, "minutes": minutes, "focus": str(phase.get("focus", ""))[:200]})
        if not clean:
            raise AutopilotError("Say what to do, e.g. \"study 1 hour, improve 1 hour, loop\".")
        window_hours = hours if hours is not None else parsed["hours"]
        if window_hours is not None and not 0 < float(window_hours) <= 24 * 30:
            raise AutopilotError("A run can last up to 30 days.")
        with self._lock:
            self._ensure_loaded()
            now = self.clock()
            for other in self._runs.values():
                if other.status in ("active", "paused", "waiting"):
                    if not replace:
                        raise AutopilotError("An autopilot run is already going. Stop it first.")
                    self._stop_locked(other, "Replaced by a new run")
            run = Run(run_id=uuid.uuid4().hex[:10], instruction=(instruction or "").strip()[:500], phases=clean,
                      loop=bool(parsed["loop"] if loop is None else loop),
                      auto_approve=bool(parsed["auto_approve"] if auto_approve is None else auto_approve),
                      focus=(focus or parsed["focus"] or instruction or "")[:300], created_at=now,
                      ends_at=(now + float(window_hours) * 3600) if window_hours else None,
                      phase_started_at=now, started_by=started_by)
            self._runs[run.run_id] = run
            self._log(run, "start", self._describe(run))
            self._save()
        self._publish(run)
        if self._threaded:
            self._spawn(run)
        return run.view(self.clock())

    def stop(self, run_id: str = "", reason: str = "Stopped by the owner") -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            run = self._find(run_id)
            self._stop_locked(run, reason)
            self._save()
        self._publish(run)
        return run.view(self.clock())

    def pause(self, run_id: str = "") -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            run = self._find(run_id)
            if run.status in ("active", "waiting"):
                run.status, run.paused_at, run.work = "paused", self.clock(), "Paused"
                self._log(run, "pause", "Paused")
                self._save()
        self._publish(run)
        return run.view(self.clock())

    def resume(self, run_id: str = "") -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            run = self._find(run_id)
            if run.status == "paused":
                shift = self.clock() - (run.paused_at or self.clock())
                run.phase_started_at += shift
                if run.ends_at:
                    run.ends_at += shift
                run.status, run.paused_at = "active", None
                self._log(run, "resume", "Resumed")
                self._save()
        self._publish(run)
        if self._threaded:
            self._spawn(run)
        return run.view(self.clock())

    def runs(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure_loaded()
            return [r.view(self.clock()) for r in sorted(self._runs.values(), key=lambda r: -r.created_at)]

    def active(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure_loaded()
            run = next((r for r in self._runs.values() if r.status in ("active", "paused", "waiting")), None)
            return run.view(self.clock()) if run else None

    def controls(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._ensure_loaded()
            return [dict(c) for c in self._controls]

    def control_values(self) -> Dict[str, Any]:
        return {c["key"]: c.get("value") for c in self.controls()}

    def set_control(self, key: str, value: Any, by: str = "owner") -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            control = next((c for c in self._controls if c["key"] == key), None)
            if control is None:
                raise AutopilotError(f"No control called {key!r}.")
            control["value"] = _coerce(control, value)
            control["changed_by"] = by
            self._save()
        self._publish(None)
        return dict(control)

    def add_control(self, spec: Dict[str, Any], by: str = "nyx") -> Dict[str, Any]:
        key = re.sub(r"[^a-z0-9_]+", "_", str(spec.get("key") or spec.get("label") or "").lower()).strip("_")[:40]
        kind = str(spec.get("kind", "slider")).lower()
        if not key or not spec.get("label"):
            raise AutopilotError("A control needs a key and a label.")
        if kind not in CONTROL_KINDS:
            raise AutopilotError(f"kind must be one of {', '.join(CONTROL_KINDS)}.")
        control: Dict[str, Any] = {"key": key, "label": str(spec["label"])[:60], "kind": kind,
                                   "description": str(spec.get("description", ""))[:200],
                                   "affects": str(spec.get("affects", spec.get("description", "")))[:300],
                                   "added_by": by, "custom": True}
        if kind == "slider":
            lo, hi = float(spec.get("min", 0)), float(spec.get("max", 10))
            if hi <= lo:
                raise AutopilotError("A slider's max must be above its min.")
            control.update(min=lo, max=hi, step=float(spec.get("step", 1) or 1))
            control["value"] = _coerce(control, spec.get("value", lo))
        elif kind in ("select", "multiselect"):
            options = [str(o)[:40] for o in (spec.get("options") or []) if str(o).strip()][:20]
            if not options:
                raise AutopilotError("A picker needs options.")
            control["options"] = options
            control["value"] = _coerce(control, spec.get("value", [] if kind == "multiselect" else options[0]))
        elif kind == "toggle":
            control["value"] = _coerce(control, spec.get("value", False))
        else:
            control["value"] = str(spec.get("value", ""))[:200]
        with self._lock:
            self._ensure_loaded()
            if key in _BUILTIN_KEYS:
                raise AutopilotError(f"{key} is a built-in control; change its value instead.")
            self._controls = [c for c in self._controls if c["key"] != key] + [control]
            self._save()
        self._publish(None)
        return control

    def remove_control(self, key: str) -> None:
        with self._lock:
            self._ensure_loaded()
            if key in _BUILTIN_KEYS:
                raise AutopilotError("Built-in controls can't be removed.")
            before = len(self._controls)
            self._controls = [c for c in self._controls if c["key"] != key]
            if len(self._controls) == before:
                raise AutopilotError(f"No control called {key!r}.")
            self._save()
        self._publish(None)

    def lessons(self, limit: int = 30) -> List[Dict[str, Any]]:
        path = self._dir() / "lessons.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return []
        out = []
        for line in reversed(lines):
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def resume_on_startup(self) -> None:
        """Continue runs that were active when the engine stopped (restarts included)."""
        with self._lock:
            self._ensure_loaded()
            runs = [r for r in self._runs.values() if r.status in ("active", "waiting")]
        for run in runs:
            self._log(run, "resume", "Engine restarted — continuing")
            if self._threaded:
                self._spawn(run)

    # --- the loop ------------------------------------------------------------------

    def _spawn(self, run: Run) -> None:
        with self._lock:
            existing = self._workers.get(run.run_id)
            if existing and existing.is_alive():
                return
            stop = threading.Event()
            self._stops[run.run_id] = stop
            thread = threading.Thread(target=self._worker, args=(run.run_id, stop), name=f"nyx-autopilot-{run.run_id}", daemon=True)
            self._workers[run.run_id] = thread
        thread.start()

    def _worker(self, run_id: str, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                if not self.step(run_id, stop):
                    break
            except Exception as error:  # noqa: BLE001 - keep the run alive; record why a step failed
                with self._lock:
                    run = self._runs.get(run_id)
                    if run:
                        self._log(run, "error", f"{type(error).__name__}: {str(error)[:200]}")
                        self._save()
                _LOG.warning("autopilot step failed: %s", error)
                self._wait(30, stop, None)
            self._maybe_restart()

    def step(self, run_id: str, stop: Optional[threading.Event] = None) -> bool:
        """One unit of work. Returns False when the run is over (or paused)."""
        with self._lock:
            self._ensure_loaded()
            run = self._runs.get(run_id)
            if run is None:
                return False
            if run.status in ("stopped", "done", "error", "paused"):
                return False
            self._advance(run)
            if run.status not in ("active", "waiting"):
                self._save()
                self._publish(run)
                return False
            reason = self._gate(run)
            if reason:
                if run.status != "waiting" or run.work != reason:
                    run.status, run.work = "waiting", reason
                    self._log(run, "wait", reason)
                    self._save()
                    self._publish(run)
            else:
                run.status = "active"
            kind = run.phase()["kind"]
            deadline = min(run.phase_ends_at(), run.ends_at or float("inf"))
        if reason:
            self._wait(60, stop, deadline)
            return True
        if kind == "study":
            self._study_unit(run, deadline, stop)
        elif kind == "improve":
            self._improve_unit(run, deadline, stop)
        elif kind == "detox":
            self._detox_unit(run, deadline, stop)
        else:
            with self._lock:
                run.work = "Resting"
            self._publish(run)
            self._wait(max(1.0, deadline - self.clock()), stop, deadline)
        return True

    def _advance(self, run: Run) -> None:
        now = self.clock()
        if run.ends_at and now >= run.ends_at:
            run.status, run.work = "done", "Finished the scheduled time"
            self._log(run, "done", "Time window ended")
            return
        while now >= run.phase_ends_at():
            previous_end = run.phase_ends_at()
            if run.phase_index + 1 < len(run.phases):
                run.phase_index += 1
            elif run.loop:
                run.phase_index = 0
                run.cycles += 1
            else:
                run.status, run.work = "done", "All phases finished"
                self._log(run, "done", "All phases finished")
                return
            run.phase_started_at = previous_end
            if now - previous_end > float(run.phase().get("minutes", 60)) * 60:
                run.phase_started_at = now  # the engine was off for a whole phase: start this one fresh
            self._log(run, "phase", f"{run.phase()['kind'].capitalize()} for {_fmt_minutes(run.phase()['minutes'])}")

    def _gate(self, run: Run) -> str:
        values = self.control_values()
        hour = self._hour_fn() if self._hour_fn else time.localtime(self.clock()).tm_hour
        start, end = int(values.get("active_from_hour", 0)), int(values.get("active_to_hour", 24))
        inside = start <= hour < end if start < end else (hour >= start or hour < end)
        if not inside:
            return f"Waiting for working hours ({start:02d}:00–{end % 24:02d}:00)"
        if values.get("only_when_idle"):
            idle = self._idle_fn() if self._idle_fn else _presence_idle()
            if idle < float(values.get("idle_minutes", 10)) * 60:
                return "Waiting until you're away"
        return ""

    def _wait(self, seconds: float, stop: Optional[threading.Event], deadline: Optional[float]) -> None:
        end = self.clock() + seconds
        if deadline is not None:
            end = min(end, deadline)
        while self.clock() < end:
            if stop is not None and stop.is_set():
                return
            chunk = min(5.0, end - self.clock())
            if chunk <= 0:
                return
            self._sleep(chunk)
            if not self._threaded:
                return

    # --- study ----------------------------------------------------------------------

    def _study_unit(self, run: Run, deadline: float, stop: Optional[threading.Event]) -> None:
        values = self.control_values()
        with self._lock:
            run.work = "Studying: reading recent activity"
        self._publish(run)
        material = gather_material(values.get("study_sources") or [])
        prompt = study_prompt(run, material, self.controls())
        # 3000 tokens: at 1500 the reply was cut off inside the lessons list, and every study cycle said
        # "Nothing new to learn" (2026-09-16).
        reply = self._model(prompt, system="You are Nyx's study partner. Extract concrete lessons as JSON only. Keep each field short.",
                            max_tokens=3000, role="reading_text")
        lessons = parse_lessons(reply)
        research_done = 0
        if "web" in (values.get("study_sources") or []):
            for lesson in lessons[: int(values.get("research_queries", 1) or 0)]:
                query = lesson.get("research_query")
                if not query:
                    continue
                summary = self._research(query)
                if summary:
                    lesson["research"] = summary
                    research_done += 1
        with self._lock:
            for lesson in lessons:
                lesson.update(run_id=run.run_id, ts=self.clock())
                self._append_lesson(lesson)
            run.stats["study_cycles"] += 1
            run.stats["lessons"] += len(lessons)
            run.stats["research"] += research_done
            run.work = f"Studied: {len(lessons)} lesson{'s' if len(lessons) != 1 else ''}"
            self._log(run, "study", "; ".join(l.get("topic", "") for l in lessons[:4]) or "Nothing new to learn")
            self._save()
        self._publish(run)
        _feed_brain(lessons)
        cycle = float(values.get("study_cycle_minutes", 10)) * 60
        self._wait(cycle, stop, deadline)

    def _research(self, query: str) -> str:
        try:
            import web_access

            results = web_access.search_results(query)[:5]
        except Exception:
            return ""
        if not results:
            return ""
        text = "\n".join(f"- {r.get('title', '')}: {r.get('snippet', '')} ({r.get('url', '')})" for r in results)
        try:
            return self._model(f"Summarize what these search results teach about: {query}\n\n{text}\n\nThree sentences, concrete.",
                               system="Summarize precisely.", max_tokens=300, role="reading_text")[:800]
        except Exception:
            return text[:800]

    def _append_lesson(self, lesson: Dict[str, Any]) -> None:
        with open(self._dir() / "lessons.jsonl", "a", encoding="utf-8") as handle:
            handle.write(json.dumps(lesson, ensure_ascii=False) + "\n")

    # --- improve ----------------------------------------------------------------------

    def _improve_unit(self, run: Run, deadline: float, stop: Optional[threading.Event], light: bool = False) -> None:
        values = self.control_values()
        engine = self._engine_obj()
        goal = compose_goal(run, self.lessons(8), self.controls(), light=light)
        budget = max(60.0, min(900.0, deadline - self.clock()))
        with self._lock:
            run.work = "Improving: analysing the code"
        self._publish(run)
        try:
            session = engine.start(goal, time_budget_seconds=budget, max_power=int(values.get("aggressiveness", 3)) >= 4 and not light)
        except Exception as error:  # noqa: BLE001 - e.g. the owner started a manual session
            with self._lock:
                self._log(run, "wait", f"Could not start analysis: {str(error)[:160]}")
            self._wait(60, stop, deadline)
            return
        session_id = session["session_id"]
        with self._lock:
            run.stats["sessions"] += 1
        polls = 0
        while (engine.get(session_id) or {}).get("status") in ("running", "stopping") and polls < 5000:
            if (stop is not None and stop.is_set()) or self.clock() >= deadline or self._run_over(run):
                engine.stop(session_id)
            polls += 1
            self._sleep(2.0)
        state = engine.get(session_id) or {}
        change_ids = list(state.get("change_ids", []))
        with self._lock:
            run.stats["proposals"] += len(change_ids)
            self._log(run, "improve", f"Analysis found {len(change_ids)} improvement{'s' if len(change_ids) != 1 else ''}"
                      + (f" ({state.get('error')})" if state.get("error") else ""))
            self._save()
        for change_id in change_ids:
            if (stop is not None and stop.is_set()) or self._run_over(run):
                break
            self._handle_change(run, change_id)
        self._publish(run)
        if not change_ids:
            self._wait(120, stop, deadline)

    def _run_over(self, run: Run) -> bool:
        return run.status not in ("active", "waiting")

    def _handle_change(self, run: Run, change_id: str) -> None:
        import improve_review

        log = self._change_log_obj()
        change = log.get(change_id)
        if change is None:
            return
        values = self.control_values()
        data = change.as_dict()
        window_open = run.auto_approve and (run.ends_at is None or self.clock() < run.ends_at)

        # 1. The same idea again (open, applied or refused before) is closed without spending a model call.
        mine = float(data.get("created_at") or 0)
        others = [c for c in log.list_changes() if c.get("origin") == "agent" and c["id"] != change_id
                  and ((float(c.get("created_at") or 0) < mine and c.get("status") in improve_review.OPEN_STATUSES)
                       or improve_review.counts_as_decision(c))]
        duplicate = improve_review.find_duplicate(data, others)
        if duplicate is not None:
            try:
                log.reject(change_id, "Nyx (duplicate check)", f"Duplicate of “{duplicate['title'][:90]}” ({duplicate['status']})")
            except Exception:
                pass
            with self._lock:
                run.stats["duplicates"] = run.stats.get("duplicates", 0) + 1
            return
        if not window_open:
            try:
                log.submit_for_review(change_id)
            except Exception:
                pass
            with self._lock:
                run.stats["waiting_for_owner"] += 1
            return
        if self._approved_last_hour() >= int(values.get("max_changes_per_hour", 4)):
            try:
                log.submit_for_review(change_id)
            except Exception:
                pass
            with self._lock:
                run.stats["waiting_for_owner"] += 1
                self._log(run, "limit", f"Hourly limit reached — “{change.title[:60]}” waits for you")
            return

        # 2. Research: read the file, optionally the web, and judge the idea (not a diff that doesn't exist yet).
        with self._lock:
            run.work = f"Researching: {change.title[:70]}"
        self._publish(run)
        queue = improve_review.ReviewQueue(log=log, store=improve_review.ReviewStore(self._dir() / "reviews.json"),
                                           model_fn=self._model_fn_for_review(), values_fn=lambda: values,
                                           threaded=False, web_fn=self._web_fn)
        web = int(values.get("research_queries", 1) or 0) > 0 and "web" in (values.get("study_sources") or [])
        record = queue.research_and_recommend(data, web=web)
        if record.get("verdict") != "approve":
            try:
                log.attach_review(change_id, f"DENY\n{record.get('reasons', '')}", "Nyx research (autopilot)")
                log.reject(change_id, "Nyx research", str(record.get("reasons", ""))[:400])
            except Exception:
                pass
            with self._lock:
                run.stats["rejected"] += 1
                self._log(run, "reject", f"Research said no to “{change.title[:60]}”: {str(record.get('reasons', ''))[:120]}")
            return

        try:
            log.submit_for_review(change_id)
        except Exception:
            pass
        until = time.strftime("%a %H:%M", time.localtime(run.ends_at)) if run.ends_at else "stopped"
        log.approve(change_id, f"Autopilot (auto-approve authorised by the owner until {until})")
        with self._lock:
            run.stats["approved"] += 1
            self._approval_times.append(self.clock())
            self._log(run, "approve", f"Approved “{change.title[:70]}” — {str(record.get('reasons', ''))[:100]}")
            self._save()
        if not values.get("implement_approved", True):
            queue.store.update(change_id, implement={"state": "approved_only", "at": self.clock(),
                                                     "message": "Approved only — “Implement approved changes” is off, so the code is left for you."})
            with self._lock:
                run.stats["approved_only"] = run.stats.get("approved_only", 0) + 1
                self._log(run, "approve", "Not implemented: “Implement approved changes” is off — it waits in the review queue")
                self._save()
            self._publish(run)
            return

        # 3. Write + test in the sandbox, 4. critic reads the real diff, 5. apply.
        def step(text: str) -> None:
            with self._lock:
                run.work = f"{text}: {change.title[:60]}"
            self._publish(run)

        outcome = improve_review.implement_change(
            log.get(change_id).as_dict(), log, values=values, model_fn=self._model_fn_for_review(),
            preparer=self._preparer, committer=self._committer, publisher="Autopilot", reject_on_failure=True, on_step=step)
        queue.store.update(change_id, implement={**outcome, "at": self.clock()})
        with self._lock:
            if outcome["state"] == "applied":
                run.stats["applied"] += 1
                self.restart_pending = True
                self._log(run, "apply", outcome["message"][:200])
            elif outcome["state"] == "blocked":
                run.stats["rejected"] += 1
                self._log(run, "reject", f"Critic blocked the real diff for “{change.title[:60]}”")
            else:
                run.stats["failed"] += 1
                self._log(run, "fail", f"Not applied: {outcome['message'][:160]}")
            self._save()
        self._publish(run)

    def _model_fn_for_review(self) -> Optional[Callable[..., str]]:
        if self._model_fn is None:
            return None
        return lambda prompt, system="", max_tokens=800, **_kw: self._model_fn(prompt, system=system, max_tokens=max_tokens)

    def _approved_last_hour(self) -> int:
        cutoff = self.clock() - 3600
        self._approval_times = [t for t in self._approval_times if t >= cutoff]
        return len(self._approval_times)

    # --- detox -----------------------------------------------------------------------------

    def _detox_unit(self, run: Run, deadline: float, stop: Optional[threading.Event]) -> None:
        with self._lock:
            run.work = "Detox: consolidating what was learned"
        self._publish(run)
        notes = consolidate()
        with self._lock:
            self._log(run, "detox", notes)
            self._save()
        if self.clock() < deadline:
            self._improve_unit(run, deadline, stop, light=True)

    def _maybe_restart(self) -> None:
        if not self.restart_pending or not self.control_values().get("restart_when_idle", True):
            return
        try:
            from turn_registry import TURNS

            if TURNS.active(include_recent=False):
                return
            from improvement_engine import ENGINE

            if any(s["status"] in ("running", "stopping") for s in ENGINE.list_sessions()):
                return
            import server

            restart = server.ENGINE_HOOKS.get("restart")
        except Exception:
            return
        if callable(restart):
            self.restart_pending = False
            with self._lock:
                self._save()
            _LOG.info("autopilot restarting the engine to load applied changes")
            restart()

    # --- helpers -------------------------------------------------------------------------

    def _engine_obj(self) -> Any:
        if self._engine is not None:
            return self._engine
        from improvement_engine import ENGINE

        return ENGINE

    def _change_log_obj(self) -> Any:
        if self._change_log is not None:
            return self._change_log
        from change_review import CHANGE_LOG

        return CHANGE_LOG

    def _model(self, prompt: str, *, system: str = "", max_tokens: int = 1000, role: str = "reading_text") -> str:
        if self._model_fn is not None:
            return self._model_fn(prompt, system=system, max_tokens=max_tokens)
        from model_roles import MODEL_ROLES

        return MODEL_ROLES.run(role, prompt, system=system, max_tokens=max_tokens).text

    def _find(self, run_id: str) -> Run:
        if run_id:
            run = self._runs.get(run_id)
        else:
            run = next((r for r in sorted(self._runs.values(), key=lambda r: -r.created_at)
                        if r.status in ("active", "paused", "waiting")), None)
        if run is None:
            raise AutopilotError("No autopilot run is going." if not run_id else "No such run.")
        return run

    def _stop_locked(self, run: Run, reason: str) -> None:
        if run.status in ("active", "paused", "waiting"):
            run.status, run.work = "stopped", reason
            self._log(run, "stop", reason)
        stop = self._stops.get(run.run_id)
        if stop:
            stop.set()

    def _log(self, run: Run, kind: str, text: str) -> None:
        run.log.append({"ts": self.clock(), "kind": kind, "text": text[:300]})
        del run.log[:-_MAX_LOG]

    def _describe(self, run: Run) -> str:
        parts = " → ".join(f"{p['kind']} {_fmt_minutes(p['minutes'])}" for p in run.phases)
        window = f" for {_fmt_minutes((run.ends_at - run.created_at) / 60)}" if run.ends_at else " until stopped"
        return f"{parts}{' (looping)' if run.loop else ''}{window}{' · auto-approve on' if run.auto_approve else ''}"

    def _publish(self, run: Optional[Run]) -> None:
        try:
            from agent_events import publish_ui

            publish_ui("improve.autopilot", run=run.view(self.clock()) if run else None)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Prompts, material, parsing
# ---------------------------------------------------------------------------


def _coerce(control: Dict[str, Any], value: Any) -> Any:
    kind = control.get("kind")
    if kind == "slider":
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = float(control.get("min", 0))
        number = min(max(number, float(control.get("min", 0))), float(control.get("max", 10)))
        step = float(control.get("step", 1) or 1)
        number = round(round(number / step) * step, 4)
        return int(number) if float(number).is_integer() else number
    if kind == "toggle":
        return value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes", "on")
    if kind == "select":
        options = control.get("options") or []
        return value if value in options else (options[0] if options else "")
    if kind == "multiselect":
        options = control.get("options") or []
        items = value if isinstance(value, list) else [v.strip() for v in str(value).split(",")]
        return [v for v in items if v in options]
    return str(value)[:200]


def _fmt_minutes(minutes: float) -> str:
    minutes = float(minutes)
    if minutes >= 60 * 24 and minutes % (60 * 24) == 0:
        days = int(minutes // (60 * 24))
        return f"{days} day{'s' if days != 1 else ''}"
    if minutes >= 60:
        hours = minutes / 60
        return f"{hours:g} hour{'s' if hours != 1 else ''}"
    return f"{minutes:g} min"


def _presence_idle() -> float:
    try:
        import presence

        return presence.idle_seconds()
    except Exception:
        return 10 ** 9


def gather_material(sources: List[str], limit_chars: int = 9000) -> Dict[str, str]:
    """What a study cycle reads. Each source is best-effort and size-capped."""
    material: Dict[str, str] = {}
    if "recent chats" in sources or "feedback" in sources:
        try:
            lines = data_path("learning/turns.jsonl").read_text(encoding="utf-8").splitlines()[-40:]
            turns = [json.loads(line) for line in lines if line.strip()]
            material["recent turns"] = "\n".join(
                f"- [{t.get('mode')}/{t.get('provider')} {int(t.get('latency_ms') or 0)}ms ok={t.get('ok')} tools={','.join(t.get('tools') or [])}] "
                f"{str(t.get('message', ''))[:160]}" for t in turns)
        except (OSError, ValueError):
            pass
    if "feedback" in sources:
        try:
            lines = data_path("learning/feedback.jsonl").read_text(encoding="utf-8").splitlines()[-20:]
            material["feedback"] = "\n".join(lines)[:2000]
        except OSError:
            pass
    if "errors" in sources:
        try:
            import launcher

            text = launcher.log_path().read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
            errors = [line for line in text if re.search(r"error|exception|traceback|failed|warning", line, re.I)][-40:]
            material["engine errors"] = "\n".join(errors)[:3000]
        except Exception:
            pass
    if "codebase" in sources:
        try:
            from improvement_engine import build_repo_map

            material["code map"] = "\n".join(f"{m['module']} ({m['lines']} lines) {m['doc'][:80]}" for m in build_repo_map()[:40])
        except Exception:
            pass
    total = 0
    for key in list(material):
        room = max(0, limit_chars - total)
        material[key] = material[key][:room]
        total += len(material[key])
    return material


def _control_text(controls: List[Dict[str, Any]]) -> str:
    lines = []
    for c in controls:
        value = ", ".join(c["value"]) if isinstance(c.get("value"), list) else c.get("value")
        meaning = c.get("affects") or c.get("description") or ""
        lines.append(f"- {c['label']}: {value}" + (f" — {meaning}" if meaning else ""))
    return "\n".join(lines)


def study_prompt(run: Run, material: Dict[str, str], controls: List[Dict[str, Any]]) -> str:
    body = "\n\n".join(f"## {k}\n{v}" for k, v in material.items() if v) or "(no new material)"
    return (
        "You are studying how Nyx (a local AI assistant) has been doing, to find what to improve next.\n"
        f"The owner's instruction for this autopilot run: {run.focus or run.instruction}\n\n"
        f"The owner's Improve-tab settings (follow them):\n{_control_text(controls)}\n\n{body}\n\n"
        'Reply with JSON only: {"lessons": [{"topic": "...", "insight": "what the evidence shows", '
        '"improvement": "a concrete change to make", "module": "file.py or empty", "evidence": "short quote", '
        '"research_query": "a web search that would help, or empty"}]}. At most 5 lessons; fewer is fine; no invented evidence.'
    )


def parse_lessons(reply: str) -> List[Dict[str, Any]]:
    text = reply or ""
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    body = fence.group(1) if fence else text
    start, end = body.find("{"), body.rfind("}")
    try:
        data = json.loads(body[start:end + 1]) if start != -1 and end > start else {}
    except ValueError:
        data = {}
    if not data.get("lessons") and '"lessons"' in body:
        # A reply cut off mid-list still holds whole lessons: take every complete {...} object in it.
        data = {"lessons": [_loads_object(chunk) for chunk in _complete_objects(body[body.find('"lessons"'):])]}
    lessons = []
    for item in (data.get("lessons") or [])[:5]:
        if isinstance(item, dict) and item.get("topic") and item.get("insight"):
            lessons.append({k: str(item.get(k, ""))[:400] for k in ("topic", "insight", "improvement", "module", "evidence", "research_query")})
    return lessons


def _complete_objects(text: str) -> List[str]:
    """Top-level {...} chunks that close properly, ignoring braces inside strings."""
    chunks, depth, start, in_string, escaped = [], 0, -1, False, False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start != -1:
                chunks.append(text[start:index + 1])
    return chunks


def _loads_object(chunk: str) -> Dict[str, Any]:
    try:
        value = json.loads(chunk)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def compose_goal(run: Run, lessons: List[Dict[str, Any]], controls: List[Dict[str, Any]], light: bool = False) -> str:
    phase_focus = run.phase().get("focus") or ""
    recent = "\n".join(f"- {l.get('improvement') or l.get('insight')} ({l.get('module') or 'any module'})" for l in lessons[:5])
    return (
        f"{'Light, reliability-first tidy-up. ' if light else ''}{phase_focus or run.focus or 'General improvement'}\n"
        f"Owner settings:\n{_control_text(controls)}"
        + (f"\nLessons from studying recent use:\n{recent}" if recent else "")
    )[:2500]


def _feed_brain(lessons: List[Dict[str, Any]]) -> None:
    try:
        import super_brain

        for lesson in lessons:
            super_brain.BRAIN.ingest(f"{lesson.get('topic')}: {lesson.get('insight')} {lesson.get('improvement')}",
                                     source="self-study", kind="lesson")
    except Exception:
        pass


def consolidate() -> str:
    """The detox work that needs no model: tidy caches and learned stores."""
    done = []
    try:
        from response_cache import RESPONSE_CACHE

        stats = RESPONSE_CACHE.stats()
        done.append(f"cache {stats.get('entries', 0)} answers ({stats.get('hit_rate', 0):.0%} hits)")
    except Exception:
        pass
    try:
        from learning import LEARNER

        stats = LEARNER.stats()
        done.append(f"learner {stats.get('total_turns', 0)} turns")
    except Exception:
        pass
    try:
        import super_brain

        done.append(super_brain.BRAIN.consolidate())
    except Exception:
        pass
    return "Consolidated: " + (", ".join(d for d in done if d) or "nothing to tidy")


AUTOPILOT = AutopilotManager()
