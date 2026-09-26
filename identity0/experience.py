"""Identity 0's experiences: what each answer was, who wrote it, how it compared, what was learned.

This is how "when it can't figure it out it tries to, collaborates with AI added, and learns it"
works. Every lead answer is recorded. Some turns also get a shadow answer from another member; a
background judge compares the two (order-swapped, budgeted), the verdict moves the competence table,
and when the lead lost or failed, the better answer becomes a lesson in the super brain at once and a
training example later (only if ``policy.may_train_on`` allows that model).

Records are written when complete (lead, plus shadow and verdict when there is one), so the JSONL
file never needs rewriting; owner ratings arrive later and go to ``ratings.jsonl`` keyed by turn id.
The file is capped (``experience_cap_mb``): past the cap the oldest 30% is dropped.

What is stored is PII-scrubbed (``policy.scrub_pii``): this file is training data and the closest
thing Big Kahuna has to a diary, so a key or a card number the owner pasted into a chat must not
settle in it. The models themselves still see the real words — only the record is cleaned.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Optional

from identity0 import competence, state

_LOG = logging.getLogger("nyx.identity0")
FILE = "experiences.jsonl"
RATINGS = "ratings.jsonl"
_write_lock = threading.Lock()
_recent_turns: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_judge_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=64)
_worker: Optional[threading.Thread] = None
_stats: Dict[str, Any] = {}


def new_id() -> str:
    return "exp_" + uuid.uuid4().hex[:12]


def digest(messages: List[Dict[str, Any]]) -> str:
    body = json.dumps([[m.get("role"), str(m.get("content", ""))[:2000]] for m in messages], ensure_ascii=False)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()


def _trainable(member: str) -> bool:
    try:
        from identity0.members import split_id
        from identity0.policy import may_train_on

        provider, model = split_id(member)
        return bool(may_train_on(provider, model)[0])
    except Exception:  # noqa: BLE001 - unknown provenance is never trainable
        return False


def _answer(member: str, text: str, ms: float, ok: bool, error: str = "") -> Dict[str, Any]:
    return {"member": member, "text": (text or "")[:8000], "ms": round(float(ms or 0)), "ok": bool(ok),
            **({"error": error[:300]} if error else {})}


def begin(*, turn_id: str, prompt: str, messages: List[Dict[str, Any]], domain: str, difficulty: float,
          protocol: str) -> Dict[str, Any]:
    return {"id": new_id(), "ts": time.time(), "turn_id": turn_id or "", "domain": domain or "chat",
            "difficulty": round(float(difficulty), 3), "prompt": (prompt or "")[:4000],
            "context_digest": digest(messages), "protocol": protocol, "lead": None, "shadow": None,
            "helpers": [], "verdict": None, "rating": None, "trainable": {}, "learned": False}


def lead_done(record: Dict[str, Any], member: str, text: str, ms: float, ok: bool, error: str = "") -> None:
    record["lead"] = _answer(member, text, ms, ok, error)
    record["trainable"]["lead"] = _trainable(member) and ok
    competence.record_answer(record["domain"], member, ok, ms)
    if record.get("turn_id"):
        _recent_turns[record["turn_id"]] = {"domain": record["domain"], "member": member, "exp": record["id"],
                                             "prompt": record.get("prompt", "")[:1000]}
        while len(_recent_turns) > 300:
            _recent_turns.popitem(last=False)


def shadow_done(record: Dict[str, Any], answer: Dict[str, Any]) -> None:
    """A shadow finished: judge it against the lead in the background, then write the record."""
    member = str(answer.get("member", ""))
    record["shadow"] = _answer(member, answer.get("text", ""), answer.get("ms", 0), answer.get("ok", False),
                               str(answer.get("error", "")))
    record["trainable"]["shadow"] = _trainable(member) and bool(answer.get("ok"))
    competence.record_answer(record["domain"], member, bool(answer.get("ok")), float(answer.get("ms", 0)))
    lead = record.get("lead") or {}
    if lead.get("ok") and answer.get("ok"):
        _enqueue(record)
    else:
        if lead.get("ok") is False and answer.get("ok"):
            _learn(record, "shadow")
        write(record)


def _enqueue(record: Dict[str, Any]) -> None:
    global _worker
    try:
        _judge_queue.put_nowait(record)
    except queue.Full:
        write(record)
        return
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_judge_loop, name="kahuna-judge", daemon=True)
        _worker.start()


def _judge_loop() -> None:
    while True:
        try:
            record = _judge_queue.get(timeout=60)
        except queue.Empty:
            return
        try:
            judge_now(record)
        except Exception as error:  # noqa: BLE001 - one bad record must not stop the loop
            _LOG.warning("identity0 judge failed: %s", error)
            write(record)


def judge_now(record: Dict[str, Any]) -> Dict[str, Any]:
    from identity0 import judge

    lead, shadow = record["lead"], record["shadow"]
    verdict = judge.compare(record["prompt"], lead["text"], shadow["text"],
                            exclude=[lead["member"], shadow["member"]])
    if verdict.get("ok"):
        record["verdict"] = {"winner": {"a": "lead", "b": "shadow"}.get(verdict["winner"], "tie"),
                             "confidence": verdict.get("confidence", 0.0), "by": verdict.get("by", ""),
                             "reason": verdict.get("reason", "")}
        winner = record["verdict"]["winner"]
        tie = winner == "tie"
        first, second = (lead, shadow) if winner in ("lead", "tie") else (shadow, lead)
        change = competence.record_verdict(record["domain"], first["member"], second["member"], tie=tie)
        if change:
            _announce(change, record["domain"])
        if winner == "shadow":
            _learn(record, "shadow")
    write(record)
    return record


def _scrub(text: str) -> str:
    try:
        from identity0.policy import scrub_pii

        return scrub_pii(text or "")
    except Exception:  # noqa: BLE001 - never lose a record over the scrubber
        return text or ""


def _clean(record: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of the record with secrets and personal details removed (what goes on disk)."""
    out = dict(record)
    out["prompt"] = _scrub(str(record.get("prompt", "")))
    for key in ("lead", "shadow"):
        answer = record.get(key)
        if isinstance(answer, dict) and answer.get("text"):
            out[key] = {**answer, "text": _scrub(str(answer["text"]))}
    helpers = record.get("helpers")
    if isinstance(helpers, list):
        out["helpers"] = [{**h, "text": _scrub(str(h["text"]))} if isinstance(h, dict) and h.get("text") else h
                          for h in helpers]
    return out


def _learn(record: Dict[str, Any], which: str) -> None:
    """The lead could not do it and a collaborator could: keep the better answer as a lesson."""
    answer = record.get(which) or {}
    text = str(answer.get("text", ""))
    if len(text) < 60 or "<tool_call>" in text:
        return
    record["learned"] = True
    try:
        import super_brain

        super_brain.BRAIN.ingest(f"Question: {_scrub(record['prompt'])[:1200]}\nA better answer "
                                 f"({answer.get('member')}): {_scrub(text)[:3000]}",
                                 source="knowledge", kind="lesson", ref=f"kahuna:{record['id']}")
    except Exception:  # noqa: BLE001 - memory is a bonus, the record still counts
        pass


def _announce(change: str, domain: str) -> None:
    try:
        from agent_events import publish_ui
        import identity0

        publish_ui("identity0.stage", domain=domain, change=change,
                   text=f"{identity0.NAME}'s own model {change} in {domain}")
    except Exception:  # noqa: BLE001
        pass


def write(record: Dict[str, Any]) -> None:
    line = json.dumps(_clean(record), ensure_ascii=False) + "\n"
    target = state.path(FILE)
    with _write_lock:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(line)
        _count(record)
        _enforce_cap(target)


def _count(record: Dict[str, Any]) -> None:
    stats = _load_stats()
    stats["total"] = stats.get("total", 0) + 1
    stats["learned"] = stats.get("learned", 0) + int(bool(record.get("learned")))
    protocols = stats.setdefault("protocols", {})
    protocols[record.get("protocol", "solo")] = protocols.get(record.get("protocol", "solo"), 0) + 1
    verdict = (record.get("verdict") or {}).get("winner")
    if verdict:
        verdicts = stats.setdefault("verdicts", {})
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
    if record.get("shadow"):
        stats["shadowed"] = stats.get("shadowed", 0) + 1
    stats["last"] = record.get("ts")
    state.write_json("experience_stats.json", stats)


def _load_stats() -> Dict[str, Any]:
    global _stats
    if not _stats:
        loaded = state.read_json("experience_stats.json", {})
        _stats = loaded if isinstance(loaded, dict) else {}
    return _stats


def reset_cache() -> None:
    global _stats
    _stats = {}
    _recent_turns.clear()


def _enforce_cap(target: Any) -> None:
    try:
        from identity0.state import get_settings

        cap = int(get_settings().get("experience_cap_mb", 50)) * 1024 * 1024
        if target.stat().st_size <= cap:
            return
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        keep = lines[int(len(lines) * 0.3):]
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text("".join(keep), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        pass


def recent(limit: int = 30, offset: int = 0) -> List[Dict[str, Any]]:
    """Newest first. Reads only the tail of the file."""
    target = state.path(FILE)
    try:
        with open(target, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - 2_000_000))
            tail = handle.read().decode("utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    rows: List[Dict[str, Any]] = []
    for line in reversed(tail):
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
        if len(rows) >= offset + limit:
            break
    return rows[offset:offset + limit]


def stats() -> Dict[str, Any]:
    return {**_load_stats(), "judging_queue": _judge_queue.qsize()}


def on_feedback(turn_id: str, rating: int) -> bool:
    """A 👍/👎 on a turn Identity 0 answered: credit (or debit) the member that led it."""
    info = _recent_turns.get(turn_id or "")
    with _write_lock:
        with open(state.path(RATINGS), "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": time.time(), "turn_id": turn_id, "rating": int(rating),
                                     "member": (info or {}).get("member", "")}) + "\n")
    if not info:
        return False
    competence.record_rating(info["domain"], info["member"], int(rating))
    try:
        # Adaptation (Request S16/S17): the skills and agents that fit this request gain or lose weight.
        from identity0 import predict

        for skill in predict.skills(info.get("prompt", "")):
            predict.learn("skill", skill["id"], int(rating))
        for agent in predict.agents(info.get("prompt", "")):
            predict.learn("agent", agent["name"], int(rating))
    except Exception:  # noqa: BLE001
        pass
    return True
