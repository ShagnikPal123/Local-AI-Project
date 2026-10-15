"""Start Ichos Trader: ``python run_trader.py`` then open http://127.0.0.1:8100.

``--forever`` restarts the server if it ever exits (a crash, or the PC waking from sleep with a
dead socket), waiting a little longer each time it fails quickly, so the trader can run 24/7.
``--offline`` uses the built-in simulated market (no internet needed). ``--open`` opens the
dashboard once it answers, and ``--autostart on|off`` makes it start with Windows (or stops that).
By default it listens on 127.0.0.1 only. ``--host 0.0.0.0`` is for a cloud machine and needs a
login set up first (Google, GitHub or a passcode), or every visitor is refused.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from ichos_trader import config
from ichos_trader.autostart import set_autostart

HERE = Path(__file__).resolve().parent
WEB = HERE / "web"


def build_dashboard() -> None:
    """Build the dashboard once if it has never been built (needs Node.js; the API works without it)."""
    if (WEB / "dist" / "index.html").is_file():
        return
    npm = shutil.which("npm")
    if not npm:
        print("Node.js is not installed, so the dashboard is not built yet; the API still runs.")
        return
    print("Building the dashboard (first run only)…", flush=True)
    for step in (["install", "--no-audit", "--no-fund"], ["run", "build"]):
        if subprocess.call([npm, *step], cwd=WEB) != 0:
            print("The dashboard build failed; the API still runs.")
            return


def open_when_up(url: str, tries: int = 120) -> None:
    """Open the browser once the server answers, so the person never sees "can't connect"."""
    for _ in range(tries):
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.5)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run Ichos Trader.")
    parser.add_argument("--host", default=config.DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    parser.add_argument("--forever", action="store_true", help="restart the server whenever it exits")
    parser.add_argument("--offline", action="store_true", help="use the simulated market")
    parser.add_argument("--open", action="store_true", help="open the dashboard in the browser once it is up")
    parser.add_argument("--autostart", choices=("on", "off"), help="start with Windows (or stop doing so), then exit")
    args = parser.parse_args(argv)
    if args.autostart:
        print(set_autostart(args.autostart == "on", HERE))
        return 0
    build_dashboard()
    if args.open:
        threading.Thread(target=open_when_up, args=(f"http://{args.host}:{args.port}",), daemon=True).start()
    env = dict(os.environ, **({"ICHOS_TRADER_OFFLINE": "1"} if args.offline else {}))
    command = [sys.executable, "-m", "uvicorn", "ichos_trader.server:app", "--host", args.host,
               "--port", str(args.port)]
    print(f"Ichos Trader on http://{args.host}:{args.port}  (practice money only)")
    wait = 2.0
    while True:
        began = time.time()
        code = subprocess.call(command, cwd=HERE, env=env)
        if not args.forever:
            return code
        wait = 2.0 if time.time() - began > 300 else min(wait * 2, 120.0)
        print(f"The server stopped (exit {code}); starting again in {wait:.0f} s.", flush=True)
        time.sleep(wait)


if __name__ == "__main__":
    sys.exit(main())
