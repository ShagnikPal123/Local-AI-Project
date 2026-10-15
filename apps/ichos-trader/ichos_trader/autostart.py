"""Start with Windows: a small file in the person's Startup folder, added or removed on request.

Only ``run_trader.py --autostart on|off`` calls this, so nothing outside the trader's folder changes
unless the person asks. The file starts the trader minimised with ``--forever``, so it runs 24/7
from sign-in and restarts itself if it ever stops.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

NAME = "Ichos Trader.cmd"


def startup_folder() -> Optional[Path]:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def set_autostart(on: bool, app_root: Path) -> str:
    folder = startup_folder()
    if folder is None:
        return "Start-with-Windows only works on Windows."
    target = folder / NAME
    if not on:
        if target.exists():
            target.unlink()
        return "Ichos Trader will no longer start with Windows."
    python = app_root / ".venv" / "Scripts" / "python.exe"
    folder.mkdir(parents=True, exist_ok=True)
    target.write_text("@echo off\r\n"
                      f'cd /d "{app_root}"\r\n'
                      f'start "Ichos Trader" /min "{python}" run_trader.py --forever\r\n', encoding="utf-8")
    return f"Ichos Trader will start with Windows ({target})."
