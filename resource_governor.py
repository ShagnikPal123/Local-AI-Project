"""Resource governor (ROADMAP EE1-EE9).

Gives the user a direct ceiling on how much of their machine the AI may use, in
plain terms — low, medium, high, max — plus two automatic modes: one that reads
the hardware, one that reads the task.

Two rules shape everything here:

1. **The safety floor always wins.** A user may select `MAX` on a weak laptop and
   the governor will still refuse to hand out more workers than the machine can
   survive. Section X2 is a guarantee, not a preference, so a setting cannot
   override it. What the user gets instead is an honest warning saying so.
2. **This enforces, it does not advise.** The ceiling is consumed by whatever
   spawns agents and picks models. A governor that only displays a number is
   decoration.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class PowerMode(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    MAX = "max"
    AUTO = "auto"          # Derive from the machine
    AUTO_TASK = "auto_task"  # Derive from the machine, adjusted by the task


@dataclass(frozen=True)
class ResourceCeiling:
    """What the AI is currently permitted to consume."""

    max_workers: int
    max_agents: int
    allow_local_models: bool
    mode: PowerMode
    # Set when the requested mode was reduced for safety, so the UI can explain
    # why the user did not get what they asked for.
    capped_reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "max_workers": self.max_workers,
            "max_agents": self.max_agents,
            "allow_local_models": self.allow_local_models,
            "capped_reason": self.capped_reason,
        }


# Share of the machine's safe worker budget each mode may claim.
_MODE_SHARE: Dict[PowerMode, float] = {
    PowerMode.LOW: 0.25,
    PowerMode.MEDIUM: 0.5,
    PowerMode.HIGH: 0.8,
    PowerMode.MAX: 1.0,
}

# Never drop below this; one worker means the product still functions.
_MIN_WORKERS = 1

# Device tiers where local inference is a bad idea regardless of the mode chosen.
_NO_LOCAL_TIERS = frozenset({"tiny"})


class ResourceGovernor:
    """Holds the current power mode and derives the live ceiling from it."""

    def __init__(self) -> None:
        self._mode = PowerMode.AUTO
        self._lock = threading.Lock()

    @property
    def mode(self) -> PowerMode:
        with self._lock:
            return self._mode

    def set_mode(self, mode: PowerMode) -> ResourceCeiling:
        """Select a power mode and return the ceiling it actually produced.

        The returned ceiling may be lower than requested; `capped_reason` says so.
        """
        with self._lock:
            self._mode = mode
        return self.ceiling()

    # --- derivation ---------------------------------------------------------

    def _device_budget(self) -> Tuple[int, str]:
        """Return the machine's safe worker budget and its tier name.

        Falls back to the most conservative possible answer rather than raising:
        an unreadable machine is treated as a weak one.
        """
        try:
            from device_profile import get_device_profile

            profile = get_device_profile()
            workers = int(getattr(profile, "max_workers", 0) or 0)
            tier = str(getattr(profile, "recommended_power_mode", "") or "")
        except Exception:
            return _MIN_WORKERS, "unknown"

        if workers < _MIN_WORKERS:
            workers = _MIN_WORKERS
        return workers, tier

    def _tier_name(self) -> str:
        """Best-effort device tier, used for the local-model decision."""
        try:
            from device_profile import get_device_profile, select_tier

            return str(select_tier(get_device_profile()).name)
        except Exception:
            return "unknown"

    def _effective_mode(self, task_complexity: Optional[str] = None) -> PowerMode:
        """Resolve AUTO / AUTO_TASK into a concrete mode."""
        mode = self.mode
        if mode not in (PowerMode.AUTO, PowerMode.AUTO_TASK):
            return mode

        budget, _ = self._device_budget()
        # Base the automatic choice on how much headroom the machine has.
        if budget >= 8:
            base = PowerMode.HIGH
        elif budget >= 4:
            base = PowerMode.MEDIUM
        else:
            base = PowerMode.LOW

        if mode is PowerMode.AUTO or task_complexity is None:
            return base

        # AUTO_TASK: a trivial turn does not need the whole machine, and a hard
        # one should be allowed more of it.
        if task_complexity in ("simple",):
            return PowerMode.LOW
        if task_complexity in ("complex", "parallel"):
            return PowerMode.HIGH if base is not PowerMode.LOW else PowerMode.MEDIUM
        return base

    def ceiling(self, task_complexity: Optional[str] = None) -> ResourceCeiling:
        """Compute the live ceiling, respecting the safety floor."""
        requested = self.mode
        effective = self._effective_mode(task_complexity)
        budget, _ = self._device_budget()
        tier = self._tier_name()

        share = _MODE_SHARE.get(effective, 0.5)
        workers = max(_MIN_WORKERS, int(budget * share))

        capped = ""
        # Safety floor: throttling in progress overrides whatever was requested.
        if self._is_throttled():
            safe_workers = max(_MIN_WORKERS, budget // 2)
            if workers > safe_workers:
                workers = safe_workers
                capped = (
                    "Reduced: the machine is currently throttling. "
                    "The safety limit overrides the selected mode."
                )

        if requested is PowerMode.MAX and workers < budget and not capped:
            capped = (
                f"Max is limited to {workers} workers on this machine "
                f"(hardware budget is {budget})."
            )

        allow_local = tier not in _NO_LOCAL_TIERS
        if not allow_local and not capped:
            capped = (
                "Local models are disabled on this device tier — running one here "
                "risks exhausting memory and hanging the system."
            )

        return ResourceCeiling(
            max_workers=workers,
            # Agents are cheaper than inference workers, but still bounded.
            max_agents=max(1, workers * 2),
            allow_local_models=allow_local,
            mode=effective,
            capped_reason=capped,
        )

    @staticmethod
    def _is_throttled() -> bool:
        try:
            from hardware_safety import SAFETY_MONITOR

            return bool(SAFETY_MONITOR.get_hardware_status().throttle_recommended)
        except Exception:
            return False

    # --- advice for the UI --------------------------------------------------

    def can_sustain(self, mode: PowerMode) -> Tuple[bool, str]:
        """Whether this machine can hold a mode, and what to expect if not."""
        budget, _ = self._device_budget()
        tier = self._tier_name()

        if mode in (PowerMode.AUTO, PowerMode.AUTO_TASK):
            return True, "Adapts to this machine automatically. Recommended."

        if tier in _NO_LOCAL_TIERS and mode in (PowerMode.HIGH, PowerMode.MAX):
            return False, (
                "This machine is below the bar for sustained heavy use. "
                "Selecting this can make the system unresponsive."
            )
        if budget <= 2 and mode is PowerMode.MAX:
            return False, (
                f"Only {budget} safe worker(s) available. Max will behave much like "
                "medium here, and will make the machine sluggish while it runs."
            )
        if mode is PowerMode.MAX:
            return True, "Uses the full safe capacity of this machine. Expect fan noise."
        return True, ""

    def describe_modes(self) -> Dict[str, Any]:
        """Every mode with its live effect on this specific machine."""
        budget, _ = self._device_budget()
        modes = []
        for mode in PowerMode:
            sustainable, note = self.can_sustain(mode)
            share = _MODE_SHARE.get(mode)
            modes.append({
                "id": mode.value,
                "label": mode.value.replace("_", " ").title(),
                "workers": max(_MIN_WORKERS, int(budget * share)) if share else None,
                "sustainable": sustainable,
                "note": note,
                "recommended": mode is PowerMode.AUTO,
            })
        return {
            "current": self.mode.value,
            "hardware_budget": budget,
            "device_tier": self._tier_name(),
            "modes": modes,
            "ceiling": self.ceiling().as_dict(),
        }


GOVERNOR = ResourceGovernor()
