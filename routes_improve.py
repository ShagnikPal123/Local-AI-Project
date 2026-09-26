"""HTTP routes for self-improvement sessions.

The owner points Nyx at its own base code from the Improve tab (or chat);
sessions analyze and file draft proposals into the existing change-review
gate. Nothing here publishes, applies, or edits anything: every outcome is a
draft awaiting the owner in Admin → changes.

Gating follows the ``routes_access`` pattern for owner-level actions: admin
permission once an owner account exists, loopback-only before that — the
person at the keyboard on a fresh local install *is* the owner, and the tab
must not dead-end on an install that has never been claimed. Starting or
stopping a session uses the same trust level as reviewing the changes it
files, because the session's output lands in exactly that queue.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


def _require_reviewer_or_local_owner(request: Request) -> Any:
    """Review permission once claimed; loopback-only before that (routes_access)."""
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


class ImproveStartRequest(BaseModel):
    """One analysis commission: what to improve, and how hard to try."""

    goal: str
    #: Seconds the analysis may run; 0 means "as long as the session needs"
    #: (still bounded by the engine's hard 45-minute ceiling).
    time_budget_seconds: float = Field(default=0.0, ge=0, le=45 * 60)
    #: Full power: four analysis angles instead of one, wider proposal cap.
    max_power: bool = False


@router.post("/api/improve/start")
def improve_start(
    request: ImproveStartRequest, _caller: Any = Depends(_require_reviewer_or_local_owner)
) -> Dict[str, Any]:
    from improvement_engine import ENGINE, SelfImprovementError

    try:
        return ENGINE.start(
            request.goal,
            time_budget_seconds=request.time_budget_seconds,
            max_power=request.max_power,
        )
    except (ValueError, RuntimeError, SelfImprovementError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/api/improve/sessions")
def improve_sessions(_caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improvement_engine import ENGINE

    return {"sessions": ENGINE.list_sessions()}


@router.get("/api/improve/sessions/{session_id}")
def improve_session(
    session_id: str, _caller: Any = Depends(_require_reviewer_or_local_owner)
) -> Dict[str, Any]:
    from improvement_engine import ENGINE

    session = ENGINE.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No such session.")
    return session


@router.post("/api/improve/sessions/{session_id}/stop")
def improve_stop(
    session_id: str, _caller: Any = Depends(_require_reviewer_or_local_owner)
) -> Dict[str, Any]:
    from improvement_engine import ENGINE, SelfImprovementError

    try:
        return ENGINE.stop(session_id)
    except SelfImprovementError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/api/improve/map")
def improve_map(_caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    """The repo map the analyzer reasons over — the same data, shown to the owner."""
    from improvement_engine import build_repo_map

    modules = build_repo_map()
    return {"modules": modules, "count": len(modules)}


# --- Autopilot: schedules, auto-approve windows, controls -----------------------


class AutopilotStartRequest(BaseModel):
    instruction: str = ""
    phases: list = Field(default_factory=list)
    loop: bool | None = None
    hours: float | None = None
    auto_approve: bool | None = None
    focus: str = ""


def _autopilot_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    from improve_autopilot import AutopilotError

    try:
        return fn(*args, **kwargs)
    except AutopilotError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/improve/autopilot")
def autopilot_state(_caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_autopilot import AUTOPILOT

    try:
        import self_patch

        applied = self_patch.applied_changes()
    except Exception:  # noqa: BLE001
        applied = {}
    return {"active": AUTOPILOT.active(), "runs": AUTOPILOT.runs()[:10], "controls": AUTOPILOT.controls(),
            "lessons": AUTOPILOT.lessons(20), "applied": applied}


@router.post("/api/improve/autopilot")
def autopilot_start(body: AutopilotStartRequest, caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_autopilot import AUTOPILOT
    import improve_review

    # "Apply all", "approve these changes in review", "deny the duplicates": the owner means the review queue,
    # not a new improve run (before 2026-09-16 each of those started another analysis session).
    intent = improve_review.review_intent(body.instruction) if not body.phases else None
    if intent:
        return {"review": _review_call(improve_review.run_intent, intent, by=_who(caller)), "intent": intent}
    return _autopilot_call(AUTOPILOT.start, body.instruction, phases=body.phases or None, loop=body.loop,
                           hours=body.hours, auto_approve=body.auto_approve, focus=body.focus)


@router.post("/api/improve/autopilot/{action}")
def autopilot_action(action: str, _caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_autopilot import AUTOPILOT

    handlers = {"stop": AUTOPILOT.stop, "pause": AUTOPILOT.pause, "resume": AUTOPILOT.resume}
    if action not in handlers:
        raise HTTPException(status_code=404, detail="Use stop, pause or resume.")
    return _autopilot_call(handlers[action])


class ControlValue(BaseModel):
    value: Any = None


@router.put("/api/improve/controls/{key}")
def control_set(key: str, body: ControlValue, _caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_autopilot import AUTOPILOT

    return _autopilot_call(AUTOPILOT.set_control, key, body.value, by="owner")


@router.post("/api/improve/controls")
def control_add(spec: Dict[str, Any], _caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_autopilot import AUTOPILOT

    return _autopilot_call(AUTOPILOT.add_control, spec, by="owner")


@router.delete("/api/improve/controls/{key}")
def control_remove(key: str, _caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_autopilot import AUTOPILOT

    _autopilot_call(AUTOPILOT.remove_control, key)
    return {"ok": True}


@router.get("/api/improve/changes")
def improve_changes(_caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    """Self-improvement changes (newest first) with their diff and whether they can be rolled back."""
    from change_review import CHANGE_LOG

    import self_patch

    applied = self_patch.applied_changes()
    items = []
    for change in CHANGE_LOG.list_changes():
        if change["origin"] != "agent":
            continue
        record = applied.get(change["id"], {})
        items.append({**{k: change[k] for k in ("id", "title", "description", "target", "status", "ai_review",
                                                  "reviewed_by", "published_by", "created_at", "published_at")},
                      "diff": change["content"] if record else "", "applied": bool(record),
                      "rolled_back": bool(record.get("rolled_back_at")),
                      "can_roll_back": bool(record) and not record.get("rolled_back_at")})
    return {"changes": items[:100]}


@router.post("/api/improve/changes/{change_id}/rollback")
def improve_rollback(change_id: str, _caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from change_review import CHANGE_LOG, ChangeError

    import self_patch

    try:
        message = self_patch.rollback(change_id)
    except self_patch.PatchError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    try:
        CHANGE_LOG.rollback(change_id, "owner")
    except ChangeError:
        pass
    return {"ok": True, "message": message, "restart_needed": True}


# --- Review queue: approve / deny / analyze all / implement (Request J3) -----------------------


class ReviewAnalyzeRequest(BaseModel):
    ids: list = Field(default_factory=list)
    limit: int = Field(default=40, ge=1, le=200)
    web: bool = False
    then_apply: bool = False
    implement: bool | None = None


class ReviewApplyRequest(BaseModel):
    #: {change_id: "approve" | "deny"}; empty means "use Nyx's recommendations".
    decisions: Dict[str, str] = Field(default_factory=dict)
    implement: bool | None = None


class ReviewDecision(BaseModel):
    implement: bool | None = None
    reason: str = ""


def _review_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    from improve_review import ReviewError

    try:
        return fn(*args, **kwargs)
    except ReviewError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001 - ChangeError and friends: say why
        if type(error).__name__ == "ChangeError":
            raise HTTPException(status_code=409, detail=str(error)) from error
        raise


def _who(caller: Any) -> str:
    return f"Owner ({getattr(caller, 'username', '') or 'this computer'})"


@router.get("/api/improve/review")
def review_queue(limit: int = 200, _caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_review import REVIEW_QUEUE

    return REVIEW_QUEUE.queue(limit=max(1, min(limit, 1000)))


@router.post("/api/improve/review/analyze")
def review_analyze(body: ReviewAnalyzeRequest, caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_review import REVIEW_QUEUE

    by = _who(caller) + (" — let Nyx decide and apply" if body.then_apply else "")
    return {"job": _review_call(REVIEW_QUEUE.analyze, ids=[str(i) for i in body.ids] or None, limit=body.limit,
                                web=body.web, then_apply=body.then_apply, implement=body.implement, by=by)}


@router.post("/api/improve/review/apply")
def review_apply(body: ReviewApplyRequest, caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_review import REVIEW_QUEUE

    decisions = {str(k): str(v) for k, v in body.decisions.items() if v in ("approve", "deny")}
    return {"job": _review_call(REVIEW_QUEUE.apply, decisions=decisions or None, implement=body.implement, by=_who(caller))}


@router.post("/api/improve/review/stop")
def review_stop(_caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_review import REVIEW_QUEUE

    return {"job": REVIEW_QUEUE.stop()}


@router.post("/api/improve/review/deny-duplicates")
def review_deny_duplicates(caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_review import REVIEW_QUEUE

    return REVIEW_QUEUE.deny_duplicates(by=_who(caller))


@router.post("/api/improve/changes/{change_id}/approve")
def change_approve(change_id: str, body: ReviewDecision, caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_review import REVIEW_QUEUE

    return _review_call(REVIEW_QUEUE.approve, change_id, by=_who(caller), implement=body.implement)


@router.post("/api/improve/changes/{change_id}/deny")
def change_deny(change_id: str, body: ReviewDecision, caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_review import REVIEW_QUEUE

    return _review_call(REVIEW_QUEUE.deny, change_id, by=_who(caller), reason=body.reason)


@router.post("/api/improve/changes/{change_id}/implement")
def change_implement(change_id: str, caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    from improve_review import REVIEW_QUEUE

    return _review_call(REVIEW_QUEUE.implement, change_id, by=_who(caller))


# --- Deep & specific mode (Request J4) -----------------------------------------------------------


class DeepPlanRequest(BaseModel):
    text: str
    iterations: int = Field(default=2, ge=1, le=5)


class DeepStartRequest(BaseModel):
    text: str
    items: list = Field(default_factory=list)
    iterations: int = Field(default=2, ge=1, le=5)
    apply: bool = True
    extend: bool = True


@router.post("/api/improve/deep/plan")
def deep_plan(body: DeepPlanRequest, _caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    """Split the owner's list into items and estimate each — offline, fast enough to call while typing."""
    import improve_deep

    return improve_deep.plan(body.text[:20000], body.iterations)


@router.post("/api/improve/deep")
def deep_start(body: DeepStartRequest, _caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    import improve_deep

    try:
        return {"job": improve_deep.DEEP_JOBS.start(body.text, items=body.items or None, iterations=body.iterations,
                                                    apply=body.apply, extend=body.extend)}
    except improve_deep.DeepError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/api/improve/deep")
def deep_state(_caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    import improve_deep

    return {"job": improve_deep.DEEP_JOBS.current()}


@router.post("/api/improve/deep/stop")
def deep_stop(_caller: Any = Depends(_require_reviewer_or_local_owner)) -> Dict[str, Any]:
    import improve_deep

    return {"job": improve_deep.DEEP_JOBS.stop()}
