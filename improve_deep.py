"""Improve → Deep & specific mode: the owner's own list of improvements, estimated, then worked through (Request J4).

The owner (2026-09-16): "In improve allow a deep and specific mode, clicking this shows a big box and I can paste
or write specific improvements and such and it auto generates the time it thinks it will take and can
iterate if needed."

* :func:`plan` splits the text into items (numbered/bulleted lines, paragraphs, or sentences), guesses the file
  each one touches from the words and the repo map, and estimates minutes from the size of the ask — offline,
  so the estimate updates as the owner types.
* :class:`DeepJobs` works through the items one at a time: research the target, file the change in the review
  gate (these are the owner's own words, so they start approved when the owner said "apply"), write and test it
  in the sandbox, let the critic read the real diff, apply. A failed attempt is retried with its error as
  feedback up to ``iterations`` times. When the work runs past the estimate it **extends** the estimate (and
  says so) if the owner allowed that, or stops and leaves the rest in the review queue.

Only Python modules can be edited automatically today (``self_patch``). An item about the UI is still filed,
researched and estimated, and says plainly that it needs a UI edit.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import PROJECT_DIR, data_path

MAX_ITEMS = 25
MAX_ITERATIONS = 5

_UI_WORDS = re.compile(r"\b(tab|button|ui|screen|page|panel|css|style|colou?r|layout|animation|hover|click|drag|drop|"
                       r"box|sheet|menu|icon|font|theme|dark mode|frontend|react|tsx|view|gauge|chart|aesthetic)\b", re.I)
_LARGE = re.compile(r"\b(new (tab|mode|page|system|feature|view)|redesign|rewrite|integrat|refactor|overhaul|architecture|"
                    r"migrat|multi|several|all|every|whole|entire|website|site|3d|game|pipeline)\w*", re.I)
_SMALL = re.compile(r"\b(rename|typo|label|text|wording|colou?r|spacing|tooltip|placeholder|default|log(ging)?|comment|"
                    r"docstring|message)\b", re.I)


class DeepError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def split_items(text: str) -> List[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    lines = [l.rstrip() for l in raw.splitlines()]
    bullet = re.compile(r"^\s*(?:[-*•]|\d+[.)]|\[[ x]\])\s+")
    if sum(1 for l in lines if bullet.match(l)) >= 2:
        items: List[str] = []
        for line in lines:
            if bullet.match(line):
                items.append(bullet.sub("", line).strip())
            elif line.strip() and items:
                items[-1] += " " + line.strip()
            elif line.strip():
                items.append(line.strip())
        return [i for i in items if len(i) > 3][:MAX_ITEMS]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    if len(paragraphs) >= 2:
        return [" ".join(p.split()) for p in paragraphs][:MAX_ITEMS]
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\s+(?=Also\b)", " ".join(raw.split())) if s.strip()]
    items = []
    for sentence in sentences:
        if items and (len(sentence) < 40 or re.match(r"^(and|then|so|but|it|this)\b", sentence, re.I)):
            items[-1] += " " + sentence
        else:
            items.append(sentence)
    return items[:MAX_ITEMS]


def guess_target(item: str, repo_map: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    named = re.findall(r"\b([\w/-]+\.(?:py|tsx|ts|css))\b", item)
    if named:
        name = named[0]
        return {"target": name, "kind": "python" if name.endswith(".py") else "ui", "why": "named in the text"}
    if repo_map is None:
        try:
            from improvement_engine import build_repo_map

            repo_map = build_repo_map()
        except Exception:  # noqa: BLE001
            repo_map = []
    import improve_review

    words = improve_review.tokens(item)
    best, best_score = None, 0.0
    for row in repo_map:
        module_words = improve_review.tokens(f"{row['module'].replace('_', ' ').replace('.py', '')} {row.get('doc', '')}")
        name_words = improve_review.tokens(row["module"].replace("_", " ").replace(".py", ""))
        score = 2 * len(words & name_words) + len(words & module_words)
        if score > best_score:
            best, best_score = row, score
    ui = bool(_UI_WORDS.search(item))
    if best is not None and best_score >= 2 and not (ui and best_score < 3):
        prefix = f"{best['dir']}/" if best.get("dir") else ""
        return {"target": prefix + best["module"], "kind": "python", "why": f"matches {best['module']}"}
    return {"target": "", "kind": "ui" if ui else "unknown", "why": "a UI change" if ui else "no clear file"}


def estimate_minutes(item: str, kind: str, iterations: int = 1) -> float:
    words = len(item.split())
    base = 8.0
    if _LARGE.search(item) or words > 60:
        base = 20.0
    elif _SMALL.search(item) and words < 25:
        base = 3.0
    base += min(15.0, words / 12)          # a longer ask is usually a bigger one
    if kind == "ui":
        base *= 1.4                        # UI work also needs a build and a look
    if kind == "unknown":
        base += 4.0                        # time to find where it goes
    base += 2.0                            # sandbox tests
    return round(base * (1 + 0.5 * (max(1, iterations) - 1)), 1)


def plan(text: str, iterations: int = 2, repo_map: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    iterations = max(1, min(MAX_ITERATIONS, int(iterations or 1)))
    items = []
    for index, item in enumerate(split_items(text)):
        target = guess_target(item, repo_map)
        items.append({"index": index, "text": item[:1200], **target,
                      "minutes": estimate_minutes(item, target["kind"], iterations),
                      "auto": target["kind"] == "python"})
    total = round(sum(i["minutes"] for i in items), 1)
    return {"items": items, "iterations": iterations, "total_minutes": total,
            "auto_count": sum(1 for i in items if i["auto"]), "manual_count": sum(1 for i in items if not i["auto"])}


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


@dataclass
class DeepJob:
    job_id: str
    text: str
    items: List[Dict[str, Any]]
    iterations: int
    apply: bool
    extend: bool
    estimate_minutes: float
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    status: str = "running"            # running | done | stopped | out_of_time | error
    now: str = "Starting"
    extended_minutes: float = 0.0
    log: List[Dict[str, Any]] = field(default_factory=list)

    def view(self) -> Dict[str, Any]:
        data = asdict(self)
        elapsed = (self.ended_at or time.time()) - self.started_at
        done = [i for i in self.items if i.get("state") in ("applied", "filed", "failed", "blocked", "skipped")]
        remaining = [i for i in self.items if i.get("state") in (None, "queued", "working")]
        spent_per_item = elapsed / 60 / len(done) if done else None
        data["elapsed_minutes"] = round(elapsed / 60, 1)
        data["budget_minutes"] = round(self.estimate_minutes + self.extended_minutes, 1)
        # Re-estimate from how long finished items really took.
        data["remaining_minutes"] = round(sum((spent_per_item or i["minutes"]) if spent_per_item else i["minutes"]
                                              for i in remaining), 1)
        data["log"] = self.log[-40:]
        return data


class DeepJobs:
    def __init__(self, *, queue: Any = None, threaded: bool = True, clock: Callable[[], float] = time.time,
                 store_path: Optional[Path] = None, repo_map: Optional[List[Dict[str, Any]]] = None) -> None:
        self._queue = queue
        self._threaded = threaded
        self._clock = clock
        self._path = store_path
        self._repo_map = repo_map
        self._lock = threading.RLock()
        self._jobs: Dict[str, DeepJob] = {}
        self._stop = threading.Event()

    def queue(self) -> Any:
        if self._queue is not None:
            return self._queue
        from improve_review import REVIEW_QUEUE

        return REVIEW_QUEUE

    def current(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: -j.started_at)
            return jobs[0].view() if jobs else None

    def stop(self) -> Optional[Dict[str, Any]]:
        self._stop.set()
        return self.current()

    def start(self, text: str, *, items: Optional[List[Dict[str, Any]]] = None, iterations: int = 2, apply: bool = True,
              extend: bool = True) -> Dict[str, Any]:
        with self._lock:
            if any(j.status == "running" for j in self._jobs.values()):
                raise DeepError("A deep improvement run is already going — stop it first.")
        planned = plan(text, iterations, self._repo_map)
        if items:
            # The owner may have edited the list, fixed a file or removed an item before pressing Start.
            by_index = {i["index"]: i for i in planned["items"]}
            chosen = []
            for index, item in enumerate(items[:MAX_ITEMS]):
                base = by_index.get(item.get("index"), {})
                text_i = str(item.get("text") or base.get("text") or "").strip()
                if not text_i:
                    continue
                target = str(item.get("target") if item.get("target") is not None else base.get("target", "")).strip()
                kind = "python" if target.endswith(".py") else ("ui" if target else guess_target(text_i, self._repo_map)["kind"])
                chosen.append({"index": index, "text": text_i[:1200], "target": target, "kind": kind,
                               "minutes": float(item.get("minutes") or estimate_minutes(text_i, kind, planned["iterations"])),
                               "auto": kind == "python"})
            planned["items"] = chosen
            planned["total_minutes"] = round(sum(i["minutes"] for i in chosen), 1)
        if not planned["items"]:
            raise DeepError("Write at least one improvement.")
        job = DeepJob(job_id=uuid.uuid4().hex[:8], text=text[:20000], items=[dict(i, state="queued") for i in planned["items"]],
                      iterations=planned["iterations"], apply=bool(apply), extend=bool(extend),
                      estimate_minutes=planned["total_minutes"], started_at=self._clock())
        with self._lock:
            self._stop.clear()
            self._jobs[job.job_id] = job
        self._note(job, f"Planned {len(job.items)} improvement(s), about {job.estimate_minutes:g} min")
        if self._threaded:
            threading.Thread(target=self._run, args=(job,), name=f"nyx-deep-{job.job_id}", daemon=True).start()
        else:
            self._run(job)
        return job.view()

    def _note(self, job: DeepJob, text: str) -> None:
        with self._lock:
            job.log.append({"ts": self._clock(), "text": text[:300]})
            job.now = text[:160]
        try:
            from agent_events import publish_ui

            publish_ui("improve.deep", job=job.view())
        except Exception:  # noqa: BLE001
            pass
        self._save()

    def _save(self) -> None:
        try:
            path = self._path or data_path("autopilot/deep_jobs.json")
            with self._lock:
                jobs = sorted(self._jobs.values(), key=lambda j: -j.started_at)[:10]
                payload = {"jobs": [j.view() for j in jobs]}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def _run(self, job: DeepJob) -> None:
        from change_review import ChangeOrigin

        queue = self.queue()
        log = queue.log()
        try:
            for item in job.items:
                if self._stop.is_set():
                    job.status = "stopped"
                    break
                elapsed = (self._clock() - job.started_at) / 60
                budget = job.estimate_minutes + job.extended_minutes
                if elapsed > budget:
                    if job.extend:
                        remaining = sum(i["minutes"] for i in job.items if i.get("state") == "queued")
                        with self._lock:
                            job.extended_minutes += round(remaining, 1)
                        self._note(job, f"Taking longer than estimated — extended by {remaining:g} min")
                    else:
                        job.status = "out_of_time"
                        self._note(job, "Out of the estimated time — the rest stay in the review queue")
                        break
                item["state"], item["started_at"] = "working", self._clock()
                self._note(job, f"Item {item['index'] + 1}: {item['text'][:90]}")
                title = item["text"].split(". ")[0][:90]
                # The change log's target is a flat name; self_patch finds providers/x.py from x.py.
                target = (item.get("target") or "").replace("\\", "/").split("/")[-1]
                try:
                    change = log.propose(title=f"Improve {target or 'Nyx'}: {title}",
                                         description=item["text"] + "\n\n(From the owner's Deep & specific list.)",
                                         author="Owner (Deep & specific mode)", target=target or "base_ai",
                                         origin=ChangeOrigin.AGENT)
                except Exception as error:  # noqa: BLE001 - e.g. an invalid target
                    item["state"], item["message"] = "skipped", f"Could not file it: {error}"
                    self._note(job, item["message"])
                    continue
                item["change_id"] = change.change_id
                if not item.get("auto"):
                    item["state"] = "filed"
                    item["message"] = ("Filed in the review queue. It needs a UI edit, which Nyx can't apply by itself yet."
                                       if item.get("kind") == "ui" else "Filed in the review queue — say which file it belongs to.")
                    self._note(job, item["message"])
                    continue
                research = queue.research_and_recommend(change.as_dict())
                item["research"] = research.get("reasons", "")[:400]
                if not job.apply:
                    item["state"], item["message"] = "filed", "Researched and filed for your approval."
                    self._note(job, item["message"])
                    continue
                try:
                    log.submit_for_review(change.change_id)
                    log.approve(change.change_id, "Owner (Deep & specific mode)")
                except Exception:  # noqa: BLE001
                    pass
                from improve_review import implement_change

                outcome = implement_change(log.get(change.change_id).as_dict(), log, values=queue.values(),
                                           model_fn=getattr(queue, "_model_fn", None),
                                           preparer=getattr(queue, "_preparer", None), committer=getattr(queue, "_committer", None),
                                           publisher="Owner (Deep & specific mode)", retries=job.iterations - 1,
                                           on_step=lambda text, i=item: self._note(job, f"Item {i['index'] + 1}: {text}"))
                queue.store.update(change.change_id, implement={**outcome, "at": self._clock()})
                item["state"], item["message"] = outcome["state"], outcome["message"][:400]
                item["lines"] = outcome.get("lines")  # which file, how many lines (Request R9)
                item["seconds"] = round(self._clock() - item["started_at"], 1)
                self._note(job, f"Item {item['index'] + 1} {outcome['state']}: {outcome['message'][:120]}")
            if job.status == "running":
                job.status = "done"
        except Exception as error:  # noqa: BLE001
            job.status = "error"
            self._note(job, f"Stopped by an error: {type(error).__name__}: {str(error)[:200]}")
        finally:
            job.ended_at = self._clock()
            applied = sum(1 for i in job.items if i.get("state") == "applied")
            self._note(job, f"Finished: {applied} applied, {sum(1 for i in job.items if i.get('state') == 'filed')} filed, "
                            f"{sum(1 for i in job.items if i.get('state') in ('failed', 'blocked'))} not applied")
            if applied:
                try:
                    from improve_autopilot import AUTOPILOT

                    AUTOPILOT.restart_pending = True
                except Exception:  # noqa: BLE001
                    pass


DEEP_JOBS = DeepJobs()
