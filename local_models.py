"""Local models on this PC: what is installed, what is downloaded, and adding either to Nyx (Request R12, M3).

The owner (2026-09-17): "In keys also add a way to add local models so basically it's another part where if I have a
download I click on it and it adds to the overall model", and earlier: "make sure I can add offline models like if I
tell it to download it and use it as a locally model".

Three ways a local model reaches Nyx:

* **Already in Ollama** — every model ``ollama`` serves is listed with its size; "Use" makes it the local model Nyx
  falls back to offline, and it can be picked for any job in Keys & Models.
* **A file you downloaded** — ``scan()`` looks through Downloads, the Desktop, Documents and the usual model folders
  (LM Studio, GPT4All, Jan, the Hugging Face cache) for ``.gguf`` files, says whether each one fits in this machine's
  memory, and ``add_file()`` registers it with Ollama (a Modelfile with ``FROM <path>``). Ollama copies the weights
  into its own store, so the space is needed twice — the UI says so before the click.
* **Pulled by name** — ``pull()`` downloads a model through Ollama with live progress, sized to this PC's VRAM.

A local server that is already running (LM Studio, llama.cpp, Jan, KoboldCpp) is found by ``probe_servers()`` and can
be added as an ordinary OpenAI-compatible provider instead.

Nothing here installs anything by itself: ``install_ollama()`` runs only from the owner's own button, and every route
in ``routes_local_models`` is owner-gated.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

_LOG = logging.getLogger("nyx.local_models")

GGUF_SUFFIXES = (".gguf",)
OTHER_WEIGHTS = (".safetensors", ".bin", ".pt", ".onnx")
MAX_SCAN_FILES = 400
PULL_TIMEOUT = 3 * 3600
#: ollama.exe and winget are console programs: without this each one flashes a window over the owner's work.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

#: Models worth suggesting, smallest first, with the memory each needs. "job" is what it is good at.
SUGGESTED: List[Dict[str, Any]] = [
    {"name": "qwen3:1.7b", "gb": 1.4, "job": "Fast chat, tiny footprint"},
    {"name": "llama3.2:3b", "gb": 2.0, "job": "General chat and summaries"},
    {"name": "gemma3:4b", "gb": 3.3, "job": "General chat, strong for its size"},
    {"name": "qwen2.5-coder:7b", "gb": 4.7, "job": "Code"},
    {"name": "qwen3:8b", "gb": 5.2, "job": "General, thinks step by step"},
    {"name": "llava:7b", "gb": 4.7, "job": "Looks at pictures and screenshots"},
    {"name": "qwen2.5vl:7b", "gb": 6.0, "job": "Reads screens and documents"},
    {"name": "gpt-oss:20b", "gb": 13.0, "job": "Strong general model"},
    {"name": "qwen2.5-coder:14b", "gb": 9.0, "job": "Code, bigger"},
    {"name": "qwen3:32b", "gb": 20.0, "job": "Heavy work, needs a big GPU"},
]

#: Where a downloaded model file usually lands.
def _search_dirs() -> List[Path]:
    home = Path.home()
    candidates = [home / "Downloads", home / "Desktop", home / "Documents", home / ".lmstudio" / "models",
                  home / "AppData" / "Local" / "nomic.ai" / "GPT4All", home / "jan" / "models",
                  home / ".cache" / "lm-studio" / "models", home / ".cache" / "huggingface" / "hub",
                  home / "AppData" / "Roaming" / "koboldcpp", Path("C:/models"), Path("D:/models")]
    return [p for p in candidates if p.exists()]


#: Local servers that speak the OpenAI protocol, and where they usually listen.
LOCAL_SERVERS = [
    {"name": "LM Studio", "port": 1234, "path": "/v1"},
    {"name": "llama.cpp server", "port": 8080, "path": "/v1"},
    {"name": "Jan", "port": 1337, "path": "/v1"},
    {"name": "KoboldCpp", "port": 5001, "path": "/v1"},
    {"name": "Text generation web UI", "port": 5000, "path": "/v1"},
    {"name": "vLLM", "port": 8001, "path": "/v1"},
]


class LocalModelError(RuntimeError):
    """Something the owner asked for cannot be done here; the message says why."""


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------


def host() -> str:
    try:
        from config import SETTINGS

        value = SETTINGS.ollama_host or "http://127.0.0.1:11434"
    except Exception:  # pragma: no cover
        value = "http://127.0.0.1:11434"
    return value.replace("//localhost:", "//127.0.0.1:").rstrip("/")


def ollama_exe() -> str:
    found = shutil.which("ollama")
    if found:
        return found
    for candidate in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
                      Path("C:/Program Files/Ollama/ollama.exe")):
        if candidate.exists():
            return str(candidate)
    return ""


def _get(path: str, timeout: float = 2.0) -> Any:
    response = requests.get(host() + path, timeout=timeout)
    response.raise_for_status()
    return response.json()


def running() -> bool:
    try:
        _get("/api/tags", timeout=1.0)
        return True
    except Exception:  # noqa: BLE001
        return False


def installed_models() -> List[Dict[str, Any]]:
    try:
        models = _get("/api/tags").get("models", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for model in models:
        details = model.get("details") or {}
        out.append({"name": model.get("name", ""), "bytes": int(model.get("size") or 0),
                    "family": details.get("family", ""), "parameters": details.get("parameter_size", ""),
                    "quantization": details.get("quantization_level", ""), "modified": model.get("modified_at", "")})
    return sorted(out, key=lambda m: m["name"])


def memory() -> Dict[str, float]:
    try:
        from device_profile import get_device_profile

        profile = get_device_profile()
        return {"vram_gb": float(getattr(profile, "vram_gb", 0) or 0), "ram_gb": float(getattr(profile, "ram_gb", 0) or 0)}
    except Exception:  # noqa: BLE001
        return {"vram_gb": 0.0, "ram_gb": 0.0}


def fits(gb: float, room: Optional[Dict[str, float]] = None) -> str:
    """"gpu" (comfortably in VRAM), "ram" (runs on the processor, slower) or "no"."""
    room = room or memory()
    vram, ram = room.get("vram_gb", 0.0), room.get("ram_gb", 0.0)
    if vram and gb <= vram * 0.85:
        return "gpu"
    if ram and gb <= ram * 0.7:
        return "ram"
    return "no"


def status() -> Dict[str, Any]:
    exe = ollama_exe()
    live = running()
    room = memory()
    models = installed_models() if live else []
    active = ""
    try:
        from config import SETTINGS

        active = SETTINGS.ollama_model
    except Exception:  # pragma: no cover
        pass
    return {
        "installed": bool(exe), "running": live, "exe": exe, "host": host(), "models": models, "active": active,
        "memory": room, "total_bytes": sum(m["bytes"] for m in models),
        "suggested": [{**item, "fits": fits(item["gb"], room), "installed": any(m["name"].startswith(item["name"]) for m in models)}
                      for item in SUGGESTED],
        "store": str(Path(os.environ.get("OLLAMA_MODELS", "")) if os.environ.get("OLLAMA_MODELS") else Path.home() / ".ollama" / "models"),
    }


# ---------------------------------------------------------------------------
# Files on this PC
# ---------------------------------------------------------------------------


def _describe(path: Path) -> Dict[str, Any]:
    size = path.stat().st_size
    gb = size / (1024 ** 3)
    name = path.stem.lower()
    quant = next((q for q in ("q2_k", "q3_k", "q4_0", "q4_k_m", "q4_k_s", "q5_k_m", "q5_0", "q6_k", "q8_0", "f16", "bf16")
                  if q in name), "")
    return {"path": str(path), "name": path.name, "stem": path.stem, "bytes": size, "gb": round(gb, 2),
            "kind": path.suffix.lower().lstrip("."), "quantization": quant.upper(), "fits": fits(gb),
            "modified": path.stat().st_mtime, "ready": path.suffix.lower() in GGUF_SUFFIXES}


def scan(extra: Optional[List[str]] = None, include_other: bool = False) -> Dict[str, Any]:
    """Model files sitting on this PC, newest first. Only the top levels are walked, so it stays quick."""
    wanted = GGUF_SUFFIXES + (OTHER_WEIGHTS if include_other else ())
    seen: Dict[str, Dict[str, Any]] = {}
    roots = _search_dirs() + [Path(p) for p in (extra or []) if p and Path(p).exists()]
    for root in roots:
        try:
            for depth, pattern in ((1, "*"), (2, "*/*"), (3, "*/*/*")):
                for path in root.glob(pattern):
                    if len(seen) >= MAX_SCAN_FILES:
                        break
                    if path.is_file() and path.suffix.lower() in wanted and path.stat().st_size > 50 * 1024 * 1024:
                        seen[str(path)] = _describe(path)
                del depth
        except (OSError, PermissionError):
            continue
    files = sorted(seen.values(), key=lambda f: -f["modified"])
    return {"files": files, "roots": [str(r) for r in roots], "memory": memory()}


# ---------------------------------------------------------------------------
# Jobs (pull / create / install) — they take minutes, so they run in the background with progress
# ---------------------------------------------------------------------------

JOBS: Dict[str, Dict[str, Any]] = {}
_JOB_LOCK = threading.RLock()


def _job(kind: str, title: str) -> Dict[str, Any]:
    job = {"id": uuid.uuid4().hex[:8], "kind": kind, "title": title, "status": "running", "percent": 0.0,
           "detail": "Starting…", "started_at": time.time(), "ended_at": 0.0, "error": "", "log": []}
    with _JOB_LOCK:
        JOBS[job["id"]] = job
        for old in sorted(JOBS.values(), key=lambda j: j["started_at"])[:-12]:
            JOBS.pop(old["id"], None)
    return job


def _note(job: Dict[str, Any], text: str, percent: Optional[float] = None) -> None:
    job["detail"] = str(text)[:300]
    if percent is not None:
        job["percent"] = round(max(0.0, min(100.0, percent)), 1)
    job["log"].append({"t": time.time(), "text": job["detail"]})
    del job["log"][:-60]
    try:
        from agent_events import publish_ui

        publish_ui("local_models.job", job={k: job[k] for k in ("id", "kind", "title", "status", "percent", "detail")})
    except Exception:  # noqa: BLE001
        pass


def jobs() -> List[Dict[str, Any]]:
    with _JOB_LOCK:
        return sorted(JOBS.values(), key=lambda j: -j["started_at"])


def _finish(job: Dict[str, Any], error: str = "") -> None:
    job["status"] = "error" if error else "done"
    job["error"] = error[:300]
    job["ended_at"] = time.time()
    job["percent"] = job["percent"] if error else 100.0
    _note(job, error or "Done")
    try:
        from agent_events import publish_ui

        publish_ui("keys.changed")
    except Exception:  # noqa: BLE001
        pass


def _stream_ollama(job: Dict[str, Any], path: str, payload: Dict[str, Any], threaded: bool = True) -> None:
    """Run one streaming Ollama job (``/api/pull`` or ``/api/create``) and turn its lines into progress."""

    def work() -> None:
        try:
            with requests.post(host() + path, json=payload, stream=True, timeout=PULL_TIMEOUT) as response:
                if response.status_code != 200:
                    raise LocalModelError(f"Ollama answered {response.status_code}: {response.text[:200]}")
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if event.get("error"):
                        raise LocalModelError(str(event["error"])[:300])
                    total, done = event.get("total") or 0, event.get("completed") or 0
                    percent = (done / total * 100) if total else None
                    status_text = str(event.get("status") or "")
                    if total:
                        status_text += f" — {done / 1e9:.1f} of {total / 1e9:.1f} GB"
                    _note(job, status_text or "Working", percent)
            _finish(job)
        except Exception as error:  # noqa: BLE001 - the job card says what went wrong
            _finish(job, f"{type(error).__name__}: {error}")

    if threaded:
        threading.Thread(target=work, name=f"nyx-local-{job['id']}", daemon=True).start()
    else:
        work()


def pull(name: str, threaded: bool = True) -> Dict[str, Any]:
    """Download a model by name through Ollama (``llama3.2``, ``qwen3:8b``…)."""
    clean = str(name or "").strip()
    if not re.match(r"^[A-Za-z0-9][\w.:/-]{1,80}$", clean):
        raise LocalModelError("That does not look like a model name (try llama3.2 or qwen3:8b).")
    if not running():
        raise LocalModelError("Ollama is not running on this PC yet.")
    job = _job("pull", f"Downloading {clean}")
    # "name" is the older Ollama's key for the same field; sending both works on every version.
    _stream_ollama(job, "/api/pull", {"model": clean, "name": clean, "stream": True}, threaded)
    return job


def add_file(path: str, name: str = "", threaded: bool = True,
             runner: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Register a downloaded .gguf with Ollama so it becomes one of Nyx's models.

    The CLI does this rather than the HTTP API: ``/api/create`` changed shape between Ollama versions (a Modelfile
    string, then blob digests), while ``ollama create -f`` has meant the same thing throughout.
    """
    source = Path(str(path or ""))
    if not source.is_file():
        raise LocalModelError("That file is not on this PC any more.")
    if source.suffix.lower() not in GGUF_SUFFIXES:
        raise LocalModelError("Ollama can take a .gguf file. Other formats need a conversion first — "
                              "or run them in LM Studio and add that as a local server below.")
    # Weights are a download from a stranger like any other: check the header is
    # really GGUF (a renamed pickle would run code) before Ollama copies it in.
    try:
        import file_guard

        verdict = file_guard.check_file(source, source="local model file")
    except Exception:  # noqa: BLE001 - a broken checker must not stop a real model
        verdict = None
    if verdict is not None and verdict.blocked:
        raise LocalModelError(verdict.message)
    clean = re.sub(r"[^a-z0-9._-]+", "-", (name or source.stem).lower()).strip("-")[:40] or "local-model"
    exe = ollama_exe()
    if not exe:
        raise LocalModelError("Ollama is not installed on this PC yet.")
    job = _job("create", f"Adding {source.name} as “{clean}”")
    _note(job, f"Ollama copies the weights into its own store, so {source.stat().st_size / 1e9:.1f} GB more disk is used.", 2)

    def work() -> None:
        recipe = None
        try:
            import tempfile

            recipe = Path(tempfile.gettempdir()) / f"nyx-modelfile-{job['id']}"
            recipe.write_text(f"FROM {source}\n", encoding="utf-8")
            start = runner or subprocess.Popen
            process = start([exe, "create", clean, "-f", str(recipe)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, creationflags=_NO_WINDOW)
            percent = 5.0
            for line in iter(process.stdout.readline, ""):  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                percent = min(95.0, percent + 4)
                _note(job, line[:200], percent)
            code = process.wait(timeout=PULL_TIMEOUT)
            if code != 0:
                raise LocalModelError(f"ollama create ended with code {code} — {job['detail']}")
            _finish(job)
        except Exception as error:  # noqa: BLE001 - the job card says what went wrong
            _finish(job, f"{type(error).__name__}: {error}")
        finally:
            if recipe is not None:
                try:
                    recipe.unlink()
                except OSError:
                    pass

    if threaded:
        threading.Thread(target=work, name=f"nyx-local-{job['id']}", daemon=True).start()
    else:
        work()
    return job


def remove(name: str) -> Dict[str, Any]:
    """Delete a model from Ollama. The owner confirms this in the UI first; it frees the disk space."""
    clean = str(name or "").strip()
    if not clean:
        raise LocalModelError("Name the model to remove.")
    try:
        response = requests.delete(host() + "/api/delete", json={"model": clean}, timeout=60)
    except requests.RequestException as error:
        raise LocalModelError(f"Ollama could not be reached ({type(error).__name__}).") from error
    if response.status_code >= 400:
        raise LocalModelError(f"Ollama answered {response.status_code}: {response.text[:160]}")
    return {"removed": clean}


def use(name: str, role: str = "") -> Dict[str, Any]:
    """Make this the local model Nyx uses offline, and optionally give it one of the jobs in Keys & Models."""
    clean = str(name or "").strip()
    if not clean:
        raise LocalModelError("Name the model to use.")
    from config import SETTINGS

    SETTINGS.ollama_model = clean
    try:
        import model_choice

        model_choice.remember("ollama", clean)
    except Exception:  # noqa: BLE001
        pass
    assigned = ""
    if role:
        from model_roles import MODEL_ROLES

        entry = MODEL_ROLES.assign_role(role, "ollama", model=clean, assigned_by="owner")
        assigned = entry.get("title", role)
    try:
        from agent_events import publish_ui

        publish_ui("keys.changed")
    except Exception:  # noqa: BLE001
        pass
    return {"model": clean, "role": assigned}


def install_ollama(threaded: bool = True, runner: Optional[Callable[..., Any]] = None) -> Dict[str, Any]:
    """Install Ollama with winget — only ever from the owner's own button."""
    if ollama_exe():
        raise LocalModelError("Ollama is already installed on this PC.")
    job = _job("install", "Installing Ollama")

    def work() -> None:
        try:
            _note(job, "Running winget install Ollama.Ollama…", 5)
            run = runner or subprocess.run
            result = run(["winget", "install", "--id", "Ollama.Ollama", "--accept-source-agreements",
                          "--accept-package-agreements", "--silent"], capture_output=True, text=True, timeout=1800,
                         creationflags=_NO_WINDOW)
            output = f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}".strip()
            if getattr(result, "returncode", 1) != 0 and not ollama_exe():
                raise LocalModelError(output[-300:] or "winget could not install it.")
            _note(job, "Installed. Starting the service…", 80)
            exe = ollama_exe()
            if exe and not running():
                subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
                for _ in range(20):
                    if running():
                        break
                    time.sleep(1)
            _finish(job)
        except Exception as error:  # noqa: BLE001
            _finish(job, f"{type(error).__name__}: {error}")

    if threaded:
        threading.Thread(target=work, name="nyx-install-ollama", daemon=True).start()
    else:
        work()
    return job


# ---------------------------------------------------------------------------
# Other local servers
# ---------------------------------------------------------------------------


def probe_servers(get: Optional[Callable[..., Any]] = None) -> List[Dict[str, Any]]:
    """Local OpenAI-compatible servers that are already running, with the models they serve."""
    http = get or requests.get
    found = []
    for server in LOCAL_SERVERS:
        url = f"http://127.0.0.1:{server['port']}{server['path']}"
        try:
            response = http(url + "/models", timeout=0.6)
            if response.status_code != 200:
                continue
            models = [str(m.get("id", "")) for m in (response.json().get("data") or []) if m.get("id")]
        except Exception:  # noqa: BLE001 - nothing listening is the normal case
            continue
        found.append({"name": server["name"], "url": url + "/chat/completions", "port": server["port"], "models": models[:20]})
    return found
