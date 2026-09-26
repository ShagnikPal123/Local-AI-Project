"""HTTP routes for the chat's context bar and compaction (Request Q). Signed-in chat actions on that chat."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server_auth import RequireChat

router = APIRouter()


class CompactBody(BaseModel):
    focus: str = ""
    keep_last: int = Field(default=0, ge=0, le=20)
    provider: str = ""
    model: str = ""


class UndoBody(BaseModel):
    provider: str = ""
    model: str = ""


class SettingsBody(BaseModel):
    auto_compact: bool | None = None
    threshold: int | None = Field(default=None, ge=50, le=98)
    keep_last: int | None = Field(default=None, ge=2, le=20)


def _service(chat_id: str) -> Any:
    import server

    store = server._shared_chat_store()
    if chat_id != "default" and not store.exists(chat_id):
        raise HTTPException(status_code=404, detail="No such chat.")
    return server._get_service(chat_id), store


def _not_running(chat_id: str) -> None:
    try:
        from turn_registry import TURNS

        if TURNS.running_for_chat(chat_id):
            raise HTTPException(status_code=409, detail="Nyx is still answering in this chat — compact when it's done.")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        pass


@router.get("/api/chats/{chat_id}/context")
def chat_context(chat_id: str, provider: str = "", model: str = "", _user=RequireChat) -> Dict[str, Any]:
    import context_budget

    service, store = _service(chat_id)
    provider = provider.strip().lower()
    if provider and not model.strip():
        try:
            from model_hub import default_model

            model = default_model(provider, "text")  # Kimi's default has 8k of context, not 128k
        except Exception:  # noqa: BLE001
            model = ""
    result = context_budget.measure(service.conversation_history, provider, model.strip())
    result["can_undo"] = context_budget.can_undo(service)
    result["saved_summary"] = bool(store.compaction(chat_id)) if chat_id != "default" else False
    return result


@router.post("/api/chats/{chat_id}/compact")
def chat_compact(chat_id: str, body: CompactBody, _user=RequireChat) -> Dict[str, Any]:
    import context_budget

    _not_running(chat_id)
    service, store = _service(chat_id)
    try:
        return context_budget.compact(service, provider=body.provider.strip().lower(), model=body.model.strip(),
                                      keep_last=body.keep_last or None, focus=body.focus, chat_store=store,
                                      chat_id=chat_id if chat_id != "default" else getattr(service, "chat_id", ""))
    except context_budget.ContextError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/api/chats/{chat_id}/compact/undo")
def chat_compact_undo(chat_id: str, body: UndoBody, _user=RequireChat) -> Dict[str, Any]:
    import context_budget

    _not_running(chat_id)
    service, store = _service(chat_id)
    try:
        return context_budget.undo(service, chat_store=store, chat_id=chat_id if chat_id != "default" else getattr(service, "chat_id", ""),
                                   provider=body.provider.strip().lower(), model=body.model.strip())
    except context_budget.ContextError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/api/context/settings")
def context_settings(_user=RequireChat) -> Dict[str, Any]:
    import context_budget

    return context_budget.settings()


@router.put("/api/context/settings")
def context_settings_save(body: SettingsBody, _user=RequireChat) -> Dict[str, Any]:
    import context_budget

    return context_budget.save_settings(**{k: v for k, v in body.model_dump().items() if v is not None})
