"""Overlay store for applied changes (ROADMAP F1, F2, F3, AA10).

Published changes land *here*, never in the base modules. The running app reads
base configuration and then applies the overlay on top, so:

* the shipped code is always intact and always the fallback,
* an update to the base app never wipes what a user (or the agent) changed,
* and reverting is deleting an overlay entry, not un-editing a file.

This is the "weighted self-update" idea from F1: the agent may change the app,
but only by adding a layer above it. It cannot reach the floor it stands on.

**Overlay values are data, not code.** A tab spec, a setting, a prompt — things
the app interprets. Nothing here is executed. Storing executable content would
hand anything that can publish a change a path to arbitrary execution, which is
the whole risk this layer exists to remove.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from paths import data_path

# Keep a bounded history so a long-lived install does not accumulate forever.
_MAX_CHECKPOINTS = 20


class OverlayError(Exception):
    """Raised when an overlay operation cannot be completed safely."""


def validate_target(target: str) -> str:
    """Return a clean overlay target, or raise.

    The overlay is a flat namespace of app-level keys, not a filesystem path.
    Exposed so callers earlier in the pipeline can reject a bad target at the
    point it is written, rather than letting it sit in a review queue looking
    approvable and only failing when someone tries to publish it.
    """
    clean = str(target or "").strip()
    if not clean:
        raise OverlayError("A change needs a target.")
    if any(ch in clean for ch in ("/", "\\", "..")):
        raise OverlayError(
            f"Invalid target {clean!r}: the overlay is a flat namespace, not a path."
        )
    return clean


@dataclass
class OverlayEntry:
    target: str
    value: Any
    change_id: str = ""
    applied_at: float = field(default_factory=time.time)
    applied_by: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "target": self.target,
            "value": self.value,
            "change_id": self.change_id,
            "applied_at": self.applied_at,
            "applied_by": self.applied_by,
        }


class OverlayStore:
    """Layer of applied changes sitting above the shipped app."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_path("overlay.json")
        self.checkpoint_dir = self.path.parent / "checkpoints"
        self._entries: Dict[str, OverlayEntry] = {}
        self._lock = threading.Lock()
        self._load()

    # --- persistence --------------------------------------------------------

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return
        for entry in raw.get("entries", []):
            try:
                overlay = OverlayEntry(
                    target=str(entry["target"]),
                    value=entry.get("value"),
                    change_id=str(entry.get("change_id", "")),
                    applied_at=float(entry.get("applied_at", time.time())),
                    applied_by=str(entry.get("applied_by", "")),
                )
            except Exception:
                continue
            self._entries[overlay.target] = overlay

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"entries": [e.as_dict() for e in self._entries.values()]}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as error:
            raise OverlayError(f"Could not write the overlay: {error}") from error

    # --- checkpoints (F2) ---------------------------------------------------

    def checkpoint(self, label: str = "") -> str:
        """Snapshot the current overlay before changing it.

        Taken *before* every apply, so there is always a known-good state to
        return to — including when the thing being applied is what breaks.
        """
        checkpoint_id = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
        try:
            self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
            snapshot = {
                "id": checkpoint_id,
                "label": label,
                "created_at": time.time(),
                "entries": [e.as_dict() for e in self._entries.values()],
            }
            (self.checkpoint_dir / f"{checkpoint_id}.json").write_text(
                json.dumps(snapshot, indent=2), encoding="utf-8"
            )
        except Exception as error:
            raise OverlayError(f"Could not write a checkpoint: {error}") from error

        self._prune_checkpoints()
        return checkpoint_id

    def _prune_checkpoints(self) -> None:
        """Drop the oldest checkpoints beyond the cap.

        Ordered by file mtime rather than name for the same reason as
        `list_checkpoints`: whole-second filenames would let this delete a newer
        checkpoint and keep an older one, which is the opposite of the job.
        """
        try:
            files = sorted(
                self.checkpoint_dir.glob("*.json"),
                key=lambda f: f.stat().st_mtime,
            )
            for stale in files[:-_MAX_CHECKPOINTS]:
                stale.unlink(missing_ok=True)
        except Exception:
            pass  # Pruning is housekeeping; never let it break an apply.

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """Checkpoints, newest first.

        Ordered by the `created_at` recorded inside each file, not by filename.
        Filenames carry only whole seconds, so two checkpoints taken in the same
        second sorted by the random suffix — which made "restore the latest"
        non-deterministic exactly when it matters most, during rapid changes.
        """
        results: List[Dict[str, Any]] = []
        try:
            for file in self.checkpoint_dir.glob("*.json"):
                try:
                    data = json.loads(file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                results.append({
                    "id": data.get("id", file.stem),
                    "label": data.get("label", ""),
                    "created_at": float(data.get("created_at", 0)),
                    "entries": len(data.get("entries", [])),
                })
        except Exception:
            pass
        return sorted(results, key=lambda c: c["created_at"], reverse=True)

    def restore(self, checkpoint_id: str) -> Dict[str, Any]:
        """Roll the overlay back to a checkpoint (F3, self code revival)."""
        file = self.checkpoint_dir / f"{checkpoint_id}.json"
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except Exception as error:
            raise OverlayError(f"Checkpoint {checkpoint_id} is unreadable.") from error

        with self._lock:
            self._entries = {}
            for entry in data.get("entries", []):
                try:
                    overlay = OverlayEntry(
                        target=str(entry["target"]),
                        value=entry.get("value"),
                        change_id=str(entry.get("change_id", "")),
                        applied_at=float(entry.get("applied_at", time.time())),
                        applied_by=str(entry.get("applied_by", "")),
                    )
                except Exception:
                    continue
                self._entries[overlay.target] = overlay
            self._save()

        return {"restored": checkpoint_id, "entries": len(self._entries)}

    def restore_latest(self) -> Dict[str, Any]:
        """Return to the most recent checkpoint. The panic button for F3."""
        checkpoints = self.list_checkpoints()
        if not checkpoints:
            raise OverlayError("No checkpoints exist to restore from.")
        return self.restore(checkpoints[0]["id"])

    # --- applying (AA10) ----------------------------------------------------

    def apply(self, target: str, value: Any, change_id: str = "", applied_by: str = "") -> OverlayEntry:
        """Apply a change to the overlay, checkpointing first.

        Rejects a target that would reach outside the overlay. The overlay is a
        flat namespace of app-level keys, not a filesystem path, and letting a
        target contain path separators would defeat the point of the layer.
        """
        clean = validate_target(target)
        self.checkpoint(label=f"before {clean}")

        with self._lock:
            entry = OverlayEntry(
                target=clean,
                value=value,
                change_id=change_id,
                applied_by=applied_by,
            )
            self._entries[clean] = entry
            self._save()
            return entry

    def revert(self, target: str) -> bool:
        """Remove an overlay entry, falling back to the shipped behaviour."""
        with self._lock:
            if target not in self._entries:
                return False
            self.checkpoint(label=f"before reverting {target}")
            del self._entries[target]
            self._save()
            return True

    # --- reads --------------------------------------------------------------

    def get(self, target: str, default: Any = None) -> Any:
        """Overlay value for a target, or the shipped default."""
        with self._lock:
            entry = self._entries.get(target)
        return entry.value if entry is not None else default

    def is_overridden(self, target: str) -> bool:
        with self._lock:
            return target in self._entries

    def list_entries(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [e.as_dict() for e in
                    sorted(self._entries.values(), key=lambda e: e.applied_at, reverse=True)]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "entries": self.list_entries(),
            "checkpoints": self.list_checkpoints(),
            "count": len(self._entries),
        }

    def clear(self) -> None:
        """Drop every override, returning the app to shipped behaviour."""
        with self._lock:
            if self._entries:
                self.checkpoint(label="before clearing all overrides")
            self._entries = {}
            self._save()


OVERLAY = OverlayStore()
