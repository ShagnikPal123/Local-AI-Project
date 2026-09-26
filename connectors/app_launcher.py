"""Application and system launcher connector with confirmation gating."""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector, ConnectorManifest

logger = logging.getLogger(__name__)

# Common friendly app aliases across Windows/macOS/Linux
COMMON_APPS = {
    "notepad": ["notepad.exe", "notepad"],
    "calculator": ["calc.exe", "calculator", "gnome-calculator"],
    "browser": ["start", "open", "xdg-open"],
    "terminal": ["cmd.exe", "powershell.exe", "gnome-terminal", "xterm"],
    "vscode": ["code.cmd", "code", "code.exe"],
    "explorer": ["explorer.exe", "nautilus", "open ."],
}


class AppLauncherConnector(BaseConnector):
    """System connector to launch or open desktop applications safely."""

    def __init__(self):
        self._manifest = ConnectorManifest(
            name="app_launcher",
            description="Launch installed system applications upon user request (guarded by confirmation gate).",
            permissions=["execute", "system"],
            is_offline=True,
            requires_auth=False,
            is_write=True,
            risk_level="medium",
        )

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def is_available(self) -> bool:
        return True

    def find_app_command(self, app_name: str) -> Optional[List[str]]:
        """Resolve a friendly app name to an executable path or shell command."""
        key = app_name.lower().strip()
        candidates = COMMON_APPS.get(key, [app_name])

        for cand in candidates:
            # Check if command is on PATH
            resolved = shutil.which(cand)
            if resolved:
                return [resolved]

        # Windows-specific direct launch checks
        if platform.system() == "Windows":
            if key in ("calc", "calculator"):
                return ["calc.exe"]
            if key in ("notepad", "notes"):
                return ["notepad.exe"]

        return None

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        if action == "launch":
            app_name = params.get("app_name", "").strip()
            args = params.get("args", [])
            if not app_name:
                return {"success": False, "error": "app_name parameter cannot be empty."}

            cmd = self.find_app_command(app_name)
            if not cmd:
                return {
                    "success": False,
                    "error": f"Application '{app_name}' could not be located on this system.",
                }

            full_cmd = cmd + list(args)
            try:
                # Non-blocking launch in background
                subprocess.Popen(
                    full_cmd,
                    shell=(platform.system() == "Windows"),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    # shell=True means cmd.exe: without this it flashes a console over the owner's work.
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                return {
                    "success": True,
                    "launched": app_name,
                    "command": full_cmd,
                    "status": "started",
                }
            except Exception as e:
                logger.exception("Failed to launch application '%s'", app_name)
                return {"success": False, "error": str(e)}

        elif action == "list_common":
            return {
                "success": True,
                "common_apps": sorted(list(COMMON_APPS.keys())),
            }

        return {"success": False, "error": f"Unknown action '{action}' for app_launcher connector."}
