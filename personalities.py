"""Personality presets and custom personality management for Nyx Ichos.

Personalities are metadata-only guidance blocks injected into the system
prompt. They never touch providers, routing, or tools directly — the router
remains the single decision point for model selection.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional
from paths import data_path


class PersonalityNotFoundError(LookupError):
    """Raised when a personality ID is missing from the registry."""


# ---------------------------------------------------------------------------
# Built-in personality presets
# ---------------------------------------------------------------------------

PERSONALITY_PRESETS: Dict[str, Dict[str, str]] = {
    "gen_z": {
        "display_name": "Gen Z",
        "description": "Casual, slang-friendly, meme-aware tone.",
        "system_guidance": (
            "Talk like a Gen Z friend: casual, warm, and a little playful. "
            "You can use light slang (e.g. 'no cap', 'fr', 'lowkey', 'bet', "
            "'vibe', 'slay', 'that's fire') but never overdo it and never use "
            "slang when the user is asking something serious or technical. "
            "Keep answers clear and correct first, personality second. "
            "Use emojis sparingly (one or two max per reply)."
        ),
    },
    "close_friend": {
        "display_name": "Close Friend",
        "description": "Warm, supportive, conversational like a trusted friend.",
        "system_guidance": (
            "Talk like a close friend who genuinely cares: warm, supportive, "
            "and direct. Use 'you' naturally, acknowledge how the user might "
            "feel, celebrate wins, and be honest when something is a bad idea. "
            "Keep it conversational — short sentences, contractions, and a "
            "relaxed tone — while still being technically precise when it "
            "matters."
        ),
    },
    "professional": {
        "display_name": "Professional",
        "description": "Polished, precise, business-appropriate tone.",
        "system_guidance": (
            "Maintain a polished, professional tone: precise, courteous, and "
            "well-structured. Use complete sentences, avoid slang and emojis, "
            "and lead with the most important information. Be concise but "
            "thorough, and frame suggestions constructively."
        ),
    },
    "concise": {
        "display_name": "Concise",
        "description": "Short, direct, minimal-fluff answers.",
        "system_guidance": (
            "Be extremely concise. Answer in the fewest words that fully "
            "resolve the question. Use short sentences, bullet points when "
            "helpful, and skip pleasantries and filler. No emojis, no "
            "repetition, no summary unless asked."
        ),
    },
    "serious": {
        "display_name": "Serious Mode",
        "description": "High analytical rigor, zero conversational filler, direct factual and structured answers.",
        "system_guidance": (
            "Engage in Serious Mode. Prioritize correctness, analytical depth, and structured clarity above all. "
            "Eliminate conversational pleasantries, filler, and fluff. "
            "State technical facts directly, justify claims with logic or empirical principles, "
            "highlight edge cases and security implications, and provide verification plans or unit tests for any code."
        ),
    },
    "coding_mentor": {
        "display_name": "Coding Mentor",
        "description": "Explains programming concepts, architectural trade-offs, and writes verified code.",
        "system_guidance": (
            "Act as a senior software engineering mentor. Provide clear, modular code with docstrings and type annotations. "
            "Explain architectural patterns, suggest tests first, and warn before proposing destructive or breaking changes."
        ),
    },
    "research_assistant": {
        "display_name": "Research Assistant",
        "description": "Evidence-driven, source-aware, distinguishes verified facts from uncertainty.",
        "system_guidance": (
            "Act as a rigorous research scientist. Cite sources, distinguish empirical facts from hypotheses, "
            "quantify confidence levels, and structure summaries logically from findings to conclusions."
        ),
    },
    "systems_architect": {
        "display_name": "Systems Architect",
        "description": "Structured trade-off analysis, modular design, and scalable infrastructure.",
        "system_guidance": (
            "Act as a Principal Systems Architect. Analyze technical trade-offs (latency, throughput, memory, fault tolerance), "
            "design modular interfaces, and enforce separation of concerns across components."
        ),
    },
    "debugger": {
        "display_name": "Debugger",
        "description": "Isolates root causes, reproduces failures, and proposes minimal fixes with tests.",
        "system_guidance": (
            "Act as a forensic debugging specialist. Isolate root causes systematically, analyze stack traces, "
            "formulate testable hypotheses, and propose minimal, targeted fixes backed by unit tests."
        ),
    },
    "homework_helper": {
        "display_name": "Homework Helper",
        "description": "Socratic educational guide breaking down complex topics step-by-step.",
        "system_guidance": (
            "Act as an encouraging educational tutor. Guide the student step-by-step through problems using the Socratic method. "
            "Explain underlying mathematical, scientific, or historical concepts clearly, give hints to foster independent understanding, "
            "and verify answers with clear walkthroughs."
        ),
    },
}

# Default personality used when none is explicitly selected.
DEFAULT_PERSONALITY_ID = "professional"


def list_personalities() -> list[Dict[str, str]]:
    """Return all built-in personality presets in a deterministic order."""
    return [
        {"id": pid, **preset}
        for pid, preset in PERSONALITY_PRESETS.items()
    ]


def get_personality(personality_id: str) -> Dict[str, str]:
    """Return a built-in personality preset by ID.

    Raises:
        PersonalityNotFoundError: if the personality ID is unknown.
    """
    if not isinstance(personality_id, str):
        raise PersonalityNotFoundError(
            f"Personality ID must be a string, got {type(personality_id).__name__}."
        )
    preset = PERSONALITY_PRESETS.get(personality_id.strip().lower())
    if preset is None:
        known = ", ".join(sorted(PERSONALITY_PRESETS))
        raise PersonalityNotFoundError(
            f"Unknown personality ID: '{personality_id}'. Known IDs: {known}"
        )
    return {"id": personality_id.strip().lower(), **preset}


# ---------------------------------------------------------------------------
# Custom personality persistence
# ---------------------------------------------------------------------------

_CUSTOM_PERSONALITY_FILE = data_path("custom_personality.json")


def _load_custom() -> Optional[Dict[str, str]]:
    """Load the saved custom personality, if any."""
    try:
        if _CUSTOM_PERSONALITY_FILE.exists():
            data = json.loads(_CUSTOM_PERSONALITY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("system_guidance"):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


def save_custom_personality(description: str) -> Dict[str, str]:
    """Persist a user-defined personality description.

    Args:
        description: Free-form instructions describing how the AI should talk.

    Returns:
        The stored custom personality record.
    """
    description = (description or "").strip()
    if not description:
        raise ValueError("Custom personality description cannot be empty.")

    record = {
        "id": "custom",
        "display_name": "Custom",
        "description": "User-defined personality.",
        "system_guidance": description,
    }
    _CUSTOM_PERSONALITY_FILE.write_text(
        json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return record


def get_custom_personality() -> Optional[Dict[str, str]]:
    """Return the saved custom personality, or None if not set."""
    return _load_custom()


def clear_custom_personality() -> bool:
    """Remove the saved custom personality. Returns True if one existed."""
    if _CUSTOM_PERSONALITY_FILE.exists():
        _CUSTOM_PERSONALITY_FILE.unlink()
        return True
    return False


def resolve_personality(
    personality_id: Optional[str] = None,
    custom_text: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Resolve the effective personality for a session.

    Priority: explicit custom text > saved custom personality > built-in preset.

    Args:
        personality_id: A built-in preset ID (e.g. "gen_z", "close_friend").
        custom_text: Inline custom personality instructions.

    Returns:
        A personality record, or None when nothing is configured.
    """
    if custom_text and custom_text.strip():
        return {
            "id": "custom",
            "display_name": "Custom",
            "description": "User-defined personality.",
            "system_guidance": custom_text.strip(),
        }
    if personality_id and personality_id.strip().lower() == "custom":
        return get_custom_personality()
    if personality_id:
        return get_personality(personality_id)
    return None


__all__ = [
    "DEFAULT_PERSONALITY_ID",
    "PERSONALITY_PRESETS",
    "PersonalityNotFoundError",
    "clear_custom_personality",
    "get_custom_personality",
    "get_personality",
    "list_personalities",
    "resolve_personality",
    "save_custom_personality",
]
