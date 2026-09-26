"""Nyx Core — Nyx's own model, which learns from every turn and leans on API models less over time.

The owner asked for "super learn": a main model that learns from each prompt and
search, starts small, gets bigger, and uses Gemini (or any key) "as a crutch"
while it improves, with a tab to watch it grow. Nyx Core is that main model. It
is not a large language model; it is the part of Nyx that is *genuinely trained
here, on this owner's use*, and it gets real work:

* **A growing neural network** (numpy MLP over hashed text features). Heads
  predict whether a request needs tools (route), which domain it belongs to
  (the brain's clusters) and which kinds of tools it will use. It starts with
  12 hidden neurons and *grows* — wider layers, then more layers — as it sees
  more turns, using function-preserving growth (new neurons copy existing ones
  and split their outgoing weights) so it never forgets by growing. Its
  predictions are scored *before* it trains on each turn, so the accuracy curve
  in the Learn tab is honest.
* **A word model** (trigram counts in SQLite) of how the owner writes, used for
  predictive text in the composer.
* **The crutch ledger** — which outside model answered which domain, how often
  it worked, how fast, and how the owner rated it — used to recommend models.
* **A distillation set** — every prompt/answer pair, rated when the owner rates
  it — ready to fine-tune a real local model when the owner wants one.

Everything adds up to a **level**: the count of learned parameters across the
network, word model, knowledge graph, learner, cache and dataset, from "Seed"
(a pocket calculator) to "Frontier" (a GPU server).
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

import numpy as np

from paths import data_path

_LOG = logging.getLogger("nyx.core")

INPUT_DIM = 2048
ROUTES = ["fast", "full"]
DOMAINS = ["chat", "web", "files", "code", "knowledge", "agents", "self-study", "email", "design", "system", "models", "voice"]
TOOL_KINDS = ["web", "files", "shell", "computer", "email", "apps", "system", "ui", "agents", "self", "media", "memory"]
MAX_WIDTH = 512
MAX_DEPTH = 4

LEVELS: List[Tuple[int, str, str]] = [
    (0, "Seed", "a pocket calculator"),
    (50_000, "Sprout", "a smartwatch"),
    (500_000, "Spark", "a phone assistant"),
    (5_000_000, "Mind", "a laptop model"),
    (50_000_000, "Deep", "a gaming PC"),
    (500_000_000, "Titan", "a workstation"),
    (5_000_000_000, "Frontier", "a high-end GPU server"),
]

_WORD = re.compile(r"[a-z0-9']+")


def tool_kind(name: str, category: str = "") -> Optional[str]:
    text = f"{name} {category}".lower()
    for kind, needles in (("web", ("web", "search", "fetch", "url", "browse")), ("email", ("email", "mail")),
                          ("files", ("file", "folder", "path", "document", "obsidian", "read_file")),
                          ("shell", ("command", "shell", "python", "run_")), ("computer", ("mouse", "keyboard", "screen", "window")),
                          ("apps", ("open_", "app", "youtube", "spotify")), ("system", ("system", "volume", "process", "power", "clipboard")),
                          ("ui", ("ui_", "tab", "theme", "design")), ("agents", ("agent", "delegate", "skill")),
                          ("self", ("improve", "self")), ("media", ("image", "voice", "speak", "vision")),
                          ("memory", ("brain", "memory", "remember", "recall"))):
        if any(n in text for n in needles):
            return kind
    return None


def domain_for(tools: Sequence[str], message: str = "") -> str:
    kinds = [k for k in (tool_kind(t) for t in tools) if k]
    mapping = {"web": "web", "files": "files", "shell": "code", "email": "email", "computer": "system", "apps": "system",
               "system": "system", "ui": "design", "agents": "agents", "self": "self-study", "media": "voice", "memory": "knowledge"}
    if kinds:
        return mapping[Counter(kinds).most_common(1)[0][0]]
    lower = (message or "").lower()
    if re.search(r"```|\bcode|\bpython|\bjavascript|\bfunction|\bbug|\berror\b", lower):
        return "code"
    if re.search(r"\bdesign|\blayout|\bui\b|\bcolou?r|\bcircuit|\b3d\b", lower):
        return "design"
    return "chat"


def features(text: str) -> Tuple[np.ndarray, np.ndarray]:
    """Hashed bag of words + bigrams → (indices, values) into INPUT_DIM, L2-normalised."""
    from learning import FeatureHasher

    raw = FeatureHasher().featurize(text or "")
    folded: Dict[int, float] = {}
    for bucket, value in raw.items():
        index = bucket % INPUT_DIM
        folded[index] = folded.get(index, 0.0) + value
    if not folded:
        folded = {0: 1.0}
    idx = np.fromiter(folded.keys(), dtype=np.int64)
    vals = np.fromiter(folded.values(), dtype=np.float64)
    norm = np.linalg.norm(vals) or 1.0
    return idx, vals / norm


class GrowingNet:
    """A small MLP that widens and deepens itself as it sees more examples."""

    def __init__(self, seed: int = 7) -> None:
        self.rng = np.random.default_rng(seed)
        self.layers: List[Dict[str, np.ndarray]] = []
        self.heads: Dict[str, Dict[str, np.ndarray]] = {}
        self.examples = 0
        self.growth_log: List[Dict[str, Any]] = []
        self.lr = 0.05
        self._add_layer(INPUT_DIM, 12)
        for name, size in (("route", len(ROUTES)), ("domain", len(DOMAINS)), ("tools", len(TOOL_KINDS))):
            self.heads[name] = {"W": self.rng.normal(0, 0.1, (size, 12)), "b": np.zeros(size)}

    # --- shape -------------------------------------------------------------------

    def _add_layer(self, fan_in: int, width: int) -> None:
        self.layers.append({"W": self.rng.normal(0, math.sqrt(2 / max(1, min(fan_in, 64))), (width, fan_in)), "b": np.zeros(width)})

    def widths(self) -> List[int]:
        return [layer["W"].shape[0] for layer in self.layers]

    def parameters(self) -> int:
        total = sum(layer["W"].size + layer["b"].size for layer in self.layers)
        return int(total + sum(head["W"].size + head["b"].size for head in self.heads.values()))

    def widen(self, k: int) -> None:
        """Function-preserving: new neurons copy random existing ones; outgoing weights are split between copies."""
        layer = self.layers[k]
        old = layer["W"].shape[0]
        new = min(MAX_WIDTH, old * 2)
        if new == old:
            return
        mapping = np.concatenate([np.arange(old), self.rng.integers(0, old, new - old)])
        counts = np.bincount(mapping, minlength=old).astype(float)
        noise = self.rng.normal(0, 1e-3, (new - old, layer["W"].shape[1]))
        layer["W"] = np.vstack([layer["W"], layer["W"][mapping[old:]] + noise])
        layer["b"] = np.concatenate([layer["b"], layer["b"][mapping[old:]]])
        outgoing = [self.layers[k + 1]] if k + 1 < len(self.layers) else list(self.heads.values())
        for target in outgoing:
            columns = target["W"][:, mapping] / counts[mapping]
            target["W"] = columns
        self.growth_log.append({"ts": time.time(), "event": f"layer {k + 1} grew {old} → {new} neurons", "examples": self.examples})

    def deepen(self) -> None:
        """Add a hidden layer that starts as the identity (ReLU of a non-negative input is itself)."""
        width = self.layers[-1]["W"].shape[0]
        self.layers.append({"W": np.eye(width) + self.rng.normal(0, 1e-3, (width, width)), "b": np.zeros(width)})
        self.growth_log.append({"ts": time.time(), "event": f"added layer {len(self.layers)} ({width} neurons)", "examples": self.examples})

    def maybe_grow(self) -> Optional[str]:
        widths = self.widths()
        smallest = int(np.argmin(widths))
        if self.examples >= 4 * sum(widths) and widths[smallest] < MAX_WIDTH:
            self.widen(smallest)
            return self.growth_log[-1]["event"]
        if len(self.layers) < MAX_DEPTH and min(widths) >= 128 * len(self.layers) and self.examples >= 12 * sum(widths):
            self.deepen()
            return self.growth_log[-1]["event"]
        return None

    # --- learning ----------------------------------------------------------------

    def forward(self, idx: np.ndarray, vals: np.ndarray) -> Tuple[List[np.ndarray], Dict[str, np.ndarray]]:
        activations = []
        first = self.layers[0]
        h = np.maximum(0.0, first["W"][:, idx] @ vals + first["b"])
        activations.append(h)
        for layer in self.layers[1:]:
            h = np.maximum(0.0, layer["W"] @ h + layer["b"])
            activations.append(h)
        outputs = {}
        for name, head in self.heads.items():
            logits = head["W"] @ h + head["b"]
            if name == "tools":
                outputs[name] = 1 / (1 + np.exp(-np.clip(logits, -30, 30)))
            else:
                shifted = np.exp(logits - logits.max())
                outputs[name] = shifted / shifted.sum()
        return activations, outputs

    def predict(self, text: str) -> Dict[str, Any]:
        idx, vals = features(text)
        _, out = self.forward(idx, vals)
        return {"route": ROUTES[int(np.argmax(out["route"]))], "route_p": float(out["route"].max()),
                "domain": DOMAINS[int(np.argmax(out["domain"]))], "domain_p": float(out["domain"].max()),
                "tools": [TOOL_KINDS[i] for i, p in enumerate(out["tools"]) if p >= 0.5],
                "tool_p": {TOOL_KINDS[i]: round(float(p), 3) for i, p in enumerate(out["tools"])}}

    def learn(self, idx: np.ndarray, vals: np.ndarray, route: int, domain: int, tools: Sequence[int], weight: float = 1.0) -> float:
        activations, out = self.forward(idx, vals)
        h_last = activations[-1]
        targets = {"route": np.eye(len(ROUTES))[route], "domain": np.eye(len(DOMAINS))[domain],
                   "tools": np.zeros(len(TOOL_KINDS))}
        for t in tools:
            targets["tools"][t] = 1.0
        loss = float(-np.log(out["route"][route] + 1e-9) - np.log(out["domain"][domain] + 1e-9)
                     - np.sum(targets["tools"] * np.log(out["tools"] + 1e-9) + (1 - targets["tools"]) * np.log(1 - out["tools"] + 1e-9)) / len(TOOL_KINDS))
        grad_h = np.zeros_like(h_last)
        lr = self.lr * weight
        for name, head in self.heads.items():
            delta = (out[name] - targets[name]) * (1.0 if name != "tools" else 0.5)
            grad_h += head["W"].T @ delta
            head["W"] -= lr * np.clip(np.outer(delta, h_last), -1, 1)
            head["b"] -= lr * delta
        for k in range(len(self.layers) - 1, -1, -1):
            layer = self.layers[k]
            grad_z = grad_h * (activations[k] > 0)
            if k == 0:
                layer["W"][:, idx] -= lr * np.clip(np.outer(grad_z, vals), -1, 1)
            else:
                grad_h = layer["W"].T @ grad_z
                layer["W"] -= lr * np.clip(np.outer(grad_z, activations[k - 1]), -1, 1)
            layer["b"] -= lr * grad_z
            layer["W"] *= (1 - 1e-6)
        return loss

    # --- persistence ---------------------------------------------------------------

    def to_arrays(self) -> Dict[str, np.ndarray]:
        arrays: Dict[str, np.ndarray] = {"examples": np.array([self.examples])}
        for i, layer in enumerate(self.layers):
            arrays[f"L{i}_W"], arrays[f"L{i}_b"] = layer["W"], layer["b"]
        for name, head in self.heads.items():
            arrays[f"H_{name}_W"], arrays[f"H_{name}_b"] = head["W"], head["b"]
        return arrays

    @classmethod
    def from_arrays(cls, arrays: Any) -> "GrowingNet":
        net = cls()
        net.layers = []
        i = 0
        while f"L{i}_W" in arrays:
            net.layers.append({"W": np.array(arrays[f"L{i}_W"]), "b": np.array(arrays[f"L{i}_b"])})
            i += 1
        for name in list(net.heads):
            net.heads[name] = {"W": np.array(arrays[f"H_{name}_W"]), "b": np.array(arrays[f"H_{name}_b"])}
        net.examples = int(arrays["examples"][0])
        return net


class NyxCore:
    def __init__(self, directory: Optional[Path] = None) -> None:
        self._dir = directory
        self._lock = threading.RLock()
        self._net: Optional[GrowingNet] = None
        self._db: Optional[sqlite3.Connection] = None
        self._state: Dict[str, Any] = {}
        self._replay: Deque[Tuple[np.ndarray, np.ndarray, int, int, List[int]]] = deque(maxlen=256)
        self._last_save = 0.0
        self._last_snapshot = 0.0

    # --- storage ----------------------------------------------------------------------

    def _path(self, name: str) -> Path:
        base = self._dir or data_path("brain")
        base.mkdir(parents=True, exist_ok=True)
        return base / name

    def _ensure(self) -> None:
        if self._net is not None:
            return
        try:
            with np.load(self._path("core_weights.npz")) as arrays:
                self._net = GrowingNet.from_arrays(arrays)
        except (OSError, KeyError, ValueError):
            self._net = GrowingNet()
        try:
            self._state = json.loads(self._path("core_state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._state = {}
        self._state.setdefault("route_hits", [])
        self._state.setdefault("domain_hits", [])
        self._state.setdefault("ledger", {})
        self._state.setdefault("local_answers", 0)
        self._state.setdefault("api_answers", 0)
        self._state.setdefault("daily", {})
        self._state.setdefault("growth_log", [])
        self._state.setdefault("recent_loss", [])
        self._state.setdefault("distill_count", 0)
        self._net.growth_log = list(self._state["growth_log"])
        db = sqlite3.connect(str(self._path("core.db")), check_same_thread=False, timeout=30)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS ngrams (ctx TEXT, next TEXT, n INTEGER, PRIMARY KEY (ctx, next)) WITHOUT ROWID")
        self._db = db

    def _save(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_save < 10:
            return
        self._last_save = now
        assert self._net is not None
        tmp = self._path("core_weights.tmp.npz")
        np.savez_compressed(tmp, **self._net.to_arrays())
        tmp.replace(self._path("core_weights.npz"))
        self._state["growth_log"] = self._net.growth_log[-100:]
        self._path("core_state.json").write_text(json.dumps(self._state), encoding="utf-8")

    # --- learning from turns -------------------------------------------------------------

    def observe_turn(self, *, turn_id: str, message: str, reply: str, mode: str, escalated: bool, provider: str,
                     model: str, tools: Sequence[str], ok: bool, latency_ms: float, from_cache: bool = False) -> Dict[str, Any]:
        with self._lock:
            self._ensure()
            net = self._net
            assert net is not None
            idx, vals = features(message)
            route = 0 if mode == "fast" and not escalated else 1
            domain = DOMAINS.index(domain_for(tools, message))
            tool_ids = sorted({TOOL_KINDS.index(k) for k in (tool_kind(t) for t in tools) if k})
            guess = net.predict(message)
            self._state["route_hits"] = (self._state["route_hits"] + [int(guess["route"] == ROUTES[route])])[-300:]
            self._state["domain_hits"] = (self._state["domain_hits"] + [int(guess["domain"] == DOMAINS[domain])])[-300:]
            loss = net.learn(idx, vals, route, domain, tool_ids)
            self._replay.append((idx, vals, route, domain, tool_ids))
            for sample in list(self._replay)[-8:-1]:
                net.learn(*sample, weight=0.3)
            net.examples += 1
            self._state["recent_loss"] = (self._state["recent_loss"] + [round(loss, 4)])[-300:]
            grew = net.maybe_grow()

            key = "local" if from_cache or provider.startswith(("cache", "offline", "nyx")) else "api"
            self._state["local_answers" if key == "local" else "api_answers"] += 1
            day = time.strftime("%Y-%m-%d")
            daily = self._state["daily"].setdefault(day, {"local": 0, "api": 0, "turns": 0})
            daily[key] += 1
            daily["turns"] += 1
            if len(self._state["daily"]) > 120:
                for old in sorted(self._state["daily"])[:-120]:
                    self._state["daily"].pop(old, None)
            if key == "api" and provider:
                entry = self._state["ledger"].setdefault(f"{DOMAINS[domain]}|{provider}|{model}", {"n": 0, "ok": 0, "ms": 0.0, "rating": 0})
                entry["n"] += 1
                entry["ok"] += int(bool(ok))
                entry["ms"] += float(latency_ms or 0)

            self._learn_words(message)
            if reply and key == "api":
                self._append_distill({"ts": time.time(), "turn_id": turn_id, "prompt": message[:4000], "answer": reply[:8000],
                                      "provider": provider, "model": model, "domain": DOMAINS[domain], "tools": list(tools)})
            self._maybe_snapshot()
            self._save(force=bool(grew))
        if grew:
            try:
                from agent_events import publish_ui

                publish_ui("core.grew", event=grew, widths=self._net.widths(), parameters=self._net.parameters())
            except Exception:
                pass
        return {"guess": guess, "loss": loss, "grew": grew}

    def feedback(self, turn_id: str, rating: int) -> None:
        """A 👍/👎 marks the distillation example and moves the crutch ledger."""
        path = self._path("distill.jsonl")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        changed = False
        for i in range(len(lines) - 1, max(-1, len(lines) - 400), -1):
            try:
                record = json.loads(lines[i])
            except ValueError:
                continue
            if record.get("turn_id") == turn_id:
                record["rating"] = int(rating)
                lines[i] = json.dumps(record, ensure_ascii=False)
                with self._lock:
                    self._ensure()
                    entry = self._state["ledger"].get(f"{record.get('domain')}|{record.get('provider')}|{record.get('model')}")
                    if entry:
                        entry["rating"] += int(rating)
                    self._save(force=True)
                changed = True
                break
        if changed:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _append_distill(self, record: Dict[str, Any]) -> None:
        path = self._path("distill.jsonl")
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._state["distill_count"] = int(self._state.get("distill_count", 0)) + 1
        if self._state["distill_count"] % 500 == 0:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > 20000:
                path.write_text("\n".join(lines[-20000:]) + "\n", encoding="utf-8")
                self._state["distill_count"] = 20000

    def _learn_words(self, text: str) -> None:
        assert self._db is not None
        words = _WORD.findall((text or "").lower())[:200]
        if len(words) < 2:
            return
        rows = []
        padded = ["^", "^"] + words
        for a, b, c in zip(padded, padded[1:], padded[2:]):
            rows.append((f"{a} {b}", c))
            rows.append((b, c))
        with self._db:
            self._db.executemany("INSERT INTO ngrams(ctx, next, n) VALUES (?, ?, 1) ON CONFLICT(ctx, next) DO UPDATE SET n = n + 1", rows)

    # --- using what it learned ---------------------------------------------------------

    def predict(self, message: str) -> Dict[str, Any]:
        with self._lock:
            self._ensure()
            assert self._net is not None
            return self._net.predict(message)

    def complete(self, prefix: str, limit: int = 3) -> List[str]:
        """Next words the owner is likely to type (predictive text)."""
        with self._lock:
            self._ensure()
            assert self._db is not None
            words = _WORD.findall((prefix or "").lower())
            if prefix and not prefix[-1].isspace() and words:
                partial, words = words[-1], words[:-1]
            else:
                partial = ""
            padded = ["^", "^"] + words
            suggestions: List[str] = []
            for ctx in (f"{padded[-2]} {padded[-1]}", padded[-1]):
                rows = self._db.execute("SELECT next, n FROM ngrams WHERE ctx=? AND next LIKE ? ORDER BY n DESC LIMIT ?",
                                        (ctx, f"{partial}%", limit * 2)).fetchall()
                for word, _n in rows:
                    if word not in suggestions and word != partial:
                        suggestions.append(word)
                if len(suggestions) >= limit:
                    break
            return suggestions[:limit]

    def recommend_model(self, message: str) -> Optional[Dict[str, Any]]:
        """The outside model that has done best on requests like this one (needs evidence)."""
        domain = self.predict(message)["domain"]
        best = None
        with self._lock:
            for key, entry in self._state["ledger"].items():
                d, provider, model = key.split("|", 2)
                if d != domain or entry["n"] < 3:
                    continue
                success = (entry["ok"] + 1) / (entry["n"] + 2) + 0.05 * math.tanh(entry["rating"] / 3)
                speed = 1 / (1 + (entry["ms"] / entry["n"]) / 10000)
                score = success * 0.8 + speed * 0.2
                if best is None or score > best["score"]:
                    best = {"provider": provider, "model": model, "domain": domain, "score": round(score, 3), "turns": entry["n"]}
        return best

    # --- progress ------------------------------------------------------------------------

    def parameters(self) -> Dict[str, int]:
        with self._lock:
            self._ensure()
            assert self._net is not None and self._db is not None
            words = self._db.execute("SELECT COUNT(*) FROM ngrams").fetchone()[0]
            parts = {"neural_network": self._net.parameters(), "word_model": int(words),
                     "distillation_examples": int(self._state.get("distill_count", 0))}
        try:
            import super_brain

            counts = super_brain.BRAIN.counts()
            parts["knowledge_graph"] = int(counts["nodes"] + counts["edges"])
        except Exception:
            parts["knowledge_graph"] = 0
        try:
            from learning import LEARNER

            models = LEARNER.stats().get("models", {})
            parts["learner"] = int(sum(int(m.get("weights", 0) or 0) for m in models.values() if isinstance(m, dict)))
        except Exception:
            parts["learner"] = 0
        try:
            from response_cache import RESPONSE_CACHE

            parts["answer_memory"] = int(RESPONSE_CACHE.stats().get("entries", 0))
        except Exception:
            parts["answer_memory"] = 0
        return parts

    @staticmethod
    def level_for(total: int) -> Dict[str, Any]:
        index = max(i for i, (threshold, _, _) in enumerate(LEVELS) if total >= threshold)
        threshold, name, like = LEVELS[index]
        nxt = LEVELS[index + 1] if index + 1 < len(LEVELS) else None
        progress = 1.0 if nxt is None else (math.log10(max(total, 1)) - math.log10(max(threshold, 1))) / (math.log10(nxt[0]) - math.log10(max(threshold, 1)))
        return {"level": index + 1, "name": name, "like": like, "parameters": total, "next_name": nxt[1] if nxt else None,
                "next_at": nxt[0] if nxt else None, "progress": round(max(0.0, min(1.0, progress)), 4)}

    def _maybe_snapshot(self) -> None:
        now = time.time()
        if now - self._last_snapshot < 1800:
            return
        self._last_snapshot = now
        try:
            snap = {"ts": now, "parameters": sum(self.parameters().values()), "widths": self._net.widths() if self._net else [],
                    "examples": self._net.examples if self._net else 0, "route_accuracy": _mean(self._state["route_hits"][-100:]),
                    "domain_accuracy": _mean(self._state["domain_hits"][-100:])}
            with open(self._path("growth.jsonl"), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(snap) + "\n")
        except Exception:
            pass

    def snapshot(self) -> Dict[str, Any]:
        parts = self.parameters()
        total = sum(parts.values())
        with self._lock:
            net = self._net
            assert net is not None
            local, api = int(self._state["local_answers"]), int(self._state["api_answers"])
            ledger = sorted(({"domain": k.split("|")[0], "provider": k.split("|")[1], "model": k.split("|", 2)[2], **v,
                              "avg_ms": round(v["ms"] / v["n"]) if v["n"] else 0} for k, v in self._state["ledger"].items()),
                            key=lambda e: -e["n"])[:30]
            route_hits, domain_hits = list(self._state["route_hits"]), list(self._state["domain_hits"])
            state = {"examples": net.examples, "widths": net.widths(), "depth": len(net.layers),
                     "network_parameters": net.parameters(), "growth_log": net.growth_log[-20:],
                     "loss": self._state["recent_loss"][-120:], "daily": dict(sorted(self._state["daily"].items())[-30:])}
        try:
            history = [json.loads(line) for line in self._path("growth.jsonl").read_text(encoding="utf-8").splitlines()[-200:]]
        except (OSError, ValueError):
            history = []
        return {**self.level_for(total), "parts": parts, **state,
                "route_accuracy": _mean(route_hits[-100:]), "domain_accuracy": _mean(domain_hits[-100:]),
                "accuracy_curve": _rolling(domain_hits, 20), "independence": round(local / (local + api), 4) if local + api else 0.0,
                "local_answers": local, "api_answers": api, "crutches": ledger, "history": history}

    def network_view(self, sample: int = 24, text: str = "") -> Dict[str, Any]:
        """A drawable slice of the real network: layer sizes, strongest weights, and activations for ``text``."""
        with self._lock:
            self._ensure()
            net = self._net
            assert net is not None
            idx, vals = features(text or "hello")
            activations, outputs = net.forward(idx, vals)
            layers = [{"name": "input", "size": INPUT_DIM, "active": [int(i) for i in idx[:sample]]}]
            for k, layer in enumerate(net.layers):
                act = activations[k]
                top = np.argsort(-act)[:sample]
                layers.append({"name": f"hidden {k + 1}", "size": int(layer["W"].shape[0]),
                               "activation": [round(float(act[i]), 4) for i in top], "neurons": [int(i) for i in top]})
            links = []
            first = net.layers[0]["W"]
            for n_out in layers[1]["neurons"][:sample]:
                row = first[n_out, idx]
                for j in np.argsort(-np.abs(row))[:3]:
                    links.append({"from": ["input", int(idx[j])], "to": ["hidden 1", int(n_out)], "w": round(float(row[j]), 4)})
            for k in range(1, len(net.layers)):
                W = net.layers[k]["W"]
                for n_out in layers[k + 1]["neurons"][:sample]:
                    for j in layers[k]["neurons"][:6]:
                        links.append({"from": [f"hidden {k}", int(j)], "to": [f"hidden {k + 1}", int(n_out)], "w": round(float(W[n_out, j]), 4)})
            heads = {name: {"labels": labels, "values": [round(float(v), 4) for v in outputs[name]]}
                     for name, labels in (("route", ROUTES), ("domain", DOMAINS), ("tools", TOOL_KINDS))}
        return {"layers": layers, "links": links, "heads": heads, "parameters": net.parameters(), "examples": net.examples}

    def bootstrap_from_history(self, limit: int = 2000) -> int:
        """First run: learn from the turns the learner already recorded, so the core does not start blank."""
        with self._lock:
            self._ensure()
            if self._net and self._net.examples:
                return 0
        try:
            lines = data_path("learning/turns.jsonl").read_text(encoding="utf-8").splitlines()[-limit:]
        except OSError:
            return 0
        count = 0
        for line in lines:
            try:
                t = json.loads(line)
            except ValueError:
                continue
            self.observe_turn(turn_id=t.get("turn_id", ""), message=t.get("message", ""), reply="", mode=t.get("mode", "full"),
                              escalated=bool(t.get("escalated")), provider=t.get("provider", ""), model=t.get("model", ""),
                              tools=t.get("tools") or [], ok=bool(t.get("ok", True)), latency_ms=float(t.get("latency_ms") or 0))
            count += 1
        with self._lock:
            self._save(force=True)
        return count


def _mean(values: Sequence[int]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def _rolling(values: Sequence[int], window: int) -> List[float]:
    out = []
    for i in range(window, len(values) + 1, max(1, window // 4)):
        chunk = values[i - window:i]
        out.append(round(sum(chunk) / len(chunk), 3))
    return out[-60:]


CORE = NyxCore()

_work: "Deque[Dict[str, Any]]" = deque(maxlen=500)
_work_event = threading.Event()
_worker: Optional[threading.Thread] = None


def observe_async(**turn: Any) -> None:
    """Learn from a turn on a background thread, so saving weights never delays a reply."""
    global _worker
    _work.append(turn)
    _work_event.set()
    if _worker is None or not _worker.is_alive():
        def run() -> None:
            while True:
                if not _work_event.wait(timeout=30):
                    return
                _work_event.clear()
                while _work:
                    item = _work.popleft()
                    try:
                        CORE.observe_turn(**item)
                    except Exception:  # noqa: BLE001 - learning never breaks anything else
                        _LOG.exception("core observe failed")

        _worker = threading.Thread(target=run, name="nyx-core-learner", daemon=True)
        _worker.start()
