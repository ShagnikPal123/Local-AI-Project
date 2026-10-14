"""Text Nyx from your phone, and let Nyx text you — over WhatsApp, tied to this one PC.

Owner (2026-10-09): "I would like a way to text my AI from my phone … I give it a number and it establishes a
connection line where the user puts in their phone … if I text on whatsapp … all I have to do is confirm as it used
the PC MAC Address or something unique to the PC so it always communicates to the correct phone/PC."

How the line is made (no account, no server, nothing public):
  1. The owner types their phone number and picks which WhatsApp Nyx uses: their OWN (they talk to Nyx in the
     "message yourself" chat) or a SEPARATE number for Nyx (a spare SIM or eSIM; they text it like a contact).
  2. Nyx asks WhatsApp for a pairing code for that number. WhatsApp pushes "Enter code to link a new device" to the
     phone — the owner taps it and confirms the code shown in Nyx. That is the only step on the phone.
  3. The link is stamped with this PC's fingerprint (a hash of Windows' MachineGuid and the network card's MAC).
     If the data folder is copied to another PC the fingerprint differs and Nyx refuses to use the link there, so
     the phone only ever reaches the PC it was paired with.

Then: whatever the owner texts arrives as a turn in a chat called "WhatsApp" (visible on the PC too), and the answer
goes back to the phone. From the PC (the Connectors tab, or Nyx's ``whatsapp_send`` tool) a message goes to the
owner's phone — and only to it: there is no way to send to anyone else from here.

Limits kept on purpose: the phone side runs behind a guard ("chat" by default: answers, web, memory, pictures — not
the PC's files, apps, shell, trading orders or settings) because a phone is easier to lose than a PC; the owner can
raise it to "full". WhatsApp links a device through its unofficial multi-device protocol (whatsmeow); WhatsApp may
restrict numbers that use unofficial clients, which is why a separate number for Nyx is offered.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import platform
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import whatsapp_files as files
import whatsapp_lanes as lanes
from paths import data_path

log = logging.getLogger("nyx.whatsapp")

STATE_FILE = "whatsapp/link.json"
SESSION_DB = "whatsapp/session.sqlite3"
#: Where the helper puts files the phone sends, until they are checked and moved into Nyx's uploads.
INBOX = "whatsapp/inbox"
WORKER = Path(__file__).resolve().parent / "whatsapp_worker" / "worker.py"
PACKAGE = "neonize==0.5.2"
#: Starts every message Nyx sends, so in the "message yourself" chat its replies are told apart from the owner's.
REPLY_PREFIX = "🌙 "
CHUNK = 3500
LOG_KEEP = 40
ALLOW_LEVELS = ("chat", "full")
#: What survives pairing again (a new phone) or unlinking: the owner's choices and their chats, never the keys.
KEEP_ON_PAIR = ("allow", "chat_id", "log", "notify", "lane", "listing", "lane_chats", "linked_chats")
KEEP_ON_UNLINK = ("allow", "chat_id", "log", "lane_chats", "linked_chats")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PHONE_NOTE = (
    "[WhatsApp] The owner is texting you from their phone and will read this on WhatsApp. Answer in short plain text: "
    "no tables, no headings, no code blocks unless asked. *single asterisks* make bold there. If something needs the PC "
    "(a file, an app, a long document), say so briefly and offer to have it ready on the PC."
)

HELP = lanes.HELP


class WhatsAppError(RuntimeError):
    """Something the owner can act on, said in their words."""


# ---------------------------------------------------------------------------
# This PC
# ---------------------------------------------------------------------------


def _machine_guid() -> str:
    if os.name != "nt":
        for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                return Path(candidate).read_text(encoding="utf-8").strip()
            except OSError:
                continue
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                            winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)) as key:
            return str(winreg.QueryValueEx(key, "MachineGuid")[0])
    except OSError:
        return ""


def device_fingerprint() -> str:
    """A hash naming this PC. The MAC and MachineGuid themselves are never stored or sent anywhere."""
    raw = f"nyx-whatsapp|{_machine_guid()}|{uuid.getnode():012x}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def pc_name() -> str:
    return platform.node() or "this PC"


def digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def valid_number(value: Any) -> str:
    """International format without the plus: country code then number, 8–15 digits (E.164)."""
    number = digits(value)
    if str(value or "").strip().startswith("00"):
        number = number[2:]
    if not 8 <= len(number) <= 15 or number.startswith("0"):
        raise WhatsAppError("Type the number with its country code, e.g. +44 7700 900123 or +1 555 010 0199.")
    return number


def masked(number: str) -> str:
    number = digits(number)
    return f"+{number[:2]}•••{number[-3:]}" if len(number) > 5 else ""


def sdk_installed() -> bool:
    return importlib.util.find_spec("neonize") is not None


def to_whatsapp(text: str) -> str:
    """Markdown → WhatsApp's own marks: **bold** → *bold*, headings to bold lines, code fences dropped."""
    text = re.sub(r"```[a-zA-Z0-9_-]*\n?", "", text or "")
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"^#{1,6}\s*(.+)$", r"*\1*", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)
    return text.strip()


def chunks(text: str, size: int = CHUNK) -> List[str]:
    """WhatsApp caps a message at ~4096 characters; split on paragraph or line ends where possible."""
    text = text.strip()
    parts: List[str] = []
    while len(text) > size:
        cut = max(text.rfind("\n\n", 0, size), text.rfind("\n", 0, size))
        if cut < size // 2:
            cut = text.rfind(" ", 0, size)
        if cut < size // 2:
            cut = size
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


# ---------------------------------------------------------------------------
# The phone side's guard
# ---------------------------------------------------------------------------

#: Tools that stay usable from the phone at the "chat" level even though their category is not.
PHONE_EXTRA_TOOLS = frozenset({"whatsapp_send", "whatsapp_status", "memory_search", "remember", "set_reminder",
                               # Mail: reading is safe from a phone, and "email me this" can only reach the owner's own
                               # connected address. email_send / email_reply to other people stay behind "full".
                               "email_list", "email_read", "email_accounts", "email_to_me"})


def phone_guard(name: str, category: str) -> None:
    """Called by ``tools.call_tool`` before every tool of a phone turn at the "chat" level. Deny by default."""
    from freewill import may_use
    from permissions import PermissionDenied

    if name in PHONE_EXTRA_TOOLS or may_use(name, category):
        return
    raise PermissionDenied(
        f"Blocked from the phone: {name} ({category or 'general'}) needs the PC. Tell the owner what you would do; "
        "they can do it at the PC, or raise the phone's access to Full in Connectors → WhatsApp.")


# ---------------------------------------------------------------------------
# The helper process
# ---------------------------------------------------------------------------


class WorkerTransport:
    """The WhatsApp helper: requests matched by id, plus the events it sends on its own."""

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._next = 0
        self._waiting: Dict[int, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.on_event: Callable[[Dict[str, Any]], None] = lambda _event: None

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _spawn(self) -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        # The helper's own log, for when the owner asks why it will not connect. Local, git-ignored, one run long.
        self._log = open(data_path("whatsapp/helper.log"), "w", encoding="utf-8", errors="replace")
        self._proc = subprocess.Popen([sys.executable, str(WORKER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=self._log, text=True, encoding="utf-8", bufsize=1, env=env,
                                      cwd=str(data_path("whatsapp").resolve()), creationflags=_NO_WINDOW)
        hello = threading.Event()
        self._waiting[0] = {"event": hello, "reply": None}
        threading.Thread(target=self._read, args=(self._proc,), name="nyx-whatsapp-reader", daemon=True).start()
        if not hello.wait(30):
            self.close()
            raise WhatsAppError("The WhatsApp helper did not start.")

    def _read(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout or []:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if "event" in message:
                try:
                    self.on_event(message)
                except Exception:  # noqa: BLE001 - one bad event must not stop the reader
                    log.warning("WhatsApp event failed", exc_info=True)
                continue
            with self._lock:
                slot = self._waiting.get(int(message.get("id", -1)))
            if slot is not None:
                slot["reply"] = message
                slot["event"].set()
        with self._lock:
            for slot in self._waiting.values():
                slot["event"].set()
        try:
            self.on_event({"event": "stopped"})
        except Exception:  # noqa: BLE001
            pass

    def request(self, op: str, timeout: float = 60, **args: Any) -> Any:
        if not self.alive():
            self._spawn()
        with self._lock:
            self._next += 1
            request_id = self._next
            slot = {"event": threading.Event(), "reply": None}
            self._waiting[request_id] = slot
        try:
            assert self._proc is not None and self._proc.stdin is not None
            self._proc.stdin.write(json.dumps({"id": request_id, "op": op, **args}) + "\n")
            self._proc.stdin.flush()
            if not slot["event"].wait(timeout):
                raise WhatsAppError("WhatsApp did not answer in time.")
            reply = slot["reply"]
            if reply is None:
                raise WhatsAppError("The WhatsApp helper stopped.")
            if not reply.get("ok"):
                raise WhatsAppError(str(reply.get("error") or "It failed."))
            return reply.get("result")
        except (OSError, ValueError) as error:
            raise WhatsAppError(f"Could not reach the WhatsApp helper: {error}") from error
        finally:
            with self._lock:
                self._waiting.pop(request_id, None)

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=15)
        except Exception:  # noqa: BLE001 - a stuck helper is ended
            proc.kill()
        log_file = getattr(self, "_log", None)
        if log_file is not None:
            log_file.close()


# ---------------------------------------------------------------------------
# The link
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _blank() -> Dict[str, Any]:
    return {"status": "unpaired", "phone": "", "mode": "self", "nyx_number": "", "device": "", "pc": "",
            "paired_at": "", "enabled": True, "allow": "chat", "chat_id": "", "log": [],
            # Where the next text goes (see whatsapp_lanes.py), the chat ids behind the last /chats list, the phone's own
            # chat per avatar, and the PC chats the owner connected to WhatsApp (shown as a badge on those chats).
            "lane": lanes.lane(), "listing": [], "lane_chats": {}, "linked_chats": [],
            # Things Nyx may text the owner about without being asked (all off until they switch one on).
            "notify": {"office": False}}


class WhatsAppLink:
    """One line between this PC and the owner's phone. ``transport`` and ``turn`` are swapped for fakes in tests."""

    def __init__(self, transport: Any = None, turn: Optional[Callable[..., str]] = None,
                 state_path: Optional[Path] = None, chats: Any = None, avatars: Any = None) -> None:
        self.transport = transport or WorkerTransport()
        self.transport.on_event = self._on_event
        self._turn = turn
        self.chats = chats or ServerChats()
        self.avatars = avatars or AvatarBook()
        self._path = state_path or data_path(STATE_FILE)
        self._lock = threading.RLock()
        self._busy = threading.Lock()
        self.connected = False
        self.pair_code = ""
        self.last_error = ""
        self._me = ""
        self.state = self._load()

    # -- storage ------------------------------------------------------------

    def _load(self) -> Dict[str, Any]:
        try:
            saved = json.loads(self._path.read_text(encoding="utf-8"))
            return {**_blank(), **saved} if isinstance(saved, dict) else _blank()
        except (OSError, ValueError):
            return _blank()

    def _save(self) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temp, self._path)

    def _note(self, direction: str, text: str) -> None:
        with self._lock:
            self.state["log"] = (self.state.get("log") or [])[-(LOG_KEEP - 1):] + [
                {"at": _now(), "dir": direction, "text": text[:300]}]
            self._save()

    # -- what the owner sees ------------------------------------------------

    def device_ok(self) -> bool:
        return bool(self.state.get("device")) and self.state["device"] == device_fingerprint()

    def status(self) -> Dict[str, Any]:
        state = self.state
        linked = state.get("status") == "linked"
        moved = linked and not self.device_ok()
        return {
            "installed": sdk_installed(),
            "status": "moved" if moved else state.get("status", "unpaired"),
            "connected": self.connected and not moved,
            "pair_code": self.pair_code if state.get("status") == "pairing" else "",
            "phone": masked(state.get("phone", "")),
            "mode": state.get("mode", "self"),
            "nyx_number": masked(state.get("nyx_number", "")),
            "pc": state.get("pc") or "",
            "this_pc": pc_name(),
            "paired_at": state.get("paired_at", ""),
            "enabled": bool(state.get("enabled", True)),
            "allow": state.get("allow", "chat"),
            "notify": dict(state.get("notify") or {"office": False}),
            "chat_id": state.get("chat_id", ""),
            "lane": dict(state.get("lane") or lanes.lane()),
            "lane_name": self.lane_name(),
            "linked_chats": list(state.get("linked_chats") or []),
            "log": list(state.get("log") or [])[-20:],
            "error": self.last_error,
            "moved": moved,
        }

    # -- pairing --------------------------------------------------------------

    def begin_pairing(self, phone: str, mode: str = "self", nyx_number: str = "") -> Dict[str, Any]:
        if not sdk_installed():
            raise WhatsAppError("Set up WhatsApp first (one download, about 7 MB).")
        if mode not in ("self", "number"):
            raise WhatsAppError("Choose your own WhatsApp or a separate number for Nyx.")
        owner = valid_number(phone)
        nyx = valid_number(nyx_number) if mode == "number" else owner
        if mode == "number" and nyx == owner:
            raise WhatsAppError("Nyx's number must be different from yours — or choose 'My own WhatsApp'.")
        self.stop()
        session = data_path(SESSION_DB)
        if session.exists():               # an old link's keys: kept aside, never reused for a new pairing
            os.replace(session, session.with_suffix(".sqlite3.old"))
        with self._lock:
            keep = {k: self.state.get(k) for k in KEEP_ON_PAIR if self.state.get(k) is not None}
            self.state = {**_blank(), **keep, "status": "pairing", "phone": owner, "mode": mode,
                          "nyx_number": nyx if mode == "number" else "", "device": device_fingerprint(),
                          "pc": pc_name()}
            self._save()
        self.pair_code = ""
        self.last_error = ""
        self._start_worker(pair_phone=nyx)
        return self.status()

    def _inbox(self) -> Path:
        return data_path(INBOX)

    def _allow_rule(self) -> Dict[str, Any]:
        return {"mode": self.state.get("mode", "self"), "owner": self.state.get("phone", ""),
                "reply_prefix": REPLY_PREFIX, "inbox": str(self._inbox().resolve())}

    def _start_worker(self, pair_phone: str = "") -> None:
        self.transport.request("start", timeout=60, db=str(data_path(SESSION_DB).resolve()),
                               pair_phone=pair_phone, allow=self._allow_rule())

    def start_if_ready(self) -> bool:
        """At engine start: reconnect a link made on THIS PC. A link copied from another PC stays off."""
        if self.state.get("status") != "linked" or not self.state.get("enabled", True):
            return False
        if not self.device_ok():
            self.last_error = (f"This WhatsApp link was made on {self.state.get('pc') or 'another PC'}. "
                               "Pair again to use it here.")
            return False
        if not sdk_installed() or not data_path(SESSION_DB).exists():
            return False
        try:
            self._start_worker()
            return True
        except WhatsAppError as error:
            self.last_error = str(error)
            return False

    def stop(self) -> None:
        if getattr(self.transport, "alive", lambda: False)():
            try:
                self.transport.request("stop", timeout=10)
            except WhatsAppError:
                pass
            self.transport.close()
        self.connected = False

    def unlink(self) -> Dict[str, Any]:
        """Sign this PC out of WhatsApp (it disappears from Linked devices on the phone) and forget the line."""
        if self.connected:
            try:
                self.transport.request("logout", timeout=20)
            except WhatsAppError:
                pass
        self.stop()
        session = data_path(SESSION_DB)
        if session.exists():
            os.replace(session, session.with_suffix(".sqlite3.old"))
        with self._lock:
            keep = {k: self.state.get(k) for k in KEEP_ON_UNLINK if self.state.get(k) is not None}
            self.state = {**_blank(), **keep}
            self._save()
        self.pair_code = ""
        return self.status()

    def update(self, *, enabled: Optional[bool] = None, allow: Optional[str] = None,
               notify_office: Optional[bool] = None) -> Dict[str, Any]:
        with self._lock:
            if notify_office is not None:
                self.state["notify"] = {**(self.state.get("notify") or {}), "office": bool(notify_office)}
            if allow is not None:
                if allow not in ALLOW_LEVELS:
                    raise WhatsAppError("The phone's access is 'chat' or 'full'.")
                self.state["allow"] = allow
            if enabled is not None:
                self.state["enabled"] = bool(enabled)
            self._save()
        if enabled is False:
            self.stop()
        elif enabled is True and not self.connected:
            self.start_if_ready()
        return self.status()

    # -- events from the helper ----------------------------------------------

    def _on_event(self, event: Dict[str, Any]) -> None:
        """Runs on the helper's reader thread. Anything that sends goes to its own thread: a request made here
        would wait for a reply only this same thread can read (a 60-second hang, then a failed send)."""
        kind = event.get("event")
        if kind == "pair_code":
            self.pair_code = str(event.get("code") or "")
        elif kind == "connected":
            self.connected = True
            self._me = digits(event.get("me"))
            self.last_error = ""
            if self.state.get("status") == "pairing":
                threading.Thread(target=self._finish_pairing, name="nyx-whatsapp-paired", daemon=True).start()
        elif kind == "logged_out":
            self.connected = False
            with self._lock:
                self.state["status"] = "unpaired"
                self._save()
            self.last_error = "WhatsApp signed this PC out (removed from Linked devices on the phone)."
        elif kind == "stopped":
            self.connected = False
        elif kind == "needs_pairing" and self.state.get("status") == "linked":
            self.last_error = "WhatsApp no longer accepts this PC's link (it was removed on the phone). Pair again."
        elif kind == "error":
            self.last_error = str(event.get("message") or "")[:300]
        elif kind == "message":
            text = str(event.get("text") or "")
            media = event.get("media") or None
            threading.Thread(target=self.handle_incoming, args=(text, media), name="nyx-whatsapp-turn",
                             daemon=True).start()

    def _finish_pairing(self) -> None:
        expected = self.state.get("nyx_number") or self.state.get("phone")
        if self._me and expected and self._me != expected:
            self.last_error = (f"WhatsApp linked {masked(self._me)}, not {masked(expected)}. Unlink and pair the "
                               "number you meant.")
        with self._lock:
            self.state.update(status="linked", paired_at=_now(), device=device_fingerprint(), pc=pc_name())
            self._save()
        self.pair_code = ""
        self.send(f"Linked to {pc_name()}. Text me here any time — /help for the shortcuts.", origin="nyx")

    # -- talking ----------------------------------------------------------------

    def send(self, text: str, origin: str = "pc") -> Dict[str, Any]:
        """Send to the owner's phone — the one number this line has. There is no other recipient."""
        text = to_whatsapp(text)
        if not text:
            raise WhatsAppError("Nothing to send.")
        if self.state.get("status") != "linked" or not self.device_ok():
            raise WhatsAppError("WhatsApp is not linked on this PC yet.")
        if not self.connected:
            raise WhatsAppError("WhatsApp is linked but not connected right now. Check the PC is online.")
        to = self.state.get("phone", "")
        for part in chunks(text):
            self.transport.request("send", timeout=60, to=to, text=REPLY_PREFIX + part)
        self._note("out", text)
        return {"sent": True, "to": masked(to), "parts": len(chunks(text)), "origin": origin}

    def send_file(self, path: str, caption: str = "", origin: str = "pc") -> Dict[str, Any]:
        """Send one file or picture from this PC to the owner's phone — the one number this line has.

        Refused (in plain words) for protected credential files, anything the file check blocks, folders and files too
        big for WhatsApp, because a phone is easier to lose than a PC."""
        if self.state.get("status") != "linked" or not self.device_ok():
            raise WhatsAppError("WhatsApp is not linked on this PC yet.")
        if not self.connected:
            raise WhatsAppError("WhatsApp is linked but not connected right now. Check the PC is online.")
        try:
            resolved, size = files.check_outgoing(path)
        except files.FileRefused as error:
            raise WhatsAppError(str(error)) from error
        name = Path(resolved).name
        kind = files.kind_for(resolved)
        # The caption always starts with the reply mark: in the "message yourself" chat that is how Nyx's own file
        # is told apart from one the owner sent.
        shown = REPLY_PREFIX + (to_whatsapp(caption) or name)
        to = self.state.get("phone", "")
        self.transport.request("send_file", timeout=180, to=to, path=resolved, kind=kind, caption=shown, filename=name)
        self._note("out", f"[{kind}] {name}")
        return {"sent": True, "to": masked(to), "name": name, "kind": kind, "size": size, "origin": origin}

    def handle_incoming(self, text: str, media: Optional[List[Dict[str, Any]]] = None) -> None:
        """One message from the owner's phone: a shortcut, a question for one avatar, or a turn in the current lane.

        ``media`` is what came with it (pictures, documents), already downloaded by the helper into the inbox."""
        text = (text or "").strip()
        if not (text or media) or not self.state.get("enabled", True) or not self.device_ok():
            self._discard(media)
            return
        self._note("in", text or f"[{len(media or [])} file(s)]")
        _notify_pc(text or "a file")
        try:
            command = lanes.parse(text)
            if command is not None:
                self._discard(media)
                self._shortcut(command)
                return
            target = self.current_lane()
            mention = lanes.split_mention(text)
            avatar = self.avatars.find(mention[0]) if mention else None
            if avatar is not None:                     # "@Mira …": answered by Mira, the lane stays where it was
                target, text = lanes.lane(lanes.AVATAR, avatar["id"]), mention[1]
            kept, notes = files.keep_incoming(media or [], self._inbox())
            if notes:
                self.send("\n".join(notes), origin="nyx")
            if media and not kept and not text:
                return                                 # nothing usable came, and the notes above said why
            text = files.incoming_text(text, len(kept), [str(m.get("kind") or "") for m in media or []])
            with self._busy:                           # one phone turn at a time, in the order sent
                speaker, reply = self._answer(text, target, kept)
            words, pictures = files.split_pictures(reply or "")
            if words or not pictures:
                self.send(lanes.tag(speaker, words or "(I had nothing to say to that — try asking another way.)"),
                          origin="nyx")
            self._send_pictures(pictures)
        except WhatsAppError as error:
            self.last_error = str(error)
        except Exception as error:  # noqa: BLE001 - the phone gets a plain message, the log the detail
            log.warning("WhatsApp turn failed", exc_info=True)
            try:
                self.send(f"Something went wrong on the PC: {type(error).__name__}.", origin="nyx")
            except WhatsAppError:
                pass

    # -- lanes: which chat or avatar the next text goes to ------------------------------

    def current_lane(self) -> Dict[str, str]:
        """Where the next text goes. A chat or avatar that has been deleted falls back to the main chat."""
        saved = self.state.get("lane") or {}
        current = lanes.lane(str(saved.get("kind") or lanes.GENERAL), str(saved.get("id") or ""))
        if current["kind"] == lanes.CHAT and not self.chats.exists(current["id"]):
            return lanes.lane()
        if current["kind"] == lanes.AVATAR and self.avatars.get(current["id"]) is None:
            return lanes.lane()
        return current

    def lane_name(self, current: Optional[Dict[str, str]] = None) -> str:
        current = current or self.current_lane()
        if current["kind"] == lanes.AVATAR:
            return str((self.avatars.get(current["id"]) or {}).get("name") or "")
        if current["kind"] == lanes.CHAT:
            return self.chats.title(current["id"])
        return ""

    def set_lane(self, kind: str, ident: str = "") -> Dict[str, Any]:
        """Point the phone at the main chat, one PC chat, or one avatar (also what the PC's own buttons call)."""
        if kind == lanes.CHAT:
            if not self.chats.exists(ident):
                raise WhatsAppError("There is no such chat.")
            self.link_chat(ident, switch=False)
        elif kind == lanes.AVATAR:
            if self.avatars.get(ident) is None:
                raise WhatsAppError("There is no such avatar.")
        with self._lock:
            self.state["lane"] = lanes.lane(kind, ident)
            self._save()
        return self.status()

    def link_chat(self, chat_id: str, switch: bool = True) -> Dict[str, Any]:
        """Connect a PC chat to WhatsApp: it shows the WhatsApp badge, and the phone can continue it with /chat."""
        if not self.chats.exists(chat_id):
            raise WhatsAppError("There is no such chat.")
        with self._lock:
            linked = list(self.state.get("linked_chats") or [])
            if chat_id not in linked:
                self.state["linked_chats"] = linked + [chat_id]
            if switch:
                self.state["lane"] = lanes.lane(lanes.CHAT, chat_id)
            self._save()
        return self.status()

    def unlink_chat(self, chat_id: str) -> Dict[str, Any]:
        with self._lock:
            self.state["linked_chats"] = [c for c in (self.state.get("linked_chats") or []) if c != chat_id]
            lane = self.state.get("lane") or {}
            if lane.get("kind") == lanes.CHAT and lane.get("id") == chat_id:
                self.state["lane"] = lanes.lane()
            self._save()
        return self.status()

    def is_chat_linked(self, chat_id: str) -> bool:
        return chat_id in (self.state.get("linked_chats") or [])

    def _shortcut(self, command: "lanes.Command") -> None:
        name, arg = command.name, command.arg
        if name == "help":
            self.send(HELP, origin="nyx")
        elif name == "status":
            self.send(f"Tied to {self.state.get('pc') or pc_name()}. Phone access: {self.state.get('allow')}."
                      f" Linked {str(self.state.get('paired_at', ''))[:10]}. "
                      + lanes.describe(self.current_lane(), self.lane_name()), origin="nyx")
        elif name == "where":
            self.send(lanes.describe(self.current_lane(), self.lane_name()), origin="nyx")
        elif name == "pause":
            # Stays connected so the PC can still text the phone; it just stops answering.
            with self._lock:
                self.state["enabled"] = False
                self._save()
            self.send("Paused. Resume it in Connectors → WhatsApp on the PC.", origin="nyx")
        elif name == "new":
            self._fresh_conversation()
        elif name == "general":
            self.set_lane(lanes.GENERAL)
            self.send("Back in the main WhatsApp chat.", origin="nyx")
        elif name == "chats":
            text, ids = lanes.format_chats(self.chats.recent(lanes.CHATS_SHOWN), self._current_chat_id(),
                                           self.state.get("linked_chats") or [])
            with self._lock:
                self.state["listing"] = ids
                self._save()
            self.send(text, origin="nyx")
        elif name == "chat":
            self._continue_chat(arg)
        elif name == "avatars":
            current = self.current_lane()
            self.send(lanes.format_avatars(self.avatars.list(), current["id"] if current["kind"] == lanes.AVATAR else ""),
                      origin="nyx")
        elif name == "avatar":
            self._switch_avatar(arg)
        elif name == "newavatar":
            self._make_avatar(arg)

    def _current_chat_id(self) -> str:
        current = self.current_lane()
        return current["id"] if current["kind"] == lanes.CHAT else (self.state.get("chat_id") or "")

    def _fresh_conversation(self) -> None:
        current = self.current_lane()
        with self._lock:
            if current["kind"] == lanes.AVATAR:
                (self.state.get("lane_chats") or {}).pop(f"avatar:{current['id']}", None)
            else:
                self.state["chat_id"] = ""
                self.state["lane"] = lanes.lane()
            self._save()
        self.send("Fresh conversation started.", origin="nyx")

    def _continue_chat(self, arg: str) -> None:
        if not arg:
            self.send("Which chat? Text /chats to see the list, then /chat 2.", origin="nyx")
            return
        chats = self.chats.recent(200)
        chat = lanes.pick_chat(arg, self.state.get("listing") or [], chats)
        if chat is None:
            self.send(f"I could not tell which chat “{arg[:40]}” is. Text /chats, then /chat and its number.", origin="nyx")
            return
        self.link_chat(chat["id"])
        said = f" The last thing in it: {chat['preview']}" if chat.get("preview") else ""
        self.send(f"Continuing “{chat.get('title') or chat['id']}”.{said}", origin="nyx")

    def _switch_avatar(self, arg: str) -> None:
        if not arg:
            self.send(lanes.describe(self.current_lane(), self.lane_name()), origin="nyx")
            return
        avatar = self.avatars.find(arg)
        if avatar is None:
            names = ", ".join(a["name"] for a in self.avatars.list()) or "none yet"
            self.send(f"No avatar called “{arg[:40]}”. Your avatars: {names}.", origin="nyx")
            return
        self.set_lane(lanes.AVATAR, avatar["id"])
        self.send(lanes.tag(avatar["name"], f"Hi, I am {avatar['name']}. Everything you text now goes to me. "
                                            "/general takes you back."), origin="nyx")

    def _make_avatar(self, arg: str) -> None:
        parsed = lanes.split_new_avatar(arg)
        if parsed is None:
            self.send("Say it like this: /newavatar Mira: watches my inbox and tells me what matters", origin="nyx")
            return
        try:
            avatar = self.avatars.create(parsed[0], parsed[1])
        except Exception as error:  # noqa: BLE001 - avatars.AvatarError and friends: the owner reads the reason
            self.send(f"Could not make that avatar: {error}", origin="nyx")
            return
        self.set_lane(lanes.AVATAR, avatar["id"])
        self.send(lanes.tag(avatar["name"], f"Made. {lanes.NEW_AVATAR_NOTE} You are talking to {avatar['name']} now."),
                  origin="nyx")

    # -- the turn itself ---------------------------------------------------------------

    def _answer(self, text: str, target: Dict[str, str], attachments: Optional[List[str]] = None) -> "tuple[str, str]":
        """Run one turn in ``target`` and return (who is speaking, the reply). The speaker is blank in the main chat."""
        speaker = self.lane_name(target) if target["kind"] != lanes.GENERAL else ""
        if self._turn is not None:
            extra = {"attachments": attachments} if attachments else {}
            return speaker, self._turn(text, lane=target, **extra)
        return speaker, self._run_turn(text, target, attachments)

    def _discard(self, media: Optional[List[Dict[str, Any]]]) -> None:
        """Files that arrived with something that is not a question (a shortcut, a paused line) are not kept."""
        for item in media or []:
            try:
                os.remove(str(item.get("path") or ""))
            except OSError:
                pass

    def _send_pictures(self, upload_ids: List[str]) -> None:
        """Pictures Nyx made this turn go to the phone as pictures, not as links to the PC."""
        import uploads

        for upload_id in upload_ids[:6]:
            record = uploads.get_upload(upload_id)
            if record is None:
                continue
            try:
                self.send_file(record["path"], caption=str(record.get("name") or ""), origin="nyx")
            except WhatsAppError as error:
                self.last_error = str(error)

    def _run_turn(self, text: str, target: Optional[Dict[str, str]] = None,
                  attachments: Optional[List[str]] = None) -> str:
        import server

        target = target or lanes.lane()
        store = server._shared_chat_store()
        avatar = self.avatars.get(target["id"]) if target["kind"] == lanes.AVATAR else None
        if target["kind"] == lanes.CHAT:
            chat_id = target["id"]
        elif avatar is not None:
            chat_id = (self.state.get("lane_chats") or {}).get(f"avatar:{avatar['id']}") or ""
        else:
            chat_id = self.state.get("chat_id") or ""
        if not chat_id or not store.exists(chat_id):
            chat_id = store.create(title=f"WhatsApp · {avatar['name']}" if avatar else "WhatsApp", activate=False)
            with self._lock:
                if avatar is not None:
                    self.state.setdefault("lane_chats", {})[f"avatar:{avatar['id']}"] = chat_id
                else:
                    self.state["chat_id"] = chat_id
                self._save()
        service = server._get_service(chat_id)
        guard_before = getattr(service, "tool_guard", None)
        guards = [] if self.state.get("allow", "chat") == "full" else [phone_guard]
        if avatar is not None:
            guards.append(self.avatars.guard(avatar))     # the avatar's own Allow / Ask / Never rules still apply
        if guards:
            service.tool_guard = _all_of(guards)
        try:
            service.set_turn_context(PHONE_NOTE + (("\n\n" + self.avatars.note(avatar)) if avatar is not None else ""))
            result = service.chat_turn(text, sink=lambda _event: None, role="local", turn_id=uuid.uuid4().hex[:12],
                                       attachments=attachments or None,
                                       provider="ollama" if avatar is not None and avatar.get("model") == "local" else None)
        finally:
            service.tool_guard = guard_before
        return str((result or {}).get("reply") or "") if isinstance(result, dict) else str(result or "")


def _all_of(guards: List[Callable[[str, str], None]]) -> Callable[[str, str], None]:
    """One tool guard from several: a tool runs only if every guard lets it through."""
    def guard(name: str, category: str) -> None:
        for each in guards:
            each(name, category)
    return guard


class ServerChats:
    """The PC's chat list, reached lazily so importing this file never loads the server (tests replace the whole thing)."""

    @staticmethod
    def _store() -> Any:
        import server

        return server._shared_chat_store()

    def recent(self, limit: int = 9) -> List[Dict[str, Any]]:
        return [c for c in self._store().summaries() if c.get("kind", "chat") == "chat"][:limit]

    def exists(self, chat_id: str) -> bool:
        return bool(chat_id) and bool(self._store().exists(chat_id))

    def title(self, chat_id: str) -> str:
        for chat in self._store().summaries():
            if chat["id"] == chat_id:
                return str(chat.get("title") or chat_id)
        return ""


class AvatarBook:
    """The owner's avatars as the phone needs them. All of it is ``avatars.py``'s public surface; nothing here edits
    that module, so the Avatars team can change its insides freely."""

    @staticmethod
    def _module() -> Any:
        import avatars

        return avatars

    def list(self) -> List[Dict[str, Any]]:
        return self._module().list_avatars()

    def get(self, avatar_id: str) -> Optional[Dict[str, Any]]:
        return self._module().get(avatar_id) if avatar_id else None

    def find(self, name: str) -> Optional[Dict[str, Any]]:
        try:
            return self._module().find(name)
        except Exception:  # noqa: BLE001 - "@someone" that is not an avatar is just text
            return None

    def create(self, name: str, does: str) -> Dict[str, Any]:
        module = self._module()
        return module.create({"name": name, "does": does, "main": "custom",
                              "schedule": {"mode": "on_call", "every_minutes": 60},
                              "functions": {"talk": "allow", "web": module.FUNCTIONS["web"]["default"]}})

    def guard(self, avatar: Dict[str, Any]) -> Callable[[str, str], None]:
        return self._module().AvatarGuard(avatar)

    def note(self, avatar: Dict[str, Any]) -> str:
        return self._module().note_for(avatar)


def _notify_pc(text: str) -> None:
    """A toast on the PC, so a text from the phone is noticed there too; the answer lands in the WhatsApp chat."""
    try:
        from landscape_tools import tool_ui_notify

        tool_ui_notify(f"From your phone: {text[:120]}", "info")
    except Exception:  # noqa: BLE001 - a missed toast never costs the reply
        pass


def notify(kind: str, text: str) -> bool:
    """Text the owner about something they switched on (e.g. "office": a job finished). Never raises, never waits:
    a phone that is off, unlinked or not opted in simply gets nothing."""
    current = _LINK
    if current is None or not (current.state.get("notify") or {}).get(kind):
        return False
    if current.state.get("status") != "linked" or not current.connected:
        return False

    def send() -> None:
        try:
            current.send(text, origin=f"notify:{kind}")
        except Exception:  # noqa: BLE001
            log.info("WhatsApp notice not sent", exc_info=True)

    threading.Thread(target=send, name="nyx-whatsapp-notice", daemon=True).start()
    return True


_LINK: Optional[WhatsAppLink] = None
_LINK_LOCK = threading.Lock()


def link() -> WhatsAppLink:
    global _LINK
    with _LINK_LOCK:
        if _LINK is None:
            _LINK = WhatsAppLink()
        return _LINK


def start_in_background() -> None:
    """Called at engine start: reconnect without holding up the server."""
    threading.Thread(target=lambda: link().start_if_ready(), name="nyx-whatsapp-start", daemon=True).start()


def install() -> Dict[str, Any]:
    """Install the WhatsApp client into Nyx's own Python — only from the owner's button."""
    if sdk_installed():
        return {"installed": True}
    done = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", PACKAGE],
                          capture_output=True, text=True, timeout=900, creationflags=_NO_WINDOW)
    if done.returncode != 0:
        raise WhatsAppError("The WhatsApp client did not install: " + (done.stderr or done.stdout)[-400:])
    importlib.invalidate_caches()
    remove_stray_tests()
    return {"installed": sdk_installed()}


def remove_stray_tests() -> bool:
    """linkpreview (pulled in by neonize) ships its own test suite as a top-level ``tests`` package in site-packages.
    That shadows Nyx's ``tests`` folder (``from tests.conftest import …`` stops working), so it is removed — only
    when linkpreview's install record says the folder is its own."""
    import shutil
    import sysconfig

    site = Path(sysconfig.get_paths()["purelib"])
    stray = site / "tests"
    if not stray.is_dir():
        return False
    for record in site.glob("linkpreview-*.dist-info/RECORD"):
        try:
            owned = any(line.startswith("tests/__init__.py") for line in record.read_text(encoding="utf-8").splitlines())
        except OSError:
            continue
        if owned:
            shutil.rmtree(stray, ignore_errors=True)
            return True
    return False


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def tool_send(text: str) -> str:
    try:
        result = link().send(text, origin="tool")
        return f"Sent to the owner's phone ({result['to']}) on WhatsApp."
    except WhatsAppError as error:
        return f"Not sent: {error}"


def tool_send_file(path: str, caption: str = "") -> str:
    try:
        result = link().send_file(path, caption, origin="tool")
        return f"Sent {result['name']} to the owner's phone ({result['to']}) on WhatsApp."
    except WhatsAppError as error:
        return f"Not sent: {error}"


def tool_status() -> str:
    s = link().status()
    if s["status"] != "linked":
        return "WhatsApp is not linked. The owner can link it in Connectors → WhatsApp."
    return (f"WhatsApp is linked to {s['phone']} on {s['pc']}, "
            f"{'connected' if s['connected'] else 'not connected right now'}; phone access: {s['allow']}.")


def tool_email_to_me(subject: str, body: str, attachments: Any = None, account: str = "") -> str:
    """Email something to the owner's OWN connected address. Never to anyone else, so it is safe from the phone."""
    import email_client

    try:
        accounts = email_client.list_accounts()
        picked = next((a for a in accounts if account and account.strip().lower() in (a["address"].lower(), a["id"])),
                      accounts[0] if accounts and not account else None)
        if picked is None:
            return ("Error: no email account is set up" if not accounts else f"Error: no email account {account!r}") + \
                ". The owner adds one in Keys → Email or signs in with Google in Connectors."
        files = [str(path) for path in (attachments or [])]
        outcome = email_client.send_email(picked["address"], subject or "From Nyx", body or "", account=picked["address"],
                                          attachments=files, allow_compose=False)
        return f"Emailed {outcome['to'][0]} (the owner's own address) from {outcome['from']}."
    except email_client.EmailError as error:
        return f"Not sent: {error}"


def register_whatsapp_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register(
        "whatsapp_send",
        "Text the owner on their phone over WhatsApp. It only ever reaches the owner's own paired phone — use it when "
        "they ask you to send them something, or to tell them a long job finished. Never for anyone else.",
        [P("text", "string", "The message")], tool_send, category="whatsapp", label="Texting your phone")
    registry.register(
        "whatsapp_send_file",
        "Send a file or picture from this PC to the owner's phone over WhatsApp (a photo, a PDF, a spreadsheet). It only "
        "reaches the owner's own phone. Protected credential files and anything the file check blocks are refused.",
        [P("path", "string", "Full path of the file on this PC"), P("caption", "string", "A short line to go with it",
                                                                    required=False)],
        tool_send_file, category="whatsapp", label=lambda a: f"Sending {str(a.get('path', 'a file'))[-40:]} to your phone")
    registry.register("whatsapp_status", "Whether the owner's phone is linked to Nyx over WhatsApp.", [],
                      tool_status, category="whatsapp", label="Checking the WhatsApp link")
    registry.register(
        "email_to_me", "Email something to the owner's own address (the account they connected). Use it when they ask to "
        "have a result, summary or file sent to their email. It cannot reach anyone else, so it also works from the phone.",
        [P("subject", "string", "Subject line"), P("body", "string", "Plain-text body"),
         P("attachments", "array", "File paths to attach", required=False),
         P("account", "string", "Which of the owner's accounts to use (default: the first)", required=False)],
        tool_email_to_me, category="email.send", label="Emailing you")
