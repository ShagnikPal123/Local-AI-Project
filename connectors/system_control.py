"""Computer and system controls connector (clipboard, screenshots, processes, volume, lock)."""

from __future__ import annotations

import logging
import os
import platform
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector, ConnectorManifest

logger = logging.getLogger(__name__)

#: Windows console programs open a black window in front of the owner's typing without this.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SystemControlConnector(BaseConnector):
    """Provides computer controls including clipboard, screenshots, process listing, and system status."""

    def __init__(self):
        self._manifest = ConnectorManifest(
            name="system_control",
            description="Control computer hardware and OS actions (clipboard, screenshot, processes, volume, lock screen).",
            permissions=["read", "execute", "system"],
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

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        if action == "get_clipboard":
            return self._get_clipboard()
        elif action == "set_clipboard":
            return self._set_clipboard(params.get("text", ""))
        elif action == "take_screenshot":
            return self._take_screenshot(params.get("output_path"))
        elif action == "list_processes":
            return self._list_processes(params.get("limit", 20))
        elif action == "get_system_stats":
            return self._get_system_stats()
        elif action == "lock_workstation":
            return self._lock_workstation()
        elif action == "open_url":
            return self._open_url(params.get("url", ""))
        else:
            return {"success": False, "error": f"Unknown action '{action}' for system_control connector."}

    def _get_clipboard(self) -> Dict[str, Any]:
        """Read text from the OS clipboard."""
        system = platform.system()
        try:
            if system == "Windows":
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Get-Clipboard"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=True,
                    creationflags=_NO_WINDOW,
                )
                return {"success": True, "clipboard": result.stdout.strip()}
            elif system == "Darwin":
                result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=3, check=True)
                return {"success": True, "clipboard": result.stdout.strip()}
            else:
                result = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True, timeout=3, check=True)
                return {"success": True, "clipboard": result.stdout.strip()}
        except Exception as e:
            return {"success": False, "error": f"Failed to read clipboard: {e}", "clipboard": ""}

    def _set_clipboard(self, text: str) -> Dict[str, Any]:
        """Copy text to the OS clipboard."""
        system = platform.system()
        try:
            if system == "Windows":
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Value @'\n{text}\n'@"],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=True,
                    creationflags=_NO_WINDOW,
                )
            elif system == "Darwin":
                p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                p.communicate(input=text.encode("utf-8"))
            else:
                p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                p.communicate(input=text.encode("utf-8"))
            return {"success": True, "copied_length": len(text)}
        except Exception as e:
            return {"success": False, "error": f"Failed to set clipboard: {e}"}

    def _take_screenshot(self, output_path: Optional[str] = None) -> Dict[str, Any]:
        """Capture a desktop screenshot and save it to file."""
        target_path = Path(output_path) if output_path else Path("screenshot.png")
        target_path = target_path.resolve()

        try:
            # Try PIL / Pillow if installed
            try:
                from PIL import ImageGrab  # type: ignore
                img = ImageGrab.grab()
                img.save(str(target_path))
                return {"success": True, "path": str(target_path), "method": "PIL"}
            except Exception:
                pass

            # Windows powershell fallback
            if platform.system() == "Windows":
                ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bitmap = New-Object System.Drawing.Bitmap $screen.Width, $screen.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)
$bitmap.Save('{str(target_path).replace(chr(92), chr(92)*2)}')
$graphics.Dispose()
$bitmap.Dispose()
"""
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, timeout=5, check=True,
                               creationflags=_NO_WINDOW)
                return {"success": True, "path": str(target_path), "method": "powershell"}

            return {"success": False, "error": "No screenshot utility available on this OS."}
        except Exception as e:
            return {"success": False, "error": f"Screenshot failed: {e}"}

    def _list_processes(self, limit: int = 20) -> Dict[str, Any]:
        """List active processes on the host."""
        processes = []
        try:
            if platform.system() == "Windows":
                res = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "Get-Process | Select-Object -First 30 Id, ProcessName, WorkingSet64 | ConvertTo-Json"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    creationflags=_NO_WINDOW,
                )
                import json
                raw = json.loads(res.stdout or "[]")
                if isinstance(raw, dict):
                    raw = [raw]
                for item in raw[:limit]:
                    processes.append({
                        "pid": item.get("Id"),
                        "name": item.get("ProcessName"),
                        "memory_mb": round(item.get("WorkingSet64", 0) / (1024 * 1024), 1),
                    })
            else:
                res = subprocess.run(["ps", "-eo", "pid,comm,%mem", "--sort=-%mem"], capture_output=True, text=True, timeout=5)
                lines = res.stdout.strip().splitlines()[1:limit+1]
                for line in lines:
                    parts = line.split(maxsplit=2)
                    if len(parts) >= 2:
                        processes.append({"pid": parts[0], "name": parts[1]})
            return {"success": True, "process_count": len(processes), "processes": processes}
        except Exception as e:
            return {"success": False, "error": str(e), "processes": []}

    def _get_system_stats(self) -> Dict[str, Any]:
        """Read basic OS status (platform, CPU cores, user)."""
        return {
            "success": True,
            "os": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "cpu_cores": os.cpu_count() or 1,
            "user": os.getlogin() if hasattr(os, "getlogin") else os.environ.get("USERNAME", "user"),
        }

    def _lock_workstation(self) -> Dict[str, Any]:
        """Lock the workstation screen."""
        try:
            if platform.system() == "Windows":
                subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], check=True, creationflags=_NO_WINDOW)
                return {"success": True, "action": "lock_workstation", "status": "locked"}
            elif platform.system() == "Darwin":
                subprocess.run(["pmset", "displaysleepnow"], check=True)
                return {"success": True, "action": "lock_workstation", "status": "locked"}
            return {"success": False, "error": "Lock workstation not supported on this OS."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _open_url(self, url: str) -> Dict[str, Any]:
        """Open a URL in the user's default browser."""
        import webbrowser
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            return {"success": True, "url": url, "status": "opened"}
        except Exception as e:
            return {"success": False, "error": str(e)}
