"""HTTP routes for system specs and live readings (OVERHAUL_CONTRACTS.md §4.1).

Included by ``server.py``'s ``_include_routers()`` — no edit to server.py is
needed. Both routes are read-only, so they sit behind the same chat gate as
everything else: open on an unclaimed local install, session-required once
claimed. Hardware facts about the machine the engine already runs on are not
a new exposure.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from server_auth import RequireChat

router = APIRouter()


@router.get("/api/system/specs")
def system_specs(refresh: bool = False, _user=RequireChat) -> Dict[str, Any]:
    """Accurate, sourced hardware identity. Unknown fields are null, never guessed."""
    from system_info import collect_specs

    return collect_specs(refresh=refresh)


@router.get("/api/system/live")
def system_live(_user=RequireChat) -> Dict[str, Any]:
    """The machine right now: CPU, memory, GPU telemetry, rates, top processes."""
    from system_info import collect_live

    return collect_live()
