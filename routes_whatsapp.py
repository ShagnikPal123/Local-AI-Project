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
    notify_office: Optional[bool] = None


@router.post("/api/whatsapp/settings")
def whatsapp_settings(body: SettingsBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import whatsapp_link

    return _run(lambda: whatsapp_link.link().update(enabled=body.enabled, allow=body.allow,
                                                         notify_office=body.notify_office))


@router.post("/api/whatsapp/unlink")
def whatsapp_unlink(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import whatsapp_link

    return _run(lambda: whatsapp_link.link().unlink())


@router.get("/api/whatsapp/chats")
def whatsapp_chats(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    """The PC's chats with a ``whatsapp`` flag on the ones connected to the phone (the chat list shows it as a badge)."""
    import whatsapp_link

    current = whatsapp_link.link()
    linked = set(current.state.get("linked_chats") or [])
    return {"lane": current.current_lane(), "chats": [{**chat, "whatsapp": chat["id"] in linked}
                                                      for chat in current.chats.recent(200)]}


class LaneBody(BaseModel):
    kind: str = "general"
    id: str = ""


@router.post("/api/whatsapp/lane")
def whatsapp_lane(body: LaneBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Point the phone at the main chat, one PC chat, or one avatar (the same thing /chat and /avatar do from the phone)."""
    import whatsapp_link
    import whatsapp_lanes

    if body.kind not in whatsapp_lanes.LANE_KINDS:
        raise HTTPException(status_code=400, detail="kind is general, chat or avatar.")
    return _run(lambda: whatsapp_link.link().set_lane(body.kind, body.id))


class LinkChatBody(BaseModel):
    chat_id: str
    linked: bool = True


@router.post("/api/whatsapp/link-chat")
def whatsapp_link_chat(body: LinkChatBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Connect any PC chat to WhatsApp (or take it off): connected chats carry the badge and can be continued by /chat."""
    import whatsapp_link

    current = whatsapp_link.link()
    if body.linked:
        return _run(lambda: current.link_chat(body.chat_id, switch=False))
    return _run(lambda: current.unlink_chat(body.chat_id))


class SendFileBody(BaseModel):
    path: str
    caption: str = ""


@router.post("/api/whatsapp/send-file")
def whatsapp_send_file(body: SendFileBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Text one file or picture from this PC to the owner's phone. Protected files and risky ones are refused."""
    import whatsapp_link

    return _run(lambda: whatsapp_link.link().send_file(body.path, body.caption, origin="pc"))
