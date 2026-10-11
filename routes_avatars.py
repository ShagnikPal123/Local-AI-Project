"""HTTP routes for Avatars (avatars.py). All the owner's: an avatar can be given their computer, files and mail."""

from __future__ import annotations

import threading
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _call(action):
    import avatars

    try:
        return action()
    except avatars.AvatarError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class CreateBody(BaseModel):
    avatar: Dict[str, Any] = {}
    template: str = ""


class TalkBody(BaseModel):
    text: str


class RunBody(BaseModel):
    kind: str = "checkin"
    item: str = ""


class ItemBody(BaseModel):
    item: Dict[str, Any]


class TeamBody(BaseModel):
    avatars: List[str]
    task: str


@router.get("/api/avatars")
def avatars_list(_o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    return {"avatars": avatars.list_avatars(),
            "catalog": {"functions": {k: {"label": v["label"], "about": v["about"], "default": v["default"],
                                          "locked": bool(v.get("locked")), "always_ask": bool(v.get("always_ask"))}
                                      for k, v in avatars.FUNCTIONS.items()},
                        "main": avatars.MAIN_FUNCTIONS, "schedules": avatars.SCHEDULES, "models": avatars.MODELS,
                        "repeats": list(avatars.REPEATS)}}


@router.post("/api/avatars")
def avatars_create(body: CreateBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    return _call(lambda: avatars.create(body.avatar, template=body.template))


@router.post("/api/avatars/restore")
def avatars_restore(_o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    return {"avatars": avatars.restore_defaults()}


@router.post("/api/avatars/team")
def avatars_team(body: TeamBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    return _call(lambda: avatars.team(body.avatars, body.task[:2000]))


@router.get("/api/avatars/{avatar_id}")
def avatars_get(avatar_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    found = avatars.get(avatar_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such avatar.")
    return found


@router.put("/api/avatars/{avatar_id}")
def avatars_update(avatar_id: str, changes: Dict[str, Any], _o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    return _call(lambda: avatars.update(avatar_id, changes))


@router.delete("/api/avatars/{avatar_id}")
def avatars_delete(avatar_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    return {"deleted": avatars.delete(avatar_id)}


@router.post("/api/avatars/{avatar_id}/reset")
def avatars_reset(avatar_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    return _call(lambda: avatars.reset(avatar_id))


@router.post("/api/avatars/{avatar_id}/talk")
def avatars_talk(avatar_id: str, body: TalkBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    text = body.text.strip()[:4000]
    if not text:
        raise HTTPException(status_code=400, detail="Say something first.")
    return _call(lambda: avatars.run(avatar_id, text, kind="talk", wait=5))


@router.post("/api/avatars/{avatar_id}/run")
def avatars_run(avatar_id: str, body: RunBody, _o=Depends(_owner)) -> Dict[str, Any]:
    """Run a check-in, a watch or a lesson now, in the background; the card updates when it is done."""
    import avatars

    avatar = avatars.get(avatar_id)
    if avatar is None:
        raise HTTPException(status_code=404, detail="No such avatar.")
    if avatar_id in avatars._busy:
        raise HTTPException(status_code=409, detail=f"{avatar['name']} is busy.")
    if body.kind == "watch":
        job = lambda: avatars.run_watch(avatar_id, body.item, wait=0)  # noqa: E731
    elif body.kind == "lesson":
        job = lambda: avatars.run_lesson(avatar_id, body.item, wait=0)  # noqa: E731
    else:
        job = lambda: avatars.run(avatar_id, avatars.check_in_text(avatar), kind="check-in", wait=0)  # noqa: E731

    def background() -> None:
        try:
            job()
        except Exception:  # noqa: BLE001 - logged into the avatar's activity by run()
            pass

    threading.Thread(target=background, name=f"nyx-avatar-{avatar_id}", daemon=True).start()
    return {"started": True}


@router.post("/api/avatars/{avatar_id}/{kind}")
def avatars_add_item(avatar_id: str, kind: str, body: ItemBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    if kind not in ("goals", "watches", "lessons"):
        raise HTTPException(status_code=404, detail="Unknown list.")
    return _call(lambda: avatars.add_item(avatar_id, kind, body.item))


@router.delete("/api/avatars/{avatar_id}/{kind}/{item_id}")
def avatars_remove_item(avatar_id: str, kind: str, item_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import avatars

    if kind not in ("goals", "watches", "lessons"):
        raise HTTPException(status_code=404, detail="Unknown list.")
    return _call(lambda: avatars.remove_item(avatar_id, kind, item_id))
