"""HTTP routes for the Create tab's drawing studio (sketch_studio.py, UPDATE_IDEAS U2). The owner's: they spend
model calls and keep the owner's drawings."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _run(action):
    import sketch_studio
    from model_hub import ModelCallError

    try:
        return action()
    except sketch_studio.SketchError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ModelCallError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


class DrawBody(BaseModel):
    request: str = ""
    existing: str = ""


class ScanBody(BaseModel):
    image: str = ""
    request: str = ""


class RenderBody(BaseModel):
    request: str = ""
    sees: str = ""


class SaveBody(BaseModel):
    image: str = ""
    name: str = ""


@router.post("/api/sketch/draw")
def sketch_draw(body: DrawBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import sketch_studio

    return _run(lambda: sketch_studio.draw(body.request, existing=body.existing))


@router.post("/api/sketch/scan")
def sketch_scan(body: ScanBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import sketch_studio

    return _run(lambda: sketch_studio.scan(body.image, body.request))


@router.post("/api/sketch/render")
def sketch_render(body: RenderBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import sketch_studio

    return _run(lambda: sketch_studio.render(body.request, body.sees))


@router.get("/api/sketch/saved")
def sketch_list(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import sketch_studio

    return {"sketches": sketch_studio.sketches()}


@router.post("/api/sketch/saved")
def sketch_save(body: SaveBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import sketch_studio

    return _run(lambda: sketch_studio.save(body.image, body.name))


@router.get("/api/sketch/saved/{sketch_id}")
def sketch_load(sketch_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import sketch_studio

    return {"image": _run(lambda: sketch_studio.load(sketch_id))}
