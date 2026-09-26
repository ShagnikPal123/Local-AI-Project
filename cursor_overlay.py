"""The AI cursor you can see: a small click-through, always-on-top window.

Run as its own process by ``computer_control`` (so a Tk main loop never lives in
the engine). It reads one JSON command per line on stdin and exits when stdin
closes, so it can never outlive the engine:

    {"op": "move",  "x": 1200, "y": 640, "label": "Clicking Save", "ms": 320}
    {"op": "click", "x": 1200, "y": 640, "button": "left"}
    {"op": "type",  "x": 1200, "y": 640, "label": "Typing…"}
    {"op": "hide"}  {"op": "show"}  {"op": "quit"}

Coordinates are physical screen pixels (the process is per-monitor DPI aware,
like the screenshots). The window is only ~240×96 and moves with the cursor, so
it costs nothing when idle and hides itself after a few quiet seconds.
"""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
from typing import Any, Dict, Optional, Tuple

KEY = "#010203"  # transparent colour key
ACCENT = "#8B5CF6"
TIP = (34, 34)   # where the arrow tip sits inside the window
WIDTH, HEIGHT = 250, 100
IDLE_HIDE_SECONDS = 4.0


def parse_command(line: str) -> Optional[Dict[str, Any]]:
    """One stdin line → a validated command, or None to ignore it."""
    try:
        data = json.loads(line)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("op") not in {"move", "click", "type", "hide", "show", "quit"}:
        return None
    command: Dict[str, Any] = {"op": data["op"]}
    if data["op"] in {"move", "click", "type"}:
        try:
            command["x"], command["y"] = int(data["x"]), int(data["y"])
        except (KeyError, TypeError, ValueError):
            return None
        command["label"] = str(data.get("label", ""))[:48]
        command["ms"] = max(0, min(2000, int(data.get("ms", 280) or 0)))
        command["button"] = str(data.get("button", "left"))
    return command


def ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _dpi_aware() -> None:
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass


def _make_click_through(root: Any) -> None:
    """WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE: never takes a click or focus."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        GWL_EXSTYLE = -20
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | 0x80000 | 0x20 | 0x80 | 0x08000000)
    except Exception:
        pass


class Overlay:
    def __init__(self) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=KEY)
        try:
            self.root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            self.root.attributes("-alpha", 0.85)
        self.canvas = tk.Canvas(self.root, width=WIDTH, height=HEIGHT, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.root.update_idletasks()
        _make_click_through(self.root)
        self.pos: Tuple[float, float] = (-1000.0, -1000.0)
        self.label = ""
        self.ripple: Optional[Tuple[float, str]] = None  # (started, kind)
        self.anim: Optional[Tuple[Tuple[float, float], Tuple[float, float], float, float]] = None
        self.last_activity = 0.0
        self.visible = False
        self.commands: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        threading.Thread(target=self._read_stdin, daemon=True).start()
        self.root.withdraw()
        self.root.after(16, self._tick)

    def _read_stdin(self) -> None:
        for line in sys.stdin:
            command = parse_command(line)
            if command:
                self.commands.put(command)
        self.commands.put({"op": "quit"})  # engine gone

    def _show(self) -> None:
        if not self.visible:
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self.visible = True

    def _handle(self, command: Dict[str, Any]) -> bool:
        op = command["op"]
        if op == "quit":
            return False
        if op == "hide":
            self.root.withdraw()
            self.visible = False
            return True
        self.last_activity = time.monotonic()
        self._show()
        if op in {"move", "click", "type"}:
            target = (float(command["x"]), float(command["y"]))
            start = self.pos if self.pos[0] > -999 else target
            self.anim = (start, target, time.monotonic(), command["ms"] / 1000.0)
            if command["label"]:
                self.label = command["label"]
            if op == "click":
                self.ripple = (time.monotonic() + command["ms"] / 1000.0, command["button"])
            elif op == "type":
                self.ripple = (time.monotonic(), "type")
        return True

    def _tick(self) -> None:
        while True:
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                break
            if not self._handle(command):
                self.root.destroy()
                return
        now = time.monotonic()
        if self.anim:
            (sx, sy), (tx, ty), started, duration = self.anim
            t = 1.0 if duration <= 0 else (now - started) / duration
            k = ease_out(t)
            self.pos = (sx + (tx - sx) * k, sy + (ty - sy) * k)
            if t >= 1.0:
                self.anim = None
        if self.visible and now - self.last_activity > IDLE_HIDE_SECONDS and not self.anim:
            self.root.withdraw()
            self.visible = False
        if self.visible:
            self.root.geometry(f"{WIDTH}x{HEIGHT}+{int(self.pos[0]) - TIP[0]}+{int(self.pos[1]) - TIP[1]}")
            self._draw(now)
        self.root.after(16, self._tick)

    def _draw(self, now: float) -> None:
        c = self.canvas
        c.delete("all")
        x, y = TIP
        if self.ripple:
            started, kind = self.ripple
            age = now - started
            if 0 <= age < 0.6:
                radius = 6 + age / 0.6 * 26
                colour = "#F59E0B" if kind == "right" else ("#22D3EE" if kind == "type" else ACCENT)
                c.create_oval(x - radius, y - radius, x + radius, y + radius, outline=colour, width=3)
            elif age >= 0.6:
                self.ripple = None
        # Arrow cursor: dark outline, accent fill.
        arrow = [x, y, x, y + 26, x + 7, y + 20, x + 12, y + 31, x + 17, y + 29, x + 12, y + 18, x + 21, y + 18]
        c.create_polygon(arrow, fill=ACCENT, outline="#0B0B12", width=2)
        if self.label:
            text = self.label
            font = ("Segoe UI Semibold", 10)
            item = c.create_text(x + 30, y + 38, text=text, anchor="w", fill="#FFFFFF", font=font)
            box = c.bbox(item)
            if box:
                pill = c.create_rectangle(box[0] - 8, box[1] - 4, box[2] + 8, box[3] + 4, fill="#1E1B2E", outline=ACCENT, width=1)
                c.tag_lower(pill, item)
        c.create_text(x + 24, y + 12, text="Nyx", anchor="w", fill=ACCENT, font=("Segoe UI Black", 9))

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    _dpi_aware()
    try:
        Overlay().run()
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
