"""Nyx's own computer: a sandboxed desktop it works on instead of the owner's screen (Update 1, U49).

The owner (2026-10-05): "Using this https://cua.ai/, add to the ai so it will basically have its own computer setup
so when I don't want it to use my screen it works on this one and won't interrupt me unless I say it can or it asks."

Two halves:

* **Its own computer.** A Linux desktop in a sandbox, driven through Cua's open-source Computer SDK (``cua-computer``,
  MIT): screenshots, mouse, keyboard, scrolling, opening apps and links, a shell and files — all *inside* the sandbox.
  It runs either locally in Docker (free, needs Docker Desktop) or as a Cua Cloud sandbox (the owner's account and
  API key, billed by Cua by usage). Nothing it does there can touch this PC.
* **The owner's screen is theirs.** ``my_screen`` decides what the existing screen tools (``computer_control``:
  screen_view, mouse_*, keyboard_*, window tools) may do: ``never`` — refused, use your own computer; ``ask`` (the
  default) — an approval card in the chat, and a yes covers the next ``grant_minutes``; ``allow`` — as before.

The SDK runs in a small worker process (``own_computer_worker/worker.py``) with Cua's telemetry switched off, both in
its environment and on every computer it makes: nothing about the owner's use is sent anywhere by this module.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import atomic_replace, data_path

SCREEN_MODES = ("never", "ask", "allow")
PROVIDERS = ("docker", "cloud")
DEFAULTS: Dict[str, Any] = {
    "my_screen": "ask",
    "provider": "docker",
    # The light XFCE desktop: a smaller download than the full Ubuntu image, the same tools.
    "image": "trycua/cua-xfce:latest",
    "name": "nyx-computer",
    "cloud_name": "",
    "grant_minutes": 10,
    "display": "1280x800",
}
SECRET = "cua"
DOCKER_URL = "https://www.docker.com/products/docker-desktop/"
CLOUD_URL = "https://cua.ai"
#: How long one action inside the sandbox may take before Nyx gives up on it.
ACTION_TIMEOUT = 60.0
START_TIMEOUT = 600.0

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_LOCK = threading.RLock()


class OwnComputerError(RuntimeError):
    """Something the owner can act on: not set up, not running, an action that failed inside the sandbox."""


# --- settings -------------------------------------------------------------------------------------------------


def _path():
    return data_path("own_computer.json")


def settings() -> Dict[str, Any]:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    out = dict(DEFAULTS)
    out.update({k: v for k, v in (raw if isinstance(raw, dict) else {}).items() if k in DEFAULTS})
    if out["my_screen"] not in SCREEN_MODES:
        out["my_screen"] = DEFAULTS["my_screen"]
    if out["provider"] not in PROVIDERS:
        out["provider"] = DEFAULTS["provider"]
    return out


def save(**changes: Any) -> Dict[str, Any]:
    with _LOCK:
        current = settings()
        for key, value in changes.items():
            if key not in DEFAULTS or value is None:
                continue
            if key == "my_screen" and value not in SCREEN_MODES:
                raise OwnComputerError(f"Use one of: {', '.join(SCREEN_MODES)}.")
            if key == "provider" and value not in PROVIDERS:
                raise OwnComputerError(f"Use one of: {', '.join(PROVIDERS)}.")
            if key == "grant_minutes":
                value = max(1, min(240, int(value)))
            current[key] = value
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        atomic_replace(tmp, path)
    return status()


# --- what is installed -----------------------------------------------------------------------------------------


def sdk_installed() -> bool:
    return importlib.util.find_spec("computer") is not None


def docker_state() -> str:
    """"missing" (not installed), "stopped" (installed, engine not running) or "ready"."""
    if not shutil.which("docker"):
        return "missing"
    try:
        done = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True,
                              timeout=8, creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return "stopped"
    return "ready" if done.returncode == 0 and done.stdout.strip() else "stopped"


def cloud_key() -> str:
    try:
        import secret_store

        keys = secret_store.get_keys(SECRET)
        return keys[0] if keys else ""
    except Exception:  # noqa: BLE001
        return ""


def set_cloud_key(key: str) -> Dict[str, Any]:
    import secret_store

    key = (key or "").strip()
    secret_store.set_keys(SECRET, [key] if key else [])
    return status()


def readiness() -> Dict[str, Any]:
    """Can the chosen kind of computer start, and if not, the one thing to do next."""
    conf = settings()
    if not sdk_installed():
        return {"ready": False, "next": "Install the Cua Computer SDK (the Set up button does it: pip install cua-computer)."}
    if conf["provider"] == "docker":
        state = docker_state()
        if state == "missing":
            return {"ready": False, "next": "Install Docker Desktop (it sets up WSL 2 and needs a restart), then press "
                                            "Check again. Or switch to Cua Cloud.", "link": DOCKER_URL}
        if state == "stopped":
            return {"ready": False, "next": "Open Docker Desktop so its engine is running, then press Check again."}
        return {"ready": True, "next": ""}
    if not cloud_key():
        return {"ready": False, "next": "Add your Cua Cloud API key (cua.ai → your account). Cloud sandboxes are billed "
                                        "by Cua by usage.", "link": CLOUD_URL}
    if not conf["cloud_name"]:
        return {"ready": False, "next": "Type the name of the sandbox you made on cua.ai."}
    return {"ready": True, "next": ""}


# --- the computer itself ----------------------------------------------------------------------------------------
#
# The SDK runs in its own process (own_computer_worker/worker.py): Cua ships a top-level package called "core" and so
# does Nyx, so inside the engine the SDK could not import at all. The worker speaks one JSON object per line.

WORKER = Path(__file__).resolve().parent / "own_computer_worker" / "worker.py"


class WorkerTransport:
    """The worker process: start it, send requests, match replies by id."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._next = 0
        self._waiting: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _spawn(self) -> None:
        env = dict(os.environ, CUA_TELEMETRY="off", CUA_TELEMETRY_ENABLED="false", PYTHONIOENCODING="utf-8")
        self._proc = subprocess.Popen([sys.executable, str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1, env=env,
                                      creationflags=_NO_WINDOW)
        hello = threading.Event()
        self._waiting[0] = {"event": hello, "reply": None}
        threading.Thread(target=self._read, args=(self._proc,), name="nyx-own-computer-reader", daemon=True).start()
        if not hello.wait(30):
            self.close()
            raise OwnComputerError("The helper for Nyx's computer did not start.")

    def _read(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout or []:
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            with self._lock:
                slot = self._waiting.get(int(reply.get("id", -1)))
            if slot is not None:
                slot["reply"] = reply
                slot["event"].set()
        with self._lock:                      # the worker ended: nobody waits forever
            for slot in self._waiting.values():
                slot["event"].set()

    def request(self, op: str, timeout: float = ACTION_TIMEOUT, **args: Any) -> Any:
        if not self.alive():
            self._spawn()
        with self._lock:
            self._next += 1
            request_id = self._next
            slot = {"event": threading.Event(), "reply": None}
            self._waiting[request_id] = slot
        try:
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write(json.dumps({"id": request_id, "op": op, **args}) + "\n")
            self._proc.stdin.flush()
            if not slot["event"].wait(timeout):
                raise OwnComputerError("Nyx's computer did not answer in time.")
            reply = slot["reply"]
            if reply is None:
                raise OwnComputerError("The helper for Nyx's computer stopped.")
            if not reply.get("ok"):
                raise OwnComputerError(str(reply.get("error") or "It failed."))
            return reply.get("result")
        except (OSError, ValueError) as error:
            raise OwnComputerError(f"Could not reach Nyx's computer: {error}") from error
        finally:
            with self._lock:
                self._waiting.pop(request_id, None)

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=30)
        except Exception:  # noqa: BLE001 - a stuck helper is ended
            proc.kill()


class OwnComputer:
    """One sandbox computer, held by the worker process. ``transport`` is swapped for a fake in tests."""

    def __init__(self, transport: Any = None) -> None:
        self._transport = transport or WorkerTransport()
        self.state = "off"                 # off | starting | on | error | stopping
        self.error = ""
        self.started_at = 0.0
        self.last_shot: bytes = b""
        self.last_shot_at = 0.0
        self.actions: List[Dict[str, Any]] = []

    def _note(self, kind: str, text: str) -> None:
        entry = {"ts": time.time(), "kind": kind, "text": text[:200]}
        self.actions = (self.actions + [entry])[-60:]
        try:
            from agent_events import publish_ui

            publish_ui("own_computer.action", **entry)
        except Exception:  # noqa: BLE001 - the UI is a bonus
            pass

    # -- life

    def start(self) -> Dict[str, Any]:
        with _LOCK:
            if self.state in ("on", "starting"):
                return self.view()
            ready = readiness()
            if not ready["ready"]:
                raise OwnComputerError(ready["next"])
            self.state, self.error = "starting", ""
        try:
            self._transport.request("start", timeout=START_TIMEOUT, conf=settings(), api_key=cloud_key())
        except Exception as error:  # noqa: BLE001 - a computer that will not start is reported, not raised raw
            self.state, self.error = "error", str(error)[:400]
            self._note("error", f"Could not start: {self.error}")
            raise OwnComputerError(f"Nyx's computer could not start: {self.error}") from error
        self.state, self.started_at = "on", time.time()
        self._note("start", "Nyx's computer is on")
        return self.view()

    def stop(self) -> Dict[str, Any]:
        if self.state in ("on", "starting", "error"):
            self.state = "stopping"
            try:
                self._transport.request("stop", timeout=120)
            except Exception:  # noqa: BLE001 - stopping must always end in "off"
                pass
            self._note("stop", "Nyx's computer is off")
        try:
            self._transport.close()
        except Exception:  # noqa: BLE001
            pass
        self.state = "off"
        return self.view()

    def view(self) -> Dict[str, Any]:
        return {"state": self.state, "error": self.error, "started_at": self.started_at,
                "last_shot_at": self.last_shot_at, "actions": list(self.actions[-20:])}

    def _ask(self, op: str, timeout: float = ACTION_TIMEOUT, **args: Any) -> Any:
        if self.state != "on":
            if readiness()["ready"]:
                self.start()            # first use starts it: the owner already set it up
            else:
                raise OwnComputerError("Nyx's own computer is not set up yet: " + readiness()["next"])
        return self._transport.request(op, timeout=timeout, **args)

    # -- actions (inside the sandbox only)

    def screenshot(self) -> bytes:
        data = base64.b64decode(self._ask("screenshot") or "")
        self.last_shot, self.last_shot_at = data, time.time()
        return data

    def screen_size(self) -> Dict[str, int]:
        return dict(self._ask("screen_size") or {})

    def click(self, x: int, y: int, button: str = "left", double: bool = False) -> str:
        self._ask("click", x=int(x), y=int(y), button=button, double=bool(double))
        text = f"{'Double-clicked' if double else 'Clicked'} {button} at {int(x)},{int(y)}"
        self._note("click", text)
        return text + " on Nyx's computer."

    def type_text(self, text: str) -> str:
        self._ask("type", text=str(text))
        self._note("type", f"Typed {len(text)} characters")
        return f"Typed {len(text)} characters on Nyx's computer."

    def keys(self, combo: str) -> str:
        parts = [k.strip() for k in str(combo).replace(" ", "").split("+") if k.strip()]
        if not parts:
            raise OwnComputerError("Say which keys, e.g. enter or ctrl+l.")
        self._ask("keys", keys=parts)
        self._note("keys", f"Pressed {combo}")
        return f"Pressed {combo} on Nyx's computer."

    def scroll(self, amount: int) -> str:
        self._ask("scroll", amount=int(amount))
        direction = "down" if int(amount) < 0 else "up"
        self._note("scroll", f"Scrolled {direction} {abs(int(amount)) or 1}")
        return f"Scrolled {direction} {abs(int(amount)) or 1} on Nyx's computer."

    def open(self, target: str) -> str:
        self._ask("open", target=str(target))
        self._note("open", f"Opened {target}")
        return f"Opened {target} on Nyx's computer."

    def shell(self, command: str) -> str:
        result = self._ask("shell", timeout=180, command=str(command)) or {}
        self._note("shell", f"Ran: {command[:120]}")
        out, err, code = result.get("stdout", ""), result.get("stderr", ""), result.get("returncode")
        return (f"exit {code}\n" if code is not None else "") + out[-6000:] + (f"\n[stderr]\n{err[-3000:]}" if err else "")


COMPUTER = OwnComputer()


def status() -> Dict[str, Any]:
    conf = settings()
    ready = readiness()
    return {
        "settings": conf,
        "sdk": sdk_installed(),
        "docker": docker_state() if conf["provider"] == "docker" else "",
        "cloud_key": bool(cloud_key()),
        "ready": ready["ready"],
        "next": ready["next"],
        "link": ready.get("link", ""),
        "computer": COMPUTER.view(),
        "grant": _grant_view(),
    }


# --- the owner's screen: never, ask first, or allowed ------------------------------------------------------------

_grant_until = 0.0


def _grant_view() -> Dict[str, Any]:
    left = max(0.0, _grant_until - time.time())
    return {"active": left > 0, "seconds_left": int(left)}


def revoke_grant() -> Dict[str, Any]:
    global _grant_until
    _grant_until = 0.0
    return status()


def host_gate(action: str) -> None:
    """Before a tool touches the owner's own screen, mouse or keyboard. Raises PermissionDenied when it may not."""
    global _grant_until
    from permissions import PermissionDenied

    mode = settings()["my_screen"]
    if mode == "allow" or time.time() < _grant_until:
        return
    own = "Use your own computer instead (own_computer_view, own_computer_click, own_computer_type …)."
    if mode == "never":
        raise PermissionDenied(f"The owner's screen is off-limits ({action}). {own} If the task really needs their "
                               "screen, say so and ask them to allow it in the Nyx's Computer tab.")
    import permissions

    conf = settings()
    permissions.ask("computer", f"Use your screen: {action}",
                    f"Nyx wants to use your own screen, mouse and keyboard. If you say yes it may for the next "
                    f"{conf['grant_minutes']} minutes. Say no and it works on its own computer instead.")
    _grant_until = time.time() + 60 * int(conf["grant_minutes"])


# --- tools ---------------------------------------------------------------------------------------------------------


def _tool(fn: Callable[[], str]) -> str:
    try:
        return fn()
    except OwnComputerError as error:
        return f"Error: {error}"
    except Exception as error:  # noqa: BLE001 - a sandbox hiccup is reported to the model, not raised
        return f"Error on Nyx's computer: {type(error).__name__}: {error}"


def tool_view() -> str:
    def run() -> str:
        from tool_context import attach_image

        data = COMPUTER.screenshot()
        size = COMPUTER.screen_size()
        shown = attach_image(data, "image/png", name="nyx-computer.png",
                             note=f"Nyx's own computer, {size.get('width')}×{size.get('height')} px. Coordinates are "
                                  "pixels on this screenshot.")
        return (f"Showing your own computer's screen ({size.get('width')}×{size.get('height')})." if shown
                else "Captured your computer's screen but could not attach it here.")
    return _tool(run)


def register_own_computer_tools(registry: Any) -> None:
    from tools import ToolParam as P

    where = ("on Nyx's OWN computer — a sandboxed desktop, not the owner's screen; nothing here can touch their PC")

    def reg(name, description, params, handler, label):
        registry.register(name, description, params, handler, category="own_computer", label=label)

    reg("own_computer_view", f"Look at the screen {where}. Use before and after each step.", [], tool_view,
        "Looking at my own computer")
    reg("own_computer_click", f"Click at x,y {where}.",
        [P("x", "number", "x in screenshot pixels"), P("y", "number", "y in screenshot pixels"),
         P("button", "string", "left or right", required=False, enum_values=["left", "right"]),
         P("double", "boolean", "Double-click", required=False)],
        lambda x, y, button="left", double=False: _tool(lambda: COMPUTER.click(int(float(x)), int(float(y)), button or "left", bool(double))),
        lambda a: f"Clicking at {a.get('x')},{a.get('y')} on my computer")
    reg("own_computer_type", f"Type text into the focused window {where}.", [P("text", "string", "What to type")],
        lambda text: _tool(lambda: COMPUTER.type_text(text)), "Typing on my computer")
    reg("own_computer_keys", f"Press a key or shortcut {where}: enter, tab, ctrl+l, ctrl+c …",
        [P("keys", "string", "Keys joined with +")], lambda keys: _tool(lambda: COMPUTER.keys(keys)),
        lambda a: f"Pressing {a.get('keys', '')} on my computer")
    reg("own_computer_scroll", f"Scroll {where} (negative = down).", [P("amount", "number", "Notches; -5 scrolls down")],
        lambda amount: _tool(lambda: COMPUTER.scroll(int(float(amount)))), "Scrolling on my computer")
    reg("own_computer_open", f"Open a website, file or app {where}.", [P("target", "string", "URL, path or app name")],
        lambda target: _tool(lambda: COMPUTER.open(target)), lambda a: f"Opening {str(a.get('target', ''))[:40]} on my computer")
    reg("own_computer_shell", f"Run a shell command {where} (Linux). Use it to install tools, build or test there.",
        [P("command", "string", "The command")], lambda command: _tool(lambda: COMPUTER.shell(command)),
        lambda a: f"Running {str(a.get('command', ''))[:40]} on my computer")
