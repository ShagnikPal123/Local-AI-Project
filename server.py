"""FastAPI backend for Nyx Ichos — desktop and mobile access layer.

Exposes the chat service, memory, personalities, speech patterns, and the
folder reader over HTTP so the React frontend (frontend/nyx-pulse) and
future mobile clients can talk to the same local brain.

Run with:
    uvicorn server:app --reload --port 8000

Requires: pip install fastapi uvicorn
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from pathlib import Path
from typing import Any, Coroutine, Dict, List, Optional

import quiet_windows

# Before anything can start a child process: no console window may pop up in
# front of the owner and take the keyboard (Plan Null N87).
quiet_windows.install()

from pydantic import BaseModel

from chat_service import ChatService
from folder_reader import FolderReader, FolderReaderError
from personalities import (
    PersonalityNotFoundError,
    clear_custom_personality,
    get_custom_personality,
    list_personalities,
    resolve_personality,
    save_custom_personality,
)
from auth import (
    check_password_policy,
    AuthError,
    Permission,
    Role,
    UnknownAccountError,
    WeakPasswordError,
    invite_link,
)
from rag_memory import RagMemory
from server_auth import (
    AUTH_STORE,
    enforce_session_middleware,
    RequireAdmin,
    RequireChat,
    RequireGrant,
    RequireInvite,
    RequireMachineControl,
    RequireModifyAI,
    RequirePublishChanges,
    RequireReviewChanges,
    is_claimed,
)
from speech_patterns import SpeechPatternStore

try:
    from fastapi import Depends, FastAPI, Header, HTTPException, Request
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as exc:  # pragma: no cover - import guard for non-server use
    raise ImportError(
        "FastAPI is required for the server. Install it with: pip install fastapi uvicorn"
    ) from exc


app = FastAPI(
    title="Nyx Ichos API",
    version="0.1.0",
    description="Local-first multi-agent AI assistant. Created by Shagnik.",
    contact={"name": "Shagnik"},
)

def _allowed_origins() -> List[str]:
    """CORS origins for this build.

    A local build talks to itself and a dev server, so a wildcard is harmless.
    A hosted build must not accept credentialed requests from anywhere — that
    would let any page a user visits call this API with their session. Hosted
    origins come from NYX_ALLOWED_ORIGINS, and an empty list is the safe answer
    rather than a permissive default.
    """
    import os

    from deploy_mode import is_hosted

    configured = [
        o.strip()
        for o in (os.getenv("NYX_ALLOWED_ORIGINS") or "").split(",")
        if o.strip()
    ]

    if is_hosted():
        # Nothing is assumed. An empty list refuses every cross-origin call,
        # which is the safe answer when nobody has said which sites may connect.
        return configured

    # A local build also accepts a hosted UI the user has pointed at it — the
    # interface can live on the web while the brain stays on this machine. That
    # only works if this origin is named explicitly, so it is still opt-in.
    return [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:8000", "http://127.0.0.1:8000",
        "http://localhost:4173", "http://127.0.0.1:4173",
        *configured,
    ]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Speed. Responses over 1 KB are compressed (the UI bundle drops from ~310 KB to
# ~90 KB on the wire). Starlette excludes Server-Sent Events from compression,
# so streaming turns are never buffered.
from starlette.middleware.gzip import GZipMiddleware  # noqa: E402

app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)

# "Leave the site and come back": a first-party nyx_client cookie identifies this
# browser, so /api/client/state can restore its tabs, drafts and active chat.
# Pure ASGI (headers only), so streaming turns are not buffered.
try:
    from client_state import ClientCookieMiddleware

    app.add_middleware(ClientCookieMiddleware)
except Exception:  # pragma: no cover - persistence is an extra, never a startup failure
    pass


@app.middleware("http")
async def cache_static_assets(request: Request, call_next):
    """Let browsers keep hashed build files for a year.

    Vite names every asset by content hash, so a changed file is a new URL and
    "immutable" is safe. Without this each page load re-validated the bundle.
    The app shell (/) stays no-cache so a rebuild is picked up immediately.
    """
    response = await call_next(request)
    if request.url.path.startswith("/assets/") and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return response


# Deny-by-default session gate. Every /api route except the public allowlist in
# server_auth.PUBLIC_PATHS requires a session once an owner account exists, so a
# newly added endpoint is protected without anyone having to remember.
app.middleware("http")(enforce_session_middleware)


@app.middleware("http")
async def allow_anonymous_health_probe(request: Request, call_next):
    """Let any page check whether the engine is alive.

    The landing page has to answer one question - "is the engine running on this
    machine?" - from whatever origin it happens to be served from: a file:// URL
    (origin "null"), a hosted site, or a scratch port. The main CORS policy is a
    fixed localhost allowlist, so all of those were refused and the page showed
    "Engine not running" even while the engine was answering perfectly well.

    Widening the global policy would be the wrong fix: it is credentialed, so it
    guards real endpoints. Instead this exempts liveness only, and does it
    WITHOUT credentials - a wildcard origin and cookies together is exactly the
    combination that would let any page a user visits call this API as them.
    /api/health returns no personal data; the deep variant is not exempted.
    """
    response = await call_next(request)
    if request.url.path == "/api/health":
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Credentials"] = "false"
        response.headers["Vary"] = "Origin"
    return response

# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    message: Optional[str] = None
    messages: Optional[List[Dict[str, Any]]] = None
    attribute_id: Optional[str] = None
    personality_id: Optional[str] = None
    personality_text: Optional[str] = None
    use_rag: bool = True
    model: Optional[str] = None
    provider: Optional[str] = None
    workspace_files: Optional[List[str]] = None
    memories: Optional[List[str]] = None
    chat_id: Optional[str] = None
    background: bool = False


class ChatResponse(BaseModel):
    reply: str
    response: Optional[str] = None
    provider: str
    metadata: Dict[str, Any] = {}
    chat_id: str = "default"
    thought_id: Optional[str] = None

    def __init__(self, **data: Any):
        if "response" not in data and "reply" in data:
            data["response"] = data["reply"]
        super().__init__(**data)


class MemoryItem(BaseModel):
    topic: str
    content: str


class FolderAddRequest(BaseModel):
    name: str
    path: str


class LoginRequest(BaseModel):
    email: str
    password: str


class JoinRequest(BaseModel):
    invite: str
    email: str
    password: str = ""


class InviteRequest(BaseModel):
    role: str = "beta"
    email: str = ""
    # Empty means "use the address this request came in on"; see
    # admin_create_invite. A hardcoded default here pointed invites at the dev
    # server for everyone who minted one from the real app.
    base_url: str = ""


class ClaimRequest(BaseModel):
    """First-run ownership claim. Loopback-only; see claim_ownership."""

    email: str
    password: str


class GrantRequest(BaseModel):
    email: str
    role: str


class ForkChatRequest(BaseModel):
    """Branch a chat. Empty source forks whichever chat is active."""

    source: str = ""
    title: str = ""


class PersonalityRequest(BaseModel):
    """Which personality to apply. Empty id restores the default voice."""

    id: str = ""


class SpeedRequest(BaseModel):
    mode: str = "auto"


class AgentSpec(BaseModel):
    name: str
    goal: str = ""
    role: str = "worker"
    personality_id: Optional[str] = None
    emoji: str = ""
    #: Start working on the goal immediately (the UI's "Create and start").
    run: bool = False


class SpawnAgentRequest(BaseModel):
    agents: List[AgentSpec] = []


class PowerRequest(BaseModel):
    mode: str = "auto"


class WidgetRequest(BaseModel):
    type: str
    title: str = ""
    config: Dict[str, Any] = {}


class WidgetOrderRequest(BaseModel):
    order: List[str] = []


class ChangeRequest(BaseModel):
    title: str
    description: str = ""
    target: str
    content: str = ""
    previous_content: str = ""
    origin: str = "human"


class RejectRequest(BaseModel):
    reason: str = ""


class RestoreRequest(BaseModel):
    checkpoint_id: str = ""


class GrantCapabilityRequest(BaseModel):
    capability: str
    scope: str = ""
    ttl_seconds: int = 3600


class RevokeCapabilityRequest(BaseModel):
    capability: str = ""
    all: bool = False


class SkillRequest(BaseModel):
    name: str
    description: str = ""
    instructions: str
    triggers: List[str] = []


class SkillFromTextRequest(BaseModel):
    description: str


class SkillToggleRequest(BaseModel):
    enabled: bool = True


class SkillPreviewRequest(BaseModel):
    message: str = ""


class TabCreateRequest(BaseModel):
    label: str
    blocks: List[Dict[str, Any]] = []
    icon: str = "ph-squares-four"
    description: str = ""
    connectors: List[str] = []
    accent: str = ""


class TabFromTextRequest(BaseModel):
    description: str


class TabUpdateRequest(BaseModel):
    label: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    blocks: Optional[List[Dict[str, Any]]] = None
    connectors: Optional[List[str]] = None
    accent: Optional[str] = None
    #: Request H16: picture/colour/gradient background and how the text boxes look.
    background: Optional[Dict[str, Any]] = None
    theme: Optional[Dict[str, Any]] = None
    #: Words for the edit history ("Added a timer").
    request: Optional[str] = None


class TabEditRequest(BaseModel):
    instruction: str


class TabCombineRequest(BaseModel):
    first: str
    second: str
    label: str = ""


class SpeechLearnRequest(BaseModel):
    messages: List[str]


class ProviderAddRequest(BaseModel):
    """Add a provider by name plus a key.

    ``api_key`` carries no pydantic constraint on purpose. A failed field
    validation is echoed back by FastAPI with the offending ``input`` value, so
    constraining the key here would be a route that returns the key in its own
    error response. It is validated in the handler instead, where the message
    is written by hand.
    """

    name: str = ""
    api_key: str = ""
    endpoint: str = ""
    model: str = ""
    label: str = ""
    api_key_name: str = ""
    free: bool = True
    timeout_seconds: int = 30
    # Explicit opt-in for an endpoint on this machine (an Ollama-style local
    # gateway). Off by default: without it a private URL is refused.
    local: bool = False


# ---------------------------------------------------------------------------
# Shared service instances
# ---------------------------------------------------------------------------

# One ChatService per chat_id so multiple chats stay active concurrently —
# the App can fire 2+ prompts across chats without them stepping on each other.
_services: Dict[str, ChatService] = {}
_services_lock = threading.Lock()
_folder_reader: Optional[FolderReader] = None
_speech: Optional[SpeechPatternStore] = None
_rag: Optional[RagMemory] = None


_chat_store_singleton: Any = None


def _shared_chat_store() -> Any:
    """One ChatSessionStore for the whole server.

    Every ChatService used to open its own copy of chats.json and append to
    whichever chat was globally "active", so two chat tabs wrote into the same
    stored conversation and their saves could overwrite each other.
    """
    global _chat_store_singleton
    with _services_lock:
        if _chat_store_singleton is None:
            from chat_sessions import ChatSessionStore
            from memory import MemoryStore

            _chat_store_singleton = ChatSessionStore(memory_store=MemoryStore())
        return _chat_store_singleton


def _get_service(chat_id: Optional[str] = None) -> ChatService:
    key = chat_id or "default"
    store = _shared_chat_store()
    with _services_lock:
        if key not in _services:
            if key.startswith("__"):
                # Machinery (tab design, tab edits) gets its own store. Sharing the
                # user's wrote raw JSON design prompts into their real chat history.
                from chat_sessions import ChatSessionStore
                from paths import data_path

                _services[key] = ChatService(chat_store=ChatSessionStore(data_path("internal_chats.json")))
            else:
                bound = key if key != "default" and store.exists(key) else None
                _services[key] = ChatService(chat_store=store, chat_id=bound)
        return _services[key]


def _forget_service(chat_id: str) -> None:
    with _services_lock:
        _services.pop(chat_id, None)


def _tab_edit_service() -> ChatService:
    """A tool-free service dedicated to translating tab edits into JSON.

    Tab editing was borrowing an ordinary chat service, which carries the full
    ~8KB tool schema, the memory context and the personality. None of that helps
    turn "add a checklist called Weekly Goals" into a spec, and all of it is sent
    on every edit - a request the user sits and waits on. Without tools the model
    also cannot wander off into a search mid-edit.

    web_access stays ON. Disabling it looked harmless - this never needs the web -
    but it also drops every online provider from the router, and with no local
    Ollama installed that leaves nothing to answer at all: the edit came back as
    the offline courtesy text, which is not JSON, and surfaced as "the model did
    not return a usable edit".
    """
    key = "__tabedit__"
    with _services_lock:
        if key not in _services:
            from chat_sessions import ChatSessionStore
            from paths import data_path

            _services[key] = ChatService(
                enable_tools=False,
                chat_store=ChatSessionStore(data_path("internal_chats.json")),
            )
        return _services[key]


def _chat_ids() -> List[str]:
    with _services_lock:
        # The tab editor is machinery, not a conversation; listing it as a chat
        # would put it in the user's chat count and switcher.
        return [key for key in _services if not key.startswith("__")]


def _get_folder_reader() -> FolderReader:
    global _folder_reader
    if _folder_reader is None:
        _folder_reader = FolderReader()
    return _folder_reader


def _get_speech() -> SpeechPatternStore:
    global _speech
    if _speech is None:
        _speech = SpeechPatternStore()
    return _speech


def _get_rag() -> RagMemory:
    global _rag
    if _rag is None:
        _rag = RagMemory(memory=_get_service().memory)
    return _rag


# ---------------------------------------------------------------------------
# Health & status
# ---------------------------------------------------------------------------


def _build_info() -> Dict[str, Any]:
    """What this build can do, so the UI never offers a missing capability."""
    from deploy_mode import describe

    return describe()


@app.get("/api/health")
def health() -> Dict[str, Any]:
    """Return backend liveness and capability flags."""
    return {
        "status": "ok",
        # Tells the frontend whether to show a login screen. An unclaimed install
        # is a fresh local one and works without an account.
        "claimed": is_claimed(),
        "build": _build_info(),
        "capabilities": [
            "chat",
            "memory",
            "personalities",
            "speech_patterns",
            "folders",
            "rag",
            "multi_chat",
            "background_thinking",
            "math",
            "knowledge",
            "finance",
            "multi_model",
            "voice",
        ],
    }


# ---------------------------------------------------------------------------
# Engine control — the launcher's side of "one click to turn on"
# ---------------------------------------------------------------------------

#: Filled in by ``launcher.Engine`` when the engine runs under the tray launcher
#: (stop/restart callables, port, pid). Empty when started with plain uvicorn,
#: in which case there is no supervisor to hand a restart to.
ENGINE_HOOKS: Dict[str, Any] = {}

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

# Shutdown timeout for background tasks (seconds), configurable via env
SHUTDOWN_TIMEOUT = float(os.getenv("NYX_SHUTDOWN_TIMEOUT", "5"))

#: Async work Nyx itself started — the only tasks shutdown waits on. Never ``asyncio.all_tasks()``:
#: that also holds the server's own task (uvicorn's serve, TestClient's portal), which is waiting
#: for shutdown to finish, so shutdown waited on itself.
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def spawn_background(coro: Coroutine[Any, Any, Any], *, name: Optional[str] = None) -> asyncio.Task[Any]:
    """Start async work that shutdown lets finish for up to ``SHUTDOWN_TIMEOUT``, then cancels."""
    task = asyncio.get_running_loop().create_task(coro, name=name)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


def require_local_owner(
    http_request: Request,
    authorization: Optional[str] = Header(default=None),
) -> Any:
    """Owner-level actions on this machine's own engine.

    Stopping or restarting the engine, or changing whether it starts with
    Windows, belongs to whoever owns the machine. On an unclaimed install that is
    whoever sits at it, so the caller must be on loopback. Once claimed, it takes
    an admin session, so an invited tester cannot switch the owner's engine off.
    """
    from server_auth import current_user

    if is_claimed():
        user = current_user(authorization)
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in required.")
        from auth import has_permission

        if not has_permission(user.role, Permission.VIEW_ADMIN):
            raise HTTPException(status_code=403, detail="Only the owner or an admin can control the engine.")
        return user
    client_host = http_request.client.host if http_request.client else ""
    if client_host not in _LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="The engine can only be controlled from this computer.")
    return None


class AutostartRequest(BaseModel):
    enabled: bool = True


def _engine_snapshot() -> Dict[str, Any]:
    import os

    import launcher
    import paths

    return {
        "managed": bool(ENGINE_HOOKS.get("launcher")),
        "port": ENGINE_HOOKS.get("port"),
        "pid": ENGINE_HOOKS.get("pid") or os.getpid(),
        "autostart": launcher.autostart_enabled(),
        "link_registered": launcher.url_handler_registered(),
        "data_dir": str(paths.DATA_DIR),
        "log": str(launcher.log_path()),
    }


@app.get("/api/engine")
def engine_status(_user=RequireChat) -> Dict[str, Any]:
    """How this engine was started, and whether one-click start is wired up."""
    return _engine_snapshot()


def _later(action: Any, delay: float = 0.4) -> None:
    """Run ``action`` after the HTTP response has had time to leave."""
    timer = threading.Timer(delay, action)
    timer.daemon = True
    timer.start()


@app.post("/api/engine/stop")
def engine_stop(_owner=Depends(require_local_owner)) -> Dict[str, Any]:
    """Stop the engine (tray Quit, nyx://stop, the web UI's power button)."""
    stop = ENGINE_HOOKS.get("stop")
    if not callable(stop):
        raise HTTPException(
            status_code=409,
            detail="This engine was started by hand (uvicorn), not by the Nyx launcher; stop it there.",
        )
    _later(stop)
    return {"ok": True, "action": "stop"}


@app.post("/api/engine/restart")
def engine_restart(_owner=Depends(require_local_owner)) -> Dict[str, Any]:
    """Restart as a fresh process so code and configuration changes take effect."""
    restart = ENGINE_HOOKS.get("restart")
    if not callable(restart):
        raise HTTPException(
            status_code=409,
            detail="This engine was started by hand (uvicorn), not by the Nyx launcher; restart it there.",
        )
    _later(restart)
    return {"ok": True, "action": "restart"}


_ADMIN_CONSOLE: Dict[str, Any] = {}


@app.post("/api/engine/admin-console")
def engine_admin_console(_owner=Depends(require_local_owner)) -> Dict[str, Any]:
    """Start the admin access server (testers, access keys, applications, audit) and return its URL.

    It runs inside this engine on a loopback-only port, started on first use so a
    normal session does not carry a second listening server.
    """
    import os
    import socket

    port = int(os.getenv("NYX_ADMIN_PORT", "8765"))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        in_use = probe.connect_ex(("127.0.0.1", port)) == 0
    if not in_use and not _ADMIN_CONSOLE:
        try:
            import admin_server

            _ADMIN_CONSOLE["server"], _ADMIN_CONSOLE["port"] = admin_server.start_in_thread(port)
        except Exception as error:  # noqa: BLE001 - reported to the owner
            raise HTTPException(status_code=500, detail=f"The admin console could not start: {error}") from error
    return {"url": f"http://127.0.0.1:{port}/", "started": not in_use}


@app.post("/api/engine/autostart")
def engine_autostart(request: AutostartRequest, _owner=Depends(require_local_owner)) -> Dict[str, Any]:
    """Turn start-with-Windows on or off."""
    import launcher

    launcher.set_autostart(request.enabled)
    return _engine_snapshot()


@app.get("/api/status")
def status() -> Dict[str, Any]:
    """Return service, router, and connector status."""
    service = _get_service()
    from knowledge import get_knowledge
    from thought_loop import list_thoughts

    return {
        "service": service.get_status(),
        "personality": resolve_personality() and resolve_personality().get("id"),
        "folders": _get_folder_reader().list_folders(),
        "speech_patterns": _get_speech().get_patterns(),
        "knowledge": get_knowledge().status(),
        "active_chats": _chat_ids(),
        "background_thoughts": list_thoughts(),
    }


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest, _user=RequireChat) -> ChatResponse:
    """Send a message and receive a reply from the routed provider.

    Each chat_id gets its own ChatService, so many chats can be active at once.
    Set background=true to acknowledge immediately and finish the research in a
    background thought; poll /api/think/{thought_id} for the final answer.
    """
    user_text = ""
    if request.message and request.message.strip():
        user_text = request.message.strip()
    elif request.messages:
        # Find last user message in the list
        for m in reversed(request.messages):
            if m.get("role") == "user" and m.get("content", "").strip():
                user_text = m["content"].strip()
                break

    if not user_text:
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    chat_id = request.chat_id or "default"
    service = _get_service(chat_id)
    personality = resolve_personality(request.personality_id, request.personality_text)
    if personality:
        service.set_personality(personality)

    rag_context = ""
    if request.use_rag:
        rag_context = _get_rag().build_context_prompt(user_text)

    message = f"{rag_context}\n\n{user_text}" if rag_context else user_text

    if request.background:
        from thought_loop import start_background_thought

        thinker = start_background_thought(service, message, attribute_id=request.attribute_id)
        return ChatResponse(
            reply=(
                "I'm working on this in the background — researching and studying now. "
                f"Thought ID: {thinker.thought.thought_id}"
            ),
            provider="background",
            metadata={"rag": bool(rag_context), "background": True},
            chat_id=chat_id,
            thought_id=thinker.thought.thought_id,
        )

    reply, provider = service.chat(message, attribute_id=request.attribute_id)
    return ChatResponse(
        reply=reply,
        response=reply,
        provider=provider,
        metadata={"rag": bool(rag_context)},
        chat_id=chat_id,
    )


# ---------------------------------------------------------------------------
# Concurrent chats & background thoughts
# ---------------------------------------------------------------------------


@app.get("/api/chats")
def list_chats() -> Dict[str, Any]:
    """List all concurrently active chat services."""
    service = _get_service()
    return {
        "chats": _chat_ids(),
        "count": len(_chat_ids()),
        # The stored sessions, which carry titles and branch links. _chat_ids()
        # only knows about services currently cached in memory.
        "sessions": service.chat_store.list(),
        "active": service.chat_store.data.get("active_chat", ""),
    }


@app.post("/api/chats/fork")
def fork_chat(request: ForkChatRequest, _user=RequireChat) -> Dict[str, Any]:
    """Branch the conversation into a linked chat.

    Opening a blank chat loses the thread; continuing in the same one buries it.
    A fork keeps both: the branch starts knowing where it came from, and each
    side records the other, so several chats can work the same problem and still
    be related afterwards.
    """
    service = _get_service(request.source or "default")
    try:
        branch = service.chat_store.fork(
            source_id=request.source or None,
            title=(request.title or "").strip() or None,
        )
    except RuntimeError as error:
        # Raised when the source is missing, and when the chat limit is reached.
        raise HTTPException(status_code=400, detail=str(error)) from error

    return {"chat": branch, "sessions": service.chat_store.list()}


@app.post("/api/think")
def start_thought(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Start a background thought; returns an id to poll for the final answer."""
    from thought_loop import start_background_thought

    task = (payload.get("task") or "").strip()
    if not task:
        raise HTTPException(status_code=400, detail="Task cannot be empty.")
    chat_id = payload.get("chat_id") or "default"
    thinker = start_background_thought(
        _get_service(chat_id),
        task,
        attribute_id=payload.get("attribute_id"),
    )
    return {
        "thought_id": thinker.thought.thought_id,
        "chat_id": chat_id,
        "status": thinker.status(),
    }


@app.get("/api/think")
def list_background_thoughts() -> Dict[str, Any]:
    """List all background thoughts (for live App/Web status)."""
    from thought_loop import list_thoughts

    return {"thoughts": list_thoughts()}


@app.get("/api/think/{thought_id}")
def thought_status(thought_id: str) -> Dict[str, Any]:
    """Poll a background thought's live status and final result."""
    from thought_loop import get_thought

    thinker = get_thought(thought_id)
    if thinker is None:
        raise HTTPException(status_code=404, detail=f"Unknown thought: {thought_id}")
    return thinker.status()


# ---------------------------------------------------------------------------
# Math & permanent general knowledge
# ---------------------------------------------------------------------------


@app.post("/api/math")
def math_endpoint(payload: Dict[str, str]) -> Dict[str, Any]:
    """Evaluate a math expression or solve an equation in x."""
    from math_engine import MathError, evaluate, solve

    expression = (payload.get("expression") or "").strip()
    if not expression:
        raise HTTPException(status_code=400, detail="Expression cannot be empty.")
    try:
        result = evaluate(expression)
        return {"expression": expression, "result": result, "kind": "expression"}
    except MathError:
        pass
    try:
        solved = solve(expression)
        return {**solved, "kind": "equation"}
    except MathError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/knowledge")
def knowledge_search(q: str, limit: int = 5) -> Dict[str, Any]:
    """Search the permanent general knowledge base."""
    from knowledge import get_knowledge

    return {"query": q, "results": get_knowledge().search(q, limit=limit)}


# ---------------------------------------------------------------------------
# Models: list local (Ollama) and online providers, switch the active one
# ---------------------------------------------------------------------------


_SHARED_OLLAMA: Any = None


def _shared_ollama() -> Any:
    """One shared Ollama probe for the model listings.

    A fresh OllamaProvider has an empty availability cache, so every call paid
    the full loopback timeout (~0.5 s) whenever Ollama is not installed — on
    every Models tab open and every provider picker.
    """
    global _SHARED_OLLAMA
    if _SHARED_OLLAMA is None:
        from providers.ollama_provider import OllamaProvider

        _SHARED_OLLAMA = OllamaProvider()
    return _SHARED_OLLAMA


@app.get("/api/models")
def list_models() -> Dict[str, Any]:
    """List local Ollama models and configured online providers."""
    from config import SETTINGS
    from providers.anthropic_provider import AnthropicProvider
    from providers.deepseek_provider import DeepSeekProvider
    from providers.gemini_provider import GeminiProvider
    from providers.groq_provider import GroqProvider
    from providers.kimi_provider import KimiProvider
    from providers.nvidia_provider import NvidiaProvider
    from providers.ollama_provider import OllamaProvider
    from providers.openai_provider import OpenAIProvider
    from providers.perplexity_provider import PerplexityProvider
    from providers.qwen_provider import QwenProvider

    local = _shared_ollama().list_models()
    online = []
    for name, provider in (
        ("claude", AnthropicProvider()),
        ("openai", OpenAIProvider()),
        ("gemini", GeminiProvider()),
        ("kimi", KimiProvider()),
        ("deepseek", DeepSeekProvider()),
        ("groq", GroqProvider()),
        ("nvidia", NvidiaProvider()),
        ("perplexity", PerplexityProvider()),
        ("qwen", QwenProvider()),
    ):
        online.append({"name": name, "configured": provider.is_available()})
    return {
        "local": local,
        "local_active": SETTINGS.ollama_model,
        "online": online,
        "preferred_online": SETTINGS.preferred_online_provider,
    }


@app.get("/api/models/active")
def active_model(_user=RequireChat) -> Dict[str, Any]:
    """Which provider answers by default right now — the chat dropdown syncs to this."""
    from config import SETTINGS

    name = SETTINGS.preferred_online_provider
    model = getattr(SETTINGS, f"{name}_model", "") if name else ""
    return {"provider": name, "model": model or "", "local_model": SETTINGS.ollama_model}


@app.post("/api/models/switch")
def switch_model(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Switch the active local model or the preferred online provider."""
    from config import SETTINGS
    from providers.ollama_provider import OllamaProvider

    target = (payload.get("model") or payload.get("provider") or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="Model name cannot be empty.")

    # Any provider the router knows, custom ones included. When it cannot answer,
    # say why instead of switching to something that will be skipped (Request G9:
    # the dropdown "didn't switch" while asking in chat did).
    router = _get_service(None).router
    name = target.lower()
    if name == "anthropic":
        name = "claude"
    if name in getattr(router, "providers", {}) and name != "ollama":
        reason = router.unavailable_reason(name, explicit=True) if hasattr(router, "unavailable_reason") else None
        if reason:
            raise HTTPException(status_code=409, detail=f"Can't switch to {name}: {reason}.")
        SETTINGS.preferred_online_provider = name
        try:
            import model_choice

            # Survives restarts (H6) and counts as the owner allowing a billable key (H11).
            model_choice.remember(name)
        except Exception:  # pragma: no cover
            pass
        return {"kind": "online", "model": name, "preferred": SETTINGS.preferred_online_provider}

    local = _shared_ollama().list_models()
    if name == "ollama":
        # The dropdown's "ollama" means "answer on this PC": keep the local model in use, or the first installed one.
        # It used to fall through to the name match below, where no model name contains "ollama", so it was a 404.
        if not local:
            raise HTTPException(status_code=409, detail="Ollama has no models installed yet — add one in Keys & Models.")
        chosen = SETTINGS.ollama_model if SETTINGS.ollama_model in local else local[0]
        SETTINGS.ollama_model = chosen
        return {"kind": "local", "model": chosen, "active": SETTINGS.ollama_model}
    match = next((m for m in local if m == target or target in m), None)
    if match:
        SETTINGS.ollama_model = match
        return {"kind": "local", "model": match, "active": SETTINGS.ollama_model}

    raise HTTPException(status_code=404, detail=f"No local model or provider named '{target}'.")


# ---------------------------------------------------------------------------
# Voice: talk back, listen, voice selection, and voice-ID scan (App startup)
# ---------------------------------------------------------------------------


@app.get("/api/voice/status")
def voice_status() -> Dict[str, Any]:
    """Return voice enrollment status, active voice, mic, and installed voices.

    The App can use this on startup to decide whether to ask for a voice scan.
    """
    import voice

    return voice.voice_status()


@app.get("/api/voice/voices")
def voice_voices() -> Dict[str, Any]:
    """List installed text-to-speech voices."""
    import voice

    return {"voices": voice.list_voices(), "active": voice.get_voice()}


@app.post("/api/voice/speak")
def voice_speak(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Speak text aloud through the selected (or requested) voice."""
    import voice

    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text cannot be empty.")
    return {"message": voice.speak(text, voice=payload.get("voice"))}


@app.post("/api/voice/listen")
def voice_listen(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Listen to the microphone and return recognized speech (offline STT)."""
    import voice

    timeout = int(payload.get("timeout", 10))
    text = voice.listen(timeout=timeout)
    return {"text": text}


@app.post("/api/voice/set")
def voice_set(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Select which installed voice speaks."""
    import voice

    name = (payload.get("voice") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Voice name cannot be empty.")
    return {"message": voice.set_voice(name)}


@app.post("/api/voice/scan")
def voice_scan(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Voice ID: enroll (mode='enroll'), verify (mode='verify'), or status."""
    import voice

    mode = payload.get("mode", "status")
    if mode == "enroll":
        return voice.enroll_voice(label=payload.get("label", "user"), duration=float(payload.get("duration", 3.0)))
    if mode == "verify":
        return voice.verify_voice(duration=float(payload.get("duration", 3.0)))
    return voice.voice_status()


# ---------------------------------------------------------------------------
# Finance tab: live market data + permanent financial knowledge + advice
# ---------------------------------------------------------------------------


@app.get("/api/finance/quote")
def finance_quote(symbols: str) -> Dict[str, Any]:
    """Fetch live quotes for comma-separated symbols."""
    from connectors import CONNECTOR_REGISTRY

    result = CONNECTOR_REGISTRY.execute("finance", "quote", symbols=symbols)
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "quote failed"))
    return result


@app.get("/api/finance/history")
def finance_history(symbol: str, range: str = "3mo") -> Dict[str, Any]:
    """Fetch daily price history for a symbol."""
    from connectors import CONNECTOR_REGISTRY

    result = CONNECTOR_REGISTRY.execute("finance", "history", symbol=symbol, range=range)
    if not result.get("success"):
        raise HTTPException(status_code=502, detail=result.get("error", "history failed"))
    return result


@app.get("/api/finance/status")
def finance_status() -> Dict[str, Any]:
    """Report US market open/close and connector health."""
    from connectors import CONNECTOR_REGISTRY

    result = CONNECTOR_REGISTRY.execute("finance", "market_status")
    health = CONNECTOR_REGISTRY.health_status().get("finance", {})
    return {"market": result, "connector": health}


@app.get("/api/finance/knowledge")
def finance_knowledge(q: str, limit: int = 5) -> Dict[str, Any]:
    """Search the permanent financial literacy knowledge base."""
    from finance import get_finance_knowledge

    return {"query": q, "results": get_finance_knowledge().search(q, limit=limit)}


@app.post("/api/finance/advice")
def finance_advice(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Get grounded financial guidance from the finance advisor mode."""
    from finance import advisor_context, finance_system_prompt

    question = (payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    chat_id = payload.get("chat_id") or "default"
    service = _get_service(chat_id)
    context = advisor_context(question, memory=service.memory)
    prompt = f"{finance_system_prompt()}\n\n{context}\n\n{question}" if context else question
    reply, provider = service.chat(prompt, attribute_id="finance")
    return {"reply": reply, "provider": provider, "chat_id": chat_id}


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


@app.get("/api/memory")
def list_memory() -> Dict[str, Any]:
    """Return important memories and preferences."""
    service = _get_service()
    return {
        "important": service.memory.get_important(),
        "preferences": service.memory.data.get("preferences", {}),
    }


@app.post("/api/memory/important")
def add_important(item: MemoryItem) -> Dict[str, str]:
    """Store an important memory."""
    service = _get_service()
    service.remember_important(item.topic, item.content)
    _get_rag().mark_dirty()
    return {"status": "stored", "topic": item.topic}


@app.delete("/api/memory/important/{topic}")
def remove_important(topic: str) -> Dict[str, Any]:
    """Remove an important memory by topic."""
    service = _get_service()
    removed = service.remove_important_memory(topic)
    _get_rag().mark_dirty()
    return {"removed": removed}


@app.get("/api/memory/rag")
def rag_search(q: str, limit: int = 5) -> Dict[str, Any]:
    """Retrieve the most relevant memory entries for a query."""
    results = _get_rag().search(q, limit=limit)
    return {"query": q, "results": results}


# ---------------------------------------------------------------------------
# Personalities
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Admin change review (ROADMAP AA7-AA11)
#
# Every modification to the app becomes a reviewable record before it can reach
# anyone else. Reviewing and publishing are separate permissions, and only the
# owner may touch the base AI.
# ---------------------------------------------------------------------------


@app.get("/api/changes")
def list_changes(_user=RequireReviewChanges) -> Dict[str, Any]:
    """Every proposed and published change, newest first."""
    from change_review import CHANGE_LOG

    return {"changes": CHANGE_LOG.list_changes(), "summary": CHANGE_LOG.summary()}


@app.post("/api/changes")
def propose_change(request: ChangeRequest, user=RequireReviewChanges) -> Dict[str, Any]:
    """Record a proposed change. Always starts as a draft."""
    from change_review import CHANGE_LOG, ChangeError, ChangeOrigin

    # Editing the base AI is a different act from editing a tab, and only the
    # owner may do it.
    if request.target.strip().lower() == "base_ai":
        try:
            AUTH_STORE.require_user(user, Permission.MODIFY_BASE_AI)
        except AuthError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    try:
        change = CHANGE_LOG.propose(
            title=request.title,
            description=request.description,
            author=user.email,
            target=request.target,
            content=request.content,
            previous_content=request.previous_content,
            origin=ChangeOrigin(request.origin),
        )
    except (ChangeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    from event_log import info

    info(f"Change proposed: {change.title}", source="admin")
    return {"change": change.as_dict()}


@app.post("/api/changes/{change_id}/review")
def review_change(change_id: str, user=RequireReviewChanges) -> Dict[str, Any]:
    """Ask the AI to review a change, then move it into review.

    The review is attached as notes; it never decides the outcome. A reviewer
    prompted to approve would approve, which would defeat the point.
    """
    from change_review import CHANGE_LOG, ChangeError, ChangeStatus, build_review_prompt

    change = CHANGE_LOG.get(change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="No such change.")

    try:
        service = _get_service("__review__")
        review, _provider = service.chat(build_review_prompt(change))
    except Exception as error:  # pragma: no cover - provider dependent
        review = f"AI review unavailable: {error}"

    CHANGE_LOG.attach_review(change_id, review, reviewer=f"ai (requested by {user.email})")
    if change.status is ChangeStatus.DRAFT:
        try:
            CHANGE_LOG.submit_for_review(change_id)
        except ChangeError:
            pass
    return {"change": CHANGE_LOG.get(change_id).as_dict()}


@app.post("/api/changes/{change_id}/approve")
def approve_change(change_id: str, user=RequireReviewChanges) -> Dict[str, Any]:
    from change_review import CHANGE_LOG, ChangeError

    try:
        change = CHANGE_LOG.approve(change_id, reviewer=user.email)
    except ChangeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"change": change.as_dict()}


@app.post("/api/changes/{change_id}/reject")
def reject_change(change_id: str, request: RejectRequest, user=RequireReviewChanges) -> Dict[str, Any]:
    from change_review import CHANGE_LOG, ChangeError

    try:
        change = CHANGE_LOG.reject(change_id, reviewer=user.email, reason=request.reason)
    except ChangeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"change": change.as_dict()}


@app.post("/api/changes/{change_id}/publish")
def publish_change(change_id: str, user=RequirePublishChanges) -> Dict[str, Any]:
    """Publish an approved change and apply it to the overlay.

    The change is applied to the overlay layer, never to the shipped modules, and
    a checkpoint is taken first. If applying fails the publish is refused rather
    than leaving the record and the running app disagreeing about reality.
    """
    from change_review import CHANGE_LOG, ChangeError
    from overlay import OVERLAY, OverlayError

    change = CHANGE_LOG.get(change_id)
    if change is None:
        raise HTTPException(status_code=404, detail="No such change.")

    try:
        entry = OVERLAY.apply(
            target=change.target,
            value=change.content,
            change_id=change_id,
            applied_by=user.email,
        )
    except OverlayError as error:
        raise HTTPException(
            status_code=400, detail=f"Could not apply the change: {error}"
        ) from error

    # Self-revival (F3): verify the app still works with the change applied. A
    # bad change is undone inside the same request that made it, rather than
    # being discovered later by a confused user.
    from health_check import run_health_check

    health = run_health_check()
    if not health["healthy"]:
        OVERLAY.revert(change.target)
        from event_log import error as log_error

        log_error(
            f"Auto-reverted {change.title}: health check failed "
            f"({', '.join(health['failed'])})",
            source="admin",
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "The change was applied, broke a health check, and has been "
                    "automatically reverted. Nothing was published."
                ),
                "failed": health["failed"],
                "health": health["results"],
            },
        )

    try:
        published = CHANGE_LOG.publish(change_id, publisher=user.email)
    except ChangeError as error:
        # The overlay accepted it but the record refused. Undo the application so
        # the two never disagree about what is live.
        OVERLAY.revert(change.target)
        raise HTTPException(status_code=400, detail=str(error)) from error

    from event_log import ok

    ok(f"Change published and applied: {published.title}", source="admin")
    return {
        "change": published.as_dict(),
        "applied": entry.as_dict(),
        "health": health,
    }


@app.post("/api/changes/{change_id}/rollback")
def rollback_change(change_id: str, user=RequirePublishChanges) -> Dict[str, Any]:
    """Revert a published change, removing its overlay entry."""
    from change_review import CHANGE_LOG, ChangeError
    from overlay import OVERLAY

    try:
        change = CHANGE_LOG.rollback(change_id, actor=user.email)
    except ChangeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    reverted = OVERLAY.revert(change.target)

    from event_log import warn

    warn(f"Change rolled back: {change.title}", source="admin")
    return {"change": change.as_dict(), "overlay_reverted": reverted}


@app.get("/api/health/deep")
def deep_health(_user=RequireChat) -> Dict[str, Any]:
    """Run the full health check on demand.

    Distinct from `/api/health`, which is a cheap liveness ping the login screen
    polls. This one actually exercises the subsystems.
    """
    from health_check import run_health_check

    return run_health_check()


@app.get("/api/overlay")
def get_overlay(_user=RequireReviewChanges) -> Dict[str, Any]:
    """What is currently layered on top of the shipped app, plus checkpoints."""
    from overlay import OVERLAY

    return OVERLAY.snapshot()


@app.post("/api/overlay/restore")
def restore_overlay(request: RestoreRequest, user=RequirePublishChanges) -> Dict[str, Any]:
    """Roll the whole overlay back to a checkpoint (self code revival, F3)."""
    from overlay import OVERLAY, OverlayError

    try:
        result = (
            OVERLAY.restore(request.checkpoint_id)
            if request.checkpoint_id
            else OVERLAY.restore_latest()
        )
    except OverlayError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    from event_log import warn

    warn(f"Overlay restored to {result['restored']} by {user.email}", source="admin")
    return result


# ---------------------------------------------------------------------------
# Machine control (ROADMAP V1-V8)
#
# Owner-only, and absent entirely from a hosted build — see deploy_mode.py.
# ---------------------------------------------------------------------------


@app.get("/api/machine")
def machine_status(_user=RequireMachineControl) -> Dict[str, Any]:
    """Active grants, the audit trail, and what can never be reached."""
    from machine_control import MACHINE

    return MACHINE.snapshot()


@app.post("/api/machine/grant")
def grant_capability(request: GrantCapabilityRequest, user=RequireMachineControl) -> Dict[str, Any]:
    """Grant one capability, optionally scoped, always expiring."""
    from machine_control import MACHINE, Capability, MachineControlError

    try:
        capability = Capability(request.capability.strip().lower())
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail=f"Unknown capability: {request.capability}"
        ) from error
    try:
        grant = MACHINE.grant(
            capability,
            scope=request.scope,
            granted_by=user.email,
            ttl_seconds=request.ttl_seconds,
        )
    except MachineControlError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"grant": grant.as_dict(), "machine": MACHINE.snapshot()}


@app.post("/api/machine/revoke")
def revoke_capability(request: RevokeCapabilityRequest, user=RequireMachineControl) -> Dict[str, Any]:
    """Revoke one capability, or everything (the kill switch)."""
    from machine_control import MACHINE, Capability

    if request.all:
        dropped = MACHINE.revoke_all(actor=user.email)
        return {"revoked": dropped, "machine": MACHINE.snapshot()}

    try:
        capability = Capability(request.capability.strip().lower())
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail=f"Unknown capability: {request.capability}"
        ) from error
    return {
        "revoked": 1 if MACHINE.revoke(capability, actor=user.email) else 0,
        "machine": MACHINE.snapshot(),
    }


# ---------------------------------------------------------------------------
# Dynamic tabs (ROADMAP CC1-CC12)
#
# A tab is a declarative spec the client renders. Nothing here is executed.
# ---------------------------------------------------------------------------

# Tabs that ship with the app, for fuzzy search to match against.
SHIPPED_TABS = [
    {"id": "strands", "label": "Strands"},
    {"id": "chat", "label": "Chat"},
    {"id": "dashboard", "label": "Dashboard"},
    {"id": "work", "label": "Sessions and Memory"},
    {"id": "models", "label": "Models"},
    {"id": "agents", "label": "Agents"},
    {"id": "connectors", "label": "Connectors"},
    {"id": "store", "label": "Add capability skills"},
    {"id": "power", "label": "Power"},
    {"id": "admin", "label": "Admin changes"},
    {"id": "settings", "label": "Settings"},
]


@app.get("/api/tabs")
def list_dynamic_tabs(_user=RequireChat) -> Dict[str, Any]:
    """The user's own tabs, plus the shipped set for reference."""
    from dynamic_tabs import ALLOWED_CONNECTORS, BlockType, TAB_STORE

    return {
        "tabs": TAB_STORE.list_tabs(),
        "shipped": SHIPPED_TABS,
        "block_types": [b.value for b in BlockType],
        "allowed_connectors": sorted(ALLOWED_CONNECTORS),
    }


@app.get("/api/tabs/search")
def search_tabs(q: str = "", _user=RequireChat) -> Dict[str, Any]:
    """Fuzzy tab search (CC2, CC6).

    The user types what they call it, not what it is called. When nothing
    matches, the reply says a new tab could be created instead.
    """
    from dynamic_tabs import TAB_STORE

    results = TAB_STORE.find(q, shipped=SHIPPED_TABS)
    return {
        "query": q,
        "results": results,
        "offer_create": not results and bool(q.strip()),
    }


@app.post("/api/tabs")
def create_tab(request: TabCreateRequest, user=RequireChat) -> Dict[str, Any]:
    """Create a tab from an explicit spec."""
    from dynamic_tabs import TAB_STORE, TabSpecError, build_spec

    try:
        spec = build_spec(
            label=request.label,
            blocks=request.blocks,
            icon=request.icon,
            description=request.description,
            connectors=request.connectors,
            accent=request.accent,
            author=getattr(user, "email", ""),
        )
    except TabSpecError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    TAB_STORE.create(spec)

    from event_log import info

    info(f"Tab created: {spec.label}", source="tabs")
    return {"tab": spec.as_dict()}


@app.post("/api/tabs/from-description")
def create_tab_from_description(request: TabFromTextRequest, user=RequireChat) -> Dict[str, Any]:
    """Describe a tab in words; the agent designs it (CC4, CC5)."""
    from dynamic_tabs import (
        TAB_STORE,
        TabSpecError,
        build_spec,
        build_tab_prompt,
        parse_tab_reply,
    )

    if not request.description.strip():
        raise HTTPException(status_code=400, detail="Describe what the tab is for.")

    try:
        service = _get_service("__tabs__")
        prompt = build_tab_prompt(request.description)
        try:
            import design_sense  # decide the look for this request, not from habit (N88)

            prompt += "\n\n" + design_sense.brief_for_prompt(request.description)
        except Exception:  # pragma: no cover - the brief is an improvement, not a requirement
            pass
        reply, _provider = service.chat(prompt)
        data = parse_tab_reply(reply)
    except TabSpecError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:  # pragma: no cover - provider dependent
        raise HTTPException(status_code=503, detail=f"Model unavailable: {error}") from error

    try:
        spec = build_spec(
            label=data.get("label", ""),
            blocks=data.get("blocks", []),
            icon=data.get("icon", "ph-squares-four"),
            description=data.get("description", request.description[:200]),
            connectors=data.get("connectors", []),
            author=getattr(user, "email", ""),
            source="agent",
        )
    except TabSpecError as error:
        raise HTTPException(
            status_code=422, detail=f"The design was not usable: {error}"
        ) from error

    TAB_STORE.create(spec)

    from event_log import ok

    ok(f"Tab designed from description: {spec.label}", source="tabs")
    return {"tab": spec.as_dict()}


@app.patch("/api/tabs/{tab_id}")
def update_tab(tab_id: str, request: TabUpdateRequest, _user=RequireChat) -> Dict[str, Any]:
    """Edit a tab (CC9, CC10). Every field is re-validated."""
    from dynamic_tabs import TAB_STORE, TabSpecError

    try:
        spec = TAB_STORE.update(
            tab_id,
            request=request.request or "",
            label=request.label,
            icon=request.icon,
            description=request.description,
            blocks=request.blocks,
            connectors=request.connectors,
            accent=request.accent,
            background=request.background,
            theme=request.theme,
        )
    except TabSpecError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"tab": spec.as_dict()}


@app.post("/api/tabs/{tab_id}/edit")
def edit_tab_conversationally(tab_id: str, request: TabEditRequest, _user=RequireChat) -> Dict[str, Any]:
    """Change a tab by describing the change (CC9).

    Unambiguous edits — colour, rename, add or remove a block — are read locally,
    so they are instant and work offline. Anything else goes to the model, whose
    reply is validated exactly like a hand-written edit.
    """
    from dynamic_tabs import TAB_STORE, TabSpecError
    from tab_editor import build_edit_prompt, interpret_locally, parse_edit_reply

    spec = TAB_STORE.get(tab_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="No such tab.")
    if not request.instruction.strip():
        raise HTTPException(status_code=400, detail="Say what you want changed.")

    changes = interpret_locally(spec, request.instruction)
    interpreted_by = "local"

    if changes is None:
        interpreted_by = "model"
        try:
            service = _tab_edit_service()
            reply, _provider = service.chat(build_edit_prompt(spec, request.instruction))
            changes = parse_edit_reply(reply)
        except TabSpecError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except Exception as error:  # pragma: no cover - provider dependent
            raise HTTPException(status_code=503, detail=f"Model unavailable: {error}") from error

    try:
        updated = TAB_STORE.update(
            tab_id,
            request=request.instruction,
            edit_source=interpreted_by,
            **changes,
        )
    except TabSpecError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    from event_log import info

    # applied says whether anything actually changed. An instruction can be
    # understood and still be a no-op ("make it green" when it already is), and
    # reporting that as success is what made editing feel like it did nothing.
    applied = updated.edits[-1].summary if updated.edits else ""
    info(f"Tab edited ({interpreted_by}): {updated.label}", source="tabs")
    return {
        "tab": updated.as_dict(),
        "changes": changes,
        "interpreted_by": interpreted_by,
        "applied": bool(applied),
        "summary": applied or "Nothing changed - the tab already looked like that.",
        "edits": [e.as_dict() for e in updated.edits],
    }


@app.post("/api/tabs/combine")
def combine_tabs(request: TabCombineRequest, _user=RequireChat) -> Dict[str, Any]:
    """Merge two tabs into one (CC11). The originals are left alone."""
    from dynamic_tabs import TAB_STORE, TabSpecError

    try:
        spec = TAB_STORE.combine(request.first, request.second, request.label)
    except TabSpecError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"tab": spec.as_dict()}


@app.delete("/api/tabs/{tab_id}")
def delete_tab(tab_id: str, _user=RequireChat) -> Dict[str, Any]:
    from dynamic_tabs import TAB_STORE

    if not TAB_STORE.delete(tab_id):
        raise HTTPException(status_code=404, detail="No such tab.")
    return {"tabs": TAB_STORE.list_tabs()}


# ---------------------------------------------------------------------------
# Skills (ROADMAP U1-U5)
# ---------------------------------------------------------------------------


@app.get("/api/skills")
def list_skills(_user=RequireChat) -> Dict[str, Any]:
    """The skill library, built-ins first."""
    from skills import SKILL_STORE

    skills = SKILL_STORE.list_skills()
    return {
        "skills": skills,
        "enabled": sum(1 for s in skills if s["enabled"]),
        "total": len(skills),
    }


@app.post("/api/skills/preview")
def preview_skills(request: SkillPreviewRequest, _user=RequireChat) -> Dict[str, Any]:
    """Which skills a given message would attach, and why.

    Useful for understanding why an answer came out the way it did — automatic
    behaviour is only trustworthy if it can be inspected.
    """
    from skills import SKILL_STORE

    selected = SKILL_STORE.select_for(request.message)
    return {
        "message": request.message,
        "selected": [
            {"id": s.skill_id, "name": s.name, "hits": s.match_score(request.message)}
            for s in selected
        ],
    }


@app.post("/api/skills")
def add_skill(request: SkillRequest, user=RequireChat) -> Dict[str, Any]:
    """Add a skill directly, with instructions already written."""
    from skills import SKILL_STORE, SkillError

    try:
        skill = SKILL_STORE.add(
            name=request.name,
            description=request.description,
            instructions=request.instructions,
            triggers=request.triggers,
            source="manual",
            author=getattr(user, "email", ""),
        )
    except SkillError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    from event_log import info

    info(f"Skill added: {skill.name}", source="skills")
    return {"skill": skill.as_dict()}


@app.post("/api/skills/from-conversation")
def create_skill_from_description(request: SkillFromTextRequest, user=RequireChat) -> Dict[str, Any]:
    """Describe a capability in words; the agent writes the skill (U2)."""
    from skills import SKILL_STORE, SkillError, build_skill_prompt, parse_skill_reply

    if not request.description.strip():
        raise HTTPException(status_code=400, detail="Describe what the skill should do.")

    try:
        service = _get_service("__skills__")
        reply, _provider = service.chat(build_skill_prompt(request.description))
        parsed = parse_skill_reply(reply)
    except SkillError as error:
        raise HTTPException(
            status_code=422,
            detail=f"Could not turn that into a skill: {error}",
        ) from error
    except Exception as error:  # pragma: no cover - provider dependent
        raise HTTPException(status_code=503, detail=f"Model unavailable: {error}") from error

    try:
        skill = SKILL_STORE.add(
            name=parsed["name"],
            description=request.description.strip()[:200],
            instructions=parsed["instructions"],
            triggers=parsed["triggers"],
            source="conversation",
            author=getattr(user, "email", ""),
        )
    except SkillError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    from event_log import ok

    ok(f"Skill created from description: {skill.name}", source="skills")
    return {"skill": skill.as_dict()}


@app.post("/api/skills/{skill_id}/enabled")
def set_skill_enabled(skill_id: str, request: SkillToggleRequest, _user=RequireChat) -> Dict[str, Any]:
    from skills import SKILL_STORE, SkillError

    try:
        skill = SKILL_STORE.set_enabled(skill_id, request.enabled)
    except SkillError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return {"skill": skill.as_dict()}


@app.delete("/api/skills/{skill_id}")
def remove_skill(skill_id: str, _user=RequireChat) -> Dict[str, Any]:
    from skills import SKILL_STORE, SkillError

    try:
        if not SKILL_STORE.remove(skill_id):
            raise HTTPException(status_code=404, detail="No such skill.")
    except SkillError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"skills": SKILL_STORE.list_skills()}


@app.get("/api/events")
def get_events(limit: int = 60, _user=RequireChat) -> Dict[str, Any]:
    """Recent real system activity for the HUD log."""
    from event_log import EVENT_LOG

    return EVENT_LOG.snapshot(limit=max(1, min(limit, 200)))


@app.get("/api/widgets")
def get_widgets(_user=RequireChat) -> Dict[str, Any]:
    """The user's HUD layout, plus the widget types they can add."""
    from widgets import WIDGET_STORE

    return {
        "widgets": WIDGET_STORE.list_widgets(),
        "available": WIDGET_STORE.available_types(),
    }


@app.post("/api/widgets")
def add_widget(request: WidgetRequest, _user=RequireChat) -> Dict[str, Any]:
    """Add a widget to the HUD."""
    from widgets import WIDGET_STORE, WidgetType

    try:
        widget_type = WidgetType(request.type.strip().lower())
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail=f"Unknown widget type: {request.type}"
        ) from error
    try:
        widget = WIDGET_STORE.add(widget_type, request.title, request.config)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    from event_log import info

    info(f"Widget added: {widget.type.value}", source="hud")
    return {"widget": widget.as_dict(), "widgets": WIDGET_STORE.list_widgets()}


@app.delete("/api/widgets/{widget_id}")
def remove_widget(widget_id: str, _user=RequireChat) -> Dict[str, Any]:
    from widgets import WIDGET_STORE

    if not WIDGET_STORE.remove(widget_id):
        raise HTTPException(status_code=404, detail="No such widget.")
    return {"widgets": WIDGET_STORE.list_widgets()}


@app.post("/api/widgets/order")
def reorder_widgets(request: WidgetOrderRequest, _user=RequireChat) -> Dict[str, Any]:
    from widgets import WIDGET_STORE

    return {"widgets": WIDGET_STORE.reorder(request.order)}


@app.post("/api/widgets/reset")
def reset_widgets(_user=RequireChat) -> Dict[str, Any]:
    from widgets import WIDGET_STORE

    return {"widgets": WIDGET_STORE.reset()}


@app.get("/api/strands")
def get_strands(_user=RequireChat) -> Dict[str, Any]:
    """The live strand graph for the HUD tab, built from real system state."""
    from agent_team import AGENT_TEAM
    from strands import build_strands

    return build_strands(
        memory=_get_service().memory,
        team=AGENT_TEAM,
        chat_ids=_chat_ids(),
    )


@app.get("/api/power")
def get_power(_user=RequireChat) -> Dict[str, Any]:
    """Power modes and what each one means on this specific machine."""
    from resource_governor import GOVERNOR

    return GOVERNOR.describe_modes()


@app.post("/api/power")
def set_power(request: PowerRequest, _user=RequireChat) -> Dict[str, Any]:
    """Select a power mode.

    The response reports the ceiling that actually resulted, which may be lower
    than requested — the hardware safety floor overrides the setting.
    """
    from resource_governor import GOVERNOR, PowerMode

    try:
        mode = PowerMode(request.mode.strip().lower())
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail=f"Unknown power mode: {request.mode}"
        ) from error

    ceiling = GOVERNOR.set_mode(mode)
    return {"ceiling": ceiling.as_dict(), **GOVERNOR.describe_modes()}


@app.get("/api/agents")
def list_agents(_user=RequireChat) -> Dict[str, Any]:
    """Live team status for the agent progress panel."""
    from agent_runtime import sync_team
    from agent_team import AGENT_TEAM

    sync_team(AGENT_TEAM)
    snapshot = AGENT_TEAM.snapshot()

    # Pool stats describe anonymous execution capacity; the team describes who is
    # doing what. The panel wants both.
    try:
        from agent_pool import get_agent_pool

        snapshot["pool"] = get_agent_pool().get_pool_stats()
    except Exception as error:  # pragma: no cover - pool is optional
        snapshot["pool"] = {"error": str(error)}
    return snapshot


@app.post("/api/agents")
def spawn_agent(request: SpawnAgentRequest, _user=RequireChat) -> Dict[str, Any]:
    """Add one or more agents to the team.

    Supports the shape Shagnik asked for directly: several agents in one call,
    each with its own goal, one of them managing the others.
    """
    from agent_runtime import start_agent_task, tool_create_agent
    from agent_team import AGENT_TEAM, AgentRole

    AGENT_TEAM.ensure_master()
    created = []
    started = []
    for spec in request.agents:
        try:
            role = AgentRole(spec.role)
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail=f"Unknown role: {spec.role}"
            ) from error
        agent = None
        if role is AgentRole.WORKER and spec.goal.strip():
            # A worker with a goal joins the real roster, so it can be handed
            # work (by the Manager in chat, or by "run" below). An in-memory
            # spawn could be seen but never do anything — the "agents don't
            # update" complaint, because there was nothing to update.
            tool_create_agent(spec.name, spec.goal, emoji=spec.emoji or "🤖")
            agent = next((a for a in AGENT_TEAM.members() if a.name.lower() == spec.name.strip().lower()), None)
        if agent is None:
            agent = AGENT_TEAM.spawn(
                name=spec.name,
                goal=spec.goal,
                role=role,
                personality_id=spec.personality_id,
            )
        created.append(agent.snapshot())
        if spec.run and spec.goal.strip() and role is AgentRole.WORKER:
            started.append(start_agent_task(agent.name, spec.goal, role=_role_name(_user)))
    return {"created": created, "started": started, "team": AGENT_TEAM.snapshot()}


class AgentTaskRequest(BaseModel):
    task: str
    context: str = ""


def _role_name(user: Any) -> str:
    role = getattr(user, "role", None)
    return getattr(role, "value", None) or "local"


@app.post("/api/agents/{agent_name}/tasks")
def give_agent_task(agent_name: str, request: AgentTaskRequest, _user=RequireChat) -> Dict[str, Any]:
    """Hand one agent a task directly and watch it at /api/turns/{turn_id}/stream."""
    from agent_runtime import roster_entry, start_agent_task

    if not request.task.strip():
        raise HTTPException(status_code=400, detail="Say what the agent should do.")
    entry = roster_entry(agent_name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No agent called {agent_name!r}.")
    if entry.get("role") == "master":
        raise HTTPException(status_code=400, detail="The Manager works through chat; send it a message there.")
    return start_agent_task(entry["name"], request.task, context=request.context, role=_role_name(_user))


@app.get("/api/agents/details")
def agents_details(_user=RequireChat) -> Dict[str, Any]:
    """Every agent's goal, purpose, model, consult settings, status and recent work (Request H2)."""
    from agent_runtime import all_agent_details

    return {"agents": all_agent_details()}


@app.post("/api/agents/subagents")
def create_subagent_route(fields: Dict[str, Any], _user=RequireChat) -> Dict[str, Any]:
    """The Sub-agents tab: make one with its model and consult settings.

    Then, as the owner asked (2026-09-15), start it three ways: on nothing, on a task in the
    background, or in its own chat — with or without a first message.
    """
    from agent_runtime import create_subagent, start_agent_task

    try:
        props = create_subagent(fields)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    task = str(fields.get("task") or "").strip()
    chat_id = ""
    started = None
    if fields.get("start_chat"):
        store = _shared_chat_store()
        chat_id = store.create(title=f"{props.get('emoji', '')} {props['name']}".strip())
        store.set_agent(chat_id, props["name"])
    elif task:
        started = start_agent_task(props["name"], task, role=_role_name(_user))
    return {"agent": props, "started": started, "chat_id": chat_id, "task": task if chat_id else ""}


class ChatAgentRequest(BaseModel):
    agent: str = ""


@app.post("/api/chats/{chat_id}/agent")
def link_chat_to_agent(chat_id: str, request: ChatAgentRequest, _user=RequireChat) -> Dict[str, Any]:
    """Give this chat to one agent (empty name hands it back to the Manager)."""
    from agent_runtime import roster_entry_exact

    name = request.agent.strip()
    if name and roster_entry_exact(name) is None:
        raise HTTPException(status_code=404, detail=f"No agent called {name!r}.")
    try:
        chat = _shared_chat_store().set_agent(chat_id, name)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="No such chat.") from error
    return {"chat_id": chat_id, "agent": chat.get("agent", ""), "title": chat.get("title", "")}


@app.get("/api/agents/{agent_name}/chats")
def chats_of_agent(agent_name: str, _user=RequireChat) -> Dict[str, Any]:
    store = _shared_chat_store()
    ids = store.chats_for_agent(agent_name)
    summaries = [s for s in store.summaries() if s.get("id") in set(ids)] if hasattr(store, "summaries") else []
    return {"agent": agent_name, "chats": summaries or [{"id": cid, "title": cid} for cid in ids]}


@app.delete("/api/agents/subagents/{agent_name}")
def delete_subagent_route(agent_name: str, _user=RequireChat) -> Dict[str, Any]:
    from agent_runtime import remove_custom_agent

    if not remove_custom_agent(agent_name):
        raise HTTPException(status_code=404, detail="Only agents made in chat or in the Sub-agents tab can be deleted.")
    return {"deleted": agent_name}


@app.get("/api/agents/{agent_name}/properties")
def get_agent_properties(agent_name: str, _user=RequireChat) -> Dict[str, Any]:
    """One agent's settings, live status and recent work — the Properties sheet (Request G16b)."""
    from agent_runtime import agent_properties

    props = agent_properties(agent_name)
    if props is None:
        raise HTTPException(status_code=404, detail=f"No agent called {agent_name!r}.")
    return {"agent": props}


@app.patch("/api/agents/{agent_name}")
def patch_agent(agent_name: str, changes: Dict[str, Any], _user=RequireChat) -> Dict[str, Any]:
    """Change an agent's objective, instructions, model, tools… Built-in agents keep edits as an overlay."""
    from agent_runtime import update_agent

    try:
        return {"agent": update_agent(agent_name, changes)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail=str(error).strip("'\"")) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/agents/{agent_id}")
def dismiss_agent(agent_id: str, _user=RequireChat) -> Dict[str, Any]:
    """Remove an agent. Refuses to remove the master while workers remain."""
    from agent_team import AGENT_TEAM

    if not AGENT_TEAM.dismiss(agent_id):
        raise HTTPException(
            status_code=400,
            detail="Agent not found, or it is the master and workers still depend on it.",
        )
    return {"team": AGENT_TEAM.snapshot()}


@app.get("/api/speed")
def get_speed(_user=RequireChat) -> Dict[str, Any]:
    """Report the current speed mode and what each option means."""
    service = _get_service()
    return {
        "mode": service.speed_mode.value,
        "modes": [
            {
                "id": "auto",
                "label": "Auto",
                "description": "Decide per turn. Simple questions take the fast path; "
                               "anything needing tools, fresh data, or code uses the full "
                               "pipeline. Recommended.",
            },
            {
                "id": "fast",
                "label": "Fast",
                "description": "Always answer directly with no tools. Much quicker, but "
                               "cannot search, read files, or run code — so it can be wrong "
                               "about anything current.",
            },
            {
                "id": "full",
                "label": "Full",
                "description": "Always use the complete pipeline with tools. Slower on "
                               "trivial questions, most thorough on hard ones.",
            },
        ],
    }


@app.post("/api/speed")
def set_speed(request: SpeedRequest, _user=RequireChat) -> Dict[str, Any]:
    """Override per-turn speed selection. 'auto' restores automatic behaviour."""
    from fast_response import SpeedMode

    try:
        mode = SpeedMode(request.mode.strip().lower())
    except ValueError as error:
        raise HTTPException(
            status_code=400, detail=f"Unknown speed mode: {request.mode}"
        ) from error

    # Apply to every live chat so the change is not silently per-session.
    with _services_lock:
        for service in _services.values():
            service.set_speed_mode(mode)
    _get_service().set_speed_mode(mode)
    return {"mode": mode.value}


@app.get("/api/personalities")
def personalities() -> Dict[str, Any]:
    """List built-in personalities and the saved custom one."""
    return {
        "presets": list_personalities(),
        "custom": get_custom_personality(),
        "active": (_get_service().get_personality() or {}).get("id", ""),
    }


@app.get("/api/personality")
def get_active_personality(_user=RequireChat) -> Dict[str, Any]:
    """Report which personality is currently applied."""
    active = _get_service().get_personality()
    return {"active": (active or {}).get("id", ""), "personality": active}


@app.post("/api/personality")
def set_active_personality(request: PersonalityRequest, _user=RequireChat) -> Dict[str, Any]:
    """Apply a personality to the assistant.

    This route did not exist, which is why choosing a personality in Settings did
    nothing: the panel could list presets and mark one selected in React state,
    but had nowhere to send it, so every reply came back in the default voice.

    An empty id clears the personality and restores the default voice.
    """
    wanted = (request.id or "").strip()

    try:
        # Apply to every live chat, matching /api/speed. A setting that only took
        # effect in whichever conversation happened to be cached would look like
        # it worked and then randomly not.
        with _services_lock:
            for service in _services.values():
                if wanted:
                    service.set_personality_from_id(wanted)
                else:
                    service.set_personality(None)
        default = _get_service()
        message = (
            default.set_personality_from_id(wanted)
            if wanted
            else default.set_personality(None)
        )
    except PersonalityNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    active = default.get_personality()
    return {
        "active": (active or {}).get("id", ""),
        "personality": active,
        "message": message,
    }


@app.post("/api/personalities/custom")
def set_custom_personality(payload: Dict[str, str]) -> Dict[str, Any]:
    """Save a custom personality description."""
    description = (payload.get("description") or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="Description cannot be empty.")
    return save_custom_personality(description)


@app.delete("/api/personalities/custom")
def delete_custom_personality() -> Dict[str, bool]:
    """Remove the saved custom personality."""
    return {"cleared": clear_custom_personality()}


# ---------------------------------------------------------------------------
# Speech patterns
# ---------------------------------------------------------------------------


@app.get("/api/speech")
def speech_patterns() -> Dict[str, Any]:
    """Return currently learned speech patterns."""
    return {"patterns": _get_speech().get_patterns()}


@app.post("/api/speech/learn")
def learn_speech(payload: SpeechLearnRequest) -> Dict[str, Any]:
    """Learn speech patterns from a batch of user messages."""
    patterns = _get_speech().learn(payload.messages)
    return {"patterns": patterns}


@app.delete("/api/speech")
def clear_speech() -> Dict[str, int]:
    """Clear learned speech patterns."""
    return {"cleared": _get_speech().clear()}


# ---------------------------------------------------------------------------
# Folder reader
# ---------------------------------------------------------------------------


@app.get("/api/folders")
def folder_list() -> Dict[str, Any]:
    """List registered folders."""
    return {"folders": _get_folder_reader().list_folders()}


@app.post("/api/folders")
def folder_add(payload: FolderAddRequest) -> Dict[str, str]:
    """Register a folder by name and path."""
    try:
        resolved = _get_folder_reader().add_folder(payload.name, payload.path)
        return {"status": "registered", "name": payload.name, "path": resolved}
    except FolderReaderError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.delete("/api/folders/{name}")
def folder_remove(name: str) -> Dict[str, Any]:
    """Unregister a folder."""
    try:
        removed = _get_folder_reader().remove_folder(name)
        return {"removed": removed}
    except FolderReaderError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/folders/{name}/files")
def folder_files(name: str, limit: int = 100) -> Dict[str, Any]:
    """List files in a registered folder, any format."""
    try:
        return {"folder": name, "files": _get_folder_reader().list_files(name, limit=limit)}
    except FolderReaderError as error:
        raise HTTPException(status_code=400, detail=str(error))


@app.get("/api/folders/{name}/read")
def folder_read(name: str, path: str) -> Dict[str, Any]:
    """Read a file from a registered folder."""
    try:
        return _get_folder_reader().read_file(name, path)
    except FolderReaderError as error:
        raise HTTPException(status_code=404, detail=str(error))

@app.get("/api/folders/{name}/search")
def folder_search(name: str, q: str, limit: int = 10) -> Dict[str, Any]:
    """Search text files in a registered folder for a query string."""
    try:
        return {"query": q, "results": _get_folder_reader().search_files(name, q, limit=limit)}
    except FolderReaderError as error:
        raise HTTPException(status_code=400, detail=str(error))


# ---------------------------------------------------------------------------
# Connectors, Graphs, Homework, Storage & Database Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/connectors")
def list_connectors() -> Dict[str, Any]:
    """List all registered connectors and their health status."""
    from connectors import CONNECTOR_REGISTRY

    return {
        "connectors": CONNECTOR_REGISTRY.list_connectors(),
        "health": CONNECTOR_REGISTRY.health_status(),
    }


@app.post("/api/connectors/{name}/execute")
def execute_connector(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Execute an action on a named connector."""
    from connectors import CONNECTOR_REGISTRY

    action = payload.get("action", "")
    params = payload.get("params", {})
    return CONNECTOR_REGISTRY.execute(name, action, **params)


@app.post("/api/graphs/create")
def create_graph_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Generate Mermaid and ASCII graphs from node and edge definitions."""
    from graph_engine import GraphEngine

    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])
    graph_type = payload.get("graph_type", "flowchart")
    direction = payload.get("direction", "TD")
    return GraphEngine.create_graph(nodes, edges, graph_type=graph_type, direction=direction)


@app.post("/api/graphs/read")
def read_graph_endpoint(payload: Dict[str, str]) -> Dict[str, Any]:
    """Extract entities and relationship edges from plain text or diagrams."""
    from graph_engine import GraphEngine

    text = payload.get("text", "")
    return GraphEngine.read_graph(text)


@app.post("/api/homework/analyze")
def homework_analyze_endpoint(payload: Dict[str, str]) -> Dict[str, Any]:
    """Decompose homework problem into concept breakdown, steps, and hints."""
    from homework_helper import HomeworkHelper

    problem = payload.get("problem", "")
    return HomeworkHelper.decompose_problem(problem)


@app.get("/api/doctor")
def doctor_diagnostics() -> Dict[str, Any]:
    """Run full system diagnostics on providers, memory, and connectors."""
    from connectivity import is_online
    from connectors import CONNECTOR_REGISTRY
    from device_profile import get_device_profile, select_tier

    profile = get_device_profile(force_refresh=True)
    tier = select_tier(profile)
    return {
        "status": "healthy",
        "online": is_online(),
        "hardware": {
            "ram_gb": profile.ram_gb,
            "vram_gb": profile.vram_gb,
            "gpu_name": profile.gpu_name,
            "cpu_cores": profile.cpu_cores,
            "tier": tier.name,
            "max_workers": tier.max_workers,
        },
        "connectors": CONNECTOR_REGISTRY.health_status(),
    }


# ---------------------------------------------------------------------------
# Personality error mapping
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Authentication & admin (ROADMAP AA1-AA6)
#
# The API is open while unclaimed (a fresh local install) and requires a session
# the moment an owner account exists. Privileged routes are always gated.
# ---------------------------------------------------------------------------


@app.post("/api/auth/login")
def login(request: LoginRequest) -> Dict[str, Any]:
    """Exchange credentials for a session token."""
    try:
        token = AUTH_STORE.authenticate(request.email, request.password)
    except AuthError as error:
        # 401 with the store's deliberately non-specific message: it never
        # reveals whether the account exists.
        raise HTTPException(status_code=401, detail=str(error)) from error
    user = AUTH_STORE.get_user(request.email)
    return {"token": token, "user": user.public() if user else None}


@app.post("/api/auth/logout")
def logout(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    """Invalidate the caller's session."""
    if authorization:
        AUTH_STORE.logout(authorization.replace("Bearer ", "").strip())
    return {"ok": True}


@app.get("/api/auth/me")
def whoami(user=RequireChat) -> Dict[str, Any]:
    """Return the signed-in account, or the unclaimed-install marker."""
    if user is None:
        return {"claimed": False, "user": None}
    return {"claimed": True, "user": user.public()}


@app.post("/api/auth/join")
def join(request: JoinRequest) -> Dict[str, Any]:
    """Redeem a single-use invite and create the account."""
    try:
        user = AUTH_STORE.redeem_invite(request.invite, request.email, request.password)
    except AuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"user": user.public()}


@app.get("/api/admin/users")
def admin_users(user=RequireAdmin) -> Dict[str, Any]:
    """List accounts. Requires VIEW_ADMIN."""
    return {"users": [u.public() for u in AUTH_STORE.users.values()]}


@app.get("/api/admin/invites")
def admin_invites(user=RequireInvite) -> Dict[str, Any]:
    """List invites. Requires INVITE_TESTERS."""
    return {
        "invites": [
            {
                "token": i.token,
                "role": i.role.value,
                "email": i.email,
                "created_by": i.created_by,
                "expires_at": i.expires_at,
                "redeemed_by": i.redeemed_by,
                "valid": i.is_valid(),
            }
            for i in AUTH_STORE.invites.values()
        ]
    }


@app.post("/api/admin/invites")
def admin_create_invite(
    request: InviteRequest, http_request: Request, user=RequireInvite
) -> Dict[str, Any]:
    """Mint a single-use beta invite and return its shareable link.

    The link is built against the address this request actually arrived on
    unless the caller names one. It used to fall back to the Vite dev server,
    so an invite minted from the packaged app pointed at a port the recipient
    has nothing running on.
    """
    try:
        role = Role(request.role)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Unknown role: {request.role}") from error
    try:
        invite = AUTH_STORE.mint_invite(user, role, request.email)
    except AuthError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    return {
        "token": invite.token,
        "role": invite.role.value,
        "email": invite.email,
        "expires_at": invite.expires_at,
        "link": invite_link(request.base_url or str(http_request.base_url), invite.token),
    }


@app.post("/api/admin/grant")
def admin_grant(request: GrantRequest, user=RequireGrant) -> Dict[str, Any]:
    """Change an account's role. Owner only.

    Delegates to AuthStore.grant_role_as rather than re-checking the owner rules
    here. The previous version duplicated that policy inline and reached into the
    store's private _save(), so the same rule lived in two places and could drift
    apart silently.
    """
    try:
        role = Role(request.role)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Unknown role: {request.role}") from error

    try:
        target = AUTH_STORE.grant_role_as(user, request.email, role)
    except UnknownAccountError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AuthError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    return {"user": target.public()}


@app.post("/api/auth/claim")
def claim_ownership(request: ClaimRequest, http_request: Request) -> Dict[str, Any]:
    """Create the owner account on a fresh install, from the UI.

    Claiming was CLI-only (`python admin_setup.py claim <email>`), which meant a
    normal user had no way to secure their install without a terminal.

    Two guards that matter:

    * **Loopback only.** On an unclaimed install whoever calls this first becomes
      the owner. Over the network that is a land-grab; from the local machine it
      is the same trust level the CLI already had.
    * **409 once claimed.** bootstrap_owner refuses a second owner anyway, but
      answering plainly is better than surfacing a generic error.
    """
    client_host = http_request.client.host if http_request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(
            status_code=403,
            detail="Ownership can only be claimed from the machine running Nyx.",
        )

    if is_claimed():
        raise HTTPException(
            status_code=409,
            detail="This install already has an owner. Sign in instead.",
        )

    # Check the password BEFORE creating anything. bootstrap_owner makes a
    # passwordless owner, so validating afterwards left a half-made account on
    # rejection: is_claimed() flipped to true, the install could never be claimed
    # again, and an owner account sat there with no password set.
    try:
        check_password_policy(request.password)
    except WeakPasswordError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    try:
        AUTH_STORE.bootstrap_owner(request.email)
        AUTH_STORE.set_password(request.email, request.password)
        token = AUTH_STORE.authenticate(request.email, request.password)
    except WeakPasswordError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except AuthError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error

    user = AUTH_STORE.get_user(request.email)
    return {"token": token, "user": user.public() if user else None}


@app.exception_handler(PersonalityNotFoundError)
async def personality_not_found_handler(request, exc: PersonalityNotFoundError):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=404, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Serve the built workspace (ROADMAP BB12)
#
# One process, one URL. Previously the UI needed a second terminal running the
# Vite dev server on :5173, so anything pointing a user at the app hit
# ERR_CONNECTION_REFUSED unless they happened to have started it. Serving the
# built bundle from the API means `uvicorn server:app` is the whole product.
#
# Mounted last so it never shadows an /api route.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Live routes, tool modules, and capability routers
# ---------------------------------------------------------------------------

def _include_routers() -> Dict[str, str]:
    """Attach route modules that exist on this install; report the ones that do not.

    The capability routers (system specs, computer control, email, access keys,
    voices) are separate modules so they can land and be tested independently.
    A missing optional dependency must cost its own routes, never the server.
    """
    import importlib

    status: Dict[str, str] = {}
    for module_name in ("routes_live", "routes_system", "routes_computer", "routes_email",
                        "routes_access", "routes_voice", "routes_learning", "routes_providers", "routes_models",
                        "routes_improve", "routes_intelligence", "routes_notes", "routes_code", "routes_trading", "routes_key_pool",
                        "routes_build", "routes_game", "routes_command_zone", "routes_core", "routes_collab", "routes_research", "routes_context",
                        "routes_absorb", "routes_local_models", "routes_diagram", "routes_screen", "routes_apply",
                        "routes_security", "routes_proto_voice", "routes_features", "routes_curiosity", "routes_finance_lab", "routes_voice_gestures",
                        "routes_design", "routes_accounts", "routes_swarm", "routes_own_computer", "routes_connectors",
                        "routes_freewill", "routes_identity0", "routes_office", "routes_world", "routes_whatsapp"):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as error:
            status[module_name] = "not installed yet" if error.name == module_name else f"missing {error.name}"
            continue
        except Exception as error:  # noqa: BLE001
            status[module_name] = f"{type(error).__name__}: {error}"
            continue
        router = getattr(module, "router", None)
        if router is None:
            status[module_name] = "no router"
            continue
        app.include_router(router)
        status[module_name] = "ok"
    return status


ROUTER_STATUS = _include_routers()

try:
    # Probe slow connector checks (Obsidian's REST port) before anyone opens a
    # tab that lists them.
    from connectors import CONNECTOR_REGISTRY as _CONNECTORS

    _CONNECTORS.warm()
except Exception:  # pragma: no cover - warming is an optimisation only
    pass

try:
    from tool_setup import register_all_tools

    register_all_tools()
except Exception:  # pragma: no cover - tools failing to register must not stop the API
    pass


class PresencePing(BaseModel):
    tab: str = ""


@app.post("/api/presence")
def presence_ping(body: PresencePing, _user=RequireChat) -> Dict[str, Any]:
    """The web UI's throttled "someone is using me" heartbeat (real input only)."""
    import presence

    presence.mark_active("input", tab=body.tab)
    try:
        from predictor import PREDICTOR

        if body.tab:
            PREDICTOR.observe_tab(body.tab)
        else:
            PREDICTOR.observe_activity()
    except Exception:  # pragma: no cover - predictions are a hint
        pass
    return presence.snapshot()


@app.get("/api/presence")
def presence_state(_user=RequireChat) -> Dict[str, Any]:
    import presence

    return presence.snapshot()


@app.on_event("shutdown")
async def _shutdown_background_work() -> None:
    """Guarantee lingering background tasks or loops terminate within a timeout during shutdown."""
    logger = logging.getLogger("nyx.server")

    # Stop known background services first
    try:
        from predictor import SCHEDULER
        if hasattr(SCHEDULER, "stop") and callable(SCHEDULER.stop):
            if asyncio.iscoroutinefunction(SCHEDULER.stop):
                await asyncio.shield(asyncio.wait_for(SCHEDULER.stop(), timeout=SHUTDOWN_TIMEOUT))
            else:
                SCHEDULER.stop()
    except asyncio.TimeoutError:
        logger.warning("scheduler shutdown timed out after %.1fs", SHUTDOWN_TIMEOUT, exc_info=True)
    except Exception:
        logger.warning("scheduler shutdown failed", exc_info=True)

    # Child processes Nyx started for the owner: site previews' dev servers and the WhatsApp helper.
    try:
        import site_preview

        site_preview.stop_all()
    except Exception:
        logger.warning("site previews did not stop", exc_info=True)
    try:
        import whatsapp_link

        if whatsapp_link._LINK is not None:
            whatsapp_link._LINK.stop()
    except Exception:
        logger.warning("WhatsApp helper did not stop", exc_info=True)

    # Only what Nyx started (see _BACKGROUND_TASKS). A task left from an earlier loop — a previous
    # TestClient session — cannot be awaited or cancelled from this one.
    loop = asyncio.get_running_loop()
    pending = {t for t in _BACKGROUND_TASKS if not t.done() and t.get_loop() is loop}
    if not pending:
        return
    logger.info("Waiting for %d background tasks to complete (timeout=%.1fs)", len(pending), SHUTDOWN_TIMEOUT)
    _, overdue = await asyncio.wait(pending, timeout=SHUTDOWN_TIMEOUT)
    for task in overdue:
        logger.warning("Background task %r exceeded shutdown timeout, cancelling", task)
        task.cancel()
    if overdue:
        # Bounded as well: a task that swallows its cancel must not hold the engine open.
        await asyncio.wait(overdue, timeout=SHUTDOWN_TIMEOUT)
    for task in pending:
        if task.done() and not task.cancelled() and task.exception() is not None:
            logger.error("Background task %r raised during shutdown", task, exc_info=task.exception())


@app.on_event("startup")
def _resume_background_work() -> None:
    """Long-running owner-started work (improvement autopilot) continues after a restart."""
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("NYX_NO_BACKGROUND"):
        return
    try:
        import storage_budget

        # Keep growing stores inside their budgets (owner, 2026-09-15: "doesn't take too much storage").
        storage_budget.start_background()
    except Exception:  # pragma: no cover
        logging.getLogger("nyx.server").warning("storage budget did not start", exc_info=True)
    try:
        from improve_autopilot import AUTOPILOT

        AUTOPILOT.resume_on_startup()
    except Exception:  # pragma: no cover - a stale run file must not stop the API
        logging.getLogger("nyx.server").warning("could not resume the improvement autopilot", exc_info=True)
    try:
        from identity0 import jobs as kahuna_jobs

        # Training its own model takes hours; a sleep or a restart should not end it (Request S4).
        picked_up = kahuna_jobs.recover()
        if picked_up:
            logging.getLogger("nyx.server").info("Big Kahuna resumed training %s", picked_up["id"])
        from identity0 import api as kahuna_api

        kahuna_api.warm_up()  # the first spoken turn should not be the slow one (Request S22)
    except Exception:  # pragma: no cover - never at the cost of the API starting
        logging.getLogger("nyx.server").warning("could not resume Big Kahuna's training", exc_info=True)

    def grow_on_first_run() -> None:
        # The brain starts from what is already on this PC; Nyx Core from the turns already learned.
        try:
            import nyx_core
            import super_brain

            if super_brain.BRAIN.counts()["nodes"] == 0:
                super_brain.BRAIN.seed(background=False)
            nyx_core.CORE.bootstrap_from_history()
        except Exception:  # pragma: no cover
            logging.getLogger("nyx.server").warning("brain first-run growth failed", exc_info=True)

    threading.Thread(target=grow_on_first_run, name="nyx-brain-first-run", daemon=True).start()

    try:
        import whatsapp_link

        # The owner's phone line reconnects by itself, but only on the PC it was paired with.
        whatsapp_link.start_in_background()
    except Exception:  # pragma: no cover - the phone line must never stop the API
        logging.getLogger("nyx.server").warning("WhatsApp link did not start", exc_info=True)

    try:
        from predictor import SCHEDULER

        restart = ENGINE_HOOKS.get("restart")
        if callable(restart):
            SCHEDULER._restart = restart
        SCHEDULER.start()
    except Exception:  # pragma: no cover
        logging.getLogger("nyx.server").warning("idle scheduler did not start", exc_info=True)


_FRONTEND_DIST = Path(__file__).resolve().parent / "frontend" / "nyx-pulse" / "dist"


def _mount_frontend() -> bool:
    """Serve the built frontend at / when it exists.

    Returns whether it was mounted, so `/api/health` can tell the truth about
    whether this install has a UI rather than assuming one.
    """
    index = _FRONTEND_DIST / "app" / "index.html"
    if not index.is_file():
        return False

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # Hashed asset filenames, so they can be cached hard.
    assets = _FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    favicon = _FRONTEND_DIST / "favicon.svg"
    if favicon.is_file():
        @app.get("/favicon.svg", include_in_schema=False)
        @app.get("/favicon.ico", include_in_schema=False)
        def icon() -> Any:
            """Browsers request /favicon.ico unprompted; serve the SVG for both."""
            return FileResponse(favicon, media_type="image/svg+xml")

    service_worker = _FRONTEND_DIST / "sw.js"
    if service_worker.is_file():
        @app.get("/sw.js", include_in_schema=False)
        def shell_cache_worker() -> Any:
            """The worker that keeps the app loadable while the engine is off.

            Never cached itself, so a fix to it reaches browsers on the next load.
            """
            return FileResponse(
                service_worker,
                media_type="application/javascript",
                headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
            )

    @app.get("/", include_in_schema=False)
    @app.get("/app", include_in_schema=False)
    @app.get("/app/{_path:path}", include_in_schema=False)
    @app.get("/join", include_in_schema=False)
    def workspace(_path: str = "") -> Any:
        """The single-page workspace, at every path the app is linked to.

        `/join` is here because that is where invite links point: auth.py builds
        `{base}/join?invite=…` and the app reads the token out of the query
        string. Without this route every invite we ever sent 404'd, which is
        why it is listed explicitly rather than left to a catch-all — a
        catch-all would also swallow genuine 404s from the API.

        no-cache so a rebuilt UI is picked up immediately; the service worker
        holds the offline copy, not the browser's HTTP cache.
        """
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return True


_FRONTEND_MOUNTED = _mount_frontend()


if __name__ == "__main__":
    import uvicorn

    print("Nyx Ichos — created by Shagnik")
    if _FRONTEND_MOUNTED:
        print("  workspace: http://127.0.0.1:8000/")
    else:
        print("  workspace: not built yet — run `npm run build` in frontend/nyx-pulse")
    print("  API docs:  http://127.0.0.1:8000/docs")
    uvicorn.run(app, host="127.0.0.1", port=8000)
