"""Obsidian Local REST API & Vault Connector for Nyx Ichos.

Integrates with the Obsidian Local REST API plugin and local vault files
for reading, writing, appending, and searching notes and knowledge resources.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
import urllib3

from connectors.base import BaseConnector, ConnectorManifest

# Disable insecure HTTPS warnings for local self-signed certificates from Obsidian
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_DEFAULT_API_KEY = ""  # never a literal: set OBSIDIAN_API_KEY in .env.local


class ObsidianConnector(BaseConnector):
    """Bridge to an Obsidian vault via Local REST API or direct filesystem."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        port: int = 27124,
        vault_path: Optional[str] = None,
    ):
        self._api_key = api_key if api_key is not None else os.getenv("OBSIDIAN_API_KEY", _DEFAULT_API_KEY).strip()
        self._port = int(os.getenv("OBSIDIAN_PORT", str(port)))
        self._vault_path = vault_path or os.getenv("OBSIDIAN_VAULT_PATH", "")

    @property
    def manifest(self) -> ConnectorManifest:
        return ConnectorManifest(
            name="obsidian",
            description="Manage notes, knowledge bases, and resources in Obsidian vaults via Local REST API.",
            permissions=["read", "write", "search"],
            is_offline=True,
            requires_auth=True,
            is_write=True,
            risk_level="low",
            config_schema={
                "api_key": {"type": "string", "description": "Obsidian Local REST API token"},
                "port": {"type": "integer", "default": 27124, "description": "Local REST API port (default HTTPS 27124)"},
                "vault_path": {"type": "string", "default": "", "description": "Optional local folder fallback path"},
            },
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/vnd.olra+json",
        }

    def _base_url(self, secure: bool = True) -> str:
        protocol = "https" if secure else "http"
        return f"{protocol}://127.0.0.1:{self._port}"

    def is_available(self) -> bool:
        """Check if Obsidian REST API is responding or if a local vault path exists."""
        # The filesystem transport works whether or not Obsidian is open, so a
        # vault on disk answers instantly without probing the REST port.
        if self._vault_path and Path(self._vault_path).is_dir():
            return True
        if self._api_key:
            try:
                res = requests.get(
                    f"{self._base_url(secure=True)}/",
                    headers=self._headers(),
                    verify=False,
                    timeout=0.5,
                )
                if res.status_code in (200, 401, 403):
                    return True
            except Exception:
                pass

            try:
                res = requests.get(
                    f"{self._base_url(secure=False)}/",
                    headers=self._headers(),
                    timeout=1.0,
                )
                if res.status_code in (200, 401, 403):
                    return True
            except Exception:
                pass

        if self._vault_path and Path(self._vault_path).is_dir():
            return True

        # Always available as long as an API key is provided
        return bool(self._api_key)

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        """Execute Obsidian actions: list, read, write, append, search, status."""
        action = action.lower().strip()
        if action in ("status", "health"):
            return self._status()
        elif action in ("list", "list_notes", "list_files"):
            return self._list_files(params.get("directory", params.get("path", "")))
        elif action in ("read", "read_note", "get"):
            return self._read_note(params.get("path", params.get("filename", "")))
        elif action in ("write", "write_note", "put"):
            return self._write_note(
                params.get("path", params.get("filename", "")),
                params.get("content", params.get("text", "")),
            )
        elif action in ("append", "append_note"):
            return self._append_note(
                params.get("path", params.get("filename", "")),
                params.get("content", params.get("text", "")),
            )
        elif action in ("search", "search_notes"):
            return self._search(params.get("query", ""))
        else:
            return {
                "success": False,
                "error": f"Unknown Obsidian action: {action}. Available: list, read, write, append, search, status.",
            }

    def _status(self) -> Dict[str, Any]:
        api_reachable = False
        vault_name = ""
        for secure in (True, False):
            try:
                res = requests.get(
                    f"{self._base_url(secure=secure)}/",
                    headers=self._headers(),
                    verify=False,
                    timeout=1.5,
                )
                if res.ok:
                    api_reachable = True
                    data = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
                    vault_name = data.get("service", {}).get("vault", "") or data.get("vault", "Obsidian Vault")
                    break
            except Exception:
                continue

        return {
            "success": True,
            "api_reachable": api_reachable,
            "port": self._port,
            "has_api_key": bool(self._api_key),
            "vault_name": vault_name,
            "vault_path": self._vault_path,
        }

    def _list_files(self, directory: str = "") -> Dict[str, Any]:
        rel_path = directory.strip("/\\")
        url = f"{self._base_url(secure=True)}/vault/{rel_path}" if rel_path else f"{self._base_url(secure=True)}/vault/"
        try:
            res = requests.get(url, headers=self._headers(), verify=False, timeout=3.0)
            if res.ok:
                data = res.json()
                files = data.get("files", []) if isinstance(data, dict) else data
                return {"success": True, "files": files, "count": len(files)}
        except Exception:
            pass

        # Filesystem fallback if path configured
        if self._vault_path and Path(self._vault_path).is_dir():
            target = Path(self._vault_path) / rel_path
            if target.is_dir():
                found = [str(f.relative_to(Path(self._vault_path))) for f in target.glob("**/*.md")]
                return {"success": True, "files": found, "count": len(found), "source": "filesystem"}

        return {
            "success": False,
            "error": f"Could not list vault files. Ensure Obsidian Local REST API is active on port {self._port} or set OBSIDIAN_VAULT_PATH.",
        }

    def _read_note(self, path: str) -> Dict[str, Any]:
        rel_path = path.strip("/\\")
        if not rel_path.endswith(".md"):
            rel_path += ".md"

        url = f"{self._base_url(secure=True)}/vault/{rel_path}"
        try:
            res = requests.get(
                url,
                headers={"Authorization": f"Bearer {self._api_key}", "Accept": "text/markdown"},
                verify=False,
                timeout=3.0,
            )
            if res.ok:
                return {"success": True, "path": rel_path, "content": res.text}
        except Exception:
            pass

        if self._vault_path and Path(self._vault_path).is_dir():
            fp = Path(self._vault_path) / rel_path
            if fp.is_file():
                return {"success": True, "path": rel_path, "content": fp.read_text(encoding="utf-8")}

        return {"success": False, "error": f"Note '{rel_path}' could not be retrieved from Obsidian."}

    def _write_note(self, path: str, content: str) -> Dict[str, Any]:
        rel_path = path.strip("/\\")
        if not rel_path.endswith(".md"):
            rel_path += ".md"

        url = f"{self._base_url(secure=True)}/vault/{rel_path}"
        try:
            res = requests.put(
                url,
                data=content.encode("utf-8"),
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "text/markdown"},
                verify=False,
                timeout=4.0,
            )
            if res.status_code in (200, 204, 201):
                return {"success": True, "path": rel_path, "bytes_written": len(content)}
        except Exception:
            pass

        if self._vault_path and Path(self._vault_path).is_dir():
            fp = Path(self._vault_path) / rel_path
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding="utf-8")
            return {"success": True, "path": rel_path, "bytes_written": len(content), "source": "filesystem"}

        return {"success": False, "error": f"Could not write note '{rel_path}' to Obsidian."}

    def _append_note(self, path: str, content: str) -> Dict[str, Any]:
        rel_path = path.strip("/\\")
        if not rel_path.endswith(".md"):
            rel_path += ".md"

        url = f"{self._base_url(secure=True)}/vault/{rel_path}"
        try:
            res = requests.post(
                url,
                data=content.encode("utf-8"),
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "text/markdown"},
                verify=False,
                timeout=4.0,
            )
            if res.status_code in (200, 204, 201):
                return {"success": True, "path": rel_path, "appended": True}
        except Exception:
            pass

        if self._vault_path and Path(self._vault_path).is_dir():
            fp = Path(self._vault_path) / rel_path
            fp.parent.mkdir(parents=True, exist_ok=True)
            with open(fp, "a", encoding="utf-8") as f:
                f.write(("\n" if fp.exists() and fp.stat().st_size > 0 else "") + content)
            return {"success": True, "path": rel_path, "appended": True, "source": "filesystem"}

        return {"success": False, "error": f"Could not append to note '{rel_path}'."}

    def _search(self, query: str) -> Dict[str, Any]:
        if not query:
            return {"success": False, "error": "Search query cannot be empty."}

        url = f"{self._base_url(secure=True)}/search/simple"
        try:
            res = requests.post(
                url,
                params={"query": query},
                headers=self._headers(),
                verify=False,
                timeout=5.0,
            )
            if res.ok:
                matches = res.json()
                return {"success": True, "query": query, "matches": matches, "count": len(matches)}
        except Exception:
            pass

        if self._vault_path and Path(self._vault_path).is_dir():
            matches = []
            lowered = query.lower()
            for fp in Path(self._vault_path).glob("**/*.md"):
                try:
                    text = fp.read_text(encoding="utf-8", errors="ignore")
                    if lowered in text.lower() or lowered in fp.name.lower():
                        matches.append({
                            "filename": str(fp.relative_to(Path(self._vault_path))),
                            "score": text.lower().count(lowered),
                        })
                except Exception:
                    continue
            return {"success": True, "query": query, "matches": matches, "count": len(matches), "source": "filesystem"}

        return {"success": False, "error": f"Could not search Obsidian vault for '{query}'."}
