"""Start Nyx with one click — no console window, no copy-pasted commands.

This is what the desktop shortcut, the Start Menu entry, the ``nyx://`` link on
the website, and "Start with Windows" all run.

Why it looks the way it does
----------------------------
**It runs on Python's own signed interpreter, not a custom .exe.** The packaged
``Nyx.exe`` was blocked on the owner's PC by Windows Smart App Control, which
refuses unsigned executables with no reputation (CodeIntegrity event 3077,
result 4551 on the logon task). That is why "the engine never turns on": every
start attempt was being killed before a line of our code ran. ``pythonw.exe``
from python.org is signed by the Python Software Foundation and is allowed, so
the shortcut and the ``nyx://`` handler point at it and run this file.

**A tray icon replaces "leave this window open".** A console that must stay open
is a console people close. The engine runs in the background; the icon near the
clock opens Nyx, restarts the engine, toggles start-with-Windows, and quits.

**Starting twice is harmless.** Clicking the shortcut while Nyx is running opens
the browser instead of launching a rival copy on port 8001. A named mutex covers
the race where two starts happen in the same second (a logon task and a click).

**Failures are shown, not swallowed.** With no console there is nowhere for a
traceback to go, so output goes to a log file and a startup failure pops up a
message box that says what happened and where the log is.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import quiet_windows

    # Every helper the launcher and the tray start (the engine, winget, the
    # browser) runs without opening a console window (Plan Null N87).
    quiet_windows.install()
except Exception:  # pragma: no cover - the launcher must start even if this does not
    quiet_windows = None  # type: ignore[assignment]

DEFAULT_PORT = 8000
HOST = "127.0.0.1"
# Enough room to find a gap without scanning forever if something is holding a
# whole range (a previous crashed instance, another dev server).
PORT_SEARCH_LIMIT = 20

#: The scheme the website and the web UI's Start button navigate to. A browser
#: cannot start a local process — that boundary exists for good reason — so the
#: honest way to make a button work is to let Windows launch us for the link.
URL_SCHEME = "nyx"

#: Name of the per-user Run value that starts Nyx when Windows starts.
RUN_VALUE_NAME = "NyxIchos"
_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

#: Held while a launcher owns the engine, so a second launcher waits instead of
#: starting a duplicate.
_MUTEX_NAME = "Local\\NyxIchosEngineLauncher"

#: How long to wait for the engine to answer after starting it. Cold starts on
#: a slow disk import a lot of modules; this is deliberately generous.
READY_TIMEOUT_SECONDS = 60.0

#: Actions a nyx:// link may ask for. Anything else is treated as "open".
LINK_ACTIONS = frozenset({"open", "start", "stop", "restart", "redeem"})


# ---------------------------------------------------------------------------
# Ports and discovery
# ---------------------------------------------------------------------------


def _port_is_free(port: int) -> bool:
    """Whether we could bind ``port`` right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
            return True
        except OSError:
            return False


def find_free_port(preferred: int = DEFAULT_PORT, limit: int = PORT_SEARCH_LIMIT) -> int:
    """Return the first free port at or after ``preferred``.

    Binding is the only reliable test: asking the OS whether a port is in use is
    inherently racy, and on Windows a socket in TIME_WAIT still refuses a bind
    without SO_REUSEADDR, which is exactly the case after a restart.
    """
    for offset in range(limit):
        candidate = preferred + offset
        if _port_is_free(candidate):
            return candidate
    raise RuntimeError(
        f"No free port between {preferred} and {preferred + limit - 1}. "
        "Something is holding that range - reboot, or close other dev servers."
    )


def probe_engine(port: int, timeout: float = 0.8) -> Optional[Dict[str, Any]]:
    """Return Nyx's health payload if Nyx (not some other server) answers on ``port``."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read(64_000).decode("utf-8", errors="replace"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if isinstance(payload, dict) and payload.get("status") == "ok" and "capabilities" in payload:
        return payload
    return None


def _state_file() -> Path:
    import paths

    return paths.data_path("engine.json")


def find_running_engine(preferred: int = DEFAULT_PORT, limit: int = PORT_SEARCH_LIMIT) -> Optional[int]:
    """The port of a Nyx engine already running on this machine, or None.

    The engine records its port when it starts, so the usual case is a single
    probe. The range scan covers an engine started some other way (uvicorn by
    hand, an older launcher) that never wrote the file.
    """
    candidates: List[int] = []
    try:
        recorded = json.loads(_state_file().read_text(encoding="utf-8")).get("port")
        if isinstance(recorded, int):
            candidates.append(recorded)
    except (OSError, ValueError):
        pass
    candidates += [p for p in range(preferred, preferred + limit) if p not in candidates]

    for port in candidates:
        # A free port cannot have an engine on it; skip the HTTP timeout.
        if _port_is_free(port):
            continue
        if probe_engine(port) is not None:
            return port
    return None


def wait_for_engine(port: int, timeout: float = READY_TIMEOUT_SECONDS,
                    alive: Callable[[], bool] = lambda: True) -> bool:
    """Poll until the engine answers, it dies, or ``timeout`` passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe_engine(port, timeout=1.0) is not None:
            return True
        if not alive():
            return False
        time.sleep(0.25)
    return False


def open_app(port: int, path: str = "/") -> None:
    """Open the workspace in the default browser."""
    webbrowser.open(f"http://localhost:{port}{path}")


# ---------------------------------------------------------------------------
# How Windows should start us
# ---------------------------------------------------------------------------


def project_dir() -> Path:
    import paths

    return paths.PROJECT_DIR


def windowless_python(executable: Optional[str] = None) -> str:
    """The console-free twin of the running interpreter (pythonw.exe), if present."""
    exe = Path(executable or sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(exe)


def launch_command(*extra: str) -> List[str]:
    """The argv that starts Nyx without a console window.

    A frozen build is its own entry point. A source install runs this file under
    pythonw.exe — which is also what keeps it runnable under Smart App Control.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra]
    return [windowless_python(), str(project_dir() / "launcher.py"), *extra]


def command_line(argv: List[str]) -> str:
    """Quote an argv the way the registry expects (each part in double quotes)."""
    parts = []
    for arg in argv:
        if arg == "%1" or (arg.startswith('"') and arg.endswith('"')):
            parts.append(arg if arg.startswith('"') else f'"{arg}"')
        elif arg.startswith("--"):
            parts.append(arg)
        else:
            parts.append(f'"{arg}"')
    return " ".join(parts)


def register_url_handler() -> bool:
    """Claim ``nyx://`` for this install, per-user.

    Written under HKCU so no administrator prompt is needed — a launcher that
    demands elevation on first run is a launcher people close. Idempotent: the
    write is skipped when the handler already points here. Best-effort: failing
    to register costs the link, never the app.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg

        target = command_line(launch_command("%1"))
        base = rf"Software\Classes\{URL_SCHEME}"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"{base}\shell\open\command") as key:
                if winreg.QueryValueEx(key, "")[0] == target:
                    return True
        except OSError:
            pass

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "URL:Nyx Ichos")
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")
        icon = project_dir() / "assets" / "brand" / "nyx.ico"
        if icon.is_file():
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\DefaultIcon") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(icon))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, rf"{base}\shell\open\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, target)
        return True
    except Exception:  # noqa: BLE001 - a missing link must never block startup
        return False


def url_handler_registered() -> bool:
    """Whether ``nyx://`` currently points at this install."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Classes\{URL_SCHEME}\shell\open\command") as key:
            return winreg.QueryValueEx(key, "")[0] == command_line(launch_command("%1"))
    except OSError:
        return False


def unregister_url_handler() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        for sub in (r"shell\open\command", r"shell\open", "shell", "DefaultIcon", ""):
            path = rf"Software\Classes\{URL_SCHEME}" + (rf"\{sub}" if sub else "")
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            except OSError:
                pass
        return True
    except Exception:  # noqa: BLE001
        return False


def autostart_command() -> str:
    return command_line(launch_command("--background"))


def autostart_enabled() -> bool:
    """Whether *this* install starts when Windows starts (per-user Run key).

    Compared against this install's own command, not merely "some Nyx entry
    exists": a second copy (or a moved folder) must not show the box ticked for a
    Run entry that will never start it.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value = winreg.QueryValueEx(key, RUN_VALUE_NAME)[0]
        return str(value).strip() == autostart_command()
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Turn start-with-Windows on or off. Returns the resulting state.

    The Run key rather than a scheduled task: it needs no elevation, starts
    pythonw directly (no console flash at logon), and is what Settings > Apps >
    Startup lists, so the owner can see and switch it off outside Nyx too.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except OSError:
                    pass
    except OSError:
        pass
    return autostart_enabled()


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


def parse_link(url: str) -> Tuple[str, Dict[str, str]]:
    """Turn ``nyx://redeem?key=…`` into ``("redeem", {"key": "…"})``.

    Unknown or empty actions mean "open": the most useful thing a link that
    reaches us can do is show the app.
    """
    text = (url or "").strip()
    if not text.lower().startswith(f"{URL_SCHEME}:"):
        return "open", {}
    parsed = urllib.parse.urlsplit(text)
    action = (parsed.netloc or parsed.path or "").strip("/").lower() or "open"
    action = action.split("/")[0]
    params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items() if v}
    return (action if action in LINK_ACTIONS else "open"), params


def app_path_for(action: str, params: Dict[str, str]) -> str:
    if action == "redeem" and params.get("key"):
        return "/?redeem=" + urllib.parse.quote(params["key"], safe="")
    return "/"


# ---------------------------------------------------------------------------
# Talking to a running engine
# ---------------------------------------------------------------------------


def control_engine(port: int, action: str, timeout: float = 5.0) -> bool:
    """Ask a running engine to stop or restart itself."""
    request = urllib.request.Request(
        f"http://{HOST}:{port}/api/engine/{action}", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


# ---------------------------------------------------------------------------
# The engine itself
# ---------------------------------------------------------------------------


class Engine:
    """Uvicorn on a background thread, so the main thread can own the tray icon."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.server = None
        self.thread: Optional[threading.Thread] = None
        self.error: Optional[BaseException] = None
        self.on_stopped: Optional[Callable[[], None]] = None
        self.restart_requested = False

    def start(self) -> None:
        import uvicorn

        from server import app

        # timeout_graceful_shutdown: an open browser tab holds the live event
        # stream (SSE) forever, and uvicorn's default graceful shutdown waits for
        # every connection to close — so Stop and Restart hung whenever Nyx was
        # open in a browser. Three seconds lets in-flight requests finish.
        config = uvicorn.Config(app, host=HOST, port=self.port, log_level="info", access_log=False,
                                timeout_graceful_shutdown=3)
        self.server = uvicorn.Server(config)

        # Let the web UI (and nyx://stop) ask us to stop or restart. The server
        # module only calls these; it never learns about uvicorn or the tray.
        try:
            import server as server_module

            server_module.ENGINE_HOOKS.update({
                "stop": self.request_stop,
                "restart": self.request_restart,
                "port": self.port,
                "pid": os.getpid(),
                "launcher": True,
            })
        except Exception:
            pass

        def run() -> None:
            try:
                self.server.run()
            except BaseException as error:  # noqa: BLE001 - reported through self.error
                self.error = error
            finally:
                _forget_state(self.port)
                if self.on_stopped is not None:
                    try:
                        self.on_stopped()
                    except Exception:
                        pass
                # Once the server has stopped, nothing else in this process is
                # worth waiting for. If the tray loop does not unwind (seen when
                # the icon thread misses its stop message) the process would
                # linger holding the single-instance lock, and a restart's
                # successor would give up. Stores write synchronously, so a
                # hard exit here loses nothing.
                watchdog = threading.Timer(6.0, lambda: os._exit(0))
                watchdog.daemon = True
                watchdog.start()

        self.thread = threading.Thread(target=run, name="nyx-engine", daemon=True)
        self.thread.start()
        _record_state(self.port)

    def alive(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def request_stop(self) -> None:
        if self.server is not None:
            self.server.should_exit = True

    def request_restart(self) -> None:
        """Restart as a fresh process, so code and settings changes are picked up."""
        self.restart_requested = True
        try:
            _spawn_detached(launch_command("--background", "--wait-for-port", str(self.port)))
        finally:
            self.request_stop()

    def join(self, timeout: Optional[float] = None) -> None:
        if self.thread is not None:
            self.thread.join(timeout)


def _record_state(port: int) -> None:
    try:
        _state_file().write_text(
            json.dumps({"port": port, "pid": os.getpid(), "started_at": time.time()}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _forget_state(port: int) -> None:
    try:
        path = _state_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid() and data.get("port") == port:
            path.unlink()
    except (OSError, ValueError):
        pass


def _spawn_detached(argv: List[str]) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    options = dict(cwd=str(project_dir()), close_fds=True,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform == "win32":
        # Started as a logon task, the engine lives in Task Scheduler's job object,
        # which kills every process in it when the old engine exits — so a
        # restart's successor died with its parent and Nyx stayed down
        # (2026-09-15). Break away from the job when Windows allows it.
        try:
            subprocess.Popen(argv, creationflags=flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **options)
            return
        except OSError:
            pass
    subprocess.Popen(argv, creationflags=flags, **options)


# ---------------------------------------------------------------------------
# No console: logging and error dialogs
# ---------------------------------------------------------------------------


def log_path() -> Path:
    import paths

    return paths.data_path("logs/engine.log")


def _has_console() -> bool:
    return sys.stdout is not None and sys.stderr is not None


def redirect_output_to_log() -> Optional[Path]:
    """Under pythonw there is no console; keep output in a rolling log instead."""
    if _has_console():
        return None
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 5 * 1024 * 1024:
            path.replace(path.with_suffix(".log.1"))
        stream = open(path, "a", encoding="utf-8", buffering=1, errors="replace")
        stream.write(f"\n===== Nyx starting {time.strftime('%Y-%m-%d %H:%M:%S')} (pid {os.getpid()}) =====\n")
        sys.stdout = stream
        sys.stderr = stream
        return path
    except OSError:
        return None


def message_box(title: str, text: str, error: bool = False) -> None:
    """A native dialog when there is no console to print to."""
    if _has_console() or sys.platform != "win32":
        print(f"\n  {title}: {text}\n")
        return
    try:
        import ctypes

        flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, text, title, flags | 0x10000)  # MB_SETFOREGROUND
    except Exception:
        pass


def _mutex_name() -> str:
    """One mutex per data directory: a second install may run beside the first,
    but the same install may not start twice."""
    import hashlib

    import paths

    digest = hashlib.sha1(str(paths.DATA_DIR).lower().encode("utf-8")).hexdigest()[:12]
    return f"{_MUTEX_NAME}-{digest}"


class _SingleInstance:
    """A named mutex: the first launcher owns the engine, later ones defer to it."""

    def __init__(self) -> None:
        self.handle = None
        self.owned = True
        if sys.platform != "win32":
            return
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            self.handle = kernel32.CreateMutexW(None, False, _mutex_name())
            self.owned = kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
        except Exception:
            self.owned = True

    def release(self) -> None:
        if self.handle and sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.kernel32.CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None


# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------


def _tray_image():
    from PIL import Image

    brand = project_dir() / "assets" / "brand"
    for name in ("ichnos-64.png", "nyx.ico", "ichnos-32.png"):
        candidate = brand / name
        if candidate.is_file():
            try:
                return Image.open(candidate)
            except Exception:
                continue
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    from PIL import ImageDraw

    ImageDraw.Draw(image).ellipse((6, 6, 58, 58), fill=(145, 132, 217, 255))
    return image


def run_tray(engine: Engine) -> bool:
    """Block on the tray icon until the user quits. False when no tray is possible."""
    try:
        import pystray
    except Exception:
        return False

    def open_nyx(_icon=None, _item=None) -> None:
        open_app(engine.port)

    def restart(_icon=None, _item=None) -> None:
        engine.request_restart()

    admin: Dict[str, Any] = {}

    def open_admin(_icon=None, _item=None) -> None:
        """Start the admin access server on first use (loopback only) and open it."""
        port = int(os.getenv("NYX_ADMIN_PORT", "8765"))
        if not admin and _port_is_free(port):
            try:
                import admin_server

                admin["server"], admin["port"] = admin_server.start_in_thread(port)
                deadline = time.monotonic() + 10
                while _port_is_free(port) and time.monotonic() < deadline:
                    time.sleep(0.2)
            except Exception as error:  # noqa: BLE001 - shown to the owner
                message_box("Nyx admin console", f"The admin console could not start: {error}", error=True)
                return
        webbrowser.open(f"http://127.0.0.1:{port}/")

    def toggle_autostart(_icon=None, _item=None) -> None:
        set_autostart(not autostart_enabled())

    def open_data(_icon=None, _item=None) -> None:
        import paths

        try:
            os.startfile(str(paths.DATA_DIR))  # type: ignore[attr-defined]
        except Exception:
            pass

    def open_log(_icon=None, _item=None) -> None:
        try:
            os.startfile(str(log_path()))  # type: ignore[attr-defined]
        except Exception:
            pass

    def quit_nyx(icon, _item=None) -> None:
        engine.request_stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open Nyx", open_nyx, default=True),
        pystray.MenuItem("Restart engine", restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start with Windows", toggle_autostart, checked=lambda _item: autostart_enabled()),
        pystray.MenuItem("Admin console (testers, keys, access)", open_admin),
        pystray.MenuItem("Open data folder", open_data),
        pystray.MenuItem("View engine log", open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit Nyx", quit_nyx),
    )
    try:
        icon = pystray.Icon("NyxIchos", _tray_image(), f"Nyx Ichos — http://localhost:{engine.port}", menu)
    except Exception:
        return False

    # When the engine stops for any reason (web "Stop", restart, crash), the tray
    # must go too — an icon for a dead engine is a lie.
    engine.on_stopped = icon.stop
    try:
        icon.run()
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="Nyx", description="Nyx Ichos - local-first AI agent")
    parser.add_argument("url", nargs="?", default="",
                        help="A nyx:// link passed by Windows (start, open, stop, restart, redeem).")
    parser.add_argument("--no-browser", action="store_true",
                        help="Start the engine without opening a browser.")
    parser.add_argument("--background", action="store_true",
                        help="Start quietly (tray only, no browser). Used by start-with-Windows.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Preferred port (default {DEFAULT_PORT}). The next free port is used if taken.")
    parser.add_argument("--strict-port", action="store_true",
                        help="Fail instead of searching for a free port.")
    parser.add_argument("--console", action="store_true",
                        help="Stay in this console instead of the tray (for troubleshooting).")
    parser.add_argument("--wait-for-port", type=int, default=0,
                        help=argparse.SUPPRESS)  # used by restart: wait for the old engine to let go
    parser.add_argument("--register-only", action="store_true",
                        help="Register the nyx:// link for this install and exit.")
    parser.add_argument("--no-register", action="store_true",
                        help="Do not claim nyx:// for this copy (portable or test copies must not "
                             "steal the link from the installed one).")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    action, params = parse_link(args.url)
    if args.url and not args.url.lower().startswith(f"{URL_SCHEME}:"):
        action = "open"
    quiet = args.background or args.no_browser or action in ("start", "stop")

    redirect_output_to_log()
    if not args.no_register:
        register_url_handler()
    if args.register_only:
        return 0

    if args.wait_for_port:
        # A restart's successor. The old engine can take a while to let go (open event
        # streams, a turn finishing). Deferring to it as "already running" after 20 s left
        # nothing running once it did exit (2026-09-15), so wait up to a minute.
        deadline = time.monotonic() + 60
        while not _port_is_free(args.wait_for_port) and time.monotonic() < deadline:
            time.sleep(0.25)

    guard = _SingleInstance()
    if not guard.owned and args.wait_for_port:
        # A restart's successor: the old process is on its way out and still
        # holds the lock. Wait for it rather than deferring to an engine that
        # is shutting down.
        deadline = time.monotonic() + 30
        while not guard.owned and time.monotonic() < deadline:
            guard.release()
            time.sleep(0.5)
            guard = _SingleInstance()
    try:
        if not guard.owned:
            # Another launcher is starting the engine right now. Give it time to
            # come up, then behave exactly as if it had been running already.
            deadline = time.monotonic() + READY_TIMEOUT_SECONDS
            while time.monotonic() < deadline and find_running_engine(args.port) is None:
                time.sleep(0.5)

        running = find_running_engine(args.port)

        if action == "stop":
            if running is not None:
                control_engine(running, "stop")
            return 0

        if action == "restart" and running is not None:
            control_engine(running, "restart")
            return 0

        if running is not None:
            if not quiet or action == "redeem":
                open_app(running, app_path_for(action, params))
            print(f"  Nyx is already running on http://localhost:{running}/")
            return 0

        if not guard.owned:
            message_box("Nyx Ichos", "Nyx is starting in another window. Try again in a moment.")
            return 1

        try:
            # A verified beta update downloaded last session is installed before the engine loads it.
            import beta_channel

            applied = beta_channel.apply_staged()
            if applied:
                print(f"  Update: {applied.get('detail')}")
        except Exception as error:  # noqa: BLE001 - an update problem must never stop Nyx starting
            print(f"  Update skipped: {error}")

        return _start_engine(args, action, params, quiet)
    finally:
        guard.release()


def _run_repair() -> bool:
    """Open the setup window that installs whatever packages are missing.

    Used when the code has moved on (a new requirement) but the environment has
    not: rather than tell the user to go and run something, start it for them.
    """
    bat = project_dir() / "Start Nyx.bat"
    if getattr(sys, "frozen", False) or sys.platform != "win32" or not bat.is_file():
        return False
    try:
        os.startfile(str(bat), arguments="--repair")  # type: ignore[attr-defined]
        return True
    except (OSError, TypeError):
        return False


def _start_engine(args: argparse.Namespace, action: str, params: Dict[str, str], quiet: bool) -> int:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as error:
        if _run_repair():
            message_box(
                "Nyx Ichos is finishing setup",
                f"A package Nyx needs is missing ({error.name}), so setup has opened in a "
                "window to install it. Nyx starts by itself when it finishes.",
            )
        else:
            message_box(
                "Nyx Ichos needs setting up",
                f"Nyx's Python packages are not installed ({error.name}).\n\n"
                "Double-click 'Start Nyx.bat' in the Nyx folder once — it installs everything "
                "and creates the desktop shortcut.",
                error=True,
            )
        return 1

    # Newer optional pieces (tray icon, live specs, screenshots). The engine runs
    # without them, so start anyway and repair in the background.
    try:
        import setup_nyx

        if setup_nyx.missing_modules(("psutil", "PIL", "pystray")):
            _run_repair()
    except Exception:
        pass

    try:
        port = args.port if args.strict_port else find_free_port(args.port)
    except RuntimeError as error:
        message_box("Nyx Ichos could not start", str(error), error=True)
        return 1
    if args.strict_port and not _port_is_free(port):
        message_box("Nyx Ichos could not start", f"Port {port} is in use by another program.", error=True)
        return 1

    print(f"  Starting Nyx on http://localhost:{port}/")
    engine = Engine(port)
    try:
        engine.start()
    except Exception as error:  # noqa: BLE001 - the user needs to see anything that kills startup
        import traceback

        traceback.print_exc()
        message_box("Nyx Ichos could not start", f"{type(error).__name__}: {error}\n\nLog: {log_path()}", error=True)
        return 1

    if not wait_for_engine(port, alive=engine.alive):
        engine.request_stop()
        detail = f"{type(engine.error).__name__}: {engine.error}" if engine.error else "The engine did not answer in time."
        message_box("Nyx Ichos could not start", f"{detail}\n\nDetails are in the log:\n{log_path()}", error=True)
        return 1

    print(f"  Nyx is running on http://localhost:{port}/")
    if not quiet or action == "redeem":
        open_app(port, app_path_for(action, params))

    if args.console or not run_tray(engine):
        print("  Press Ctrl+C to stop Nyx.")
        try:
            while engine.alive():
                engine.join(0.5)
        except KeyboardInterrupt:
            engine.request_stop()

    engine.join(10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
