"""HTTP routes for the Connectors tab (Plan Null N10, Update 1 U9/U24).

The catalogue and its connections live in ``connectors/catalog.py``; "add anything" drafts in ``connector_builder``;
calls in ``connector_use``; Microsoft sign-in in ``connectors/microsoft_graph``; Google sign-in keeps its own routes
in ``routes_email`` (the Connectors sheet calls them with the app it is connecting).

Reads use the chat gate and never carry a secret (saved keys show as their last four characters). Anything that
stores a credential, uses one, or asks a model to draft a connector needs the owner — the same rule as ``/api/keys``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _for(user: Any, shown: Dict[str, Any]) -> Dict[str, Any]:
    """An invited tester sees which apps exist and whether they work, not the owner's addresses or key endings."""
    if user is None:
        return shown  # unclaimed install: whoever sits at this PC is the owner
    from auth import Permission, has_permission

    if has_permission(user.role, Permission.VIEW_ADMIN):
        return shown
    return {**shown, "accounts": [], "mail_accounts": [], "saved": {}}


def _entry_or_404(connector_id: str) -> Dict[str, Any]:
    from connectors import catalog

    entry = catalog.get(connector_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"There is no connector called {connector_id!r}.")
    return entry


@router.get("/api/connectors/catalog")
def connectors_catalog(_user=RequireChat) -> Dict[str, Any]:
    """Every connector with its connection state, the categories in grid order, and the chat settings."""
    import connector_use
    from connectors import catalog

    listed = [_for(_user, catalog.public(e)) for e in catalog.list_catalog(include_custom=True)]
    used = {c["category"] for c in listed} | {"custom"}
    groups = [c for c in catalog.categories() if c["id"] in used]
    return {"categories": groups, "connectors": listed, "settings": connector_use.settings(),
            "connected": sum(1 for c in listed if c.get("connected")), "total": len(listed)}


@router.get("/api/connectors/catalog/{connector_id}")
def connector_detail(connector_id: str, _user=RequireChat) -> Dict[str, Any]:
    """One connector with its full action list (an MCP server's tools are fetched only when it is connected)."""
    import connector_use
    from connectors import catalog

    entry = _entry_or_404(connector_id)
    shown = _for(_user, catalog.public(entry, detail=True))
    if entry.get("kind") in ("mcp", "website") and shown.get("connected"):
        shown["actions"] = connector_use.actions_for(str(entry["id"]))
    return {"connector": shown}


@router.get("/api/connectors/mine")
def my_connectors(_user=RequireChat) -> Dict[str, Any]:
    from connectors import catalog

    return {"connectors": [_for(_user, catalog.public(e)) for e in catalog.list_catalog() if catalog.is_connected(e["id"])]}


class ConnectIn(BaseModel):
    fields: Dict[str, Any] = {}


@router.post("/api/connectors/{connector_id}/connect")
def connect_connector(connector_id: str, body: ConnectIn, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    from connectors import catalog

    entry = _entry_or_404(connector_id)
    try:
        catalog.connect(str(entry["id"]), body.fields)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"connector": catalog.public(catalog.get(str(entry["id"])) or entry)}


@router.post("/api/connectors/{connector_id}/test")
def test_connector(connector_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """One read-only call that proves the connection works. Writes nothing in the other app."""
    import connector_builder

    entry = _entry_or_404(connector_id)
    try:
        return connector_builder.test(str(entry["id"]))
    except connector_builder.BuilderError as error:
        return {"ok": False, "message": str(error)}


@router.delete("/api/connectors/{connector_id}")
def disconnect_connector(connector_id: str, account: str = "", _owner_user=Depends(_owner)) -> Dict[str, Any]:
    from connectors import catalog

    entry = _entry_or_404(connector_id)
    removed = catalog.disconnect(str(entry["id"]), account=account)
    shown = catalog.get(str(entry["id"]))
    return {"removed": removed, "connector": catalog.public(shown) if shown else None}


class FindIn(BaseModel):
    text: str


@router.post("/api/connectors/find")
def find_connector(body: FindIn, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """"Add any site or connector": words or an address in, a draft out (catalogue, known MCP server, or a new one).

    Keys pasted into the words are held server-side with the draft and shown back only masked.
    """
    import connector_builder

    try:
        return {"draft": connector_builder.draft(body.text)}
    except connector_builder.BuilderError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class AddIn(BaseModel):
    draft_id: str = ""
    fields: Dict[str, Any] = {}


@router.post("/api/connectors/add")
def add_connector(body: AddIn, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import connector_builder
    from connectors import catalog

    try:
        result = connector_builder.add(body.draft_id, fields=body.fields)
    except connector_builder.BuilderError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    entry = catalog.get(str(result.get("id", "")))
    return {**result, "connector": catalog.public(entry) if entry else None}


class UseSettingsIn(BaseModel):
    auto: bool | None = None
    confirm_writes: bool | None = None
    max_per_turn: int | None = None


@router.put("/api/connectors/settings")
def put_connector_settings(body: UseSettingsIn, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import connector_use

    return {"settings": connector_use.save_settings(auto=body.auto, confirm_writes=body.confirm_writes,
                                                     max_per_turn=body.max_per_turn)}


# --- Microsoft 365 sign-in (device code) ------------------------------------------------------------------------


class MicrosoftClientIn(BaseModel):
    client_id: str
    tenant: str = "common"


class MicrosoftStartIn(BaseModel):
    products: List[str] = []


def _microsoft_error(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(error))


@router.get("/api/connectors/microsoft/status")
def microsoft_status(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Where the sign-in stands; while one is waiting, this also asks Microsoft once whether it finished."""
    from connectors import microsoft_graph

    result = microsoft_graph.poll() if microsoft_graph.pending() else {"state": "idle"}
    if result.get("state") == "connected":
        try:
            from agent_events import publish_ui

            publish_ui("connectors.changed", id="microsoft")
        except Exception:  # pragma: no cover
            pass
    return {**microsoft_graph.status(), "last": result}


@router.post("/api/connectors/microsoft/client")
def microsoft_client(body: MicrosoftClientIn, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    from connectors import microsoft_graph

    try:
        microsoft_graph.save_client(body.client_id, body.tenant)
    except microsoft_graph.MicrosoftError as error:
        raise _microsoft_error(error) from error
    return microsoft_graph.status()


@router.post("/api/connectors/microsoft/start")
def microsoft_start(body: MicrosoftStartIn, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    from connectors import microsoft_graph

    unknown = [p for p in body.products if p not in microsoft_graph.PRODUCT_SCOPES]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown Microsoft app: {', '.join(unknown)}.")
    try:
        return {"pending": microsoft_graph.start(body.products)}
    except microsoft_graph.MicrosoftError as error:
        raise _microsoft_error(error) from error
    except Exception as error:  # noqa: BLE001 - Microsoft unreachable is an answer
        raise HTTPException(status_code=502, detail=f"Microsoft could not be reached: {type(error).__name__}") from error
