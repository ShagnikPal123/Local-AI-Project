"""What a running tool can reach: the turn it belongs to, and the user watching.

Tools are plain functions that return a string for the model. That stays true —
a tool must still work from the CLI, a test, or a background thought where no
one is watching. But inside a chat turn, a tool can do two more useful things:

* **Report progress** while it works ("Downloading 40%…"), so a slow step is
  visibly alive rather than indistinguishable from a hang.
* **Show the model an image** — a screenshot, an uploaded photo, a local picture
  it was asked about. Returning base64 in the result string would flood the
  context window with text the model cannot see as an image, so images ride
  alongside and are attached to the model's next call instead.

The context travels in a ``ContextVar`` so no tool signature has to change.
Helpers are no-ops outside a turn, which is what keeps tools usable everywhere.
"""

from __future__ import annotations

import base64
import contextvars
import io
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional

#: Largest edge of the thumbnail sent to the UI. The model gets the full image;
#: the timeline only needs something recognisable, and SSE frames should stay small.
_THUMB_EDGE = 360

#: Hard cap on one image handed to a model, after any caller-side resizing.
#: Providers reject or silently truncate very large inline payloads.
MAX_MODEL_IMAGE_BYTES = 7 * 1024 * 1024


@dataclass
class ToolContext:
    """Per-turn state shared by every tool call inside that turn."""

    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    chat_id: str = "default"
    #: "local" (unclaimed install), or the signed-in account's role.
    role: str = "local"
    #: Where events go. The chat service installs a sink that publishes on the
    #: turn's channel; None means nobody is listening.
    sink: Optional[Callable[[Dict[str, Any]], None]] = None
    #: Images waiting to be shown to the model on its next call.
    pending_images: List[Dict[str, str]] = field(default_factory=list)
    #: Id of the tool call currently running, so progress lines attach to it.
    call_id: str = ""
    #: Set when the user presses Stop. Long-running tools should check it.
    cancelled: threading.Event = field(default_factory=threading.Event)
    #: An extra gate for this turn's tools — the Free Will tab's (freewill.guard). Called with (tool name, category)
    #: before a tool runs; it raises PermissionDenied to refuse.
    guard: Optional[Callable[[str, str], None]] = None

    def emit(self, event_type: str, **payload: Any) -> None:
        if self.sink is None:
            return
        try:
            self.sink({"type": event_type, **payload})
        except Exception:  # pragma: no cover - a UI problem must not fail a tool
            pass

    def take_images(self) -> List[Dict[str, str]]:
        """Hand pending images to the next model call, clearing the queue."""
        images, self.pending_images = self.pending_images, []
        return images


_CURRENT: contextvars.ContextVar[Optional[ToolContext]] = contextvars.ContextVar(
    "nyx_tool_context", default=None
)


def current() -> Optional[ToolContext]:
    """The context of the turn this code is running in, or None."""
    return _CURRENT.get()


@contextmanager
def use_context(ctx: ToolContext) -> Iterator[ToolContext]:
    """Install ``ctx`` for the duration of a turn (or a delegated sub-task)."""
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


def emit(event_type: str, **payload: Any) -> None:
    """Publish an event on the current turn. No-op outside a turn."""
    ctx = current()
    if ctx is not None:
        ctx.emit(event_type, **payload)


def progress(text: str) -> None:
    """Report a progress line for the tool that is running now."""
    ctx = current()
    if ctx is not None:
        ctx.emit("tool.progress", call_id=ctx.call_id, text=str(text)[:300])


def is_cancelled() -> bool:
    ctx = current()
    return bool(ctx and ctx.cancelled.is_set())


def _thumbnail_data_url(data: bytes, mime: str) -> tuple[str, int, int]:
    """A small JPEG preview for the timeline, plus the source dimensions."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            preview = image.convert("RGB")
            preview.thumbnail((_THUMB_EDGE, _THUMB_EDGE))
            buffer = io.BytesIO()
            preview.save(buffer, format="JPEG", quality=70)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}", width, height
    except Exception:
        # No Pillow, or an image format it cannot open: the model can still see
        # it, the timeline just goes without a preview.
        if len(data) <= 200_000:
            return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}", 0, 0
        return "", 0, 0


def attach_image(data: bytes, mime: str, name: str = "", note: str = "") -> bool:
    """Let the model see an image on its next call in this turn.

    Returns False when there is no turn to attach to (CLI, tests) or the image
    is too large, so a tool can say so in its text result instead of claiming
    the model looked at something it never received.
    """
    ctx = current()
    if ctx is None or not data:
        return False
    if len(data) > MAX_MODEL_IMAGE_BYTES:
        ctx.emit("tool.progress", call_id=ctx.call_id,
                 text=f"Image {name or ''} is too large to show the model ({len(data) // 1024} KB).")
        return False

    ctx.pending_images.append({
        "mime": mime or "image/png",
        "data": base64.b64encode(data).decode("ascii"),
        "name": name,
        "note": note,
    })
    data_url, width, height = _thumbnail_data_url(data, mime)
    ctx.emit("tool.image", call_id=ctx.call_id, name=name, note=note,
             data_url=data_url, width=width, height=height)
    return True
