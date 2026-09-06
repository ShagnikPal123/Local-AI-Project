"""Dynamic multi-approach engine that combines multiple analytical routes automatically."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass(frozen=True)
class Approach:
    """An analytical strategy used during multi-route execution."""

    name: str
    instruction: str
    complexity: int
    role: str = "general"


# Default strategy routes that Nyx Pulse coordinates automatically
APPROACHES: Dict[str, Approach] = {
    "auto": Approach(
        "auto",
        "Dynamically select the optimal multi-stage strategy, explore edge cases, and double-check conclusions.",
        3,
        "coordinator",
    ),
    "step_by_step": Approach(
        "step_by_step",
        "Deconstruct the problem into explicit logical steps, verifying preconditions before advancing.",
        2,
        "analyst",
    ),
    "direct": Approach(
        "direct",
        "Deliver the most concise, correct solution first with immediate actionable code.",
        1,
        "coder",
    ),
    "alternatives": Approach(
        "alternatives",
        "Explore multiple viable approaches, compare trade-offs, and recommend the best option with justification.",
        3,
        "architect",
    ),
    "research_first": Approach(
        "research_first",
        "Gather, corroborate, and cross-reference multiple live evidence sources before drawing conclusions.",
        4,
        "researcher",
    ),
    "test_driven": Approach(
        "test_driven",
        "Define concrete unit tests, edge-case assertions, and invariants first, then craft implementation.",
        3,
        "tester",
    ),
    "systems": Approach(
        "systems",
        "Analyze security, performance, dependencies, backwards-compatibility, and failure recovery paths.",
        5,
        "systems_engineer",
    ),
}


def get_approach(name: str = "auto") -> Approach:
    """Return the selected approach or default to the adaptive 'auto' multi-approach."""
    key = (name or "auto").strip().lower()
    return APPROACHES.get(key, APPROACHES["auto"])


def build_multi_approach_prompt(task: str, approach_name: str = "auto") -> str:
    """Format prompt with instructions for automatic multi-route problem solving."""
    approach = get_approach(approach_name)
    if approach.name == "auto":
        guidance = (
            "[MULTI-APPROACH PROTOCOL: AUTO]\n"
            "1. Analyze requirements, invariants, and edge cases.\n"
            "2. Formulate the cleanest, most maintainable solution.\n"
            "3. Double-check for edge cases, performance, security, and test verification."
        )
    else:
        guidance = f"[APPROACH: {approach.name}] {approach.instruction}"

    return f"{guidance}\n\n{task}"


def try_approaches(
    task: str,
    solve: Callable[[str], Any],
    names: Optional[List[str]] = None,
) -> tuple[Any, str]:
    """Execute a task with sequential strategy fallback if an error occurs."""
    selected = list(names or ["auto", "step_by_step", "alternatives", "systems"])
    last_error = None
    for name in selected:
        approach = get_approach(name)
        try:
            prompt = build_multi_approach_prompt(task, approach.name)
            result = solve(prompt)
            if result:
                return result, approach.name
        except Exception as error:
            last_error = error

    if last_error:
        raise last_error
    raise RuntimeError("No approaches were configured.")
