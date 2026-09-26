"""The corpus on disk: gzip JSONL shards, one license per document, near-duplicates dropped, a hard size cap.

Near-duplicates matter more than they look: Wikipedia intros, mirrored books and repeated chat questions
would otherwise be seen many times per epoch and memorised. A 64-bit SimHash over word 3-grams catches
them; documents within 5 of 64 bits of one already kept are skipped (unrelated texts differ by ~32). The cap is on compressed bytes on disk,
because that is what the owner's storage actually pays.

It has to stay fast at corpus scale (tens of thousands of documents), so:

* the SimHash comparison is banded — 8 bands of 8 bits, so two hashes within 5 bits always share a
  whole band — and only the few candidates in a shared band are compared bit by bit;
* the per-document index is an append-only sidecar (``index.jsonl``), not a file rewritten per add;
* the size on disk is measured at most once a second, not once per document;
* ``has()`` answers "already collected" from the index, so a fetcher can skip what it already has
  instead of downloading it again to find out.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from identity0.policy import source_license

_WORDS = re.compile(r"[a-z0-9']+")
_SHARD_BYTES = 16 * 1024 * 1024
_NEAR = 5
_BANDS = 8  # 8 bits each: with at most 5 differing bits, at least three bands still match exactly


def simhash(text: str) -> int:
    words = _WORDS.findall((text or "").lower())
    if len(words) < 3:
        words = words + ["_"] * (3 - len(words))
    weights = [0] * 64
    for i in range(len(words) - 2):
        h = int.from_bytes(hashlib.blake2b(" ".join(words[i:i + 3]).encode(), digest_size=8).digest(), "big")
        for bit in range(64):
            weights[bit] += 1 if (h >> bit) & 1 else -1
    return sum(1 << bit for bit in range(64) if weights[bit] > 0)


def _bands(value: int) -> List[str]:
    return [f"{band}:{(value >> (band * 8)) & 0xFF}" for band in range(_BANDS)]


class CorpusStore:
    def __init__(self, root: Path, cap_mb: float = 2048) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.cap = int(cap_mb * 1024 * 1024)
        self._lock = threading.Lock()
        self._size = 0.0
        self._sized_at = 0.0
        self._dirty = False
        self._saved_at = 0.0
        self._index = self._load_index()

    # --- index ------------------------------------------------------------------------------

    def _sidecar(self) -> Path:
        return self.root / "index.jsonl"

    def _load_index(self) -> Dict[str, Any]:
        try:
            data = json.loads((self.root / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data.setdefault("counts", {})
        data.setdefault("chars", {})
        hashes: List[int] = []
        ids: List[str] = []
        keys: List[str] = []
        try:
            with open(self._sidecar(), "r", encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    ids.append(str(row.get("id", "")))
                    hashes.append(int(row.get("hash", 0)))
                    keys.append(str(row.get("key", "")))
        except OSError:
            pass
        if not ids and data.get("ids"):
            # An older index kept everything in index.json: carry it over once.
            ids = [str(i) for i in data.get("ids", [])]
            hashes = [int(h) for h in data.get("hashes", [])]
            keys = ["" for _ in ids]
            with open(self._sidecar(), "a", encoding="utf-8") as handle:
                for doc_id, value in zip(ids, hashes):
                    handle.write(json.dumps({"id": doc_id, "hash": value, "key": ""}) + "\n")
        data["ids"], data["hashes"], data["keys"] = ids, hashes, keys
        self._ids = set(ids)
        self._keys = set(k for k in keys if k)
        self._buckets: Dict[str, List[int]] = {}
        for value in hashes:
            for band in _bands(value):
                self._buckets.setdefault(band, []).append(value)
        return data

    def _save_index(self, *, force: bool = False) -> None:
        """The summary (counts, characters); the per-document rows are appended as they arrive."""
        now = time.time()
        if not force and now - self._saved_at < 5:
            self._dirty = True
            return
        self._saved_at, self._dirty = now, False
        summary = {"counts": self._index["counts"], "chars": self._index["chars"],
                   "documents": len(self._index["ids"])}
        tmp = self.root / "index.json.tmp"
        tmp.write_text(json.dumps(summary), encoding="utf-8")
        tmp.replace(self.root / "index.json")

    def flush(self) -> None:
        with self._lock:
            self._save_index(force=True)

    def _near(self, value: int) -> bool:
        for band in _bands(value):
            for other in self._buckets.get(band, ()):  # only documents that share a whole band
                if bin(value ^ other).count("1") <= _NEAR:
                    return True
        return False

    def has(self, source: str, title_or_url: str) -> bool:
        """Whether a document from ``source`` with this title or url was already collected."""
        return f"{source}|{title_or_url}" in self._keys

    # --- writing ----------------------------------------------------------------------------

    def size(self, *, fresh: bool = False) -> int:
        now = time.time()
        if fresh or now - self._sized_at > 1.0:
            self._size = sum(p.stat().st_size for p in self.root.glob("shard_*.jsonl.gz"))
            self._sized_at = now
        return int(self._size)

    def _shard(self) -> Path:
        shards = sorted(self.root.glob("shard_*.jsonl.gz"))
        if shards and shards[-1].stat().st_size < _SHARD_BYTES:
            return shards[-1]
        return self.root / f"shard_{len(shards):04d}.jsonl.gz"

    def add(self, text: str, *, source: str, title: str = "", url: str = "", extra: Optional[Dict[str, Any]] = None) -> str:
        """Store one document; returns "added", "duplicate", "full", "empty" or "not allowed"."""
        text = (text or "").strip()
        if len(text) < 200:
            return "empty"
        license_info = source_license(source)
        if not license_info.get("train"):
            return "not allowed"
        key = f"{source}|{url or title}"
        doc_id = hashlib.sha1(f"{source}|{url or title}|{text[:200]}".encode("utf-8")).hexdigest()[:16]
        value = simhash(text[:20000])
        with self._lock:
            if doc_id in self._ids or key in self._keys or self._near(value):
                return "duplicate"
            if self.size() >= self.cap:
                return "full"
            record = {"id": doc_id, "source": source, "title": title[:300], "url": url[:500],
                      "license": license_info["license"], "fetched": time.time(), "text": text, **(extra or {})}
            line = json.dumps(record, ensure_ascii=False) + "\n"
            with gzip.open(self._shard(), "at", encoding="utf-8") as handle:
                handle.write(line)
            self._size += len(line) // 3  # roughly what gzip keeps; corrected by the next real measurement
            self._index["hashes"].append(value)
            self._index["ids"].append(doc_id)
            self._index["keys"].append(key)
            self._ids.add(doc_id)
            self._keys.add(key)
            for band in _bands(value):
                self._buckets.setdefault(band, []).append(value)
            with open(self._sidecar(), "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"id": doc_id, "hash": value, "key": key}) + "\n")
            self._index["counts"][source] = self._index["counts"].get(source, 0) + 1
            self._index["chars"][source] = self._index["chars"].get(source, 0) + len(text)
            self._save_index()
        return "added"

    # --- reading ----------------------------------------------------------------------------

    def documents(self) -> Iterator[Dict[str, Any]]:
        for shard in sorted(self.root.glob("shard_*.jsonl.gz")):
            try:
                with gzip.open(shard, "rt", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            yield json.loads(line)
                        except ValueError:
                            continue
            except (OSError, EOFError):
                continue  # a shard a collecting job is appending to right now: whatever it has is enough

    def texts(self) -> Iterator[str]:
        for doc in self.documents():
            yield doc["text"]

    def titles(self, source: Optional[str] = None) -> List[str]:
        return [d["title"] for d in self.documents() if d.get("title") and (source is None or d["source"] == source)]

    def stats(self) -> Dict[str, Any]:
        return {"documents": len(self._index["ids"]), "by_source": dict(self._index["counts"]),
                "characters": dict(self._index["chars"]), "bytes_on_disk": self.size(fresh=True), "cap_bytes": self.cap}

    def card(self) -> str:
        """A dataset card: what is in here, under which license, and whom to credit."""
        lines = ["# Identity 0 corpus", "", "| Source | Documents | Characters | License |", "|---|---|---|---|"]
        for source, count in sorted(self._index["counts"].items()):
            info = source_license(source)
            lines.append(f"| {source} | {count} | {self._index['chars'].get(source, 0):,} | {info['license']} |")
        lines += ["", "## Attribution", ""]
        for source in sorted(self._index["counts"]):
            lines.append(f"- {source_license(source)['attribution']}")
        return "\n".join(lines) + "\n"
