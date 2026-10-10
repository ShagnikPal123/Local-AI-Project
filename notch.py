"""The desktop notch: Ichos's voice as a pill at the top of the screen, outside the browser (owner, 2026-10-10:
"make sure it is separate from the chrome tab or the browser tab and instead can be on top of the screen like a notch
separated from apps").

A frameless, always-on-top Tk window owned by the engine (Tk ships with Python — no download). It never takes focus
when it changes, only when clicked (docs/DESIGN.md §7 Notch). States come from the page (``set_state``, posted by the
chat's voice bridge); the Talk button reaches the page through the workspace bus (``voice.toggle``). It hides while a
full-screen app or game runs (Windows sends no event for that, so it polls ``SHQueryUserNotificationState``), and it
sizes itself by state: a 360×34 pill, growing to 360×112 on hover with what was heard and two buttons.

Runs in its own thread; every Tk call happens on that thread. Off unless the owner turns it on.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Any, Dict, Optional

_state: Dict[str, Any] = {"state": "idle", "text": "", "voice": False, "at": 0.0}
_thread: Optional[threading.Thread] = None
_stop = threading.Event()
_lock = threading.Lock()

WORDS = {"idle": "Ichos", "listening": "Listening…", "thinking": "Thinking…", "speaking": "Speaking"}
COLORS = {"idle": "#a594ff", "listening": "#60cdff", "thinking": "#fce100", "speaking": "#6ccb5f"}
SMALL = (360, 34)
LARGE = (360, 112)


def set_state(state: str, text: str = "", voice: bool = False) -> None:
    with _lock:
        _state.update(state=state if state in WORDS else "idle", text=str(text or "")[:160], voice=bool(voice),
                      at=time.time())


def status() -> Dict[str, Any]:
    with _lock:
        return {"running": bool(_thread and _thread.is_alive()), **_state}


def _fullscreen_app_running() -> bool:
    """True while a game, video or presentation owns the screen (QUNS_BUSY / D3D full screen / presentation)."""
    if sys.platform != "win32":
        return False
    try:
        value = ctypes.c_int(0)
        if ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(value)) != 0:
            return False
        return value.value in (2, 3, 4)
    except Exception:  # noqa: BLE001
        return False


def _toggle_voice() -> None:
    try:
        from agent_events import publish_ui

        publish_ui("voice.toggle")
    except Exception:  # noqa: BLE001
        pass


def _open_app() -> None:
    try:
        import os
        import webbrowser

        webbrowser.open(f"http://127.0.0.1:{os.environ.get('NYX_PORT', '8000')}/")
    except Exception:  # noqa: BLE001
        pass


def _run() -> None:
    import tkinter as tk

    root = tk.Tk()
    root.overrideredirect(True)                  # no title bar, no taskbar button
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.96)
    except tk.TclError:
        pass
    bg = "#1c1c1c"
    root.configure(bg=bg)

    def place(size) -> None:
        width, height = size
        x = (root.winfo_screenwidth() - width) // 2
        root.geometry(f"{width}x{height}+{x}+0")

    place(SMALL)
    frame = tk.Frame(root, bg=bg, highlightthickness=1, highlightbackground="#3a3a3a")
    frame.pack(fill="both", expand=True)
    top = tk.Frame(frame, bg=bg)
    top.pack(fill="x", padx=12, pady=6)
    dot = tk.Canvas(top, width=12, height=12, bg=bg, highlightthickness=0)
    dot.pack(side="left")
    light = dot.create_oval(1, 1, 11, 11, fill=COLORS["idle"], outline="")
    label = tk.Label(top, text="Ichos", fg="#ffffff", bg=bg, font=("Segoe UI Variable Text", 10, "bold"))
    label.pack(side="left", padx=8)
    hint = tk.Label(top, text="hover for more", fg="#969696", bg=bg, font=("Segoe UI Variable Text", 9))
    hint.pack(side="right")
    more = tk.Frame(frame, bg=bg)
    heard = tk.Label(more, text="", fg="#cccccc", bg=bg, font=("Segoe UI Variable Text", 9), wraplength=330,
                     justify="left", anchor="w")
    heard.pack(fill="x", padx=12)
    buttons = tk.Frame(more, bg=bg)
    buttons.pack(fill="x", padx=12, pady=8)
    talk = tk.Button(buttons, text="Talk", command=_toggle_voice, bg="#a594ff", fg="#000000", relief="flat",
                     activebackground="#d6ceff", font=("Segoe UI Variable Text", 9, "bold"), padx=14)
    talk.pack(side="left")
    tk.Button(buttons, text="Open Ichos", command=_open_app, bg="#2d2d2d", fg="#ffffff", relief="flat",
              activebackground="#383838", font=("Segoe UI Variable Text", 9), padx=10).pack(side="left", padx=8)
    tk.Button(buttons, text="✕", command=lambda: _stop.set(), bg=bg, fg="#969696", relief="flat",
              activebackground="#2d2d2d", font=("Segoe UI Variable Text", 9)).pack(side="right")

    expanded = {"on": False}

    def expand(_event=None) -> None:
        if not expanded["on"]:
            expanded["on"] = True
            more.pack(fill="both", expand=True)
            hint.configure(text="")
            place(LARGE)

    def collapse(_event=None) -> None:
        x, y = root.winfo_pointerxy()
        inside = root.winfo_rootx() <= x <= root.winfo_rootx() + root.winfo_width() and \
            root.winfo_rooty() <= y <= root.winfo_rooty() + root.winfo_height()
        if expanded["on"] and not inside:
            expanded["on"] = False
            more.pack_forget()
            hint.configure(text="hover for more")
            place(SMALL)

    root.bind("<Enter>", expand)
    root.bind("<Leave>", collapse)

    hidden = {"on": False}

    def tick() -> None:
        if _stop.is_set():
            root.destroy()
            return
        current = status()
        state = current["state"]
        dot.itemconfigure(light, fill=COLORS.get(state, COLORS["idle"]))
        label.configure(text=WORDS.get(state, "Ichos") if current["voice"] or state != "idle" else "Ichos")
        heard.configure(text=f"“{current['text']}”" if current["text"] else "Say “Nyx”, or press Talk.")
        talk.configure(text="Stop" if current["voice"] else "Talk")
        busy = _fullscreen_app_running()
        if busy and not hidden["on"]:
            root.withdraw()
            hidden["on"] = True
        elif not busy and hidden["on"]:
            root.deiconify()
            root.attributes("-topmost", True)
            hidden["on"] = False
        root.after(250, tick)

    root.after(250, tick)
    root.mainloop()


def start() -> Dict[str, Any]:
    global _thread
    if _thread and _thread.is_alive():
        return status()
    _stop.clear()
    _thread = threading.Thread(target=_run, name="ichos-notch", daemon=True)
    _thread.start()
    return status()


def stop() -> Dict[str, Any]:
    _stop.set()
    return status()
