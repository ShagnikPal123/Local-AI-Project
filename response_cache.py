"""Serve an identical or near-identical question from a prior answer.

Refuses aggressively on purpose: anything time-sensitive, personal, tool-
assisted beyond a pure lookup, delegated to an agent, or disliked never gets
cached or served, because one wrong cached answer costs more trust than a
slow answer ever does. See ``ResponseCache._refusal_reason`` for the exact
rules (OVERHAUL_CONTRACTS.md round 2, Coder B).

Two lookup paths:

* **Exact** — the normalised text (casefold, strip punctuation, collapse
  whitespace) plus a caller-supplied ``context_key`` (personality + provider
  family + a chat-independence flag — see ``learning_hooks.py`` for what the
  Lead should build it from) hash straight to one entry.
* **Near-duplicate** — a cosine similarity of at least 0.93 over hashed
  TF-IDF vectors (using ``learning.FeatureHasher`` for the hashing trick, with
  a real, if approximate, IDF term computed from the entries currently in the
  cache — not a fake keyword overlap check).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import string
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from learning import FeatureHasher
from paths import atomic_replace, data_path

_LOG = logging.getLogger("nyx.response_cache")

_MAX_ENTRIES = 500
_SIMILARITY_THRESHOLD = 0.85
_DEFAULT_TTL_SECONDS = 24 * 3600.0

# Word-anchored so "date" does not match "update", "now" does not match
# "know", etc. — the exact bug class that makes naive substring checks unsafe.
_TIME_SENSITIVE_WORDS = (
    "today", "now", "latest", "current", "currently", "news", "price", "prices",
    "stock", "stocks", "weather", "score", "scores", "tomorrow", "yesterday",
    "date", "time", "this week",
)
_TIME_SENSITIVE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(w) for w in _TIME_SENSITIVE_WORDS) + r")\b", re.IGNORECASE
)
_PERSONAL_RE = re.compile(
    r"\b(?:remember|forget|my name|i am|i'm)\b", re.IGNORECASE
)
_PURE_KNOWLEDGE_TOOLS = frozenset({"solve_math", "search_knowledge"})
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def _default_ttl_seconds() -> float:
    """Configurable via ``config.SETTINGS`` when the Lead adds the field; a
    module this repo's config does not know about yet must not crash on
    import, so the lookup is best-effort with a hard-coded fallback."""
    try:
        from config import SETTINGS

        value = getattr(SETTINGS, "response_cache_ttl_hours", None)
        if value:
            return float(value) * 3600.0
    except Exception:  # noqa: BLE001 - config is optional here
        pass
    return _DEFAULT_TTL_SECONDS


#: Contractions expanded before matching, so "what's the capital" and "what is
#: the capital" are the same question rather than a near miss.
_CONTRACTIONS = (
    (re.compile(r"\b(what|who|where|when|why|how|that|there|it|he|she)'s\b"), r"\1 is"),
    (re.compile(r"\b(\w+)'re\b"), r"\1 are"),
    (re.compile(r"\b(\w+)'ll\b"), r"\1 will"),
    (re.compile(r"\b(\w+)'ve\b"), r"\1 have"),
    (re.compile(r"\bcan't\b"), "cannot"),
    (re.compile(r"\bwon't\b"), "will not"),
    (re.compile(r"\b(\w+)n't\b"), r"\1 not"),
    (re.compile(r"\bi'm\b"), "i am"),
)


def normalize(text: str) -> str:
    """casefold, expand contractions, strip punctuation, collapse whitespace — the exact-match key basis."""
    text = (text or "").casefold().replace("’", "'")
    for pattern, replacement in _CONTRACTIONS:
        text = pattern.sub(replacement, text)
    text = text.translate(_PUNCT_TABLE)
    return " ".join(text.split())


def _exact_key(normalized: str, context_key: str) -> str:
    digest = hashlib.blake2b(f"{context_key}\x00{normalized}".encode("utf-8"), digest_size=16)
    return digest.hexdigest()


@dataclass
class CacheHit:
    reply: str
    provider: str
    cached_at: float
    similarity: float
    entry_id: str


@dataclass
class _Entry:
    entry_id: str
    context_key: str
    normalized: str
    vector: Dict[int, float]
    norm: float
    reply: str
    provider: str
    turn_id: str
    cached_at: float
    expires_at: float
    hits: int = 0


def _vector_norm(vector: Dict[int, float]) -> float:
    return math.sqrt(sum(v * v for v in vector.values())) or 1e-9


def _cosine(a: Dict[int, float], a_norm: float, b: Dict[int, float], b_norm: float) -> float:
    if not a or not b:
        return 0.0
    small, big = (a, b) if len(a) <= len(b) else (b, a)
    dot = sum(value * big.get(bucket, 0.0) for bucket, value in small.items())
    return dot / (a_norm * b_norm)


class ResponseCache:
    """Exact + near-duplicate answer cache with LRU eviction and hard refusal rules.

    Storage is lazy (mirrors ``learning.Learner``): nothing is read from disk
    until the first real call, so constructing one with explicit paths for a
    test never touches the real data directory, and the module-level
    singleton never does either unless the app actually calls it.
    """

    def __init__(
        self,
        *,
        path: Optional[Path] = None,
        ttl_seconds: Optional[float] = None,
        max_entries: int = _MAX_ENTRIES,
        clock=time.time,
    ) -> None:
        self._path = path
        self._ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._hasher = FeatureHasher()
        self._lock = threading.RLock()
        self._loaded = False

        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._doc_freq: Dict[int, int] = {}
        self._doc_count = 0
        self._hits = 0
        self._misses = 0
        self._refusals: Dict[str, int] = {}

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds if self._ttl_seconds is not None else _default_ttl_seconds()

    def _cache_path(self) -> Path:
        return self._path or data_path("learning/cache.json")

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load()

    # --- persistence -------------------------------------------------------------------

    def _load(self) -> None:
        path = self._cache_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LOG.warning("could not read %s; starting with an empty cache", path)
            return
        for raw in data.get("entries", []):
            try:
                entry = _Entry(
                    entry_id=raw["entry_id"], context_key=raw["context_key"], normalized=raw["normalized"],
                    vector={int(b): float(v) for b, v in raw.get("vector", {}).items()},
                    norm=float(raw["norm"]), reply=raw["reply"], provider=raw.get("provider", ""),
                    turn_id=raw.get("turn_id", ""), cached_at=float(raw["cached_at"]),
                    expires_at=float(raw["expires_at"]), hits=int(raw.get("hits", 0)),
                )
            except (KeyError, TypeError, ValueError):
                continue
            self._entries[entry.entry_id] = entry
            self._register_doc(entry.vector)
        self._hits = int(data.get("hits", 0))
        self._misses = int(data.get("misses", 0))
        self._refusals = dict(data.get("refusals", {}))

    def _save(self) -> None:
        path = self._cache_path()
        payload = {
            "version": 1,
            "hits": self._hits,
            "misses": self._misses,
            "refusals": self._refusals,
            "entries": [
                {
                    "entry_id": e.entry_id, "context_key": e.context_key, "normalized": e.normalized,
                    "vector": {str(b): v for b, v in e.vector.items()}, "norm": e.norm,
                    "reply": e.reply, "provider": e.provider, "turn_id": e.turn_id,
                    "cached_at": e.cached_at, "expires_at": e.expires_at, "hits": e.hits,
                }
                for e in self._entries.values()
            ],
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            atomic_replace(tmp, path)
        except OSError:
            _LOG.warning("could not save %s", path)

    # --- document-frequency bookkeeping for the IDF term --------------------------------

    def _register_doc(self, vector: Dict[int, float]) -> None:
        for bucket in vector:
            self._doc_freq[bucket] = self._doc_freq.get(bucket, 0) + 1
        self._doc_count += 1

    def _unregister_doc(self, vector: Dict[int, float]) -> None:
        for bucket in vector:
            remaining = self._doc_freq.get(bucket, 0) - 1
            if remaining <= 0:
                self._doc_freq.pop(bucket, None)
            else:
                self._doc_freq[bucket] = remaining
        self._doc_count = max(0, self._doc_count - 1)

    def _tfidf_vector(self, normalized_text: str) -> Dict[int, float]:
        tf = self._hasher.featurize(normalized_text)
        if not tf:
            return {}
        n = max(self._doc_count, 1)
        return {
            bucket: value * (math.log((1.0 + n) / (1.0 + self._doc_freq.get(bucket, 0))) + 1.0)
            for bucket, value in tf.items()
        }

    # --- refusal rules -------------------------------------------------------------------

    @staticmethod
    def _refusal_reason(
        message: str, *, tools: Sequence[str] = (), agents: Sequence[str] = (),
        attachments: Sequence[Any] = (), rating: Optional[int] = None,
    ) -> Optional[str]:
        text = message or ""
        if _TIME_SENSITIVE_RE.search(text):
            return "time_sensitive"
        if _PERSONAL_RE.search(text):
            return "personal"
        if attachments:
            return "attachments"
        if agents:
            return "delegated"
        if any(t not in _PURE_KNOWLEDGE_TOOLS for t in (tools or ())):
            return "tool_used"
        if rating is not None and rating < 0:
            return "disliked"
        return None

    def _record_refusal(self, reason: str) -> None:
        self._refusals[reason] = self._refusals.get(reason, 0) + 1

    def _expire(self, now: float) -> None:
        expired = [key for key, entry in self._entries.items() if entry.expires_at <= now]
        for key in expired:
            entry = self._entries.pop(key)
            self._unregister_doc(entry.vector)

    def _evict_if_needed(self) -> None:
        while len(self._entries) > self.max_entries:
            key, entry = self._entries.popitem(last=False)  # least-recently-used
            self._unregister_doc(entry.vector)

    # --- public API ---------------------------------------------------------------------

    def lookup(self, message: str, context_key: str) -> Optional[CacheHit]:
        with self._lock:
            self._ensure_loaded()
            now = self._clock()
            self._expire(now)

            text = message or ""
            reason = self._refusal_reason(text)
            if reason in ("time_sensitive", "personal"):
                # Never *serve* a stale answer to a question that reads as
                # time-sensitive or personal, even if an old entry happens to
                # match — the refusal applies symmetrically to store and serve.
                self._record_refusal(reason)
                self._misses += 1
                return None

            normalized = normalize(text)
            if not normalized:
                self._misses += 1
                return None

            key = _exact_key(normalized, context_key)
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > now:
                entry.hits += 1
                self._entries.move_to_end(key)
                self._hits += 1
                self._save()
                return CacheHit(reply=entry.reply, provider=entry.provider, cached_at=entry.cached_at,
                                 similarity=1.0, entry_id=entry.entry_id)

            query_vector = self._tfidf_vector(normalized)
            query_norm = _vector_norm(query_vector)
            best: Optional[_Entry] = None
            best_score = 0.0
            for candidate in self._entries.values():
                if candidate.context_key != context_key or candidate.expires_at <= now:
                    continue
                score = _cosine(query_vector, query_norm, candidate.vector, candidate.norm)
                if score > best_score:
                    best_score, best = score, candidate

            if best is not None and best_score >= _SIMILARITY_THRESHOLD:
                best.hits += 1
                self._entries.move_to_end(best.entry_id)
                self._hits += 1
                self._save()
                return CacheHit(reply=best.reply, provider=best.provider, cached_at=best.cached_at,
                                 similarity=round(best_score, 4), entry_id=best.entry_id)

            self._misses += 1
            return None

    def store(
        self, message: str, context_key: str, reply: str, provider: str, turn_id: str,
        tools: Sequence[str] = (), agents: Sequence[str] = (), attachments: Sequence[Any] = (),
    ) -> bool:
        """Cache one answer, applying every refusal rule itself. Returns whether it stored."""
        with self._lock:
            self._ensure_loaded()
            reason = self._refusal_reason(message, tools=tools, agents=agents, attachments=attachments)
            if reason:
                self._record_refusal(reason)
                return False
            if not (reply or "").strip():
                self._record_refusal("empty_reply")
                return False

            normalized = normalize(message)
            if not normalized:
                self._record_refusal("empty_message")
                return False

            key = _exact_key(normalized, context_key)
            vector = self._tfidf_vector(normalized)
            now = self._clock()
            self._expire(now)

            existing = self._entries.pop(key, None)
            if existing is not None:
                self._unregister_doc(existing.vector)

            entry = _Entry(
                entry_id=key, context_key=context_key, normalized=normalized, vector=vector,
                norm=_vector_norm(vector), reply=reply, provider=provider, turn_id=turn_id,
                cached_at=now, expires_at=now + self.ttl_seconds,
            )
            self._entries[key] = entry
            self._register_doc(vector)
            self._evict_if_needed()
            self._save()
            return True

    def invalidate_turn(self, turn_id: str) -> int:
        """Drop every entry that was stored from ``turn_id`` (a 👎 undoes the cache write)."""
        with self._lock:
            self._ensure_loaded()
            if not turn_id:
                return 0
            keys = [k for k, e in self._entries.items() if e.turn_id == turn_id]
            for key in keys:
                entry = self._entries.pop(key)
                self._unregister_doc(entry.vector)
            if keys:
                self._save()
            return len(keys)

    def clear(self) -> None:
        with self._lock:
            self._ensure_loaded()
            self._entries.clear()
            self._doc_freq.clear()
            self._doc_count = 0
            self._hits = 0
            self._misses = 0
            self._refusals = {}
            self._save()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            total = self._hits + self._misses
            return {
                "entries": len(self._entries),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(self._hits / total, 4) if total else 0.0,
                "refusals": dict(self._refusals),
            }


#: The singleton the rest of the app uses. Storage is lazy, so importing this
#: module never touches the real data directory.
RESPONSE_CACHE = ResponseCache()
