"""The Jarvis page's data (from the Jarvis projects the owner pointed at, 2026-10-09): what needs the owner right now,
and every Claude Code session on this PC. All the owner's, all read-only, absent from hosted builds."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


@router.get("/api/jarvis/sessions")
def jarvis_sessions(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import claude_sessions

    return {"sessions": claude_sessions.sessions()}


def needs_you() -> List[Dict[str, Any]]:
    """Everything waiting on the owner, from every part of Nyx that can wait, plus Claude Code. Never raises."""
    items: List[Dict[str, Any]] = []
    try:
        import permissions

        for p in permissions.pending_approvals():
            items.append({"kind": "approval", "id": p["id"], "title": p["summary"], "detail": p.get("detail", ""),
                          "where": "chat", "since": p.get("created", 0)})
    except Exception:  # noqa: BLE001
        pass
    try:
        from trading import guard

        for a in guard.pending_approvals():
            order = a.get("order", {})
            items.append({"kind": "trade", "id": a.get("id", ""), "where": "trading", "since": a.get("created_at", 0),
                          "title": f"{order.get('side', '').title()} {order.get('symbol', '')} — waiting for your approval",
                          "detail": order.get("reason", "")})
    except Exception:  # noqa: BLE001
        pass
    try:
        import claude_sessions

        for s in claude_sessions.sessions():
            if s["state"] == "needs_you":
                items.append({"kind": "claude", "id": s["id"], "where": "claude", "since": s["last"],
                              "title": f"Claude Code · {s['project']}: {s['title']}", "detail": s["why"]})
    except Exception:  # noqa: BLE001
        pass
    return sorted(items, key=lambda i: -float(i.get("since") or 0))


@router.get("/api/jarvis/needs-you")
def jarvis_needs_you(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    return {"items": needs_you()}
