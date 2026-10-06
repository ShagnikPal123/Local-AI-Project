"""How changes reach beta testers: reviewed GitHub releases, verified, applied on restart (Request G2).

The owner: "in beta test make sure that changes are put through GitHub then added
or some kind of way… just let me know what way you do it."

The way:

1. Changes are made and tested here (Claude, Codex, the owner). Nyx's own
   self-improvements stay on this PC — nothing Nyx edits itself ships on its own.
2. The owner runs ``release_beta.py``: full test suite, UI build, secret scan, a
   versioned zip and a ``release.json`` with the zip's SHA-256. Nothing is public yet.
3. ``release_beta.py --publish`` (after the commits are pushed) creates a GitHub
   *pre-release* ``beta-<version>`` with those two files. That publish is the human
   review gate: no release, no update.
4. A tester's Nyx (a zip install, not a git checkout) checks the channel, downloads
   the zip, refuses it unless the SHA-256 matches, stages it, and applies it the
   next time Nyx starts — backing up every file it replaces so "Roll back" works.
   Personal data (chats, keys, memory, notes…) is never touched.

A git checkout (the owner's own copy) keeps updating with ``git`` (predictor.py).
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from paths import data_path

PROJECT = Path(__file__).resolve().parent
DEFAULT_REPO = "ShagnikPal123/Local-AI-Project"
TOP = "NyxIchos"


class UpdateError(RuntimeError):
    """A refused or failed update, with a sentence the owner or tester can act on."""


def _config_path() -> Path:
    return data_path("updates/channel.json")


def config() -> Dict[str, Any]:
    try:
        data = json.loads(_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"channel": data.get("channel", "beta"), "repo": data.get("repo") or os.getenv("NYX_UPDATE_REPO") or DEFAULT_REPO}


def set_channel(channel: str) -> Dict[str, Any]:
    if channel not in ("beta", "stable"):
        raise UpdateError("The channel is beta or stable.")
    current = config()
    current["channel"] = channel
    _config_path().parent.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def local_version(project: Optional[Path] = None) -> str:
    project = project or PROJECT
    try:
        return (project / "VERSION").read_text(encoding="utf-8").strip() or "0"
    except OSError:
        return "0"


def _version_key(version: str) -> List[int]:
    return [int(part) if part.isdigit() else 0 for part in version.replace("-", ".").split(".")]


def is_git_checkout(project: Optional[Path] = None) -> bool:
    project = project or PROJECT
    return (project / ".git").exists()


def latest_release(channel: Optional[str] = None, session: Any = requests) -> Optional[Dict[str, Any]]:
    cfg = config()
    channel = channel or cfg["channel"]
    try:
        response = session.get(f"https://api.github.com/repos/{cfg['repo']}/releases?per_page=20", timeout=15,
                               headers={"Accept": "application/vnd.github+json"})
    except requests.RequestException as error:
        raise UpdateError(f"Couldn't reach GitHub: {type(error).__name__}.") from error
    if response.status_code == 404:
        raise UpdateError("The update repository isn't public (or doesn't exist), so testers can't download from it.")
    if response.status_code >= 400:
        raise UpdateError(f"GitHub answered {response.status_code}.")
    for release in response.json():
        tag = str(release.get("tag_name", ""))
        if release.get("draft"):
            continue
        if channel == "beta" and not tag.startswith("beta-"):
            continue
        if channel == "stable" and (release.get("prerelease") or not tag.startswith("v")):
            continue
        assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
        zip_url = next((url for name, url in assets.items() if name.endswith(".zip")), None)
        if not zip_url or "release.json" not in assets:
            continue
        return {"tag": tag, "version": tag.split("-", 1)[-1].lstrip("v"), "notes": release.get("body") or "",
                "published_at": release.get("published_at"), "zip_url": zip_url, "manifest_url": assets["release.json"]}
    return None


def check(session: Any = requests) -> Dict[str, Any]:
    cfg = config()
    base = {"channel": cfg["channel"], "repo": cfg["repo"], "local_version": local_version(),
            "install_kind": "git" if is_git_checkout() else "zip", "staged": staged()}
    try:
        release = latest_release(cfg["channel"], session)
    except UpdateError as error:
        return {**base, "ok": False, "available": False, "detail": str(error)}
    if release is None:
        return {**base, "ok": True, "available": False, "detail": f"No {cfg['channel']} release has been published yet."}
    newer = _version_key(release["version"]) > _version_key(base["local_version"])
    return {**base, "ok": True, "available": newer, "latest": release,
            "detail": f"Version {release['version']} is ready to install." if newer else "Up to date."}


def _staged_path() -> Path:
    return data_path("updates/staged.json")


def staged() -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_staged_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def download(session: Any = requests) -> Dict[str, Any]:
    """Download and verify the newest release; it is applied the next time Nyx starts."""
    status = check(session)
    if status["install_kind"] == "git":
        raise UpdateError("This copy is a git checkout — update it with git (Settings → Updates uses git here).")
    if not status.get("available"):
        raise UpdateError(status["detail"])
    release = status["latest"]
    try:
        manifest = session.get(release["manifest_url"], timeout=20).json()
        response = session.get(release["zip_url"], timeout=300)
    except (requests.RequestException, ValueError) as error:
        raise UpdateError(f"Download failed: {type(error).__name__}.") from error
    if getattr(response, "status_code", 200) >= 400:
        raise UpdateError(f"Download failed ({response.status_code}).")
    digest = hashlib.sha256(response.content).hexdigest()
    if digest != manifest.get("sha256"):
        raise UpdateError("The download doesn't match its published checksum, so it was thrown away.")
    folder = data_path("updates")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"NyxIchos-{release['version']}.zip"
    target.write_bytes(response.content)
    # The checksum proves it is the published build; this asks whether the
    # published build is safe (archive traps, Windows Security).
    try:
        import file_guard

        verdict = file_guard.check_file(target, source="update download")
    except Exception:  # noqa: BLE001 - a broken checker must not block updating
        verdict = None
    if verdict is not None and verdict.blocked:
        try:
            target.unlink()
        except OSError:
            pass
        raise UpdateError(verdict.message)
    record = {"version": release["version"], "zip": str(target), "sha256": digest, "notes": release["notes"][:4000], "downloaded_at": time.time()}
    _staged_path().write_text(json.dumps(record, indent=2), encoding="utf-8")
    return {**status, "staged": record, "detail": f"Version {release['version']} downloaded — restart Nyx to install it."}


def _protected(relative: str) -> bool:
    """Personal data and keys are never overwritten by an update (the same list the release build excludes)."""
    import build_release

    posix = relative.replace("\\", "/")
    name = posix.rsplit("/", 1)[-1]
    for pattern in build_release.EXCLUDE:
        if pattern.endswith("/*") and pattern[:-2] in ("frontend/nyx-pulse/node_modules",):
            continue
        if fnmatch.fnmatch(posix, pattern) or ("/" not in pattern and fnmatch.fnmatch(name, pattern)):
            return True
    return posix.startswith(("data/", ".venv/", "notes/", "learning/", "brain/"))


def apply_staged(project: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Install a downloaded update before the engine starts. Returns what happened, or None when nothing is staged."""
    project = project or PROJECT
    record = staged()
    if not record or is_git_checkout(project):
        return None
    archive = Path(record["zip"])
    result: Dict[str, Any] = {"version": record["version"], "at": time.time()}
    try:
        if hashlib.sha256(archive.read_bytes()).hexdigest() != record["sha256"]:
            raise UpdateError("The staged update changed on disk; it was not installed.")
        backup = data_path(f"updates/backup-{local_version(project)}")
        written: List[str] = []
        with zipfile.ZipFile(archive) as bundle, tempfile.TemporaryDirectory() as temp:
            for info in bundle.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or not name.startswith(f"{TOP}/"):
                    continue
                relative = name[len(TOP) + 1:]
                if not relative or ".." in Path(relative).parts or Path(relative).is_absolute() or _protected(relative):
                    continue
                destination = project / relative
                if destination.exists():
                    saved = backup / relative
                    saved.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, saved)
                staging = Path(temp) / relative
                staging.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, open(staging, "wb") as sink:
                    shutil.copyfileobj(source, sink)
                written.append(relative)
            for relative in written:
                destination = project / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(Path(temp) / relative), destination)
        (project / "VERSION").write_text(record["version"], encoding="utf-8")
        result.update(ok=True, files=len(written), backup=str(backup), detail=f"Installed version {record['version']}.")
    except (UpdateError, OSError, zipfile.BadZipFile) as error:
        result.update(ok=False, detail=str(error))
    finally:
        try:
            _staged_path().unlink()
        except OSError:
            pass
    data_path("updates/last_apply.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def rollback(project: Optional[Path] = None) -> Dict[str, Any]:
    """Put back the files the last update replaced."""
    project = project or PROJECT
    try:
        last = json.loads(data_path("updates/last_apply.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise UpdateError("There's no installed update to roll back.") from error
    backup = Path(last.get("backup", ""))
    if not last.get("ok") or not backup.is_dir():
        raise UpdateError("The backup from the last update is missing, so it can't be rolled back.")
    restored = 0
    for path in backup.rglob("*"):
        if path.is_file():
            target = project / path.relative_to(backup)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            restored += 1
    (project / "VERSION").write_text(backup.name.replace("backup-", ""), encoding="utf-8")
    return {"ok": True, "restored": restored, "detail": f"Rolled back {restored} files. Restart Nyx to use them."}


def last_apply() -> Optional[Dict[str, Any]]:
    """What the most recent install did, if one has run on this copy."""
    try:
        return json.loads(data_path("updates/last_apply.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status() -> Dict[str, Any]:
    """Everything Settings → Updates shows before anyone presses a button. Never touches the network."""
    cfg = config()
    applied = last_apply()
    backup = Path(applied.get("backup", "")) if applied else None
    return {
        "channel": cfg["channel"], "repo": cfg["repo"], "local_version": local_version(),
        "install_kind": "git" if is_git_checkout() else "zip", "staged": staged(), "last_apply": applied,
        "can_roll_back": bool(applied and applied.get("ok") and backup and backup.is_dir()),
    }
