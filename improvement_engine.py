"""Self-improvement sessions: the owner points Nyx at its own base code.

The owner's ask: a place to tell the AI to improve itself — optionally with a
time budget ("analyze for 30 minutes") or at full power ("use everything you
have") — with every outcome landing as an approval-gated proposal, never a
direct edit. The gate already exists (``change_review.ChangeLog``: draft →
review → approve → publish, owner-only publish); this module feeds it.
(``self_improvement.py`` keeps its own, separate CLI proposal store.)

One session runs on one background thread:

1. **Map** — the repo as data: top-level modules with their docstring first
   lines and sizes, so the model reasons over the real codebase, not a guess.
2. **Analyze** — the assigned ``code_generation`` model-role model proposes
   concrete, file-specific improvements. Max power widens the pass (separate
   architecture / correctness / performance / tests angles) and raises the
   per-pass proposal cap; a time budget bounds how long analysis may run.
3. **File** — each accepted proposal becomes a ``ChangeLog.propose`` draft with
   ``origin=AGENT``. Nothing is applied here: the owner reads them in the
   Improve tab (or Admin → changes) and publishes only what they approve.

The model function is injectable. Tests pass a stub; production resolves the
owner's assigned model through :func:`_default_model_fn`.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from paths import PROJECT_DIR

_LOG = logging.getLogger("nyx.improvement_engine")

#: Hard ceiling on session length even when no budget is set (seconds).
_MAX_SESSION_SECONDS = 45 * 60

#: Directories the analyzer may map. The base code is the point; the venv,
#: frontend bundle, archives and scratch space are not.
_SCAN_EXCLUDE = ("frontend", ".venv", "_archive", "site", "system", "tests", "skills",
                 "node_modules", "local_pytest_tmp", "training", "data", "__pycache__",
                 "dist", "build")
_MAX_MODULES_IN_MAP = 60

#: Max-power analysis angles. A default session runs one combined pass.
_MAX_POWER_ANGLES = ("architecture and structure", "correctness and edge cases",
                     "performance and resource use", "missing tests and error handling")

ModelFn = Callable[..., str]
"""Signature: ``model_fn(prompt: str, *, system: str = "", max_tokens: int) -> str``.

Raises ``Exception`` on failure; the session records the message and stops.
"""


class SelfImprovementError(Exception):
    """A session-level request could not be carried out (unknown id, busy engine)."""


# --- repo map -----------------------------------------------------------------


def build_repo_map() -> List[Dict[str, Any]]:
    """The base code as data: one row per module.

    A row carries the module name, its size in lines, and the first line of its
    docstring — enough for the model to propose file-specific work without
    shipping the whole tree into a prompt. Sorted by size, biggest first: the
    largest modules are where improvement effort usually pays.
    """
    rows: List[Dict[str, Any]] = []
    try:
        entries = sorted(PROJECT_DIR.iterdir())
    except OSError:
        return rows
    for entry in entries:
        if entry.suffix == ".py" and entry.is_file():
            _add_module_row(rows, entry)
        elif entry.is_dir() and entry.name not in _SCAN_EXCLUDE and not entry.name.startswith("."):
            try:
                for child in sorted(entry.glob("*.py")):
                    _add_module_row(rows, child)
            except OSError:
                continue
    rows.sort(key=lambda r: -r["lines"])
    return rows[:_MAX_MODULES_IN_MAP]


def _add_module_row(rows: List[Dict[str, Any]], path: Any) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    lines = text.count("\n") + 1
    doc = ""
    match = re.search(r'"""(.{5,120})', text)
    if match:
        doc = " ".join(match.group(1).split())
    rows.append({"module": path.name,
                 "dir": path.parent.name if path.parent != PROJECT_DIR else "",
                 "lines": lines, "doc": doc})


# --- prompts and parsing ---------------------------------------------------------


def _repo_map_text(repo_map: List[Dict[str, Any]]) -> str:
    lines = []
    for row in repo_map:
        prefix = f"{row['dir']}/" if row.get("dir") else ""
        doc = f" — {row['doc']}" if row.get("doc") else ""
        lines.append(f"{prefix}{row['module']} ({row['lines']} lines){doc}")
    return "\n".join(lines)


def _analysis_prompt(goal: str, repo_map: List[Dict[str, Any]], angle: str, max_proposals: int,
                     known: Optional[List[str]] = None) -> str:
    angles = f" Focus on: {angle}." if angle else ""
    already = ""
    if known:
        # Without this the engine proposed the same five ideas every session (701 waiting on 2026-09-16).
        already = ("Already proposed, applied or refused — do NOT propose these again, even reworded:\n"
                   + "\n".join(f"- {title}" for title in known[:30]) + "\n\n")
    return (
        "You are analyzing an AI assistant's own Python codebase so it can improve itself.\n"
        f"The owner's goal: {goal.strip() or 'general improvement of the codebase'}.{angles}\n\n"
        "The modules:\n\n" + _repo_map_text(repo_map) + "\n\n" + already +
        f"Propose at most {max_proposals} concrete improvements. For each, answer exactly:\n\n"
        "TITLE: <short title>\n"
        "FILE: <module filename from the list above>\n"
        "CHANGE: <what specifically to change in that file, 1-3 sentences>\n"
        "WHY: <the benefit, 1 sentence>\n"
        "---\n\n"
        "Only propose changes to files that appear in the list. A proposal that would\n"
        "weaken security, permissions, or tests is worse than no proposal; skip it.\n"
        "If nothing is worth changing, say NONE and nothing else."
    )


_PROP_BLOCK = re.compile(
    r"TITLE:\s*(?P<title>.+?)\s*\n+\s*FILE:\s*(?P<file>.+?)\s*\n+\s*CHANGE:\s*(?P<change>.+?)\s*\n+\s*WHY:\s*(?P<why>.+?)(?:\n\s*---|\Z)",
    re.DOTALL,
)


def parse_proposals(reply: str) -> List[Dict[str, str]]:
    """Extract structured proposals from a model reply; empty when NONE."""
    if not reply or reply.strip().upper().startswith("NONE"):
        return []
    proposals: List[Dict[str, str]] = []
    for match in _PROP_BLOCK.finditer(reply):
        title = " ".join(match.group("title").split())
        filename = match.group("file").strip().split("/")[-1].strip()
        change = " ".join(match.group("change").split())
        why = " ".join(match.group("why").split())
        if not (title and filename.endswith(".py") and change):
            continue
        proposals.append({"title": title[:120], "file": filename[:120],
                          "change": change[:600], "why": why[:300]})
    return proposals


# --- sessions -------------------------------------------------------------------


@dataclass
class ImprovementSession:
    session_id: str
    goal: str
    time_budget_seconds: float = 0.0     # 0 = no budget (still bounded by _MAX_SESSION_SECONDS)
    max_power: bool = False
    status: str = "running"              # running | done | error | stopping | stopped
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    error: str = ""
    modules_scanned: int = 0
    proposals_filed: int = 0
    change_ids: List[str] = field(default_factory=list)
    repeats_skipped: int = 0
    progress: str = "Starting"
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        elapsed = (self.ended_at or time.time()) - self.started_at
        return {
            "session_id": self.session_id, "goal": self.goal,
            "time_budget_seconds": self.time_budget_seconds, "max_power": self.max_power,
            "status": self.status, "error": self.error,
            "started_at": self.started_at, "ended_at": self.ended_at,
            "elapsed_seconds": round(elapsed, 1),
            "time_remaining_seconds": self._remaining(),
            "modules_scanned": self.modules_scanned,
            "proposals_filed": self.proposals_filed, "change_ids": list(self.change_ids),
            "repeats_skipped": self.repeats_skipped,
            "progress": self.progress, "notes": list(self.notes)[-12:],
        }

    def _remaining(self) -> Optional[float]:
        if not self.time_budget_seconds:
            return None
        return max(0.0, round(self.time_budget_seconds - (time.time() - self.started_at), 1))


class SelfImprovementEngine:
    """Runs analysis sessions and files their output as draft changes."""

    def __init__(self, model_fn: Optional[ModelFn] = None, max_concurrent: int = 1) -> None:
        self._model_fn = model_fn
        self._sessions: Dict[str, ImprovementSession] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._max_concurrent = max_concurrent

    # --- public API ---------------------------------------------------------

    def start(self, goal: str, *, time_budget_seconds: float = 0.0,
              max_power: bool = False, model_fn: Optional[ModelFn] = None) -> Dict[str, Any]:
        """Start a session; returns its view immediately (it runs in background)."""
        clean_goal = (goal or "").strip()
        if not clean_goal:
            raise ValueError("Describe what you want improved.")
        with self._lock:
            running = [s for s in self._sessions.values() if s.status == "running"]
            if len(running) >= self._max_concurrent:
                raise RuntimeError("A self-improvement session is already running. Stop it first.")
            session = ImprovementSession(
                session_id=uuid.uuid4().hex[:12], goal=clean_goal,
                time_budget_seconds=max(0.0, float(time_budget_seconds or 0.0)),
                max_power=bool(max_power),
            )
            self._sessions[session.session_id] = session
            thread = threading.Thread(
                target=self._run, args=(session, self._resolve_model_fn(model_fn)),
                name=f"nyx-improve-{session.session_id}", daemon=True,
            )
            self._threads[session.session_id] = thread
        thread.start()
        return session.as_dict()

    def stop(self, session_id: str) -> Dict[str, Any]:
        """Ask a session to finish at the next boundary. Cooperative, not abrupt."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise SelfImprovementError("No such session.")
            if session.status == "running":
                session.status = "stopping"
                session.progress = "Stopping after the current step"
            return session.as_dict()

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            return session.as_dict() if session else None

    def list_sessions(self) -> List[Dict[str, Any]]:
        with self._lock:
            sessions = sorted(self._sessions.values(), key=lambda s: -s.started_at)
            return [s.as_dict() for s in sessions]

    # --- internals -----------------------------------------------------------

    def _resolve_model_fn(self, explicit: Optional[ModelFn]) -> ModelFn:
        """Explicit argument wins, then the constructor's, then model roles."""
        if explicit is not None:
            return explicit
        if self._model_fn is not None:
            return self._model_fn
        return _default_model_fn()

    def _timed_out(self, session: ImprovementSession) -> bool:
        if session.time_budget_seconds <= 0:
            return False
        return time.time() >= session.started_at + min(session.time_budget_seconds, _MAX_SESSION_SECONDS)

    def _set_progress(self, session: ImprovementSession, text: str) -> None:
        session.progress = text
        try:
            from agent_events import publish_activity

            publish_activity("improve.progress", session_id=session.session_id, progress=text,
                             status=session.status, proposals=session.proposals_filed)
        except Exception:
            pass

    def _run(self, session: ImprovementSession, model_fn: ModelFn) -> None:
        try:
            self._set_progress(session, "Mapping the base code")
            repo_map = build_repo_map()
            session.modules_scanned = len(repo_map)
            if not repo_map:
                raise RuntimeError("Could not read the project directory.")

            angles = _MAX_POWER_ANGLES if session.max_power else (None,)
            per_pass_cap = 4 if session.max_power else 3
            system = (
                "You are Nyx's self-improvement analyst. You propose changes to the "
                "codebase you yourself run on; be concrete and conservative. Reply in "
                "the exact TITLE/FILE/CHANGE/WHY format, or NONE."
            )
            for index, angle in enumerate(angles):
                if session.status in ("stopping", "stopped"):
                    session.status = "stopped"
                    break
                if index > 0 and self._timed_out(session):
                    self._set_progress(session, "Time budget reached — stopping")
                    break
                self._set_progress(session, f"Analyzing ({angle})" if angle else "Analyzing")
                prompt = _analysis_prompt(session.goal, repo_map, angle or "", per_pass_cap, _known_titles())
                try:
                    reply = model_fn(prompt, system=system, max_tokens=1400)
                except Exception as error:  # noqa: BLE001 - first pass fails the session
                    if index == 0:
                        raise RuntimeError(f"Analysis model failed: {error}") from error
                    session.notes.append(f"pass {index + 1} failed: {error}")
                    continue
                for item in parse_proposals(reply):
                    if self._timed_out(session) or session.status in ("stopping", "stopped"):
                        break
                    self._file_proposal(session, item)
                self._set_progress(session, f"Filing — {session.proposals_filed} proposals so far")

            # Finalize the terminal state here, in the thread, whatever the
            # loop did: a stop() that landed between the last boundary check
            # and this line would otherwise leave the session "stopping"
            # forever, and its status route would report a half-dead state.
            if session.status == "running":
                session.status = "done"
                self._set_progress(session, f"Done — {session.proposals_filed} proposals awaiting your approval")
            elif session.status == "stopping":
                session.status = "stopped"
                self._set_progress(session, f"Stopped — {session.proposals_filed} proposals filed")
        except Exception as error:  # noqa: BLE001 - a failed session is a status, not a crash
            session.status = "error"
            session.error = str(error)[:300]
            self._set_progress(session, f"Failed: {session.error}")
            _LOG.warning("Self-improvement session %s failed: %s", session.session_id, error)
        finally:
            session.ended_at = time.time()
            with self._lock:
                self._threads.pop(session.session_id, None)

    def _file_proposal(self, session: ImprovementSession, item: Dict[str, str]) -> None:
        """One analysis finding → one draft change in the review gate (unless it repeats one already there)."""
        from change_review import CHANGE_LOG, ChangeOrigin

        try:
            import improve_review

            candidate = {"id": "", "title": f"Improve {item['file']}: {item['title']}", "target": item["file"],
                         "description": f"{item['change']} Why: {item['why']}"}
            existing = [c for c in CHANGE_LOG.list_changes() if c.get("origin") == "agent"
                        and (c.get("status") in improve_review.OPEN_STATUSES or improve_review.counts_as_decision(c))]
            repeat = improve_review.find_duplicate(candidate, existing)
        except Exception:  # noqa: BLE001 - dedupe is a courtesy; filing still works without it
            repeat = None
        if repeat is not None:
            session.repeats_skipped += 1
            session.notes.append(f"skipped a repeat of “{repeat['title'][:70]}”")
            return
        try:
            change = CHANGE_LOG.propose(
                title=f"Improve {item['file']}: {item['title']}",
                description=f"{item['change']} Why: {item['why']}",
                author="Nyx (self-improvement)",
                target=item["file"], origin=ChangeOrigin.AGENT,
            )
        except Exception as error:  # noqa: BLE001 - one bad proposal must not end the session
            session.notes.append(f"skipped {item['file']}: {error}")
            return
        session.change_ids.append(change.change_id)
        session.proposals_filed += 1


def _known_titles(limit: int = 30) -> List[str]:
    """Recent self-improvement titles, open or decided, newest first."""
    try:
        from change_review import CHANGE_LOG

        seen: List[str] = []
        for change in CHANGE_LOG.list_changes():
            if change.get("origin") != "agent":
                continue
            title = change.get("title", "")
            if title and title not in seen:
                seen.append(title)
            if len(seen) >= limit:
                break
        return seen
    except Exception:  # noqa: BLE001
        return []


def _default_model_fn() -> ModelFn:
    """Production model function: the owner's assigned code-generation role."""
    def model_fn(prompt: str, *, system: str = "", max_tokens: int = 1400, **_kw) -> str:
        from model_roles import MODEL_ROLES

        run = MODEL_ROLES.run("code_generation", prompt, system=system, max_tokens=max_tokens)
        return run.text

    return model_fn


#: Shared engine: one session at a time keeps the analysis readable and the
#: review queue sane. Tests build their own with a stub model.
ENGINE = SelfImprovementEngine()
