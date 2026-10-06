"""HTTP routes for the swarm size — the slider beside Swarm in the chat's mode switch (Update 1, U5).

The swarm itself runs inside a chat turn (``chat_modes`` Swarm mode → ``dispatch_agents``); these routes only
read and remember how many agents it may use, which ``swarm.py`` clamps to what this PC can carry.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


class SwarmSettings(BaseModel):
    size: int


@router.get("/api/swarm")
def swarm_state(_user=RequireChat) -> Dict[str, Any]:
    """The owner's swarm size, the machine's ceiling, and how many agents work at once."""
    import swarm

    return swarm.describe()


@router.post("/api/swarm")
def swarm_save(body: SwarmSettings, _user=RequireChat) -> Dict[str, Any]:
    import swarm

    try:
        return swarm.save(body.size)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
