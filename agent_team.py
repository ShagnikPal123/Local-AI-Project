"""Named agent team with a master/worker hierarchy (ROADMAP B1-B6, Z3).

`AgentPool` already handles anonymous parallel execution. This sits above it and
tracks *who* is doing *what*: named agents with individual goals, an assigned
role, an optional personality, and live status the UI can poll.

The distinction matters for the request this implements — "create 3 sub-agents,
one with this goal, one with that, and a third managing the others". That needs
identity and delegation, which a worker pool deliberately does not have.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentRole(Enum):
    """Where an agent sits in the hierarchy."""

    MASTER = "master"   # Delegates and reviews. Exactly one at a time.
    WORKER = "worker"   # Executes an assigned goal.


class AgentStatus(Enum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"   # Waiting on a dependency or a resource
    ERROR = "error"
    DONE = "done"


@dataclass
class ManagedAgent:
    """One named agent with a goal and observable progress."""

    agent_id: str
    name: str
    goal: str
    role: AgentRole = AgentRole.WORKER
    personality_id: Optional[str] = None
    status: AgentStatus = AgentStatus.IDLE
    current_step: str = ""
    steps_completed: int = 0
    total_seconds: float = 0.0
    last_error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    # True for a master the team created for itself rather than one the user
    # asked for. Lets a real master replace the placeholder instead of demoting
    # it into a confusing extra worker.
    auto_created: bool = False

    def snapshot(self) -> Dict[str, Any]:
        """Serialise for the live progress panel."""
        elapsed = (
            time.time() - self.started_at
            if self.started_at is not None and self.status is AgentStatus.WORKING
            else self.total_seconds
        )
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "goal": self.goal,
            "role": self.role.value,
            "personality_id": self.personality_id,
            "status": self.status.value,
            "current_step": self.current_step,
            "steps_completed": self.steps_completed,
            "elapsed_seconds": round(elapsed, 2),
            "last_error": self.last_error,
        }


# A prompt this short almost never carries a usable goal. Surfaced in the panel
# so "why is nothing happening" has a visible answer, which is one of the things
# the live view is for.
_VAGUE_GOAL_CHARS = 12


class AgentTeam:
    """A team of named agents with exactly one master.

    Thread-safe: the pool runs agents concurrently, so status updates arrive from
    worker threads while the UI polls for a snapshot.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, ManagedAgent] = {}
        self._lock = threading.Lock()

    # --- membership ---------------------------------------------------------

    def spawn(
        self,
        name: str,
        goal: str = "",
        role: AgentRole = AgentRole.WORKER,
        personality_id: Optional[str] = None,
        auto_created: bool = False,
    ) -> ManagedAgent:
        """Add an agent to the team.

        Exactly one master exists at a time. A new master replaces an idle
        placeholder the team created for itself, and demotes a real one the user
        put there — replacing a user's agent would silently discard their work.
        """
        agent = ManagedAgent(
            agent_id=uuid.uuid4().hex[:8],
            name=name.strip() or "agent",
            goal=goal.strip(),
            role=role,
            personality_id=personality_id,
            auto_created=auto_created,
        )
        with self._lock:
            if role is AgentRole.MASTER:
                retired = [
                    existing_id
                    for existing_id, existing in self._agents.items()
                    if existing.role is AgentRole.MASTER
                    and existing.auto_created
                    and existing.steps_completed == 0
                ]
                for existing_id in retired:
                    del self._agents[existing_id]
                for existing in self._agents.values():
                    if existing.role is AgentRole.MASTER:
                        existing.role = AgentRole.WORKER
            self._agents[agent.agent_id] = agent
        return agent

    def ensure_master(self, name: str = "master") -> ManagedAgent:
        """Return the master, creating one if the team has none.

        A team defaults to having a manager rather than requiring the user to ask
        for one, which is the behaviour Shagnik specified.
        """
        with self._lock:
            for agent in self._agents.values():
                if agent.role is AgentRole.MASTER:
                    return agent
        return self.spawn(
            name,
            goal="Coordinate the team and review its output.",
            role=AgentRole.MASTER,
            auto_created=True,
        )

    def ensure_default_subagents(self) -> List[ManagedAgent]:
        """Ensure the four core sub-agents requested by Shagnik are present:
        1. Manager (Role: MASTER) - Coordinates the team, reviews ideas, and routes tasks.
        2. Site/Web Dev (Role: WORKER) - Oversees web interface, landing pages, and local packaging.
        3. Coder (Role: WORKER) - Implements algorithms, features, APIs, and connectors.
        4. Checker (Role: WORKER) - Validates correctness, safety boundaries, and test suites.
        """
        defaults = [
            ("Manager", "Coordinate the multi-agent team, review incoming tasks, and validate outputs.", AgentRole.MASTER),
            ("Site/Web Dev", "Improve website usability, maintain local launchers, and ensure web workspace responsiveness.", AgentRole.WORKER),
            ("Coder", "Implement clean, modular code, handle model inference, and build integrations.", AgentRole.WORKER),
            ("Checker", "Verify logic and test coverage, validate safety rules, and ensure ideas are solid and work.", AgentRole.WORKER),
        ]
        created = []
        existing_names = {a.name.lower(): a for a in self._agents.values()}
        for name, goal, role in defaults:
            if name.lower() not in existing_names:
                agent = self.spawn(name, goal=goal, role=role)
                created.append(agent)
            else:
                created.append(existing_names[name.lower()])
        return created

    def dismiss(self, agent_id: str) -> bool:
        """Remove an agent. The master cannot be dismissed while workers remain."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return False
            if agent.role is AgentRole.MASTER and len(self._agents) > 1:
                return False
            del self._agents[agent_id]
            return True

    def get(self, agent_id: str) -> Optional[ManagedAgent]:
        with self._lock:
            return self._agents.get(agent_id)

    def clear(self) -> None:
        with self._lock:
            self._agents.clear()

    # --- progress reporting -------------------------------------------------

    def begin(self, agent_id: str, step: str) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return
            agent.status = AgentStatus.WORKING
            agent.current_step = step
            agent.started_at = time.time()

    def finish_step(self, agent_id: str) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is None:
                return
            if agent.started_at is not None:
                agent.total_seconds += time.time() - agent.started_at
                agent.started_at = None
            agent.steps_completed += 1
            agent.status = AgentStatus.IDLE
            agent.current_step = ""

    def block(self, agent_id: str, reason: str) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is not None:
                agent.status = AgentStatus.BLOCKED
                agent.current_step = reason

    def fail(self, agent_id: str, error: str) -> None:
        with self._lock:
            agent = self._agents.get(agent_id)
            if agent is not None:
                agent.status = AgentStatus.ERROR
                agent.last_error = error
                agent.current_step = ""
                agent.started_at = None

    # --- the live view ------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Full team status for the progress panel.

        Includes the two diagnoses the panel exists to answer: whether the
        machine is throttling the agents, and whether a goal looks too vague to
        act on. Without those, a stalled team looks identical to an idle one.
        """
        with self._lock:
            agents = [a.snapshot() for a in self._agents.values()]
            vague = [
                a.name for a in self._agents.values()
                if a.role is AgentRole.WORKER and len(a.goal) < _VAGUE_GOAL_CHARS
            ]

        return {
            "agents": sorted(agents, key=lambda a: (a["role"] != "master", a["name"])),
            "total": len(agents),
            "working": sum(1 for a in agents if a["status"] == "working"),
            "blocked": sum(1 for a in agents if a["status"] == "blocked"),
            "errored": sum(1 for a in agents if a["status"] == "error"),
            "resource_pressure": _resource_pressure(),
            "vague_goals": vague,
        }


def _resource_pressure() -> Dict[str, Any]:
    """Report whether the host is currently limiting the team.

    Agents run locally, so a busy machine slows them in ways that look like the
    agent being stuck. Reading the safety monitor turns that into a stated cause.
    Never raises: a diagnostic that crashes the panel is worse than no diagnostic.
    """
    try:
        from hardware_safety import SAFETY_MONITOR

        status = SAFETY_MONITOR.get_hardware_status()
        blind = "no_gpu_telemetry" in (status.status_summary or "")
        return {
            "throttled": bool(status.throttle_recommended),
            "gpu_temp_c": status.gpu_temp,
            "gpu_utilization": status.gpu_utilization,
            "vram_used_mb": status.vram_used_mb,
            "vram_total_mb": status.vram_total_mb,
            "telemetry_available": not blind,
            "summary": status.status_summary,
        }
    except Exception as error:  # pragma: no cover - defensive
        return {
            "throttled": False,
            "telemetry_available": False,
            "summary": f"unavailable: {error}",
        }


# Process-wide team, mirroring how AgentPool is exposed.
AGENT_TEAM = AgentTeam()
