"""The process that holds Nyx's own computer (Update 1, U49). Started by ``own_computer.py``; never run by hand.

Why a separate process: Cua's SDK ships a top-level package called ``core``, and so does Nyx — inside the engine,
``from core.telemetry import …`` found Nyx's ``core`` and the SDK could not even import. This script lives in its own
folder, so its ``sys.path[0]`` is this folder, not the project, and Cua's ``core`` is the one found. It also keeps the
SDK's event loop, websockets and Docker calls out of the engine.

Protocol: one JSON object per line on stdin, one per line on stdout, matched by ``id``:
  → {"id": 1, "op": "start", "conf": {...}, "api_key": "..."}       ← {"id": 1, "ok": true, "result": ...}
Screenshots come back base64-encoded. The API key arrives on stdin, never in argv or the environment.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import threading

os.environ["CUA_TELEMETRY"] = "off"
os.environ["CUA_TELEMETRY_ENABLED"] = "false"

_computer = None
# stdout is the protocol. Anything the SDK prints goes to stderr instead, so a stray log line can never be read as
# a reply.
_OUT = sys.stdout
sys.stdout = sys.stderr


def _send(message: dict) -> None:
    _OUT.write(json.dumps(message) + "\n")
    _OUT.flush()


async def _start(conf: dict, api_key: str) -> dict:
    global _computer
    from computer import Computer  # type: ignore

    if conf.get("provider") == "cloud":
        _computer = Computer(os_type="linux", provider_type="cloud", name=conf.get("cloud_name") or "",
                             api_key=api_key, telemetry_enabled=False)
    else:
        _computer = Computer(os_type="linux", provider_type="docker", image=conf.get("image") or "trycua/cua-xfce:latest",
                             name=conf.get("name") or "nyx-computer", display=conf.get("display") or "1280x800",
                             telemetry_enabled=False)
    await _computer.run()
    return {"started": True}


async def _handle(op: str, args: dict):
    if op == "start":
        return await _start(args.get("conf") or {}, args.get("api_key") or "")
    if op == "ping":
        return {"pong": True}
    if _computer is None:
        raise RuntimeError("Nyx's computer is not started.")
    iface = _computer.interface
    if op == "stop":
        await _computer.stop()
        return {"stopped": True}
    if op == "screenshot":
        return base64.b64encode(await iface.screenshot()).decode("ascii")
    if op == "screen_size":
        return dict(await iface.get_screen_size())
    if op == "click":
        x, y = int(args["x"]), int(args["y"])
        if args.get("double"):
            await iface.double_click(x, y)
        elif args.get("button") == "right":
            await iface.right_click(x, y)
        else:
            await iface.left_click(x, y)
        return True
    if op == "type":
        await iface.type_text(str(args.get("text", "")))
        return True
    if op == "keys":
        keys = list(args.get("keys") or [])
        await (iface.hotkey(*keys) if len(keys) > 1 else iface.press_key(keys[0]))
        return True
    if op == "scroll":
        clicks = abs(int(args.get("amount", -3))) or 1
        await (iface.scroll_down(clicks) if int(args.get("amount", -3)) < 0 else iface.scroll_up(clicks))
        return True
    if op == "open":
        await iface.open(str(args.get("target", "")))
        return True
    if op == "shell":
        result = await iface.run_command(str(args.get("command", "")))
        return {"stdout": getattr(result, "stdout", "") or "", "stderr": getattr(result, "stderr", "") or "",
                "returncode": getattr(result, "returncode", None)}
    raise ValueError(f"Unknown operation: {op}")


async def _main() -> None:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def read() -> None:
        for line in sys.stdin:
            loop.call_soon_threadsafe(queue.put_nowait, line)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=read, daemon=True).start()
    _send({"id": 0, "ok": True, "result": {"ready": True}})
    while True:
        line = await queue.get()
        if line is None:
            break
        try:
            message = json.loads(line)
        except ValueError:
            continue
        request_id = message.get("id")

        async def run(message=message, request_id=request_id) -> None:
            try:
                result = await _handle(str(message.get("op")), message)
                _send({"id": request_id, "ok": True, "result": result})
            except Exception as error:  # noqa: BLE001 - every failure goes back to Nyx as text
                _send({"id": request_id, "ok": False, "error": f"{type(error).__name__}: {error}"[:600]})

        # Start and stop run one at a time; actions may overlap (a screenshot while a click lands).
        if message.get("op") in ("start", "stop"):
            await run()
        else:
            asyncio.create_task(run())
    if _computer is not None:
        try:
            await _computer.stop()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    asyncio.run(_main())
