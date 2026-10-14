"""Owner routes for the phone connection (Settings → Phone): switch it on, show a one-minute key, remove a phone.

These live on Nyx's own API and need the owner. The phone itself never talks to this API; it talks to the separate
gateway in ``phone_gateway`` once it holds a token from pairing.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _view() -> Dict[str, Any]:
    import phone_gateway
    import phone_pairing

    book = phone_pairing.book()
    return {**phone_gateway.gateway().status(), "key_seconds_left": book.key_seconds_left(), "devices": book.devices()}


@router.get("/api/phone")
def get_phone(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    return _view()


class GatewayBody(BaseModel):
    enabled: bool
    port: Optional[int] = None


@router.post("/api/phone/gateway")
def set_gateway(body: GatewayBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Turn the phone server on or off. Off is the default, and turning it off also forgets any key being shown."""
    import phone_gateway
    import phone_pairing

    if body.port is not None and not 1024 <= body.port <= 65535:
        raise HTTPException(status_code=400, detail="Pick a port between 1024 and 65535.")
    if body.enabled:
        phone_gateway.gateway().start(body.port)
    else:
        phone_gateway.gateway().stop()
        phone_pairing.book().cancel_key()
    return _view()


@router.post("/api/phone/key")
def make_key(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    """A new key, good for 60 seconds and one phone. It is shown here once and held nowhere else."""
    import phone_gateway
    import phone_pairing

    if not phone_gateway.gateway().running:
        raise HTTPException(status_code=409, detail="Turn on 'Allow my phone' first; the key is for the phone server.")
    return {**phone_pairing.book().mint(), **_view()}


@router.delete("/api/phone/devices/{device_id}")
def remove_device(device_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import phone_pairing

    if not phone_pairing.book().revoke(device_id):
        raise HTTPException(status_code=404, detail="That phone is not connected.")
    return _view()
