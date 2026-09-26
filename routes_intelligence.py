"""HTTP routes for the intelligence layer: prompt optimizer, super brain, Nyx Core.

Reads use the chat gate. Seeding the brain from folders and changing the
optimizer need the owner (the same rule as keys and the engine).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


# --- prompt optimizer ---------------------------------------------------------------


class OptimizerSettings(BaseModel):
    enabled: Optional[bool] = None
    online: Optional[bool] = None
    strength: Optional[int] = None
    show_in_chat: Optional[bool] = None
    expand_short_tasks: Optional[bool] = None
    polish_long_requests: Optional[bool] = None
    online_timeout_seconds: Optional[int] = None


@router.get("/api/optimizer/settings")
def optimizer_settings(_user=RequireChat) -> Dict[str, Any]:
    import prompt_optimizer

    return prompt_optimizer.OPTIMIZER.settings()


@router.put("/api/optimizer/settings")
def optimizer_update(body: OptimizerSettings, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import prompt_optimizer

    settings = prompt_optimizer.OPTIMIZER.update_settings(**body.model_dump())
    try:
        from agent_events import publish_ui

        publish_ui("optimizer.changed", settings=settings)
    except Exception:  # noqa: BLE001
        pass
    return settings


class PreviewRequest(BaseModel):
    text: str
    context: Dict[str, Any] = {}


@router.post("/api/optimizer/preview")
def optimizer_preview(body: PreviewRequest, _user=RequireChat) -> Dict[str, Any]:
    """What the optimizer would do with a message — even when switched off."""
    import prompt_optimizer

    result = prompt_optimizer.OPTIMIZER.optimize(body.text, body.context, force=True)
    return {**result.event(), "model_text": result.model_text}


# --- super brain -------------------------------------------------------------------


@router.get("/api/brain/summary")
def brain_summary(_user=RequireChat) -> Dict[str, Any]:
    import super_brain

    return super_brain.BRAIN.summary()


@router.get("/api/brain/points")
def brain_points(limit: int = 400_000, _user=RequireChat) -> Response:
    """Float32 little-endian, 6 per node: x, y, z, cluster, kind (0 memory · 1 concept · 2 source), weight."""
    import super_brain

    count, data = super_brain.BRAIN.points_buffer(max(1, min(limit, 2_000_000)))
    return Response(content=data, media_type="application/octet-stream",
                    headers={"X-Count": str(count), "X-Stride": "6", "Cache-Control": "no-store"})


@router.get("/api/brain/edges")
def brain_edges(limit: int = 60_000, _user=RequireChat) -> Response:
    """Uint32 little-endian index pairs into /api/brain/points, strongest first."""
    import super_brain

    count, data = super_brain.BRAIN.edges_buffer(max(1, min(limit, 400_000)))
    return Response(content=data, media_type="application/octet-stream", headers={"X-Count": str(count), "Cache-Control": "no-store"})


@router.get("/api/brain/recent")
def brain_recent(limit: int = 40, _user=RequireChat) -> Dict[str, Any]:
    import super_brain

    return {"memories": super_brain.BRAIN.recent(max(1, min(limit, 200)))}


@router.get("/api/brain/search")
def brain_search(q: str = "", _user=RequireChat) -> Dict[str, Any]:
    import super_brain

    if not q.strip():
        return {"memories": [], "concepts": []}
    return super_brain.BRAIN.search(q)


@router.get("/api/brain/node/{node_id}")
def brain_node(node_id: int, _user=RequireChat) -> Dict[str, Any]:
    import super_brain

    node = super_brain.BRAIN.node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="No such node.")
    return node


@router.get("/api/brain/at/{index}")
def brain_node_at(index: int, _user=RequireChat) -> Dict[str, Any]:
    import super_brain

    node = super_brain.BRAIN.node_at(index)
    if node is None:
        raise HTTPException(status_code=404, detail="No node there.")
    return node


class SeedRequest(BaseModel):
    sources: List[str] = []
    folder: str = ""


@router.post("/api/brain/seed")
def brain_seed(body: SeedRequest, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import super_brain

    sources = body.sources or (["folder"] if body.folder else list(super_brain.SEED_SOURCES))
    return super_brain.BRAIN.seed(sources, folder=body.folder)


class RememberRequest(BaseModel):
    text: str
    source: str = "files"


@router.post("/api/brain/remember")
def brain_remember(body: RememberRequest, _user=RequireChat) -> Dict[str, Any]:
    import super_brain

    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Nothing to remember.")
    super_brain.BRAIN.ingest(body.text, source=body.source, kind="remembered")
    return {"ok": True}


# --- Nyx Core ----------------------------------------------------------------------


@router.get("/api/core")
def core_snapshot(_user=RequireChat) -> Dict[str, Any]:
    import nyx_core

    return nyx_core.CORE.snapshot()


@router.get("/api/core/network")
def core_network(text: str = "", _user=RequireChat) -> Dict[str, Any]:
    import nyx_core

    return nyx_core.CORE.network_view(text=text)


@router.get("/api/core/predict")
def core_predict(text: str = "", _user=RequireChat) -> Dict[str, Any]:
    import nyx_core

    return {"prediction": nyx_core.CORE.predict(text), "recommended_model": nyx_core.CORE.recommend_model(text)}


@router.get("/api/core/complete")
def core_complete(prefix: str = "", _user=RequireChat) -> Dict[str, Any]:
    import nyx_core

    return {"suggestions": nyx_core.CORE.complete(prefix) if prefix.strip() else []}


# --- predictions & autonomy ----------------------------------------------------------


class PredictSettings(BaseModel):
    predictions: Optional[bool] = None
    predictive_text: Optional[bool] = None
    next_tab_hints: Optional[bool] = None
    model_hints: Optional[bool] = None
    idle_tabs: Optional[bool] = None
    auto_updates: Optional[str] = None
    detox_daily: Optional[bool] = None
    detox_auto_approve: Optional[bool] = None
    idle_minutes: Optional[int] = None


@router.get("/api/predict")
def predict(message: str = "", _user=RequireChat) -> Dict[str, Any]:
    from predictor import PREDICTOR

    return PREDICTOR.snapshot(message)


@router.get("/api/predict/settings")
def predict_settings(_user=RequireChat) -> Dict[str, Any]:
    from predictor import PREDICTOR

    return PREDICTOR.settings()


@router.put("/api/predict/settings")
def predict_settings_update(body: PredictSettings, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    from predictor import PREDICTOR

    settings = PREDICTOR.update_settings(**body.model_dump())
    try:
        from agent_events import publish_ui

        publish_ui("predict.changed", settings=settings)
    except Exception:  # noqa: BLE001
        pass
    return settings


@router.get("/api/updates")
def updates_check(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Git checkouts update with git; zip installs (beta testers) from the reviewed release channel."""
    import beta_channel
    from predictor import check_updates

    if beta_channel.is_git_checkout():
        return {**check_updates(), "install_kind": "git", "local_version": beta_channel.local_version()}
    return beta_channel.check()


@router.get("/api/updates/status")
def updates_status(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Channel, version, staged download and last install — no network call (Request G2)."""
    import beta_channel

    return beta_channel.status()


@router.post("/api/updates/install")
def updates_install(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import beta_channel
    from predictor import install_updates

    if beta_channel.is_git_checkout():
        return install_updates()
    try:
        return beta_channel.download()
    except beta_channel.UpdateError as error:
        return {"ok": False, "installed": False, "detail": str(error)}


class ChannelBody(BaseModel):
    channel: str


@router.put("/api/updates/channel")
def updates_channel(body: ChannelBody, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import beta_channel

    try:
        return beta_channel.set_channel(body.channel)
    except beta_channel.UpdateError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/updates/rollback")
def updates_rollback(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import beta_channel

    try:
        return beta_channel.rollback()
    except beta_channel.UpdateError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
