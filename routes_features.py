"""HTTP routes for the feature catalog (Project Null N100).

What Nyx can do, what is running in the background right now, and how much each
part is used. Reading it is open to any signed-in chat caller — it is a list of
capabilities, not data — while rescanning is the owner's.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Request
from server_auth import RequireChat

router = APIRouter()


@router.get("/api/features")
def features(area: str = "", _user=RequireChat) -> Dict[str, Any]:
    import feature_catalog

    catalog = feature_catalog.scan()
    return {
        "counts": catalog["counts"],
        "scanned_at": catalog["scanned_at"],
        "new_modules": catalog.get("new_modules", []),
        "tools": catalog["tools"] if area in ("", "tools") else [],
        "tabs": catalog["tabs"] if area in ("", "tabs") else [],
        "roles": catalog["roles"] if area in ("", "roles") else [],
        "modules": catalog["modules"] if area == "modules" else [],
        "routes": catalog["routes"] if area == "routes" else [],
        "running": feature_catalog.live_processes(),
        "summary": feature_catalog.summary(area),
    }


@router.get("/api/features/processes")
def processes(_user=RequireChat) -> Dict[str, Any]:
    """Everything running in the background, found rather than listed."""
    import feature_catalog

    return {"running": feature_catalog.live_processes()}


@router.post("/api/features/rescan")
def rescan(request: Request) -> Dict[str, Any]:
    import server

    server.require_local_owner(request, request.headers.get("authorization"))
    import feature_catalog

    catalog = feature_catalog.scan(force=True)
    return {"counts": catalog["counts"], "new_modules": catalog.get("new_modules", [])}
