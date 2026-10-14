"""The web API (docs/API.md) and the built dashboard, from one small FastAPI app.

Deny by default: every ``/api/*`` route needs a signed-in person unless it is in ``PUBLIC``, and a
route that changes anything also needs the **owner** (``Depends(owner)``) and the
``x-ichos-trader: 1`` header the dashboard sends (so another website cannot press the buttons). A viewer sees the setup,
never a key, and cannot trade. The dashboard is served from ``web/dist`` on the same address, so
there is no cross-site access to open up.
"""

from __future__ import annotations

import os
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from . import __version__, config, settings as settings_mod
from .access import auth
from .connectors import catalog, models
from .engine import Engine
from .models import BrokerError
from .paper import PaperAccount

PUBLIC = ("/api/health", "/api/me", "/api/auth/")
WEB = config.APP_ROOT / "web" / "dist"
PASSCODE_TRIES, PASSCODE_WINDOW = 5, 600.0
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CHANGE_HEADER = "x-ichos-trader"


def _who(request: Request) -> Optional[Dict[str, Any]]:
    host = request.client.host if request.client else ""
    return auth.current_user(request.cookies.get(auth.COOKIE), host)


def viewer(request: Request) -> Dict[str, Any]:
    user = getattr(request.state, "user", None) or _who(request)
    if not user:
        raise HTTPException(401, "Please sign in.")
    return user


def owner(user: Dict[str, Any] = Depends(viewer)) -> Dict[str, Any]:
    if user.get("role") != "owner":
        raise HTTPException(403, "Only the owner can change this. You can look around.")
    return user


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or os.environ.get("ICHOS_PUBLIC_URL", "").startswith("https://")


def _redirect_uri(request: Request, provider: str) -> str:
    base = os.environ.get("ICHOS_PUBLIC_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
    return f"{base}/api/auth/callback/{provider}"


def create_app(engine: Optional[Engine] = None) -> FastAPI:
    app = FastAPI(title="Ichos Trader", version=__version__, docs_url=None, redoc_url=None)
    started = time.time()
    holder: Dict[str, Engine] = {}
    failures: Deque[float] = deque(maxlen=PASSCODE_TRIES)

    def eng() -> Engine:
        if "engine" not in holder:
            holder["engine"] = engine or Engine()
            holder["engine"].resume_if_running()
        return holder["engine"]

    @app.middleware("http")
    async def deny_by_default(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            # Another website open in the same browser can send requests to 127.0.0.1, but it cannot
            # add a custom header without permission we never give, and a renamed address (DNS
            # rebinding) shows up in Host. Together they keep local mode's trust to this app's own page.
            if request.method not in SAFE_METHODS and request.headers.get(CHANGE_HEADER) != "1":
                return JSONResponse({"detail": "Changes must come from the trader's own page."}, status_code=403)
            if auth.mode() == "local" and (request.url.hostname or "") not in auth.LOOPBACK:
                return JSONResponse({"detail": "Open the trader at http://127.0.0.1."}, status_code=403)
        if path.startswith("/api/") and not path.startswith(PUBLIC):
            user = _who(request)
            if not user:
                return JSONResponse({"detail": "Please sign in."}, status_code=401)
            request.state.user = user
        return await call_next(request)

    # --- who am I -------------------------------------------------------------------------

    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {"ok": True, "version": __version__, "uptime_s": round(time.time() - started, 1)}

    @app.get("/api/me")
    def me(request: Request) -> Dict[str, Any]:
        user = _who(request)
        public = {k: user[k] for k in ("name", "email", "role")} if user else None
        return {"user": public, "auth_mode": auth.mode(), "providers": auth.providers(), "signed_in": bool(user)}

    @app.get("/api/auth/login/{provider}")
    def login(provider: str, request: Request):
        try:
            start = auth.login_url(provider, _redirect_uri(request, provider))
        except auth.AuthError as error:
            raise HTTPException(404, str(error)) from error
        reply = RedirectResponse(start["url"], status_code=302)
        reply.set_cookie(auth.STATE_COOKIE, auth.sign({"state": start["state"], "exp": time.time() + 600}),
                         max_age=600, httponly=True, samesite="lax", secure=_secure(request))
        return reply

    @app.get("/api/auth/callback/{provider}")
    def callback(provider: str, request: Request, code: str = "", state: str = ""):
        kept = auth.unsign(request.cookies.get(auth.STATE_COOKIE)) or {}
        if not code or not state or kept.get("state") != state:
            raise HTTPException(400, "That login link has expired. Please sign in again.")
        try:
            session = auth.finish_login(provider, code, _redirect_uri(request, provider))
        except auth.AuthError as error:
            raise HTTPException(400, str(error)) from error
        reply = RedirectResponse("/", status_code=302)
        reply.delete_cookie(auth.STATE_COOKIE)
        reply.set_cookie(auth.COOKIE, session, max_age=auth.SESSION_DAYS * 86_400, httponly=True, samesite="lax",
                         secure=_secure(request))
        return reply

    @app.post("/api/auth/passcode")
    def passcode(request: Request, body: Dict[str, Any] = Body(default={})):
        now = time.time()
        if len(failures) == PASSCODE_TRIES and now - failures[0] < PASSCODE_WINDOW:
            raise HTTPException(429, "Too many wrong passcodes. Wait ten minutes.")
        if not auth.check_passcode(str(body.get("passcode", ""))):
            failures.append(now)
            raise HTTPException(401, "That passcode is not right.")
        reply = JSONResponse({"ok": True})
        reply.set_cookie(auth.COOKIE, auth.session_for("Owner", "owner", provider="passcode"),
                         max_age=auth.SESSION_DAYS * 86_400, httponly=True, samesite="lax", secure=_secure(request))
        return reply

    @app.post("/api/auth/logout")
    def logout():
        reply = JSONResponse({"ok": True})
        reply.delete_cookie(auth.COOKIE)
        return reply

    # --- the dashboard and the switches ---------------------------------------------------

    @app.get("/api/dashboard")
    def dashboard(_: Dict[str, Any] = Depends(viewer)) -> Dict[str, Any]:
        return eng().dashboard()

    @app.post("/api/control/start")
    def start(_: Dict[str, Any] = Depends(owner)) -> Dict[str, str]:
        eng().start()
        return eng().status()

    @app.post("/api/control/stop")
    def stop(body: Dict[str, Any] = Body(default={}), _: Dict[str, Any] = Depends(owner)) -> Dict[str, str]:
        eng().stop(str(body.get("reason", ""))[:200])
        return eng().status()

    @app.post("/api/control/cycle")
    def cycle(_: Dict[str, Any] = Depends(owner)) -> Dict[str, Any]:
        result = eng().run_cycle()
        return {"ok": True, "ms": result["ms"], **eng().status()}

    @app.post("/api/control/flatten")
    def flatten(_: Dict[str, Any] = Depends(owner)) -> Dict[str, Any]:
        return {"sold": eng().flatten(), **eng().status()}

    # --- tuning, speed and the practice account -------------------------------------------

    @app.get("/api/settings")
    def get_settings(_: Dict[str, Any] = Depends(viewer)) -> Dict[str, Any]:
        return settings_mod.describe()

    @app.put("/api/settings")
    def put_settings(body: Dict[str, Any] = Body(default={}), _: Dict[str, Any] = Depends(owner)) -> Dict[str, Any]:
        unpin = body.pop("unpin", []) or []
        body.pop("running", None)  # start and stop have their own buttons, so the watchdog's word sticks
        try:
            settings_mod.save(body, unpin if isinstance(unpin, list) else [])
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return settings_mod.describe()

    @app.post("/api/speedtest")
    def speedtest(_: Dict[str, Any] = Depends(owner)) -> Dict[str, Any]:
        return eng().speedtest()

    @app.post("/api/paper/reset")
    def paper_reset(body: Dict[str, Any] = Body(default={}), _: Dict[str, Any] = Depends(owner)) -> Dict[str, Any]:
        broker = eng().broker
        if not isinstance(broker, PaperAccount):
            raise HTTPException(400, "Only the built-in practice account can be reset here.")
        try:
            cash = float(body.get("cash", settings_mod.load()["start_cash"]))
            return broker.reset(cash, settings_mod.load()["base_currency"])
        except (BrokerError, ValueError, TypeError) as error:
            raise HTTPException(400, str(error) or "Starting cash must be a number.") from error

    # --- connectors and Claude ------------------------------------------------------------

    @app.get("/api/connectors")
    def connectors(user: Dict[str, Any] = Depends(viewer)):
        rows = catalog.describe(bool(settings_mod.load()["claude"].get("enabled")))
        if user.get("role") != "owner":  # viewers see what is connected, not even the last 4
            for row in rows:
                row["masked"] = {k: {"from": v["from"]} for k, v in row["masked"].items()}
        return rows

    @app.post("/api/connectors/{cid}")
    def connect(cid: str, body: Dict[str, Any] = Body(default={}), _: Dict[str, Any] = Depends(owner)):
        try:
            row = catalog.connect(cid, {k: str(v) for k, v in body.items() if isinstance(v, (str, int))})
        except KeyError as error:
            raise HTTPException(404, "No such connector.") from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        if cid == "claude":
            settings_mod.save({"claude": {"enabled": True}})
        return row

    @app.delete("/api/connectors/{cid}")
    def disconnect(cid: str, _: Dict[str, Any] = Depends(owner)):
        try:
            catalog.disconnect(cid)
        except KeyError as error:
            raise HTTPException(404, "No such connector.") from error
        if cid == "claude":
            settings_mod.save({"claude": {"enabled": False}})
        return {"ok": True}

    @app.post("/api/claude/ask")
    def ask(body: Dict[str, Any] = Body(default={}), _: Dict[str, Any] = Depends(owner)):
        try:
            return models.ask_claude(str(body.get("question", "")), eng().dashboard(),
                                     bool(settings_mod.load()["claude"].get("enabled")))
        except models.ModelError as error:
            raise HTTPException(400, str(error)) from error

    # --- the dashboard files --------------------------------------------------------------

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "No such route.")
        target = (WEB / path).resolve()
        if path and target.is_file() and WEB.resolve() in target.parents:
            return FileResponse(target)
        index = WEB / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse("<h1>Ichos Trader</h1><p>The API is running. Build the dashboard with "
                            "<code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code>.</p>")

    return app


app = create_app()
