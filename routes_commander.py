"""HTTP routes for the Commander (commander.py): the threads panel, a project's main chat and what each chat needs.

All the owner's: threads run on the owner's keys and models, and a project's helpers can be handed the owner's files.
Included by ``server._include_routers``; every path is in the auth test lists and blocked on a hosted build.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


def _role(user: Any) -> str:
    role = getattr(user, "role", None)
    return getattr(role, "value", None) or (str(role) if role else "local")


def _call(action):
    import commander

    try:
        return action()
    except commander.CommanderError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


class DelegatorBody(BaseModel):
    chat_id: str
    project_id: str = ""


class SendBody(BaseModel):
    chat_id: str
    message: str


class TextBody(BaseModel):
    text: str


class AnswerBody(BaseModel):
    text: str = ""
    approve: Optional[bool] = None


class KnowledgeBody(BaseModel):
    title: str = ""
    text: str


class ThreadChange(BaseModel):
    resolved: Optional[bool] = None
    pinned: Optional[bool] = None
    tier: str = ""
    effort: str = ""
    sector: str = ""
    job: str = ""


class SettingsBody(BaseModel):
    divisions_in_chat: Optional[bool] = None
    auto_pick: Optional[bool] = None


@router.get("/api/commander")
def commander_board(delegator: str = "", project_id: str = "", _o=Depends(_owner)) -> Dict[str, Any]:
    """The threads panel: Pinned, Needs you, Working, Idle and Resolved, for one Commander chat or one project."""
    import commander
    import commander_pick

    return {"board": commander.board(delegator=delegator, project_id=project_id),
            "is_delegator": commander.is_delegator(delegator) if delegator else False,
            "project_id": commander.delegator_project(delegator),
            "settings": commander.settings(),
            "kinds": [{"id": t, "label": commander_pick.TIER_LABELS[t]} for t in commander_pick.TIERS],
            "efforts": list(commander_pick.EFFORTS), "sectors": list(commander_pick.SECTORS),
            "jobs": list(commander_pick.JOBS)}


@router.get("/api/commander/chat-project")
def commander_chat_project(chat_id: str = "", _o=Depends(_owner)) -> Dict[str, Any]:
    """The project a chat is in (as its main chat or a thread), so the Overview can follow it."""
    import commander

    return commander.chat_project(chat_id)


@router.get("/api/commander/attention")
def commander_attention(_o=Depends(_owner)) -> Dict[str, Any]:
    """Every chat that needs the owner or is working, so any chat can show it beside its name."""
    import commander

    rows = commander.attention()
    return {"chats": rows, "needs_you": sum(1 for r in rows if r["status"] == "needs_you")}


@router.post("/api/commander/delegators")
def commander_make(body: DelegatorBody, _o=Depends(_owner)) -> Dict[str, Any]:
    """Switch a chat to Commander: from its next message it hands work to threads."""
    import commander

    return {"delegator": _call(lambda: commander.make_delegator(body.chat_id, body.project_id))}


@router.delete("/api/commander/delegators/{chat_id}")
def commander_drop(chat_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import commander

    if not commander.drop_delegator(chat_id):
        raise HTTPException(status_code=404, detail="That chat is not a Commander.")
    return {"ok": True}


@router.post("/api/commander/projects/{project_id}/chat")
def commander_project_chat(project_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    """A project's main chat (the delegator), made the first time it is opened."""
    import commander
    import projects

    project = projects.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="No such project.")
    return {"chat_id": _call(lambda: commander.delegator_for_project(project_id, project["name"]))}


@router.get("/api/commander/projects/{project_id}/knowledge")
def commander_knowledge(project_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    """A project's knowledge base: the notes and text files its threads draw on."""
    import project_knowledge

    return {"docs": project_knowledge.list_docs(project_id)}


@router.post("/api/commander/projects/{project_id}/knowledge")
def commander_add_knowledge(project_id: str, body: KnowledgeBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import project_knowledge
    import projects

    if projects.get(project_id) is None:
        raise HTTPException(status_code=404, detail="No such project.")
    try:
        return {"doc": project_knowledge.add(project_id, body.title, body.text)}
    except project_knowledge.KnowledgeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/api/commander/projects/{project_id}/knowledge/{doc_id}")
def commander_drop_knowledge(project_id: str, doc_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    import project_knowledge

    if not project_knowledge.delete(project_id, doc_id):
        raise HTTPException(status_code=404, detail="No such document.")
    return {"ok": True}


@router.post("/api/commander/send")
def commander_send(body: SendBody, user=Depends(_owner)) -> Dict[str, Any]:
    """Send the owner's message to a Commander chat as a normal turn; its brief makes it hand the work out."""
    import commander
    from routes_live import StreamRequest, start_turn

    message = (body.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Type what you want done.")
    if not commander.is_delegator(body.chat_id):
        raise HTTPException(status_code=400, detail="That chat is not a Commander.")
    turn_id, chat_id = start_turn(StreamRequest(message=message[:8000], chat_id=body.chat_id), user)
    return {"turn_id": turn_id, "chat_id": chat_id}


@router.post("/api/commander/threads/{thread_id}/message")
def commander_message(thread_id: str, body: TextBody, user=Depends(_owner)) -> Dict[str, Any]:
    """The owner answers or adds work to one thread directly. A full thread is restarted fresh first."""
    import commander

    return {"thread": _call(lambda: commander.message_thread(thread_id, body.text, role=_role(user)))}


@router.post("/api/commander/asks/{ask_id}/answer")
def commander_answer(ask_id: str, body: AnswerBody, user=Depends(_owner)) -> Dict[str, Any]:
    """The owner answers a thread's question or approval from the main chat; it is relayed to the thread."""
    import commander

    return {"ask": _call(lambda: commander.answer_ask(ask_id, text=body.text, approve=body.approve, role=_role(user)))}


@router.put("/api/commander/threads/{thread_id}")
def commander_change(thread_id: str, body: ThreadChange, _o=Depends(_owner)) -> Dict[str, Any]:
    """Resolve, pin, or change a thread's model kind, effort or sector (a change teaches the picker)."""
    import commander

    def apply() -> Dict[str, Any]:
        thread = commander.get(thread_id)
        if thread is None:
            raise commander.CommanderError("No such thread.")
        result = commander.view(thread)
        if body.resolved is not None:
            result = commander.resolve_thread(thread_id, body.resolved)
        if body.pinned is not None:
            result = commander.pin_thread(thread_id, body.pinned)
        if body.tier or body.effort or body.sector or body.job:
            result = commander.set_pick(thread_id, tier=body.tier, effort=body.effort, sector=body.sector, job=body.job)
        return result

    return {"thread": _call(apply)}


@router.delete("/api/commander/threads/{thread_id}")
def commander_forget(thread_id: str, _o=Depends(_owner)) -> Dict[str, Any]:
    """Forget a thread's record. Its chat stays in the chat list."""
    import commander

    if not commander.delete_thread(thread_id):
        raise HTTPException(status_code=404, detail="No such thread.")
    return {"ok": True}


@router.get("/api/commander/settings")
def commander_settings(_o=Depends(_owner)) -> Dict[str, Any]:
    import commander

    return {"settings": commander.settings()}


@router.put("/api/commander/settings")
def commander_save_settings(body: SettingsBody, _o=Depends(_owner)) -> Dict[str, Any]:
    import commander

    return {"settings": commander.save_settings(**body.model_dump())}
