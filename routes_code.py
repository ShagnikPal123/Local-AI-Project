"""HTTP routes for the Code tab and the VS Code extension (Request G7).

Editing files on the host is an owner action: on a claimed install these need an
owner or admin session; unclaimed, the caller must be on this computer. Hosted
builds do not have these routes at all (deploy_mode.HOSTED_BLOCKED_PREFIXES).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class OpenRequest(BaseModel):
    path: str


class SaveRequest(BaseModel):
    path: str
    text: str
    base_hash: str = ""


class SearchRequest(BaseModel):
    root: str
    query: str


class ProposeRequest(BaseModel):
    path: str
    instruction: str
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    context_paths: List[str] = []


class ResolveRequest(BaseModel):
    status: str = "rejected"


class AskRequest(BaseModel):
    path: str
    question: str = ""
    start_line: Optional[int] = None
    end_line: Optional[int] = None


class PickRequest(BaseModel):
    multiple: bool = True
    open: bool = True
    start: str = ""


class NewPathRequest(BaseModel):
    path: str
    text: str = ""


class StartRequest(BaseModel):
    parent: str
    name: str
    template: str = "empty"


class BuildRequest(BaseModel):
    root: str
    instruction: str


def _code_errors(fn):
    """Turn CodeError/KeyError/ModelCallError into HTTP answers with the sentence intact."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        import code_workspace
        from model_hub import ModelCallError

        try:
            return fn(*args, **kwargs)
        except code_workspace.CodeError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except KeyError as error:
            raise HTTPException(status_code=404, detail="That change no longer exists.") from error
        except ModelCallError as error:
            raise HTTPException(status_code=502, detail=f"No code model could answer: {error}") from error
    return wrapper


def _owner_dep():
    """Resolved lazily so importing this module does not import server (and its app) first."""

    def dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
        from server import require_local_owner

        return require_local_owner(http_request, authorization)
    return Depends(dependency)


Owner = _owner_dep()


@router.get("/api/code/workspaces")
def list_workspaces(_owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"workspaces": code_workspace.workspaces()}


@router.post("/api/code/workspaces")
@_code_errors
def open_workspace(body: OpenRequest, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"workspace": code_workspace.open_workspace(body.path)}


@router.delete("/api/code/workspaces/{workspace_id}")
def close_workspace(workspace_id: str, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    code_workspace.close_workspace(workspace_id)
    return {"workspaces": code_workspace.workspaces()}


@router.get("/api/code/tree")
@_code_errors
def folder_tree(path: str, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"path": path, "entries": code_workspace.tree(path)}


@router.get("/api/code/file")
@_code_errors
def read_file(path: str, start: int = 1, end: Optional[int] = None, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return code_workspace.read(path, start, end)


@router.put("/api/code/file")
@_code_errors
def save_file(body: SaveRequest, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return code_workspace.save(body.path, body.text, body.base_hash)


@router.post("/api/code/search")
@_code_errors
def search_code(body: SearchRequest, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"hits": code_workspace.search(body.root, body.query)}


@router.post("/api/code/propose")
@_code_errors
def propose_edit(body: ProposeRequest, _owner=Owner) -> Dict[str, Any]:
    """The model's edit as a diff to review. Nothing is written until it is applied."""
    import code_workspace

    return {"proposal": code_workspace.propose(body.path, body.instruction, body.start_line, body.end_line, body.context_paths)}


@router.get("/api/code/proposals")
def list_proposals(path: str = "", _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"proposals": code_workspace.proposals(path)}


@router.get("/api/code/proposals/{proposal_id}")
@_code_errors
def read_proposal(proposal_id: str, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"proposal": code_workspace.get_proposal(proposal_id, include_text=True)}


@router.post("/api/code/proposals/{proposal_id}/apply")
@_code_errors
def apply_proposal(proposal_id: str, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"proposal": code_workspace.apply(proposal_id)}


@router.post("/api/code/proposals/{proposal_id}/resolve")
@_code_errors
def resolve_proposal(proposal_id: str, body: ResolveRequest, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"proposal": code_workspace.reject(proposal_id, body.status)}


@router.post("/api/code/proposals/{proposal_id}/undo")
@_code_errors
def undo_proposal(proposal_id: str, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"proposal": code_workspace.undo(proposal_id)}


@router.post("/api/code/ask")
@_code_errors
def ask_about_code(body: AskRequest, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return code_workspace.ask(body.path, body.question, body.start_line, body.end_line)


# --- Request H1: Windows' own folder picker; H12: new files, new folders, start from scratch ----------


@router.post("/api/code/pick-folders")
@_code_errors
def pick_folders(body: PickRequest, http_request: Request, _owner=Owner) -> Dict[str, Any]:
    """Open File Explorer's folder picker on this PC and open what the owner chooses.

    The dialog appears on the computer running Nyx, so a request from another device is
    refused rather than popping a window nobody in front of that device can see.
    """
    import code_workspace
    import native_dialogs

    host = (http_request.client.host if http_request.client else "") or ""
    if host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(status_code=409, detail="The folder picker opens on the PC running Nyx. Use it there, or type the folder's path.")
    try:
        paths = native_dialogs.pick_folders(
            title="Choose folders to open in Nyx" if body.multiple else "Choose where the new folder goes",
            start=body.start, multiple=body.multiple)
    except native_dialogs.DialogUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    opened, errors = [], []
    if body.open:
        for path in paths:
            try:
                opened.append(code_workspace.open_workspace(path))
            except code_workspace.CodeError as error:
                errors.append(f"{path}: {error}")
    return {"paths": paths, "cancelled": not paths, "opened": opened, "errors": errors,
            "workspaces": code_workspace.workspaces()}


@router.post("/api/code/new-file")
@_code_errors
def new_file(body: NewPathRequest, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"file": code_workspace.create_file(body.path, body.text)}


@router.post("/api/code/new-folder")
@_code_errors
def new_folder(body: NewPathRequest, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    return {"folder": code_workspace.create_folder(body.path)}


@router.get("/api/code/templates")
def list_templates(_owner=Owner) -> Dict[str, Any]:
    from pathlib import Path

    import code_workspace

    home = Path.home()
    suggestions = [str(p) for p in (home / "Documents", home / "Desktop", home / "source" / "repos", home) if p.is_dir()]
    return {"templates": code_workspace.templates(), "parents": suggestions}


@router.post("/api/code/start")
@_code_errors
def start_project(body: StartRequest, _owner=Owner) -> Dict[str, Any]:
    import code_workspace

    workspace = code_workspace.start_project(body.parent, body.name, body.template)
    return {"workspace": workspace, "workspaces": code_workspace.workspaces()}


@router.post("/api/code/propose-files")
@_code_errors
def propose_files(body: BuildRequest, _owner=Owner) -> Dict[str, Any]:
    """New files (an empty folder is fine) as a proposal to review. Nothing is written until applied."""
    import code_workspace

    return {"proposal": code_workspace.propose_files(body.root, body.instruction)}
