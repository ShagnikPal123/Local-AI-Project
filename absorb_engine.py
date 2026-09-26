"""Data Absorption: Nyx studies documents and grows from them while the owner watches (Request R1–R6, R8).

The owner (2026-09-17): "it will basically just train itself and make itself smarter on all levels … The user can
actively see as the AI sorts through it", in three ways ("data analysis"):

* **auto** — Nyx picks broad topics (the ones the owner's chats lean on, and the ones its memory is thinnest in) and
  pulls papers, GitHub repositories, Wikipedia articles and web pages about them;
* **given** — only the files and links the owner gives it;
* **prompt** — "study this": Nyx plans sub-topics and searches for exactly that.

"At the end or when I stop it, it will say what it learned, what it added to itself like skills or agents or agent
feature or faster things … and can be relaunched for different or same things."

How a run works (one worker thread per run, one run at a time):

1. **Plan** topics and the first candidates (``absorb_text`` / ``absorb_sources``).
2. **Fetch ahead** a few documents in parallel, so the reader never waits on the network.
3. **Read** one document visibly, line by line at the owner's speed: every line is matched against the topics (the
   highlights), counted into the topic bars, scored for what is new to Nyx (the gain chart), and taught to the topic
   lexicons. With "parallel" above 1, other ready documents are *skimmed* at the same time, unanimated.
4. **Claims** — a model (role ``data_absorption``, rate-limited) turns the lines into short facts and question/answer
   pairs; with no model free, the densest lines are kept instead.
5. **Index** — facts go into the super brain tagged ``absorb:<run>:<doc>`` (so the run can be forgotten again), and
   question/answer pairs into Nyx Core's distillation set. Every later chat can recall them (``knowledge_notes``).
6. **Report** — what it learned per topic, what it stored, and *suggestions*: skills, agents, agent features,
   speed-ups and a local-model build. Each is a box the owner opens and approves; nothing changes Nyx before that
   (AGENTS.md invariant 4: an AI does not approve its own change).

Storage stays small on purpose: a run keeps the lines it showed for its latest documents and the facts it kept,
never the downloaded files. ``prune`` holds the whole folder under the owner's cap.
"""

from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
import uuid
from collections import Counter, deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import absorb_sources
import absorb_text
from paths import data_path

_LOG = logging.getLogger("nyx.absorb")

MODES = ("auto", "given", "prompt")
SOURCES = ("papers", "github", "wiki", "web")
STAGES = ("ingest", "dedupe", "tokenize", "entities", "topics", "claims", "index")
DEFAULTS: Dict[str, Any] = {
    "speed": 1.0,             # reader speed multiplier (0.25–4×); one line takes about 1.1 s at 1×
    "depth": 14,              # lines read per document (6–40)
    "parallel": 2,            # documents handled at once: 1 read visibly + skimmed alongside (1–4)
    "breadth": 6,             # topics studied at once in auto mode (3–10)
    "minutes": 20,            # how long an auto / prompt run goes (0 = until stopped)
    "docs_per_min": 10,       # network politeness cap
    "model_calls_per_min": 4, # claims extraction; the rest falls back to offline facts
    "sources": {"papers": True, "github": True, "wiki": True, "web": True},
    "storage_mb": 40,
}
LIMITS = {"speed": (0.25, 4.0), "depth": (6, 40), "parallel": (1, 4), "breadth": (3, 10), "minutes": (0, 600),
          "docs_per_min": (2, 60), "model_calls_per_min": (0, 30), "storage_mb": (5, 500)}
LINE_SECONDS = 1.1
KEEP_DOC_LINES = 40         # documents whose lines stay stored (for "click a row to hold it")
MAX_DATASET = 1500
MAX_CHART = 1200
MAX_LOG = 300
MAX_QUEUE = 40
REF_PREFIX = "absorb:"

ModelFn = Callable[..., str]


class AbsorbError(RuntimeError):
    """Something the owner asked for cannot be done; the message says why."""


def _now() -> float:
    return time.time()


def _clamp(key: str, value: Any) -> Any:
    low, high = LIMITS[key]
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULTS[key]
    number = max(low, min(high, number))
    return number if isinstance(low, float) else int(round(number))


def clean_settings(changes: Optional[Dict[str, Any]], base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = json.loads(json.dumps(base or DEFAULTS))
    for key, value in (changes or {}).items():
        if key in LIMITS and value is not None:
            settings[key] = _clamp(key, value)
        elif key == "sources" and isinstance(value, dict):
            settings["sources"] = {name: bool(value.get(name, settings["sources"].get(name, True))) for name in SOURCES}
    return settings


def json_from(text: str) -> Any:
    """The first JSON object in a model reply (fences, thinking and chatter around it are ignored).

    A reply the model ran out of tokens for is salvaged before falling back to any smaller object inside it, so a cut-off
    ``{"facts": [...` still hands back the facts it did write.
    """
    body = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    body = re.sub(r"```(?:json)?", "", body)
    first = body.find("{")
    if first != -1 and body.count("{", first) > body.count("}", first):
        salvaged = _salvage(body)
        if salvaged is not None:
            return salvaged
    start = first
    while start != -1:
        depth, in_string, escape = 0, False, False
        for index in range(start, len(body)):
            char = body[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(body[start:index + 1])
                    except ValueError:
                        break
        start = body.find("{", start + 1)
    return _salvage(body)


def _salvage(body: str) -> Any:
    """A reply that ran out of tokens mid-object: close the open strings and brackets and read what arrived."""
    start = body.find("{")
    if start == -1:
        return None
    stack, in_string, escape = [], False, False
    for char in body[start:]:
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack:
            stack.pop()
    tail = body[start:].rstrip()
    if in_string:
        tail += '"'
    tail = tail.rstrip().rstrip(",")
    for _ in range(len(stack)):
        tail += stack.pop()
    try:
        return json.loads(tail)
    except ValueError:
        return None


def _grounding(lines: Sequence[str]) -> Callable[[str], bool]:
    """Is this sentence actually about what was read? Guards against a model echoing the instructions or inventing a fact.

    A kept sentence has to share most of its meaningful words with the document — names and numbers included.
    """
    known = set()
    for line in lines:
        known.update(absorb_text.content_words(line))
        known.update(re.findall(r"\d[\d,.]*", line))
    def grounded(text: str) -> bool:
        words = set(absorb_text.content_words(text)) | set(re.findall(r"\d[\d,.]*", text or ""))
        if len(words) < 3:
            return False
        return len(words & known) / len(words) >= 0.6
    return grounded


def default_model(prompt: str, *, system: str = "", max_tokens: int = 900) -> str:
    from model_roles import MODEL_ROLES

    # "detailed thinking off" keeps NVIDIA's Nemotron from spending the whole budget reasoning before the JSON.
    return MODEL_ROLES.run("data_absorption", prompt, system="detailed thinking off\n" + system, max_tokens=max_tokens).text


# ---------------------------------------------------------------------------
# Brain access (kept here so tests can swap it)
# ---------------------------------------------------------------------------


class BrainPort:
    """The super brain as this module uses it: remember, check what is already known, recall, forget."""

    def remember(self, text: str, ref: str, topic: str = "") -> None:
        import super_brain

        super_brain.BRAIN.ingest(text, source="knowledge", kind="absorbed", ref=ref, topic=topic)

    def known(self, terms: Iterable[str]) -> Set[str]:
        import super_brain

        return super_brain.BRAIN.known_concepts(terms)

    def recall(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        import super_brain

        return super_brain.BRAIN.recall(query, limit=limit)

    def forget(self, prefix: str) -> int:
        import super_brain

        super_brain.BRAIN.flush()
        return super_brain.BRAIN.forget_ref(prefix)

    def related(self, words: Sequence[str], limit: int = 12) -> List[str]:
        import super_brain

        try:
            return super_brain.BRAIN.related_concepts(words, limit=limit)
        except Exception:  # noqa: BLE001
            return []

    def distill(self, question: str, answer: str, ref: str) -> None:
        import nyx_core

        core = getattr(nyx_core, "CORE", None)
        if core is not None and hasattr(core, "_append_distill"):
            core._append_distill({"ts": _now(), "turn_id": ref, "prompt": question[:2000], "answer": answer[:4000],
                                  "source": "absorb", "rating": 1})


# ---------------------------------------------------------------------------
# A run
# ---------------------------------------------------------------------------


class Run:
    def __init__(self, run_id: str, mode: str, prompt: str, links: List[str], uploads: List[str], settings: Dict[str, Any]) -> None:
        self.id = run_id
        self.mode = mode
        self.prompt = prompt
        self.links = links
        self.uploads = uploads
        self.settings = settings
        self.title = ""
        self.status = "starting"
        self.created_at = _now()
        self.started_at = 0.0
        self.ended_at = 0.0
        self.focus: Optional[str] = None
        self.topics = absorb_text.TopicModel([])
        self.docs: List[Dict[str, Any]] = []
        self.reader: Dict[str, Any] = {}
        self.dataset: List[Dict[str, Any]] = []
        self.chart: List[Dict[str, Any]] = []
        self.coverage_marks: Deque[Tuple[float, Dict[str, int]]] = deque(maxlen=120)
        self.log: List[Dict[str, Any]] = []
        self.stages: Counter = Counter()
        self.stage = "ingest"
        self.counts: Counter = Counter()
        self.report: Optional[Dict[str, Any]] = None
        self.suggestions: List[Dict[str, Any]] = []
        self.error = ""
        self.seq = 0
        self.queries: Deque[Tuple[str, str]] = deque()
        self.seen_urls: Set[str] = set()
        self.forgotten = False
        self.lock = threading.RLock()

    # --- views ---------------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        return {"id": self.id, "mode": self.mode, "title": self.title, "status": self.status, "created_at": self.created_at,
                "started_at": self.started_at, "ended_at": self.ended_at, "docs": self.counts.get("indexed", 0),
                "facts": self.counts.get("facts", 0), "topics": [t["code"] for t in self.topics.topics][:10],
                "headline": (self.report or {}).get("headline", ""), "pending": sum(1 for s in self.suggestions if s["state"] == "pending")}

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {"id": self.id, "mode": self.mode, "prompt": self.prompt, "links": self.links, "uploads": self.uploads,
                    "settings": self.settings, "title": self.title, "status": self.status, "created_at": self.created_at,
                    "started_at": self.started_at, "ended_at": self.ended_at, "focus": self.focus, "topics": self.topics.as_list(),
                    "docs": self.docs, "dataset": self.dataset[-MAX_DATASET:], "chart": self.chart[-MAX_CHART:], "log": self.log[-MAX_LOG:],
                    "stages": dict(self.stages), "counts": dict(self.counts), "report": self.report, "suggestions": self.suggestions,
                    "error": self.error, "forgotten": self.forgotten}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Run":
        run = cls(str(data["id"]), str(data.get("mode", "auto")), str(data.get("prompt", "")), list(data.get("links") or []),
                  list(data.get("uploads") or []), clean_settings(data.get("settings")))
        run.title = str(data.get("title", ""))
        run.status = str(data.get("status", "done"))
        if run.status in ("starting", "running", "paused", "stopping"):
            run.status = "interrupted"  # the engine stopped mid-run; the report below is what it had
        for key in ("created_at", "started_at", "ended_at"):
            setattr(run, key, float(data.get(key) or 0))
        run.focus = data.get("focus")
        run.topics = absorb_text.TopicModel(data.get("topics") or [])
        run.docs = list(data.get("docs") or [])
        run.dataset = list(data.get("dataset") or [])
        run.chart = list(data.get("chart") or [])
        run.log = list(data.get("log") or [])
        run.stages = Counter(data.get("stages") or {})
        run.counts = Counter(data.get("counts") or {})
        run.report = data.get("report")
        run.suggestions = list(data.get("suggestions") or [])
        run.error = str(data.get("error", ""))
        run.forgotten = bool(data.get("forgotten"))
        run.seen_urls = {d.get("url") for d in run.docs if d.get("url")}
        return run


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------


class AbsorbEngine:
    def __init__(self, *, store_dir: Optional[Path] = None, model_fn: Optional[ModelFn] = None, brain: Optional[BrainPort] = None,
                 finders: Optional[Dict[str, Callable[..., List[Dict[str, Any]]]]] = None,
                 reader: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
                 upload_reader: Optional[Callable[[str], Dict[str, Any]]] = None,
                 clock: Callable[[], float] = _now, sleep: Callable[[float], None] = time.sleep, threaded: bool = True,
                 line_seconds: float = LINE_SECONDS) -> None:
        self._store_dir = store_dir
        self._model_fn = model_fn
        self._brain = brain or BrainPort()
        self._finders = finders
        self._reader = reader
        self._upload_reader = upload_reader
        self._clock = clock
        self._sleep = sleep
        self._threaded = threaded
        self._line_seconds = line_seconds
        self._runs: Dict[str, Run] = {}
        self._stops: Dict[str, threading.Event] = {}
        self._pauses: Dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._loaded = False
        self._model_times: Deque[float] = deque(maxlen=64)
        self._fetch_times: Deque[float] = deque(maxlen=128)
        self._last_save: Dict[str, float] = {}

    # --- storage ---------------------------------------------------------------------------

    def _dir(self) -> Path:
        path = self._store_dir or data_path("absorb")
        (path / "runs").mkdir(parents=True, exist_ok=True)
        return path

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            for file in sorted(self._dir().joinpath("runs").glob("*.json")):
                try:
                    run = Run.from_dict(json.loads(file.read_text(encoding="utf-8")))
                    self._runs[run.id] = run
                except Exception:  # noqa: BLE001 - one bad file must not hide the rest
                    _LOG.warning("skipping unreadable absorb run %s", file.name)
            self._loaded = True

    def _save(self, run: Run, force: bool = False) -> None:
        now = self._clock()
        if not force and now - self._last_save.get(run.id, 0.0) < 5.0:
            return
        self._last_save[run.id] = now
        path = self._dir() / "runs" / f"{run.id}.json"
        try:
            data = run.to_dict()
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            temp.replace(path)
        except OSError as error:
            _LOG.warning("could not save absorb run %s: %s", run.id, error)

    def storage_bytes(self) -> int:
        return sum(f.stat().st_size for f in self._dir().rglob("*") if f.is_file())

    def prune(self, cap_mb: Optional[float] = None) -> Dict[str, Any]:
        """Keep the folder under the cap: drop stored lines of old documents first, then the oldest finished runs."""
        self._load()
        cap = float(cap_mb or max((r.settings.get("storage_mb", DEFAULTS["storage_mb"]) for r in self._runs.values()), default=DEFAULTS["storage_mb"]))
        limit = cap * 1024 * 1024
        trimmed = removed = 0
        finished = sorted((r for r in self._runs.values() if r.status not in ("running", "paused", "starting", "stopping")),
                          key=lambda r: r.created_at)
        for run in finished:
            if self.storage_bytes() <= limit:
                break
            with run.lock:
                for doc in run.docs:
                    if doc.get("lines"):
                        doc["lines"], doc["spans"] = [], []
                        trimmed += 1
                run.chart = run.chart[-200:]
                run.log = run.log[-60:]
            self._save(run, force=True)
        for run in finished:
            if self.storage_bytes() <= limit:
                break
            self.delete(run.id)
            removed += 1
        return {"bytes": self.storage_bytes(), "cap_bytes": int(limit), "trimmed_docs": trimmed, "removed_runs": removed}

    # --- reads -------------------------------------------------------------------------------

    def list(self) -> List[Dict[str, Any]]:
        self._load()
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: -r.created_at)
        return [r.summary() for r in runs]

    def get(self, run_id: str) -> Run:
        self._load()
        run = self._runs.get(run_id)
        if run is None:
            raise AbsorbError("No such study run.")
        return run

    def active(self) -> Optional[Run]:
        self._load()
        return next((r for r in self._runs.values() if r.status in ("starting", "running", "paused", "stopping")), None)

    def live(self, run_id: str, *, have_doc: str = "") -> Dict[str, Any]:
        """Everything the tab draws right now, compact enough to ask for every second."""
        run = self.get(run_id)
        with run.lock:
            now = self._clock()
            reader = dict(run.reader)
            doc = next((d for d in run.docs if d["id"] == reader.get("doc_id")), None)
            if doc is not None:
                reader["doc"] = self._doc_view(doc, lines=doc["id"] != have_doc)
            queue = [self._doc_view(d, lines=False) for d in self._queue_order(run)][:MAX_QUEUE]
            topics = []
            total = sum(t["count"] for t in run.topics.topics) or 1
            vote = (doc or {}).get("vote") or {}
            for topic in run.topics.topics:
                topics.append({"id": topic["id"], "code": topic["code"], "name": topic["name"], "color": topic["color"],
                               "count": topic["count"], "share": round(topic["count"] / total, 3), "docs": topic.get("docs", 0),
                               "doc_vote": vote.get(topic["id"], 0.0), "gain": round(topic.get("gain", 0.0), 3),
                               "terms": run.topics.top_terms(topic["id"], 5)})
            window = [p for p in run.chart if now - p["t"] <= 180]
            return {
                "id": run.id, "mode": run.mode, "title": run.title, "status": run.status, "stage": run.stage,
                "stages": {s: run.stages.get(s, 0) for s in STAGES}, "settings": run.settings, "focus": run.focus,
                "started_at": run.started_at, "ended_at": run.ended_at, "now": now,
                "ends_at": (run.started_at + run.settings["minutes"] * 60) if run.started_at and run.settings["minutes"] and run.mode != "given" else None,
                "counts": {**{k: run.counts.get(k, 0) for k in ("queued", "fetching", "indexed", "skipped", "sampled_out", "facts", "examples", "model_facts", "lines")},
                           "rows": len(run.dataset)},
                "topics": topics, "reader": reader, "queue": queue, "dataset": run.dataset[-60:][::-1], "chart": window[-400:],
                "coverage": self._coverage(run, now), "log": run.log[-20:][::-1], "error": run.error,
                "report_ready": run.report is not None, "pending": sum(1 for s in run.suggestions if s["state"] == "pending"),
                "seq": run.seq,
            }

    def doc(self, run_id: str, doc_id: str) -> Dict[str, Any]:
        run = self.get(run_id)
        with run.lock:
            doc = next((d for d in run.docs if d["id"] == doc_id), None)
            if doc is None:
                raise AbsorbError("That document is not in this run.")
            return self._doc_view(doc, lines=True)

    @staticmethod
    def _doc_view(doc: Dict[str, Any], lines: bool) -> Dict[str, Any]:
        view = {k: v for k, v in doc.items() if k not in ("lines", "spans", "text")}
        if lines:
            view["lines"] = [{"i": i, "text": text, "spans": (doc.get("spans") or [])[i] if i < len(doc.get("spans") or []) else []}
                             for i, text in enumerate(doc.get("lines") or [])]
        return view

    @staticmethod
    def _queue_order(run: Run) -> List[Dict[str, Any]]:
        order = {"reading": 0, "skimming": 1, "fetching": 2, "queued": 3, "indexed": 4, "skipped": 5, "error": 6}
        return sorted(run.docs, key=lambda d: (order.get(d["state"], 9), -(d.get("done_at") or d.get("filed_at") or 0)))

    def _coverage(self, run: Run, now: float) -> List[Dict[str, Any]]:
        counts = {t["id"]: t["count"] for t in run.topics.topics}
        total = sum(counts.values()) or 1
        earlier = next((marks for at, marks in run.coverage_marks if now - at <= 60), None)
        earlier_total = sum((earlier or {}).values()) or 1
        rows = []
        for topic in run.topics.topics:
            share = counts[topic["id"]] / total
            before = (earlier or {}).get(topic["id"], 0) / earlier_total if earlier else share
            rows.append({"id": topic["id"], "code": topic["code"], "share": round(share, 3), "delta": round(share - before, 3),
                         "color": topic["color"]})
        return rows

    # --- control -----------------------------------------------------------------------------

    def start(self, mode: str, *, prompt: str = "", links: Sequence[str] = (), uploads: Sequence[str] = (),
              settings: Optional[Dict[str, Any]] = None, replace: bool = False) -> Dict[str, Any]:
        mode = (mode or "").strip().lower()
        if mode not in MODES:
            raise AbsorbError("Pick a mode: auto, given (your files and links) or prompt (study a subject).")
        clean_links = [link.strip() for link in links if str(link or "").strip()][:40]
        clean_uploads = [str(u).strip() for u in uploads if str(u or "").strip()][:40]
        if mode == "given" and not (clean_links or clean_uploads):
            raise AbsorbError("Add at least one file or link for Nyx to study.")
        if mode == "prompt" and len((prompt or "").strip()) < 3:
            raise AbsorbError("Say what Nyx should study.")
        for link in clean_links:
            if not re.match(r"^https?://", link):
                raise AbsorbError(f"Not a web link: {link[:80]}")
        current = self.active()
        if current is not None:
            if not replace:
                raise AbsorbError("A study run is already going. Stop it first, or start with replace.")
            self.stop(current.id, wait=True)
        run = Run(uuid.uuid4().hex[:10], mode, (prompt or "").strip()[:2000], clean_links, clean_uploads, clean_settings(settings))
        run.title = self._title_for(run)
        with self._lock:
            self._load()
            self._runs[run.id] = run
            self._stops[run.id] = threading.Event()
            pause = threading.Event()
            pause.set()
            self._pauses[run.id] = pause
        self._note(run, f"Started: {run.title}")
        self._save(run, force=True)
        self._publish(run)
        if self._threaded:
            threading.Thread(target=self._run, args=(run,), name=f"nyx-absorb-{run.id}", daemon=True).start()
        else:
            self._run(run)
        return self.live(run.id)

    @staticmethod
    def _title_for(run: Run) -> str:
        if run.mode == "prompt":
            return f"Studying: {run.prompt[:80]}"
        if run.mode == "given":
            count = len(run.links) + len(run.uploads)
            return f"Studying {count} item{'s' if count != 1 else ''} you gave"
        return "Studying on its own"

    def stop(self, run_id: str, wait: bool = False) -> Dict[str, Any]:
        run = self.get(run_id)
        event = self._stops.get(run_id)
        if event is None or run.status not in ("starting", "running", "paused"):
            return self.live(run_id)
        with run.lock:
            run.status = "stopping"
        event.set()
        pause = self._pauses.get(run_id)
        if pause is not None:
            pause.set()
        self._note(run, "Stopping — writing what it learned")
        if wait:
            deadline = time.time() + 60
            while run.status == "stopping" and time.time() < deadline:
                time.sleep(0.05)
        return self.live(run_id)

    def pause(self, run_id: str) -> Dict[str, Any]:
        run = self.get(run_id)
        pause = self._pauses.get(run_id)
        if pause is not None and run.status == "running":
            pause.clear()
            with run.lock:
                run.status = "paused"
            self._note(run, "Paused")
        return self.live(run_id)

    def resume(self, run_id: str) -> Dict[str, Any]:
        run = self.get(run_id)
        pause = self._pauses.get(run_id)
        if pause is not None and run.status == "paused":
            with run.lock:
                run.status = "running"
            pause.set()
            self._note(run, "Resumed")
        return self.live(run_id)

    def set_focus(self, run_id: str, topic_id: Optional[str]) -> Dict[str, Any]:
        run = self.get(run_id)
        with run.lock:
            if topic_id and run.topics.by_id(topic_id) is None:
                raise AbsorbError("No such topic in this run.")
            run.focus = topic_id or None
            run.seq += 1
        topic = run.topics.by_id(topic_id or "")
        self._note(run, f"Focus: {topic['name']}" if topic else "Focus cleared — studying every topic")
        if topic is not None and run.mode != "given":
            for query in reversed(topic.get("queries") or [topic["name"]]):
                run.queries.appendleft((topic["id"], query))
        return self.live(run_id)

    def update_settings(self, run_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        run = self.get(run_id)
        with run.lock:
            run.settings = clean_settings(changes, run.settings)
            run.seq += 1
        return self.live(run_id)

    def delete(self, run_id: str) -> None:
        run = self.get(run_id)
        if run.status in ("starting", "running", "paused", "stopping"):
            raise AbsorbError("Stop the run before deleting it.")
        with self._lock:
            self._runs.pop(run_id, None)
        try:
            (self._dir() / "runs" / f"{run_id}.json").unlink()
        except OSError:
            pass

    def forget(self, run_id: str) -> Dict[str, Any]:
        """Take this run's facts back out of Nyx's memory (the report stays, marked forgotten)."""
        run = self.get(run_id)
        if run.status in ("starting", "running", "paused", "stopping"):
            raise AbsorbError("Stop the run first.")
        removed = self._brain.forget(f"{REF_PREFIX}{run.id}:")
        with run.lock:
            run.forgotten = True
        self._note(run, f"Forgot {removed} memories from this run")
        self._save(run, force=True)
        return {"removed": removed}

    def again(self, run_id: str, how: str = "same", topic_id: str = "") -> Dict[str, Any]:
        """Relaunch: the same study again, deeper on one topic, or the same sources with fresh eyes."""
        run = self.get(run_id)
        settings = dict(run.settings)
        if how == "deeper" and topic_id:
            topic = run.topics.by_id(topic_id)
            if topic is None:
                raise AbsorbError("No such topic in that run.")
            prompt = f"{topic['name']} — go deeper than: " + "; ".join(f["text"][:80] for f in run.dataset if f.get("topic") == topic["code"])[:600]
            return self.start("prompt", prompt=prompt, settings={**settings, "depth": min(40, int(settings["depth"]) + 6)}, replace=True)
        return self.start(run.mode, prompt=run.prompt, links=run.links, uploads=run.uploads, settings=settings, replace=True)

    # --- the worker --------------------------------------------------------------------------

    def _stopped(self, run: Run) -> bool:
        event = self._stops.get(run.id)
        return bool(event and event.is_set())

    def _wait_if_paused(self, run: Run) -> None:
        pause = self._pauses.get(run.id)
        while pause is not None and not pause.is_set() and not self._stopped(run):
            pause.wait(0.25)

    def _out_of_time(self, run: Run) -> bool:
        minutes = run.settings.get("minutes") or 0
        return bool(run.mode != "given" and minutes and self._clock() - run.started_at >= minutes * 60)

    def _run(self, run: Run) -> None:
        pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix=f"absorb-{run.id}")
        model_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"absorb-model-{run.id}")
        pending_claims: List[Future] = []
        try:
            with run.lock:
                run.status = "running"
                run.started_at = self._clock()
            self._plan(run)
            fetches: Dict[str, Future] = {}
            while not self._stopped(run):
                self._wait_if_paused(run)
                if self._stopped(run) or self._out_of_time(run):
                    break
                self._fill_queue(run)
                self._fetch_ahead(run, pool, fetches)
                ready = self._ready_docs(run, fetches)
                if not ready:
                    if run.mode == "given" and not any(d["state"] in ("queued", "fetching") for d in run.docs):
                        break  # everything the owner gave has been read
                    if run.mode != "given" and not run.queries and not any(d["state"] in ("queued", "fetching") for d in run.docs):
                        self._more_queries(run)
                        if not run.queries:
                            break
                    self._sleep(0.2)
                    continue
                visible, *skim = ready[: int(run.settings["parallel"])]
                skim_jobs = [pool.submit(self._read_doc, run, doc, False) for doc in skim]
                self._read_doc(run, visible, True)
                for job in skim_jobs:
                    try:
                        job.result(timeout=120)
                    except Exception as error:  # noqa: BLE001
                        _LOG.warning("skim failed: %s", error)
                for doc in [visible, *skim]:
                    if doc["state"] == "analysed":
                        pending_claims.append(model_pool.submit(self._claims_and_index, run, doc))
                pending_claims = [f for f in pending_claims if not f.done()]
                self._save(run)
            for future in pending_claims:
                try:
                    future.result(timeout=90)
                except Exception:  # noqa: BLE001
                    pass
            self._finish(run, "stopped" if self._stopped(run) else "done")
        except Exception as error:  # noqa: BLE001 - a failed run says why and still reports what it had
            _LOG.exception("absorb run failed")
            with run.lock:
                run.error = f"{type(error).__name__}: {str(error)[:300]}"
            self._finish(run, "error")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
            model_pool.shutdown(wait=False, cancel_futures=True)

    # --- planning ------------------------------------------------------------------------------

    def _plan(self, run: Run) -> None:
        run.stage = "ingest"
        if run.mode == "auto":
            topics = self._auto_topics(run)
            run.topics = absorb_text.TopicModel(topics)
            self._note(run, "Topics: " + ", ".join(t["name"] for t in run.topics.topics))
        elif run.mode == "prompt":
            run.topics = absorb_text.TopicModel(self._prompt_topics(run))
            self._note(run, "Plan: " + ", ".join(t["name"] for t in run.topics.topics))
        else:
            self._given_docs(run)
        if run.mode != "given":
            for topic in run.topics.topics:
                for query in topic.get("queries") or [topic["name"]]:
                    run.queries.append((topic["id"], query))
        run.seq += 1

    def _auto_topics(self, run: Run) -> List[Dict[str, Any]]:
        """The owner's interests first (what their chats talk about), then where Nyx's memory is thinnest."""
        interest: Counter = Counter()
        try:
            recent = self._brain.recall("the owner asked about " + " ".join(t["name"] for t in absorb_text.DEFAULT_TOPICS), limit=40)
        except Exception:  # noqa: BLE001
            recent = []
        model = absorb_text.TopicModel(absorb_text.DEFAULT_TOPICS)
        for memory in recent:
            for topic, share in model.vote(model.match(memory.get("text", ""), max_spans=20)).items():
                interest[topic] += share
        ranked = sorted(absorb_text.DEFAULT_TOPICS, key=lambda t: (-interest.get(t["id"], 0.0), random.random()))
        chosen = ranked[: int(run.settings["breadth"])]
        return [{**t, "color": i} for i, t in enumerate(chosen)]

    def _prompt_topics(self, run: Run) -> List[Dict[str, Any]]:
        plan = None
        reply = self._ask(run, (
            f"The owner wants their AI assistant to study this, to get better at it:\n\"{run.prompt}\"\n\n"
            "Plan 4 to 7 sub-topics to study. For each give a short name, a 3–5 letter CODE, 12–20 terms that appear in texts "
            "about it (lowercase), and 2–3 search queries that would find good papers, GitHub projects and articles.\n"
            'Reply with JSON only: {"topics": [{"name": "", "code": "", "terms": [], "queries": []}]}'),
            system="You plan study sessions. Reply with JSON only, no reasoning.", max_tokens=1400, force=True)
        if reply:
            data = json_from(reply)
            if isinstance(data, dict):
                plan = data.get("topics")
        related = self._brain.related(absorb_text.content_words(run.prompt)[:6])
        topics = absorb_text.topics_from_plan(run.prompt, plan, related)
        return [{**t, "color": i} for i, t in enumerate(topics)]

    def _given_docs(self, run: Run) -> None:
        for upload_id in run.uploads:
            self._add_doc(run, {"kind": "upload", "title": "Your file", "url": "", "source": "Your file", "upload_id": upload_id})
        for link in run.links:
            self._add_doc(run, absorb_sources.link_candidate(link))
        # Topics come from the documents themselves, so read them all (in parallel) before the reader starts.
        texts: List[str] = []
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {doc["id"]: pool.submit(self._fetch, run, doc) for doc in list(run.docs)}
            for doc in run.docs:
                try:
                    futures[doc["id"]].result(timeout=120)
                except Exception:  # noqa: BLE001 - _fetch records its own error
                    pass
                if doc.get("text"):
                    texts.append(doc["text"][:60_000])
        topics = absorb_text.derive_topics(texts, k=6) if texts else []
        named = self._name_topics(run, topics, texts)
        run.topics = absorb_text.TopicModel([{**t, "color": i} for i, t in enumerate(named or topics)])
        self._note(run, "Topics found in your documents: " + ", ".join(t["name"] for t in run.topics.topics))

    def _name_topics(self, run: Run, topics: List[Dict[str, Any]], texts: List[str]) -> List[Dict[str, Any]]:
        if not topics:
            return topics
        listing = "\n".join(f"{i + 1}. " + ", ".join(t["terms"][:10]) for i, t in enumerate(topics))
        reply = self._ask(run, (
            "These groups of terms came from documents the owner gave. Name each group as a broad topic (2–5 words) with a "
            "3–5 letter CODE, keeping the order.\n" + listing +
            '\nReply with JSON only: {"topics": [{"name": "", "code": ""}]}'),
            system="You name topics. Reply with JSON only, no reasoning.", max_tokens=700, force=True)
        data = json_from(reply or "")
        names = data.get("topics") if isinstance(data, dict) else None
        if not isinstance(names, list):
            return topics
        taken: List[str] = []
        out = []
        for topic, named in zip(topics, names + [{}] * len(topics)):
            name = str((named or {}).get("name") or topic["name"])[:60]
            code = str((named or {}).get("code") or "").upper()[:6] or absorb_text.code_for(name, taken)
            if code in taken:
                code = absorb_text.code_for(name, taken)
            taken.append(code)
            out.append({**topic, "name": name, "code": code})
        return out

    # --- queue ---------------------------------------------------------------------------------

    def _add_doc(self, run: Run, candidate: Dict[str, Any], topic_id: str = "") -> Optional[Dict[str, Any]]:
        url = candidate.get("url") or ""
        with run.lock:
            if url and url in run.seen_urls:
                run.counts["sampled_out"] += 1
                return None
            if url:
                run.seen_urls.add(url)
            doc = {"id": uuid.uuid4().hex[:8], "kind": candidate.get("kind", "web"), "source": candidate.get("source", ""),
                   "title": candidate.get("title") or url or "Document", "url": url, "state": "queued", "topic": topic_id,
                   "filed_at": self._clock(), "read_at": 0.0, "done_at": 0.0, "score": 0.0, "gain": 0.0, "vote": {},
                   "line_index": 0, "line_total": 0, "tokens": 0, "summary": "", "facts": 0, "error": "",
                   "meta": {k: candidate[k] for k in ("year", "authors", "venue", "stars", "citations") if candidate.get(k)},
                   "upload_id": candidate.get("upload_id", ""), "text": candidate.get("text", ""),
                   "full_name": candidate.get("full_name", ""), "branch": candidate.get("branch", "")}
            run.docs.append(doc)
            run.counts["queued"] += 1
            run.seq += 1
            return doc

    def _fill_queue(self, run: Run) -> None:
        if run.mode == "given":
            return
        waiting = sum(1 for d in run.docs if d["state"] in ("queued", "fetching"))
        if waiting >= int(run.settings["parallel"]) + 3 or not run.queries:
            return
        topic_id, query = self._next_query(run)
        finders = self._finders or absorb_sources.FINDERS
        limits = {"papers": 2, "github": 1, "wiki": 1, "web": 2}
        found = 0
        for name in SOURCES:
            if not run.settings["sources"].get(name) or name not in finders:
                continue
            try:
                for candidate in finders[name](query, limits[name]):
                    if self._add_doc(run, candidate, topic_id) is not None:
                        found += 1
            except Exception as error:  # noqa: BLE001 - one source down is not a failed run
                self._note(run, f"{name} search failed: {str(error)[:80]}")
        self._note(run, f"Searched “{query[:60]}” — {found} new")

    def _next_query(self, run: Run) -> Tuple[str, str]:
        if run.focus:
            for index, (topic_id, query) in enumerate(run.queries):
                if topic_id == run.focus:
                    del run.queries[index]
                    return topic_id, query
        return run.queries.popleft()

    def _more_queries(self, run: Run) -> None:
        """Keep going: the key phrases each topic picked up while reading become the next searches."""
        for topic in run.topics.topics:
            learned = [t for t in run.topics.top_terms(topic["id"], 12) if " " in t][:2]
            for phrase in learned:
                query = f"{topic['name']} {phrase}"
                if query not in {q for _, q in run.queries}:
                    run.queries.append((topic["id"], query))
        if run.queries:
            self._note(run, "Following what it learned: " + "; ".join(q for _, q in list(run.queries)[:3]))

    def _fetch_ahead(self, run: Run, pool: ThreadPoolExecutor, fetches: Dict[str, Future]) -> None:
        in_flight = sum(1 for f in fetches.values() if not f.done())
        budget = int(run.settings["parallel"]) + 1 - in_flight
        if budget <= 0:
            return
        per_minute = int(run.settings["docs_per_min"])
        now = self._clock()
        recent = sum(1 for t in self._fetch_times if now - t < 60)
        queued = [d for d in run.docs if d["state"] == "queued"]
        if run.focus:
            queued.sort(key=lambda d: 0 if d.get("topic") == run.focus else 1)
        for doc in queued[:budget]:
            if recent >= per_minute:
                break
            recent += 1
            self._fetch_times.append(now)
            with run.lock:
                doc["state"] = "fetching"
                run.counts["queued"] = max(0, run.counts["queued"] - 1)
                run.counts["fetching"] += 1
                run.seq += 1
            fetches[doc["id"]] = pool.submit(self._fetch, run, doc)

    def _fetch(self, run: Run, doc: Dict[str, Any]) -> None:
        run.stage = "ingest"
        try:
            if doc["kind"] == "upload":
                got = (self._upload_reader or absorb_sources.read_upload)(doc["upload_id"])
            else:
                got = (self._reader or absorb_sources.read)(doc)
            text = got.get("text") or ""
            with run.lock:
                doc["title"] = got.get("title") or doc["title"]
                doc["text"] = text
                doc["tokens"] = absorb_text.estimate_tokens(text)
                run.stages["ingest"] += 1
            run.stage = "dedupe"
            key = absorb_text.normalize(text[:2000])
            duplicate = any(d is not doc and d.get("_key") == key for d in run.docs)
            with run.lock:
                doc["_key"] = key
                run.stages["dedupe"] += 1
                if duplicate:
                    doc["state"], doc["error"] = "skipped", "Same text as another document"
                    run.counts["sampled_out"] += 1
                    doc["text"] = ""
                elif doc["state"] == "fetching":
                    doc["state"] = "ready"
        except absorb_sources.SourceError as error:
            with run.lock:
                doc["state"], doc["error"], doc["text"] = "skipped", str(error)[:160], ""
                run.counts["skipped"] += 1
        except Exception as error:  # noqa: BLE001
            with run.lock:
                doc["state"], doc["error"], doc["text"] = "error", f"{type(error).__name__}: {str(error)[:120]}", ""
                run.counts["skipped"] += 1
        finally:
            with run.lock:
                if run.counts["fetching"] > 0 and doc.get("state") != "fetching":
                    run.counts["fetching"] -= 1
                run.seq += 1

    def _ready_docs(self, run: Run, fetches: Dict[str, Future]) -> List[Dict[str, Any]]:
        for doc_id in [k for k, f in fetches.items() if f.done()]:
            fetches.pop(doc_id, None)
        ready = [d for d in run.docs if d["state"] == "ready"]
        if run.mode == "given" and not ready:
            ready = [d for d in run.docs if d["state"] == "queued" and d.get("text")]
        if run.focus:
            ready.sort(key=lambda d: (0 if d.get("topic") == run.focus or (d.get("vote") or {}).get(run.focus) else 1, d["filed_at"]))
        return ready

    # --- reading -------------------------------------------------------------------------------

    def _read_doc(self, run: Run, doc: Dict[str, Any], visible: bool) -> None:
        text = doc.get("text") or ""
        run.stage = "tokenize"
        lines = absorb_text.split_lines(text, limit=int(run.settings["depth"]))
        with run.lock:
            if run.counts["queued"] > 0 and doc["kind"] == "upload" and doc["state"] == "queued":
                run.counts["queued"] -= 1
            doc["state"] = "reading" if visible else "skimming"
            doc["read_at"] = self._clock()
            doc["lines"], doc["spans"] = lines, []
            doc["line_total"], doc["line_index"] = len(lines), 0
            run.stages["tokenize"] += 1
            if visible:
                run.reader = {"doc_id": doc["id"], "title_spans": run.topics.match(doc["title"], max_spans=4), "started": self._clock()}
            run.seq += 1
        if not lines:
            with run.lock:
                doc["state"], doc["error"] = "skipped", "Nothing readable in it"
                doc["text"] = ""
                run.counts["skipped"] += 1
            return
        known = set()
        try:
            known = self._brain.known({w for line in lines for w in absorb_text.content_words(line)})
        except Exception:  # noqa: BLE001 - novelty is a nicety
            pass
        gains = []
        for index, line in enumerate(lines):
            if self._stopped(run):
                break
            self._wait_if_paused(run)
            started = time.monotonic()
            run.stage = "entities"
            spans = run.topics.match(line)
            run.stage = "topics"
            with run.lock:
                run.topics.count(spans)
                run.topics.learn(line, spans)
                vote = run.topics.vote(spans)
                terms = absorb_text.content_words(line)
                gain = round(absorb_text.novelty(terms, known) * (0.4 + 0.6 * (max(vote.values()) if vote else 0.0)), 3)
                known.update(terms)
                gains.append(gain)
                doc["spans"].append(spans)
                doc["line_index"] = index + 1
                doc["gain"] = round(sum(gains) / len(gains), 3)
                top = max(vote.items(), key=lambda kv: kv[1])[0] if vote else None
                if top:
                    topic = run.topics.by_id(top)
                    if topic is not None:
                        topic["gain"] = round(topic.get("gain", 0.0) * 0.9 + gain * 0.1, 4)
                run.chart.append({"t": self._clock(), "v": gain, "topic": top})
                if len(run.chart) > MAX_CHART:
                    del run.chart[: len(run.chart) - MAX_CHART]
                run.stages["entities"] += 1
                run.stages["topics"] += 1
                run.counts["lines"] += 1
                if visible and index % 10 == 0:
                    run.coverage_marks.append((self._clock(), {t["id"]: t["count"] for t in run.topics.topics}))
                run.seq += 1
            if visible:
                pause_for = self._line_seconds / float(run.settings["speed"]) - (time.monotonic() - started)
                if pause_for > 0:
                    self._sleep(pause_for)
        all_spans = [s for line_spans in doc["spans"] for s in line_spans]
        with run.lock:
            doc["vote"] = run.topics.vote(all_spans)
            doc["gain"] = round(sum(gains) / len(gains), 3) if gains else 0.0
            doc["score"] = round(doc["gain"] * (1 + len([s for s in all_spans if s.get("topic")]) / 20), 3)
            top = max(doc["vote"].items(), key=lambda kv: kv[1])[0] if doc["vote"] else doc.get("topic")
            doc["topic"] = top or doc.get("topic")
            topic = run.topics.by_id(doc["topic"] or "")
            if topic is not None:
                topic["docs"] = topic.get("docs", 0) + 1
            doc["summary"] = absorb_text.offline_summary(lines)
            doc["state"] = "analysed"
            run.seq += 1

    def _claims_and_index(self, run: Run, doc: Dict[str, Any]) -> None:
        run.stage = "claims"
        lines = doc.get("lines") or []
        facts: List[Dict[str, Any]] = []
        qa: List[Dict[str, str]] = []
        summary = doc.get("summary", "")
        codes = {t["code"]: t["id"] for t in run.topics.topics}
        reply = self._ask(run, (
            "Topics: " + "; ".join(f"{t['code']} = {t['name']}" for t in run.topics.topics) + "\n"
            f"Document: {doc['title']} ({doc['source']})\n" + "\n".join(lines[:40]) + "\n\n"
            "Write down what an AI assistant should remember from THIS document. Every fact must be stated in the lines above — "
            "do not add anything from your own knowledge, and do not repeat the wording of these instructions.\n"
            "Fields: summary (two sentences about this document), facts (up to 6; each has text, one self-contained sentence under "
            "240 characters keeping its numbers and names, and topic, one of the codes above), qa (up to 2 question/answer pairs "
            "that this document answers).\n"
            'Example of the shape, about a different subject: {"summary": "The paper measures cache misses in web servers. It '
            'compares three eviction policies.", "facts": [{"text": "LRU eviction cut cache misses by 18% over FIFO in the 2019 '
            'benchmark.", "topic": "DATA"}], "qa": [{"q": "Which eviction policy performed best?", "a": "LRU, by 18% over FIFO."}]}'),
            system="You extract durable knowledge from documents for an assistant's memory. Reply with JSON only, no reasoning.",
            max_tokens=1400)
        data = json_from(reply or "")
        if isinstance(data, dict):
            grounded = _grounding(lines)
            model_summary = str(data.get("summary") or "").strip()
            if grounded(model_summary):
                summary = model_summary[:500]
            for item in (data.get("facts") or [])[:8]:
                body = str(item.get("text", "") if isinstance(item, dict) else item).strip()
                if len(body) <= 20 or not grounded(body):
                    continue  # a template echo, or something the document never said
                code = str(item.get("topic", "") if isinstance(item, dict) else "").upper()
                facts.append({"text": body[:300], "topic": codes.get(code) or doc.get("topic")})
                if len(facts) >= 6:
                    break
            for pair in (data.get("qa") or [])[:2]:
                # Short answers ("11434") carry too few words to judge alone, so the question is weighed with them.
                if isinstance(pair, dict) and pair.get("q") and pair.get("a") and grounded(f"{pair['q']} {pair['a']}"):
                    qa.append({"q": str(pair["q"])[:400], "a": str(pair["a"])[:1200]})
            if not facts and reply:
                self._note(run, f"The model's reply about “{doc['title'][:40]}” was not grounded in it — keeping the densest lines instead")
        model_made = bool(facts)
        if not facts:
            facts = absorb_text.offline_facts(lines, doc.get("spans") or [], limit=max(2, int(run.settings["depth"]) // 5))
        run.stage = "index"
        ref = f"{REF_PREFIX}{run.id}:{doc['id']}"
        for fact in facts:
            topic = run.topics.by_id(fact.get("topic") or "")
            try:
                self._brain.remember(f"{fact['text']} (from {doc['title'][:80]}, {doc['source']})", ref, topic["name"] if topic else "")
            except Exception as error:  # noqa: BLE001
                _LOG.warning("absorb remember failed: %s", error)
        for pair in qa:
            try:
                self._brain.distill(pair["q"], pair["a"], ref)
            except Exception:  # noqa: BLE001
                pass
        with run.lock:
            doc["summary"] = summary
            doc["facts"] = len(facts)
            doc["state"] = "indexed"
            doc["done_at"] = self._clock()
            doc["text"] = ""  # the document itself is not kept
            run.stages["claims"] += 1
            run.stages["index"] += 1
            run.counts["indexed"] += 1
            run.counts["facts"] += len(facts)
            run.counts["examples"] += len(qa)
            if model_made:
                run.counts["model_facts"] += len(facts)
            for fact in facts:
                topic = run.topics.by_id(fact.get("topic") or "")
                run.dataset.append({"t": self._clock(), "doc": doc["id"], "source": doc["source"][:24] or doc["kind"],
                                    "kind": doc["kind"], "topic": topic["code"] if topic else "—", "topic_id": topic["id"] if topic else None,
                                    "text": fact["text"][:300], "gain": doc["gain"], "by": "model" if model_made else "offline"})
            if len(run.dataset) > MAX_DATASET:
                del run.dataset[: len(run.dataset) - MAX_DATASET]
            # Only the latest documents keep their lines; older ones keep their numbers.
            with_lines = [d for d in run.docs if d.get("lines")]
            for old in with_lines[:-KEEP_DOC_LINES]:
                old["lines"], old["spans"] = [], []
            run.seq += 1

    def _ask(self, run: Run, prompt: str, *, system: str, max_tokens: int, force: bool = False) -> str:
        """One model call if the run's budget allows it right now (planning calls are always allowed)."""
        per_minute = int(run.settings.get("model_calls_per_min", 4))
        now = self._clock()
        if not force:
            if per_minute <= 0 or sum(1 for t in self._model_times if now - t < 60) >= per_minute:
                return ""
        self._model_times.append(now)
        try:
            return (self._model_fn or default_model)(prompt, system=system, max_tokens=max_tokens) or ""
        except Exception as error:  # noqa: BLE001 - offline analysis covers for it
            self._note(run, f"Model unavailable ({str(error)[:80]}) — keeping the densest lines instead")
            return ""

    # --- the end -------------------------------------------------------------------------------

    def _finish(self, run: Run, how: str) -> None:
        with run.lock:
            run.stage = "index"
            for doc in run.docs:
                if doc["state"] in ("reading", "skimming", "analysed", "ready", "fetching", "queued"):
                    doc["text"] = ""
                    if doc["state"] in ("reading", "skimming", "analysed"):
                        doc["state"] = "indexed" if doc.get("facts") else "skipped"
            run.reader = {**run.reader, "finished": True}
        try:
            report, suggestions = self._write_report(run)
        except Exception as error:  # noqa: BLE001
            _LOG.exception("absorb report failed")
            report, suggestions = {"headline": f"Stopped with an error writing the report: {error}", "learned": [], "added": {}}, []
        with run.lock:
            run.report = report
            run.suggestions = suggestions
            run.status = "error" if how == "error" else how
            run.ended_at = self._clock()
            run.seq += 1
        self._note(run, report.get("headline", "Finished"))
        self._save(run, force=True)
        self._publish(run)
        try:
            self.prune()
        except Exception:  # noqa: BLE001
            pass

    def _write_report(self, run: Run) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        by_topic: Dict[str, List[str]] = {}
        for row in run.dataset:
            by_topic.setdefault(row.get("topic") or "—", []).append(row["text"])
        indexed = [d for d in run.docs if d["state"] == "indexed"]
        added = {"documents": len(indexed), "facts": run.counts.get("facts", 0), "examples": run.counts.get("examples", 0),
                 "lines": run.counts.get("lines", 0), "skipped": run.counts.get("skipped", 0) + run.counts.get("sampled_out", 0),
                 "new_terms": sum(max(0, len(t["terms"]) - 20) for t in run.topics.topics),
                 "minutes": round(max(0.0, (self._clock() - run.started_at) / 60), 1) if run.started_at else 0}
        learned = []
        for topic in sorted(run.topics.topics, key=lambda t: -t["count"]):
            points = by_topic.get(topic["code"], [])[:5]
            if points or topic["count"]:
                learned.append({"topic": topic["name"], "code": topic["code"], "count": topic["count"], "docs": topic.get("docs", 0),
                                "points": points, "terms": run.topics.top_terms(topic["id"], 8)})
        sources = Counter(d["source"] for d in indexed)
        headline = (f"Read {len(indexed)} document{'s' if len(indexed) != 1 else ''} and kept {added['facts']} facts"
                    + (f" across {len([l for l in learned if l['points']])} topics" if learned else "")
                    + (f" (mostly {sources.most_common(1)[0][0]})" if sources else "") + ".")
        suggestions = self._suggest(run, learned)
        report = {"headline": headline, "learned": learned, "added": added,
                  "sources": [{"source": s, "count": n} for s, n in sources.most_common(8)],
                  "documents": [{"id": d["id"], "title": d["title"], "url": d["url"], "source": d["source"], "facts": d.get("facts", 0),
                                 "gain": d.get("gain", 0)} for d in sorted(indexed, key=lambda d: -d.get("gain", 0))[:30]],
                  "next": [f"Go deeper on {l['topic']}" for l in learned[:3]], "written_by": "offline"}
        facts_block = "\n".join(f"[{row.get('topic')}] {row['text'][:220]}" for row in run.dataset[-80:])
        if facts_block:
            reply = self._ask(run, (
                f"An AI assistant (Nyx) just finished a study run: {run.title}.\n"
                f"Documents read: {len(indexed)}. Facts it kept (topic code first):\n{facts_block}\n\n"
                "Write the report the owner reads, and suggest how Nyx should change itself because of what it learned. Kinds:\n"
                "- skill: reusable instructions Nyx follows when a request matches (name, description, instructions, triggers)\n"
                "- agent: a new specialist sub-agent (name, goal, instructions, expertise, emoji)\n"
                "- agent_feature: extra expertise or instructions for an existing agent such as Coder, Researcher, Finance, "
                "Designer (agent, add_expertise, add_instructions)\n"
                "- speedup: a change to Nyx's own code that would make it faster or better (title, description, target file "
                "if you know it, else empty)\n"
                "Only suggest what the facts justify; 2 to 6 suggestions.\n"
                'Reply with JSON only: {"headline": "one sentence", "learned": [{"code": "", "points": ["", ""]}], '
                '"suggestions": [{"kind": "", "title": "", "why": "", "spec": {}}], "next": ["", ""]}'),
                system="You write short, specific study reports. Reply with JSON only, no reasoning.", max_tokens=2600, force=True)
            data = json_from(reply or "")
            if isinstance(data, dict):
                report["written_by"] = "model"
                report["headline"] = str(data.get("headline") or report["headline"])[:300]
                points_by_code = {str(item.get("code", "")).upper(): [str(p)[:300] for p in (item.get("points") or [])][:6]
                                  for item in (data.get("learned") or []) if isinstance(item, dict)}
                for entry in report["learned"]:
                    if points_by_code.get(entry["code"]):
                        entry["points"] = points_by_code[entry["code"]]
                if isinstance(data.get("next"), list) and data["next"]:
                    report["next"] = [str(n)[:120] for n in data["next"][:4]]
                modelled = [self._suggestion(item) for item in (data.get("suggestions") or []) if isinstance(item, dict)]
                modelled = [s for s in modelled if s is not None]
                if modelled:
                    suggestions = modelled + [s for s in suggestions if s["kind"] in ("local_model", "dataset")]
        return report, suggestions

    # --- suggestions (R8) ---------------------------------------------------------------------------

    def _suggestion(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        kind = str(item.get("kind") or "").strip().lower()
        spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
        title = str(item.get("title") or spec.get("name") or "").strip()[:120]
        if kind not in ("skill", "agent", "agent_feature", "speedup") or not title:
            return None
        if kind == "skill" and not str(spec.get("instructions") or "").strip():
            return None
        if kind == "agent" and not (spec.get("name") and spec.get("goal")):
            return None
        if kind == "agent_feature" and not spec.get("agent"):
            return None
        return {"id": uuid.uuid4().hex[:8], "kind": kind, "title": title, "why": str(item.get("why") or "")[:400],
                "spec": {k: (v if isinstance(v, (str, int, float, bool)) else [str(x)[:80] for x in v][:12] if isinstance(v, list) else str(v))
                         for k, v in spec.items()},
                "state": "pending", "result": ""}

    def _suggest(self, run: Run, learned: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Without a model: a skill per well-covered topic, plus the dataset and the local model."""
        out: List[Dict[str, Any]] = []
        for entry in learned[:3]:
            if len(entry["points"]) < 3:
                continue
            instructions = (f"When a request is about {entry['topic'].lower()}, use what Nyx studied:\n"
                            + "\n".join(f"- {p}" for p in entry["points"][:8])
                            + "\nSay where a fact came from if the owner asks, and check anything time-sensitive.")
            out.append({"id": uuid.uuid4().hex[:8], "kind": "skill", "title": f"{entry['topic']} notes",
                        "why": f"{entry['docs']} documents about {entry['topic'].lower()} were read.",
                        "spec": {"name": f"{entry['topic']} notes", "description": f"What Nyx learned about {entry['topic'].lower()}",
                                 "instructions": instructions, "triggers": entry["terms"][:6]}, "state": "pending", "result": ""})
        if run.counts.get("examples"):
            out.append({"id": uuid.uuid4().hex[:8], "kind": "dataset", "title": "Save a fine-tuning set",
                        "why": f"{run.counts['examples']} question/answer pairs came out of this run.",
                        "spec": {"examples": run.counts["examples"]}, "state": "pending", "result": ""})
        if run.counts.get("facts", 0) >= 10:
            out.append({"id": uuid.uuid4().hex[:8], "kind": "local_model", "title": "Build a local model that knows this",
                        "why": "An Ollama model with these facts in its instructions answers from them offline.",
                        "spec": {"name": "nyx-absorbed", "base": "", "facts": min(60, run.counts["facts"])}, "state": "pending", "result": ""})
        return out

    def decide(self, run_id: str, suggestion_id: str, decision: str, by: str = "Owner") -> Dict[str, Any]:
        """Approve (apply it) or dismiss one suggestion. Only an owner action reaches this."""
        run = self.get(run_id)
        with run.lock:
            item = next((s for s in run.suggestions if s["id"] == suggestion_id), None)
            if item is None:
                raise AbsorbError("No such suggestion.")
            if item["state"] != "pending":
                raise AbsorbError(f"Already {item['state']}.")
        if decision == "dismiss":
            with run.lock:
                item["state"], item["result"] = "dismissed", "Dismissed"
        elif decision == "approve":
            try:
                result = self._apply(run, item, by)
                with run.lock:
                    item["state"], item["result"] = "applied", result
            except Exception as error:  # noqa: BLE001 - the box says why
                with run.lock:
                    item["state"], item["result"] = "failed", f"{type(error).__name__}: {str(error)[:200]}"
        else:
            raise AbsorbError("Approve or dismiss.")
        self._note(run, f"{item['title']}: {item['result']}")
        self._save(run, force=True)
        self._publish(run)
        return item

    def _apply(self, run: Run, item: Dict[str, Any], by: str) -> str:
        if item["kind"] == "dataset":
            path = self.export_dataset(run.id)
            return f"Saved {path.name} ({path.stat().st_size // 1024} KB) in the absorb exports folder."
        if item["kind"] == "local_model":
            return self._build_local_model(run, item.get("spec") or {})
        return apply_suggestion(item, by, origin=f"Data Absorption run {run.id}")

    def export_dataset(self, run_id: str) -> Path:
        """Question/answer pairs and facts from a run as chat-format JSONL (for fine-tuning a local model later)."""
        run = self.get(run_id)
        folder = self._dir() / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"absorb-{run.id}.jsonl"
        lines = []
        try:
            import nyx_core

            distill = nyx_core.CORE._path("distill.jsonl")
            for raw in distill.read_text(encoding="utf-8").splitlines()[-20000:]:
                record = json.loads(raw)
                if str(record.get("turn_id", "")).startswith(f"{REF_PREFIX}{run.id}:"):
                    lines.append({"messages": [{"role": "user", "content": record["prompt"]}, {"role": "assistant", "content": record["answer"]}]})
        except Exception:  # noqa: BLE001
            pass
        for row in run.dataset:
            lines.append({"messages": [{"role": "user", "content": f"What do you know about {row.get('topic', 'this')}?"},
                                       {"role": "assistant", "content": row["text"]}]})
        path.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in lines) + "\n", encoding="utf-8")
        return path

    def _build_local_model(self, run: Run, spec: Dict[str, Any]) -> str:
        import requests

        from config import SETTINGS

        host = (SETTINGS.ollama_host or "http://127.0.0.1:11434").replace("//localhost:", "//127.0.0.1:").rstrip("/")
        try:
            tags = requests.get(host + "/api/tags", timeout=2).json().get("models", [])
        except Exception as error:  # noqa: BLE001
            raise AbsorbError("Ollama is not running on this PC. Install it (Keys & Models → Local models) and try again.") from error
        names = [m.get("name", "") for m in tags if m.get("name")]
        base = str(spec.get("base") or "") or next((n for n in names if not n.startswith("nyx-")), "")
        if not base:
            raise AbsorbError("Ollama has no model to build on yet. Pull one in Keys & Models → Local models first.")
        facts = "\n".join(f"- {row['text'][:220]}" for row in run.dataset[-int(spec.get("facts") or 60):])
        system = ("You are Nyx, the owner's local assistant. Besides what you already know, you studied these facts "
                  f"({run.title}); use them when relevant:\n{facts}")
        name = re.sub(r"[^a-z0-9._-]", "-", str(spec.get("name") or "nyx-absorbed").lower())[:40]
        response = requests.post(host + "/api/create", json={"model": name, "from": base, "system": system[:30000], "stream": False}, timeout=300)
        if response.status_code != 200:
            raise AbsorbError(f"Ollama answered {response.status_code}: {response.text[:160]}")
        return f"Local model “{name}” built on {base} with {facts.count(chr(10)) + 1} facts. Pick it in Keys & Models."

    # --- logging / events -------------------------------------------------------------------------

    def _note(self, run: Run, text: str) -> None:
        with run.lock:
            run.log.append({"t": self._clock(), "text": str(text)[:300]})
            if len(run.log) > MAX_LOG:
                del run.log[: len(run.log) - MAX_LOG]
            run.seq += 1

    def _publish(self, run: Run) -> None:
        try:
            from agent_events import publish_ui

            publish_ui("absorb.update", run=run.summary())
        except Exception:  # noqa: BLE001
            pass

    # --- what every chat gets from it ------------------------------------------------------------------

    def knowledge_notes(self, message: str, limit: int = 3) -> str:
        """Facts from study runs (and Research's "Teach Nyx") that fit this message, for the turn's context."""
        if len((message or "").strip()) < 12 or not settings().get("use_in_chats", True):
            return ""
        try:
            memories = self._brain.recall(message, limit=8)
        except Exception:  # noqa: BLE001
            return ""
        picked = [m for m in memories if (str(m.get("ref", "")).startswith(REF_PREFIX) or m.get("kind") == "absorbed"
                                          or m.get("source") == "research") and float(m.get("score", 0)) >= 2.0][:limit]
        if not picked:
            return ""
        return ("From Nyx's own study sessions (use only if relevant; say it came from Nyx's reading):\n"
                + "\n".join(f"- {m['text'][:280]}" for m in picked))


def apply_suggestion(item: Dict[str, Any], by: str, origin: str = "") -> str:
    """Make one approved suggestion real: a skill, an agent, more for an agent, or a speed-up filed for review.

    Shared by Data Absorption reports and Data Process Use findings. It only runs from an owner's Approve click.
    """
    spec = item.get("spec") or {}
    kind = item.get("kind")
    if kind == "skill":
        from skills import SKILL_STORE

        triggers = spec.get("triggers") if isinstance(spec.get("triggers"), list) else str(spec.get("triggers") or "").split(",")
        skill = SKILL_STORE.add(str(spec.get("name") or item["title"])[:60], str(spec.get("description") or item.get("why") or "")[:300],
                                str(spec.get("instructions") or "")[:6000], triggers=[str(t) for t in triggers if str(t).strip()][:12],
                                source="conversation", author=f"Nyx · {origin or 'suggestion'} (approved by {by})", category="absorbed")
        return f"Skill “{skill.name}” added — Nyx uses it when a request matches."
    if kind == "agent":
        import agent_runtime

        return agent_runtime.tool_create_agent(str(spec.get("name"))[:40], str(spec.get("goal"))[:300],
                                               instructions=str(spec.get("instructions") or "")[:4000],
                                               expertise=str(spec.get("expertise") or "")[:600], emoji=str(spec.get("emoji") or "🤖")[:4])
    if kind == "agent_feature":
        import agent_runtime

        name = str(spec.get("agent") or "")
        current = agent_runtime.agent_properties(name) or {}
        if not current:
            raise AbsorbError(f"No agent called {name}.")
        changes: Dict[str, Any] = {}
        if spec.get("add_expertise"):
            existing = current.get("expertise", "")
            existing = ", ".join(existing) if isinstance(existing, list) else str(existing or "")
            changes["expertise"] = f"{existing}, {spec['add_expertise']}".strip(", ")[:600]
        if spec.get("add_instructions"):
            changes["instructions"] = f"{current.get('instructions', '')}\n{spec['add_instructions']}".strip()[:4000]
        if not changes:
            raise AbsorbError("Nothing to add.")
        agent_runtime.update_agent(name, changes)
        return f"{name} updated: " + " and ".join(changes) + " extended."
    if kind == "speedup":
        from change_review import CHANGE_LOG, ChangeOrigin

        change = CHANGE_LOG.propose(title=f"Improve {spec.get('target') or 'Nyx'}: {item['title']}"[:140],
                                    description=f"{spec.get('description') or item.get('why') or ''}\n\n(From {origin or 'a suggestion'}, filed by {by}.)",
                                    author="Nyx · suggestion", target=str(spec.get("target") or "base_ai"), origin=ChangeOrigin.AGENT)
        try:
            CHANGE_LOG.submit_for_review(change.change_id)
        except Exception:  # noqa: BLE001
            pass
        return "Filed in Improve → Review changes, where it is researched, tested and applied only after you approve it there."
    raise AbsorbError(f"Unknown kind {kind}.")


def _settings_path() -> Path:
    return data_path("absorb/settings.json")


def settings() -> Dict[str, Any]:
    try:
        return {"use_in_chats": True, **json.loads(_settings_path().read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return {"use_in_chats": True}


def save_settings(**changes: Any) -> Dict[str, Any]:
    current = settings()
    if "use_in_chats" in changes and changes["use_in_chats"] is not None:
        current["use_in_chats"] = bool(changes["use_in_chats"])
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current), encoding="utf-8")
    return current


ENGINE = AbsorbEngine()


# ---------------------------------------------------------------------------
# Tools (chat)
# ---------------------------------------------------------------------------


def tool_study(subject: str = "", links: str = "", minutes: int = 15) -> str:
    """Start a study run from chat: a subject (prompt mode) or links (given mode)."""
    urls = [u for u in re.split(r"[\s,]+", links or "") if u.startswith(("http://", "https://"))]
    try:
        if urls:
            live = ENGINE.start("given", links=urls, replace=False)
        elif subject.strip():
            live = ENGINE.start("prompt", prompt=subject, settings={"minutes": minutes}, replace=False)
        else:
            live = ENGINE.start("auto", settings={"minutes": minutes}, replace=False)
    except AbsorbError as error:
        return f"Not started: {error}"
    return (f"Started “{live['title']}” (run {live['id']}). Tell the owner they can watch it in the Data Absorption tab "
            "(or say “open the Data Absorption tab”) and stop it there.")


def tool_study_status() -> str:
    run = ENGINE.active()
    if run is None:
        latest = ENGINE.list()[:1]
        if not latest:
            return "No study runs yet."
        return f"No run going. Last: {latest[0]['title']} — {latest[0]['headline'] or latest[0]['status']}"
    live = ENGINE.live(run.id)
    top = sorted(live["topics"], key=lambda t: -t["count"])[:3]
    return (f"{live['title']}: {live['status']}, {live['counts']['indexed']} documents read, {live['counts']['facts']} facts kept; "
            f"busiest topics: " + ", ".join(f"{t['name']} ({t['count']})" for t in top))


def register_absorb_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="study",
        description=("Start a Data Absorption study run so Nyx learns: give a subject to study (it searches papers, GitHub, "
                     "Wikipedia and the web), or links to read, or nothing to let Nyx pick topics. It runs in the background "
                     "and the owner watches it in the Data Absorption tab."),
        parameters=[ToolParam("subject", "string", "What to study, e.g. 'options pricing' (empty = Nyx chooses)", required=False),
                    ToolParam("links", "string", "Links to read instead, separated by spaces", required=False),
                    ToolParam("minutes", "integer", "How long to study (default 15)", required=False)],
        handler=tool_study,
        category="learning",
    )
    registry.register(
        name="study_status",
        description="What the current or last Data Absorption study run is doing or found.",
        parameters=[],
        handler=tool_study_status,
        category="learning",
    )
