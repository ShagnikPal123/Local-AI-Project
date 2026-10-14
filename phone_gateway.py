"""The phone's window onto this PC: a small, separate web server for the chats, and nothing else.

Owner (2026-10-13): "a similar feature to claude which uses remote connection. So basically, I can go to the site,
allow remote connection … so the user can see ongoing chats and new chats they make."

Why a second server and not the main one: Nyx's own API is bound to this computer on purpose, and an unclaimed
install lets whoever reaches it in. Opening that to the home network would open everything. This gateway is a different
app with four small doors, all shut by default:

  * It does not run until the owner turns on "Allow my phone" in Settings.
  * Its only public doors are the phone page itself and ``/pair`` (the one-minute key, see ``phone_pairing``).
  * Everything else needs the token a phone got by pairing: list chats, read one, write to one, start a new one.
  * It answers only addresses on the home network (private or loopback). A request that arrives from the open internet
    (for example through a router port-forward) is refused before anything is read.
  * A message from the phone runs under the same "phone guard" as WhatsApp: the AI can talk, search and read, but a
    tool that changes the PC is blocked with a plain message, and the phone cannot raise its own access.

Reaching the PC from outside the home network is not built here: it needs a tunnel the owner sets up, and that is a
decision about exposure, not a default.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import phone_pairing
from paths import data_path

log = logging.getLogger("nyx.phone_gateway")

DEFAULT_PORT = 8765
STATE_FILE = "phone_gateway.json"
MESSAGES_SHOWN = 60
MESSAGE_CHARS = 4000
CHATS_SHOWN = 30
TEXT_LIMIT = 8000

PAGE_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                               "connect-src 'self'; base-uri 'none'; form-action 'none'",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def on_home_network(host: str) -> bool:
    """Private (192.168.x, 10.x, 172.16-31.x), link-local or loopback addresses only."""
    try:
        address = ipaddress.ip_address(str(host or "").split("%")[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if address.is_loopback or address.is_link_local:
        return True
    if isinstance(address, ipaddress.IPv6Address):       # home IPv6 is fc00::/7; ``is_private`` also admits odd ranges
        return address in ipaddress.ip_network("fc00::/7")
    return address.is_private


class ServerChats:
    """The PC's chats, reached lazily so importing this file never loads the whole server (tests replace it)."""

    @staticmethod
    def _store() -> Any:
        import server

        return server._shared_chat_store()

    def recent(self, limit: int) -> List[Dict[str, Any]]:
        return [c for c in self._store().summaries() if c.get("kind", "chat") == "chat"][:limit]

    def exists(self, chat_id: str) -> bool:
        return bool(chat_id) and bool(self._store().exists(chat_id))

    def messages(self, chat_id: str) -> List[Dict[str, Any]]:
        return self._store().messages(chat_id)

    def create(self, title: str) -> str:
        return self._store().create(title=title, activate=False)


def run_phone_turn(chat_id: str, text: str) -> str:
    """One AI turn in a chat, for a message typed on the phone. Same limits as the WhatsApp line at its default level."""
    import server
    from whatsapp_link import PHONE_NOTE, phone_guard

    service = server._get_service(chat_id)
    guard_before = getattr(service, "tool_guard", None)
    service.tool_guard = phone_guard
    try:
        service.set_turn_context(PHONE_NOTE)
        result = service.chat_turn(text, sink=lambda _event: None, role="local", turn_id=uuid.uuid4().hex[:12])
    finally:
        service.tool_guard = guard_before
    return str((result or {}).get("reply") or "") if isinstance(result, dict) else str(result or "")


class PairBody(BaseModel):
    key: str
    name: str = "Phone"


class SendBody(BaseModel):
    text: str


class NewChatBody(BaseModel):
    title: str = "From my phone"


def build_app(book: Optional[phone_pairing.PhoneBook] = None, chats: Any = None,
              turn: Optional[Callable[[str, str], str]] = None) -> FastAPI:
    """The gateway's web app. ``book``, ``chats`` and ``turn`` are swapped for fakes in tests."""
    the_book = book or phone_pairing.book()
    the_chats = chats or ServerChats()
    the_turn = turn or run_phone_turn
    app = FastAPI(title="Nyx phone gateway", docs_url=None, redoc_url=None, openapi_url=None)
    working: set = set()
    working_lock = threading.Lock()

    @app.middleware("http")
    async def home_only(request: Request, call_next):
        host = request.client.host if request.client else ""
        if not on_home_network(host):
            return JSONResponse({"detail": "This only answers phones on the home network."}, status_code=403)
        return await call_next(request)

    def phone(authorization: Optional[str] = Header(default=None)) -> Dict[str, Any]:
        token = ""
        if authorization:
            parts = authorization.split(None, 1)
            token = parts[1].strip() if len(parts) == 2 and parts[0].lower() == "bearer" else ""
        device = the_book.authenticate(token)
        if device is None:
            raise HTTPException(status_code=401, detail="Pair this phone again from the PC.")
        return device

    @app.get("/", response_class=HTMLResponse)
    def page() -> HTMLResponse:
        return HTMLResponse(PAGE, headers=PAGE_HEADERS)

    @app.post("/pair")
    def pair(body: PairBody, request: Request) -> Dict[str, Any]:
        source = request.client.host if request.client else "unknown"
        try:
            return the_book.redeem(body.key, body.name, source)
        except phone_pairing.PairingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/chats")
    def list_chats(_device=Depends(phone)) -> Dict[str, Any]:
        rows = [{"id": c["id"], "title": c.get("title") or "Chat", "preview": c.get("preview", ""),
                 "updated_at": c.get("updated_at"), "working": c["id"] in working}
                for c in the_chats.recent(CHATS_SHOWN)]
        return {"chats": rows}

    @app.get("/api/chats/{chat_id}")
    def read_chat(chat_id: str, _device=Depends(phone)) -> Dict[str, Any]:
        if not the_chats.exists(chat_id):
            raise HTTPException(status_code=404, detail="That chat is gone.")
        shown = [m for m in the_chats.messages(chat_id) if m.get("role") in ("user", "assistant")][-MESSAGES_SHOWN:]
        return {"id": chat_id, "working": chat_id in working,
                "messages": [{"role": m["role"], "content": str(m.get("content", ""))[:MESSAGE_CHARS]} for m in shown]}

    @app.post("/api/chats")
    def new_chat(body: NewChatBody, _device=Depends(phone)) -> Dict[str, Any]:
        return {"id": the_chats.create((body.title or "From my phone").strip()[:60] or "From my phone")}

    @app.post("/api/chats/{chat_id}/send")
    def send(chat_id: str, body: SendBody, _device=Depends(phone)) -> Dict[str, Any]:
        text = (body.text or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="Write something to send.")
        if len(text) > TEXT_LIMIT:
            raise HTTPException(status_code=400, detail=f"Keep it under {TEXT_LIMIT} characters.")
        if not the_chats.exists(chat_id):
            raise HTTPException(status_code=404, detail="That chat is gone.")
        with working_lock:
            if chat_id in working:
                raise HTTPException(status_code=409, detail="That chat is still answering. Give it a moment.")
            working.add(chat_id)
        try:
            reply = the_turn(chat_id, text)
        except Exception as error:  # noqa: BLE001 - the phone gets words, not a stack trace
            log.info("phone turn failed", exc_info=True)
            raise HTTPException(status_code=500, detail=f"The AI could not answer: {str(error)[:200]}") from error
        finally:
            with working_lock:
                working.discard(chat_id)
        return {"reply": reply}

    return app


# ---------------------------------------------------------------------------
# Running it
# ---------------------------------------------------------------------------


def lan_addresses() -> List[str]:
    """This PC's home-network addresses, the ones a phone on the same Wi-Fi can reach."""
    found: List[str] = []
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("10.255.255.255", 1))             # a UDP "connect" sends nothing; it only picks the route
            found.append(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if info[4][0] not in found:
                found.append(info[4][0])
    except OSError:
        pass
    return [a for a in found if on_home_network(a) and not a.startswith("127.")]


class Gateway:
    """Starts and stops the phone server on a background thread. ``runner`` is swapped for a fake in tests."""

    def __init__(self, state_path: Optional[Any] = None, runner: Optional[Callable[..., Any]] = None) -> None:
        self._path = state_path
        self._runner = runner or _run_uvicorn
        self._lock = threading.RLock()
        self._server: Any = None
        self._thread: Optional[threading.Thread] = None
        self.error = ""

    def _file(self):
        return self._path or data_path(STATE_FILE)

    def saved(self) -> Dict[str, Any]:
        import json

        try:
            data = json.loads(self._file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        port = data.get("port") if isinstance(data, dict) else None
        return {"enabled": bool(isinstance(data, dict) and data.get("enabled")),
                "port": port if isinstance(port, int) and 1024 <= port <= 65535 else DEFAULT_PORT}

    def _save(self, enabled: bool, port: int) -> None:
        import json

        path = self._file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"enabled": enabled, "port": port}), encoding="utf-8")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        saved = self.saved()
        port = saved["port"]
        return {"enabled": saved["enabled"], "running": self.running, "port": port, "error": self.error,
                "urls": [f"http://{a}:{port}/" for a in lan_addresses()] if self.running else []}

    def start(self, port: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            chosen = port or self.saved()["port"]
            self._save(True, chosen)
            if not self.running:
                self.error = ""
                self._server = None
                ready = threading.Event()

                def run() -> None:
                    try:
                        self._runner(self, build_app(), chosen, ready)
                    except Exception as error:  # noqa: BLE001 - a port that is taken must not crash the engine
                        self.error = f"The phone server could not start on port {chosen}: {error}"
                        log.warning("phone gateway failed", exc_info=True)

                self._thread = threading.Thread(target=run, name="nyx-phone-gateway", daemon=True)
                self._thread.start()
                ready.wait(timeout=3)
                waited = 0.0
                while (self.running and not self.error and not getattr(self._server, "started", True)
                       and waited < 3.0):                    # uvicorn flips ``started`` once the port is listening
                    time.sleep(0.05)
                    waited += 0.05
            return self.status()

    def stop(self) -> Dict[str, Any]:
        """The owner turned it off: stop serving and stay off after a restart."""
        with self._lock:
            self._save(False, self.saved()["port"])
        return self.halt()

    def halt(self) -> Dict[str, Any]:
        """Stop serving without changing the owner's choice (engine shutdown: it comes back if it was on)."""
        with self._lock:
            if self._server is not None:
                self._server.should_exit = True
            if self._thread is not None:
                self._thread.join(timeout=3)
            self._thread = None
            self._server = None
            return self.status()

    def start_if_enabled(self) -> None:
        if self.saved()["enabled"]:
            self.start()


def _run_uvicorn(gateway: Gateway, app: FastAPI, port: int, ready: threading.Event) -> None:
    import uvicorn

    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    gateway._server = server
    ready.set()
    server.run()


_GATEWAY: Optional[Gateway] = None
_GATEWAY_LOCK = threading.Lock()


def gateway() -> Gateway:
    global _GATEWAY
    with _GATEWAY_LOCK:
        if _GATEWAY is None:
            _GATEWAY = Gateway()
        return _GATEWAY


def start_in_background() -> None:
    """Called at engine start: bring the phone server back only if the owner left it on."""
    threading.Thread(target=lambda: gateway().start_if_enabled(), name="nyx-phone-start", daemon=True).start()


# ---------------------------------------------------------------------------
# The page the phone opens
# ---------------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Nyx</title>
<style>
:root{--bg:#0f1115;--card:#181b22;--line:#2a2f3a;--text:#e8eaf0;--mute:#8d94a5;--accent:#7aa2ff;--me:#26324f}
@media (prefers-color-scheme:light){:root{--bg:#f6f7f9;--card:#fff;--line:#dde0e6;--text:#14161a;--mute:#5d6575;--accent:#2a5bd7;--me:#dfe8ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.45 system-ui,sans-serif;
min-height:100dvh;display:flex;flex-direction:column}
header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:10px;align-items:center}
header b{flex:1}button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--text);
border-radius:10px;padding:8px 12px}button.go{background:var(--accent);color:#fff;border-color:var(--accent)}
main{flex:1;overflow:auto;padding:12px 16px}.row{padding:12px;border:1px solid var(--line);background:var(--card);
border-radius:12px;margin-bottom:8px}.row small{color:var(--mute);display:block}
.msg{max-width:88%;padding:8px 12px;border-radius:14px;margin:6px 0;white-space:pre-wrap;overflow-wrap:anywhere}
.me{background:var(--me);margin-left:auto}.ai{background:var(--card);border:1px solid var(--line)}
form{display:flex;gap:8px;padding:10px 16px;border-top:1px solid var(--line)}
input,textarea{font:inherit;color:var(--text);background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:10px;width:100%}.err{color:#e5645a;margin:8px 0}.mute{color:var(--mute)}
</style></head><body>
<header><b id="title">Nyx</b><button id="back" hidden>Chats</button><button id="new" hidden>New</button></header>
<main id="main"></main>
<form id="form" hidden><input id="text" placeholder="Message" autocomplete="off"><button class="go">Send</button></form>
<script>
(function(){
var KEY="nyx.phone.token",token=null,chat=null,timer=null,busy=false;
try{token=localStorage.getItem(KEY)}catch(e){}
var $=function(id){return document.getElementById(id)},main=$("main");
function el(tag,cls,text){var n=document.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n}
function api(path,opt){opt=opt||{};opt.headers=Object.assign({"Content-Type":"application/json"},token?{Authorization:"Bearer "+token}:{});
return fetch(path,opt).then(function(r){return r.json().catch(function(){return{}}).then(function(d){
if(r.status===401&&token){token=null;try{localStorage.removeItem(KEY)}catch(e){}pairView()}
if(!r.ok)throw new Error(d.detail||"Something went wrong");return d})})}
function stop(){if(timer){clearInterval(timer);timer=null}}
function pairView(){stop();chat=null;$("title").textContent="Connect to Nyx";$("back").hidden=true;$("new").hidden=true;$("form").hidden=true;
main.replaceChildren();main.appendChild(el("p","mute","On your PC open Settings, Phone, press Show a key, then type it here within a minute."));
var key=el("input");key.placeholder="Key, like K7M2-9QXA";key.autocapitalize="characters";var nm=el("input");nm.placeholder="Name for this phone";
var go=el("button","go","Connect"),err=el("div","err");nm.style.marginTop=nm.style.marginBottom="8px";
go.onclick=function(){err.textContent="";api("/pair",{method:"POST",body:JSON.stringify({key:key.value,name:nm.value||"Phone"})}).then(function(d){
token=d.token;try{localStorage.setItem(KEY,token)}catch(e){}listView()}).catch(function(e){err.textContent=e.message})};
main.append(key,nm,go,err)}
function listView(){stop();chat=null;$("title").textContent="Chats";$("back").hidden=true;$("new").hidden=false;$("form").hidden=true;
function load(){api("/api/chats").then(function(d){if(chat)return;main.replaceChildren();
if(!d.chats.length)main.appendChild(el("p","mute","No chats yet. Start one with New."));
d.chats.forEach(function(c){var r=el("div","row");r.appendChild(el("b",null,c.title+(c.working?" (answering)":"")));
r.appendChild(el("small",null,c.preview));r.onclick=function(){chatView(c.id,c.title)};main.appendChild(r)})}).catch(function(){})}
load();timer=setInterval(load,5000)}
function chatView(id,title){stop();chat=id;$("title").textContent=title||"Chat";$("back").hidden=false;$("new").hidden=true;$("form").hidden=false;
function load(){api("/api/chats/"+encodeURIComponent(id)).then(function(d){if(chat!==id)return;
var atEnd=main.scrollHeight-main.scrollTop-main.clientHeight<80;main.replaceChildren();
d.messages.forEach(function(m){main.appendChild(el("div","msg "+(m.role==="user"?"me":"ai"),m.content))});
if(d.working)main.appendChild(el("div","mute","Answering…"));if(atEnd||!timer)main.scrollTop=main.scrollHeight}).catch(function(){})}
load();timer=setInterval(load,4000)}
$("back").onclick=listView;
$("new").onclick=function(){api("/api/chats",{method:"POST",body:JSON.stringify({title:"From my phone"})}).then(function(d){chatView(d.id,"From my phone")})};
$("form").onsubmit=function(e){e.preventDefault();var t=$("text").value.trim();if(!t||busy||!chat)return;busy=true;$("text").value="";
var id=chat,mine=el("div","msg me",t);main.appendChild(mine);main.appendChild(el("div","mute","Answering…"));main.scrollTop=main.scrollHeight;
api("/api/chats/"+encodeURIComponent(id)+"/send",{method:"POST",body:JSON.stringify({text:t})}).catch(function(err){
main.appendChild(el("div","err",err.message))}).then(function(){busy=false;if(chat===id)chatView(id,$("title").textContent)})};
if(token)listView();else pairView()
})();
</script></body></html>
"""
