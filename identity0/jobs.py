"""Background jobs for Identity 0's own model: build the corpus, distill from the teacher, train, serve.

Each job runs in its own process (``python -m identity0.jobs run <id>``) so torch, big downloads and a
GPU at full power never touch the app process: the chat stays responsive and a crash (out of memory,
a bad driver) costs the job, not Nyx. Progress lives in ``kahuna/jobs/<id>.json``; cancelling drops a
``<id>.cancel`` file the job checks between steps (every few seconds while training).

``train_nano`` is the whole pipeline behind the "Train the Nano seed" button: corpus (if empty) →
teacher answers (if a permitted teacher is up) → training → register → promote the very first version.

A job whose process is gone (the PC slept, the app or the session that started it closed) is shown as
``interrupted``, never as running forever; ``resume`` carries a training job on from its last checkpoint
(weights, optimiser and schedule are saved every few minutes). Jobs are started outside the parent's
process group so closing whatever started them does not kill a long run.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from identity0 import state

KINDS = ("corpus", "distill", "train_nano", "shard", "serve")
_GPU_CACHE: Dict[str, Any] = {}
_JOB_ID = re.compile(r"^[a-z_]+-[0-9a-f]{8}$")
VERSION = re.compile(r"^[a-z0-9][a-z0-9._-]{0,40}$")
_ACTIVE = ("queued", "running")


class JobError(RuntimeError):
    pass


def _dir() -> Path:
    return state.path("jobs/.keep").parent


def _file(job_id: str) -> Path:
    if not _JOB_ID.match(job_id or ""):
        raise JobError("No such job.")
    return _dir() / f"{job_id}.json"


def _alive(pid: Any) -> bool:
    """Whether the job's process still exists (and is a Python process, so a reused pid does not count)."""
    try:
        import psutil
    except ImportError:  # cannot tell: never mark a job dead on a guess
        return True
    try:
        process = psutil.Process(int(pid))
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE and "python" in process.name().lower()
    except (psutil.Error, ValueError, TypeError):
        return False


def _refresh(job: Dict[str, Any]) -> Dict[str, Any]:
    """A job still marked active whose process died is marked interrupted (resumable), once."""
    if job.get("state") in _ACTIVE and job.get("pid") and not _alive(job["pid"]):
        job.update(state="interrupted", finished=time.time(),
                   message="Stopped unexpectedly (the PC slept or what started it closed). Resume carries on "
                           "from the last checkpoint.")
        try:
            _write(job)
        except OSError:
            pass
    return job


def _read(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_file(job_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, JobError):
        return None


def _write(job: Dict[str, Any]) -> None:
    tmp = _file(job["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, _file(job["id"]))


def requirements() -> Dict[str, Any]:
    """What this PC has for training — without importing torch here."""
    missing = [name for name in ("torch", "safetensors", "tokenizers") if importlib.util.find_spec(name) is None]
    if not _GPU_CACHE:
        gpu, vram = "", 0.0
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            out = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=5, creationflags=flags).stdout.strip()
            if out:
                name, total = out.splitlines()[0].rsplit(",", 1)
                gpu, vram = name.strip(), round(float(total) / 1024, 1)
        except Exception:  # noqa: BLE001 - no NVIDIA GPU is a valid answer
            pass
        _GPU_CACHE.update(gpu=gpu, vram_gb=vram)
    return {"torch": "torch" not in missing, "cuda": bool(_GPU_CACHE.get("gpu")), "gpu": _GPU_CACHE.get("gpu", ""),
            "vram_gb": _GPU_CACHE.get("vram_gb", 0.0), "missing": missing}


def start(kind: str, params: Optional[Dict[str, Any]] = None, *, spawn: bool = True) -> Dict[str, Any]:
    if kind not in KINDS:
        raise JobError(f"Unknown job: {kind}")
    if kind in ("train_nano", "distill", "shard") and requirements()["missing"]:
        raise JobError("The training kit is not installed: " + ", ".join(requirements()["missing"]))
    params = dict(params or {})
    _check_params(kind, params)
    running = [j for j in list_jobs() if j["state"] in _ACTIVE and j["kind"] == kind]
    if running:
        raise JobError(f"A {kind} job is already running ({running[0]['id']}).")
    job = {"id": f"{kind}-{uuid.uuid4().hex[:8]}", "kind": kind, "params": params, "state": "queued",
           "progress": 0.0, "message": "Waiting to start…", "started": time.time(), "finished": None, "pid": None,
           "log": [], "result": None}
    _write(job)
    if spawn:
        pid = _spawn(job["id"])
        job = _read(job["id"]) or job  # the job may already have written "running" itself
        job["pid"] = job.get("pid") or pid
        _write(job)
    return job


def _check_params(kind: str, params: Dict[str, Any]) -> None:
    """Paths and names from the UI stay inside Big Kahuna's own folders."""
    version = params.get("version")
    if version is not None and not VERSION.match(str(version)):
        raise JobError("A version name is lowercase letters, digits, dots, dashes or underscores.")
    if kind == "shard":
        from identity0.model import registry

        root = registry.models_dir().resolve()
        if not params.get("dir"):
            raise JobError("Say which model folder to shard.")
        for key in ("dir", "out"):
            if not params.get(key):
                continue
            raw = Path(str(params[key]))
            target = (raw if raw.is_absolute() else root / raw).resolve()
            if root not in target.parents:
                raise JobError("Only Big Kahuna's own model folders can be sharded.")
            params[key] = str(target)


def _spawn(job_id: str) -> int:
    base = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
    project = Path(__file__).resolve().parent.parent
    log = open(_dir() / f"{job_id}.log", "a", encoding="utf-8")
    command = [sys.executable, "-m", "identity0.jobs", "run", job_id]
    kwargs: Dict[str, Any] = dict(cwd=str(project), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if os.name != "nt":
        return subprocess.Popen(command, start_new_session=True, **kwargs).pid
    # Outside the starter's process group and job object, so closing the app or a terminal does not end a run.
    detached = base | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
    try:
        return subprocess.Popen(command, creationflags=detached, **kwargs).pid
    except OSError:  # the job object does not allow breakaway: start it normally
        return subprocess.Popen(command, creationflags=base, **kwargs).pid


def resume(job_id: str, *, spawn: bool = True) -> Dict[str, Any]:
    """Carry an interrupted, failed or stopped training job on from its last checkpoint."""
    job = get(job_id)
    if job is None:
        raise JobError("No such job.")
    if job["kind"] != "train_nano":
        raise JobError("Only training jobs can be resumed; start this one again instead.")
    if job["state"] in _ACTIVE:
        raise JobError("That job is still running.")
    version = str(job.get("version") or (job.get("params") or {}).get("version") or "")
    if not version:
        raise JobError("That job never reached training, so there is nothing to resume: start a new one.")
    params = {**(job.get("params") or {}), "version": version, "resume": True, "resumed_from": job_id}
    return start("train_nano", params, spawn=spawn)


def recover(max_age_hours: float = 48.0) -> Optional[Dict[str, Any]]:
    """Pick training back up when the engine starts, if a run was cut short (a sleep, a crash, a restart).

    Training a model here takes hours; the owner should not have to notice that the PC slept and press
    a button. Only the newest interrupted run is resumed, only when nothing is training already, and
    only when the run is recent enough to still be what the owner wanted.
    """
    try:
        if not state.get_settings().get("auto_resume_training", True):
            return None
        jobs = list_jobs()
        if any(j["kind"] == "train_nano" and j["state"] in _ACTIVE for j in jobs):
            return None
        already = {str((j.get("params") or {}).get("resumed_from") or "") for j in jobs}
        for job in jobs:  # newest first
            if job["kind"] != "train_nano" or job["state"] != "interrupted":
                continue
            if job["id"] in already or not float(job.get("progress") or 0):
                continue  # already picked up once, or it never got as far as a checkpoint
            when = float(job.get("finished") or job.get("started") or 0)
            if time.time() - when > max_age_hours * 3600:
                return None
            return resume(job["id"])
    except (JobError, OSError, ValueError):
        return None
    return None


def get(job_id: str) -> Optional[Dict[str, Any]]:
    job = _read(job_id)
    return _refresh(job) if job else None


def list_jobs(limit: int = 30) -> List[Dict[str, Any]]:
    jobs = []
    for path in sorted(_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            jobs.append(_refresh(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return jobs


def cancel(job_id: str) -> Dict[str, Any]:
    job = get(job_id)
    if job is None:
        raise JobError("No such job.")
    if job["state"] not in _ACTIVE:
        return job
    (_dir() / f"{job_id}.cancel").write_text("stop", encoding="utf-8")
    return {**job, "message": "Stopping…"}


# --- the worker side (runs in the job process) ------------------------------------------------------


class Reporter:
    def __init__(self, job: Dict[str, Any]) -> None:
        self.job = job
        self._last = 0.0

    def stop(self) -> bool:
        return (_dir() / f"{self.job['id']}.cancel").exists()

    def __call__(self, message: str, fraction: float, metrics: Optional[Dict[str, Any]] = None) -> None:
        self.job.update(message=message[:300], progress=round(max(0.0, min(1.0, fraction)), 4), state="running")
        if metrics:
            self.job["metrics"] = {k: v for k, v in metrics.items() if isinstance(v, (int, float, str))}
        now = time.time()
        if now - self._last > 2 or fraction >= 1.0:
            self._last = now
            self.job["log"] = (self.job.get("log", []) + [f"{time.strftime('%H:%M:%S')} {message[:200]}"])[-40:]
            _write(self.job)


def _corpus_dir() -> Path:
    return state.path("corpus/.keep").parent


def run_corpus(params: Dict[str, Any], report: Reporter) -> Dict[str, Any]:
    from identity0.corpus import sources
    from identity0.corpus.store import CorpusStore

    cap = float(params.get("cap_mb", state.get_settings().get("corpus_cap_mb", 2048)))
    store = CorpusStore(_corpus_dir(), cap_mb=cap)
    counts: Dict[str, int] = {}

    def keep(source: str, items, total: int, base: float, span: float) -> None:
        done = 0
        for item in items:
            if report.stop():
                return
            result = store.add(item["text"], source=source, title=item.get("title", ""), url=item.get("url", ""))
            counts[f"{source}:{result}"] = counts.get(f"{source}:{result}", 0) + 1
            done += 1
            report(f"{source}: {done}/{total} ({item.get('title', '')[:60]})", base + span * done / max(1, total))
            if result == "full":
                return

    def safely(name: str, work: Callable[[], None]) -> None:
        # One source being down (gutendex timing out, Wikidata busy) must not cost the others.
        try:
            work()
        except Exception as error:  # noqa: BLE001
            counts[f"{name}:error"] = str(error)[:160]  # type: ignore[assignment]
            report(f"{name} is unavailable right now ({type(error).__name__}); carrying on", report.job.get("progress", 0))

    have = store.stats()["by_source"]
    # Enough text to actually train on: a 32M-parameter model wants tens of millions of tokens, and
    # 800 articles is one million. Featured articles first, then Good ones, fetched a few at a time.
    full_n, intro_n = int(params.get("wiki_full", 12000)), int(params.get("wiki_intros", 3000))
    workers = max(1, min(8, int(params.get("workers", 4))))
    if have.get("wikipedia", 0) < (full_n + intro_n) * 0.9:
        titles: List[str] = []

        def pick() -> None:
            wanted = sources.article_titles(int((full_n + intro_n) * 1.3))
            # Skip what is already collected instead of downloading it again to find out it is a duplicate.
            titles.extend(t for t in wanted
                          if not store.has("wikipedia", f"https://en.wikipedia.org/wiki/{t.replace(' ', '_')}"))

        safely("wikipedia titles", pick)
        safely("wikipedia", lambda: keep("wikipedia", sources.wikipedia_articles(titles[:full_n], stop=report.stop,
                                                                                 workers=workers),
                                         min(full_n, len(titles)), 0.0, 0.62))
        safely("wikipedia intros", lambda: keep("wikipedia", sources.wikipedia_intros(titles[full_n:full_n + intro_n]),
                                                intro_n, 0.62, 0.08))
    books = int(params.get("books", 150))
    if have.get("gutenberg", 0) < books * 0.9:
        safely("gutenberg", lambda: keep("gutenberg", sources.gutenberg_books(
            books, stop=report.stop, skip=lambda url: store.has("gutenberg", url)), books, 0.70, 0.20))
    films = int(params.get("films", 400))
    safely("films", lambda: keep("wikipedia", sources.films(films), films, 0.90, 0.06))
    papers = int(params.get("arxiv", 400))
    if have.get("arxiv", 0) < papers * 0.9:
        safely("arxiv", lambda: keep("arxiv", sources.arxiv_abstracts("cat:cs.AI OR cat:cs.LG OR cat:cs.CL", papers),
                                     papers, 0.96, 0.04))
    store.flush()
    (_corpus_dir() / "CARD.md").write_text(store.card(), encoding="utf-8")
    report("Corpus ready", 1.0)
    return {"counts": counts, "stats": store.stats()}


def run_distill(params: Dict[str, Any], report: Reporter) -> Dict[str, Any]:
    import random

    from identity0.corpus import dataset, sources
    from identity0.corpus.store import CorpusStore

    teacher = str(params.get("teacher") or _local_teacher() or "")
    if not teacher:
        from identity0 import members

        if members.maybe_start_ollama():  # it is installed but not up: bring it back and wait for it
            report("Starting Ollama…", 0.01)
            for _ in range(30):
                time.sleep(2)
                teacher = str(_local_teacher() or "")
                if teacher:
                    break
    if not teacher:
        raise JobError("No permitted teacher is running (start Ollama with an open-license model such as qwen3.5).")
    report(f"Teacher: {teacher}", 0.02)
    store = CorpusStore(_corpus_dir(), cap_mb=1e9)
    rng = random.Random(11)
    prompts = dataset.grounded_prompts(store.documents(), int(params.get("grounded", 400)), rng)
    if state.get_settings().get("train_on_chats", True):
        prompts += [{"prompt": q, "source": "chats"} for q in sources.owner_questions(int(params.get("chats", 150)))]
    rng.shuffle(prompts)
    out = state.path("datasets/sft.jsonl")
    return dataset.distill(prompts, teacher=teacher, out=out, minutes=float(params.get("minutes", 25)),
                           progress=lambda m, f: report(m, f), stop=report.stop)


def _local_teacher() -> Optional[str]:
    """The best permitted local teacher that is running (the configured Ollama model first)."""
    try:
        import requests
        import local_models
        from config import SETTINGS
        from identity0.policy import may_train_on

        names = [m.get("name", "") for m in requests.get(local_models.host() + "/api/tags", timeout=2).json().get("models", [])]
    except Exception:  # noqa: BLE001
        return None
    ordered = sorted(names, key=lambda n: 0 if n == SETTINGS.ollama_model else 1)
    for name in ordered:
        if may_train_on("ollama", name)[0] and "embed" not in name:
            return f"ollama:{name}"
    return None


def run_train(params: Dict[str, Any], report: Reporter) -> Dict[str, Any]:
    from identity0.corpus import dataset
    from identity0.corpus.store import CorpusStore
    from identity0.model import registry

    store = CorpusStore(_corpus_dir(), cap_mb=1e9)
    if store.stats()["documents"] < 50:
        report("Building the corpus first…", 0.01)
        run_corpus(params.get("corpus", {}), report)
    sft_path = state.path("datasets/sft.jsonl")
    if not sft_path.exists() and params.get("distill", True) and _local_teacher():
        report("Asking the teacher for answers first…", 0.05)
        run_distill({"minutes": float(params.get("distill_minutes", 20))}, report)
    from identity0.model import train

    version = str(params.get("version") or registry.next_version("nano"))
    if not VERSION.match(version):
        raise JobError("bad version name")
    report.job["version"] = version  # recorded first, so an interrupted run can be resumed
    _write(report.job)
    out = registry.models_dir() / version
    resume_run = bool(params.get("resume")) and (out / "model.safetensors").exists()
    # Who it is (oversampled: a handful of rows among thousands would be drowned), what it got wrong before,
    # and thousands of tasks whose answers are computed from the corpus — free, truthful, and the part a small
    # model can really learn: doing what the message asked, in the shape it asked for.
    rows = dataset.identity_examples(repeat=int(params.get("identity_repeat", 10)))
    rows += dataset.experience_examples(state.path("experiences.jsonl"))
    synthetic = int(params.get("synthetic", 4000))
    if synthetic > 0:
        rows += dataset.synthetic_examples(store.documents(), limit=synthetic)
    settings = {"out": str(out), "corpus": str(_corpus_dir()), "sft": [str(sft_path)] if sft_path.exists() else [],
                "sft_rows": rows, "minutes": float(params.get("minutes", 30)), "resume": resume_run,
                "preset": params.get("preset", "nano"), "batch": int(params.get("batch", 32))}
    # Knobs the owner (or a longer run) can set: how much of the time is reading, how long the window
    # is, how fast it learns. Left out, the defaults in ``train.run`` apply.
    for knob in ("pretrain_share", "seq_len", "lr", "warmup", "sft_lr_scale", "seed"):
        if params.get(knob) is not None:
            settings[knob] = params[knob]
    metrics = train.run(settings, progress=report, stop=report.stop)
    entry = registry.register(version, out, kind="nano", metrics=metrics)
    if registry.current() is None or state.get_settings().get("auto_promote"):
        registry.promote(version)
        entry["promoted"] = True
    return {"version": version, "metrics": {k: v for k, v in metrics.items() if k != "history"}, "entry": entry}


def run_shard(params: Dict[str, Any], report: Reporter) -> Dict[str, Any]:
    from identity0.model import layered

    _check_params("shard", params)
    return layered.shard(Path(params["dir"]), Path(params.get("out") or Path(params["dir"]) / "layers"),
                         compression=params.get("compression"), progress=lambda m, f: report(m, f))


def run_serve(params: Dict[str, Any], report: Reporter) -> Dict[str, Any]:
    from identity0.model import client

    result = client.ensure_started()
    report("Serving" if result.get("ok") else result.get("error", "Could not start"), 1.0)
    return result


HANDLERS: Dict[str, Callable[[Dict[str, Any], Reporter], Dict[str, Any]]] = {
    "corpus": run_corpus, "distill": run_distill, "train_nano": run_train, "shard": run_shard, "serve": run_serve,
}


def run(job_id: str) -> int:
    job = _read(job_id)
    if job is None:
        return 2
    report = Reporter(job)
    job.update(state="running", pid=os.getpid(), message="Starting…")
    _write(job)
    try:
        result = HANDLERS[job["kind"]](job.get("params") or {}, report)
        job.update(state="cancelled" if report.stop() else "done", progress=1.0, result=result,
                   message="Stopped by the owner" if report.stop() else "Finished")
        code = 0
    except Exception as error:  # noqa: BLE001 - reported in the job file for the UI
        job.update(state="failed", message=f"{type(error).__name__}: {str(error)[:300]}",
                   log=(job.get("log", []) + traceback.format_exc().splitlines()[-6:])[-40:])
        code = 1
    job["finished"] = time.time()
    _write(job)
    (_dir() / f"{job_id}.cancel").unlink(missing_ok=True)
    return code


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "run":
        sys.exit(run(sys.argv[2]))
    print("usage: python -m identity0.jobs run <job id>")
