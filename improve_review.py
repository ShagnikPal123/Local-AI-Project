"""The Improve tab's review queue: find duplicates, research each change, recommend, decide, implement.

The owner (2026-09-16): "In improve tab add a place where I can approve or deny changes. Make a mode to
analyze all in review or changes and then approve or deny and apply" — and "tell it to approve and auto
check … but still doesn't, please see and make sure it can research, then approve on its own."

What went wrong before this module: the improvement engine files *descriptions* of changes, and the
autopilot's critic was shown that description with an empty "proposed content" block. It blocked 94 of 101
changes as "the diff is missing". The engine also re-proposed the same five ideas every session, so 701
changes sat in review with no way to act on them from the Improve tab.

The flow now, for one change:

1. **Duplicates** are found offline (same file, overlapping words) — no model call.
2. **Research**: the target file is read (the parts the description talks about), protected or missing
   files are ruled out, and optionally the web is searched. A model then answers *should this be done*,
   with ``already_done`` and ``risk`` — judging the idea, not a diff that does not exist yet.
3. **Decide**: the owner approves or denies (one, many, or all recommendations at once), or authorises
   Nyx to apply its own recommendations. Denied changes are rejected with the reason.
4. **Implement** (only when "Implement approved changes" is on, or the owner presses Implement now):
   ``self_patch.prepare`` writes the edit and runs the tests in a sandbox, a critic reads the *real* diff
   and test result, and only then ``self_patch.commit`` writes the file. Everything applied can be rolled back.

Nothing here weakens the gate (invariant 4): an AI recommendation is stored next to the change, and only
the owner's action — or an auto-apply the owner started — moves it to approved.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import PROJECT_DIR, data_path

_LOG = logging.getLogger("nyx.improve_review")

#: Changes that still need a decision (``approved`` ones may still need implementing).
OPEN_STATUSES = ("draft", "in_review", "approved")
#: Default cap on model calls for one "Analyze all" run; duplicates and protected files cost none.
DEFAULT_ANALYZE_LIMIT = 40

_STOP = frozenset("""a an and the to of in for on with by from into at or as is are be this that it its add adds added
improve improves improved make makes use uses using when where which so than then more better robust proper
handling handle support py file module nyx""".split())

ModelFn = Callable[..., str]


class ReviewError(RuntimeError):
    """A review action that cannot be done (unknown change, job already running)."""


# ---------------------------------------------------------------------------
# Duplicates
# ---------------------------------------------------------------------------


def _stem(word: str) -> str:
    for suffix in ("ation", "ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> set:
    return {_stem(w) for w in re.findall(r"[a-z][a-z0-9]+", (text or "").lower()) if w not in _STOP and len(w) > 2}


def similarity(a: str, b: str) -> float:
    left, right = tokens(a), tokens(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _title_body(change: Dict[str, Any]) -> str:
    return re.sub(r"^Improve [\w./-]+:\s*", "", str(change.get("title", "")))


def is_duplicate(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    if (a.get("target") or "").lower() != (b.get("target") or "").lower():
        return False
    title = similarity(_title_body(a), _title_body(b))
    whole = similarity(f"{_title_body(a)} {a.get('description', '')}", f"{_title_body(b)} {b.get('description', '')}")
    return title >= 0.5 or whole >= 0.42 or (title >= 0.34 and whole >= 0.3)


#: Who rejected changes before 2026-09-16, when the critic was shown an empty diff. Those refusals say nothing
#: about the idea, so a later proposal of the same idea is not a "duplicate" of them.
_LEGACY_REVIEWERS = ("Autopilot critic", "Autopilot")


def counts_as_decision(change: Dict[str, Any]) -> bool:
    if change.get("status") == "published":
        return True
    return change.get("status") == "rejected" and str(change.get("reviewed_by", "")) not in _LEGACY_REVIEWERS


def find_duplicate(change: Dict[str, Any], others: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """An earlier change that says the same thing (open, applied or already refused), if there is one."""
    for other in others:
        if other.get("id") == change.get("id"):
            continue
        if other.get("status") in ("rolled_back",):
            continue
        if is_duplicate(change, other):
            return other
    return None


def group_duplicates(changes: List[Dict[str, Any]]) -> Dict[str, str]:
    """``{change_id: id_of_the_one_it_repeats}`` for open changes. The oldest of a group is the one kept.

    A change that repeats one already applied or already refused is a duplicate of that decision.
    """
    decided = [c for c in changes if counts_as_decision(c)]
    kept: List[Dict[str, Any]] = []
    result: Dict[str, str] = {}
    for change in sorted((c for c in changes if c.get("status") in OPEN_STATUSES), key=lambda c: float(c.get("created_at") or 0)):
        earlier = find_duplicate(change, kept) or find_duplicate(change, decided)
        if earlier is not None:
            result[change["id"]] = earlier["id"]
        else:
            kept.append(change)
    return result


# ---------------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------------


def file_excerpt(target: str, description: str, root: Path = PROJECT_DIR, limit: int = 3500) -> Dict[str, Any]:
    """The parts of the target file the change talks about, plus its outline. Protected files are refused."""
    import self_patch

    try:
        path = self_patch.resolve_target(target, root)
    except self_patch.PatchError as error:
        return {"ok": False, "error": str(error), "protected": "protected" in str(error)}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        return {"ok": False, "error": f"Could not read {target}: {error}", "protected": False}
    lines = text.splitlines()
    words = [w for w in tokens(description) if len(w) > 3][:14]
    scored = []
    for index, line in enumerate(lines):
        lower = line.lower()
        hits = sum(1 for w in words if w in lower)
        if hits:
            scored.append((hits, index))
    windows: List[range] = []
    for _hits, index in sorted(scored, reverse=True)[:6]:
        span = range(max(0, index - 5), min(len(lines), index + 7))
        if not any(span.start < w.stop and w.start < span.stop for w in windows):
            windows.append(span)
    body = "\n...\n".join("\n".join(f"{i + 1}: {lines[i]}" for i in span) for span in sorted(windows, key=lambda r: r.start))
    outline = "\n".join(line.strip() for line in lines if re.match(r"\s*(async\s+def|def|class)\s", line))[:1500]
    return {"ok": True, "file": path.relative_to(root).as_posix(), "lines": len(lines),
            "excerpt": body[:limit], "outline": outline, "matched_words": words}


def web_notes(query: str, limit: int = 3) -> str:
    try:
        import web_access

        results = web_access.search_results(query)[:limit]
    except Exception:  # noqa: BLE001 - research is best-effort
        return ""
    return "\n".join(f"- {r.get('title', '')}: {str(r.get('snippet', ''))[:220]} ({r.get('url', '')})" for r in results)


def verdict_prompt(change: Dict[str, Any], research: Dict[str, Any], web: str = "") -> str:
    return (
        "You are deciding whether an AI assistant should make one proposed change to its own Python code.\n"
        "You are judging the IDEA, not a diff: no code has been written yet. If it is approved, a coder writes\n"
        "the edit, the tests run in a sandbox, and a reviewer reads the real diff before anything is applied.\n\n"
        f"Change: {change.get('title', '')}\nFile: {change.get('target', '')}\nDescription: {change.get('description', '')}\n\n"
        f"What the file has now ({research.get('lines', '?')} lines). Outline:\n{research.get('outline', '')}\n\n"
        f"Parts related to the change:\n{research.get('excerpt') or '(nothing in the file mentions it)'}\n\n"
        + (f"Web research:\n{web}\n\n" if web else "")
        + "Reply with JSON only: {\"verdict\": \"approve\" or \"deny\", \"confidence\": 0-1, \"already_done\": true/false, "
          "\"risk\": \"low\"|\"medium\"|\"high\", \"reasons\": \"2-3 sentences citing what the file shows\"}.\n"
          "Deny when the file already does it, when it is vague or unlikely to help, when it would weaken security, "
          "permissions or tests, or when it risks breaking users. Approve concrete, useful, low-risk changes."
    )


def parse_verdict(reply: str) -> Dict[str, Any]:
    """The model's verdict. Reasoning models write their thinking first — the answer is the last JSON with a verdict.

    No readable verdict means no recommendation (``verdict: None``), never a silent "deny".
    """
    text = re.sub(r"<think>.*?</think>", "", reply or "", flags=re.S)
    data: Dict[str, Any] = {}
    from improve_autopilot import _complete_objects, _loads_object

    for chunk in reversed(_complete_objects(text)):
        candidate = _loads_object(chunk)
        if not candidate:
            try:
                from tools import _loads_lenient

                loaded = _loads_lenient(chunk)
                candidate = loaded if isinstance(loaded, dict) else {}
            except Exception:  # noqa: BLE001
                candidate = {}
        if "verdict" in candidate:
            data = candidate
            break
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in ("approve", "deny"):
        return {"verdict": None, "confidence": None, "already_done": False, "risk": None,
                "reasons": "The model did not give a clear verdict — run Analyze again or decide yourself."}
    risk = str(data.get("risk", "medium")).lower()
    already = bool(data.get("already_done"))
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    reasons = str(data.get("reasons") or text[:400]).strip()[:600]
    if verdict == "approve" and (already or risk == "high"):
        verdict = "deny"
        reasons = ("Already done in the file. " if already else "High risk. ") + reasons
    return {"verdict": verdict, "confidence": round(confidence, 2), "already_done": already,
            "risk": risk if risk in ("low", "medium", "high") else "medium", "reasons": reasons}


def critic_prompt(change: Dict[str, Any], diff: str, tests: str) -> str:
    return (
        "You are reviewing a proposed change to a local-first AI assistant before it is applied to its own code.\n"
        "The edit below was written for the change and already ran the tests in a sandbox.\n\n"
        f"Title: {change.get('title', '')}\nTarget: {change.get('target', '')}\nDescription: {change.get('description', '')}\n\n"
        f"--- the real diff ---\n{diff[:6000]}\n\n--- test result ---\n{(tests or 'passed')[:1200]}\n\n"
        "Begin your reply with exactly one word on its own line: BLOCK if the diff could break users, weaken "
        "security or permissions, lose data, or does not do what the title says; otherwise OK. Then 2-4 sentences why."
    )


def default_model(prompt: str, *, system: str = "", max_tokens: int = 800, role: str = "code_generation") -> str:
    from model_roles import MODEL_ROLES

    return MODEL_ROLES.run(role, prompt, system=system, max_tokens=max_tokens).text


# ---------------------------------------------------------------------------
# Records next to each change
# ---------------------------------------------------------------------------


class ReviewStore:
    """``autopilot/reviews.json``: the recommendation and implementation outcome per change id."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else data_path("autopilot/reviews.json")
        self._lock = threading.Lock()
        self._data: Optional[Dict[str, Dict[str, Any]]] = None

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if self._data is None:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self._data = raw if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self._data = {}
        return self._data

    def get(self, change_id: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._load().get(change_id, {}))

    def all(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._load().items()}

    def update(self, change_id: str, **fields: Any) -> Dict[str, Any]:
        with self._lock:
            data = self._load()
            record = dict(data.get(change_id, {}))
            record.update(fields)
            record["updated_at"] = time.time()
            data[change_id] = record
            # Keep the file small: only the newest 2000 records.
            if len(data) > 2000:
                for key in sorted(data, key=lambda k: data[k].get("updated_at", 0))[: len(data) - 2000]:
                    data.pop(key, None)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            return dict(record)


# ---------------------------------------------------------------------------
# Implementing one approved change (shared by the autopilot and the review queue)
# ---------------------------------------------------------------------------

#: One sandbox, one edit at a time: the autopilot and the review queue must not test into each other.
IMPLEMENT_LOCK = threading.Lock()


def _lines(result: Any) -> Dict[str, Any]:
    """Which file an edit touches and how many lines (Request R9) — exact from both versions when prepared."""
    import diff_stats

    after, relative = getattr(result, "after", ""), getattr(result, "relative", "") or getattr(result, "file", "")
    if after and relative:
        return diff_stats.from_texts(getattr(result, "before", ""), after, relative)
    return diff_stats.stats(getattr(result, "diff", "") or "")


def implement_change(change: Dict[str, Any], log: Any, *, values: Dict[str, Any], model_fn: Optional[ModelFn] = None,
                     preparer: Optional[Callable[..., Any]] = None, committer: Optional[Callable[..., Any]] = None,
                     publisher: str = "Owner", reject_on_failure: bool = False, retries: int = 1,
                     on_step: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Write, test, review and apply one *approved* change. Returns ``{"state", "message", ...}``.

    States: ``applied`` · ``blocked`` (the critic refused the real diff) · ``failed`` (no edit passed the tests).
    """
    import self_patch

    step = on_step or (lambda _text: None)
    prepare = preparer or (lambda ch, **kw: self_patch.prepare(ch, **kw))
    apply = committer or (lambda result: self_patch.commit(result))
    model = model_fn or default_model
    feedback = ""
    result: Any = None
    with IMPLEMENT_LOCK:
        for attempt in range(retries + 1):
            where = f" to {change.get('target')}" if change.get("target") and change.get("target") != "base_ai" else ""
            step(f"Writing the edit{where} and running the tests" + (f" (try {attempt + 1})" if attempt else ""))
            result = prepare(change, test_depth=str(values.get("test_depth", "quick")),
                             max_changed_lines=int(values.get("max_patch_lines", 150)), feedback=feedback)
            if getattr(result, "ok", False):
                break
            error = str(getattr(result, "error", "") or "")
            if any(word in error for word in ("protected", "No module named", "too large", "skip:", "chose not to")):
                break  # trying again cannot fix these
            feedback = error
        if not getattr(result, "ok", False):
            error = (getattr(result, "error", "") or "not implemented")[:500]
            if reject_on_failure:
                _safe(log.reject, change["id"], publisher, error)
            return {"state": "failed", "message": error, "diff": getattr(result, "diff", ""), "lines": _lines(result)}
        import diff_stats

        lines = _lines(result)
        step(f"Reviewing the real diff — {diff_stats.describe(lines)}")
        try:
            review = model(critic_prompt(change, result.diff, getattr(result, "tests", "")),
                           system="You are a strict code reviewer.", max_tokens=400) or "OK"
        except Exception as error:  # noqa: BLE001 - no reviewer, no apply
            review = f"BLOCK\nThe reviewer model was unavailable ({str(error)[:120]}), so this waits for the owner."
        current = log.get(change["id"])
        # Keep who approved it (the owner, or the auto-approve window they started) as the reviewer of record.
        _safe(log.attach_review, change["id"], review, getattr(current, "reviewed_by", "") or "Nyx critic")
        if review.strip().upper().startswith("BLOCK"):
            if reject_on_failure:
                _safe(log.reject, change["id"], "Nyx critic", review[:400])
            return {"state": "blocked", "message": review[:600], "diff": result.diff, "lines": lines}
        step(f"Applying — {diff_stats.describe(lines)}")
        result = apply(result)
        if not getattr(result, "ok", False):
            error = (getattr(result, "error", "") or "not applied")[:500]
            if reject_on_failure:
                _safe(log.reject, change["id"], publisher, error)
            return {"state": "failed", "message": error, "diff": getattr(result, "diff", ""), "lines": lines}
    note = "Original kept by self_patch; roll back from the Improve tab."
    if getattr(result, "already_failing", None):
        note += f" {len(result.already_failing)} test(s) were already failing before this edit."
    _safe(log.record_content, change["id"], result.diff, note)
    _safe(log.publish, change["id"], publisher)
    return {"state": "applied", "message": f"Applied — {diff_stats.describe(lines)}. {getattr(result, 'summary', '')}"[:300],
            "diff": result.diff, "file": result.file, "lines": lines, "seconds": getattr(result, "seconds", 0),
            "already_failing": list(getattr(result, "already_failing", []) or [])}


def _safe(fn: Callable[..., Any], *args: Any) -> Any:
    try:
        return fn(*args)
    except Exception as error:  # noqa: BLE001 - a status move that is already done is not an error here
        _LOG.debug("review step %s skipped: %s", getattr(fn, "__name__", fn), error)
        return None


# ---------------------------------------------------------------------------
# The queue and its jobs
# ---------------------------------------------------------------------------


class ReviewQueue:
    def __init__(self, *, log: Any = None, store: Optional[ReviewStore] = None, model_fn: Optional[ModelFn] = None,
                 preparer: Optional[Callable[..., Any]] = None, committer: Optional[Callable[..., Any]] = None,
                 values_fn: Optional[Callable[[], Dict[str, Any]]] = None, threaded: bool = True,
                 root: Path = PROJECT_DIR, web_fn: Optional[Callable[[str], str]] = None) -> None:
        self._log = log
        self.store = store or ReviewStore()
        self._model_fn = model_fn
        self._preparer, self._committer = preparer, committer
        self._values_fn = values_fn
        self._threaded = threaded
        self._root = root
        self._web_fn = web_fn or web_notes
        self._lock = threading.RLock()
        self._job: Optional[Dict[str, Any]] = None
        self._stop = threading.Event()

    # --- plumbing -----------------------------------------------------------------

    def log(self) -> Any:
        if self._log is not None:
            return self._log
        from change_review import CHANGE_LOG

        return CHANGE_LOG

    def values(self) -> Dict[str, Any]:
        if self._values_fn is not None:
            return self._values_fn()
        try:
            from improve_autopilot import AUTOPILOT

            return AUTOPILOT.control_values()
        except Exception:  # noqa: BLE001
            return {"implement_approved": True, "test_depth": "quick", "max_patch_lines": 150}

    def _model(self, prompt: str, **kw: Any) -> str:
        if self._model_fn is not None:
            return self._model_fn(prompt, **{k: v for k, v in kw.items() if k in ("system", "max_tokens")})
        return default_model(prompt, **kw)

    def _publish(self) -> None:
        try:
            from agent_events import publish_ui

            publish_ui("improve.review", job=self.job())
        except Exception:  # noqa: BLE001
            pass

    def agent_changes(self) -> List[Dict[str, Any]]:
        return [c for c in self.log().list_changes() if c.get("origin") == "agent"]

    # --- reads ------------------------------------------------------------------------

    def job(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return json.loads(json.dumps(self._job)) if self._job else None

    def queue(self, limit: int = 200) -> Dict[str, Any]:
        """Open changes with their recommendation, implementation state and duplicate link."""
        import self_patch

        changes = self.agent_changes()
        by_id = {c["id"]: c for c in changes}
        duplicates = group_duplicates(changes)
        applied = self_patch.applied_changes()
        records = self.store.all()
        items = []
        for change in changes:
            if change["status"] not in OPEN_STATUSES:
                continue
            if change["status"] == "approved" and change["id"] in applied:
                continue
            record = records.get(change["id"], {})
            dup = duplicates.get(change["id"])
            if not dup and record.get("duplicate_of") in by_id and by_id[record["duplicate_of"]]["status"] != "rolled_back":
                dup = record["duplicate_of"]
            items.append({
                **{k: change.get(k) for k in ("id", "title", "description", "target", "status", "created_at", "ai_review", "reviewed_by")},
                "duplicate_of": dup, "duplicate_title": by_id.get(dup, {}).get("title", "") if dup else "",
                "recommendation": record.get("verdict") or ("deny" if dup else None),
                "confidence": record.get("confidence"), "reasons": record.get("reasons") or (
                    f"Repeats “{by_id[dup]['title'][:90]}” ({by_id[dup]['status'].replace('_', ' ')})." if dup else ""),
                "risk": record.get("risk"), "already_done": record.get("already_done", False),
                "research": record.get("research", ""), "analyzed_at": record.get("analyzed_at"),
                "implement": record.get("implement"),
            })
        counts = {
            "open": len(items),
            "waiting": sum(1 for i in items if i["status"] in ("draft", "in_review")),
            "approved_not_applied": sum(1 for i in items if i["status"] == "approved"),
            "duplicates": sum(1 for i in items if i["duplicate_of"]),
            "recommended_approve": sum(1 for i in items if i["recommendation"] == "approve"),
            "recommended_deny": sum(1 for i in items if i["recommendation"] == "deny"),
            "analyzed": sum(1 for i in items if i["analyzed_at"]),
        }
        # Most useful first: unique before duplicates, approved-but-waiting first, then newest.
        items.sort(key=lambda i: (bool(i["duplicate_of"]), i["status"] != "approved", -float(i["created_at"] or 0)))
        return {"items": items[:limit], "counts": counts, "job": self.job(),
                "implement_approved": bool(self.values().get("implement_approved", True))}

    # --- single decisions -----------------------------------------------------------------

    def _change(self, change_id: str) -> Dict[str, Any]:
        change = self.log().get(change_id)
        if change is None:
            raise ReviewError("No such change.")
        return change.as_dict()

    def approve(self, change_id: str, *, by: str = "Owner", implement: Optional[bool] = None) -> Dict[str, Any]:
        change = self._change(change_id)
        log = self.log()
        if change["status"] == "draft":
            log.submit_for_review(change_id)
        if change["status"] in ("draft", "in_review"):
            log.approve(change_id, by)
        elif change["status"] != "approved":
            raise ReviewError(f"That change is already {change['status'].replace('_', ' ')}.")
        should = bool(self.values().get("implement_approved", True)) if implement is None else implement
        if not should:
            record = self.store.update(change_id, implement={"state": "approved_only", "at": time.time(),
                                                             "message": "Approved only — “Implement approved changes” is off, so the code is left for you."})
            self._publish()
            return {"id": change_id, "status": "approved", "implement": record["implement"]}
        return self.implement(change_id, by=by)

    def deny(self, change_id: str, *, by: str = "Owner", reason: str = "") -> Dict[str, Any]:
        change = self._change(change_id)
        if change["status"] not in OPEN_STATUSES:
            raise ReviewError(f"That change is already {change['status'].replace('_', ' ')}.")
        self.log().reject(change_id, by, reason or "Denied in the Improve tab")
        self._publish()
        return {"id": change_id, "status": "rejected"}

    def implement(self, change_id: str, *, by: str = "Owner", background: Optional[bool] = None) -> Dict[str, Any]:
        """Implement an approved change now (in the background when threaded)."""
        change = self._change(change_id)
        if change["status"] != "approved":
            raise ReviewError("Approve the change first.")
        self.store.update(change_id, implement={"state": "running", "at": time.time(), "message": "Starting"})
        self._publish()

        def work() -> None:
            outcome = self._implement_one(change, by)
            self.store.update(change_id, implement={**outcome, "at": time.time()})
            self._publish()

        if self._threaded if background is None else background:
            threading.Thread(target=work, name=f"nyx-implement-{change_id}", daemon=True).start()
            return {"id": change_id, "status": "approved", "implement": {"state": "running"}}
        work()
        return {"id": change_id, "status": self._change(change_id)["status"], "implement": self.store.get(change_id).get("implement")}

    def _implement_one(self, change: Dict[str, Any], by: str) -> Dict[str, Any]:
        def step(text: str) -> None:
            self.store.update(change["id"], implement={"state": "running", "message": text, "at": time.time()})
            self._publish()

        preparer = self._preparer or (lambda ch, **kw: __import__("self_patch").prepare(ch, root=self._root, **kw))
        committer = self._committer or (lambda result: __import__("self_patch").commit(result, self._root))
        outcome = implement_change(change, self.log(), values=self.values(), model_fn=self._model_fn,
                                   preparer=preparer, committer=committer, publisher=by, on_step=step)
        if outcome["state"] == "applied":
            try:
                from improve_autopilot import AUTOPILOT

                AUTOPILOT.restart_pending = True
            except Exception:  # noqa: BLE001
                pass
        return outcome

    def deny_duplicates(self, *, by: str = "Owner") -> Dict[str, Any]:
        changes = self.agent_changes()
        by_id = {c["id"]: c for c in changes}
        denied = 0
        for change_id, original in group_duplicates(changes).items():
            try:
                self.log().reject(change_id, by, f"Duplicate of “{by_id[original]['title'][:90]}”")
                denied += 1
            except Exception:  # noqa: BLE001
                continue
        self._publish()
        return {"denied": denied}

    # --- jobs ------------------------------------------------------------------------------------

    def _start_job(self, kind: str, work: Callable[[Dict[str, Any]], None], total: int, **info: Any) -> Dict[str, Any]:
        with self._lock:
            if self._job and self._job["status"] == "running":
                raise ReviewError("A review job is already running — stop it first or wait for it to finish.")
            self._stop.clear()
            self._job = {"id": uuid.uuid4().hex[:8], "kind": kind, "status": "running", "total": total, "done": 0,
                         "started_at": time.time(), "ended_at": None, "now": "Starting", "log": [], **info,
                         "results": {"approved": 0, "denied": 0, "applied": 0, "failed": 0, "blocked": 0,
                                     "analyzed": 0, "duplicates": 0, "approved_only": 0}}
            job = self._job

        def run() -> None:
            try:
                work(job)
                with self._lock:
                    job["status"] = "stopped" if self._stop.is_set() else "done"
            except Exception as error:  # noqa: BLE001 - a failed job is a status, not a crash
                with self._lock:
                    job["status"], job["error"] = "error", f"{type(error).__name__}: {str(error)[:200]}"
                _LOG.warning("review job failed: %s", error)
            finally:
                with self._lock:
                    job["ended_at"] = time.time()
                    job["now"] = {"done": "Finished", "stopped": "Stopped"}.get(job["status"], job.get("error", ""))
                self._publish()

        if self._threaded:
            threading.Thread(target=run, name=f"nyx-review-{job['id']}", daemon=True).start()
        else:
            run()
        return self.job() or {}

    def _note(self, job: Dict[str, Any], text: str, now: str = "") -> None:
        with self._lock:
            job["log"] = (job["log"] + [{"ts": time.time(), "text": text[:240]}])[-60:]
            if now:
                job["now"] = now
        self._publish()

    def stop(self) -> Optional[Dict[str, Any]]:
        self._stop.set()
        return self.job()

    def analyze(self, *, ids: Optional[List[str]] = None, limit: int = DEFAULT_ANALYZE_LIMIT, web: bool = False,
                then_apply: bool = False, implement: Optional[bool] = None, by: str = "Owner") -> Dict[str, Any]:
        """Research every open change and recommend approve or deny. ``then_apply`` acts on the recommendations."""
        changes = self.agent_changes()
        open_changes = [c for c in changes if c["status"] in OPEN_STATUSES and (not ids or c["id"] in ids)]
        import self_patch

        applied = self_patch.applied_changes()
        open_changes = [c for c in open_changes if not (c["status"] == "approved" and c["id"] in applied)]
        duplicates = group_duplicates(changes)
        unique = [c for c in open_changes if c["id"] not in duplicates]
        todo = unique[: max(1, int(limit))]

        def work(job: Dict[str, Any]) -> None:
            nonlocal todo
            by_id = {c["id"]: c for c in changes}
            for change_id, original in duplicates.items():
                if ids and change_id not in ids:
                    continue
                self.store.update(change_id, verdict="deny", confidence=0.9, risk="low", already_done=False,
                                  reasons=f"Repeats “{by_id[original]['title'][:90]}” ({by_id[original]['status'].replace('_', ' ')}).",
                                  duplicate_of=original, analyzed_at=time.time(), research="")
                job["results"]["duplicates"] += 1
            self._note(job, f"{job['results']['duplicates']} duplicates found without asking a model", "Grouping the same ideas")
            if len(todo) > 5 and not self._stop.is_set():
                # Reworded repeats ("Add timeout handling to ASGI middleware" / "…cancellation guards to endpoints")
                # slip past word overlap; one model call groups them so each idea is researched once.
                same = self.cluster_same_ideas(todo)
                for change_id, original in same.items():
                    self.store.update(change_id, verdict="deny", confidence=0.8, risk="low", already_done=False,
                                      reasons=f"Same idea as “{by_id[original]['title'][:90]}”, which is reviewed instead.",
                                      duplicate_of=original, analyzed_at=time.time(), research="")
                    job["results"]["duplicates"] += 1
                if same:
                    todo = [c for c in todo if c["id"] not in same]
                    with self._lock:
                        job["total"] = len(todo)
                    self._note(job, f"{len(same)} more were the same idea in other words")
            for change in todo:
                if self._stop.is_set():
                    break
                self._note(job, f"Researching {change['title'][:90]}", f"Researching: {change['title'][:70]}")
                record = self.research_and_recommend(change, web=web)
                with self._lock:
                    job["done"] += 1
                    job["results"]["analyzed"] += 1
                verdict = (record.get("verdict") or "no verdict").upper()
                self._note(job, f"{verdict} ({record.get('risk') or '?'} risk) — {change['title'][:80]}")
            if then_apply and not self._stop.is_set():
                self._apply_recommendations(job, ids=[c["id"] for c in open_changes], implement=implement, by=by)

        return self._start_job("analyze_apply" if then_apply else "analyze", work, total=len(todo), web=web,
                               skipped=max(0, len(unique) - len(todo)), open=len(open_changes))

    def cluster_same_ideas(self, changes: List[Dict[str, Any]]) -> Dict[str, str]:
        """``{id: id_kept}`` for proposals that are the same idea in other words (one model call)."""
        numbered = {str(i + 1): c for i, c in enumerate(changes[:80])}
        listing = "\n".join(f"{n}. [{c.get('target', '')}] {_title_body(c)}" for n, c in numbered.items())
        prompt = ("These are proposed improvements to one codebase. Several say the same thing in different words.\n"
                  f"{listing}\n\nGroup the ones that are the same idea for the same file. Reply with JSON only: "
                  '{"groups": [[1, 4, 9], [2, 7]]} — list only groups of 2 or more, best-worded first.')
        try:
            reply = self._model(prompt, system="You group duplicate proposals. JSON only.", max_tokens=600)
        except Exception:  # noqa: BLE001 - no grouping, every change is researched on its own
            return {}
        start, end = reply.find("{"), reply.rfind("}")
        try:
            groups = json.loads(reply[start:end + 1]).get("groups", []) if start != -1 else []
        except (ValueError, AttributeError):
            return {}
        result: Dict[str, str] = {}
        for group in groups if isinstance(groups, list) else []:
            members = [numbered.get(str(n)) for n in (group if isinstance(group, list) else [])]
            members = [m for m in members if m is not None]
            if len(members) < 2 or len({(m.get("target") or "").lower() for m in members}) != 1:
                continue
            keep = members[0]
            for other in members[1:]:
                if other["id"] != keep["id"] and other["id"] not in result:
                    result[other["id"]] = keep["id"]
        return result

    def research_and_recommend(self, change: Dict[str, Any], *, web: bool = False) -> Dict[str, Any]:
        research = file_excerpt(str(change.get("target", "")), f"{change.get('title', '')} {change.get('description', '')}", self._root)
        if not research["ok"]:
            reason = research["error"] + (" Nyx can't change it automatically; approve only if you'll edit it by hand."
                                          if research.get("protected") else "")
            return self.store.update(change["id"], verdict="deny", confidence=0.95, risk="high" if research.get("protected") else "medium",
                                     already_done=False, reasons=reason, research="", analyzed_at=time.time())
        notes = self._web_fn(f"python {change.get('title', '')}"[:160]) if web else ""
        try:
            # "detailed thinking off" stops NVIDIA's Nemotron from writing its reasoning before the JSON.
            reply = self._model(verdict_prompt(change, research, notes),
                                system="detailed thinking off\nYou review proposed code changes. Reply with JSON only, no reasoning.",
                                max_tokens=1200)
            verdict = parse_verdict(reply)
        except Exception as error:  # noqa: BLE001 - no model: say so, recommend nothing
            return self.store.update(change["id"], verdict=None, confidence=None, risk=None, already_done=False,
                                     reasons=f"Could not research this: {str(error)[:200]}", research="", analyzed_at=time.time())
        summary = f"Read {research['file']} ({research['lines']} lines)"
        if research["excerpt"]:
            summary += f"; related code found for: {', '.join(research['matched_words'][:6])}"
        if notes:
            summary += "; searched the web"
        return self.store.update(change["id"], **verdict, research=summary, web=notes[:1200], analyzed_at=time.time())

    def apply(self, *, decisions: Optional[Dict[str, str]] = None, implement: Optional[bool] = None,
              by: str = "Owner") -> Dict[str, Any]:
        """Act on explicit decisions, or on the stored recommendations when none are given."""
        pending = decisions or {}
        total = len(pending) or self.queue(limit=5000)["counts"]["open"]

        def work(job: Dict[str, Any]) -> None:
            self._apply_recommendations(job, decisions=pending or None, implement=implement, by=by)

        return self._start_job("apply", work, total=total)

    def _apply_recommendations(self, job: Dict[str, Any], *, ids: Optional[List[str]] = None,
                               decisions: Optional[Dict[str, str]] = None, implement: Optional[bool] = None,
                               by: str = "Owner") -> None:
        records = self.store.all()
        items = self.queue(limit=5000)["items"]
        if decisions is None:
            decisions = {i["id"]: (records.get(i["id"], {}).get("verdict") or i.get("recommendation") or "")
                         for i in items if not ids or i["id"] in ids}
        should_implement = bool(self.values().get("implement_approved", True)) if implement is None else implement
        with self._lock:
            job["total"] = len([d for d in decisions.values() if d in ("approve", "deny")])
            job["done"] = 0
        by_id = {i["id"]: i for i in items}
        # Denials first (cheap), then approvals one at a time (each may run the tests).
        for change_id, decision in sorted(decisions.items(), key=lambda kv: kv[1] != "deny"):
            if self._stop.is_set():
                break
            if decision not in ("approve", "deny") or change_id not in by_id:
                continue
            title = by_id[change_id]["title"][:80]
            try:
                if decision == "deny":
                    reason = records.get(change_id, {}).get("reasons") or "Denied in the Improve tab"
                    self.log().reject(change_id, by, reason[:400])
                    job["results"]["denied"] += 1
                    self._note(job, f"Denied — {title}")
                else:
                    self._note(job, f"Approving — {title}", f"Approving: {title[:60]}")
                    change = self._change(change_id)
                    if change["status"] == "draft":
                        self.log().submit_for_review(change_id)
                    if change["status"] in ("draft", "in_review"):
                        self.log().approve(change_id, by)
                    job["results"]["approved"] += 1
                    if not should_implement:
                        self.store.update(change_id, implement={"state": "approved_only", "at": time.time(),
                                                                "message": "Approved only — “Implement approved changes” is off."})
                        job["results"]["approved_only"] += 1
                        continue
                    self._note(job, f"Implementing — {title}", f"Implementing: {title[:60]}")
                    outcome = self._implement_one(self._change(change_id), by)
                    self.store.update(change_id, implement={**outcome, "at": time.time()})
                    job["results"][outcome["state"] if outcome["state"] in ("applied", "failed", "blocked") else "failed"] += 1
                    self._note(job, f"{outcome['state'].capitalize()} — {title}: {outcome['message'][:120]}")
            except Exception as error:  # noqa: BLE001 - one bad change must not stop the rest
                self._note(job, f"Skipped {title}: {str(error)[:120]}")
            finally:
                with self._lock:
                    job["done"] += 1


# ---------------------------------------------------------------------------
# "Apply all" typed into the Improve box, or said in chat
# ---------------------------------------------------------------------------

_SCHEDULE_WORDS = re.compile(r"\b(study|detox|rest|loop|until i stop|overnight|hours?|minutes?|mins?|days?|\d+\s*h\b)", re.I)
_TARGETS = r"(all|every|everything|these|them|those|pending|changes?|in[ -]?review|queue|improvements?|proposals?|duplicates?)"


def review_intent(text: str) -> Optional[Dict[str, Any]]:
    """Whether words typed into the Improve box are about the review queue rather than a new schedule.

    "Apply all", "approve these changes in review", "deny the duplicates", "analyze everything in review".
    A duration or a phase word ("for 22 hours", "study") keeps it a schedule.
    """
    lower = (text or "").strip().lower()
    if not lower or _SCHEDULE_WORDS.search(lower):
        return None
    if re.search(rf"\b(deny|reject|decline|discard|dismiss|clear)\b.*\b{_TARGETS}", lower):
        return {"action": "deny_duplicates" if "duplicate" in lower else "deny_all"}
    wants_apply = re.search(rf"\b(apply|approve|accept|implement|merge|auto[ -]?apply|auto[ -]?approve)\b", lower)
    wants_check = re.search(r"\b(analy[sz]e|review|check|research|go through|look through)\b", lower)
    if wants_apply and re.search(rf"\b{_TARGETS}\b", lower):
        return {"action": "analyze_apply"}
    if wants_check and re.search(rf"\b{_TARGETS}\b", lower):
        return {"action": "analyze"}
    if wants_apply:
        # "Apply Image Generation and NSFW Request Handling": a change named by its title.
        query = re.sub(r"^\s*(please\s+)?(auto[ -]?)?(apply|approve|accept|implement|merge)\s+", "", lower).strip()
        if len(tokens(query)) >= 2:
            return {"action": "apply_matching", "query": query}
    return None


def matching_changes(query: str, changes: List[Dict[str, Any]], floor: float = 0.3) -> List[Dict[str, Any]]:
    scored = sorted(((similarity(query, f"{c.get('title', '')} {c.get('description', '')}"), c) for c in changes
                     if c.get("status") in OPEN_STATUSES), key=lambda pair: -pair[0])
    return [c for score, c in scored if score >= floor][:10]


def run_intent(intent: Dict[str, Any], queue: Optional["ReviewQueue"] = None, by: str = "Owner") -> Dict[str, Any]:
    q = queue or REVIEW_QUEUE
    action = intent.get("action")
    if action == "deny_duplicates":
        result = q.deny_duplicates(by=by)
        return {"message": f"Denied {result['denied']} duplicate changes.", "result": result}
    if action == "deny_all":
        items = q.queue(limit=5000)["items"]
        job = q.apply(decisions={i["id"]: "deny" for i in items}, by=by)
        return {"message": f"Denying all {len(items)} open changes.", "job": job}
    if action == "analyze":
        job = q.analyze(by=by)
        return {"message": "Researching every open change — recommendations appear in the review queue.", "job": job}
    if action == "analyze_apply":
        job = q.analyze(then_apply=True, by=f"{by} (asked Nyx to check and apply)")
        return {"message": "Checking every open change first, then approving the good ones and denying the rest.", "job": job}
    if action == "apply_matching":
        found = matching_changes(str(intent.get("query", "")), q.agent_changes())
        if not found:
            return {"message": f"No open change matches “{intent.get('query', '')}”."}
        job = q.analyze(ids=[c["id"] for c in found], then_apply=True, by=f"{by} (asked Nyx to check and apply)")
        return {"message": f"Checking and applying {len(found)} matching change(s): " + "; ".join(c['title'][:60] for c in found[:3]),
                "job": job}
    return {"message": "Nothing to do."}


REVIEW_QUEUE = ReviewQueue()
