"""HTTP routes for the diagram overlay (Request R14).

Drawing a diagram is an ordinary chat action — it reads public image libraries and this install's own roster — so the
chat gate applies, the same as asking in the chat would.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server_auth import RequireChat

router = APIRouter()


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    import diagram_engine

    try:
        return fn(*args, **kwargs)
    except diagram_engine.DiagramError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


class MakeBody(BaseModel):
    request: str
    with_picture: bool = False


class ImageBody(BaseModel):
    query: str
    generate: bool = False


class UpdateBody(BaseModel):
    title: Optional[str] = None
    strokes: Optional[List[Dict[str, Any]]] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    groups: Optional[List[Dict[str, Any]]] = None
    kind: Optional[str] = None
    caption: Optional[str] = None
    image: Optional[Dict[str, Any]] = Field(default=None)


@router.get("/api/diagram")
def diagram_list(_user=RequireChat) -> Dict[str, Any]:
    import diagram_engine

    return {"recent": diagram_engine.recent(), "kinds": list(diagram_engine.KINDS)}


@router.post("/api/diagram")
def diagram_make(body: MakeBody, _user=RequireChat) -> Dict[str, Any]:
    import diagram_engine

    spec = _call(diagram_engine.make, body.request)
    if body.with_picture or diagram_engine.wants_picture(body.request):
        images = diagram_engine.find_image(body.request, limit=4)
        if images:
            spec["image"], spec["image_choices"] = images[0], images
    diagram_engine.save(spec)
    return {"diagram": spec}


@router.post("/api/diagram/image")
def diagram_image(body: ImageBody, _user=RequireChat) -> Dict[str, Any]:
    import diagram_engine

    if body.generate:
        from image_gen import generate_image

        result = generate_image(body.query)
        if not result.ok:
            raise HTTPException(status_code=409, detail=result.error)
        return {"images": [{"url": result.url, "thumb": result.url, "title": body.query[:90], "source": "",
                            "licence": "", "by": result.label, "where": "Nyx drew it"}]}
    return {"images": diagram_engine.find_image(body.query, limit=8)}


@router.get("/api/diagram/{diagram_id}")
def diagram_get(diagram_id: str, _user=RequireChat) -> Dict[str, Any]:
    import diagram_engine

    return {"diagram": _call(diagram_engine.load, diagram_id)}


@router.put("/api/diagram/{diagram_id}")
def diagram_update(diagram_id: str, body: UpdateBody, _user=RequireChat) -> Dict[str, Any]:
    import diagram_engine

    changes = {k: v for k, v in body.model_dump().items() if v is not None}
    return {"diagram": _call(diagram_engine.update, diagram_id, changes)}
