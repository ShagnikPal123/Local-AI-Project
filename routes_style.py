"""Settings › Appearance › Style from an image: ask a model that can see what the picture's style is."""

from __future__ import annotations

import base64
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()

MAX_BYTES = 6 * 1024 * 1024


class StyleImage(BaseModel):
    image: str  # base64, with or without a data: prefix
    mime: str = "image/png"


@router.post("/api/style/from-image")
def style_from_image(body: StyleImage, _user=RequireChat) -> Dict[str, Any]:
    import style_from_image as sfi
    import vision

    data = body.image.split(",", 1)[1] if body.image.startswith("data:") else body.image
    try:
        image = base64.b64decode(data, validate=False)
    except (ValueError, TypeError) as error:
        raise HTTPException(status_code=400, detail="That image could not be read.") from error
    if not image or len(image) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Use an image under 6 MB.")
    if not body.mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="That file is not an image.")
    try:
        look = sfi.read_style(image, body.mime)
    except vision.VisionUnavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"ok": True, "look": look}
