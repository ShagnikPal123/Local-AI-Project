"""Pictures and files over the WhatsApp line, both ways.

Owner (2026-10-13): "the AI can send files like images or files to the user and the user can send files from phone to
the AI. Make sure it works."

Coming in: the helper downloads what the phone sent into an inbox folder; ``keep_incoming`` hands each file to
``uploads.save_upload`` (which runs ``file_guard`` on it: disguised programs, zip bombs, known malware shapes), deletes
the inbox copy, and returns upload ids the chat turn reads like a file dragged into the chat. A file that fails the
check is not kept, and the owner is told why in the same words the PC would use.

Going out: ``check_outgoing`` decides whether a file on this PC may be texted to the owner's phone. A phone is easier
to lose than a PC, so it refuses what the owner marked protected (credential stores), anything ``file_guard`` blocks,
folders, empty files and files too big for WhatsApp. Pictures the AI made during a turn leave as pictures: the chat
answer carries them as ``![name](/api/uploads/<id>)``; ``split_pictures`` lifts those links out of the text so the
phone does not receive raw markdown.

Nothing here talks to WhatsApp; ``whatsapp_link`` does the sending and the receiving.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

#: WhatsApp accepts documents up to 100 MB; Nyx stays well under it so a send never stalls the line.
MAX_SEND_BYTES = 50 * 1024 * 1024
_IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_VIDEO = {".mp4", ".mov", ".3gp"}
_UPLOAD_LINK = re.compile(r"!?\[([^\]]*)\]\(/api/uploads/([0-9a-f]{16})[^)]*\)")


class FileRefused(ValueError):
    """Why a file will not be sent or kept, in words the owner can read."""


def kind_for(path: str) -> str:
    """How WhatsApp should show it: ``image``, ``video`` or ``document`` (the safe default).

    Sound files go as documents on purpose: WhatsApp gives audio no caption, and the caption is what tells Nyx's own
    message apart from the owner's in the "message yourself" chat (see ``REPLY_PREFIX``).
    """
    suffix = Path(path).suffix.lower()
    if suffix in _IMAGE:
        return "image"
    if suffix in _VIDEO:
        return "video"
    return "document"


def check_outgoing(path: Any) -> Tuple[str, int]:
    """Whether this file may go to the owner's phone. Returns (resolved path, size) or raises ``FileRefused``."""
    try:
        target = Path(str(path)).expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as error:
        raise FileRefused("That path does not make sense.") from error
    if not target.exists():
        raise FileRefused(f"There is no file at {target.name or 'that path'}.")
    if not target.is_file():
        raise FileRefused("That is a folder. Send a file, or zip the folder first.")
    size = target.stat().st_size
    if size == 0:
        raise FileRefused(f"{target.name} is empty.")
    if size > MAX_SEND_BYTES:
        raise FileRefused(f"{target.name} is {size // (1024 * 1024)} MB; WhatsApp sends here stop at "
                          f"{MAX_SEND_BYTES // (1024 * 1024)} MB.")
    from permissions import is_protected_path

    if is_protected_path(str(target)):
        raise FileRefused(f"{target.name} is on your protected list (it can hold passwords), so it is not sent.")
    import file_guard

    verdict = file_guard.check_file(target, source="whatsapp-out")
    if not verdict.ok:
        raise FileRefused(f"{target.name} did not pass the file check: {'; '.join(verdict.reasons)[:200]}")
    return str(target), size


def split_pictures(reply: str) -> Tuple[str, List[str]]:
    """Take ``![name](/api/uploads/<id>)`` links out of an answer. Returns (the text without them, the upload ids)."""
    ids: List[str] = []

    def lift(found: "re.Match[str]") -> str:
        if found.group(2) not in ids:
            ids.append(found.group(2))
        return ""

    text = _UPLOAD_LINK.sub(lift, reply or "")
    return re.sub(r"\n{3,}", "\n\n", text).strip(), ids


def keep_incoming(items: List[Dict[str, Any]], inbox: Path) -> Tuple[List[str], List[str]]:
    """Move what the phone sent into Nyx's uploads. Returns (upload ids kept, plain notes about what was not kept).

    Only files inside ``inbox`` are read: a path in an event from the helper that points anywhere else is ignored, so
    nothing can make the engine ingest an arbitrary file by naming it.
    """
    import uploads

    kept: List[str] = []
    notes: List[str] = []
    root = inbox.resolve()
    for item in items or []:
        name = str(item.get("name") or item.get("kind") or "file")
        if item.get("error"):
            notes.append(f"I could not take {name}: {item['error']}.")
            continue
        source = Path(str(item.get("path") or "")).resolve()
        inside = root in source.parents
        try:
            if not inside or not source.is_file():
                notes.append(f"I could not find {name} after it arrived.")
                continue
            record = uploads.save_upload(source.read_bytes(), name if item.get("name") else source.name,
                                         str(item.get("mime") or ""))
            kept.append(record["id"])
        except uploads.UploadError as error:
            notes.append(f"I did not keep {name}: {error}")
        except OSError:
            notes.append(f"I could not read {name} after it arrived.")
        finally:
            if inside:                               # the inbox copy goes either way; a path elsewhere is never touched
                try:
                    os.remove(str(source))
                except OSError:
                    pass
    return kept, notes


def incoming_text(text: str, kept: int, kinds: List[str]) -> str:
    """What the turn is told when files came with (or instead of) words."""
    if kept == 0:
        return text
    what = "/".join(sorted(set(kinds))) or "file"
    note = f"[The owner sent {kept} file(s) from their phone ({what}), attached.]"
    return f"{text}\n\n{note}" if text else f"{note} Look at what they sent and answer, or ask what they want done with it."
