"""Try what Nyx built — a site, a web game, an office's output — three ways (UPDATE_IDEAS U11/U12/U19).

The owner: *"If i want to try the site or the game i want to open it either on a download where I can actually do
things without posting or on a website page or on the AI environment itself."*

* **On a web page** — ``start`` serves the folder on this PC (127.0.0.1 only) and keeps it running until stopped,
  unlike ``machine_tools.run_command``, which ends a command at its timeout. A folder with a ``dev`` (or ``start``)
  script in package.json and its packages installed runs that instead, and the address it prints is used.
* **Inside Nyx** — the same address, shown in a frame in the Code tab.
* **As a download** — ``zip_folder`` packs the folder (without node_modules, .git or caches) so it can be run or
  shared by hand. Nothing is published anywhere by this module: posting stays the owner's click (invariant 4).

Only folders the owner opened in the Code tab, or an office's own work folders, can be served.
"""

from __future__ import annotations

import functools
import http.server
import json
import os
import re
import socket
import subprocess
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import data_path

SKIP = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".next", ".cache", ".parcel-cache"}
ZIP_LIMIT = 200 * 1024 * 1024
DEV_WAIT_SECONDS = 90
MAX_RUNNING = 6
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class PreviewError(RuntimeError):
    """Something the owner can act on."""


# ---------------------------------------------------------------------------
# Which folders may be served
# ---------------------------------------------------------------------------


def allowed_folder(path: str) -> Path:
    """A folder the owner opened in the Code tab, or one of the offices' work folders. Anything else is refused."""
    target = Path(os.path.expandvars((path or "").strip().strip('"'))).resolve()
    if target.is_file():
        target = target.parent
    if not target.is_dir():
        raise PreviewError(f"There is no folder at {target}.")
    try:
        import code_workspace

        code_workspace.resolve(str(target))
        return target
    except Exception:  # noqa: BLE001 - not a Code tab folder; an office's work folder is the other way in
        pass
    try:
        from office import library

        root = Path(library.root()).resolve()
        if target == root or root in target.parents:
            return target
    except Exception:  # noqa: BLE001
        pass
    raise PreviewError("Open that folder in the Code tab first — Nyx only serves folders you opened.")


def site_root(folder: Path) -> Path:
    """Where the page actually is: the folder, or its built output when only that has an index.html."""
    if (folder / "index.html").exists():
        return folder
    for sub in ("dist", "build", "public", "out", "site", "www"):
        if (folder / sub / "index.html").exists():
            return folder / sub
    return folder


def dev_script(folder: Path) -> str:
    """"dev" or "start" when package.json has one and its packages are installed, else ""."""
    try:
        scripts = json.loads((folder / "package.json").read_text(encoding="utf-8")).get("scripts") or {}
    except (OSError, ValueError):
        return ""
    if not (folder / "node_modules").is_dir():
        return ""
    return next((name for name in ("dev", "start") if name in scripts), "")


# ---------------------------------------------------------------------------
# Running previews
# ---------------------------------------------------------------------------


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: Any) -> None:  # the engine log is not the place for every file request
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")   # a rebuilt file shows on the next reload
        super().end_headers()


class Preview:
    def __init__(self, folder: Path, mode: str) -> None:
        self.id = "pv-" + uuid.uuid4().hex[:8]
        self.folder = folder
        self.mode = mode
        self.url = ""
        self.started = time.time()
        self.note = ""
        self._server: Optional[http.server.ThreadingHTTPServer] = None
        self._proc: Optional[subprocess.Popen] = None
        self._log: Any = None

    def as_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "folder": str(self.folder), "name": self.folder.name, "mode": self.mode,
                "url": self.url, "started": self.started, "note": self.note, "alive": self.alive()}

    def alive(self) -> bool:
        if self._proc is not None:
            return self._proc.poll() is None
        return self._server is not None

    def serve_static(self) -> None:
        root = site_root(self.folder)
        handler = functools.partial(_Quiet, directory=str(root))
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._server.daemon_threads = True
        port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, name=f"nyx-preview-{self.id}", daemon=True).start()
        self.url = f"http://127.0.0.1:{port}/"
        if root != self.folder:
            self.note = f"Serving {root.name}/ — the folder's built output."
        elif not (root / "index.html").exists():
            self.note = "There is no index.html here, so the page lists the files."

    def run_dev(self, script: str) -> None:
        port = _free_port()
        env = dict(os.environ, PORT=str(port), BROWSER="none", FORCE_COLOR="0")
        self._log = open(data_path(f"previews/{self.id}.log"), "w", encoding="utf-8", errors="replace")
        npm = "npm.cmd" if os.name == "nt" else "npm"
        self._proc = subprocess.Popen([npm, "run", script], cwd=str(self.folder), env=env, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                      creationflags=_NO_WINDOW)
        found = threading.Event()

        def watch() -> None:
            assert self._proc is not None and self._proc.stdout is not None
            for line in self._proc.stdout:
                self._log.write(line)
                self._log.flush()
                match = re.search(r"https?://(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0):(\d{2,5})", line)
                if match and not found.is_set():
                    self.url = f"http://127.0.0.1:{match.group(1)}/"
                    found.set()

        threading.Thread(target=watch, name=f"nyx-preview-{self.id}", daemon=True).start()
        if not found.wait(DEV_WAIT_SECONDS):
            self.url = self.url or f"http://127.0.0.1:{port}/"
            self.note = (f"`npm run {script}` has not printed an address yet; trying port {port}. Its output is in "
                         f"previews/{self.id}.log.")

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._proc is not None and self._proc.poll() is None:
            if os.name == "nt":       # npm starts node under it; end the whole tree
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(self._proc.pid)], capture_output=True,
                               creationflags=_NO_WINDOW)
            else:
                self._proc.terminate()
        if self._log is not None:
            self._log.close()
            self._log = None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


_RUNNING: Dict[str, Preview] = {}
_LOCK = threading.Lock()


def start(path: str, mode: str = "auto") -> Dict[str, Any]:
    """Serve a folder until it is stopped. The same folder twice gives back the running preview."""
    folder = allowed_folder(path)
    with _LOCK:
        for preview in list(_RUNNING.values()):
            if preview.folder == folder and preview.alive():
                return preview.as_dict()
            if not preview.alive():
                _RUNNING.pop(preview.id, None)
        if len(_RUNNING) >= MAX_RUNNING:
            raise PreviewError(f"{MAX_RUNNING} previews are running already. Stop one first.")
    script = dev_script(folder) if mode in ("auto", "dev") else ""
    if mode == "dev" and not script:
        raise PreviewError("There is no dev or start script with its packages installed (run npm install first).")
    preview = Preview(folder, "dev" if script else "static")
    try:
        preview.run_dev(script) if script else preview.serve_static()
    except OSError as error:
        preview.stop()
        raise PreviewError(f"Could not start the preview: {error}") from error
    with _LOCK:
        _RUNNING[preview.id] = preview
    return preview.as_dict()


def stop(preview_id: str) -> Dict[str, Any]:
    with _LOCK:
        preview = _RUNNING.pop(preview_id, None)
    if preview is None:
        raise PreviewError("That preview is not running.")
    preview.stop()
    return {"stopped": preview_id}


def stop_all() -> None:
    with _LOCK:
        previews = list(_RUNNING.values())
        _RUNNING.clear()
    for preview in previews:
        preview.stop()


def running() -> List[Dict[str, Any]]:
    with _LOCK:
        return [p.as_dict() for p in _RUNNING.values()]


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def zip_folder(path: str) -> Path:
    """The folder as a .zip in Nyx's data folder (replaced each time), without packages, history or caches."""
    folder = allowed_folder(path)
    target = data_path(f"previews/{re.sub(r'[^A-Za-z0-9._-]+', '-', folder.name) or 'site'}.zip")
    total = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for current, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in SKIP and not d.startswith(".")]
            for name in files:
                file = Path(current) / name
                try:
                    total += file.stat().st_size
                except OSError:
                    continue
                if total > ZIP_LIMIT:
                    archive.close()
                    target.unlink(missing_ok=True)
                    raise PreviewError("The folder is over 200 MB without its packages — too big to download from here.")
                archive.write(file, file.relative_to(folder.parent))
    return target


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


def tool_preview(path: str) -> str:
    try:
        preview = start(path)
    except PreviewError as error:
        return f"Not started: {error}"
    return (f"{preview['name']} is running at {preview['url']} ({'its dev server' if preview['mode'] == 'dev' else 'served as files'})"
            f"{' — ' + preview['note'] if preview['note'] else ''}. The owner can open it in the Code tab's preview, "
            "in a browser, or download the folder as a zip from there. It keeps running until stopped.")


def register_preview_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register(
        "preview_site",
        "Run a website or web game folder on this PC so the owner can try it: in a browser, inside Nyx, or as a "
        "download. Use after building a site or game. Only folders opened in the Code tab or an office's work folder.",
        [P("path", "string", "The folder (or a file in it)")], tool_preview, category="code",
        label=lambda a: f"Starting a preview of {Path(str(a.get('path', ''))).name}")
