"""Multi-agent orchestrator for parallel task processing, strain-aware scaling, and load distribution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import threading
import time
from typing import Any, Dict, List, Optional
import uuid

from approaches import build_multi_approach_prompt, get_approach
from chat_service import ChatService
from device_profile import get_device_profile
from hardware_safety import SAFETY_MONITOR
from task_analyzer import TaskAnalysis, TaskComplexity, analyzer


class AgentMode(Enum):
    """Mode of operation for an agent."""

    QUICK = "quick"  # Fast, direct responses
    DEEP = "deep"  # Deep thinking, detailed analysis
    SPECIALIZED = "specialized"  # Specialized for a domain
    RESEARCH = "research"  # Research with current web sources & fact checking
    CODING = "coding"  # Coding implementation, architecture, and debugging
    SUPER_RESEARCH = "super_research"  # Extended multi-source research
    SELF_IMPROVE = "self_improve"  # Controlled self-improvement proposals
    AUTO = "auto"  # Adaptive multi-approach routing


@dataclass
class TaskResult:
    """Result from processing a task."""

    task_id: str
    agent_id: str
    response: str
    provider: str
    processing_time: float
    mode: AgentMode
    timestamp: datetime


class Agent:
    """Individual agent for processing tasks."""

    def __init__(self, agent_id: str, mode: AgentMode, attribute_id: Optional[str] = None):
        self.agent_id = agent_id
        self.mode = mode
        self.attribute_id = attribute_id
        self.service = ChatService(attribute_id=attribute_id)
        self.is_busy = False
        self.tasks_completed = 0
        self.total_processing_time = 0.0

    def process(self, task: str) -> TaskResult:
        """Process a task synchronously with hardware safety throttling."""
        start_time = time.time()
        self.is_busy = True

        # Apply thermal throttle backoff if hardware is running hot
        throttle_delay = SAFETY_MONITOR.calculate_strain_throttle()
        if throttle_delay > 0:
            time.sleep(throttle_delay)

        try:
            mode_hints = {
                AgentMode.DEEP: "[DEEP ANALYSIS MODE] Provide thorough analysis, verify all assumptions, and inspect edge cases.",
                AgentMode.RESEARCH: "[RESEARCH MODE] Use current web research, cross-reference multiple independent sources, check timestamps, and double-check facts.",
                AgentMode.CODING: "[CODING MODE] Focus on clean, modular, typed code. Validate imports, handle edge cases, and ensure testability.",
                AgentMode.SUPER_RESEARCH: "[SUPER RESEARCH MODE] Perform extended multi-source research, compare evidence, identify conflicts, and build an expert-level synthesis.",
                AgentMode.SELF_IMPROVE: "[SELF-IMPROVE MODE] Propose reversible, testable improvements. Do not modify live code without explicit user approval.",
                AgentMode.AUTO: "[AUTO MULTI-APPROACH MODE] Dynamically analyze, solve, and double-check.",
            }
            hint = mode_hints.get(self.mode)
            task_with_hint = f"{hint}\n\n{task}" if hint and hint not in task else task

            response, provider = self.service.chat(task_with_hint)
            processing_time = time.time() - start_time

            self.tasks_completed += 1
            self.total_processing_time += processing_time

            return TaskResult(
                task_id=str(uuid.uuid4()),
                agent_id=self.agent_id,
                response=response,
                provider=provider,
                processing_time=round(processing_time, 3),
                mode=self.mode,
                timestamp=datetime.now(),
            )
        finally:
            self.is_busy = False

    def get_stats(self) -> Dict[str, Any]:
        """Get agent statistics."""
        avg_time = (
            self.total_processing_time / self.tasks_completed
            if self.tasks_completed > 0
            else 0.0
        )
        return {
            "agent_id": self.agent_id,
            "mode": self.mode.value,
            "is_busy": self.is_busy,
            "tasks_completed": self.tasks_completed,
            "avg_processing_time": round(avg_time, 3),
            "attribute": self.attribute_id,
        }


class AgentPool:
    """Manages a pool of agents with hardware-aware auto-scaling."""

    def __init__(self, initial_size: int = 2, max_agents: Optional[int] = None):
        profile = get_device_profile()
        hardware_max = profile.max_workers
        self.max_agents = min(max_agents or hardware_max, max(1, hardware_max))
        self.agents: List[Agent] = []
        self.results: Dict[str, TaskResult] = {}
        self.lock = threading.Lock()

        initial_count = min(initial_size, self.max_agents)
        self._create_initial_pool(initial_count)

    def _create_initial_pool(self, size: int) -> None:
        with self.lock:
            for i in range(max(1, size // 2)):
                self.agents.append(Agent(f"quick-{i}", AgentMode.QUICK))
            for i in range(max(1, size - (size // 2))):
                self.agents.append(Agent(f"deep-{i}", AgentMode.DEEP))

    def _find_available_agent(self, mode: Optional[AgentMode] = None) -> Optional[Agent]:
        with self.lock:
            if mode:
                for agent in self.agents:
                    if not agent.is_busy and agent.mode == mode:
                        return agent
            for agent in self.agents:
                if not agent.is_busy:
                    return agent
        return None

    def _governor_agent_ceiling(self) -> Optional[int]:
        """The resource governor's current cap on concurrent agents.

        Returns None when the governor is unavailable, so the pool keeps working
        on its own limits rather than refusing to run. A governor that can break
        the product by being absent is worse than no governor.
        """
        try:
            from resource_governor import GOVERNOR

            return int(GOVERNOR.ceiling().max_agents)
        except Exception:
            return None

    def _effective_max_agents(self) -> int:
        """Pool limit, further constrained by the user's selected power mode.

        This is what makes the power setting enforcement rather than decoration:
        choosing Low actually stops the pool growing.
        """
        ceiling = self._governor_agent_ceiling()
        if ceiling is None:
            return self.max_agents
        return max(1, min(self.max_agents, ceiling))

    def _should_spawn_agent(self) -> bool:
        limit = self._effective_max_agents()
        with self.lock:
            busy_count = sum(1 for a in self.agents if a.is_busy)
            total_count = len(self.agents)
            if total_count == 0:
                return True
            return (busy_count / total_count > 0.75) and (total_count < limit)

    def _spawn_agent(self) -> Optional[Agent]:
        limit = self._effective_max_agents()
        with self.lock:
            if len(self.agents) >= limit:
                return None

            quick_count = sum(1 for a in self.agents if a.mode == AgentMode.QUICK)
            deep_count = sum(1 for a in self.agents if a.mode == AgentMode.DEEP)

            mode = AgentMode.DEEP if deep_count <= quick_count else AgentMode.QUICK
            agent_id = f"{mode.value}-{len(self.agents)}"

            new_agent = Agent(agent_id, mode)
            self.agents.append(new_agent)
            return new_agent

    def process_task(
        self,
        task: str,
        attribute_id: Optional[str] = None,
        force_mode: Optional[AgentMode] = None,
    ) -> TaskResult:
        """Process a task, auto-scaling agents bounded by hardware capabilities."""
        if force_mode:
            mode = force_mode
        else:
            analysis = analyzer.analyze(task)
            if analysis.recommended_mode == "coding":
                mode = AgentMode.CODING
            elif analysis.recommended_mode == "quick":
                mode = AgentMode.QUICK
            else:
                mode = AgentMode.DEEP

        agent = self._find_available_agent(mode)

        while agent is None and self._should_spawn_agent():
            agent = self._spawn_agent()
            if agent is None:
                break

        retry_count = 0
        while agent is None and retry_count < 30:
            time.sleep(0.05)
            agent = self._find_available_agent(mode)
            retry_count += 1

        if agent is None:
            with self.lock:
                agent = self.agents[0] if self.agents else None

        if agent is None:
            raise RuntimeError("No agents available in pool")

        result = agent.process(task)
        self.results[result.task_id] = result
        return result

    def process_approaches(
        self,
        task: str,
        approaches: List[str],
        attribute_id: Optional[str] = None,
    ) -> List[TaskResult]:
        """Run the task through different strategies concurrently."""
        from concurrent.futures import ThreadPoolExecutor

        def _run_one(appr: str) -> TaskResult:
            prompt = build_multi_approach_prompt(task, appr)
            return self.process_task(prompt, attribute_id)

        with ThreadPoolExecutor(max_workers=min(len(approaches), self.max_agents)) as executor:
            return list(executor.map(_run_one, approaches))

    def process_parallel(
        self,
        tasks: List[str],
        attribute_ids: Optional[List[Optional[str]]] = None,
    ) -> List[TaskResult]:
        """Process multiple independent subtasks concurrently."""
        from concurrent.futures import ThreadPoolExecutor

        if attribute_ids is None:
            attribute_ids = [None] * len(tasks)

        def _run_subtask(item: tuple[str, Optional[str]]) -> TaskResult:
            subtask_text, attr_id = item
            return self.process_task(subtask_text, attr_id)

        items = list(zip(tasks, attribute_ids))
        max_workers = min(len(tasks), self.max_agents)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(_run_subtask, items))

    def get_pool_stats(self) -> Dict[str, Any]:
        """Get statistics about the agent pool and hardware capacity."""
        with self.lock:
            busy_count = sum(1 for a in self.agents if a.is_busy)
            agent_stats = [a.get_stats() for a in self.agents]
            profile = get_device_profile()

            return {
                "total_agents": len(self.agents),
                "busy_agents": busy_count,
                "idle_agents": len(self.agents) - busy_count,
                "max_agents": self.max_agents,
                "hardware_max_workers": profile.max_workers,
                "power_mode": profile.recommended_power_mode,
                "agents": agent_stats,
            }

    def shutdown(self) -> None:
        """Shutdown all agents gracefully."""
        with self.lock:
            self.agents.clear()


_agent_pool: Optional[AgentPool] = None


def get_agent_pool(initial_size: int = 2, max_agents: int = 10) -> AgentPool:
    """Get or create the global agent pool."""
    global _agent_pool
    if _agent_pool is None:
        _agent_pool = AgentPool(initial_size, max_agents)
    return _agent_pool


def shutdown_pool() -> None:
    """Shutdown the global agent pool."""
    global _agent_pool
    if _agent_pool:
        _agent_pool.shutdown()
        _agent_pool = None
