"""Configurable HUD widgets (ROADMAP DD6, DD7, DD8, DD9, DD11).

A widget is a small live window onto something the system already knows: hardware
telemetry, the agent team, the event log, a tab, or a saved prompt. The user
chooses which appear, in what order.

Two design choices worth stating:

* **Widgets are a declarative spec, not code.** A widget names a type and some
  config; the client renders it. Storing renderable code would be an injection
  surface and would break the update path, the same reasoning as the dynamic
  tabs note in ROADMAP section CC.
* **Layout is per-user data.** It persists to its own file and survives app
  updates, so a base-app change never silently rearranges someone's HUD.
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from paths import data_path


class WidgetType(Enum):
    """What a widget shows. The client has a renderer for each."""

    SYSTEM = "system"          # hardware telemetry
    AGENTS = "agents"          # live AI processes
    EVENTS = "events"          # streaming system log
    SOURCES = "sources"        # what the strand graph is built from
    FINANCE = "finance"        # market data
    TAB = "tab"                # a live window onto another tab
    PROMPT = "prompt"          # a saved prompt and its latest result


# Types that need a `target` in config to mean anything.
_NEEDS_TARGET = frozenset({WidgetType.TAB, WidgetType.PROMPT})


@dataclass
class Widget:
    widget_id: str
    type: WidgetType
    title: str = ""
    # Type-specific config: {"target": "models"} for TAB, {"prompt": "..."} for PROMPT.
    config: Dict[str, Any] = field(default_factory=dict)
    position: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.widget_id,
            "type": self.type.value,
            "title": self.title or self.type.value.title(),
            "config": dict(self.config),
            "position": self.position,
        }


DEFAULT_LAYOUT: List[Dict[str, Any]] = [
    {"type": "system", "title": "System"},
    {"type": "agents", "title": "AI processes"},
    {"type": "events", "title": "Activity"},
    {"type": "sources", "title": "Sources"},
]


class WidgetStore:
    """Per-user widget layout, persisted to disk."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_path("widgets.json")
        self._lock = threading.Lock()
        self._widgets: Dict[str, Widget] = {}
        self._load()

    # --- persistence --------------------------------------------------------

    def _load(self) -> None:
        """Read the saved layout, falling back to defaults on any problem.

        A corrupt layout file must not stop the HUD from rendering — the user
        loses their arrangement, not the application.
        """
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            entries = raw.get("widgets", [])
        except Exception:
            entries = []

        if not entries:
            self._install_defaults()
            return

        for entry in entries:
            try:
                widget = Widget(
                    widget_id=str(entry["id"]),
                    type=WidgetType(entry["type"]),
                    title=str(entry.get("title", "")),
                    config=dict(entry.get("config", {})),
                    position=int(entry.get("position", 0)),
                )
            except Exception:
                # Skip an unreadable entry rather than discarding the whole layout.
                continue
            self._widgets[widget.widget_id] = widget

        if not self._widgets:
            self._install_defaults()

    def _install_defaults(self) -> None:
        for index, spec in enumerate(DEFAULT_LAYOUT):
            widget = Widget(
                widget_id=uuid.uuid4().hex[:8],
                type=WidgetType(spec["type"]),
                title=str(spec.get("title", "")),
                position=index,
            )
            self._widgets[widget.widget_id] = widget

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"widgets": [w.as_dict() for w in self._ordered()]}
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            # Losing persistence is bad; crashing the request is worse.
            pass

    # --- reads --------------------------------------------------------------

    def _ordered(self) -> List[Widget]:
        return sorted(self._widgets.values(), key=lambda w: (w.position, w.title))

    def list_widgets(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [w.as_dict() for w in self._ordered()]

    def available_types(self) -> List[Dict[str, Any]]:
        """Widget types the user can add, and what each needs."""
        described = {
            WidgetType.SYSTEM: "Live hardware telemetry — temperature, VRAM, throttling.",
            WidgetType.AGENTS: "What each agent is doing right now.",
            WidgetType.EVENTS: "Streaming log of real system activity.",
            WidgetType.SOURCES: "What the strand graph is built from.",
            WidgetType.FINANCE: "Market data for a symbol you choose.",
            WidgetType.TAB: "A live window onto another tab.",
            WidgetType.PROMPT: "A saved prompt and its most recent answer.",
        }
        return [
            {
                "type": t.value,
                "description": described[t],
                "needs_target": t in _NEEDS_TARGET,
            }
            for t in WidgetType
        ]

    # --- writes -------------------------------------------------------------

    def add(
        self,
        widget_type: WidgetType,
        title: str = "",
        config: Optional[Dict[str, Any]] = None,
    ) -> Widget:
        """Add a widget. Raises ValueError when a bound type has no target."""
        config = dict(config or {})
        if widget_type in _NEEDS_TARGET and not str(config.get("target", "")).strip():
            raise ValueError(
                f"A {widget_type.value} widget needs a target — "
                "which tab, or which saved prompt, it should show."
            )
        with self._lock:
            widget = Widget(
                widget_id=uuid.uuid4().hex[:8],
                type=widget_type,
                title=title,
                config=config,
                position=len(self._widgets),
            )
            self._widgets[widget.widget_id] = widget
            self._save()
            return widget

    def remove(self, widget_id: str) -> bool:
        with self._lock:
            if widget_id not in self._widgets:
                return False
            del self._widgets[widget_id]
            self._save()
            return True

    def reorder(self, widget_ids: List[str]) -> List[Dict[str, Any]]:
        """Apply a new order. Unlisted widgets keep their relative position after."""
        with self._lock:
            for index, widget_id in enumerate(widget_ids):
                widget = self._widgets.get(widget_id)
                if widget is not None:
                    widget.position = index
            offset = len(widget_ids)
            for widget in self._widgets.values():
                if widget.widget_id not in widget_ids:
                    widget.position = offset
                    offset += 1
            self._save()
            return [w.as_dict() for w in self._ordered()]

    def reset(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._widgets.clear()
            self._install_defaults()
            self._save()
            return [w.as_dict() for w in self._ordered()]


WIDGET_STORE = WidgetStore()
