"""Educational and homework assistance engine for structured learning and problem solving."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class HomeworkHelper:
    """Provides structured problem breakdown, hint generation, and Socratic guidance."""

    SUBJECTS = {
        "math": [r"\b(?:derivative|integral|equation|algebra|polynomial|matrix|triangle|geometry|logarithm|solve for x|theorem)\b"],
        "physics": [r"\b(?:velocity|acceleration|gravity|momentum|force|friction|energy|circuit|resistor|voltage|optics|quantum)\b"],
        "chemistry": [r"\b(?:reaction|stoichiometry|mole|acid|base|pH|periodic table|covalent|ionic|equilibrium|enthalpy)\b"],
        "computer_science": [r"\b(?:algorithm|big o|data structure|binary tree|recursion|python|javascript|sql|pointer|sorting)\b"],
        "literature": [r"\b(?:metaphor|simile|theme|protagonist|symbolism|stanza|poem|novel|character analysis)\b"],
        "history": [r"\b(?:revolution|treaty|century|empire|war|dynasty|constitution|amendment|president|monarch)\b"],
    }

    @classmethod
    def detect_subject(cls, problem_text: str) -> str:
        """Classify academic subject from problem text."""
        for subject, patterns in cls.SUBJECTS.items():
            for pat in patterns:
                if re.search(pat, problem_text, re.IGNORECASE):
                    return subject
        return "general"

    @classmethod
    def decompose_problem(cls, problem_text: str) -> Dict[str, Any]:
        """Deconstruct a homework problem into knowns, unknowns, steps, and hints."""
        subject = cls.detect_subject(problem_text)

        # Extract numeric values / potential given variables
        numbers = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", problem_text)

        steps = [
            "1. Identify the core concepts and target question.",
            "2. List known variables, given constraints, and relevant formulas.",
            "3. Formulate the mathematical/logical equation or outline.",
            "4. Execute step-by-step calculation or synthesis.",
            "5. Verify units, sanity-check bounds, and interpret result.",
        ]

        hints = [
            "Hint 1: Review relevant standard definitions or laws for this subject.",
            "Hint 2: Pay close attention to given units and ensure consistency.",
            "Hint 3: Try working backward from what the question asks for.",
        ]

        return {
            "problem": problem_text.strip(),
            "subject": subject,
            "detected_values": numbers,
            "recommended_steps": steps,
            "hints": hints,
            "socratic_prompt": (
                f"Guide the student through this {subject} problem using the Socratic method. "
                "Ask guiding questions first, provide hints, and only reveal the complete solution when requested."
            ),
        }
