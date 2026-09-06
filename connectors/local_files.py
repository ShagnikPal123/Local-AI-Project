"""Local filesystem connector for reading and searching project files."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from connectors.base import BaseConnector, ConnectorManifest


class LocalFilesConnector(BaseConnector):
    """Connector for local file inspection, searching, and reading."""

    def __init__(self, root_dir: Optional[Path | str] = None, max_file_bytes: int = 500_000):
        self.root_dir = Path(root_dir).resolve() if root_dir else Path.cwd().resolve()
        self.max_file_bytes = max_file_bytes
        self._manifest = ConnectorManifest(
            name="local_files",
            description="Inspect, search, and read local workspace files and directories.",
            permissions=["read"],
            is_offline=True,
            requires_auth=False,
            is_write=False,
            risk_level="low",
        )

    @property
    def manifest(self) -> ConnectorManifest:
        return self._manifest

    def is_available(self) -> bool:
        return self.root_dir.exists() and self.root_dir.is_dir()

    def execute(self, action: str, **params: Any) -> Dict[str, Any]:
        if action == "read_file":
            return self._read_file(params.get("path", ""), max_lines=params.get("max_lines", 500))
        elif action == "search_files":
            return self._search_files(params.get("query", ""), max_results=params.get("max_results", 20))
        elif action == "list_dir":
            return self._list_dir(params.get("path", "."), depth=params.get("depth", 1))
        else:
            return {"success": False, "error": f"Unknown action '{action}' for local_files connector."}

    def _resolve_safe_path(self, relative_path: str) -> Optional[Path]:
        try:
            target = (self.root_dir / relative_path).resolve()
            # Ensure target is within root_dir
            target.relative_to(self.root_dir)
            return target
        except (ValueError, OSError):
            return None

    def _read_file(self, file_path: str, max_lines: int = 500) -> Dict[str, Any]:
        target = self._resolve_safe_path(file_path)
        if not target or not target.exists() or not target.is_file():
            return {"success": False, "error": f"File not found or outside root: {file_path}"}

        size = target.stat().st_size
        if size > self.max_file_bytes:
            return {"success": False, "error": f"File too large ({size} bytes > {self.max_file_bytes} byte limit)."}

        try:
            with target.open("r", encoding="utf-8", errors="replace") as f:
                lines = [f.readline() for _ in range(max_lines)]
                content = "".join(lines)
            return {
                "success": True,
                "path": str(target.relative_to(self.root_dir)),
                "size_bytes": size,
                "line_count": len(lines),
                "content": content,
            }
        except Exception as e:
            return {"success": False, "error": f"Failed to read file: {e}"}

    def _search_files(self, query: str, max_results: int = 20) -> Dict[str, Any]:
        if not query:
            return {"success": False, "error": "Query string cannot be empty."}

        results: List[Dict[str, Any]] = []
        q_lower = query.lower()

        for dirpath, dirnames, filenames in os.walk(self.root_dir):
            # Skip hidden / venv directories
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("venv", ".venv", "__pycache__", "node_modules")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                fpath = Path(dirpath) / fname
                rel_path = str(fpath.relative_to(self.root_dir))

                # Check filename match
                if q_lower in fname.lower():
                    results.append({"path": rel_path, "type": "filename_match", "snippet": fname})
                    if len(results) >= max_results:
                        return {"success": True, "query": query, "results": results}

                # Check content match for smaller text files
                try:
                    if fpath.stat().st_size <= 200_000:
                        content = fpath.read_text(encoding="utf-8", errors="ignore")
                        if q_lower in content.lower():
                            # Extract snippet
                            idx = content.lower().find(q_lower)
                            start = max(0, idx - 40)
                            end = min(len(content), idx + len(query) + 40)
                            snippet = content[start:end].replace("\n", " ")
                            results.append({"path": rel_path, "type": "content_match", "snippet": f"...{snippet}..."})
                            if len(results) >= max_results:
                                return {"success": True, "query": query, "results": results}
                except Exception:
                    pass

        return {"success": True, "query": query, "results": results}

    def _list_dir(self, sub_path: str = ".", depth: int = 1) -> Dict[str, Any]:
        target = self._resolve_safe_path(sub_path)
        if not target or not target.exists() or not target.is_dir():
            return {"success": False, "error": f"Directory not found: {sub_path}"}

        items: List[Dict[str, Any]] = []
        try:
            for entry in sorted(target.iterdir()):
                if entry.name.startswith(".") or entry.name in ("__pycache__", "node_modules", ".venv"):
                    continue
                items.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size_bytes": entry.stat().st_size if entry.is_file() else None,
                })
            return {"success": True, "path": str(target.relative_to(self.root_dir)), "items": items}
        except Exception as e:
            return {"success": False, "error": str(e)}
