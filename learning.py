"""Real, local, explainable machine learning for Nyx (OVERHAUL_CONTRACTS.md round 2).

The owner asked for the AI to actually learn, not to print a "learning" label
over a static prompt. Everything here is auditable: a hashed bag-of-words
feature space, a multinomial logistic regression trained with plain sparse SGD
+ AdaGrad, and Beta-distribution success rates for providers. No embeddings
API, no background training job, no opaque state — every prediction can be
traced back to "these tokens, these weights, this softmax".

Four models share the same hashed feature space (``FeatureHasher``):

* ``route``      — should this turn take the fast or full pipeline.
* ``agent``      — which specialist tends to succeed on messages like this.
* ``skill``      — one binary yes/no classifier per skill id (a skill is not
  mutually exclusive with any other, so it cannot share one softmax the way
  route/agent do).
* ``provider``   — not a classifier at all: a smoothed Beta(alpha, beta)
  success rate plus mean latency per provider/model, combined into a small
  bandit-style score (``suggest``'s ``provider_ranking``).

Everything is learned from outcomes the app already produces (turn summaries
and 👍/👎 feedback) — never from a separate labelled dataset, and never
uploaded anywhere. ``LEARNER`` is the singleton the rest of the app uses;
``learning_hooks.py`` is the only thing the turn loop actually calls.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from paths import atomic_replace, data_path

_LOG = logging.getLogger("nyx.learning")

# ---------------------------------------------------------------------------
# Feature hashing
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")
_URL_RE = re.compile(r"https?://|www\.", re.IGNORECASE)
_CODE_RE = re.compile(r"```|\bdef\s|\bclass\s|=>|;\s*$|\bimport\s", re.MULTILINE)
_MAX_TOKENS = 400


def _length_bucket(chars: int) -> str:
    """Coarse length bucket shared by the hasher's meta-feature and style votes."""
    if chars < 200:
        return "short"
    if chars < 800:
        return "medium"
    return "long"


class FeatureHasher:
    """Turn free text into a fixed-width sparse vector, no vocabulary required.

    Every token maps into one of ``NUM_BUCKETS`` buckets via a stable hash, with
    a sign bit so unrelated tokens that collide into the same bucket partially
    cancel instead of always reinforcing (the standard hashing-trick
    construction, e.g. scikit-learn's ``FeatureHasher``).

    Uses ``hashlib.blake2b`` rather than Python's builtin ``hash()`` on
    purpose: ``hash()`` is salted per-process (``PYTHONHASHSEED``) for
    security, which is exactly wrong here — a model persisted to disk must
    land on the *same* buckets after a restart, or every saved weight points
    at the wrong dimension.
    """

    NUM_BUCKETS = 1 << 18  # 262,144 — large enough that collisions stay rare
                           # for a single-user vocabulary, small enough that a
                           # dense sweep over labels stays cheap.

    def token_bucket(self, token: str) -> Tuple[int, float]:
        """The (bucket, sign) a token hashes to. Exposed so it can be pinned in a test."""
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        bucket = value % self.NUM_BUCKETS
        sign = 1.0 if (value // self.NUM_BUCKETS) % 2 == 0 else -1.0
        return bucket, sign

    def _add(self, features: Dict[int, float], token: str, weight: float = 1.0) -> None:
        bucket, sign = self.token_bucket(token)
        features[bucket] = features.get(bucket, 0.0) + sign * weight

    def featurize(self, text: str, *, attachment_kinds: Sequence[str] = ()) -> Dict[int, float]:
        """Tokens + bigrams + a few cheap meta features, all hashed into one vector."""
        text = text or ""
        tokens = _WORD_RE.findall(text.lower())[:_MAX_TOKENS]
        features: Dict[int, float] = {}
        for token in tokens:
            self._add(features, f"w:{token}")
        for left, right in zip(tokens, tokens[1:]):
            self._add(features, f"b:{left}_{right}", 0.5)

        self._add(features, f"meta:len_{_length_bucket(len(text))}")
        if _CODE_RE.search(text):
            self._add(features, "meta:has_code")
        if "?" in text:
            self._add(features, "meta:has_question")
        if _URL_RE.search(text):
            self._add(features, "meta:has_url")
        for kind in attachment_kinds or ():
            self._add(features, f"meta:attach_{kind}")
        return features


# ---------------------------------------------------------------------------
# Online multinomial logistic regression (sparse SGD + AdaGrad)
# ---------------------------------------------------------------------------

_L2 = 1e-4
_LEARNING_RATE = 0.15
_ADAGRAD_EPS = 1e-8
_PRUNE_THRESHOLD = 1e-4
_MAX_WEIGHTS_PER_LABEL = 20_000


class OnlineSoftmax:
    """Multinomial logistic regression, trained one example at a time.

    ``predict_proba`` is a plain softmax over per-label linear scores;
    ``learn`` is one AdaGrad-scaled gradient step per observation, with L2
    shrinkage so a label seen only once does not leave a handful of huge
    weights behind. Labels are discovered as they are seen — there is no fixed
    schema to migrate when a new specialist or skill first appears.

    Only non-zero weights are kept: a weight that decays under the prune
    threshold is dropped rather than stored as a near-zero float, which is
    what keeps ``models.json`` small after months of use.
    """

    def __init__(self) -> None:
        self.labels: List[str] = []
        self.weights: Dict[str, Dict[int, float]] = {}
        self.bias: Dict[str, float] = {}
        self.updates = 0
        self._accum_w: Dict[str, Dict[int, float]] = {}
        self._accum_b: Dict[str, float] = {}

    def _ensure_label(self, label: str) -> None:
        if label in self.weights:
            return
        self.labels.append(label)
        self.weights[label] = {}
        self.bias[label] = 0.0
        self._accum_w[label] = {}
        self._accum_b[label] = 0.0

    def scores(self, features: Dict[int, float]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for label in self.labels:
            weights = self.weights[label]
            total = self.bias.get(label, 0.0)
            for bucket, value in features.items():
                w = weights.get(bucket)
                if w:
                    total += w * value
            out[label] = total
        return out

    def predict_proba(self, features: Dict[int, float]) -> Dict[str, float]:
        """A softmax over the current scores, or ``{}`` before any label exists."""
        if not self.labels:
            return {}
        raw = self.scores(features)
        peak = max(raw.values())
        exps = {label: math.exp(score - peak) for label, score in raw.items()}
        total = sum(exps.values()) or 1.0
        return {label: value / total for label, value in exps.items()}

    def learn(self, features: Dict[int, float], label: str, weight: float = 1.0) -> None:
        """One SGD step toward ``label`` given ``features``, scaled by AdaGrad."""
        if not features or not label or weight <= 0:
            return
        self._ensure_label(label)
        probs = self.predict_proba(features)
        self.updates += 1
        for candidate in self.labels:
            target = 1.0 if candidate == label else 0.0
            grad_out = (probs.get(candidate, 0.0) - target) * weight
            if grad_out == 0.0:
                continue
            self._step(candidate, features, grad_out)

    def _step(self, label: str, features: Dict[int, float], grad_out: float) -> None:
        w = self.weights[label]
        accum = self._accum_w[label]
        for bucket, value in features.items():
            grad = grad_out * value + _L2 * w.get(bucket, 0.0)
            accum[bucket] = accum.get(bucket, 0.0) + grad * grad
            step = _LEARNING_RATE / (math.sqrt(accum[bucket]) + _ADAGRAD_EPS)
            new_w = w.get(bucket, 0.0) - step * grad
            if abs(new_w) < _PRUNE_THRESHOLD:
                w.pop(bucket, None)
            else:
                w[bucket] = new_w
        if len(w) > _MAX_WEIGHTS_PER_LABEL:
            kept = sorted(w.items(), key=lambda kv: abs(kv[1]), reverse=True)[:_MAX_WEIGHTS_PER_LABEL]
            self.weights[label] = dict(kept)

        b_grad = grad_out
        self._accum_b[label] = self._accum_b.get(label, 0.0) + b_grad * b_grad
        b_step = _LEARNING_RATE / (math.sqrt(self._accum_b[label]) + _ADAGRAD_EPS)
        self.bias[label] = self.bias.get(label, 0.0) - b_step * b_grad

    def seed_labels(self, *labels: str) -> None:
        """Register labels with zero weight so they are real competitors from
        the first update, rather than the trivial single-class case: with only
        one label, ``predict_proba`` always returns probability 1.0 for it
        exactly, so ``learn``'s gradient (``prob - target``) is always exactly
        zero and no weight ever moves. Anything with a known, fixed label set
        decided in advance (the route model's fast/full) should call this up
        front; the open-ended ones (agent, skill) discover their labels purely
        from ``learn`` instead, which is correct for them.
        """
        for label in labels:
            self._ensure_label(label)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "labels": list(self.labels),
            "weights": {label: {str(b): v for b, v in w.items()} for label, w in self.weights.items()},
            "bias": dict(self.bias),
            "updates": self.updates,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "OnlineSoftmax":
        model = cls()
        data = data or {}
        model.labels = list(data.get("labels", []))
        raw_weights = data.get("weights", {})
        model.weights = {
            label: {int(bucket): float(value) for bucket, value in weights.items()}
            for label, weights in raw_weights.items()
        }
        model.bias = {label: float(value) for label, value in data.get("bias", {}).items()}
        model.updates = int(data.get("updates", 0))
        # AdaGrad accumulators are not persisted (they would roughly double the
        # file size for no behavioural benefit); a restart simply gives the next
        # few updates after load a fresh effective learning rate.
        for label in model.labels:
            model.weights.setdefault(label, {})
            model.bias.setdefault(label, 0.0)
            model._accum_w[label] = {}
            model._accum_b[label] = 0.0
        return model


class OneVsRestBinary:
    """Independent yes/no classifiers, one per item id (skills are not exclusive).

    Each item gets its own two-label ``OnlineSoftmax`` ("yes" vs "no"), which
    reuses the exact same sparse-SGD mechanics as route/agent — this is what
    makes it genuinely one-vs-rest rather than a single softmax pretending
    several labels can't co-occur.
    """

    YES = "yes"
    NO = "no"

    def __init__(self) -> None:
        self.models: Dict[str, OnlineSoftmax] = {}

    def ids(self) -> List[str]:
        return list(self.models.keys())

    def _model(self, item_id: str) -> OnlineSoftmax:
        model = self.models.get(item_id)
        if model is None:
            model = OnlineSoftmax()
            self.models[item_id] = model
        return model

    def learn(self, item_id: str, features: Dict[int, float], positive: bool, weight: float = 1.0) -> None:
        self._model(item_id).learn(features, self.YES if positive else self.NO, weight=weight)

    def predict_proba(self, item_id: str, features: Dict[int, float]) -> float:
        model = self.models.get(item_id)
        if model is None:
            return 0.0
        return model.predict_proba(features).get(self.YES, 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {item_id: model.to_dict() for item_id, model in self.models.items()}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "OneVsRestBinary":
        instance = cls()
        for item_id, payload in (data or {}).items():
            instance.models[item_id] = OnlineSoftmax.from_dict(payload)
        return instance


# ---------------------------------------------------------------------------
# Provider satisfaction — a Beta(alpha, beta) success rate, not a classifier
# ---------------------------------------------------------------------------


@dataclass
class _ProviderStat:
    alpha: float = 1.0  # Beta prior: starts at (1, 1), i.e. "50/50, no evidence".
    beta: float = 1.0
    latency_sum: float = 0.0
    latency_n: int = 0
    n: int = 0

    @property
    def success_rate(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def mean_latency_ms(self) -> float:
        return self.latency_sum / self.latency_n if self.latency_n else 0.0

    def score(self) -> float:
        """A bandit-style ranking score: success rate, an optimism bonus that
        shrinks as evidence accumulates (so a provider tried only once or twice
        is not permanently buried by an early bad sample), minus a mild latency
        penalty. Deterministic on purpose — this ranks options for a suggestion
        the owner can see, not a live traffic-splitting decision, so there is no
        need for the randomness real Thompson sampling would add.
        """
        total = self.alpha + self.beta
        exploration_bonus = 0.5 / total
        latency_penalty = min(self.mean_latency_ms / 20_000.0, 0.2)
        return self.success_rate + exploration_bonus - latency_penalty


def _provider_key(provider: str, model: str) -> str:
    return f"{provider}::{model or ''}"


# ---------------------------------------------------------------------------
# Turn summaries
# ---------------------------------------------------------------------------


@dataclass
class TurnSummary:
    """What one completed turn taught the learner. Built by the Lead in
    ``turn_runner.py`` and handed to ``learning_hooks.after_turn``.

    ``reply_has_bullets``/``reply_has_code`` are optional and not part of what
    the Lead needs to fill in — ``learning_hooks.after_turn`` derives them from
    the reply text itself (which reaches the hook as a separate argument, not
    through this dataclass) and attaches them before calling ``observe_turn``.
    They exist here, rather than as a separate parameter, so the whole
    per-turn record is one object.
    """

    turn_id: str
    chat_id: str
    message: str
    mode: str  # "fast" | "full"
    escalated: bool
    provider: str
    model: str
    agents: List[str] = field(default_factory=list)
    skills: List[str] = field(default_factory=list)
    tools: List[str] = field(default_factory=list)
    latency_ms: float = 0.0
    ok: bool = True
    reply_chars: int = 0
    ts: float = field(default_factory=time.time)
    reply_has_bullets: bool = False
    reply_has_code: bool = False


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_MAX_MESSAGE_CHARS = 2000
_TURNS_MAX_LINES = 5000
_TURNS_ROTATE_BUFFER = 500
_FEEDBACK_MAX_LINES = 5000
_SAVE_INTERVAL_SECONDS = 2.0
_MAX_SKILL_NEGATIVES = 20

_MIN_OBSERVATIONS = 20          # cold start: below this, suggest() stays empty
_MIN_ROUTE_UPDATES = 5
_ROUTE_CONFIDENCE = 0.55
_AGENT_MIN_P = 0.15
_SKILL_MIN_P = 0.6
_MIN_STYLE_EVIDENCE = 5
_STYLE_PREFERENCE_THRESHOLD = 0.65
_HOLDOUT_WINDOW = 200
_MIN_HOLDOUT = 5


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit]


def _default_style_votes() -> Dict[str, Any]:
    return {
        "length": {"short": [0, 0], "medium": [0, 0], "long": [0, 0]},
        "bullets": [0, 0],
        "prose": [0, 0],
        "code": [0, 0],
    }


# ---------------------------------------------------------------------------
# The learner
# ---------------------------------------------------------------------------


class Learner:
    """Owns the four models plus the bounded logs used to train and explain them.

    Thread-safe: turns run on worker threads (``routes_live.chat_stream``
    spawns one per turn), so every public method takes ``_lock`` for its whole
    body. Storage is lazy — nothing is read from disk until the first real
    call — so importing this module, or constructing a ``Learner()`` for a
    test with explicit paths, never touches the real data directory.
    """

    def __init__(
        self,
        *,
        turns_path: Optional[Path] = None,
        models_path: Optional[Path] = None,
        feedback_path: Optional[Path] = None,
    ) -> None:
        self._turns_path = turns_path
        self._models_path = models_path
        self._feedback_path = feedback_path
        self._lock = threading.RLock()
        self._loaded = False
        self._last_saved = 0.0

        self.hasher = FeatureHasher()
        self.route_model = OnlineSoftmax()
        self.route_model.seed_labels("fast", "full")
        self.agent_model = OnlineSoftmax()
        self.skill_models = OneVsRestBinary()
        self.provider_stats: Dict[str, _ProviderStat] = {}

        self.total_turns = 0
        self.feedback_counts: Counter = Counter()
        self.agent_counts: Counter = Counter()
        self.skill_counts: Counter = Counter()
        self.style_votes: Dict[str, Any] = _default_style_votes()

        self._turn_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._turns_line_count = 0
        self._ratings: Dict[str, int] = {}

    # --- paths & lazy load ---------------------------------------------------

    def _paths(self) -> Tuple[Path, Path, Path]:
        return (
            self._turns_path or data_path("learning/turns.jsonl"),
            self._models_path or data_path("learning/models.json"),
            self._feedback_path or data_path("learning/feedback.jsonl"),
        )

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        self._load_models()
        self._load_turns_tail()
        self._load_feedback_tail()

    def _load_models(self) -> None:
        _, models_path, _ = self._paths()
        if not models_path.exists():
            return
        try:
            data = json.loads(models_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LOG.warning("could not read %s; starting with fresh models", models_path)
            return
        self.total_turns = int(data.get("total_turns", 0))
        self.feedback_counts = Counter(data.get("feedback_counts", {}))
        self.agent_counts = Counter(data.get("agent_counts", {}))
        self.skill_counts = Counter(data.get("skill_counts", {}))
        self.route_model = OnlineSoftmax.from_dict(data.get("route"))
        self.route_model.seed_labels("fast", "full")
        self.agent_model = OnlineSoftmax.from_dict(data.get("agent"))
        self.skill_models = OneVsRestBinary.from_dict(data.get("skill"))
        self.provider_stats = {
            key: _ProviderStat(**{k: v for k, v in value.items() if k in _ProviderStat.__dataclass_fields__})
            for key, value in (data.get("provider") or {}).items()
        }
        loaded_votes = data.get("style_votes") or {}
        votes = _default_style_votes()
        for bucket in votes["length"]:
            pair = (loaded_votes.get("length") or {}).get(bucket)
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                votes["length"][bucket] = [int(pair[0]), int(pair[1])]
        for key in ("bullets", "prose", "code"):
            pair = loaded_votes.get(key)
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                votes[key] = [int(pair[0]), int(pair[1])]
        self.style_votes = votes

    def _save_models(self) -> None:
        _, models_path, _ = self._paths()
        payload = {
            "version": 1,
            "updated_at": time.time(),
            "total_turns": self.total_turns,
            "feedback_counts": dict(self.feedback_counts),
            "agent_counts": dict(self.agent_counts),
            "skill_counts": dict(self.skill_counts),
            "route": self.route_model.to_dict(),
            "agent": self.agent_model.to_dict(),
            "skill": self.skill_models.to_dict(),
            "provider": {key: vars(stat) for key, stat in self.provider_stats.items()},
            "style_votes": self.style_votes,
        }
        tmp = models_path.with_suffix(models_path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            atomic_replace(tmp, models_path)
        except OSError:
            _LOG.warning("could not save %s", models_path)

    def _maybe_save_models(self) -> None:
        now = time.time()
        if now - self._last_saved >= _SAVE_INTERVAL_SECONDS:
            self._save_models()
            self._last_saved = now

    def flush(self) -> None:
        """Force an immediate save. Tests and a clean shutdown want this; the
        normal turn path relies on the time-based throttle instead so a chat
        turn never pays for a full JSON re-encode on every single message."""
        with self._lock:
            self._ensure_loaded()
            self._save_models()
            self._last_saved = time.time()

    # --- bounded logs ----------------------------------------------------------

    @staticmethod
    def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        except OSError:
            _LOG.warning("could not append to %s", path)

    @staticmethod
    def _rewrite_jsonl(path: Path, records: Sequence[Dict[str, Any]]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            atomic_replace(tmp, path)
        except OSError:
            _LOG.warning("could not rotate %s", path)

    @staticmethod
    def _clear_jsonl(path: Path) -> None:
        try:
            path.write_text("", encoding="utf-8")
        except OSError:
            pass

    def _load_turns_tail(self) -> None:
        path, _, _ = self._paths()
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        self._turns_line_count = len(lines)
        for line in lines[-_TURNS_MAX_LINES:]:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            turn_id = record.get("turn_id")
            if turn_id:
                self._turn_cache[turn_id] = record

    def _load_feedback_tail(self) -> None:
        _, _, path = self._paths()
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines[-_FEEDBACK_MAX_LINES:]:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            turn_id = record.get("turn_id")
            if turn_id:
                self._ratings[turn_id] = record.get("rating")

    def _remember_turn(self, record: Dict[str, Any]) -> None:
        turn_id = record["turn_id"]
        self._turn_cache[turn_id] = record
        self._turn_cache.move_to_end(turn_id)
        while len(self._turn_cache) > _TURNS_MAX_LINES:
            self._turn_cache.popitem(last=False)

    def _append_turn_record(self, record: Dict[str, Any]) -> None:
        path, _, _ = self._paths()
        self._append_jsonl(path, record)
        self._turns_line_count += 1
        if self._turns_line_count > _TURNS_MAX_LINES + _TURNS_ROTATE_BUFFER:
            self._rewrite_jsonl(path, list(self._turn_cache.values()))
            self._turns_line_count = len(self._turn_cache)

    def _append_feedback_record(self, record: Dict[str, Any]) -> None:
        _, _, path = self._paths()
        self._append_jsonl(path, record)

    # --- observing turns ---------------------------------------------------------

    def observe_turn(self, summary: TurnSummary) -> None:
        """Train from one completed turn's outcome (see module docstring for the rules)."""
        with self._lock:
            self._ensure_loaded()
            message = _truncate(summary.message, _MAX_MESSAGE_CHARS)
            features = self.hasher.featurize(message)
            self.total_turns += 1

            # route: a fast turn that had to escalate already proved fast was
            # wrong for messages like this; a full turn that never touched a
            # tool and still succeeded suggests fast might have been enough
            # (softer signal, so it trains at half weight).
            if summary.mode == "fast" and summary.escalated:
                self.route_model.learn(features, "full", weight=1.0)
            elif summary.mode == "full" and not summary.tools and summary.ok:
                self.route_model.learn(features, "fast", weight=0.5)

            if summary.ok:
                for agent in summary.agents:
                    self.agent_model.learn(features, agent, weight=1.0)
                    self.agent_counts[agent] += 1

            if "use_skill" in (summary.tools or []):
                others = [s for s in self.skill_models.ids() if s not in summary.skills][:_MAX_SKILL_NEGATIVES]
                for skill_id in summary.skills:
                    self.skill_models.learn(skill_id, features, positive=True)
                    self.skill_counts[skill_id] += 1
                for skill_id in others:
                    self.skill_models.learn(skill_id, features, positive=False, weight=0.3)

            if summary.provider:
                key = _provider_key(summary.provider, summary.model)
                stat = self.provider_stats.setdefault(key, _ProviderStat())
                stat.n += 1
                if summary.ok:
                    stat.alpha += 1.0
                else:
                    stat.beta += 1.0
                if summary.latency_ms:
                    stat.latency_sum += float(summary.latency_ms)
                    stat.latency_n += 1

            record = {
                "turn_id": summary.turn_id,
                "chat_id": summary.chat_id,
                "message": message,
                "mode": summary.mode,
                "escalated": summary.escalated,
                "provider": summary.provider,
                "model": summary.model,
                "agents": list(summary.agents),
                "skills": list(summary.skills),
                "tools": list(summary.tools),
                "latency_ms": summary.latency_ms,
                "ok": summary.ok,
                "reply_chars": summary.reply_chars,
                "reply_has_bullets": summary.reply_has_bullets,
                "reply_has_code": summary.reply_has_code,
                "length_bucket": _length_bucket(summary.reply_chars),
                "ts": summary.ts,
            }
            self._remember_turn(record)
            self._append_turn_record(record)
            self._maybe_save_models()

    # --- feedback -----------------------------------------------------------------

    def feedback(self, turn_id: str, rating: int, comment: str = "", chat_id: str = "") -> None:
        """Apply a 👍/👎. ``rating`` is coerced to exactly +1 or -1."""
        with self._lock:
            self._ensure_loaded()
            rating = 1 if rating and rating > 0 else -1
            self.feedback_counts["positive" if rating > 0 else "negative"] += 1
            self._append_feedback_record({
                "turn_id": turn_id, "chat_id": chat_id, "rating": rating,
                "comment": _truncate(comment, 500), "ts": time.time(),
            })
            if turn_id:
                self._ratings[turn_id] = rating

            record = self._turn_cache.get(turn_id) if turn_id else None
            if record is not None:
                self._apply_feedback_to_models(record, rating)
            self._maybe_save_models()

    def _apply_feedback_to_models(self, record: Dict[str, Any], rating: int) -> None:
        features = self.hasher.featurize(record.get("message", ""))

        if rating < 0 and record.get("mode") == "fast":
            self.route_model.learn(features, "full", weight=1.0)
        elif rating > 0 and record.get("mode") == "full" and not record.get("tools"):
            self.route_model.learn(features, "fast", weight=1.0)
        elif rating > 0 and record.get("mode") == "fast":
            self.route_model.learn(features, "fast", weight=0.3)

        if rating > 0:
            for agent in record.get("agents") or []:
                self.agent_model.learn(features, agent, weight=0.5)
                self.agent_counts[agent] += 1

        for skill_id in record.get("skills") or []:
            self.skill_models.learn(skill_id, features, positive=rating > 0, weight=0.7)
            if rating > 0:
                self.skill_counts[skill_id] += 1

        provider = record.get("provider")
        if provider:
            key = _provider_key(provider, record.get("model", ""))
            stat = self.provider_stats.setdefault(key, _ProviderStat())
            if rating > 0:
                stat.alpha += 0.5
            else:
                stat.beta += 0.5

        self._record_style_vote(record, rating)

    def _record_style_vote(self, record: Dict[str, Any], rating: int) -> None:
        idx = 0 if rating > 0 else 1
        bucket = record.get("length_bucket") or _length_bucket(record.get("reply_chars", 0))
        votes = self.style_votes["length"].setdefault(bucket, [0, 0])
        votes[idx] += 1
        if record.get("reply_has_bullets"):
            self.style_votes["bullets"][idx] += 1
        else:
            self.style_votes["prose"][idx] += 1
        if record.get("reply_has_code"):
            self.style_votes["code"][idx] += 1

    # --- suggestions -----------------------------------------------------------------

    def suggest(self, message: str, attachments_kinds: Sequence[str] = ()) -> Dict[str, Any]:
        """Everything the router/prompt builder can lean on for this message.

        Cold start (fewer than ``_MIN_OBSERVATIONS`` turns ever observed)
        returns empty lists and says why in ``explain`` — a model with almost no
        data is more dangerous than no model.
        """
        with self._lock:
            self._ensure_loaded()
            result: Dict[str, Any] = {
                "route": None, "agents": [], "skills": [], "provider_ranking": [],
                "confidence": 0.0, "explain": "",
            }
            if self.total_turns < _MIN_OBSERVATIONS:
                result["explain"] = (
                    f"Cold start: only {self.total_turns} observed turn(s) so far "
                    f"(need at least {_MIN_OBSERVATIONS}) — suggestions appear once Nyx has seen more turns."
                )
                return result

            features = self.hasher.featurize(message or "", attachment_kinds=attachments_kinds)
            explain_parts = [f"{self.total_turns} observed turns"]

            route_probs = self.route_model.predict_proba(features)
            route_conf = max(route_probs.values()) if route_probs else 0.0
            if route_probs and route_conf >= _ROUTE_CONFIDENCE and self.route_model.updates >= _MIN_ROUTE_UPDATES:
                label = max(route_probs, key=route_probs.get)
                result["route"] = {"label": label, "p": round(route_conf, 3)}
                explain_parts.append(f"route leans '{label}' ({route_conf:.0%}, {self.route_model.updates} route updates)")

            agent_probs = self.agent_model.predict_proba(features)
            agents = sorted(
                ({"name": name, "p": round(p, 3)} for name, p in agent_probs.items() if p >= _AGENT_MIN_P),
                key=lambda item: -item["p"],
            )[:5]
            result["agents"] = agents
            if agents:
                explain_parts.append(f"top agent match '{agents[0]['name']}'")

            skills = []
            for skill_id in self.skill_models.ids():
                p = self.skill_models.predict_proba(skill_id, features)
                if p >= _SKILL_MIN_P:
                    skills.append({"id": skill_id, "p": round(p, 3)})
            skills.sort(key=lambda item: -item["p"])
            result["skills"] = skills[:5]
            if skills:
                explain_parts.append(f"{len(skills)} skill match(es)")

            result["provider_ranking"] = self._provider_ranking()

            confidences = [route_conf] + [a["p"] for a in agents]
            result["confidence"] = round(max(confidences), 3) if confidences else 0.0
            result["explain"] = (
                "; ".join(explain_parts) if len(explain_parts) > 1
                else f"{self.total_turns} observed turns; nothing crosses the confidence threshold yet"
            )
            return result

    def _provider_ranking(self) -> List[Dict[str, Any]]:
        ranking = []
        for key, stat in self.provider_stats.items():
            provider, _, model = key.partition("::")
            label = f"{provider}/{model}" if model else provider
            ranking.append({"provider": label, "score": round(stat.score(), 4), "n": stat.n})
        ranking.sort(key=lambda item: -item["score"])
        return ranking

    def style_hints(self) -> str:
        """Learned reply-style preferences, as a sentence to fold into a system
        prompt — empty until there is enough feedback to say anything useful."""
        with self._lock:
            self._ensure_loaded()
            hints: List[str] = []

            length_scores = {}
            for bucket, (pos, neg) in self.style_votes["length"].items():
                total = pos + neg
                if total >= _MIN_STYLE_EVIDENCE:
                    length_scores[bucket] = (pos / total, total)
            if length_scores:
                best = max(length_scores, key=lambda b: length_scores[b][0])
                rate, total = length_scores[best]
                if rate >= _STYLE_PREFERENCE_THRESHOLD:
                    label = {"short": "short, to-the-point", "medium": "moderate-length",
                              "long": "thorough, detailed"}.get(best, best)
                    hints.append(f"The owner rates {label} replies higher ({total} votes) — lean that way.")

            bp, bn = self.style_votes["bullets"]
            pp, pn = self.style_votes["prose"]
            if (bp + bn) and (pp + pn) and (bp + bn + pp + pn) >= _MIN_STYLE_EVIDENCE:
                b_rate, p_rate = bp / (bp + bn), pp / (pp + pn)
                if abs(b_rate - p_rate) >= 0.15:
                    hints.append("Prefer bulleted lists." if b_rate > p_rate else "Prefer prose over bullet lists.")

            cp, cn = self.style_votes["code"]
            if (cp + cn) >= _MIN_STYLE_EVIDENCE and cp / (cp + cn) >= _STYLE_PREFERENCE_THRESHOLD:
                hints.append("Lead with a code block before explaining, when code is relevant.")

            return " ".join(hints)

    # --- introspection -----------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            return {
                "observations": self.total_turns,
                "feedback": dict(self.feedback_counts),
                "models": {
                    "route": {"labels": list(self.route_model.labels), "updates": self.route_model.updates,
                              "weights": sum(len(w) for w in self.route_model.weights.values())},
                    "agent": {"labels": list(self.agent_model.labels), "updates": self.agent_model.updates,
                              "weights": sum(len(w) for w in self.agent_model.weights.values())},
                    "skill": {"ids": self.skill_models.ids(),
                              "updates": sum(m.updates for m in self.skill_models.models.values())},
                    "provider": {"tracked": list(self.provider_stats.keys())},
                },
                "held_out_route_accuracy": self._route_holdout_accuracy(),
                "top_agents": self.agent_counts.most_common(5),
                "top_skills": self.skill_counts.most_common(5),
            }

    def _route_holdout_accuracy(self) -> Optional[float]:
        """Best-effort validation metric: replay recent turns, compare the
        route model's *current* prediction against what, with hindsight
        (escalation/feedback), the right call actually was. Not a rigorous
        train/test split — there is only ever one stream of turns to learn
        from — but a real, checkable number rather than an invented one, and
        it degrades to ``None`` rather than a misleading value when there is
        too little to say anything ("if computable").
        """
        sample = list(self._turn_cache.values())[-_HOLDOUT_WINDOW:]
        usable = [r for r in sample if r.get("mode") in ("fast", "full")]
        if len(usable) < _MIN_HOLDOUT:
            return None
        correct = 0
        for record in usable:
            ideal = record["mode"]
            if record.get("escalated"):
                ideal = "full"
            rating = self._ratings.get(record.get("turn_id"))
            if rating == -1 and record["mode"] == "fast":
                ideal = "full"
            elif rating == 1 and record["mode"] == "full" and not record.get("tools"):
                ideal = "fast"
            probs = self.route_model.predict_proba(self.hasher.featurize(record.get("message", "")))
            if not probs:
                continue
            predicted = max(probs, key=probs.get)
            correct += int(predicted == ideal)
        return round(correct / len(usable), 4) if usable else None

    # --- reset -----------------------------------------------------------------------

    def reset(self, scope: str = "all") -> None:
        """Wipe learned state. ``scope``: ``all`` | ``models`` | ``feedback``."""
        if scope not in ("all", "models", "feedback"):
            raise ValueError("scope must be 'all', 'models', or 'feedback'")
        with self._lock:
            self._ensure_loaded()
            if scope in ("all", "models"):
                self.route_model = OnlineSoftmax()
                self.route_model.seed_labels("fast", "full")
                self.agent_model = OnlineSoftmax()
                self.skill_models = OneVsRestBinary()
                self.provider_stats = {}
                self.agent_counts = Counter()
                self.skill_counts = Counter()
                self.style_votes = _default_style_votes()
            if scope in ("all", "feedback"):
                self.feedback_counts = Counter()
                self._ratings = {}
                self._clear_jsonl(self._paths()[2])
            if scope == "all":
                self.total_turns = 0
                self._turn_cache = OrderedDict()
                self._turns_line_count = 0
                self._clear_jsonl(self._paths()[0])
            self._save_models()
            self._last_saved = time.time()


#: The singleton the rest of the app uses. Storage is lazy, so importing this
#: module never touches the real data directory (see ``Learner`` docstring).
LEARNER = Learner()
