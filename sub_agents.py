"""Lightweight specialist sub-agents for delegation without extra model processes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class SubAgent:
    name: str
    instruction: str


class SubAgentCoordinator:
    """Coordinates specialist sub-agents for modular delegation."""

    AGENTS = (
        SubAgent("researcher", "Find current evidence, sources, and conflicts."),
        SubAgent("coder", "Inspect implementation details, imports, edge cases, and tests."),
        SubAgent("reviewer", "Review proposed answers or changes for correctness and regressions."),
    )

    def plan(self, task: str) -> List[Dict[str, str]]:
        lowered = task.lower()
        selected: List[SubAgent] = []
        if any(word in lowered for word in ("research", "latest", "current", "search")):
            selected.append(self.AGENTS[0])
        if any(word in lowered for word in ("code", "coding", "debug", "implement", "function")):
            selected.append(self.AGENTS[1])
        if selected:
            selected.append(self.AGENTS[2])
        return [{"agent": agent.name, "instruction": agent.instruction} for agent in selected]
