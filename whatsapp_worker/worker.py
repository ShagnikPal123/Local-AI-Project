"""The process that holds Nyx's WhatsApp link. Started by ``whatsapp_link.py``; never run by hand.

Why a separate process: the WhatsApp client (neonize, a Python wrapper around the Go library whatsmeow) loads a
native DLL and runs its own threads. A crash there must cost the phone link, not the engine.

Privacy: when the owner links their OWN WhatsApp, this process can see every chat they have. It drops everything
except the one conversation it was told about (the owner's "message yourself" chat, or the owner's number texting
Nyx's number) before anything leaves this process — other people's messages are never sent to the engine, logged
or shown to a model.

Protocol: one JSON object per line on stdin, one per line on stdout.
  → {"id": 1, "op": "start", "db": "...", "pair_phone": "4475...", "allow": {...}}   ← {"id": 1, "ok": true, ...}
  ← {"event": "pair_code", "code": "ABCD-EFGH"}      the code the owner confirms on their phone
  ← {"event": "connected", "me": "4475...", "me_lid": "..."}
  ← {"event": "message", "id": "...", "text": "...", "sender": "4475..."}
  ← {"event": "logged_out"} / {"event": "error", "message": "..."}
"""

from __future__ import annotations

import json
import os
import sys
import threading

_PROTO = sys.stdout                 # replaced in main(); importing this file (the tests do) must not touch fd 1
_send_lock = threading.Lock()
_client = None
_allow: dict = {}
_me: dict = {"user": "", "lid": ""}
_sent_ids: set = set()
_pair_requested = False


def _emit(message: dict) -> None:
    with _send_lock:
        _PROTO.write(json.dumps(message) + "\n")
        _PROTO.flush()


def _digits(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _user(jid) -> str:
    try:
        return str(jid.User or "")
    except Exception:  # noqa: BLE001
        return ""


def accepts(source: dict, allow: dict, me: dict, sent_ids: set, message_id: str, text: str) -> bool:
    """Whether one incoming message belongs to the owner's line. Pure, so it is tested without WhatsApp.

    ``source`` holds plain strings: chat, sender, sender_alt (users, digits or LID), from_me, group.
    self mode  — the owner linked their own WhatsApp: only their "message yourself" chat, only what they typed,
                 never Nyx's own replies (matched by id and by the reply prefix).
    number mode — Nyx has its own number: only the owner's number, never a group.
    """
    if source.get("group") or not text.strip() or message_id in sent_ids:
        return False
    prefix = str(allow.get("reply_prefix") or "")
    if prefix and text.startswith(prefix):
        return False
    if allow.get("mode") == "self":
        mine = {u for u in (me.get("user"), me.get("lid")) if u}
        return bool(source.get("from_me")) and source.get("chat", "") in mine
    owner = _digits(allow.get("owner", ""))
    if not owner or source.get("from_me"):
        return False
    return owner in {_digits(source.get("sender", "")), _digits(source.get("sender_alt", ""))}


def _on_message(client, message) -> None:
    try:
        from neonize.utils.message import extract_text

        info = message.Info
        src = info.MessageSource
        text = extract_text(message.Message) or ""
        source = {"chat": _user(src.Chat), "sender": _user(src.Sender), "sender_alt": _user(src.SenderAlt),
                  "from_me": bool(src.IsFromMe), "group": bool(src.IsGroup)}
        if not accepts(source, _allow, _me, _sent_ids, str(info.ID), text):
            return                                   # someone else's conversation: dropped here, never forwarded
        _emit({"event": "message", "id": str(info.ID), "text": text[:8000],
               "sender": _digits(source["sender_alt"] or source["sender"])})
    except Exception as error:  # noqa: BLE001
        _emit({"event": "error", "message": f"Reading a message failed: {type(error).__name__}"})


def _start(args: dict) -> dict:
    global _client, _allow, _pair_requested
    from neonize.client import NewClient
    from neonize.events import ConnectedEv, LoggedOutEv, MessageEv, PairStatusEv

    _allow = dict(args.get("allow") or {})
    pair_phone = _digits(args.get("pair_phone", ""))
    client = NewClient(args.get("db") or "whatsapp.sqlite3")
    _client = client

    def on_qr(cli, _data: bytes) -> None:
        # WhatsApp offers a QR first; we answer with phone-number pairing instead, so the owner only confirms a
        # notification on the phone rather than pointing its camera at the screen.
        global _pair_requested
        if not pair_phone or _pair_requested:
            _emit({"event": "needs_pairing"})        # an old session WhatsApp no longer accepts
            return
        _pair_requested = True

        def ask() -> None:
            try:
                code = cli.PairPhone(pair_phone, True)
                _emit({"event": "pair_code", "code": str(code)})
            except Exception as error:  # noqa: BLE001
                _emit({"event": "error", "message": f"WhatsApp refused the pairing: {error}"})

        threading.Thread(target=ask, daemon=True).start()

    client.event.qr(on_qr)

    @client.event(ConnectedEv)
    def _connected(cli, _event) -> None:
        try:
            me = cli.get_me()
            _me["user"], _me["lid"] = _user(me.JID), _user(me.LID)
        except Exception:  # noqa: BLE001
            pass
        _emit({"event": "connected", "me": _digits(_me["user"]), "me_lid": _me["lid"]})

    @client.event(PairStatusEv)
    def _paired(_cli, event) -> None:
        _emit({"event": "paired", "error": str(getattr(event, "Error", "") or "")})

    @client.event(LoggedOutEv)
    def _logged_out(_cli, _event) -> None:
        _emit({"event": "logged_out"})

    client.event(MessageEv)(_on_message)

    def run() -> None:
        try:
            client.connect()
        except Exception as error:  # noqa: BLE001
            _emit({"event": "error", "message": f"WhatsApp connection ended: {error}"})
        _emit({"event": "stopped"})

    threading.Thread(target=run, name="whatsapp-connect", daemon=True).start()
    return {"started": True}


def _handle(op: str, args: dict):
    if op == "ping":
        return {"pong": True}
    if op == "start":
        return _start(args)
    if op == "allow":
        _allow.update(args.get("allow") or {})
        return {"ok": True}
    if _client is None:
        raise RuntimeError("WhatsApp is not started.")
    if op == "send":
        to = _digits(args.get("to", ""))
        if not to:
            raise RuntimeError("No number to send to.")
        response = _client.send_message(to, str(args.get("text") or ""))
        message_id = str(getattr(response, "ID", "") or "")
        if message_id:
            _sent_ids.add(message_id)
            if len(_sent_ids) > 500:
                _sent_ids.pop()
        return {"id": message_id}
    if op == "logout":
        _client.logout()
        return {"ok": True}
    if op == "stop":
        try:
            _client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        return {"ok": True}
    raise RuntimeError(f"Unknown request {op!r}.")


def main() -> None:
    global _PROTO
    # stdout is the protocol. The library prints (and its Go core may write to fd 1), so the real stdout is kept on
    # a private descriptor and fd 1 is pointed at stderr: a stray line can never be read as a reply.
    _PROTO = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    _emit({"id": 0, "ok": True, "result": {"hello": True}})
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except ValueError:
            continue
        request_id = request.get("id")
        try:
            result = _handle(str(request.get("op") or ""), request)
            _emit({"id": request_id, "ok": True, "result": result})
        except Exception as error:  # noqa: BLE001
            _emit({"id": request_id, "ok": False, "error": f"{type(error).__name__}: {error}"})
    try:
        if _client is not None:
            _client.disconnect()
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
