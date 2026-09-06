"""Multi-mode chat interface with intelligent task routing, auto-scaling, and multi-route double checking."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from colorama import Fore, Style

from agent_pool import AgentMode, get_agent_pool
from approaches import APPROACHES, build_multi_approach_prompt, get_approach
from task_analyzer import TaskComplexity, analyzer


class MultiModeChat:
    """Chat interface with multiple modes, parallel processing, and automatic multi-approach coordination."""

    def __init__(self, use_pool: bool = True, pool_size: int = 2, max_agents: int = 10):
        self.use_pool = use_pool
        if use_pool:
            self.pool = get_agent_pool(pool_size, max_agents)
        else:
            self.pool = None

    def analyze_task(self, task: str) -> Dict[str, Any]:
        """Analyze a task and return recommended strategy."""
        analysis = analyzer.analyze(task)
        return {
            "task": task[:60] + "..." if len(task) > 60 else task,
            "complexity": analysis.complexity.value,
            "estimated_time": analysis.estimated_time,
            "recommended_mode": analysis.recommended_mode,
            "reasoning": analysis.reasoning,
            "subtasks": analysis.subtasks,
            "is_parallel": analysis.complexity == TaskComplexity.PARALLEL,
            "requires_double_check": analysis.requires_double_check,
            "recommended_roles": analysis.recommended_roles,
        }

    def chat(
        self,
        task: str,
        attribute_id: Optional[str] = None,
        verbose: bool = False,
        force_mode: Optional[str] = None,
        research_minutes: Optional[int] = None,
        approach: str = "auto",
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Process a task with intelligent mode selection and automatic multi-approach double-checking.

        Args:
            task: The task/question to process
            attribute_id: Optional attribute for guidance
            verbose: Show detailed task analysis
            force_mode: Force a specific mode, overriding automatic detection
            research_minutes: Optional time budget for super research
            approach: Solution approach (defaults to adaptive 'auto')

        Returns:
            (response, provider, metadata)
        """
        if not self.use_pool:
            from chat_service import ChatService

            service = ChatService(attribute_id=attribute_id)
            response, provider = service.chat(task)
            return response, provider, {"mode": "single_agent", "approach": "auto"}

        analysis = self.analyze_task(task)

        if verbose:
            print(f"\n{Fore.CYAN}[Task Analysis]{Style.RESET_ALL}")
            print(f"  Complexity: {analysis['complexity']}")
            print(f"  Mode: {analysis['recommended_mode']}")
            print(f"  Estimated time: {analysis['estimated_time']:.1f}s")
            print(f"  Roles: {', '.join(analysis['recommended_roles'])}")
            print(f"  Reasoning: {analysis['reasoning']}")

        # Handle parallel subtasks
        if analysis["is_parallel"] and analysis["subtasks"]:
            if verbose:
                print(f"\n{Fore.YELLOW}[Parallel Sub-Agent Processing]{Style.RESET_ALL}")
                print(f"  Processing {len(analysis['subtasks'])} subtasks concurrently...")

            results = self.pool.process_parallel(
                analysis["subtasks"],
                [attribute_id] * len(analysis["subtasks"]),
            )

            combined_response = "\n\n".join(
                [f"**Part {i+1}:**\n{r.response}" for i, r in enumerate(results)]
            )

            return (
                combined_response,
                "multi-agent",
                {
                    "mode": "parallel",
                    "subtasks": len(results),
                    "agents_used": len(set(r.agent_id for r in results)),
                    "total_time": round(sum(r.processing_time for r in results), 3),
                    "approach": "auto",
                },
            )

        # Determine agent mode
        if force_mode:
            try:
                mode = AgentMode(force_mode.lower())
            except ValueError:
                mode = AgentMode.DEEP
            if verbose:
                print(f"\n{Fore.YELLOW}[Mode Override]{Style.RESET_ALL}: {force_mode}")
        else:
            rec_mode = analysis["recommended_mode"]
            if rec_mode == "coding":
                mode = AgentMode.CODING
            elif rec_mode == "quick":
                mode = AgentMode.QUICK
            elif rec_mode == "research":
                mode = AgentMode.RESEARCH
            else:
                mode = AgentMode.DEEP

        # Apply multi-approach instruction
        selected_approach = (approach or "auto").lower()
        prompt_with_approach = build_multi_approach_prompt(task, selected_approach)

        if mode == AgentMode.SUPER_RESEARCH and research_minutes:
            prompt_with_approach = f"Research time budget: {research_minutes} minutes.\n{prompt_with_approach}"

        result = self.pool.process_task(prompt_with_approach, attribute_id, force_mode=mode)

        if verbose:
            print(f"\n{Fore.GREEN}[Processing Completed]{Style.RESET_ALL}")
            print(f"  Agent: {result.agent_id} | Mode: {result.mode.value} | Time: {result.processing_time:.2f}s")

        return (
            result.response,
            result.provider,
            {
                "mode": result.mode.value,
                "agent": result.agent_id,
                "processing_time": result.processing_time,
                "approach": selected_approach,
                "available_approaches": list(APPROACHES),
                "double_checked": analysis["requires_double_check"],
            },
        )

    def get_status(self) -> Dict[str, Any]:
        """Get current system and pool status."""
        pool_stats = self.pool.get_pool_stats() if self.use_pool else None
        return {
            "multi_mode_enabled": self.use_pool,
            "pool": pool_stats,
        }

    def shutdown(self) -> None:
        """Shutdown the agent pool."""
        if self.use_pool and self.pool:
            from agent_pool import shutdown_pool

            shutdown_pool()


_multi_chat: Optional[MultiModeChat] = None


def get_multi_mode_chat(use_pool: bool = True) -> MultiModeChat:
    """Get or create the global multi-mode chat instance."""
    global _multi_chat
    if _multi_chat is None:
        _multi_chat = MultiModeChat(use_pool=use_pool)
    return _multi_chat
