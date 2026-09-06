"""Generic folder reader for Nyx Ichos.

Register any local folder by name, then list, read, and search its files
regardless of format. Text files are read directly; media/binary files
(images, video, audio, archives) are reported with metadata and a placeholder
until multimodal support lands.

The registry of named folders is persisted to a JSON file (default
`folder_registry.json`, overridable via FOLDER_REGISTRY_PATH).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import SETTINGS

# Extensions we can read as text today.
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".tsx", ".jsx", ".json",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".csv", ".tsv", ".html",
    ".htm", ".css", ".scss", ".xml", ".log", ".sh", ".bat", ".cmd", ".ps1",
    ".sql", ".rst", ".tex", ".env", ".gitignore", ".dockerfile", ".c", ".h",
    ".cpp", ".hpp", ".cc", ".java", ".go", ".rs", ".rb", ".php", ".lua",
    ".r", ".jl", ".swift", ".kt", ".scala", ".vue", ".svelte", ".astro",
    ".ipynb", ".svg", ".properties", ".gradle", ".lock",
}

# Media/binary formats we recognize but cannot read as text yet.
MEDIA_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".ico",
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".mp3", ".wav", ".flac",
    ".ogg", ".m4a", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt",
    ".pptx", ".zip", ".tar", ".gz", ".7z", ".rar", ".exe", ".dll", ".so",
    ".dylib", ".bin", ".dat", ".db", ".sqlite", ".pyc", ".woff", ".woff2",
    ".ttf", ".otf", ".eot",
}


class FolderReaderError(RuntimeError):
    """Raised when a folder operation cannot be completed."""


class FolderReader:
    """Register local folders and read their files regardless of format."""

    def __init__(self, registry_path: Optional[str | Path] = None):
        configured = (
            registry_path
            or getattr(SETTINGS, "folder_registry_path", "")
            or "folder_registry.json"
        )
        self.registry_path = Path(configured).expanduser()
        self.folders: Dict[str, str] = self._load()

    # ------------------------------------------------------------------
    # Registry persistence
    # ------------------------------------------------------------------

    def _load(self) -> Dict[str, str]:
        if not self.registry_path.exists():
            return {}
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in (data.get("folders") or {}).items()}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"folders": self.folders}
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def add_folder(self, name: str, path: str) -> str:
        """Register a folder under a name. Returns the resolved absolute path."""
        name = name.strip().lower()
        if not name:
            raise FolderReaderError("Folder name cannot be empty.")
        folder = Path(path).expanduser()
        if not folder.exists() or not folder.is_dir():
            raise FolderReaderError(f"Folder does not exist or is not a directory: {path}")
        resolved = str(folder.resolve())
        self.folders[name] = resolved
        self._save()
        return resolved

    def remove_folder(self, name: str) -> str:
        """Unregister a folder. Returns the path that was removed."""
        name = name.strip().lower()
        if name not in self.folders:
            raise FolderReaderError(f"No registered folder named '{name}'.")
        removed = self.folders.pop(name)
        self._save()
        return removed

    def list_folders(self) -> List[Dict[str, Any]]:
        """Return registered folders with existence and file counts."""
        result = []
        for name, path in self.folders.items():
            folder = Path(path)
            exists = folder.exists() and folder.is_dir()
            result.append(
                {
                    "name": name,
                    "path": path,
                    "exists": exists,
                    "file_count": self._count_files(folder) if exists else 0,
                }
            )
        return result

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def list_files(
        self, name: str, recursive: bool = True, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List files in a registered folder, any format."""
        folder = self._require_folder(name)
        pattern = "**/*" if recursive else "*"
        files = []
        for f in sorted(folder.glob(pattern)):
            if not f.is_file():
                continue
            suffix = f.suffix.lower()
            files.append(
                {
                    "name": f.name,
                    "path": f.relative_to(folder).as_posix(),
                    "size": f.stat().st_size,
                    "extension": suffix or "(none)",
                    "kind": self._classify(suffix),
                }
            )
            if len(files) >= limit:
                break
        return files

    def read_file(
        self, name: str, relative_path: str, max_chars: int = 20000
    ) -> Dict[str, Any]:
        """Read a file from a registered folder.

        Text files return their content. Media/binary files return metadata
        and a placeholder until multimodal support is added.
        """
        folder = self._require_folder(name)
        target = self._resolve_inside(folder, relative_path)
        if not target.exists() or not target.is_file():
            raise FolderReaderError(f"File not found: {relative_path}")
        suffix = target.suffix.lower()
        kind = self._classify(suffix)
        size = target.stat().st_size
        rel = target.relative_to(folder).as_posix()

        if kind == "text":
            try:
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                raise FolderReaderError(f"Could not read file: {error}")
            if len(text) > max_chars:
                text = (
                    text[:max_chars]
                    + f"\n... [truncated: showing first {max_chars} of {len(text)} chars]"
                )
            return {"name": target.name, "path": rel, "kind": "text", "size": size, "content": text}

        if kind == "media":
            return {
                "name": target.name,
                "path": rel,
                "kind": "media",
                "size": size,
                "extension": suffix,
                "content": (
                    f"[{suffix.upper() or 'MEDIA'} file — {size} bytes. "
                    "Media reading is a future feature.]"
                ),
            }

        return {
            "name": target.name,
            "path": rel,
            "kind": "binary",
            "size": size,
            "extension": suffix,
            "content": f"[Binary file — {size} bytes. Not readable as text.]",
        }

    def search_files(
        self, name: str, query: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Search text files in a registered folder for a query string."""
        folder = self._require_folder(name)
        query_lower = (query or "").strip().lower()
        if not query_lower:
            raise FolderReaderError("Search query cannot be empty.")
        matches = []
        for f in sorted(folder.rglob("*")):
            if not f.is_file() or self._classify(f.suffix.lower()) != "text":
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if query_lower in text.lower():
                matches.append(
                    {
                        "name": f.name,
                        "path": f.relative_to(folder).as_posix(),
                        "snippet": _snippet(text, query_lower),
                    }
                )
                if len(matches) >= limit:
                    break
        return matches

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_folder(self, name: str) -> Path:
        name = name.strip().lower()
        if name not in self.folders:
            raise FolderReaderError(
                f"No registered folder named '{name}'. Use /folder add <name> <path> first."
            )
        folder = Path(self.folders[name])
        if not folder.exists() or not folder.is_dir():
            raise FolderReaderError(f"Registered folder no longer exists: {folder}")
        return folder

    def _resolve_inside(self, folder: Path, relative_path: str) -> Path:
        target = (folder / relative_path).resolve()
        root = folder.resolve()
        if target != root and root not in target.parents:
            raise FolderReaderError(f"Path escapes registered folder: {relative_path}")
        return target

    @staticmethod
    def _classify(suffix: str) -> str:
        if suffix in TEXT_EXTENSIONS:
            return "text"
        if suffix in MEDIA_EXTENSIONS:
            return "media"
        return "binary"

    @staticmethod
    def _count_files(folder: Path) -> int:
        return sum(1 for f in folder.rglob("*") if f.is_file())


def _snippet(text: str, query: str, radius: int = 120) -> str:
    """Build a short context window around the first query match."""
    index = text.lower().find(query)
    if index < 0:
        return text[: radius * 2].replace("\n", " ")
    start = max(0, index - radius)
    end = min(len(text), index + len(query) + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end].replace(chr(10), " ") + suffix


__all__ = ["FolderReader", "FolderReaderError"]
