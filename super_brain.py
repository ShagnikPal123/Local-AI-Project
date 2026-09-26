"""The super brain: a living graph of everything Nyx reads, says and learns.

Every prompt, answer, web search, file, email, lesson and document Nyx looks at
becomes **memory nodes** (sentence-sized chunks, kept as text) linked to
**concept nodes** (the terms and names in them) and to a **source cluster**
(Conversations, Web, Code, Knowledge…). Concepts that appear together are linked,
so the graph grows denser the more Nyx sees — to hundreds of thousands of nodes.

It is built for three readers:

* **the web UI** — every node has a stored 3D position around its cluster's
  centre, so the Brain view streams 100k+ points as one binary buffer
  (``points_buffer``) and new nodes as ``brain.impulse`` events;
* **Nyx itself** — ``recall`` ranks stored memories for a question (SQLite FTS5
  plus concept overlap), so what it read yesterday informs today's answer;
* **Nyx Core** (``nyx_core.py``) — the counts feed its growth level.

Writes go through one background thread (``ingest`` returns immediately), so a
chat turn never waits on the database.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import queue
import random
import re
import sqlite3
import struct
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from paths import PROJECT_DIR, data_path

_LOG = logging.getLogger("nyx.brain")

#: Source clusters: id, key, label, colour. Order is stable (ids are stored).
CLUSTERS: List[Dict[str, Any]] = [
    {"id": 0, "key": "chat", "label": "Conversations", "color": "#22d3ee"},
    {"id": 1, "key": "web", "label": "Web & search", "color": "#3b82f6"},
    {"id": 2, "key": "files", "label": "Files & notes", "color": "#facc15"},
    {"id": 3, "key": "code", "label": "Code", "color": "#a78bfa"},
    {"id": 4, "key": "knowledge", "label": "Knowledge", "color": "#f472b6"},
    {"id": 5, "key": "agents", "label": "Agents & skills", "color": "#34d399"},
    {"id": 6, "key": "self-study", "label": "Self-study", "color": "#fb923c"},
    {"id": 7, "key": "email", "label": "Email", "color": "#e879f9"},
    {"id": 8, "key": "design", "label": "Design & builds", "color": "#2dd4bf"},
    {"id": 9, "key": "system", "label": "Machine", "color": "#a3e635"},
    {"id": 10, "key": "models", "label": "Model answers", "color": "#60a5fa"},
    {"id": 11, "key": "voice", "label": "Voice", "color": "#f87171"},
]
_CLUSTER_BY_KEY = {c["key"]: c["id"] for c in CLUSTERS}
_SOURCE_ALIASES = {"conversation": "chat", "user": "chat", "search": "web", "browser": "web", "file": "files",
                   "notes": "files", "obsidian": "files", "docs": "knowledge", "hig": "knowledge", "skill": "agents",
                   "agent": "agents", "lesson": "self-study", "improve": "self-study", "mail": "email",
                   "3d": "design", "machine": "system", "assistant": "models", "answer": "models"}

KIND_MEMORY, KIND_CONCEPT, KIND_HUB = 0, 1, 2
_SPREAD = 150.0
_STOP = set("""a about above after again against all also am an and any are as at be because been before being below
between both but by can could did do does doing down during each few for from further had has have having he her here
hers herself him himself his how i if in into is it its itself just let me more most my myself no nor not now of off on
once only or other our ours ourselves out over own same she should so some such than that the their theirs them
themselves then there these they this those through to too under until up very was we were what when where which while
who whom why will with would you your yours yourself yourselves use used using make makes made get gets got one two
new like want need also may might must shall via per etc yes okay ok thing things way really just still even much many
self none true false return def class import from none str int list dict any the""".split())
_TERM = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-_']{2,40}")


def cluster_for(source: str) -> int:
    key = (source or "").strip().lower()
    key = _SOURCE_ALIASES.get(key, key)
    return _CLUSTER_BY_KEY.get(key, 4)


def _centre(cluster: int) -> Tuple[float, float, float]:
    """Cluster centres on a Fibonacci sphere, flattened a little so the field reads wide."""
    n = len(CLUSTERS)
    i = cluster % n + 0.5
    phi = math.acos(1 - 2 * i / n)
    theta = math.pi * (1 + 5 ** 0.5) * i
    return (_SPREAD * math.cos(theta) * math.sin(phi), _SPREAD * 0.62 * math.cos(phi),
            _SPREAD * math.sin(theta) * math.sin(phi))


def position(key: str, cluster: int, kind: int) -> Tuple[float, float, float]:
    """Deterministic spot near the cluster centre: memories fill the cloud, concepts sit a little outside."""
    rng = random.Random(int(hashlib.blake2b(key.encode("utf-8"), digest_size=8).hexdigest(), 16))
    cx, cy, cz = _centre(cluster)
    sigma = 26.0 if kind == KIND_MEMORY else 38.0
    if kind == KIND_HUB:
        return cx, cy, cz
    return cx + rng.gauss(0, sigma), cy + rng.gauss(0, sigma * 0.8), cz + rng.gauss(0, sigma)


def concepts(text: str, limit: int = 8) -> List[str]:
    words = [w.strip(".'-_").lower() for w in _TERM.findall(text or "")]
    words = [w for w in words if len(w) >= 3 and w not in _STOP and not w.isdigit()]
    counts = Counter(words)
    pairs = Counter(f"{a} {b}" for a, b in zip(words, words[1:]) if a != b)
    ranked = [p for p, n in pairs.most_common(4) if n >= 2] + [w for w, _ in counts.most_common(limit * 2)]
    out: List[str] = []
    for term in ranked:
        if term not in out:
            out.append(term)
        if len(out) >= limit:
            break
    return out


def chunks(text: str, min_chars: int = 40, max_chars: int = 420) -> List[str]:
    """Sentence-sized pieces; short sentences are merged so every memory says something."""
    pieces = re.split(r"(?<=[.!?])\s+|\n\s*\n|\n(?=[-*#•] )", (text or "").strip())
    out: List[str] = []
    buffer = ""
    for piece in (p.strip() for p in pieces):
        if not piece:
            continue
        while len(piece) > max_chars:
            cut = piece.rfind(" ", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            out.append(piece[:cut].strip())
            piece = piece[cut:].strip()
        candidate = f"{buffer} {piece}".strip() if buffer else piece
        if len(candidate) < min_chars:
            buffer = candidate
            continue
        if len(candidate) > max_chars:
            if buffer:
                out.append(buffer)
            buffer = piece if len(piece) < min_chars else ""
            if len(piece) >= min_chars:
                out.append(piece)
        else:
            out.append(candidate)
            buffer = ""
    if buffer and len(buffer) >= 12:
        out.append(buffer)
    return [piece for piece in out if _meaningful(piece)]


_LINK = re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+")


def _meaningful(piece: str) -> bool:
    """Skip link lists, table rules and symbol soup: they make noisy memories and bad recall."""
    prose = _LINK.sub(" ", piece)
    letters = sum(ch.isalpha() for ch in prose)
    return letters >= 20 and letters / max(1, len(piece)) >= 0.45


class SuperBrain:
    def __init__(self, path: Optional[Path] = None, *, background: bool = True) -> None:
        self._path = path
        self._background = background
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._queue: "queue.Queue[Tuple[str, str, str, Dict[str, Any]]]" = queue.Queue(maxsize=20000)
        self._writer: Optional[threading.Thread] = None
        self._index_cache: Optional[Tuple[int, Dict[int, int], bytes]] = None
        self._impulses: List[Dict[str, Any]] = []
        self._pending_event: List[Dict[str, Any]] = []
        self._last_event = 0.0
        self.seeding: Dict[str, Any] = {"running": False, "done": [], "current": "", "added": 0, "error": ""}

    # --- storage -----------------------------------------------------------------

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            path = self._path or data_path("brain/brain.db")
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, label TEXT,
                    kind INTEGER, cluster INTEGER, weight REAL DEFAULT 1, hits INTEGER DEFAULT 1,
                    created REAL, updated REAL, x REAL, y REAL, z REAL);
                CREATE TABLE IF NOT EXISTS edges (a INTEGER, b INTEGER, w REAL DEFAULT 1, PRIMARY KEY (a, b)) WITHOUT ROWID;
                CREATE TABLE IF NOT EXISTS memories (node_id INTEGER PRIMARY KEY, text TEXT, source TEXT, kind TEXT,
                    ref TEXT, created REAL);
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(text, content='memories', content_rowid='node_id');
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
                CREATE INDEX IF NOT EXISTS nodes_created ON nodes(created);
                CREATE INDEX IF NOT EXISTS nodes_kind ON nodes(kind);
            """)
            self._conn = conn
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # --- writing -----------------------------------------------------------------

    def ingest(self, text: str, source: str = "chat", kind: str = "note", ref: str = "", **meta: Any) -> None:
        """Queue text to be remembered. Returns at once; never raises."""
        if not text or not str(text).strip():
            return
        item = (str(text)[:20000], source, kind, {"ref": ref, **meta})
        if not self._background:
            self._write_many([item])
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            return
        if self._writer is None or not self._writer.is_alive():
            self._writer = threading.Thread(target=self._drain, name="nyx-brain-writer", daemon=True)
            self._writer.start()

    def flush(self, timeout: float = 10.0) -> None:
        end = time.time() + timeout
        while not self._queue.empty() and time.time() < end:
            time.sleep(0.02)
        with self._lock:
            pass

    def _drain(self) -> None:
        while True:
            try:
                first = self._queue.get(timeout=5)
            except queue.Empty:
                return
            batch = [first]
            while len(batch) < 200:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            try:
                self._write_many(batch)
            except Exception:  # noqa: BLE001 - a bad batch must not kill the writer
                _LOG.exception("brain write failed")

    def _write_many(self, items: List[Tuple[str, str, str, Dict[str, Any]]]) -> int:
        added_nodes: List[Dict[str, Any]] = []
        now = time.time()
        with self._lock:
            db = self._db()
            with db:
                for text, source, kind, meta in items:
                    cluster = cluster_for(source)
                    hub = self._upsert(db, f"s:{CLUSTERS[cluster]['key']}", CLUSTERS[cluster]["label"], KIND_HUB, cluster, now, added_nodes)
                    for piece in chunks(text) or [text[:420]]:
                        digest = hashlib.sha1(piece.encode("utf-8")).hexdigest()[:16]
                        key = f"m:{digest}"
                        existing = db.execute("SELECT id FROM nodes WHERE key=?", (key,)).fetchone()
                        if existing:
                            db.execute("UPDATE nodes SET hits=hits+1, updated=? WHERE id=?", (now, existing[0]))
                            continue
                        memory = self._upsert(db, key, piece[:80], KIND_MEMORY, cluster, now, added_nodes)
                        db.execute("INSERT OR IGNORE INTO memories(node_id, text, source, kind, ref, created) VALUES (?,?,?,?,?,?)",
                                   (memory, piece, source, kind, str(meta.get("ref", ""))[:300], now))
                        db.execute("INSERT INTO memories_fts(rowid, text) VALUES (?, ?)", (memory, piece))
                        self._link(db, memory, hub, 0.5)
                        terms = concepts(piece)
                        ids = [self._upsert(db, f"c:{t}", t, KIND_CONCEPT, cluster, now, added_nodes) for t in terms]
                        for concept_id in ids:
                            self._link(db, memory, concept_id, 1.0)
                        for i, a in enumerate(ids[:5]):
                            for b in ids[i + 1:5]:
                                self._link(db, a, b, 0.5)
            self._index_cache = None
        if added_nodes:
            self._note_impulses(added_nodes)
        return len(added_nodes)

    def _upsert(self, db: sqlite3.Connection, key: str, label: str, kind: int, cluster: int, now: float,
                added: List[Dict[str, Any]]) -> int:
        row = db.execute("SELECT id FROM nodes WHERE key=?", (key,)).fetchone()
        if row:
            db.execute("UPDATE nodes SET hits=hits+1, weight=weight+0.1, updated=? WHERE id=?", (now, row[0]))
            return int(row[0])
        x, y, z = position(key, cluster, kind)
        cursor = db.execute("INSERT INTO nodes(key, label, kind, cluster, created, updated, x, y, z) VALUES (?,?,?,?,?,?,?,?,?)",
                            (key, label, kind, cluster, now, now, x, y, z))
        node_id = int(cursor.lastrowid)
        if len(added) < 400:
            added.append({"id": node_id, "kind": kind, "cluster": cluster, "x": round(x, 2), "y": round(y, 2), "z": round(z, 2),
                          "label": label[:60]})
        return node_id

    @staticmethod
    def _link(db: sqlite3.Connection, a: int, b: int, w: float) -> None:
        if a == b:
            return
        a, b = (a, b) if a < b else (b, a)
        db.execute("INSERT INTO edges(a, b, w) VALUES (?,?,?) ON CONFLICT(a, b) DO UPDATE SET w = w + excluded.w", (a, b, w))

    def _note_impulses(self, nodes: List[Dict[str, Any]]) -> None:
        now = time.time()
        self._impulses.append({"ts": now, "n": len(nodes)})
        cutoff = now - 60
        self._impulses = [i for i in self._impulses if i["ts"] >= cutoff]
        self._pending_event.extend(nodes[:200])
        if now - self._last_event < 0.8:
            return
        self._last_event = now
        batch, self._pending_event = self._pending_event[:300], []
        try:
            from agent_events import publish_ui

            publish_ui("brain.impulse", nodes=batch, total=self.counts(cached=True).get("nodes", 0))
        except Exception:
            pass

    # --- reading -----------------------------------------------------------------

    def counts(self, cached: bool = False) -> Dict[str, Any]:
        with self._lock:
            db = self._db()
            by_kind = dict(db.execute("SELECT kind, COUNT(*) FROM nodes GROUP BY kind").fetchall())
            edges = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            since = time.time() - 86400
            last_day = db.execute("SELECT COUNT(*) FROM nodes WHERE created >= ?", (since,)).fetchone()[0]
            memories_day = db.execute("SELECT COUNT(*) FROM nodes WHERE created >= ? AND kind = ?", (since, KIND_MEMORY)).fetchone()[0]
        nodes = sum(by_kind.values())
        return {"nodes": nodes, "memories": by_kind.get(KIND_MEMORY, 0), "concepts": by_kind.get(KIND_CONCEPT, 0),
                "hubs": by_kind.get(KIND_HUB, 0), "edges": edges, "added_24h": last_day, "memories_24h": memories_day}

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            db = self._db()
            per_cluster = dict(db.execute("SELECT cluster, COUNT(*) FROM nodes GROUP BY cluster").fetchall())
            top = {}
            for cluster in CLUSTERS:
                rows = db.execute("SELECT label FROM nodes WHERE cluster=? AND kind=? ORDER BY hits DESC LIMIT 4",
                                  (cluster["id"], KIND_CONCEPT)).fetchall()
                top[cluster["id"]] = [r[0] for r in rows]
        clusters = []
        for cluster in CLUSTERS:
            cx, cy, cz = _centre(cluster["id"])
            clusters.append({**cluster, "count": per_cluster.get(cluster["id"], 0), "centre": [round(cx, 1), round(cy, 1), round(cz, 1)],
                             "top": top.get(cluster["id"], [])})
        impulses_per_min = sum(i["n"] for i in self._impulses if i["ts"] >= time.time() - 60)
        return {**self.counts(), "clusters": clusters, "impulses_per_min": impulses_per_min, "seeding": dict(self.seeding),
                "queue": self._queue.qsize()}

    def _index(self) -> Tuple[int, Dict[int, int], bytes]:
        """(count, id→index, packed Float32 [x, y, z, cluster, kind, weight] per node), cached until the next write."""
        with self._lock:
            if self._index_cache is not None:
                return self._index_cache
            rows = self._db().execute("SELECT id, x, y, z, cluster, kind, weight FROM nodes ORDER BY id").fetchall()
            index = {row[0]: i for i, row in enumerate(rows)}
            buffer = bytearray(len(rows) * 24)
            for i, (_id, x, y, z, cluster, kind, weight) in enumerate(rows):
                struct.pack_into("<6f", buffer, i * 24, x, y, z, cluster, kind, min(float(weight), 50.0))
            self._index_cache = (len(rows), index, bytes(buffer))
            return self._index_cache

    def points_buffer(self, limit: int = 400_000) -> Tuple[int, bytes]:
        count, _, buffer = self._index()
        count = min(count, limit)
        return count, buffer[: count * 24]

    def edges_buffer(self, limit: int = 60_000) -> Tuple[int, bytes]:
        """Strongest links as Uint32 index pairs into ``points_buffer``."""
        count, index, _ = self._index()
        with self._lock:
            rows = self._db().execute("SELECT a, b FROM edges ORDER BY w DESC LIMIT ?", (limit,)).fetchall()
        pairs = [(index[a], index[b]) for a, b in rows if a in index and b in index]
        buffer = bytearray(len(pairs) * 8)
        for i, (a, b) in enumerate(pairs):
            struct.pack_into("<2I", buffer, i * 8, a, b)
        return len(pairs), bytes(buffer)

    def recent(self, limit: int = 40) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db().execute(
                "SELECT n.id, m.text, m.source, m.kind, m.created, n.cluster FROM memories m JOIN nodes n ON n.id = m.node_id "
                "ORDER BY m.created DESC, n.id DESC LIMIT ?", (limit,)).fetchall()
        _, index, _ = self._index()
        return [{"id": r[0], "index": index.get(r[0]), "text": r[1], "source": r[2], "kind": r[3], "created": r[4], "cluster": r[5]} for r in rows]

    def recall(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        """Memories that best answer ``query``: full-text rank, boosted by shared concepts and use."""
        terms = concepts(query, limit=10)
        words = [w for w in re.findall(r"[A-Za-z0-9]{3,}", query or "") if w.lower() not in _STOP][:12]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        with self._lock:
            db = self._db()
            try:
                rows = db.execute(
                    "SELECT m.node_id, m.text, m.source, m.kind, m.ref, bm25(memories_fts) AS rank, n.hits, n.cluster "
                    "FROM memories_fts JOIN memories m ON m.node_id = memories_fts.rowid JOIN nodes n ON n.id = m.node_id "
                    "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?", (match, limit * 5)).fetchall()
            except sqlite3.OperationalError:
                rows = []
        scored = []
        for node_id, text, source, kind, ref, rank, hits, cluster in rows:
            lower = text.lower()
            overlap = sum(1 for t in terms if t in lower)
            substance = min(len(_LINK.sub("", text)), 320) / 160  # a full sentence beats a fragment
            score = -float(rank) + overlap * 1.5 + math.log1p(hits) * 0.3 + substance
            scored.append({"id": node_id, "text": text, "source": source, "kind": kind, "ref": ref, "cluster": cluster,
                           "score": round(score, 3)})
        scored.sort(key=lambda item: -item["score"])
        return scored[:limit]

    def search(self, query: str, limit: int = 40) -> Dict[str, Any]:
        memories = self.recall(query, limit)
        _, index, _ = self._index()
        with self._lock:
            concept_rows = self._db().execute("SELECT id, label, cluster, hits FROM nodes WHERE kind=? AND label LIKE ? ORDER BY hits DESC LIMIT ?",
                                              (KIND_CONCEPT, f"%{(query or '').strip().lower()[:40]}%", limit)).fetchall()
        return {"memories": [{**m, "index": index.get(m["id"])} for m in memories],
                "concepts": [{"id": r[0], "label": r[1], "cluster": r[2], "hits": r[3], "index": index.get(r[0])} for r in concept_rows]}

    def node(self, node_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            db = self._db()
            row = db.execute("SELECT id, key, label, kind, cluster, hits, created FROM nodes WHERE id=?", (node_id,)).fetchone()
            if not row:
                return None
            memory = db.execute("SELECT text, source, kind, ref FROM memories WHERE node_id=?", (node_id,)).fetchone()
            neighbours = db.execute(
                "SELECT n.id, n.label, n.kind, n.cluster, e.w FROM edges e JOIN nodes n ON n.id = CASE WHEN e.a=? THEN e.b ELSE e.a END "
                "WHERE e.a=? OR e.b=? ORDER BY e.w DESC LIMIT 24", (node_id, node_id, node_id)).fetchall()
        _, index, _ = self._index()
        return {"id": row[0], "label": row[2], "kind": ["memory", "concept", "source"][row[3]], "cluster": row[4], "hits": row[5],
                "created": row[6], "index": index.get(row[0]),
                "memory": {"text": memory[0], "source": memory[1], "kind": memory[2], "ref": memory[3]} if memory else None,
                "neighbours": [{"id": n[0], "label": n[1], "kind": ["memory", "concept", "source"][n[2]], "cluster": n[3],
                                "weight": round(n[4], 2), "index": index.get(n[0])} for n in neighbours]}

    def node_at(self, index: int) -> Optional[Dict[str, Any]]:
        """The node drawn at position ``index`` of ``points_buffer`` (what a click in the Brain view hit)."""
        _, mapping, _ = self._index()
        for node_id, i in mapping.items():
            if i == index:
                return self.node(node_id)
        return None

    def known_concepts(self, terms: Iterable[str]) -> set:
        """Which of these words Nyx already has as concepts — how Data Absorption scores what is new (Request R1)."""
        keys = sorted({f"c:{str(t).strip().lower()}" for t in terms if str(t or "").strip()})[:900]
        if not keys:
            return set()
        found: set = set()
        with self._lock:
            db = self._db()
            for start in range(0, len(keys), 300):
                batch = keys[start:start + 300]
                rows = db.execute(f"SELECT key FROM nodes WHERE key IN ({','.join('?' * len(batch))})", batch).fetchall()
                found.update(row[0][2:] for row in rows)
        return found

    def related_concepts(self, words: Iterable[str], limit: int = 12) -> List[str]:
        """Concepts most often linked to these words — how a "study this" plan finds terms nobody typed."""
        keys = [f"c:{str(w).strip().lower()}" for w in words if str(w or "").strip()][:8]
        if not keys:
            return []
        with self._lock:
            db = self._db()
            ids = [row[0] for row in db.execute(f"SELECT id FROM nodes WHERE key IN ({','.join('?' * len(keys))})", keys).fetchall()]
            if not ids:
                return []
            marks = ",".join("?" * len(ids))
            rows = db.execute(
                f"SELECT n.label, SUM(e.w) AS strength FROM edges e JOIN nodes n ON n.id = CASE WHEN e.a IN ({marks}) THEN e.b ELSE e.a END "
                f"WHERE (e.a IN ({marks}) OR e.b IN ({marks})) AND n.kind = ? GROUP BY n.id ORDER BY strength DESC LIMIT ?",
                [*ids, *ids, *ids, KIND_CONCEPT, limit + len(ids)]).fetchall()
        wanted = {k[2:] for k in keys}
        return [label for label, _strength in rows if label not in wanted][:limit]

    def forget_ref(self, prefix: str) -> int:
        """Remove the memories one source wrote (e.g. a Data Absorption run: ``absorb:<run>:``). Shared concepts stay."""
        clean = str(prefix or "").replace("%", "").replace("_", r"\_")
        if len(clean) < 4:
            return 0
        with self._lock:
            db = self._db()
            rows = db.execute("SELECT node_id, text FROM memories WHERE ref LIKE ? ESCAPE '\\'", (clean + "%",)).fetchall()
            with db:
                for node_id, text in rows:
                    db.execute("INSERT INTO memories_fts(memories_fts, rowid, text) VALUES('delete', ?, ?)", (node_id, text))
                    db.execute("DELETE FROM memories WHERE node_id=?", (node_id,))
                    db.execute("DELETE FROM edges WHERE a=? OR b=?", (node_id, node_id))
                    db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            self._index_cache = None
        return len(rows)

    def consolidate(self) -> str:
        """Detox housekeeping: drop one-off weak links between concepts, refresh FTS, vacuum lightly."""
        with self._lock:
            db = self._db()
            with db:
                before = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                db.execute("DELETE FROM edges WHERE w < 0.6 AND a IN (SELECT id FROM nodes WHERE kind=?) "
                           "AND b IN (SELECT id FROM nodes WHERE kind=?) AND "
                           "(SELECT hits FROM nodes WHERE id=a) = 1", (KIND_CONCEPT, KIND_CONCEPT))
                after = db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                db.execute("INSERT INTO memories_fts(memories_fts) VALUES ('optimize')")
            self._index_cache = None
        return f"brain pruned {before - after} weak links"

    # --- seeding -------------------------------------------------------------------

    def seed(self, sources: Optional[Iterable[str]] = None, folder: str = "", background: bool = True) -> Dict[str, Any]:
        """Grow the brain from what is already on this PC. Idempotent: known text is skipped."""
        if self.seeding.get("running"):
            return dict(self.seeding)
        chosen = list(sources or SEED_SOURCES)
        self.seeding = {"running": True, "done": [], "current": "", "added": 0, "error": "", "started": time.time()}

        def run() -> None:
            try:
                for name in chosen:
                    self.seeding["current"] = name
                    before = self.counts()["nodes"]
                    for text, source, kind, ref in _seed_items(name, folder):
                        self._write_many([(text, source, kind, {"ref": ref})])
                    self.seeding["added"] += self.counts()["nodes"] - before
                    self.seeding["done"].append(name)
            except Exception as error:  # noqa: BLE001
                self.seeding["error"] = f"{type(error).__name__}: {error}"
                _LOG.exception("seeding failed")
            finally:
                self.seeding["running"] = False
                self.seeding["current"] = ""
                try:
                    from agent_events import publish_ui

                    publish_ui("brain.seeded", added=self.seeding["added"], total=self.counts()["nodes"])
                except Exception:
                    pass

        if background:
            threading.Thread(target=run, name="nyx-brain-seed", daemon=True).start()
        else:
            run()
        return dict(self.seeding)


SEED_SOURCES = ("knowledge", "design guidelines", "skills and agents", "conversations", "code", "lessons")

_SEED_SKIP_DIRS = {".git", ".venv", "node_modules", "dist", "build", "__pycache__", "local_pytest_tmp", "_archive",
                   "openai_mcp", "openai_mcp - Copy", "tts_cache", "uploads", "brain", "autopilot", "learning", "_preview"}


def _read(path: Path, limit: int = 400_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _seed_items(name: str, folder: str = "") -> Iterable[Tuple[str, str, str, str]]:
    root = PROJECT_DIR
    if name == "knowledge":
        for file in ("general_knowledge.md", "finance_knowledge.md", "README.md", "QUICKSTART.md", "HOW_TO_CHAT.md", "ROADMAP.md"):
            text = _read(root / file)
            if text:
                yield text, "knowledge", "document", file
        for path in sorted((root / "docs").glob("**/*.md")) if (root / "docs").is_dir() else []:
            yield _read(path), "knowledge", "document", str(path.relative_to(root))
    elif name == "design guidelines":
        hig = root / "skills" / "apple-design" / "references" / "hig"
        for path in sorted(hig.glob("*.md")) if hig.is_dir() else []:
            yield _read(path), "design", "guideline", path.name
    elif name == "skills and agents":
        for file, source in (("skills_library.json", "agents"), ("agent_roster.json", "agents")):
            try:
                data = json.loads(_read(root / file) or "{}")
            except ValueError:
                continue
            items = data.get("skills") or data.get("agents") or (data if isinstance(data, list) else [])
            for item in items:
                if isinstance(item, dict):
                    text = " ".join(str(item.get(k, "")) for k in ("name", "description", "goal", "instructions", "expertise"))
                    yield text, source, "skill" if "skill" in file else "agent", str(item.get("id") or item.get("name") or "")
    elif name == "conversations":
        try:
            chats = json.loads(_read(data_path("chats.json")) or "{}")
        except ValueError:
            chats = {}
        sessions = chats.get("chats") or chats.get("sessions") or chats
        if isinstance(sessions, dict):
            sessions = list(sessions.values())
        for session in sessions if isinstance(sessions, list) else []:
            messages = session.get("messages", []) if isinstance(session, dict) else []
            for message in messages:
                if isinstance(message, dict) and message.get("content"):
                    source = "chat" if message.get("role") == "user" else "models"
                    yield str(message["content"]), source, message.get("role", "message"), str(session.get("id", ""))
        try:
            for line in _read(data_path("learning/turns.jsonl")).splitlines():
                record = json.loads(line)
                yield record.get("message", ""), "chat", "prompt", record.get("turn_id", "")
        except ValueError:
            pass
        memory = _read(data_path("memory.json"))
        if memory:
            yield memory, "files", "memory", "memory.json"
    elif name == "code":
        for folder_path, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _SEED_SKIP_DIRS and not d.startswith((".", "local_pytest"))]
            for file in files:
                if not file.endswith((".py", ".ts", ".tsx")):
                    continue
                path = Path(folder_path) / file
                text = _read(path, 200_000)
                blocks = re.split(r"\n(?=(?:async\s+)?def |class |export |function |const \w+ = \()", text)
                rel = str(path.relative_to(root))
                for block in blocks:
                    doc = re.findall(r'"""(.+?)"""|/\*\*(.+?)\*/|#\s(.+)', block, re.S)
                    words = " ".join(" ".join(part for part in d if part) for d in doc)[:1500]
                    head = block.strip().splitlines()[0][:160] if block.strip() else ""
                    if head or words:
                        yield f"{rel}: {head}. {words}", "code", "code", rel
    elif name == "lessons":
        for line in _read(data_path("autopilot/lessons.jsonl")).splitlines():
            try:
                lesson = json.loads(line)
            except ValueError:
                continue
            yield f"{lesson.get('topic')}: {lesson.get('insight')} {lesson.get('improvement')}", "self-study", "lesson", lesson.get("module", "")
    elif name == "folder" and folder:
        base = Path(folder).expanduser()
        if not base.is_dir():
            return
        try:
            import permissions

            protected = permissions.is_protected_path
        except Exception:
            protected = lambda _p: False  # noqa: E731
        count = 0
        for folder_path, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SEED_SKIP_DIRS and not d.startswith(".")]
            for file in files:
                if not file.lower().endswith((".md", ".txt", ".py", ".ts", ".tsx", ".js", ".json", ".html", ".css", ".csv", ".rst")):
                    continue
                path = Path(folder_path) / file
                if protected(str(path)):
                    continue
                count += 1
                if count > 20000:
                    return
                yield _read(path, 300_000), "files", "file", str(path)


BRAIN = SuperBrain()


def ingest_turn(prompt: str, reply: str, provider: str = "", tools: Iterable[str] = ()) -> None:
    """Called after every chat turn: the owner's words and the gist of the answer."""
    BRAIN.ingest(prompt, source="chat", kind="prompt")
    if reply:
        BRAIN.ingest(reply[:4000], source="models", kind="answer", ref=provider)


_TOOL_SOURCES = {"web": "web", "files.read": "files", "email.read": "email", "computer": "system", "system": "system",
                 "apps": "system", "general": "knowledge"}


def ingest_tool_result(name: str, category: str, preview: str) -> None:
    """What Nyx looked at while working (searches, pages, files, mail) becomes memory too."""
    if not preview or len(preview) < 40 or name.startswith(("brain_", "improve", "ui_")):
        return
    source = _TOOL_SOURCES.get(category)
    if source is None:
        return
    BRAIN.ingest(preview[:6000], source=source, kind=name)
