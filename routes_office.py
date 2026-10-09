"""HTTP routes for the Office Space tab (Project Null N8).

Owner-only, every one of them: an office runs models on the owner's keys, writes files on their disk and can
pause the rest of Nyx, so an invited tester has no business here. Hosted builds do not have these routes at all
(``deploy_mode.HOSTED_BLOCKED_PREFIXES``).

The heavy work lives in ``office/``; this file is only the edge — it validates what came in, calls one engine
method, and answers with the same snapshot shape the tab already knows how to render.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner_dep():
    def dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
        from server import require_local_owner

        return require_local_owner(http_request, authorization)
    return Depends(dependency)


Owner = _owner_dep()


def _engine() -> Any:
    from office.engine import ENGINE

    return ENGINE


def _fail(error: Exception) -> HTTPException:
    from office.engine import OfficeError
    from office.library import LibraryError

    if isinstance(error, (OfficeError, LibraryError, ValueError)):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail=f"{type(error).__name__}: {error}")


# --- the library ------------------------------------------------------------------


class NameBody(BaseModel):
    name: str = ""
    parent: str = ""


class ItemChanges(BaseModel):
    name: Optional[str] = None
    parent: Optional[str] = None
    linked: Optional[bool] = None


@router.get("/api/office")
def office_overview(_owner=Owner) -> Dict[str, Any]:
    engine = _engine()
    engine.watchdog()
    return engine.overview()


@router.get("/api/office/library")
def office_library(_owner=Owner) -> Dict[str, Any]:
    from office import library

    return library.tree()


@router.post("/api/office/folders")
def office_new_folder(body: NameBody, _owner=Owner) -> Dict[str, Any]:
    from office import library

    try:
        return {"folder": library.create_folder(body.name, body.parent)}
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.post("/api/office/offices")
def office_new(body: NameBody, _owner=Owner) -> Dict[str, Any]:
    """*"For the first project it creates a file and opens the chat instantly."*"""
    from office import library

    try:
        office, _directory = library.create_office(body.name, body.parent)
        snapshot = _engine().snapshot(office.id)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error
    return snapshot


@router.patch("/api/office/items/{item_id}")
def office_change_item(item_id: str, body: ItemChanges, _owner=Owner) -> Dict[str, Any]:
    """Rename, drag into another folder, or turn on "link work flows" for a folder."""
    from office import library

    engine = _engine()
    try:
        item = library.find(item_id)
        if item is None:
            raise library.LibraryError("That item is gone.")
        if item.kind == "office" and engine.is_running(item_id) and (body.name or body.parent is not None):
            raise library.LibraryError("That office is working right now. Halt it before moving or renaming it.")
        result: Dict[str, Any] = {}
        if body.name:
            result = library.rename(item_id, body.name)
        if body.parent is not None:
            result = library.move(item_id, body.parent)
        if body.linked is not None:
            result = library.set_linked(item_id, body.linked)
        if item.kind == "office":
            engine.close(item_id)
        return {"item": result or (library.find(item_id).as_dict() if library.find(item_id) else {})}
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.delete("/api/office/items/{item_id}")
def office_delete_item(item_id: str, _owner=Owner) -> Dict[str, Any]:
    from office import library

    engine = _engine()
    if engine.is_running(item_id):
        raise HTTPException(status_code=409, detail="That office is working right now. Halt it first.")
    try:
        engine.close(item_id)
        return library.delete(item_id)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.post("/api/office/items/{item_id}/reveal")
def office_reveal(item_id: str, _owner=Owner) -> Dict[str, Any]:
    """Open this office or folder in File Explorer, on this computer."""
    from office import library

    item = library.find(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="That item is gone.")
    try:
        return {"opened": library.reveal(item.path)}
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


# --- one office -------------------------------------------------------------------


class SayBody(BaseModel):
    text: str = ""


class TargetBody(BaseModel):
    text: str = ""
    sections: List[str] = []
    agents: List[str] = []
    roles: List[str] = []
    focus_section: str = ""


class ControlBody(BaseModel):
    action: str = ""
    scope: str = "office"
    id: str = ""


@router.get("/api/office/offices/{office_id}")
def office_snapshot(office_id: str, _owner=Owner) -> Dict[str, Any]:
    try:
        return _engine().snapshot(office_id)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.post("/api/office/offices/{office_id}/chat")
def office_chat(office_id: str, body: SayBody, _owner=Owner) -> Dict[str, Any]:
    """The big text box: the owner talking to the top manager."""
    engine = _engine()
    try:
        result = engine.say(office_id, body.text)
        return {**result, "snapshot": engine.snapshot(office_id)}
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.post("/api/office/offices/{office_id}/say")
def office_say(office_id: str, body: TargetBody, _owner=Owner) -> Dict[str, Any]:
    """The second chat box: a message for the sections, kinds of agent or agents that were picked or named."""
    engine = _engine()
    selection = {"sections": body.sections, "agents": body.agents, "roles": body.roles}
    try:
        return engine.target(office_id, body.text, selection=selection, focus_section=body.focus_section)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.post("/api/office/offices/{office_id}/resolve")
def office_resolve(office_id: str, body: TargetBody, _owner=Owner) -> Dict[str, Any]:
    """Who would get this — answered on every keystroke, so it never calls a model."""
    selection = {"sections": body.sections, "agents": body.agents, "roles": body.roles}
    try:
        return _engine().resolve(office_id, body.text, selection=selection, focus_section=body.focus_section)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.post("/api/office/offices/{office_id}/control")
def office_control(office_id: str, body: ControlBody, _owner=Owner) -> Dict[str, Any]:
    try:
        return _engine().control(office_id, body.action, scope=body.scope or "office", target_id=body.id)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.post("/api/office/offices/{office_id}/deliver")
def office_deliver(office_id: str, _owner=Owner) -> Dict[str, Any]:
    """Deliver now (Update 1, U41): the office puts what it has in the Output box, even mid-job."""
    try:
        return _engine().deliver_now(office_id)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


class OptionsBody(BaseModel):
    #: Decide everything and produce the real result instead of plans and questions (U42).
    auto_decisions: Optional[bool] = None


@router.post("/api/office/offices/{office_id}/options")
def office_options(office_id: str, body: OptionsBody, _owner=Owner) -> Dict[str, Any]:
    try:
        return _engine().set_options(office_id, auto_decisions=body.auto_decisions)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error


@router.get("/api/office/offices/{office_id}/files")
def office_files(office_id: str, _owner=Owner) -> Dict[str, Any]:
    from office import library

    try:
        work = library.work_dir(office_id)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error
    rows: List[Dict[str, Any]] = []
    for item in sorted(work.rglob("*"))[:500]:
        if item.is_file():
            try:
                stat = item.stat()
            except OSError:
                continue
            rows.append({"path": item.relative_to(work).as_posix(), "size": stat.st_size, "at": stat.st_mtime})
    return {"files": rows, "folder": str(work)}


@router.get("/api/office/offices/{office_id}/file")
def office_file(office_id: str, path: str = "", _owner=Owner) -> Dict[str, Any]:
    from office import library, officetools

    try:
        work = library.work_dir(office_id)
    except Exception as error:  # noqa: BLE001
        raise _fail(error) from error
    target = work / officetools.safe_relative(path)
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="No such file in this office.")
    try:
        text = target.read_text(encoding="utf-8", errors="replace")[:400_000]
    except OSError as error:
        raise HTTPException(status_code=409, detail=f"Could not read that file: {error}") from error
    return {"path": officetools.safe_relative(path), "text": text, "size": target.stat().st_size}


@router.get("/api/office/offices/{office_id}/memory")
def office_memory(office_id: str, _owner=Owner) -> Dict[str, Any]:
    from office import memory

    data = memory.load(office_id)
    return {"entries": data["entries"][-200:], "profile": data["profile"]}


@router.delete("/api/office/offices/{office_id}/memory/{entry_id}")
def office_forget(office_id: str, entry_id: str, _owner=Owner) -> Dict[str, Any]:
    from office import memory

    if not memory.forget(office_id, entry_id):
        raise HTTPException(status_code=404, detail="That memory is already gone.")
    return {"entries": memory.load(office_id)["entries"][-200:]}


# --- focus mode and settings ------------------------------------------------------


class FocusBody(BaseModel):
    action: str = "enter"          # enter | leave
    office_id: str = ""
    remember: str = ""             # "always" | "never" — the "don't ask me again" answer


class SettingsBody(BaseModel):
    changes: Dict[str, Any] = {}


@router.get("/api/office/focus")
def office_focus_status(_owner=Owner) -> Dict[str, Any]:
    from office import focus

    return focus.status()


@router.post("/api/office/focus")
def office_focus(body: FocusBody, _owner=Owner) -> Dict[str, Any]:
    """*"It started by asking if they can shut everything down and only run this tab."*"""
    from office import focus, settings as settings_module

    if body.remember in ("always", "never", "ask"):
        settings_module.save({"focus_mode": body.remember})
    if (body.action or "enter") == "leave":
        return focus.leave()
    return focus.enter(body.office_id or _engine().running_office(), reason="Office Space")


@router.get("/api/office/settings")
def office_settings(_owner=Owner) -> Dict[str, Any]:
    from office import settings as settings_module

    return {"settings": settings_module.load()}


@router.put("/api/office/settings")
def office_save_settings(body: SettingsBody, _owner=Owner) -> Dict[str, Any]:
    from office import settings as settings_module

    return {"settings": settings_module.save(body.changes or {})}
