"""The Second Brain's third view ("Core") and running agents in boxes (Request J6–J8).

The owner (2026-09-16): "add usage gauges for each process, all agents, api, and such being used. Show sub
agents and a way to run them from there and a way to … drop into a single project or press a plus to add them."

``GET /api/core/overview`` is one cheap read for every gauge on that screen — the machine, the engine
process, each API provider (calls, failures, latency, known limits, key health), each agent (working copies,
tasks done, model) and the background processes (turns, autopilot, analysis, review jobs, dispatches). The
page polls it every few seconds, so nothing here may block: no model calls, no network.

``/api/dispatch*`` start, watch, extend and stop a set of agent boxes (``agent_dispatch``).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server_auth import RequireChat

router = APIRouter()

_PROCESS_LOCK = threading.Lock()
_PROCESS: Any = None


def _engine_process() -> Dict[str, Any]:
    """This engine's own CPU and memory (psutil's CPU % is the delta since the previous call)."""
    global _PROCESS
    try:
        import psutil

        with _PROCESS_LOCK:
            if _PROCESS is None:
                _PROCESS = psutil.Process(os.getpid())
                _PROCESS.cpu_percent(None)
            proc = _PROCESS
            cores = psutil.cpu_count(logical=True) or 1
            with proc.oneshot():
                return {"pid": proc.pid, "cpu_percent": round(proc.cpu_percent(None) / cores, 1),
                        "memory_mb": round(proc.memory_info().rss / (1024 ** 2)), "threads": proc.num_threads(),
                        "uptime_seconds": round(time.time() - proc.create_time())}
    except Exception:  # noqa: BLE001 - a gauge without data shows a dash
        return {}


def _machine() -> Dict[str, Any]:
    try:
        import psutil

        memory = psutil.virtual_memory()
        out = {"cpu_percent": psutil.cpu_percent(None), "memory_percent": round(memory.percent, 1),
               "memory_used_gb": round(memory.used / (1024 ** 3), 1), "memory_total_gb": round(memory.total / (1024 ** 3), 1)}
    except Exception:  # noqa: BLE001
        out = {}
    try:
        from system_info import _nvidia_live

        gpus = _nvidia_live()
        if gpus:
            first = gpus[0]
            out["gpu_percent"] = first.get("util_percent")
            out["gpu_name"] = first.get("name", "")
    except Exception:  # noqa: BLE001
        pass
    return out


_GPU_CACHE: Dict[str, Any] = {"at": 0.0, "value": {}}


def _machine_cached() -> Dict[str, Any]:
    # nvidia-smi takes ~150 ms; read it at most every 10 s.
    if time.time() - _GPU_CACHE["at"] > 10:
        _GPU_CACHE.update(at=time.time(), value=_machine())
        return _GPU_CACHE["value"]
    fresh = dict(_GPU_CACHE["value"])
    try:
        import psutil

        fresh["cpu_percent"] = psutil.cpu_percent(None)
        fresh["memory_percent"] = round(psutil.virtual_memory().percent, 1)
    except Exception:  # noqa: BLE001
        pass
    return fresh


def _providers() -> List[Dict[str, Any]]:
    """Every API Nyx talks to: calls since start (chat + model jobs), failures, latency, limits, keys."""
    rows: Dict[str, Dict[str, Any]] = {}
    now = time.time()
    try:
        from metrics import GLOBAL_METRICS

        with GLOBAL_METRICS._lock:
            metrics = list(GLOBAL_METRICS._metrics)
        from datetime import datetime

        for metric in metrics:
            row = rows.setdefault(metric.provider, {"name": metric.provider, "calls": 0, "failures": 0, "latency_total": 0.0,
                                                   "tokens": 0, "last_hour": 0, "models": {}, "last_error": "", "last_at": 0.0})
            try:
                at = datetime.fromisoformat(metric.timestamp).timestamp()
            except ValueError:
                at = now
            row["calls"] += 1
            row["failures"] += 0 if metric.success else 1
            row["latency_total"] += metric.latency_seconds
            row["tokens"] += int(metric.tokens_total or 0)
            row["last_hour"] += 1 if now - at < 3600 else 0
            row["last_at"] = max(row["last_at"], at)
            model = str((metric.metadata or {}).get("model") or "")
            if model:
                row["models"][model] = row["models"].get(model, 0) + 1
            if not metric.success and metric.error_message:
                row["last_error"] = str(metric.error_message)[:160]
    except Exception:  # noqa: BLE001
        pass
    try:
        from model_hub import is_configured, known_providers

        configured = [p for p in known_providers() if p not in ("ollama",) and _safe_bool(is_configured, p)]
    except Exception:  # noqa: BLE001
        configured = []
    for name in configured:
        rows.setdefault(name, {"name": name, "calls": 0, "failures": 0, "latency_total": 0.0, "tokens": 0, "last_hour": 0,
                               "models": {}, "last_error": "", "last_at": 0.0})
    out = []
    for name, row in rows.items():
        calls = row.pop("calls")
        latency_total = row.pop("latency_total")
        row.update(calls=calls, avg_latency=round(latency_total / calls, 2) if calls else None,
                   success_rate=round((calls - row["failures"]) / calls, 3) if calls else None,
                   configured=name in configured, models=dict(sorted(row["models"].items(), key=lambda kv: -kv[1])[:4]))
        try:
            import usage_limits

            limits = usage_limits.snapshot(name)["limits"]
            best = next((l for l in limits if l.get("limit")), None)
            if best:
                row["limit"] = {"window": best.get("window", ""), "kind": best.get("kind", ""), "limit": best.get("limit"),
                                "remaining": best.get("remaining"), "reset_at": best.get("reset_at")}
        except Exception:  # noqa: BLE001
            pass
        try:
            import key_pool

            summary = key_pool.summary(name)
            if summary.get("key_name"):
                keys = summary.get("keys", [])
                row["keys"] = {"total": len(keys), "working": sum(1 for k in keys if k.get("state") == "working"),
                               "failed": sum(1 for k in keys if k.get("state") == "failed")}
        except Exception:  # noqa: BLE001
            pass
        out.append(row)
    out.sort(key=lambda r: (-r["calls"], r["name"]))
    return out


def _safe_bool(fn: Any, *args: Any) -> bool:
    try:
        return bool(fn(*args))
    except Exception:  # noqa: BLE001
        return False


def _agents() -> List[Dict[str, Any]]:
    try:
        from agent_dispatch import DISPATCHES
        from agent_runtime import load_roster, sync_team
        from agent_team import AGENT_TEAM

        sync_team(AGENT_TEAM)
        copies = DISPATCHES.working_counts()
        rows = []
        for entry in load_roster():
            member = AGENT_TEAM.find(entry["name"])
            live = member.snapshot() if member else {}
            working = copies.get(entry["name"], 0) or (1 if live.get("status") == "working" else 0)
            rows.append({
                "name": entry["name"], "emoji": entry.get("emoji", ""), "color": entry.get("color", ""),
                "role": entry.get("role", "worker"), "goal": entry.get("goal", ""),
                "made_by": entry.get("made_by") or ("nyx" if entry.get("created_in_chat") else
                                                    "builtin" if entry.get("origin", "roster") == "roster" else "owner"),
                "builtin": entry.get("origin", "roster") == "roster",
                "provider": entry.get("provider", ""), "model": entry.get("model", ""),
                "status": "working" if working else live.get("status", "idle"), "copies_working": working,
                "step": live.get("current_step", ""), "tasks_done": live.get("tasks_completed", 0),
                "seconds": live.get("elapsed_seconds", 0), "last_error": live.get("last_error", ""),
                "command": "/" + __import__("agent_dispatch").agent_slug(entry["name"]),
            })
        return rows
    except Exception:  # noqa: BLE001
        return []


def _processes() -> List[Dict[str, Any]]:
    """Background work the owner may want to see or stop."""
    rows: List[Dict[str, Any]] = []
    try:
        from turn_registry import TURNS

        for turn in TURNS.active(include_recent=False):
            rows.append({"kind": "turn", "id": turn["turn_id"], "label": "Answering", "detail": turn["message"][:90],
                         "status": turn["status"], "seconds": turn["elapsed_seconds"], "chat_id": turn["chat_id"]})
    except Exception:  # noqa: BLE001
        pass
    try:
        from improve_autopilot import AUTOPILOT

        run = AUTOPILOT.active()
        if run:
            rows.append({"kind": "autopilot", "id": run["run_id"], "label": f"Improve autopilot · {run['phase']['kind']}",
                         "detail": run["work"][:90], "status": run["status"],
                         "seconds": round(time.time() - run["created_at"]), "progress": _run_progress(run)})
    except Exception:  # noqa: BLE001
        pass
    try:
        from improvement_engine import ENGINE

        for session in ENGINE.list_sessions()[:3]:
            if session["status"] in ("running", "stopping"):
                rows.append({"kind": "analysis", "id": session["session_id"], "label": "Code analysis",
                             "detail": session["progress"][:90], "status": session["status"],
                             "seconds": session["elapsed_seconds"]})
    except Exception:  # noqa: BLE001
        pass
    try:
        from improve_review import REVIEW_QUEUE

        job = REVIEW_QUEUE.job()
        if job and job["status"] == "running":
            rows.append({"kind": "review", "id": job["id"], "label": "Reviewing changes", "detail": job["now"][:90],
                         "status": "running", "seconds": round(time.time() - job["started_at"]),
                         "progress": round(job["done"] / job["total"], 3) if job.get("total") else None})
    except Exception:  # noqa: BLE001
        pass
    try:
        from agent_dispatch import DISPATCHES

        for dispatch in DISPATCHES.list(active_only=True):
            counts = dispatch["counts"]
            total = len(dispatch["instances"]) or 1
            names = " + ".join(f"{n}× {a}" if n > 1 else a for a, n in dispatch["agents"].items())
            rows.append({"kind": "dispatch", "id": dispatch["dispatch_id"], "label": f"Agents: {names}"[:60],
                         "detail": f"{counts['working']} working · {counts['done']} done · {counts['queued']} waiting",
                         "status": "running", "seconds": round(time.time() - dispatch["created_at"]),
                         "progress": round((counts["done"] + counts["error"] + counts["stopped"]) / total, 3)})
    except Exception:  # noqa: BLE001
        pass
    # Everything else that is running, found rather than listed, so a feature
    # built after this file still shows up here (Project Null N100).
    try:
        import feature_catalog

        known = {(row.get("kind"), str(row.get("id"))) for row in rows}
        for found in feature_catalog.live_processes():
            if found["source"] == "thread" or (found["kind"], found["id"]) in known:
                continue
            rows.append({"kind": found["kind"], "id": found["id"], "label": found["label"],
                         "detail": found["detail"], "status": found["status"], "seconds": 0})
    except Exception:  # noqa: BLE001
        pass
    return rows


def _run_progress(run: Dict[str, Any]) -> Optional[float]:
    if run.get("remaining_seconds") is None or not run.get("ends_at"):
        return None
    total = max(1.0, float(run["ends_at"]) - float(run["created_at"]))
    return round(1 - float(run["remaining_seconds"]) / total, 3)


def _today() -> Dict[str, Any]:
    """Turns answered today and how long they took (from the learning log's tail)."""
    try:
        import json

        from paths import data_path

        path = data_path("learning/turns.jsonl")
        size = path.stat().st_size
        with open(path, "rb") as handle:
            handle.seek(max(0, size - 400_000))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()[1:]
        midnight = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        turns = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if float(row.get("ts") or 0) >= midnight:
                turns.append(row)
        latencies = sorted(float(t.get("latency_ms") or 0) for t in turns if t.get("latency_ms"))
        return {"turns": len(turns), "ok": sum(1 for t in turns if t.get("ok")),
                "median_latency_s": round(latencies[len(latencies) // 2] / 1000, 1) if latencies else None,
                "agents_used": sum(len(t.get("agents") or []) for t in turns),
                "tools_used": sum(len(t.get("tools") or []) for t in turns)}
    except Exception:  # noqa: BLE001
        return {"turns": 0}


@router.get("/api/core/overview")
def core_overview(_user=RequireChat) -> Dict[str, Any]:
    return {"at": time.time(), "machine": _machine_cached(), "engine": _engine_process(), "providers": _providers(),
            "agents": _agents(), "processes": _processes(), "today": _today()}


# --- dispatches ---------------------------------------------------------------------------------


class DispatchItem(BaseModel):
    agent: str
    task: str = ""


class DispatchRequest(BaseModel):
    items: List[DispatchItem] = Field(default_factory=list)
    chat_id: str = ""
    context: str = ""
    project: Dict[str, Any] = Field(default_factory=dict)


class ParseRequest(BaseModel):
    text: str


def _dispatch_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    from agent_dispatch import DispatchError

    try:
        return fn(*args, **kwargs)
    except DispatchError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/dispatch")
def dispatch_start(body: DispatchRequest, _user=RequireChat) -> Dict[str, Any]:
    from agent_dispatch import DISPATCHES

    project = {k: str(v)[:300] for k, v in (body.project or {}).items() if k in ("name", "path", "kind", "id")}
    return {"dispatch": _dispatch_call(DISPATCHES.start, [i.model_dump() for i in body.items], chat_id=body.chat_id,
                                       origin="owner", context=body.context, project=project)}


@router.get("/api/dispatch")
def dispatch_list(active: bool = False, chat_id: str = "", _user=RequireChat) -> Dict[str, Any]:
    from agent_dispatch import DISPATCHES

    return {"dispatches": DISPATCHES.list(active_only=active, chat_id=chat_id)[:20]}


@router.post("/api/dispatch/parse")
def dispatch_parse(body: ParseRequest, _user=RequireChat) -> Dict[str, Any]:
    """``/coder [3] build X`` → the boxes to show before anything runs."""
    import agent_dispatch
    from agent_runtime import load_roster

    names = {agent_dispatch.agent_slug(a["name"]): a["name"] for a in load_roster() if a.get("role") != "master"}
    parsed = agent_dispatch.parse_invocations(body.text, names)
    return {**parsed, "items": agent_dispatch.expand(parsed["invocations"])}


@router.get("/api/dispatch/{dispatch_id}")
def dispatch_get(dispatch_id: str, _user=RequireChat) -> Dict[str, Any]:
    from agent_dispatch import DISPATCHES

    found = DISPATCHES.get(dispatch_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such dispatch.")
    return {"dispatch": found}


@router.post("/api/dispatch/{dispatch_id}/add")
def dispatch_add(dispatch_id: str, body: DispatchItem, _user=RequireChat) -> Dict[str, Any]:
    from agent_dispatch import DISPATCHES

    return {"dispatch": _dispatch_call(DISPATCHES.add, dispatch_id, body.agent, body.task)}


@router.post("/api/dispatch/{dispatch_id}/stop")
def dispatch_stop(dispatch_id: str, _user=RequireChat) -> Dict[str, Any]:
    from agent_dispatch import DISPATCHES

    return {"dispatch": _dispatch_call(DISPATCHES.stop, dispatch_id)}
