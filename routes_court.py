"""The court's routes (court.py): open a case, read it, stop it, and let the owner pick the winner."""

from __future__ import annotations

from typing import Any, Dict, List, Union

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


class CaseBody(BaseModel):
    questions: Union[str, List[str]]
    origin: str = "chat"
    origin_id: str = ""


class PickBody(BaseModel):
    side: str = ""


@router.post("/api/court")
def open_case(body: CaseBody, _u=RequireChat) -> Dict[str, Any]:
    import court

    try:
        return court.start(body.questions, origin=body.origin if body.origin in ("chat", "office", "world") else "chat",
                           origin_id=body.origin_id[:80])
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/court")
def cases(origin: str = "", _u=RequireChat) -> Dict[str, Any]:
    import court

    return {"cases": court.list_cases(origin)}


@router.get("/api/court/{case_id}")
def case(case_id: str, _u=RequireChat) -> Dict[str, Any]:
    import court

    found = court.get(case_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such case.")
    return found


@router.post("/api/court/{case_id}/stop")
def stop(case_id: str, _u=RequireChat) -> Dict[str, Any]:
    import court

    return {"stopped": court.stop(case_id)}


@router.post("/api/court/{case_id}/pick")
def pick(case_id: str, body: PickBody, _u=RequireChat) -> Dict[str, Any]:
    import court

    try:
        return court.pick(case_id, body.side)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="No such case.") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
