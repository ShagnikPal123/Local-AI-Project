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
  ← {"event": "message", "id": "...", "text": "...", "sender": "4475...", "media": [{"path","name","mime","size","kind"}]}
  → {"id": 2, "op": "send_file", "to": "4475...", "path": "...", "kind": "image|video|document", "caption": "..."}
  ← {"event": "logged_out"} / {"event": "error", "message": "..."}
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid

_PROTO = sys.stdout                 # replaced in main(); importing this file (the tests do) must not touch fd 1
_send_lock = threading.Lock()
_client = None
_allow: dict = {}
_me: dict = {"user": "", "lid": ""}
_sent_ids: set = set()
_pair_requested = False

#: Largest file taken from the phone. Bigger ones are skipped (and the owner is told), not half-downloaded.
MAX_MEDIA_BYTES = 25 * 1024 * 1024
#: Message fields that carry a file, with the kind Nyx calls it. Stickers and contacts are left alone.
_MEDIA_FIELDS = (("imageMessage", "image"), ("documentMessage", "document"), ("videoMessage", "video"),
                 ("audioMessage", "audio"))


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


def accepts(source: dict, allow: dict, me: dict, sent_ids: set, message_id: str, text: str,
            has_media: bool = False) -> bool:
    """Whether one incoming message belongs to the owner's line. Pure, so it is tested without WhatsApp.

    ``source`` holds plain strings: chat, sender, sender_alt (users, digits or LID), from_me, group.
    self mode  — the owner linked their own WhatsApp: only their "message yourself" chat, only what they typed,
                 never Nyx's own replies (matched by id and by the reply prefix).
    number mode — Nyx has its own number: only the owner's number, never a group.
    """
    if source.get("group") or not (text.strip() or has_media) or message_id in sent_ids:
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


def media_info(message) -> dict:
    """Which file a message carries, as plain values: kind, mime, name, declared size. Empty when it has none.

    ``message`` is the protobuf ``Message``; each file kind is its own field and ``ListFields()`` is empty when unset.
    """
    for field, kind in _MEDIA_FIELDS:
        part = getattr(message, field, None)
        try:
            present = bool(part is not None and part.ListFields())
        except Exception:  # noqa: BLE001
            present = False
        if present:
            name = str(getattr(part, "fileName", "") or "") or str(getattr(part, "title", "") or "")
            return {"kind": kind, "mime": str(getattr(part, "mimetype", "") or ""), "name": name,
                    "size": int(getattr(part, "fileLength", 0) or 0)}
    return {}


def inbox_name(info: dict) -> str:
    """A fresh, harmless file name for something from the phone: its own name is only kept as a visible suffix."""
    tail = re.sub(r"[^A-Za-z0-9._-]+", "_", str(info.get("name") or info.get("kind") or "file")).strip("._")[-60:]
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}-{tail or 'file'}"


def _save_media(client, message, info: dict) -> dict:
    """Download the file into the inbox the engine named, or say why not. Never raises."""
    inbox = str(_allow.get("inbox") or "")
    if not inbox:
        return {**info, "error": "no inbox"}
    if info.get("size", 0) > MAX_MEDIA_BYTES:
        return {**info, "error": f"too big ({info['size'] // (1024 * 1024)} MB; the limit is {MAX_MEDIA_BYTES // (1024 * 1024)} MB)"}
    try:
        os.makedirs(inbox, exist_ok=True)
        path = os.path.join(inbox, inbox_name(info))
        client.download_any(message, path)
        return {**info, "path": path, "size": os.path.getsize(path)}
    except Exception as error:  # noqa: BLE001
        return {**info, "error": f"download failed ({type(error).__name__})"}


def _on_message(client, message) -> None:
    try:
        from neonize.utils.message import extract_text

        info = message.Info
        src = info.MessageSource
        text = extract_text(message.Message) or ""
        media = media_info(message.Message)
        source = {"chat": _user(src.Chat), "sender": _user(src.Sender), "sender_alt": _user(src.SenderAlt),
                  "from_me": bool(src.IsFromMe), "group": bool(src.IsGroup)}
        if not accepts(source, _allow, _me, _sent_ids, str(info.ID), text, has_media=bool(media)):
            return                                   # someone else's conversation: dropped here, never forwarded
        event = {"event": "message", "id": str(info.ID), "text": text[:8000],
                 "sender": _digits(source["sender_alt"] or source["sender"])}
        if not media:
            _emit(event)
            return

        def deliver() -> None:                       # a download can take seconds; the connection thread must not wait
            _emit({**event, "media": [_save_media(client, message.Message, media)]})

        threading.Thread(target=deliver, name="whatsapp-media", daemon=True).start()
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


def _send_file(args: dict) -> dict:
    """Send a local file to one number as a picture, video, voice/audio file or document."""
    to = _digits(args.get("to", ""))
    path = str(args.get("path") or "")
    if not to:
        raise RuntimeError("No number to send to.")
    if not os.path.isfile(path):                     # only ever a local file: a URL would make the helper fetch it
        raise RuntimeError("That file is not there any more.")
    caption = str(args.get("caption") or "")
    kind = str(args.get("kind") or "document")
    if kind == "image":
        response = _client.send_image(to, path, caption=caption or None)
    elif kind == "video":
        response = _client.send_video(to, path, caption=caption or None)
    else:                                            # documents, and sound files (they carry no caption as audio)
        response = _client.send_document(to, path, caption=caption or None,
                                         filename=str(args.get("filename") or os.path.basename(path)))
    message_id = str(getattr(response, "ID", "") or "")
    if message_id:
        _sent_ids.add(message_id)
        if len(_sent_ids) > 500:
            _sent_ids.pop()
    return {"id": message_id}


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
    if op == "send_file":
        return _send_file(args)
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
