"""Predict — a swarm of agents rehearses the future (owner, 2026-10-10: "Use this and make a tab out of it
https://github.com/666ghj/MiroFish. Basically it can take in anything and use a mass amount of bots to predict. I can
give a file, a simple request, a video, anything and it can take hours to predict").

MiroFish is AGPL-3.0, so nothing is copied — this is Ichos's own engine on the same idea:

    seeds (text, files, links, a video's details) → a graph of who and what matters → outcomes to predict →
    a population of personas tied to that graph → rounds of a public "town square" where a sample of agents posts,
    reacts and shifts their lean → a running probability for each outcome → a report → chat with any agent.

Scales trade time for depth (calls are model calls; a local model makes the big ones free but slow):

    quick     12 agents ·  6 rounds · 12 act per round  ≈  25 calls · minutes
    standard  40 agents · 12 rounds · 20 act per round  ≈  45 calls
    large    120 agents · 24 rounds · 40 act per round  ≈ 140 calls
    swarm    400 agents · 40 rounds · 80 act per round  ≈ 400 calls · hours

The owner can pause, resume, stop, and inject an event from a god's-eye view between rounds. Every job is a JSON file
under the data folder, saved after each round, so a long run survives the page closing; a restart marks it paused.
"""

from __future__ import annotations

import json
import math
import random
import zlib
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import atomic_replace, data_path

SCALES: Dict[str, Dict[str, int]] = {
    "quick": {"agents": 12, "rounds": 6, "active": 12},
    "standard": {"agents": 40, "rounds": 12, "active": 20},
    "large": {"agents": 120, "rounds": 24, "active": 40},
    "swarm": {"agents": 400, "rounds": 40, "active": 80},
}
BATCH = 10
PERSONA_BATCH = 20
SEED_LIMIT = 24_000

Ask = Callable[[str, int], str]
_lock = threading.Lock()
_controls: Dict[str, Dict[str, Any]] = {}


def estimate_calls(scale: str) -> int:
    s = SCALES[scale]
    personas = -(-s["agents"] // PERSONA_BATCH)
    per_round = -(-s["active"] // BATCH) + 1
    return 2 + personas + s["rounds"] * per_round + 1


def _dir() -> Path:
    folder = data_path("predict_jobs")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _file(job_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{10}", job_id or ""):
        raise KeyError(job_id)
    return _dir() / f"{job_id}.json"


def _save(job: Dict[str, Any]) -> None:
    job["updated"] = time.time()
    path = _file(job["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    atomic_replace(tmp, path)


def load(job_id: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_file(job_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None


def summary(job: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the page draws, without the full persona list and feed (those are fetched on demand)."""
    keep = {k: job.get(k) for k in ("id", "question", "scale", "status", "round", "rounds", "outcomes", "graph",
                                    "probabilities", "events", "report", "created", "updated", "note", "seed_names",
                                    "calls", "estimate")}
    keep["agents"] = [{k: a.get(k) for k in ("id", "name", "role", "lean", "confidence", "x", "y")} for a in job.get("agents", [])]
    keep["feed"] = job.get("feed", [])[-40:]
    return keep


def list_jobs() -> List[Dict[str, Any]]:
    out = []
    for path in sorted(_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:40]:
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"id": job["id"], "question": job["question"], "status": job["status"], "scale": job["scale"],
                    "round": job.get("round", 0), "rounds": job.get("rounds", 0), "created": job.get("created", 0)})
    return out


def _publish(job: Dict[str, Any]) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("predict.update", job=summary(job))
    except Exception:  # noqa: BLE001
        pass


def _default_ask(prompt: str, max_tokens: int) -> str:
    from agent_runtime import _router

    reply, _provider = _router().chat([{"role": "user", "content": prompt}])
    return str(reply or "").strip()


def _json(text: str, fallback: Any) -> Any:
    for pattern in (r"\[.*\]", r"\{.*\}"):
        match = re.search(pattern, text or "", re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except ValueError:
                continue
    return fallback


# --- seeds ---------------------------------------------------------------------------------------------------


def read_seed(kind: str, value: str) -> Dict[str, str]:
    """One piece of seed material as text: pasted text, an uploaded file, a file path, a link, or a video."""
    value = (value or "").strip()
    if kind == "text":
        return {"name": "Your text", "text": value[:SEED_LIMIT]}
    if kind == "link":
        try:
            from web_access import fetch

            return {"name": value[:80], "text": str(fetch(value))[:SEED_LIMIT]}
        except Exception as error:  # noqa: BLE001
            return {"name": value[:80], "text": f"(Could not read the link: {error})"}
    path: Optional[Path] = None
    if kind == "upload":
        import uploads

        record = uploads.get_upload(value)
        path = Path(record["path"]) if record else None
    elif kind == "path":
        path = Path(value).expanduser()
    if path is None or not path.is_file():
        return {"name": value[:80], "text": "(File not found.)"}
    suffix = path.suffix.lower()
    if suffix in (".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"):
        size_mb = path.stat().st_size / 1_000_000
        return {"name": path.name, "text": (f"(A video, {size_mb:.1f} MB, named '{path.name}'. Ichos cannot transcribe "
                                             "video yet, so only its name and size are known — add a description.)")}
    try:
        import uploads

        text = uploads.extract_document_text(path.read_bytes(), path.name)
    except Exception:  # noqa: BLE001
        text = path.read_text(encoding="utf-8", errors="replace")
    return {"name": path.name, "text": str(text)[:SEED_LIMIT]}


# --- the run -------------------------------------------------------------------------------------------------


def _distribution(job: Dict[str, Any]) -> Dict[str, float]:
    weights = {o["id"]: 0.0 for o in job["outcomes"]}
    for agent in job["agents"]:
        if agent.get("lean") in weights:
            weights[agent["lean"]] += 0.2 + float(agent.get("confidence", 0.5)) * float(agent.get("influence", 1.0))
    total = sum(weights.values()) or 1.0
    return {k: round(v / total, 4) for k, v in weights.items()}


def _place(agents: List[Dict[str, Any]], outcomes: List[Dict[str, Any]]) -> None:
    """Where each dot sits in the swarm view: pulled toward its outcome's corner, more strongly when sure."""
    count = max(1, len(outcomes))
    for agent in agents:
        index = next((i for i, o in enumerate(outcomes) if o["id"] == agent.get("lean")), 0)
        angle = 2 * math.pi * index / count
        pull = 0.15 + 0.3 * float(agent.get("confidence", 0.5))
        jitter = (zlib.crc32(agent["id"].encode()) % 1000) / 1000
        agent["x"] = round(0.5 + math.cos(angle) * pull + (jitter - 0.5) * 0.18, 4)
        agent["y"] = round(0.5 + math.sin(angle) * pull + ((zlib.crc32(agent["id"][::-1].encode() + b"y") % 1000) / 1000 - 0.5) * 0.18, 4)


def _control(job_id: str) -> Dict[str, Any]:
    with _lock:
        return _controls.setdefault(job_id, {"pause": threading.Event(), "stop": threading.Event()})


def _run(job_id: str, ask: Ask) -> None:
    job = load(job_id)
    if job is None:
        return
    ctl = _control(job_id)
    calls = job.get("calls", 0)

    def call(prompt: str, tokens: int) -> str:
        nonlocal calls
        calls += 1
        job["calls"] = calls
        return ask(prompt, tokens)

    try:
        seeds = "\n\n".join(f"## {s['name']}\n{s['text']}" for s in job["seeds"])[:SEED_LIMIT]
        if not job.get("outcomes"):
            job["status"] = "building"
            _save(job)
            _publish(job)
            framed = _json(call(
                f"You prepare a forecasting simulation. Question: {job['question']}\n\nSeed material:\n{seeds or '(none)'}\n\n"
                "Reply with JSON only: {\"outcomes\": [{\"id\": \"o1\", \"label\": \"<short outcome>\"}, … 2 to 4 mutually "
                "exclusive outcomes], \"entities\": [{\"id\": \"e1\", \"name\": \"…\", \"kind\": \"person|group|org|place|"
                "idea\"}, … up to 24], \"relations\": [{\"from\": \"e1\", \"to\": \"e2\", \"label\": \"…\"}, … up to 40]}", 900), {})
            outcomes = [o for o in (framed.get("outcomes") or []) if isinstance(o, dict) and o.get("label")][:4]
            if len(outcomes) < 2:
                outcomes = [{"id": "o1", "label": "Yes"}, {"id": "o2", "label": "No"}]
            for i, o in enumerate(outcomes):
                o["id"] = f"o{i + 1}"
                o["label"] = str(o["label"])[:80]
            job["outcomes"] = outcomes
            job["graph"] = {"entities": (framed.get("entities") or [])[:24], "relations": (framed.get("relations") or [])[:40]}
            _save(job)
            _publish(job)
        if not job.get("agents"):
            labels = "; ".join(f"{o['id']} = {o['label']}" for o in job["outcomes"])
            entities = ", ".join(str(e.get("name", "")) for e in job["graph"].get("entities", []))[:1200]
            agents: List[Dict[str, Any]] = []
            while len(agents) < job["agents_target"]:
                if ctl["stop"].is_set():
                    break
                n = min(PERSONA_BATCH, job["agents_target"] - len(agents))
                made = _json(call(
                    f"Create {n} diverse, realistic people who would have a view on: {job['question']}\nKey entities: "
                    f"{entities or '(none)'}\nOutcomes: {labels}\nReply with a JSON array only, each item: {{\"name\": "
                    "\"…\", \"role\": \"<who they are, 6 words>\", \"traits\": \"<how they think, 8 words>\", \"lean\": "
                    "\"<outcome id>\", \"confidence\": 0.0-1.0, \"influence\": 0.5-2.0}", 1800), [])
                for item in made if isinstance(made, list) else []:
                    if not isinstance(item, dict) or len(agents) >= job["agents_target"]:
                        continue
                    agents.append({"id": f"a{len(agents) + 1}", "name": str(item.get("name", f"Agent {len(agents) + 1}"))[:40],
                                   "role": str(item.get("role", ""))[:80], "traits": str(item.get("traits", ""))[:100],
                                   "lean": item.get("lean") if item.get("lean") in {o["id"] for o in job["outcomes"]} else random.choice(job["outcomes"])["id"],
                                   "confidence": max(0.0, min(1.0, float(item.get("confidence", 0.5) or 0.5))),
                                   "influence": max(0.5, min(2.0, float(item.get("influence", 1.0) or 1.0))), "posts": []})
                if not made:
                    break
            job["agents"] = agents or [{"id": f"a{i + 1}", "name": f"Agent {i + 1}", "role": "member of the public",
                                        "traits": "", "lean": job["outcomes"][i % len(job["outcomes"])]["id"],
                                        "confidence": 0.5, "influence": 1.0, "posts": []} for i in range(job["agents_target"])]
            _place(job["agents"], job["outcomes"])
            job["probabilities"] = [{"round": 0, **_distribution(job)}]
            _save(job)
            _publish(job)

        job["status"] = "running"
        _save(job)
        labels = "; ".join(f"{o['id']} = {o['label']}" for o in job["outcomes"])
        while job["round"] < job["rounds"]:
            if ctl["stop"].is_set():
                job["status"] = "stopped"
                break
            while ctl["pause"].is_set() and not ctl["stop"].is_set():
                if job["status"] != "paused":
                    job["status"] = "paused"
                    _save(job)
                    _publish(job)
                time.sleep(0.5)
            if ctl["stop"].is_set():
                job["status"] = "stopped"
                break
            job["status"] = "running"
            number = job["round"] + 1
            news = [e for e in job.get("events", []) if e.get("round") == number]
            news_text = "".join(f"\nNEW EVENT this round: {e['text']}" for e in news)
            active = random.sample(job["agents"], min(job["active"], len(job["agents"])))
            posts: List[Dict[str, Any]] = []
            for start in range(0, len(active), BATCH):
                group = active[start:start + BATCH]
                people = "\n".join(f"- {a['id']}: {a['name']}, {a['role']}; {a['traits']}; leans {a['lean']} "
                                   f"({a['confidence']:.2f})" for a in group)
                acted = _json(call(
                    f"Simulate round {number} of {job['rounds']} of a public discussion forecasting: {job['question']}\n"
                    f"Outcomes: {labels}\nWhat has happened so far: {job.get('world', '(the discussion is starting)')}"
                    f"{news_text}\n\nThese people act now:\n{people}\n\nReply with a JSON array only, one item each: "
                    "{\"id\": \"<their id>\", \"post\": \"<what they say, max 35 words, in character>\", \"lean\": "
                    "\"<outcome id after this round>\", \"confidence\": 0.0-1.0}. People can change their mind when "
                    "persuaded; most do not.", 1600), [])
                by_id = {a["id"]: a for a in group}
                for item in acted if isinstance(acted, list) else []:
                    agent = by_id.get(str(item.get("id", ""))) if isinstance(item, dict) else None
                    if agent is None:
                        continue
                    if item.get("lean") in {o["id"] for o in job["outcomes"]}:
                        agent["lean"] = item["lean"]
                    try:
                        agent["confidence"] = max(0.0, min(1.0, float(item.get("confidence", agent["confidence"]))))
                    except (TypeError, ValueError):
                        pass
                    post = str(item.get("post", "")).strip()[:300]
                    if post:
                        agent["posts"] = (agent.get("posts", []) + [{"round": number, "text": post}])[-8:]
                        posts.append({"round": number, "agent": agent["id"], "name": agent["name"], "lean": agent["lean"], "text": post})
            job["feed"] = (job.get("feed", []) + posts)[-400:]
            world = call(
                f"Summarise in under 120 words where the discussion about '{job['question']}' stands after round "
                f"{number}: the main arguments, who is moving, and momentum.{news_text}\nPrevious summary: "
                f"{job.get('world', '(none)')}\nThis round:\n" + "\n".join(f"{p['name']}: {p['text']}" for p in posts[:40]), 300)
            job["world"] = world[:1200]
            _place(job["agents"], job["outcomes"])
            job["round"] = number
            job["probabilities"].append({"round": number, **_distribution(job)})
            _save(job)
            _publish(job)
        if job["status"] != "stopped":
            final = job["probabilities"][-1]
            table = ", ".join(f"{o['label']}: {final.get(o['id'], 0) * 100:.0f}%" for o in job["outcomes"])
            report = call(
                f"You are the report analyst of a {len(job['agents'])}-agent simulation forecasting: {job['question']}\n"
                f"Final weighted lean of the population: {table}\nHow it moved: "
                + " → ".join(", ".join(f"{k}:{v:.2f}" for k, v in p.items() if k != "round") for p in job["probabilities"][::max(1, len(job["probabilities"]) // 6)])
                + f"\nWhere it ended: {job.get('world', '')}\nInjected events: "
                + ("; ".join(e["text"] for e in job.get("events", [])) or "none")
                + "\n\nWrite the prediction report in Markdown: ## Prediction (one sentence with a probability), ## Why "
                "(3–5 drivers), ## Scenarios (what would change the outcome), ## Confidence (and the limits of a simulated "
                "population — it is a rehearsal, not data). Under 400 words.", 1400)
            job["report"] = report[:6000]
            job["status"] = "done"
    except Exception as error:  # noqa: BLE001 - a failed call pauses the run with a reason; resume continues it
        job["status"] = "failed"
        job["note"] = f"{type(error).__name__}: {error}"[:300]
    finally:
        _save(job)
        _publish(job)
        with _lock:
            _controls.pop(job_id, None)


def start(question: str, seeds: List[Dict[str, str]], scale: str = "quick", *, ask: Optional[Ask] = None,
          background: bool = True) -> Dict[str, Any]:
    question = (question or "").strip()
    if not question:
        raise ValueError("Say what the swarm should predict.")
    if scale not in SCALES:
        raise ValueError(f"Scale must be one of {', '.join(SCALES)}.")
    s = SCALES[scale]
    read = [read_seed(str(x.get("kind", "text")), str(x.get("value", ""))) for x in (seeds or [])[:12] if x.get("value")]
    job = {"id": uuid.uuid4().hex[:10], "question": question[:600], "scale": scale, "status": "queued", "round": 0,
           "rounds": s["rounds"], "agents_target": s["agents"], "active": s["active"], "seeds": read,
           "seed_names": [r["name"] for r in read], "outcomes": [], "graph": {}, "agents": [], "feed": [],
           "probabilities": [], "events": [], "report": "", "world": "", "created": time.time(), "note": "",
           "calls": 0, "estimate": estimate_calls(scale)}
    _save(job)
    return resume(job["id"], ask=ask, background=background)


def resume(job_id: str, *, ask: Optional[Ask] = None, background: bool = True) -> Dict[str, Any]:
    job = load(job_id)
    if job is None:
        raise KeyError(job_id)
    ctl = _control(job_id)
    ctl["pause"].clear()
    if ctl.get("thread") and ctl["thread"].is_alive():
        return summary(job)
    runner = ask or _default_ask
    if background:
        thread = threading.Thread(target=_run, args=(job_id, runner), name=f"predict-{job_id}", daemon=True)
        ctl["thread"] = thread
        thread.start()
    else:
        _run(job_id, runner)
    return summary(load(job_id) or job)


def pause(job_id: str) -> bool:
    _control(job_id)["pause"].set()
    return True


def stop(job_id: str) -> bool:
    ctl = _control(job_id)
    ctl["stop"].set()
    ctl["pause"].clear()
    job = load(job_id)
    if job and job["status"] in ("paused", "queued", "failed"):
        job["status"] = "stopped"
        _save(job)
        _publish(job)
    return True


def inject(job_id: str, text: str) -> Dict[str, Any]:
    """A god's-eye event: it reaches every agent at the start of the next round."""
    job = load(job_id)
    if job is None:
        raise KeyError(job_id)
    text = (text or "").strip()[:400]
    if not text:
        raise ValueError("Describe what happens.")
    job.setdefault("events", []).append({"round": job["round"] + 1, "text": text, "at": time.time()})
    _save(job)
    _publish(job)
    return summary(job)


def chat(job_id: str, who: str, question: str, *, ask: Optional[Ask] = None) -> str:
    """Ask any agent in the swarm — or the report analyst ('report') — about their view."""
    job = load(job_id)
    if job is None:
        raise KeyError(job_id)
    runner = ask or _default_ask
    if who == "report":
        prompt = (f"You are the analyst who wrote this forecast report for '{job['question']}':\n{job.get('report', '')}\n"
                  f"Discussion summary: {job.get('world', '')}\nAnswer the owner's question briefly and honestly about "
                  f"uncertainty: {question}")
    else:
        agent = next((a for a in job.get("agents", []) if a["id"] == who), None)
        if agent is None:
            raise KeyError(who)
        lean = next((o["label"] for o in job["outcomes"] if o["id"] == agent["lean"]), agent["lean"])
        said = " / ".join(p["text"] for p in agent.get("posts", []))
        prompt = (f"You are {agent['name']}, {agent['role']} ({agent['traits']}), in a simulated discussion about "
                  f"'{job['question']}'. You currently lean '{lean}' with confidence {agent['confidence']:.2f}. You said: "
                  f"{said or '(nothing yet)'}. Stay in character and answer in under 80 words: {question}")
    return runner(prompt, 400)


def recover() -> None:
    """After a restart, a run that was mid-flight is marked paused, ready to resume."""
    for path in _dir().glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if job.get("status") in ("running", "building", "queued"):
            job["status"] = "paused"
            job["note"] = "Paused when the engine restarted — press Resume."
            _save(job)


def tool_predict(question: str, scale: str = "quick", text: str = "") -> str:
    try:
        job = start(question, [{"kind": "text", "value": text}] if text.strip() else [], scale)
    except ValueError as error:
        return f"Error: {error}"
    try:
        from agent_events import publish_ui

        publish_ui("ui.open_tab", tab_id="predict")
    except Exception:  # noqa: BLE001
        pass
    return (f"Started a {scale} prediction ({SCALES[scale]['agents']} agents, {SCALES[scale]['rounds']} rounds, about "
            f"{estimate_calls(scale)} model calls) — the Predict tab shows the swarm live and the report when it ends.")


def register_predict_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="predict",
        description="Run a swarm prediction: many simulated people with their own personas discuss a question over "
                    "rounds, and the shift in their views becomes a forecast with a report (the Predict tab). Use when "
                    "the owner asks to predict, forecast or simulate how something will go. Scales: quick (minutes), "
                    "standard, large, swarm (hours).",
        parameters=[ToolParam("question", "string", "What to predict"),
                    ToolParam("scale", "string", "quick, standard, large or swarm", required=False,
                              enum_values=list(SCALES)),
                    ToolParam("text", "string", "Seed material to ground the simulation (optional)", required=False)],
        handler=tool_predict, category="general", label="Starting a prediction",
    )
