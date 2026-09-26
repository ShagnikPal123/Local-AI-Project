"""HTTP routes for the malicious-file checks (owner, 2026-09-22).

What was blocked, what was flagged, and which checks are on. Owner-only: this
is the security log of the owner's own PC, not something an invited account
needs to see. Checking one file by path is owner-only for the same reason —
it opens whatever path it is handed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> None:
    import server

    server.require_local_owner(request, request.headers.get("authorization"))


class SettingsBody(BaseModel):
    enabled: Optional[bool] = None
    windows_security: Optional[bool] = None
    block_programs: Optional[bool] = None
    block_code_in_weights: Optional[bool] = None
    warn_prompt_injection: Optional[bool] = None


class CheckBody(BaseModel):
    path: str = ""
    upload_id: str = ""


@router.get("/api/security/files")
def file_checks(request: Request, limit: int = 50) -> Dict[str, Any]:
    """Recent verdicts (blocked and flagged files) plus the current settings."""
    _owner(request)
    import file_guard

    return {
        "checks": file_guard.recent(max(1, min(limit, 200))),
        "settings": file_guard.settings(),
        "scanner": "Windows Security" if file_guard.defender_exe() else "",
    }


@router.put("/api/security/files/settings")
def set_settings(body: SettingsBody, request: Request) -> Dict[str, Any]:
    _owner(request)
    import file_guard

    return file_guard.update_settings(**body.model_dump(exclude_none=True))


@router.post("/api/security/files/check")
def check_one(body: CheckBody, request: Request) -> Dict[str, Any]:
    """Check one file on this PC, or one upload, on demand."""
    _owner(request)
    import file_guard

    if body.upload_id:
        import uploads

        record = uploads.get_upload(body.upload_id)
        if record is None:
            raise HTTPException(status_code=404, detail="No such upload.")
        target, name = record["path"], record["name"]
    elif body.path:
        target, name = body.path, ""
    else:
        raise HTTPException(status_code=400, detail="Give a path or an upload id.")
    try:
        verdict = file_guard.check_file(target, name=name, source="asked for")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="That file is not on this PC.") from None
    return {"verdict": verdict.to_dict(), "message": verdict.message}
