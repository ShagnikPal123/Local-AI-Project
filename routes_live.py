"""HTTP routes for watching and steering Nyx while it works.

Kept out of ``server.py`` (already ~2.4k lines) and included by it. Everything
here is under ``/api`` and therefore behind the session middleware once an
install is claimed; owner-only actions additionally use
``server.require_local_owner``.

Server-Sent Events are produced from ordinary generators over a thread-safe
queue: the turn runs on a worker thread and keeps going if the browser tab
closes, so an answer is never lost to a page reload — it is saved to the chat
and ``/api/chats/{id}/messages`` returns it.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from server_auth import RequireChat
from turn_registry import TURNS

router = APIRouter()

#: Turns in flight, so Stop can reach them.
_TURNS: Dict[str, threading.Event] = {}
_TURNS_LOCK = threading.Lock()

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}

#: Events worth recording in the workspace-wide activity log (the rest are too chatty).
_ACTIVITY_TYPES = {"turn.start", "tool.start", "tool.end", "agent.update", "skill.created", "done", "error",
                   "approval.request"}


def _local_owner():
    from server import require_local_owner

    return require_local_owner


def _role_of(user: Any) -> str:
    role = getattr(user, "role", None)
    return getattr(role, "value", None) or (str(role) if role else "local")


def _sse(event: Dict[str, Any]) -> str:
    return "data: " + json.dumps(event, default=str, ensure_ascii=False) + "\n\n"


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------


class StreamRequest(BaseModel):
    message: str = ""
    chat_id: Optional[str] = None
    attachments: List[str] = []
    attribute_id: Optional[str] = None
    personality_id: Optional[str] = None
    personality_text: Optional[str] = None
    use_rag: bool = True
    #: The provider picked in the chat's dropdown; empty means the router decides.
    provider: Optional[str] = None
    #: Hands-free voice (Request R11): the owner is speaking and will hear this answer read aloud.
    voice: bool = False
    #: The listening session this turn came from, so an answer drafted while the
    #: owner was still speaking can be used instead of starting from cold (N90).
    voice_session: str = ""
    #: The slider under the composer (chat_modes.py): normal | cowork | plan | plan_go.
    mode: Optional[str] = None


class StopRequest(BaseModel):
    turn_id: str


#: The Free Will tab's conversation (freewill.CHAT_KEY): Nyx's internal chat store, so it stays out of the chat list.
FREEWILL_CHAT = "__freewill__"

#: What a hands-free turn is told, so the answer sounds like speech instead of a document (Request R11).
VOICE_NOTE = (
    "[Hands-free voice] The owner is speaking to you and will hear this answer read aloud, not read it. "
    "Answer in at most three short sentences of plain spoken English: no markdown, no bullet lists, no headings, no code "
    "blocks and no links unless they ask for them. Say numbers the way they are spoken. If the answer is long, say the "
    "short version and offer the rest. If you are about to use a tool, say in a few words what you are doing first. "
    "Never say your own name in a spoken answer unless you are asked who you are."
)


@router.post("/api/chat/stream")
def chat_stream(body: StreamRequest, user=RequireChat) -> StreamingResponse:
    """Send a message and watch the turn happen (events: OVERHAUL_CONTRACTS.md §3.1)."""
    turn_id, _chat_id = start_turn(body, user)
    return StreamingResponse(_follow_turn(turn_id, 0), media_type="text/event-stream", headers=_SSE_HEADERS)


def start_turn(body: StreamRequest, user: Any) -> tuple[str, str]:
    """Start a chat turn on a worker thread and return ``(turn_id, chat_id)``.

    The streaming route follows it at once; the Command Zone starts one and lets the owner watch
    it from anywhere, since a turn never depends on the request that began it.
    """
    import server
    from agent_events import publish_activity
    from personalities import resolve_personality

    text = (body.message or "").strip()
    if not text and not body.attachments:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")
    if not text:
        text = "Please look at the attached file(s)."
    try:
        import presence

        presence.mark_active("chat")
    except Exception:  # pragma: no cover - presence is a hint, never a failure
        pass

    service = server._get_service(body.chat_id)
    freewill_note = ""
    if (body.chat_id or "") == FREEWILL_CHAT:
        # The Free Will tab (Request R15): the owner's own, allowed first, and every tool behind its guard.
        import freewill

        if _role_of(user) not in ("local", "owner", "admin"):
            raise HTTPException(status_code=403, detail="Free Will is the owner's.")
        try:
            freewill_note = freewill.prepare(service)
        except freewill.FreeWillError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
    personality = resolve_personality(body.personality_id, body.personality_text)
    if personality:
        service.set_personality(personality)
    context = ""
    if body.use_rag:
        try:
            context = server._get_rag().build_context_prompt(text)
        except Exception:
            context = ""
    if body.voice:
        context = (context + "\n\n" if context else "") + VOICE_NOTE
    if freewill_note:
        context = (context + "\n\n" if context else "") + freewill_note
    if context or body.use_rag or body.voice or freewill_note:
        service.set_turn_context(context)

    turn_id = uuid.uuid4().hex[:12]
    chat_id = getattr(service, "chat_id", None) or body.chat_id or "default"
    record = TURNS.start(turn_id, chat_id, text)
    cancel = record.cancel
    with _TURNS_LOCK:
        _TURNS[turn_id] = cancel

    def sink(event: Dict[str, Any]) -> None:
        event.setdefault("turn_id", turn_id)
        TURNS.append(turn_id, event)
        if event.get("type") in _ACTIVITY_TYPES:
            publish_activity(event["type"], **{k: v for k, v in event.items() if k not in ("type", "data_url")})

    def work() -> None:
        state = "done"
        try:
            result = service.chat_turn(
                text,
                sink=sink,
                attachments=body.attachments,
                role=_role_of(user),
                turn_id=turn_id,
                cancel_event=cancel,
                attribute_id=body.attribute_id,
                provider=body.provider,
                voice_session=body.voice_session,
                mode=body.mode,
            )
            if cancel.is_set() or (isinstance(result, dict) and result.get("stopped")):
                state = "stopped"
        except Exception as error:  # noqa: BLE001 - reported to the stream
            state = "error"
            sink({"type": "error", "turn_id": turn_id, "message": f"{type(error).__name__}: {error}"})
        finally:
            with _TURNS_LOCK:
                _TURNS.pop(turn_id, None)
            TURNS.finish(turn_id, state)

    threading.Thread(target=work, name=f"nyx-turn-{turn_id}", daemon=True).start()
    return turn_id, chat_id


def _follow_turn(turn_id: str, since: int):
    """SSE body for one turn: replay from ``since``, then live until it ends.

    The turn does not depend on this generator. If the browser goes away the
    generator is simply closed and the work carries on; anyone can attach again.
    """
    yield f": nyx turn {turn_id}\n\n"
    for event in TURNS.follow(turn_id, since=since):
        if event is None:
            yield ": keep-alive\n\n"
        else:
            yield _sse(event)


@router.get("/api/turns")
def list_turns(include_recent: bool = True, _user=RequireChat) -> Dict[str, Any]:
    """Turns running now (and recently finished), across every chat and window."""
    return {"turns": TURNS.active(include_recent=include_recent)}


@router.get("/api/turns/{turn_id}")
def get_turn(turn_id: str, _user=RequireChat) -> Dict[str, Any]:
    record = TURNS.get(turn_id)
    if record is None:
        raise HTTPException(status_code=404, detail="That turn is not running and is no longer kept.")
    return {"turn": record.summary()}


@router.get("/api/turns/{turn_id}/stream")
def follow_turn(turn_id: str, since: int = 0, _user=RequireChat) -> StreamingResponse:
    """Watch a turn that is already running — after a reload, from another tab or window."""
    if TURNS.get(turn_id) is None:
        raise HTTPException(status_code=404, detail="That turn is not running and is no longer kept.")
    return StreamingResponse(_follow_turn(turn_id, max(0, since)), media_type="text/event-stream",
                             headers=_SSE_HEADERS)


class AdviseRequest(BaseModel):
    text: str
    chat_id: Optional[str] = None
    use_model: bool = True


@router.post("/api/turns/advise")
def advise_turn(body: AdviseRequest, _user=RequireChat) -> Dict[str, Any]:
    """Queue, interrupt, run alongside or branch: Nyx's pick for a message typed mid-answer (Request G12)."""
    import turn_advice

    record = TURNS.running_for_chat(body.chat_id or "default")
    running = record.message if record else ""
    return {**turn_advice.advise(body.text, running, use_model=body.use_model and bool(running)),
            "running": bool(record)}


@router.get("/api/chats/{chat_id}/turn")
def chat_running_turn(chat_id: str, _user=RequireChat) -> Dict[str, Any]:
    """The turn running in this chat right now, if any — so reopening a chat can reattach."""
    record = TURNS.running_for_chat(chat_id)
    if record is None and chat_id == "default":
        import server

        active = server._shared_chat_store().data.get("active_chat")
        record = TURNS.running_for_chat(active) if active else None
    return {"turn": record.summary() if record else None}


@router.post("/api/chat/stop")
def chat_stop(body: StopRequest, _user=RequireChat) -> Dict[str, Any]:
    if TURNS.cancel(body.turn_id):
        return {"ok": True}
    with _TURNS_LOCK:
        cancel = _TURNS.get(body.turn_id)
    if cancel is None:
        return {"ok": False, "detail": "That turn has already finished."}
    cancel.set()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Chats as tabs
# ---------------------------------------------------------------------------


class NewChatRequest(BaseModel):
    title: str = ""


class RenameChatRequest(BaseModel):
    title: str


@router.get("/api/chats/summaries")
def chat_summaries(_user=RequireChat) -> Dict[str, Any]:
    import server

    store = server._shared_chat_store()
    return {"chats": store.summaries(), "active": store.data.get("active_chat"), "limit": store.MAX_CHATS}


@router.post("/api/chats")
def create_chat(body: NewChatRequest, _user=RequireChat) -> Dict[str, Any]:
    import server

    store = server._shared_chat_store()
    try:
        chat_id = store.create(body.title.strip() or None)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"chat": next(c for c in store.summaries() if c["id"] == chat_id)}


@router.get("/api/chats/{chat_id}/messages")
def chat_messages(chat_id: str, _user=RequireChat) -> Dict[str, Any]:
    import server

    store = server._shared_chat_store()
    if chat_id == "default" and not store.exists(chat_id):
        # "default" means "the chat I was in": a fresh page (or cleared browser
        # storage) has no chat id yet. Answer with the active chat, and say which
        # one it is so the page can switch to its real id.
        active = store.data.get("active_chat")
        if active and store.exists(active):
            messages = [m for m in store.messages(active) if m.get("role") in ("user", "assistant")]
            return {"chat_id": active, "messages": messages[-400:]}
        return {"chat_id": chat_id, "messages": []}
    if not store.exists(chat_id):
        raise HTTPException(status_code=404, detail="No such chat.")
    messages = [m for m in store.messages(chat_id) if m.get("role") in ("user", "assistant")]
    return {"chat_id": chat_id, "messages": messages[-400:]}


@router.patch("/api/chats/{chat_id}")
def rename_chat(chat_id: str, body: RenameChatRequest, _user=RequireChat) -> Dict[str, Any]:
    import server

    if not server._shared_chat_store().rename(chat_id, body.title):
        raise HTTPException(status_code=400, detail="No such chat, or the title was empty.")
    return {"ok": True}


class CopyChatRequest(BaseModel):
    title: str = ""
    #: Branch only: how many user/assistant messages to keep (None keeps all).
    upto: Optional[int] = None


@router.post("/api/chats/{chat_id}/duplicate")
def duplicate_chat(chat_id: str, body: CopyChatRequest, _user=RequireChat) -> Dict[str, Any]:
    """An exact, unlinked copy of a chat (Request G15: its own feature, not a side effect of New)."""
    import server

    try:
        chat = server._shared_chat_store().duplicate(chat_id, body.title.strip() or None)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"chat": {"id": chat["id"], "title": chat.get("title"), "kind": "duplicate"}}


@router.post("/api/chats/{chat_id}/branch")
def branch_chat(chat_id: str, body: CopyChatRequest, _user=RequireChat) -> Dict[str, Any]:
    """A linked chat with the real messages up to ``upto``, to go another way from there."""
    import server

    try:
        chat = server._shared_chat_store().branch(chat_id, body.upto, body.title.strip() or None)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"chat": {"id": chat["id"], "title": chat.get("title"), "kind": "branch", "kept": chat.get("branched_at", 0)}}


@router.post("/api/chats/{chat_id}/fork")
def fork_chat_by_id(chat_id: str, body: CopyChatRequest, _user=RequireChat) -> Dict[str, Any]:
    """A linked chat that starts from a summary of recent context."""
    import server

    try:
        chat = server._shared_chat_store().fork(chat_id, body.title.strip() or None)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"chat": {"id": chat["id"], "title": chat.get("title"), "kind": "fork"}}


@router.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str, _user=RequireChat) -> Dict[str, Any]:
    import server

    if not server._shared_chat_store().delete(chat_id, retain_memory=True):
        raise HTTPException(status_code=404, detail="No such chat.")
    server._forget_service(chat_id)
    return {"ok": True}


# Recently deleted (Plan Null N3). A separate prefix, because "/api/chats/trash" would be
# read as a chat whose id is "trash" by the routes above.
@router.get("/api/chat-trash")
def list_chat_trash(_user=RequireChat) -> Dict[str, Any]:
    import server

    store = server._shared_chat_store()
    return {"chats": store.trash(), "days": store.TRASH_DAYS}


@router.post("/api/chat-trash/{chat_id}/restore")
def restore_chat(chat_id: str, _user=RequireChat) -> Dict[str, Any]:
    import server

    try:
        restored = server._shared_chat_store().restore(chat_id)
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    if not restored:
        raise HTTPException(status_code=404, detail="That chat is no longer in Recently deleted.")
    return {"ok": True, "id": chat_id}


@router.delete("/api/chat-trash/{chat_id}")
def purge_chat(chat_id: str, _user=RequireChat) -> Dict[str, Any]:
    import server

    if not server._shared_chat_store().purge(chat_id):
        raise HTTPException(status_code=404, detail="That chat is no longer in Recently deleted.")
    return {"ok": True}


@router.delete("/api/chat-trash")
def purge_all_chats(_user=RequireChat) -> Dict[str, Any]:
    import server

    return {"ok": True, "purged": server._shared_chat_store().purge()}


# ---------------------------------------------------------------------------
# Slash commands (Request G5)
# ---------------------------------------------------------------------------


class GuessCommandRequest(BaseModel):
    text: str
    use_model: bool = True


class NewCommandRequest(BaseModel):
    name: str
    title: str = ""
    description: str = ""
    template: str


@router.get("/api/commands")
def list_commands(_user=RequireChat) -> Dict[str, Any]:
    """Every / command: built-in, owner-made, and one per enabled skill."""
    import commands

    return {"commands": commands.all_commands()}


@router.post("/api/commands/guess")
def guess_command(body: GuessCommandRequest, _user=RequireChat) -> Dict[str, Any]:
    """What an unknown /command probably meant, and a command to make if nothing fits."""
    import commands

    return commands.guess(body.text, use_model=body.use_model)


@router.post("/api/commands")
def create_command(body: NewCommandRequest, _user=RequireChat) -> Dict[str, Any]:
    import commands

    try:
        return {"command": commands.add_command(body.name, body.title, body.description, body.template)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/api/commands/{name}")
def delete_command(name: str, _user=RequireChat) -> Dict[str, Any]:
    import commands

    if not commands.remove_command(name):
        raise HTTPException(status_code=404, detail=f"No command /{name} that you made.")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Mods: the owner's lasting changes to Nyx, one named bundle each (mods.py)
# ---------------------------------------------------------------------------


class SaveModRequest(BaseModel):
    name: str
    parts: List[Dict[str, Any]]
    description: str = ""
    mod_id: str = ""
    enabled: bool = True


class ToggleModRequest(BaseModel):
    enabled: bool


@router.get("/api/mods")
def list_mods(_user=RequireChat) -> Dict[str, Any]:
    """Every mod, what the app draws for the enabled ones, and the catalogue of parts."""
    import mods

    return {"mods": mods.MOD_STORE.list(), "view": mods.MOD_STORE.view(),
            "parts": {kind: spec["does"] for kind, spec in mods.PARTS.items()}}


@router.post("/api/mods")
def save_mod(body: SaveModRequest, _user=RequireChat) -> Dict[str, Any]:
    import mods

    try:
        return {"mod": mods.MOD_STORE.save(body.name, body.parts, description=body.description,
                                           mod_id=body.mod_id, author="owner", enabled=body.enabled)}
    except mods.ModError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/mods/{mod_id}/toggle")
def toggle_mod(mod_id: str, body: ToggleModRequest, _user=RequireChat) -> Dict[str, Any]:
    import mods

    try:
        return {"mod": mods.MOD_STORE.set_enabled(mod_id, body.enabled)}
    except mods.ModError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/api/mods/{mod_id}")
def delete_mod(mod_id: str, _user=RequireChat) -> Dict[str, Any]:
    import mods

    try:
        mods.MOD_STORE.delete(mod_id)
    except mods.ModError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"ok": True}


# ---------------------------------------------------------------------------
# Backgrounds (Request G8)
# ---------------------------------------------------------------------------


class BackgroundAddRequest(BaseModel):
    upload_id: str
    name: str = ""
    animation: str = ""
    dim: float = 0.55


class BackgroundGenerateRequest(BaseModel):
    description: str
    animation: str = ""
    dim: float = 0.55


class BackgroundUpdateRequest(BaseModel):
    animation: Optional[str] = None
    dim: Optional[float] = None
    blur: Optional[float] = None
    name: Optional[str] = None


class BackgroundActiveRequest(BaseModel):
    id: Optional[str] = None


@router.get("/api/backgrounds")
def list_backgrounds(_user=RequireChat) -> Dict[str, Any]:
    import backgrounds

    return backgrounds.state()


@router.post("/api/backgrounds")
def add_background(body: BackgroundAddRequest, _user=RequireChat) -> Dict[str, Any]:
    import backgrounds

    try:
        return {"background": backgrounds.add(body.upload_id, body.name, body.animation, body.dim)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/backgrounds/generate")
def generate_background(body: BackgroundGenerateRequest, _user=RequireChat) -> Dict[str, Any]:
    """Nyx makes a wallpaper from words with the image model and applies it."""
    import backgrounds

    try:
        return {"background": backgrounds.generate(body.description, body.animation, body.dim)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/api/backgrounds/{background_id}")
def update_background(background_id: str, body: BackgroundUpdateRequest, _user=RequireChat) -> Dict[str, Any]:
    import backgrounds

    try:
        return {"background": backgrounds.update(background_id, **body.model_dump(exclude_none=True))}
    except KeyError as error:
        raise HTTPException(status_code=404, detail="No such background.") from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/backgrounds/active")
def set_active_background(body: BackgroundActiveRequest, _user=RequireChat) -> Dict[str, Any]:
    import backgrounds

    try:
        return backgrounds.activate(body.id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="No such background.") from error


@router.delete("/api/backgrounds/{background_id}")
def delete_background(background_id: str, _user=RequireChat) -> Dict[str, Any]:
    import backgrounds

    if not backgrounds.remove(background_id):
        raise HTTPException(status_code=404, detail="No such background.")
    return backgrounds.state()


# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------


@router.post("/api/uploads")
async def upload_file(request: Request, _user=RequireChat) -> Dict[str, Any]:
    """Raw body upload: the file bytes, ``X-Filename`` and ``Content-Type`` headers.

    Raw rather than multipart so no extra dependency is needed and the browser
    can stream a dropped file straight in.
    """
    import urllib.parse

    import uploads

    declared = int(request.headers.get("content-length") or 0)
    if declared > uploads.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="That file is larger than the 50 MB limit.")
    data = await request.body()
    name = urllib.parse.unquote(request.headers.get("x-filename") or "upload")
    try:
        record = uploads.save_upload(data, name, request.headers.get("content-type", ""))
    except uploads.UploadError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"upload": uploads.public_record(record)}


@router.get("/api/uploads/{upload_id}")
def get_upload_file(upload_id: str, _user=RequireChat) -> Response:
    import uploads

    record = uploads.get_upload(upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No such upload.")
    # An upload shares an origin with Nyx's own page, so anything that a browser
    # would *run* (HTML, SVG) goes back as an inert download (file_guard).
    try:
        import file_guard

        media_type, headers = file_guard.safe_serving(record["mime"], record["name"])
    except Exception:  # noqa: BLE001
        media_type, headers = record["mime"], {"X-Content-Type-Options": "nosniff"}
    return FileResponse(record["path"], media_type=media_type, filename=record["name"], headers=headers)


# ---------------------------------------------------------------------------
# Approvals and permissions
# ---------------------------------------------------------------------------


class ApprovalRequest(BaseModel):
    approve: bool


class PermissionsUpdate(BaseModel):
    categories: Optional[Dict[str, str]] = None
    protected_paths: Optional[List[str]] = None
    accounts_inherit: Optional[bool] = None


@router.get("/api/approvals")
def list_approvals(_user=RequireChat) -> Dict[str, Any]:
    from permissions import pending_approvals

    return {"pending": pending_approvals()}


@router.post("/api/approvals/{approval_id}")
def answer_approval(approval_id: str, body: ApprovalRequest, _user=RequireChat) -> Dict[str, Any]:
    from permissions import resolve_approval

    # Approving an action on the owner's machine is the owner's call. Invited
    # accounts never reach "ask" for restricted categories (they are blocked),
    # so a session is sufficient here.
    if not resolve_approval(approval_id, body.approve):
        raise HTTPException(status_code=404, detail="That request has already been answered or timed out.")
    return {"ok": True, "approved": body.approve}


@router.get("/api/permissions")
def get_permissions(_user=RequireChat) -> Dict[str, Any]:
    from permissions import POLICY

    return POLICY.snapshot()


@router.post("/api/permissions")
def set_permissions(body: PermissionsUpdate, request: Request) -> Dict[str, Any]:
    import server
    from permissions import POLICY

    server.require_local_owner(request, request.headers.get("authorization"))
    try:
        snapshot = POLICY.update(body.categories, body.protected_paths, body.accounts_inherit)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    try:
        from agent_events import publish_ui

        publish_ui("permissions.changed", categories=snapshot["categories"])
    except Exception:
        pass
    return snapshot


# ---------------------------------------------------------------------------
# The workspace event stream
# ---------------------------------------------------------------------------


@router.get("/api/events/stream")
def event_stream(channels: str = "ui,activity", replay: bool = False, _user=RequireChat) -> StreamingResponse:
    from agent_events import BUS

    wanted = [c.strip() for c in channels.split(",") if c.strip() in ("ui", "activity")] or ["ui"]

    def events():
        subscription = BUS.subscribe(wanted, replay=replay)
        try:
            yield ": nyx events\n\n"
            while True:
                event = subscription.get(timeout=15)
                if event is None:
                    yield ": keep-alive\n\n"
                    continue
                yield _sse(event)
        finally:
            subscription.close()

    return StreamingResponse(events(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.get("/api/events/recent")
def recent_events(channel: str = "activity", limit: int = 100, _user=RequireChat) -> Dict[str, Any]:
    from agent_events import BUS

    if channel not in ("ui", "activity"):
        raise HTTPException(status_code=400, detail="channel must be ui or activity")
    return {"events": BUS.recent(channel, limit=max(1, min(limit, 200)))}


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


class ThemeRequest(BaseModel):
    theme: Dict[str, Any] = {}


@router.get("/api/ui/state")
def ui_state(_user=RequireChat) -> Dict[str, Any]:
    from ui_state import UI_STATE

    return UI_STATE.snapshot()


@router.post("/api/ui/theme")
def set_theme(body: ThemeRequest, _user=RequireChat) -> Dict[str, Any]:
    from ui_state import UI_STATE, ThemeError

    try:
        UI_STATE.update_theme(body.theme)
    except ThemeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return UI_STATE.snapshot()


@router.post("/api/ui/theme/reset")
def reset_theme(_user=RequireChat) -> Dict[str, Any]:
    from ui_state import UI_STATE

    UI_STATE.reset_theme()
    return UI_STATE.snapshot()


@router.post("/api/ui/theme/undo")
def undo_theme(_user=RequireChat) -> Dict[str, Any]:
    from ui_state import UI_STATE

    UI_STATE.undo_theme()
    return UI_STATE.snapshot()


# ---------------------------------------------------------------------------
# Skills: search, keep, export
# ---------------------------------------------------------------------------


@router.get("/api/skills/search")
def search_skills(q: str = "", _user=RequireChat) -> Dict[str, Any]:
    from skills import SKILL_STORE

    return {"query": q, "results": SKILL_STORE.search(q, limit=20)}


@router.post("/api/skills/{skill_id}/keep")
def keep_skill(skill_id: str, _user=RequireChat) -> Dict[str, Any]:
    from skills import SKILL_STORE, SkillError

    try:
        skill = SKILL_STORE.promote(skill_id)
    except SkillError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"skill": skill.as_dict()}


@router.get("/api/skills/{skill_id}/export")
def export_skill(skill_id: str, format: str = "claude", _user=RequireChat) -> Dict[str, Any]:  # noqa: A002
    from skill_export import export_formats, render_skill
    from skills import SKILL_STORE

    skill = SKILL_STORE.get(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="No such skill.")
    try:
        filename, content = render_skill(skill.as_dict(), format)
    except KeyError as error:
        raise HTTPException(status_code=400, detail=f"Unknown format. Try: {', '.join(f['id'] for f in export_formats())}") from error
    return {"format": format, "filename": filename, "content": content, "formats": export_formats()}


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ToolRunRequest(BaseModel):
    name: str
    args: Dict[str, Any] = {}


@router.get("/api/tools")
def list_tools(_user=RequireChat) -> Dict[str, Any]:
    from permissions import POLICY
    from tool_setup import registration_status
    from tools import TOOL_REGISTRY

    modes = POLICY.snapshot()["categories"]
    return {
        "tools": [
            {"name": t.name, "description": t.description, "category": t.category,
             "mode": modes.get(t.category, "allow"),
             "parameters": [{"name": p.name, "type": p.param_type, "required": p.required,
                             "description": p.description} for p in t.parameters]}
            for t in sorted(TOOL_REGISTRY.list_tools(), key=lambda t: (t.category, t.name))
        ],
        "by_category": TOOL_REGISTRY.tools_by_category(),
        "modules": registration_status(),
    }


@router.post("/api/tools/run")
def run_tool(body: ToolRunRequest, request: Request) -> Dict[str, Any]:
    """Run one tool directly (Developer panel). Owner-level: it reaches the machine."""
    import server
    from tools import TOOL_REGISTRY

    server.require_local_owner(request, request.headers.get("authorization"))
    if TOOL_REGISTRY.get_tool(body.name) is None:
        raise HTTPException(status_code=404, detail="No such tool.")
    started = time.perf_counter()
    result = TOOL_REGISTRY.call_tool(body.name, **body.args)
    return {"result": result, "ms": round((time.perf_counter() - started) * 1000)}



@router.get("/api/image-proxy")
def image_proxy(url: str, _user=RequireChat) -> Response:
    """Show a remote picture in chat without the browser contacting that site (Request H15).

    https only, public addresses only (checked on every redirect), raster images only, 8 MB at most.
    """
    import sources

    try:
        data, kind = sources.fetch_image(url)
    except sources.ImageRefused as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:  # noqa: BLE001 - network trouble is reported, not raised
        raise HTTPException(status_code=502, detail="The picture could not be loaded.") from error
    return Response(content=data, media_type=kind, headers={"Cache-Control": "private, max-age=86400",
                                                            "X-Content-Type-Options": "nosniff"})
