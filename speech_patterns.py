"""Speech pattern learning for Nyx Ichos.

Analyzes the user's own messages to learn how they like to speak — slang,
emoji usage, sentence length, capitalization, and common phrases — then
persists those patterns to memory so the assistant can mirror the user's
voice in future conversations.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from paths import data_path

# ---------------------------------------------------------------------------
# Pattern analysis
# ---------------------------------------------------------------------------

_SLANG_TERMS = {
    "no cap", "fr", "lowkey", "highkey", "bet", "vibe", "slay", "fire",
    "lit", "sus", "based", "cringe", "goat", "w", "l", "ngl", "tbh",
    "imo", "idk", "ikr", "omg", "lol", "lmao", "rofl", "smh", "fyi",
    "btw", "rn", "af", "asap", "brb", "gtg", "wyd", "wya", "hmu",
    "dope", "chill", "fam", "bro", "dude", "y'all", "gonna", "wanna",
    "gotta", "kinda", "sorta", "ain't", "yep", "nah", "yeah", "okay",
}

_EMOJI_PATTERN = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]"
)

_SENTENCE_SPLIT = re.compile(r"[.!?]+")


def _count_emoji(text: str) -> int:
    return len(_EMOJI_PATTERN.findall(text))


def _count_slang(text: str) -> int:
    lowered = text.lower()
    return sum(1 for term in _SLANG_TERMS if term in lowered)


def _average_sentence_length(text: str) -> float:
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
    if not sentences:
        return 0.0
    return sum(len(s.split()) for s in sentences) / len(sentences)


def _common_phrases(messages: List[str], limit: int = 5) -> List[str]:
    """Extract frequently repeated short phrases from the user's messages."""
    counts: Dict[str, int] = {}
    for message in messages:
        lowered = message.lower()
        for phrase in re.findall(r"\b[\w']{2,}\b", lowered):
            counts[phrase] = counts.get(phrase, 0) + 1
    return [
        word for word, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)
        if counts[word] >= 2
    ][:limit]


def analyze_speech_patterns(messages: List[str]) -> Dict[str, Any]:
    """Analyze a batch of user messages and return a pattern summary.

    Args:
        messages: Raw user message strings (non-empty preferred).

    Returns:
        A dict describing the user's speaking style.
    """
    messages = [m for m in (messages or []) if m and m.strip()]
    if not messages:
        return {}

    total_chars = sum(len(m) for m in messages)
    emoji_count = sum(_count_emoji(m) for m in messages)
    slang_count = sum(_count_slang(m) for m in messages)
    avg_len = sum(_average_sentence_length(m) for m in messages) / len(messages)

    patterns: Dict[str, Any] = {
        "sample_count": len(messages),
        "emoji_usage": "frequent" if emoji_count / len(messages) >= 0.5 else "rare",
        "slang_usage": "frequent" if slang_count / len(messages) >= 0.3 else "occasional" if slang_count else "none",
        "average_sentence_length": round(avg_len, 1),
        "message_style": (
            "short" if avg_len < 8
            else "long" if avg_len > 20
            else "medium"
        ),
        "capitalization": (
            "lowercase" if sum(1 for m in messages if m == m.lower()) / len(messages) > 0.5
            else "standard"
        ),
        "common_phrases": _common_phrases(messages),
        "total_characters": total_chars,
    }
    return patterns


def format_patterns_for_prompt(patterns: Dict[str, Any]) -> str:
    """Render learned speech patterns as a system-prompt guidance block."""
    if not patterns:
        return ""

    lines = ["Speech style learned from the user:"]
    if patterns.get("emoji_usage"):
        lines.append(f"- Emoji usage: {patterns['emoji_usage']}")
    if patterns.get("slang_usage"):
        lines.append(f"- Slang usage: {patterns['slang_usage']}")
    if patterns.get("message_style"):
        lines.append(f"- Message length: {patterns['message_style']} "
                     f"(~{patterns.get('average_sentence_length', '?')} words per sentence)")
    if patterns.get("capitalization"):
        lines.append(f"- Capitalization: {patterns['capitalization']}")
    if patterns.get("common_phrases"):
        lines.append("- Frequently used words: " + ", ".join(patterns["common_phrases"]))
    lines.append("Mirror this style naturally in your replies without being robotic.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class SpeechPatternStore:
    """Persist learned speech patterns to a local JSON file."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else data_path("speech_patterns.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"patterns": {}, "history": []}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded.setdefault("patterns", {})
                loaded.setdefault("history", [])
                return loaded
        except (OSError, json.JSONDecodeError):
            pass
        return {"patterns": {}, "history": []}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def learn(self, messages: List[str]) -> Dict[str, Any]:
        """Analyze messages and merge the result into stored patterns."""
        patterns = analyze_speech_patterns(messages)
        if not patterns:
            return self.data["patterns"]

        self.data["history"].append(patterns)
        self.data["history"] = self.data["history"][-50:]

        # Merge: keep the most recent observation per field.
        merged = dict(self.data["patterns"])
        for key, value in patterns.items():
            if key != "sample_count":
                merged[key] = value
        merged["sample_count"] = sum(item.get("sample_count", 0) for item in self.data["history"])
        self.data["patterns"] = merged
        self._save()
        return merged

    def get_patterns(self) -> Dict[str, Any]:
        """Return the current learned patterns."""
        return dict(self.data.get("patterns", {}))

    def clear(self) -> int:
        """Clear learned patterns and history. Returns the number of samples removed."""
        count = len(self.data.get("history", []))
        self.data = {"patterns": {}, "history": []}
        self._save()
        return count

    def build_context_prompt(self) -> str:
        """Return a prompt block describing the learned speech style."""
        return format_patterns_for_prompt(self.get_patterns())


__all__ = [
    "SpeechPatternStore",
    "analyze_speech_patterns",
    "format_patterns_for_prompt",
]
