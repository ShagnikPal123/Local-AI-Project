"""HTTP routes for the curiosity machine (Project Null N103).

Owner-only, like Free Will itself: these are Nyx's own questions, wants and
mistakes, and studying one reaches the web.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> None:
    import server

    server.require_local_owner(request, request.headers.get("authorization"))


@router.get("/api/curiosity")
def curiosity_state(request: Request) -> Dict[str, Any]:
    _owner(request)
    import curiosity

    return curiosity.state()


class AskBody(BaseModel):
    kind: str = "question"          # question | want | mistake
    text: str
    why: str = ""


@router.post("/api/curiosity/ask")
def curiosity_ask(body: AskBody, request: Request) -> Dict[str, Any]:
    _owner(request)
    import curiosity

    text = body.text.strip()
    if len(text) < 4:
        raise HTTPException(status_code=400, detail="Say what to file.")
    if body.kind == "want":
        return {"want": curiosity.want(text, body.why)}
    if body.kind == "mistake":
        return {"mistake": curiosity.own_mistake(text, learned=body.why)}
    return {"question": curiosity.ask(text, why=body.why)}


class StudyBody(BaseModel):
    id: str = ""
    allow_web: bool = True


@router.post("/api/curiosity/study")
def curiosity_study(body: StudyBody, request: Request) -> Dict[str, Any]:
    """Look one question up now. The owner presses this; the loop is separate."""
    _owner(request)
    import curiosity

    return curiosity.study(body.id, allow_web=body.allow_web)


@router.delete("/api/curiosity/questions/{question_id}")
def curiosity_drop(question_id: str, request: Request) -> Dict[str, Any]:
    _owner(request)
    import curiosity

    return {"dropped": curiosity.drop(question_id)}


class CuriositySettings(BaseModel):
    notice: Optional[bool] = None
    study_alone: Optional[bool] = None
    per_day: Optional[int] = None


@router.put("/api/curiosity/settings")
def curiosity_settings(body: CuriositySettings, request: Request) -> Dict[str, Any]:
    _owner(request)
    import curiosity

    changes = body.model_dump(exclude_none=True)
    if "per_day" in changes:
        changes["per_day"] = max(0, min(24, int(changes["per_day"])))
    return {"settings": curiosity.update_settings(**changes)}
