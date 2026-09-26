"""HTTP routes for Accounts (local_accounts.py). Owner-only; absent from hosted builds (deploy_mode).

Switching saves which account opens next, then restarts the engine through the launcher so every store
reopens in the new account's folder. An engine started by hand cannot restart itself; the switch is kept
and the page says to restart Nyx.
"""

from __future__ import annotations

import functools
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

import local_accounts

router = APIRouter()


def _owner_dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
    from server import require_local_owner

    user = require_local_owner(http_request, authorization)
    # require_local_owner also lets admins in (they may restart the engine). Accounts hold the owner's own
    # chats, memory and files, so on a claimed install they are the owner's alone — like Big Kahuna.
    if user is not None:
        from auth import Role

        if getattr(user, "role", None) is not Role.OWNER:
            raise HTTPException(status_code=403, detail="Only the owner can use Accounts.")
    return user


Owner = Depends(_owner_dependency)


def _account_errors(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except local_accounts.AccountError as error:
            raise HTTPException(status_code=error.status, detail=str(error)) from error

    return wrapper


def _restart_hook():
    from server import ENGINE_HOOKS

    restart = ENGINE_HOOKS.get("restart")
    return restart if callable(restart) else None


class NewAccount(BaseModel):
    name: str
    purpose: str = ""
    password: str = ""


class AccountChange(BaseModel):
    password: str = ""
    name: Optional[str] = None
    purpose: Optional[str] = None
    new_password: Optional[str] = None
    remove_password: bool = False


class Unlock(BaseModel):
    password: str = ""


@router.get("/api/accounts")
@_account_errors
def accounts(_owner=Owner) -> Dict[str, Any]:
    listing = local_accounts.list_accounts()
    listing["can_restart"] = _restart_hook() is not None
    return listing


@router.post("/api/accounts")
@_account_errors
def create_account(body: NewAccount, _owner=Owner) -> Dict[str, Any]:
    return {"account": local_accounts.create(body.name, body.purpose, body.password)}


@router.patch("/api/accounts/{account_id}")
@_account_errors
def change_account(account_id: str, body: AccountChange, _owner=Owner) -> Dict[str, Any]:
    return {"account": local_accounts.update(
        account_id, password=body.password, name=body.name, purpose=body.purpose,
        new_password=body.new_password, remove_password=body.remove_password)}


@router.post("/api/accounts/{account_id}/switch")
@_account_errors
def switch_account(account_id: str, body: Unlock, _owner=Owner) -> Dict[str, Any]:
    result = local_accounts.switch(account_id, body.password)
    result["restarting"] = False
    if result["restart_needed"]:
        restart = _restart_hook()
        if restart is not None:
            from server import _later

            _later(restart)
            result["restarting"] = True
        else:
            result["message"] = (f"Saved. Restart Nyx to open {result['account']['name']} — this copy was started "
                                 "by hand, so it can't restart itself.")
    return result


@router.post("/api/accounts/{account_id}/remove")
@_account_errors
def remove_account(account_id: str, body: Unlock, _owner=Owner) -> Dict[str, Any]:
    return local_accounts.remove(account_id, body.password)
