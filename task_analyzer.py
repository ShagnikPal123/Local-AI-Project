"""Task analysis for intelligent mode routing, complexity detection, and agent delegation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class TaskComplexity(Enum):
    """Task complexity levels for routing to appropriate processing mode."""

    SIMPLE = "simple"  # Fast, direct response
    MODERATE = "moderate"  # Moderate reasoning required
    COMPLEX = "complex"  # Multi-step analysis, coding, or architecture
    PARALLEL = "parallel"  # Multiple independent subtasks


@dataclass
class TaskAnalysis:
    """Result of task analysis."""

    complexity: TaskComplexity
    estimated_time: float
    subtasks: List[str]
    reasoning: str
    recommended_mode: str
    requires_double_check: bool = False
    recommended_roles: List[str] = field(default_factory=list)


class TaskAnalyzer:
    """Analyze incoming tasks to determine optimal processing mode and agent delegation."""

    SIMPLE_KEYWORDS = {
        "quick", "fast", "brief", "simple", "short", "summarize",
        "what is", "define", "list", "name", "tell me about",
        "how many", "when", "where", "who", "which", "hello", "hi", "hey",
    }

    COMPLEX_KEYWORDS = {
        "why", "how does", "explain deeply", "analyze", "compare",
        "design", "architecture", "strategy", "implement", "debug",
        "optimize", "refactor", "trace", "understand", "complex",
        "problem", "solution", "technical", "detailed", "thoroughly",
        "write tests", "build", "pipeline", "security", "concurrency",
    }

    RESEARCH_KEYWORDS = {
        "latest", "recent", "current", "news", "price", "release date",
        "today", "this year", "market", "who won", "research",
    }

    CODING_KEYWORDS = {
        "code", "function", "class", "def ", "import", "async", "bug",
        "exception", "error", "traceback", "fix", "refactor", "pytest",
        "python", "javascript", "typescript", "html", "css", "api",
    }

    def analyze(self, task: str) -> TaskAnalysis:
        """Analyze a task and return recommended processing strategy."""
        task_lower = task.lower()

        # Check for multi-part tasks
        subtasks = self._extract_subtasks(task)
        if len(subtasks) > 1:
            return TaskAnalysis(
                complexity=TaskComplexity.PARALLEL,
                estimated_time=len(subtasks) * 1.5,
                subtasks=subtasks,
                reasoning=f"Detected {len(subtasks)} independent subtasks for concurrent execution.",
                recommended_mode="parallel",
                requires_double_check=True,
                recommended_roles=["planner", "coder", "reviewer"],
            )

        # Detect domain characteristics
        is_coding = any(kw in task_lower for kw in self.CODING_KEYWORDS)
        is_research = any(kw in task_lower for kw in self.RESEARCH_KEYWORDS)
        complexity_score = self._score_complexity(task_lower)

        roles = ["planner"]
        if is_research:
            roles.append("researcher")
        if is_coding:
            roles.extend(["coder", "reviewer"])
        else:
            roles.append("analyst")

        if complexity_score < 0.35 and not is_coding:
            complexity = TaskComplexity.SIMPLE
            estimated_time = 0.5
            mode = "quick"
            reasoning = "Straightforward factual question or simple query"
            double_check = False
        elif complexity_score < 0.65 and not is_coding:
            complexity = TaskComplexity.MODERATE
            estimated_time = 1.5
            mode = "quick"
            reasoning = "Moderate complexity, handled quickly"
            double_check = is_research
        else:
            complexity = TaskComplexity.COMPLEX
            estimated_time = 3.5
            mode = "coding" if is_coding else "deep"
            reasoning = "Complex query requiring multi-route analysis, edge-case checks, and verification"
            double_check = True

        return TaskAnalysis(
            complexity=complexity,
            estimated_time=estimated_time,
            subtasks=[],
            reasoning=reasoning,
            recommended_mode=mode,
            requires_double_check=double_check,
            recommended_roles=roles,
        )

    def _score_complexity(self, task_lower: str) -> float:
        """Score task complexity from 0.0 to 1.0."""
        score = 0.5
        words = task_lower.split()

        simple_count = sum(1 for word in words if any(kw in word for kw in self.SIMPLE_KEYWORDS))
        complex_count = sum(1 for word in words if any(kw in word for kw in self.COMPLEX_KEYWORDS))

        word_count = len(words)
        if word_count > 0:
            simple_ratio = simple_count / word_count
            complex_ratio = complex_count / word_count
            score = 0.5 + (complex_ratio - simple_ratio) * 0.35

        if len(task_lower) > 200:
            score += 0.15
        elif len(task_lower) < 25:
            score -= 0.15

        if any(marker in task_lower for marker in ["```", "def ", "class ", "test_", "raise "]):
            score = max(score, 0.7)

        return min(1.0, max(0.0, score))

    def _extract_subtasks(self, task: str) -> List[str]:
        """Extract individual subtasks if this is a multi-part question."""
        subtasks = []
        if task.count("?") > 1:
            questions = [q.strip() + "?" for q in task.split("?") if q.strip()]
            if len(questions) > 1:
                return questions

        if " and " in task.lower():
            parts = task.split(" and ")
            if len(parts) == 2 and len(parts[0]) > 25 and len(parts[1]) > 25:
                subtasks.extend([p.strip() for p in parts])

        return subtasks if len(subtasks) > 1 else []


analyzer = TaskAnalyzer()
