"""Entry point for the packaged build: start the engine and open the browser.

This is what `Nyx.exe` runs. It exists separately from `server.py` because a
packaged app has three problems a dev checkout does not:

* **Port 8000 may be taken.** A dev types a different port and moves on; a user
  who double-clicks an icon gets a stack trace and gives up. We find a free port
  and tell the browser about it.
* **The install directory is read-only.** Program Files is not writable, so all
  mutable state has to live in %LOCALAPPDATA%. `paths.py` already routes this
  when `sys.frozen` is set; the launcher just has to not fight it.
* **There is no console to read.** A packaged app that exits silently is
  indistinguishable from one that never started, so failures are held on screen.

Running this from a source checkout works too and is a convenient way to test
the packaged behaviour without building.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser

DEFAULT_PORT = 8000
HOST = "127.0.0.1"
# Enough room to find a gap without scanning forever if something is holding a
# whole range (a previous crashed instance, another dev server).
PORT_SEARCH_LIMIT = 20


def find_free_port(preferred: int = DEFAULT_PORT, limit: int = PORT_SEARCH_LIMIT) -> int:
    """Return the first free port at or after ``preferred``.

    Binding is the only reliable test: asking the OS whether a port is in use is
    inherently racy, and on Windows a socket in TIME_WAIT still refuses a bind
    without SO_REUSEADDR, which is exactly the case after a restart.
    """
    for offset in range(limit):
        candidate = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((HOST, candidate))
                return candidate
            except OSError:
                continue
    raise RuntimeError(
        f"No free port between {preferred} and {preferred + limit - 1}. "
        "Something is holding that range - reboot, or close other dev servers."
    )


def open_browser_when_ready(port: int, timeout: float = 30.0) -> None:
    """Open the browser once the server actually answers.

    Opening on a fixed delay is a coin flip: too short and the user lands on
    ERR_CONNECTION_REFUSED and assumes the app is broken, too long and it feels
    dead. Polling the port is the honest signal.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.4)
            if probe.connect_ex((HOST, port)) == 0:
                webbrowser.open(f"http://localhost:{port}/")
                return
        time.sleep(0.25)
    print(f"  The engine did not answer within {timeout:.0f}s.")
    print(f"  Try opening http://localhost:{port}/ yourself.")


def main() -> int:
    import paths

    print()
    print("  Nyx Ichos")
    print("  Local-first AI agent")
    print("  " + "-" * 49)
    print(f"  Data directory: {paths.DATA_DIR}")

    try:
        port = find_free_port()
    except RuntimeError as error:
        print(f"\n  PROBLEM: {error}\n")
        return 1

    if port != DEFAULT_PORT:
        print(f"  Port {DEFAULT_PORT} was busy; using {port} instead.")

    print(f"  Opening http://localhost:{port}/ in your browser.")
    print()
    print("  Leave this window open while you use Nyx.")
    print("  Close it, or press Ctrl+C, to stop.")
    print("  " + "-" * 49)
    print()

    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()

    try:
        import uvicorn

        from server import app

        uvicorn.run(app, host=HOST, port=port, log_level="info")
    except KeyboardInterrupt:
        print("\n  Nyx has stopped.")
        return 0
    except Exception as error:  # noqa: BLE001 - the user needs to see anything that kills startup
        # A packaged app has no console history to scroll back through, so print
        # the failure and hold the window rather than vanishing.
        import traceback

        print("\n  PROBLEM: the engine could not start.\n")
        traceback.print_exc()
        print(f"\n  {type(error).__name__}: {error}")
        if getattr(sys, "frozen", False):
            input("\n  Press Enter to close. ")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
