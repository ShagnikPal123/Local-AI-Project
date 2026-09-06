"""Permanent general knowledge store for Nyx Ichos.

Loads ``general_knowledge.md`` (a curated, always-available reference of
common facts: history, math, science, geography, technology, units) and makes
it searchable with the same lightweight token-overlap scoring used by the RAG
memory layer — no external dependencies required.

This is the assistant's permanent brain: it is independent from the user's
personal memory (memory.json) and is always present, even in a brand-new chat
or on a fresh install.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_KNOWLEDGE_FILE = "general_knowledge.md"

_TOKEN_PATTERN = re.compile(r"[a-z0-9']+")

# Words that carry no retrieval signal.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "by",
    "for", "with", "from", "is", "are", "was", "were", "be", "it", "its",
    "how", "what", "when", "where", "who", "which", "why", "do", "does",
    "did", "this", "that", "these", "those", "as", "if", "then", "than",
    "not", "no", "can", "could", "would", "should", "will", "i", "you",
    "me", "my", "your", "about", "into", "over", "under", "after",
    # Single letters are noise in weighted-overlap scoring (e.g. P/E -> p, e).
    "a", "b", "c", "d", "e", "f", "g", "h", "j", "k", "l", "m", "n",
    "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
}

# Abbreviation/synonym expansion so "ww2", "usa", "km" find their full terms.
_ALIASES = {
    "ww1": ("world", "war", "one", "wwi"),
    "ww2": ("world", "war", "two", "wwii"),
    "wwi": ("world", "war", "one", "ww1"),
    "wwii": ("world", "war", "two", "ww2"),
    "usa": ("united", "states", "america"),
    "us": ("united", "states"),
    "uk": ("united", "kingdom", "britain"),
    "km": ("kilometer", "kilometers", "kmh"),
    "kmh": ("kilometer", "kilometers", "per", "hour"),
    "mph": ("miles", "per", "hour"),
    "kg": ("kilogram", "kilograms"),
    "cm": ("centimeter", "centimeters"),
    "mm": ("millimeter", "millimeters"),
    "gb": ("gigabyte", "gigabytes"),
    "mb": ("megabyte", "megabytes"),
    "kb": ("kilobyte", "kilobytes"),
    "sqrt": ("square", "root"),
    "math": ("mathematics", "mathematical"),
    "chem": ("chemistry", "chemical"),
    "eng": ("engineering", "engine"),
    "usd": ("dollar", "dollars"),
    "eu": ("european", "union"),
    "un": ("united", "nations"),
    "nasa": ("space", "agency"),
}


def _tokens(text: str) -> List[str]:
    return _TOKEN_PATTERN.findall((text or "").lower())


def _query_tokens(query: str) -> List[str]:
    """Tokenize a query, drop stopwords, and expand abbreviations."""
    tokens = [t for t in _tokens(query) if t not in _STOPWORDS]
    expanded: List[str] = []
    for token in tokens:
        expanded.append(token)
        expanded.extend(_ALIASES.get(token, ()))
    return expanded


def _score(query_tokens: List[str], document_tokens: List[str], title_tokens: Optional[List[str]] = None) -> float:
    """Score a chunk by weighted token overlap with the query.

    Exact matches dominate; a small prefix bonus lets inflected forms match
    (e.g. query "sell" matches document "selling"). Section-title tokens are
    weighted higher so heading words pull a chunk up.
    """
    if not query_tokens or not document_tokens:
        return 0.0
    doc_counts: Dict[str, int] = {}
    for token in document_tokens:
        doc_counts[token] = doc_counts.get(token, 0) + 1
    title_counts: Dict[str, int] = {}
    for token in title_tokens or []:
        title_counts[token] = title_counts.get(token, 0) + 1

    score = 0.0
    for token in query_tokens:
        if token in doc_counts:
            title_prefix = any(
                title_token.startswith(token) for title_token in title_counts
            )
            weight = 2.0 if (token in title_counts or title_prefix) else 1.0
            score += weight / (1.0 + doc_counts[token])
        else:
            prefix_matches = sum(
                1 for doc_token in doc_counts if doc_token.startswith(token)
            )
            if prefix_matches:
                title_prefix = sum(
                    1 for doc_token in title_counts if doc_token.startswith(token)
                )
                weight = 2.0 if title_prefix else 1.0
                score += (0.25 * weight) / (1.0 + prefix_matches)
    return score


class GeneralKnowledge:
    """Searchable store over the permanent general knowledge markdown file."""

    def __init__(self, path: Optional[str | Path] = None):
        self.path = Path(path) if path is not None else Path(_DEFAULT_KNOWLEDGE_FILE)
        self.chunks: List[Dict[str, Any]] = []
        self.sections: List[str] = []
        self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Read the markdown file and split it into section-headed chunks."""
        self.chunks = []
        self.sections = []
        if not self.path.exists():
            return

        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return

        current_section = "General"
        current_lines: List[str] = []
        for line in text.splitlines():
            heading = line.strip()
            if heading.startswith("## "):
                if current_lines:
                    self._append_chunk(current_section, current_lines)
                current_section = heading[3:].strip()
                self.sections.append(current_section)
                current_lines = []
            elif heading.startswith("#"):
                continue
            else:
                current_lines.append(line)
        if current_lines:
            self._append_chunk(current_section, current_lines)

    def _append_chunk(self, section: str, lines: List[str]) -> None:
        content = "\n".join(line for line in lines if line.strip())
        if not content.strip():
            return
        # Section-title words join the chunk tokens so headings like
        # "When to Consider Selling" are searchable and weighted higher.
        title_tokens = _tokens(section)
        self.chunks.append(
            {
                "section": section,
                "text": content.strip(),
                "tokens": title_tokens + _tokens(content),
                "title_tokens": title_tokens,
            }
        )

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Return the most relevant knowledge chunks for a query."""
        query_tokens = _query_tokens(query)
        if not query_tokens or not self.chunks:
            return []
        scored = [
            (chunk, _score(query_tokens, chunk["tokens"], chunk.get("title_tokens")))
            for chunk in self.chunks
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            {
                "section": chunk["section"],
                "text": chunk["text"],
                "score": round(score, 4),
            }
            for chunk, score in scored[:limit]
            if score > 0
        ]

    def search_text(self, query: str, limit: int = 5) -> str:
        """Human-readable search result for tool/CLI output."""
        results = self.search(query, limit=limit)
        if not results:
            return f"No general knowledge found for: {query}"
        lines = [f"General knowledge for '{query}':"]
        for result in results:
            lines.append(f"\n[{result['section']}]\n{result['text']}")
        return "\n".join(lines)

    def build_context_prompt(self) -> str:
        """A compact always-on context line pointing at the knowledge base."""
        if not self.chunks:
            return ""
        section_list = ", ".join(self.sections[:8])
        return (
            "[General Knowledge]\n"
            "You have a permanent general knowledge base (history, math, science, "
            f"geography, technology, units). Sections: {section_list}.\n"
            "When a question asks for facts, formulas, conversions, or historical "
            "data, consult it with the search_knowledge tool before answering."
        )

    def status(self) -> Dict[str, Any]:
        return {
            "file": str(self.path),
            "loaded": bool(self.chunks),
            "sections": self.sections,
            "chunks": len(self.chunks),
        }


_knowledge: Optional[GeneralKnowledge] = None


def get_knowledge(path: Optional[str | Path] = None) -> GeneralKnowledge:
    """Get or create the global knowledge store."""
    global _knowledge
    if _knowledge is None:
        _knowledge = GeneralKnowledge(path=path)
    return _knowledge
