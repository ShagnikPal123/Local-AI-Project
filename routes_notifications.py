"""HTTP routes for notifications (Settings → Notifications): where the box appears, which notices, and the phone."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _view() -> Dict[str, Any]:
    import notifications

    phone_linked = False
    try:
        import whatsapp_link

        phone_linked = whatsapp_link.link().state.get("status") == "linked"
    except Exception:  # noqa: BLE001
        pass
    return {"settings": notifications.settings(), "away_now": notifications.is_away(), "phone_linked": phone_linked,
            "positions": list(notifications.POSITIONS), "kinds": list(notifications.KINDS)}


@router.get("/api/notifications")
def get_notifications(_user=RequireChat) -> Dict[str, Any]:
    """Every window reads this for the corner the boxes appear in; the rest is for the settings section."""
    import notifications

    return {**_view(), "recent": notifications.recent()}


class SettingsBody(BaseModel):
    position: Optional[str] = None
    phone: Optional[str] = None
    away: Optional[str] = None
    away_minutes: Optional[int] = None
    min_seconds: Optional[int] = None
    kinds: Optional[Dict[str, bool]] = None
    channels: Optional[Dict[str, bool]] = None


@router.post("/api/notifications/settings")
def set_notifications(body: SettingsBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import notifications

    try:
        notifications.update(body.model_dump(exclude_none=True))
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return _view()


class TestBody(BaseModel):
    kind: str = "done"
    phone: bool = False


@router.post("/api/notifications/test")
def test_notification(body: TestBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Send a sample notice so the owner sees the corner and the phone text before relying on them."""
    import time

    import notifications

    if body.kind not in notifications.KINDS:
        raise HTTPException(status_code=400, detail="kind is done, help, message or schedule.")
    sample = {"done": "A chat finished. This is a test.", "help": "A chat needs you. This is a test.",
              "message": "A chat wrote to you. This is a test.", "schedule": "A scheduled task ran. This is a test."}
    stamp = time.strftime("%H:%M:%S")
    return notifications.notify(body.kind, f"{sample[body.kind]} ({stamp})", title="Nyx", source="test",
                                urgent=body.phone)
