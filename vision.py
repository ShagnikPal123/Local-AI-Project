"""Letting the assistant see: find a thing on screen, or understand a picture.

Computer control needs one capability above all: "where is the Send button?"
Pixel coordinates are what a click needs, and a model that can see the screen
can supply them. Gemini returns points normalised to 0–1000, which survives any
screenshot downscaling — the caller maps back to real screen pixels.

Measured 2026-09-12 on gemini-flash-lite-latest with a synthetic 1280×720 UI:
asked for "the Send button" it answered [850, 804] against a true centre of
[854, 797] — well inside the button — in 1.8 s.

Only providers that can actually see are used. When none is configured the
error says so, rather than letting a text-only model guess coordinates.
"""

from __future__ import annotations

import base64
import json
import re
from typing import List, Optional, Tuple


class VisionUnavailable(RuntimeError):
    """No configured provider can look at images."""


_POINT_PROMPT = (
    "Look at this screenshot and find: {target}\n\n"
    "Reply with JSON only, no prose. If you can see it: "
    '{{"found": true, "point": [y, x], "label": "what you found"}} '
    "where y and x are the centre of it, as integers normalised to 0-1000 "
    "(0,0 is the top-left corner, 1000,1000 the bottom-right). "
    'If it is not visible: {{"found": false, "reason": "why"}}.'
)


def _vision_provider():
    from providers.gemini_provider import GeminiProvider

    provider = GeminiProvider()
    if provider.is_available():
        return provider
    raise VisionUnavailable(
        "Seeing images needs a vision-capable model. Add a free Gemini key in the Models tab."
    )


def _ask(image: bytes, mime: str, prompt: str, role: str = "image_check") -> str:
    """Ask the model assigned to ``role`` about one image, announcing which model it was.

    Goes straight to Gemini only when the role system itself cannot be imported,
    so screen control keeps working even then.
    """
    try:
        from model_hub import ModelCallError
        from model_roles import MODEL_ROLES
    except ImportError:
        MODEL_ROLES = None  # noqa: N806
    if MODEL_ROLES is not None:
        try:
            return MODEL_ROLES.run(role, prompt, images=[(image, mime or "image/png")], max_tokens=800).text
        except ModelCallError as error:
            raise VisionUnavailable(str(error)) from error
    provider = _vision_provider()
    message = {
        "role": "user",
        "content": prompt,
        "images": [{"mime": mime or "image/png", "data": base64.b64encode(image).decode("ascii")}],
    }
    return provider.chat([message])


def _json_from(text: str) -> dict:
    fence = re.search(r"```(?:json)?\s*(.+?)```", text or "", re.DOTALL)
    body = fence.group(1) if fence else text or ""
    start, end = body.find("{"), body.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in the reply")
    return json.loads(body[start:end + 1])


def locate_point(image: bytes, mime: str, description: str) -> Optional[Tuple[float, float]]:
    """Centre of ``description`` as normalised (x, y) in 0..1, or None if not visible."""
    reply = _ask(image, mime, _POINT_PROMPT.format(target=description.strip()[:300]), role="ui_pointing")
    try:
        data = _json_from(reply)
    except (ValueError, json.JSONDecodeError):
        return None
    if not data.get("found", True):
        return None
    point = data.get("point")
    if not (isinstance(point, (list, tuple)) and len(point) == 2):
        return None
    try:
        y, x = float(point[0]), float(point[1])
    except (TypeError, ValueError):
        return None
    if not (0 <= x <= 1000 and 0 <= y <= 1000):
        return None
    return x / 1000.0, y / 1000.0


def describe_image(image: bytes, mime: str, question: str = "") -> str:
    """What is in the image, or the answer to ``question`` about it."""
    prompt = question.strip() or (
        "Describe this image precisely: what it shows, any readable text, and anything notable."
    )
    return _ask(image, mime, prompt)


def batch_describe(images: List[Tuple[bytes, str]], question: str) -> str:
    """One answer about several images at once (e.g. before/after screenshots)."""
    provider = _vision_provider()
    message = {
        "role": "user",
        "content": question,
        "images": [{"mime": mime, "data": base64.b64encode(data).decode("ascii")} for data, mime in images],
    }
    return provider.chat([message])
