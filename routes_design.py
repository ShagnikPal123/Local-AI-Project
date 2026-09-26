"""HTTP routes for design sense (Project Null N88).

Used by the Redesign tab, the Apply tab and anything else that is about to put
pixels on screen: ask for a brief first, and record what the owner kept or undid
afterwards so the next brief knows their taste.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


class BriefRequest(BaseModel):
    request: str
    tab_id: Optional[str] = None
    #: Upload ids of pictures to read for layout.
    images: List[str] = []
    #: Extra material: {"kind": "upload"|"url"|"note", "value": "...", "label": "..."}
    sources: List[Dict[str, Any]] = []
    research: bool = True
    use_model: bool = True


class DecisionRequest(BaseModel):
    kind: str = "ui"
    summary: str
    detail: Dict[str, Any] = {}
    #: applied | undone | liked | disliked
    verdict: str = "applied"


@router.post("/api/design/brief")
def design_brief(body: BriefRequest, _user=RequireChat) -> Dict[str, Any]:
    """Decide how this thing should look, on the record, before building it."""
    import design_sense

    if not body.request.strip():
        raise HTTPException(status_code=400, detail="Say what is being designed.")
    return {"brief": design_sense.build_brief(body.request, tab_id=body.tab_id, images=body.images,
                                              sources=body.sources, research=body.research,
                                              use_model=body.use_model)}


@router.get("/api/design/taste")
def design_taste(_user=RequireChat) -> Dict[str, Any]:
    """What this owner has asked for, kept and undone — the profile a brief is built on."""
    import design_sense

    return {"taste": design_sense.taste(), "decisions": design_sense.decisions(limit=40),
            "avoid": design_sense.AVOID_BY_DEFAULT, "principles": design_sense.PRINCIPLES}


@router.post("/api/design/decisions")
def add_decision(body: DecisionRequest, _user=RequireChat) -> Dict[str, Any]:
    """Record a design decision and how it went (an undone one teaches the most)."""
    import design_sense

    return {"decision": design_sense.record_decision(body.kind, body.summary, body.detail, body.verdict)}
