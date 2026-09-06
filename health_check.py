"""Post-change health verification (ROADMAP F3, F5).

The half of self-revival that was missing: something has to *notice* the app is
broken before restoring a checkpoint is any use.

This runs immediately after a change is applied. If the app is no longer in a
working state, the caller rolls back to the checkpoint taken before the apply —
so a bad change is undone within the same request that made it, rather than
being discovered later by a confused user.

Design constraints, learned from the safety monitor in session 3:

* **A check that raises has become the bug.** Every check is individually
  wrapped; a check that explodes is reported as a failed check, never as an
  exception escaping into the publish path.
* **Checks must be fast.** This sits in the request path for every publish.
  Anything slow gets removed by whoever profiles it next, and then there is no
  verification at all.
* **A check verifies, it does not repair.** Deciding what to do about a failure
  belongs to the caller, which knows what it was doing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    duration_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "duration_ms": round(self.duration_ms, 2),
        }


def _check_overlay_readable() -> str:
    """The overlay must be loadable, or nothing else can be trusted."""
    from overlay import OVERLAY

    OVERLAY.list_entries()
    return "overlay readable"


def _check_core_imports() -> str:
    """The modules the app cannot run without."""
    import chat_service  # noqa: F401
    import router  # noqa: F401
    import auth  # noqa: F401

    return "core modules import"


def _check_auth_store() -> str:
    """Auth must still resolve, or everyone is locked out."""
    from server_auth import AUTH_STORE

    AUTH_STORE.resolve_session("")  # None is the correct answer, not an error
    return "auth store responds"


def _check_hardware_safety() -> str:
    """The safety monitor must still report, since it gates every turn."""
    from hardware_safety import SAFETY_MONITOR

    status = SAFETY_MONITOR.get_hardware_status()
    if status is None:
        raise RuntimeError("safety monitor returned nothing")
    return f"safety monitor: {status.status_summary}"


def _check_widgets_loadable() -> str:
    from widgets import WIDGET_STORE

    WIDGET_STORE.list_widgets()
    return "widget layout readable"


# Ordered cheapest-first so an obvious breakage is caught before the slower ones.
DEFAULT_CHECKS: List[tuple[str, Callable[[], str]]] = [
    ("overlay", _check_overlay_readable),
    ("core_imports", _check_core_imports),
    ("auth", _check_auth_store),
    ("widgets", _check_widgets_loadable),
    ("hardware_safety", _check_hardware_safety),
]


def run_health_check(checks: List[tuple[str, Callable[[], str]]] | None = None) -> Dict[str, Any]:
    """Run every check and report. Never raises.

    Returns a dict with `healthy`, the individual `results`, and `failed` — the
    names of anything that did not pass, so a caller can log what broke without
    re-deriving it.
    """
    selected = checks if checks is not None else DEFAULT_CHECKS
    results: List[CheckResult] = []

    for name, check in selected:
        started = time.perf_counter()
        try:
            detail = check()
            passed = True
        except Exception as error:
            detail = f"{type(error).__name__}: {error}"[:200]
            passed = False
        results.append(CheckResult(
            name=name,
            passed=passed,
            detail=detail,
            duration_ms=(time.perf_counter() - started) * 1000,
        ))

    failed = [r.name for r in results if not r.passed]
    return {
        "healthy": not failed,
        "failed": failed,
        "results": [r.as_dict() for r in results],
        "total_ms": round(sum(r.duration_ms for r in results), 2),
    }
