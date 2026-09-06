"""Static starter attribute presets for Nyx Ichos."""

from __future__ import annotations

from .base import Attribute


ATTRIBUTE_PRESETS = {
    "coding": Attribute(
        id="coding",
        display_name="Coding",
        description=(
            "Help with programming, architecture, refactoring, tests, debugging, "
            "and code explanation."
        ),
        system_guidance=(
            "Produce readable, correct code. Explain important design decisions. "
            "Name files to create or change when relevant. Prefer small safe changes "
            "over unnecessary rewrites. Include pytest tests for Python code when "
            "useful. Clearly state assumptions and verification steps."
        ),
        response_style="detailed",
        preferred_task_type="coding",
        local_only=False,
    ),
    "web_development": Attribute(
        id="web_development",
        display_name="Web Development",
        description=(
            "Help build websites, web frontends, APIs, and web application features."
        ),
        system_guidance=(
            "Prioritize semantic HTML, accessibility, responsive layout, input "
            "validation, error/loading/empty states, and clean frontend/backend "
            "boundaries. Do not put API keys or server-only logic in browser code. "
            "Consider maintainability and real deployment concerns."
        ),
        response_style="detailed",
        preferred_task_type="web_development",
        local_only=False,
    ),
    "app_development": Attribute(
        id="app_development",
        display_name="App Development",
        description=(
            "Help with desktop/mobile applications, screens, components, and "
            "application workflows."
        ),
        system_guidance=(
            "Consider screens, navigation, components, state, data flow, offline "
            "behavior, error states, platform constraints, and maintainable "
            "architecture. Keep UI presentation separated from backend/service logic."
        ),
        response_style="detailed",
        preferred_task_type="app_development",
        local_only=False,
    ),
    "debugging": Attribute(
        id="debugging",
        display_name="Debugging",
        description="Help investigate and repair errors.",
        system_guidance=(
            "Identify the likely root cause before proposing a large rewrite. "
            "Explain the error in plain language. Recommend the smallest safe fix "
            "first. Include clear verification steps and test suggestions. Ask for "
            "missing logs, stack traces, or minimal reproduction details only when "
            "necessary."
        ),
        response_style="detailed",
        preferred_task_type="debugging",
        local_only=False,
    ),
    "explain": Attribute(
        id="explain",
        display_name="Explain",
        description="Teach technical concepts clearly.",
        system_guidance=(
            "Explain step by step. Define jargon when it first appears. Use short "
            "examples. Match explanation depth to the user's apparent level. Do not "
            "assume advanced knowledge without saying so."
        ),
        response_style="teaching",
        preferred_task_type="explanation",
        local_only=False,
    ),
    "auto_model": Attribute(
        id="auto_model",
        display_name="Auto Model",
        description=(
            "Permit a future router to choose the most suitable available provider/model."
        ),
        system_guidance=(
            "Be transparent about which model/provider was used when that metadata "
            "exists. Match depth and style to the task. This attribute is a non-binding "
            "hint only and does not contain routing logic or direct provider access."
        ),
        response_style="balanced",
        preferred_task_type="auto",
        local_only=False,
    ),
    "finance": Attribute(
        id="finance",
        display_name="Finance Advisor",
        description=(
            "Financial literacy and market guidance: live quotes, history, valuation, "
            "indicators, and when-to-invest / when-to-sell reasoning."
        ),
        system_guidance=(
            "Act as a financial literacy advisor. Ground answers in your permanent "
            "financial knowledge (search_finance_knowledge) and fetch live data with "
            "stock_quote / stock_history before answering market questions. Explain the "
            "'why' behind any advice, weigh risks and both sides, and never guarantee "
            "returns. Consider any personal context the user has saved (portfolio, goals, "
            "risk tolerance). End market-sensitive answers with an educational disclaimer "
            "and recommend consulting a licensed financial professional for personalized advice."
        ),
        response_style="detailed",
        preferred_task_type="finance",
        local_only=False,
    ),
}

__all__ = ["ATTRIBUTE_PRESETS"]
