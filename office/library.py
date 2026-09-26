"""The office files and folders on disk — what the lobby shows and what File Explorer shows.

The naming the owner asked us to settle (*"Just work on the naming"*):

* an **office file** holds exactly one office — its team, its chat, its memory and its work folder;
* a **folder** holds office files and other folders, nested as deeply as you like, "just like in windows";
* a folder can **link work flows**, which makes the offices inside it share memory and read each other's work.

The tree on disk *is* the tree in the app, so "Open in File Explorer" lands exactly where the owner expects and
a folder they make in Explorer shows up in the lobby. On disk one office is a directory holding its own file::

    offices/                         ← the library root (never "office/": that is the code package)
      Client work/                   ← a folder      (.nyx-folder.json holds its id and the link flag)
        Site rebuild/                ← an office
          Site rebuild.office        ← the office file (all of its state)
          card.json                  ← the small summary the lobby reads, so it never parses the big file
          memory.json                ← what it remembers between sessions
          history.jsonl              ← chat and messages that aged out of the office file
          work/                      ← what the agents actually produced
      .trash/                        ← deleted offices, kept: this app never destroys the owner's work

Everything here is best-effort about *reading* (a half-written file must not hide the rest of the library) and
strict about *writing* (atomic replace, names sanitised for Windows, never a path outside the root).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paths import data_path

ROOT_NAME = "offices"
OFFICE_SUFFIX = ".office"
FOLDER_META = ".nyx-folder.json"
CARD = "card.json"
TRASH = ".trash"
MAX_DEPTH = 8

_lock = threading.RLock()
_cache: Dict[str, Any] = {"at": 0.0, "tree": None}
_CACHE_SECONDS = 1.0
_root_override: Optional[Path] = None

_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class LibraryError(ValueError):
    """Something the owner can fix: a name that cannot be used, a folder that is not empty, a missing office."""


def use_root(path: Optional[Path]) -> None:
    """Point the library somewhere else (tests, or a portable install)."""
    global _root_override
    with _lock:
        _root_override = Path(path) if path is not None else None
        _cache.update(at=0.0, tree=None)


def root() -> Path:
    with _lock:
        if _root_override is not None:
            _root_override.mkdir(parents=True, exist_ok=True)
            return _root_override
    path = data_path(f"{ROOT_NAME}/.keep").parent
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_name(name: str, *, what: str = "office") -> str:
    """A name Windows will actually accept, with the owner's own words kept wherever possible."""
    text = _BAD_CHARS.sub(" ", str(name or "")).strip().strip(".")
    text = re.sub(r"\s+", " ", text)[:60].strip()
    if not text:
        text = "New office" if what == "office" else "New folder"
    if text.lower() in _RESERVED or text.lower().split(".")[0] in _RESERVED:
        text = f"{text} ({what})"
    return text


def _unique_child(parent: Path, name: str) -> Path:
    candidate = parent / name
    if not candidate.exists():
        return candidate
    for index in range(2, 200):
        candidate = parent / f"{name} ({index})"
        if not candidate.exists():
            return candidate
    return parent / f"{name} ({int(time.time())})"


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


@dataclass
class Item:
    id: str
    name: str
    kind: str                       # "folder" | "office"
    path: str
    parent: str = ""                # parent folder id ("" = the root)
    linked: bool = False            # folders only: work flows linked
    created_at: float = 0.0
    updated_at: float = 0.0
    card: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        data = {"id": self.id, "name": self.name, "kind": self.kind, "path": self.path, "parent": self.parent,
                "created_at": self.created_at, "updated_at": self.updated_at}
        if self.kind == "folder":
            data["linked"] = self.linked
        else:
            data.update(self.card)
        return data


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 - an unreadable file is an empty one to the lobby
        return {}


def write_json(path: Path, data: Dict[str, Any], *, compact: bool = False) -> None:
    """Atomic write: a killed engine must never leave half an office file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) if compact
            else json.dumps(data, ensure_ascii=False, indent=2))
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _office_file(directory: Path) -> Optional[Path]:
    try:
        return next((p for p in directory.iterdir() if p.is_file() and p.suffix == OFFICE_SUFFIX), None)
    except OSError:
        return None


def _folder_meta(directory: Path) -> Dict[str, Any]:
    meta = _read_json(directory / FOLDER_META)
    if not meta.get("id"):
        meta = {"id": f"fld-{abs(hash(str(directory.resolve()))) % (16 ** 8):08x}", "linked": bool(meta.get("linked")),
                "created_at": meta.get("created_at") or _stat_time(directory)}
        try:
            write_json(directory / FOLDER_META, meta)
        except OSError:
            pass
    return meta


def _stat_time(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return time.time()


def _scan_dir(directory: Path, parent_id: str, depth: int, items: List[Item]) -> None:
    if depth > MAX_DEPTH:
        return
    try:
        children = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return
    for child in children:
        if not child.is_dir() or child.name.startswith(".") or child.name == TRASH:
            continue
        office_file = _office_file(child)
        if office_file is not None:
            card = _read_json(child / CARD)
            if not card.get("id"):
                card = _rebuild_card(child, office_file)
            items.append(Item(id=str(card.get("id") or ""), name=child.name, kind="office", path=str(child),
                              parent=parent_id, created_at=float(card.get("created_at") or _stat_time(child)),
                              updated_at=float(card.get("updated_at") or _stat_time(office_file)),
                              card={k: v for k, v in card.items() if k not in ("id", "created_at", "updated_at")}))
            continue
        meta = _folder_meta(child)
        folder_id = str(meta.get("id") or "")
        items.append(Item(id=folder_id, name=child.name, kind="folder", path=str(child), parent=parent_id,
                          linked=bool(meta.get("linked")), created_at=float(meta.get("created_at") or 0.0),
                          updated_at=_stat_time(child)))
        _scan_dir(child, folder_id, depth + 1, items)


def _rebuild_card(directory: Path, office_file: Path) -> Dict[str, Any]:
    """The lobby's summary, rebuilt from the office file when it is missing (or the owner copied a folder in)."""
    raw = _read_json(office_file)
    card = {
        "id": str(raw.get("id") or f"ofc-{abs(hash(str(directory.resolve()))) % (16 ** 8):08x}"),
        "name": str(raw.get("name") or directory.name),
        "created_at": float(raw.get("created_at") or _stat_time(directory)),
        "updated_at": float(raw.get("updated_at") or _stat_time(office_file)),
        "agents": len(raw.get("agents") or []),
        "sections": len(raw.get("sections") or []),
        "goal": str(raw.get("goal") or ""),
        "summary": "",
    }
    jobs = [j for j in (raw.get("jobs") or []) if isinstance(j, dict)]
    if jobs:
        card["summary"] = str(jobs[-1].get("summary") or jobs[-1].get("title") or "")[:300]
        card["last_request"] = str(jobs[-1].get("request") or "")[:300]
    try:
        write_json(directory / CARD, card)
    except OSError:
        pass
    return card


def scan(*, force: bool = False) -> List[Item]:
    """Every folder and office under the root, parents before children."""
    with _lock:
        fresh = _cache["tree"] is not None and time.time() - float(_cache["at"]) < _CACHE_SECONDS
        if fresh and not force:
            return list(_cache["tree"])
    items: List[Item] = []
    _scan_dir(root(), "", 1, items)
    with _lock:
        _cache.update(at=time.time(), tree=items)
    return list(items)


def invalidate() -> None:
    with _lock:
        _cache.update(at=0.0, tree=None)


def tree() -> Dict[str, Any]:
    """The lobby's view: folders and offices with their parents, plus the root path for "Open in File Explorer"."""
    items = scan()
    return {"root": str(root()),
            "folders": [i.as_dict() for i in items if i.kind == "folder"],
            "offices": [i.as_dict() for i in items if i.kind == "office"]}


def find(item_id: str) -> Optional[Item]:
    wanted = (item_id or "").strip()
    if not wanted:
        return None
    found = next((i for i in scan() if i.id == wanted), None)
    if found is None:  # a just-created item, before the cache expired
        found = next((i for i in scan(force=True) if i.id == wanted), None)
    return found


def _folder_path(parent_id: str) -> Path:
    if not parent_id:
        return root()
    item = find(parent_id)
    if item is None or item.kind != "folder":
        raise LibraryError("That folder is gone.")
    return Path(item.path)


def _inside_root(path: Path) -> bool:
    try:
        path.resolve().relative_to(root().resolve())
        return True
    except (ValueError, OSError):
        return False


# ---------------------------------------------------------------------------
# Making and moving things
# ---------------------------------------------------------------------------


def create_folder(name: str, parent_id: str = "") -> Dict[str, Any]:
    parent = _folder_path(parent_id)
    directory = _unique_child(parent, clean_name(name, what="folder"))
    directory.mkdir(parents=True, exist_ok=True)
    meta = {"id": f"fld-{os.urandom(4).hex()}", "linked": False, "created_at": time.time()}
    write_json(directory / FOLDER_META, meta)
    invalidate()
    return {"id": meta["id"], "name": directory.name, "kind": "folder", "path": str(directory),
            "parent": parent_id, "linked": False, "created_at": meta["created_at"], "updated_at": meta["created_at"]}


def create_office(name: str = "", parent_id: str = "") -> Tuple[Any, Path]:
    """A new office file, ready to be opened. Returns (Office, its directory)."""
    from office.state import Office, new_id

    parent = _folder_path(parent_id)
    directory = _unique_child(parent, clean_name(name or "New office"))
    (directory / "work").mkdir(parents=True, exist_ok=True)
    office = Office(id=new_id("ofc"), name=directory.name)
    save(office, directory)
    invalidate()
    return office, directory


def office_dir(office_id: str) -> Path:
    item = find(office_id)
    if item is None or item.kind != "office":
        raise LibraryError("That office is gone. It may have been moved or deleted outside Nyx.")
    return Path(item.path)


def work_dir(office_id: str) -> Path:
    directory = office_dir(office_id) / "work"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def load(office_id: str) -> Any:
    """Read an office file back into an Office."""
    from office.state import Office

    directory = office_dir(office_id)
    office_file = _office_file(directory)
    if office_file is None:
        raise LibraryError("That office file is missing.")
    raw = _read_json(office_file)
    if not raw:
        raise LibraryError("That office file could not be read.")
    office = Office.from_dict(raw)
    office.name = directory.name
    return office


def save(office: Any, directory: Optional[Path] = None) -> Path:
    """Write the office file and refresh the small card the lobby reads."""
    directory = Path(directory) if directory is not None else office_dir(office.id)
    directory.mkdir(parents=True, exist_ok=True)
    existing = _office_file(directory)
    target = existing if existing is not None else directory / f"{clean_name(office.name)}{OFFICE_SUFFIX}"
    office.updated_at = time.time()
    write_json(target, office.to_dict(), compact=True)
    last = office.jobs[-1] if office.jobs else None
    write_json(directory / CARD, {
        "id": office.id, "name": office.name, "created_at": office.created_at, "updated_at": office.updated_at,
        "agents": len(office.agents), "sections": len(office.sections), "goal": office.goal,
        "status": office.status, "jobs": len(office.jobs),
        "summary": (last.summary or last.title if last else "")[:300],
        "last_request": (last.request if last else "")[:300],
    })
    invalidate()
    return target


def rename(item_id: str, new_name: str) -> Dict[str, Any]:
    item = find(item_id)
    if item is None:
        raise LibraryError("That item is gone.")
    directory = Path(item.path)
    name = clean_name(new_name, what=item.kind)
    if name == directory.name:
        return item.as_dict()
    target = _unique_child(directory.parent, name)
    shutil.move(str(directory), str(target))
    if item.kind == "office":
        office_file = _office_file(target)
        if office_file is not None:
            renamed = target / f"{name}{OFFICE_SUFFIX}"
            if office_file != renamed:
                try:
                    os.replace(office_file, renamed)
                except OSError:
                    renamed = office_file
            raw = _read_json(renamed)
            raw["name"] = target.name
            write_json(renamed, raw, compact=True)
            card = _read_json(target / CARD)
            card["name"] = target.name
            write_json(target / CARD, card)
    invalidate()
    updated = find(item_id)
    return updated.as_dict() if updated else {"id": item_id, "name": target.name, "path": str(target)}


def move(item_id: str, parent_id: str) -> Dict[str, Any]:
    """Drag and drop: an office file (or a folder) into another folder."""
    item = find(item_id)
    if item is None:
        raise LibraryError("That item is gone.")
    source = Path(item.path)
    destination = _folder_path(parent_id)
    if not _inside_root(destination):
        raise LibraryError("That folder is outside the office library.")
    try:
        destination.resolve().relative_to(source.resolve())
        raise LibraryError("A folder cannot be moved into itself.")
    except ValueError:
        pass
    if source.parent.resolve() == destination.resolve():
        return item.as_dict()
    target = _unique_child(destination, source.name)
    shutil.move(str(source), str(target))
    invalidate()
    updated = find(item_id)
    return updated.as_dict() if updated else {"id": item_id, "path": str(target)}


def set_linked(folder_id: str, linked: bool) -> Dict[str, Any]:
    """*"If in the same folder I can click a button on the side that says link work flows so memory and work is linked."*"""
    item = find(folder_id)
    if item is None or item.kind != "folder":
        raise LibraryError("That folder is gone.")
    directory = Path(item.path)
    meta = _folder_meta(directory)
    meta["linked"] = bool(linked)
    write_json(directory / FOLDER_META, meta)
    invalidate()
    return {"id": folder_id, "linked": bool(linked), "name": directory.name, "path": str(directory)}


def delete(item_id: str) -> Dict[str, Any]:
    """Move an office (or an empty folder) into ``.trash``. Nothing here ever destroys the owner's work."""
    item = find(item_id)
    if item is None:
        raise LibraryError("That item is gone.")
    directory = Path(item.path)
    if item.kind == "folder":
        children = [i for i in scan() if i.parent == item_id]
        if children:
            raise LibraryError(f"{directory.name} still holds {len(children)} item(s). Move them out first.")
    trash = root() / TRASH
    trash.mkdir(parents=True, exist_ok=True)
    target = _unique_child(trash, f"{directory.name} {time.strftime('%Y-%m-%d %H%M')}")
    shutil.move(str(directory), str(target))
    invalidate()
    return {"id": item_id, "trashed": str(target)}


def parent_folder_of(office_id: str) -> Optional[Item]:
    item = find(office_id)
    if item is None or not item.parent:
        return None
    return find(item.parent)


def linked_siblings(office_id: str) -> List[Item]:
    """Other offices in the same folder when that folder has its work flows linked."""
    folder = parent_folder_of(office_id)
    if folder is None or not folder.linked:
        return []
    return [i for i in scan() if i.kind == "office" and i.parent == folder.id and i.id != office_id]


def reveal(path: str) -> str:
    """Open a folder in File Explorer (the owner's *"click a button to open in file explorer"*)."""
    target = Path(path)
    if not _inside_root(target) or not target.exists():
        raise LibraryError("That folder is not in the office library any more.")
    try:
        os.startfile(str(target))  # noqa: S606 - a directory, opened with the shell's own handler
        return str(target)
    except AttributeError:  # not Windows
        opener = shutil.which("xdg-open") or shutil.which("open")
        if not opener:
            raise LibraryError("Opening a folder is only supported on this computer's own desktop.")
        import subprocess

        subprocess.Popen([opener, str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return str(target)
    except OSError as error:
        raise LibraryError(f"Windows would not open that folder: {error}") from error
