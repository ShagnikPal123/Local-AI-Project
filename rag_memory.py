"""RAG (retrieval-augmented generation) memory for Nyx Ichos.

A lightweight, dependency-free retrieval layer over the local memory store.
Chunks of important memories and curated online results are indexed with a
hybrid scoring function (token overlap + BM25-style IDF + recency), so the
most relevant context can be injected into a prompt without shipping a
vector database.

This is intentionally swappable: the `RetrievalIndex` interface is the seam
where a real embedding backend (e.g. sentence-transformers, chromadb) can be
dropped in later without changing callers.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Protocol

from memory import MemoryStore

_TOKEN_PATTERN = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> List[str]:
    return _TOKEN_PATTERN.findall((text or "").lower())


def _score(query_tokens: List[str], document_tokens: List[str]) -> float:
    """Score a document by weighted token overlap with the query."""
    if not query_tokens or not document_tokens:
        return 0.0
    doc_counts: Dict[str, int] = {}
    for token in document_tokens:
        doc_counts[token] = doc_counts.get(token, 0) + 1
    score = 0.0
    for token in query_tokens:
        if token in doc_counts:
            # Rare query tokens are more informative than common ones.
            score += 1.0 / (1.0 + doc_counts[token])
    return score


class RetrievalIndex(Protocol):
    """Interface for a retrievable memory index."""

    def add(self, document_id: str, text: str, metadata: Dict[str, Any]) -> None: ...

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]: ...

    def clear(self) -> None: ...


class TokenOverlapIndex:
    """In-memory retrieval index using token-overlap scoring."""

    def __init__(self) -> None:
        self._documents: Dict[str, Dict[str, Any]] = {}

    def add(self, document_id: str, text: str, metadata: Dict[str, Any]) -> None:
        self._documents[document_id] = {
            "id": document_id,
            "text": text,
            "tokens": _tokens(text),
            "metadata": metadata,
        }

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        query_tokens = _tokens(query)
        scored = [
            (item, _score(query_tokens, item["tokens"]))
            for item in self._documents.values()
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            {
                "id": item["id"],
                "text": item["text"],
                "metadata": item["metadata"],
                "score": round(score, 4),
            }
            for item, score in scored[:limit]
            if score > 0
        ]

    def clear(self) -> None:
        self._documents.clear()


class HybridIndex:
    """Retrieval index combining token overlap, BM25-style IDF, and recency.

    Scores are a weighted blend so the most *relevant* and *recent* memories
    surface first: relevance dominates, recency breaks ties, and rare query
    tokens are weighted higher than common ones.
    """

    def __init__(self, recency_weight: float = 0.25) -> None:
        self._documents: Dict[str, Dict[str, Any]] = {}
        self._recency_weight = recency_weight

    def add(self, document_id: str, text: str, metadata: Dict[str, Any]) -> None:
        self._documents[document_id] = {
            "id": document_id,
            "text": text,
            "tokens": _tokens(text),
            "metadata": metadata,
            "added_at": metadata.get("added_at") or 0.0,
        }

    def _idf(self, token: str) -> float:
        """Inverse document frequency: rare tokens are more informative."""
        docs_with_token = sum(1 for doc in self._documents.values() if token in doc["tokens"])
        total = max(1, len(self._documents))
        return 1.0 + (total / (1.0 + docs_with_token))

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        query_tokens = _tokens(query)
        if not query_tokens or not self._documents:
            return []
        added_times = [doc["added_at"] for doc in self._documents.values()]
        oldest = min(added_times)
        span = max(1.0, max(added_times) - oldest)
        scored = []
        for doc in self._documents.values():
            doc_counts: Dict[str, int] = {}
            for token in doc["tokens"]:
                doc_counts[token] = doc_counts.get(token, 0) + 1
            doc_len = max(1, len(doc["tokens"]))
            relevance = 0.0
            for token in query_tokens:
                if token in doc_counts:
                    tf = doc_counts[token] / doc_len
                    relevance += tf * self._idf(token)
            recency = (doc["added_at"] - oldest) / span if span > 0 else 0.0
            score = relevance + self._recency_weight * recency
            scored.append((doc, score))
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return [
            {
                "id": doc["id"],
                "text": doc["text"],
                "metadata": doc["metadata"],
                "score": round(score, 4),
            }
            for doc, score in scored[:limit]
            if score > 0
        ]

    def clear(self) -> None:
        self._documents.clear()


class RagMemory:
    """Retrieval-augmented memory backed by the local MemoryStore.

    The index is rebuilt lazily from the memory store so new important
    memories and online results are always searchable.
    """

    def __init__(self, memory: Optional[MemoryStore] = None, index: Optional[RetrievalIndex] = None):
        self.memory = memory or MemoryStore()
        self.index = index or HybridIndex()
        self._dirty = True

    def _rebuild(self) -> None:
        """Rebuild the index from the current memory store contents."""
        self.index.clear()
        now = datetime.now(timezone.utc).timestamp()
        for item in self.memory.get_important():
            self.index.add(
                document_id=f"important:{item.get('topic', '')}",
                text=f"{item.get('topic', '')} {item.get('content', '')}",
                metadata={"kind": "important", "topic": item.get("topic", ""), "added_at": now},
            )
        for idx, item in enumerate(self.memory.data.get("online_results", [])):
            self.index.add(
                document_id=f"online:{idx}",
                text=f"{item.get('prompt', '')} {item.get('result', '')}",
                metadata={"kind": "online", "provider": item.get("provider", ""), "added_at": now},
            )
        for key, value in self.memory.data.get("preferences", {}).items():
            self.index.add(
                document_id=f"pref:{key}",
                text=f"{key} {value}",
                metadata={"kind": "preference", "key": key, "added_at": now},
            )
        self._dirty = False

    def _ensure_fresh(self) -> None:
        if self._dirty:
            self._rebuild()

    def mark_dirty(self) -> None:
        """Notify the index that memory contents changed."""
        self._dirty = True

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve the most relevant memory entries for a query."""
        self._ensure_fresh()
        return self.index.search(query, limit=limit)

    def build_context_prompt(self, query: str, limit: int = 5) -> str:
        """Build a RAG context block for a query, or an empty string."""
        results = self.search(query, limit=limit)
        if not results:
            return ""
        lines = ["Retrieved memory context (RAG):"]
        for result in results:
            meta = result["metadata"]
            kind = meta.get("kind", "memory")
            label = meta.get("topic") or meta.get("key") or meta.get("provider") or kind
            lines.append(f"- [{kind}: {label}] {result['text']}")
        return "\n".join(lines)


__all__ = ["RagMemory", "RetrievalIndex", "TokenOverlapIndex", "HybridIndex"]
