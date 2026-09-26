"""Predictions and autonomy: Nyx anticipates the owner, and does quiet work while they're away.

The owner asked for "prediction algorithms to almost every part", "making tabs on its
own when the user is not active — with a switch", auto updates, and "a 1 hour detox
period where it self improves". Each piece is a switch in Settings → Predictions:

Predictions (always local, no model calls)
    * **Next tab** — a time-of-day-weighted Markov model over the owner's tab visits.
    * **Usual hours** — an hour-of-week histogram of activity: when the owner is
      usually here, and therefore when quiet work won't get in the way.
    * **Model for a request** — Nyx Core's recommendation (which outside model has
      done best on requests like it).
    * **Predictive text** — Nyx Core's word model (served by ``/api/core/complete``).

Autonomy, while the owner is away (``IdleScheduler``, one check a minute)
    * **Tabs Nyx thinks you need** — at most one a day, designed from what the
      owner has actually been working on, labelled "made while you were away".
    * **Updates** — checks GitHub for new commits; "install" pulls them (only when
      the working tree is clean) and restarts.
    * **Detox hour** — once a day in the owner's quiet hours: consolidate and a
      gentle improve pass through the improvement autopilot (approval stays with
      the owner unless they switched auto-approve on for detox).
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import PROJECT_DIR, data_path

_LOG = logging.getLogger("nyx.predictor")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DEFAULT_SETTINGS: Dict[str, Any] = {
    "predictions": True,
    "predictive_text": True,
    "next_tab_hints": True,
    "model_hints": True,
    "idle_tabs": False,
    "auto_updates": "check",      # off | check | install
    "detox_daily": False,
    "detox_auto_approve": False,
    "idle_minutes": 30,
}
_UPDATE_MODES = ("off", "check", "install")


class Predictor:
    def __init__(self, path: Optional[Path] = None, clock: Callable[[], float] = time.time) -> None:
        self._path = path
        self.clock = clock
        self._lock = threading.RLock()
        self._data: Optional[Dict[str, Any]] = None

    # --- storage ---------------------------------------------------------------------

    def _file(self) -> Path:
        return self._path or data_path("predictions.json")

    def _load(self) -> Dict[str, Any]:
        if self._data is None:
            try:
                data = json.loads(self._file().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
            data.setdefault("settings", {})
            data["settings"] = {**DEFAULT_SETTINGS, **{k: v for k, v in data["settings"].items() if k in DEFAULT_SETTINGS}}
            data.setdefault("transitions", {})
            data.setdefault("visits", {})
            data.setdefault("hours", [0] * 168)
            data.setdefault("last_tab", "")
            data.setdefault("last_tab_at", 0.0)
            data.setdefault("idle_log", [])
            data.setdefault("last_idle_tab_day", "")
            data.setdefault("last_detox_day", "")
            data.setdefault("update", {})
            self._data = data
        return self._data

    def _save(self) -> None:
        path = self._file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._data), encoding="utf-8")

    # --- settings ----------------------------------------------------------------------

    def settings(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._load()["settings"])

    def update_settings(self, **changes: Any) -> Dict[str, Any]:
        with self._lock:
            settings = self._load()["settings"]
            for key, value in changes.items():
                if key not in DEFAULT_SETTINGS or value is None:
                    continue
                if key == "auto_updates":
                    if value in _UPDATE_MODES:
                        settings[key] = value
                elif key == "idle_minutes":
                    settings[key] = int(max(5, min(240, int(value))))
                else:
                    settings[key] = bool(value)
            self._save()
            return dict(settings)

    # --- observing --------------------------------------------------------------------

    def observe_tab(self, tab: str) -> None:
        tab = (tab or "").strip()[:60]
        if not tab:
            return
        with self._lock:
            data = self._load()
            now = self.clock()
            local = time.localtime(now)
            data["hours"][local.tm_wday * 24 + local.tm_hour] += 1
            previous = data["last_tab"]
            if previous and previous != tab and now - data["last_tab_at"] < 3 * 3600:
                bucket = f"{previous}|{_daypart(local.tm_hour)}"
                row = data["transitions"].setdefault(bucket, {})
                row[tab] = row.get(tab, 0) + 1
                any_row = data["transitions"].setdefault(f"{previous}|*", {})
                any_row[tab] = any_row.get(tab, 0) + 1
            if previous != tab:
                data["visits"][tab] = data["visits"].get(tab, 0) + 1
            data["last_tab"], data["last_tab_at"] = tab, now
            self._save()

    def observe_activity(self) -> None:
        with self._lock:
            data = self._load()
            local = time.localtime(self.clock())
            data["hours"][local.tm_wday * 24 + local.tm_hour] += 1
            self._save()

    # --- predicting -------------------------------------------------------------------

    def next_tab(self, current: str = "") -> Optional[Dict[str, Any]]:
        with self._lock:
            data = self._load()
            current = current or data["last_tab"]
            hour = time.localtime(self.clock()).tm_hour
            specific = Counter(data["transitions"].get(f"{current}|{_daypart(hour)}", {}))
            general = Counter(data["transitions"].get(f"{current}|*", {}))
        scores: Dict[str, float] = defaultdict(float)
        for tab, n in general.items():
            scores[tab] += n
        for tab, n in specific.items():
            scores[tab] += 2 * n  # this time of day counts double
        scores.pop(current, None)
        if not scores:
            return None
        total = sum(scores.values())
        tab, score = max(scores.items(), key=lambda item: item[1])
        evidence = int(general.get(tab, 0))
        if evidence < 2:
            return None
        return {"tab": tab, "confidence": round(score / total, 3), "evidence": evidence}

    def visits(self) -> Dict[str, int]:
        """How many times each tab has been opened (all time) — the Command Zone's "tabs you use"."""
        with self._lock:
            return dict(self._load()["visits"])

    def usual_hours(self) -> Dict[str, Any]:
        with self._lock:
            hours = list(self._load()["hours"])
        by_hour = [sum(hours[d * 24 + h] for d in range(7)) for h in range(24)]
        total = sum(by_hour)
        quiet = [h for h in range(24) if total and by_hour[h] <= total * 0.01]
        return {"by_hour": by_hour, "total": total, "quiet_hours": quiet,
                "busiest_hour": max(range(24), key=lambda h: by_hour[h]) if total else None}

    def is_quiet_now(self) -> bool:
        info = self.usual_hours()
        if info["total"] < 50:  # not enough history: fall back to "the middle of the night"
            return time.localtime(self.clock()).tm_hour in (1, 2, 3, 4, 5)
        return time.localtime(self.clock()).tm_hour in info["quiet_hours"]

    def snapshot(self, message: str = "") -> Dict[str, Any]:
        settings = self.settings()
        out: Dict[str, Any] = {"settings": settings, "next_tab": None, "usual_hours": self.usual_hours(), "model": None}
        if not settings["predictions"]:
            return out
        if settings["next_tab_hints"]:
            out["next_tab"] = self.next_tab()
        if settings["model_hints"] and message:
            try:
                import nyx_core

                out["model"] = nyx_core.CORE.recommend_model(message)
            except Exception:
                out["model"] = None
        with self._lock:
            data = self._load()
            out["idle_log"] = list(data["idle_log"])[-20:]
            out["update"] = dict(data["update"])
        return out

    def log_idle(self, kind: str, text: str) -> None:
        with self._lock:
            data = self._load()
            data["idle_log"] = (data["idle_log"] + [{"ts": self.clock(), "kind": kind, "text": text[:300]}])[-60:]
            self._save()
        try:
            from agent_events import publish_ui

            publish_ui("predict.idle", kind=kind, text=text[:300])
        except Exception:
            pass


def _daypart(hour: int) -> str:
    return "night" if hour < 6 else "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"


# ---------------------------------------------------------------------------
# Updates from GitHub
# ---------------------------------------------------------------------------


def _git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=PROJECT_DIR, capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW)


def check_updates() -> Dict[str, Any]:
    """Fetch origin and report how far behind this install is. Never changes files."""
    try:
        if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
            return {"ok": False, "detail": "This install isn't a git checkout, so it can't update from GitHub."}
        branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
        fetch = _git("fetch", "--quiet", "origin", branch, timeout=120)
        if fetch.returncode != 0:
            return {"ok": False, "detail": f"Couldn't reach GitHub: {(fetch.stderr or '').strip()[:200]}"}
        behind = int((_git("rev-list", "--count", f"HEAD..origin/{branch}").stdout or "0").strip() or 0)
        ahead = int((_git("rev-list", "--count", f"origin/{branch}..HEAD").stdout or "0").strip() or 0)
        dirty = bool(_git("status", "--porcelain", "--untracked-files=no").stdout.strip())
        subjects = _git("log", "--format=%s", f"HEAD..origin/{branch}", "-n", "8").stdout.strip().splitlines() if behind else []
        return {"ok": True, "branch": branch, "behind": behind, "ahead": ahead, "dirty": dirty, "new": subjects,
                "checked_at": time.time(),
                "detail": (f"{behind} update{'s' if behind != 1 else ''} available" if behind else "Up to date")}
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return {"ok": False, "detail": f"Update check failed: {error}"}


def install_updates() -> Dict[str, Any]:
    """Fast-forward to origin — only when nothing local would be overwritten."""
    status = check_updates()
    if not status.get("ok") or not status.get("behind"):
        return status
    if status.get("dirty"):
        return {**status, "installed": False, "detail": "Updates are waiting, but this copy has local changes; install them by hand so nothing is lost."}
    if status.get("ahead"):
        return {**status, "installed": False, "detail": "This copy has its own commits; merge the updates by hand."}
    pull = _git("merge", "--ff-only", f"origin/{status['branch']}", timeout=120)
    if pull.returncode != 0:
        return {**status, "installed": False, "detail": f"Couldn't install: {(pull.stderr or '').strip()[:200]}"}
    return {**status, "installed": True, "detail": f"Installed {status['behind']} update(s); restart to use them."}


# ---------------------------------------------------------------------------
# Quiet work while the owner is away
# ---------------------------------------------------------------------------


class IdleScheduler:
    def __init__(self, predictor: Predictor, *, idle_fn: Optional[Callable[[], float]] = None,
                 tab_maker: Optional[Callable[[str, str], str]] = None, detox_starter: Optional[Callable[[bool], Any]] = None,
                 updater: Optional[Callable[[str], Dict[str, Any]]] = None, restart: Optional[Callable[[], None]] = None) -> None:
        self.predictor = predictor
        self._idle_fn = idle_fn
        self._tab_maker = tab_maker
        self._detox = detox_starter
        self._updater = updater
        self._restart = restart
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_update_check = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="nyx-idle-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(60):
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the scheduler must outlive a bad tick
                _LOG.exception("idle tick failed")

    def _idle(self) -> float:
        if self._idle_fn:
            return self._idle_fn()
        import presence

        return presence.idle_seconds()

    def tick(self) -> List[str]:
        """One check. Returns what it did (for tests and the log)."""
        settings = self.predictor.settings()
        did: List[str] = []
        idle = self._idle()
        away = idle >= settings["idle_minutes"] * 60 and idle < 10 ** 8
        now = self.predictor.clock()
        today = time.strftime("%Y-%m-%d", time.localtime(now))

        if settings["auto_updates"] != "off" and now - self._last_update_check > 6 * 3600 and (away or self._last_update_check == 0):
            self._last_update_check = now
            result = (self._updater or (lambda mode: install_updates() if mode == "install" else check_updates()))(settings["auto_updates"])
            with self.predictor._lock:
                self.predictor._load()["update"] = result
                self.predictor._save()
            if result.get("behind"):
                self.predictor.log_idle("update", result.get("detail", ""))
                did.append("update")
                if result.get("installed") and self._restart:
                    self._restart()

        if not away:
            return did

        data = self.predictor._load()
        if settings["idle_tabs"] and data["last_idle_tab_day"] != today:
            topic, why = self._needed_tab()
            if topic:
                maker = self._tab_maker or _make_tab
                result = maker(topic, why)
                with self.predictor._lock:
                    data["last_idle_tab_day"] = today
                    self.predictor._save()
                self.predictor.log_idle("tab", f"Made “{topic}” while you were away — {why}. {result[:120]}")
                did.append("tab")

        if settings["detox_daily"] and data["last_detox_day"] != today and self.predictor.is_quiet_now():
            starter = self._detox or _start_detox
            outcome = starter(bool(settings["detox_auto_approve"]))
            with self.predictor._lock:
                data["last_detox_day"] = today
                self.predictor._save()
            self.predictor.log_idle("detox", f"Started the daily detox hour ({outcome}).")
            did.append("detox")
        return did

    def needed_tab(self) -> tuple[str, str]:
        """The tab Nyx would make, without making it — the Command Zone offers it for approval."""
        return self._needed_tab()

    def _needed_tab(self) -> tuple[str, str]:
        """A tab worth making: the topic the owner returned to most in recent turns, if no tab covers it yet."""
        try:
            from identity0 import tabs as kahuna_tabs

            if kahuna_tabs.auto_enabled():
                # Big Kahuna makes the tabs itself from tested templates (Request S18); don't make a second one.
                kahuna_tabs.refresh()
                return "", ""
        except Exception:  # pragma: no cover - the old path still works without it
            pass
        try:
            lines = data_path("learning/turns.jsonl").read_text(encoding="utf-8").splitlines()[-80:]
            messages = [json.loads(line).get("message", "") for line in lines if line.strip()]
        except (OSError, ValueError):
            messages = []
        if len(messages) < 5:
            return "", ""
        try:
            import super_brain

            stop = super_brain._STOP
        except Exception:
            stop = set()
        import re

        terms: Counter = Counter()
        phrases: Counter = Counter()
        for message in messages:
            words = [w for w in re.findall(r"[a-z0-9][a-z0-9+#.-]{1,30}", message.lower()) if w not in stop and len(w) >= 3]
            terms.update(set(words))
            phrases.update({f"{a} {b}" for a, b in zip(words, words[1:])})
        # A repeated two-word topic ("gpu prices") beats either word alone.
        ranked = [(p, n) for p, n in phrases.most_common(5) if n >= 3] + terms.most_common(8)
        existing = set()
        try:
            from dynamic_tabs import TAB_STORE

            existing = {t.get("label", "").lower() for t in TAB_STORE.list_tabs()}
        except Exception:
            pass
        for term, count in ranked:
            if count >= 3 and len(term) >= 3 and not any(term in label for label in existing):
                return term.title(), f"you came back to {term} in {count} recent requests"
        return "", ""


def _make_tab(topic: str, why: str) -> str:
    from landscape_tools import tool_ui_create_tab

    return tool_ui_create_tab(topic, description=f"A workspace for {topic}, made by Nyx while the owner was away because {why}.")


def _start_detox(auto_approve: bool) -> str:
    from improve_autopilot import AUTOPILOT, AutopilotError

    if AUTOPILOT.active():
        return "skipped: an autopilot run is already going"
    try:
        run = AUTOPILOT.start("take a detox hour", auto_approve=auto_approve, started_by="daily detox (Settings → Predictions)", replace=False)
    except AutopilotError as error:
        return f"skipped: {error}"
    return f"run {run['run_id']}, auto-approve {'on' if auto_approve else 'off'}"


PREDICTOR = Predictor()
SCHEDULER = IdleScheduler(PREDICTOR)
