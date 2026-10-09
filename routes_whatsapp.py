"""HTTP routes for the WhatsApp line (Connectors → WhatsApp). All the owner's: the line reaches their phone.

Nothing here is public — WhatsApp is reached by the helper process going out, not by anything coming in, so there is
no webhook to open to the internet.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _run(action):
    import whatsapp_link

    try:
        return action()
    except whatsapp_link.WhatsAppError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/api/whatsapp")
def whatsapp_status(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import whatsapp_link

    return whatsapp_link.link().status()


@router.post("/api/whatsapp/setup")
def whatsapp_setup(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import whatsapp_link

    return _run(whatsapp_link.install)


class PairBody(BaseModel):
    phone: str = ""
    mode: str = "self"
    nyx_number: str = ""


@router.post("/api/whatsapp/pair")
def whatsapp_pair(body: PairBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import whatsapp_link

    return _run(lambda: whatsapp_link.link().begin_pairing(body.phone, body.mode, body.nyx_number))


class SendBody(BaseModel):
    text: str = ""


@router.post("/api/whatsapp/send")
def whatsapp_send(body: SendBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import whatsapp_link

    return _run(lambda: whatsapp_link.link().send(body.text, origin="pc"))


class SettingsBody(BaseModel):
    enabled: Optional[bool] = None
    allow: Optional[str] = None


@router.post("/api/whatsapp/settings")
def whatsapp_settings(body: SettingsBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import whatsapp_link

    return _run(lambda: whatsapp_link.link().update(enabled=body.enabled, allow=body.allow))


@router.post("/api/whatsapp/unlink")
def whatsapp_unlink(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import whatsapp_link

    return _run(lambda: whatsapp_link.link().unlink())
