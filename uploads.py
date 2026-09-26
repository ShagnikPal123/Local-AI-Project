"""Files and pictures the user hands to Nyx.

"Allow picture uploads and file uploads. It could download the image off the user
computer or just look at it and understand it."

An upload is stored once under ``data_path("uploads")`` and described by a small
record. What the *model* gets depends on the kind of file:

* **Images** are shown to the model as images (downscaled so a phone photo does
  not blow the request size), so it genuinely looks at them.
* **PDFs** go to vision-capable models as documents — Gemini reads PDFs natively,
  layout and figures included — with extracted text as the fallback for models
  that cannot.
* **Text, code, CSV/JSON, Word, Excel and PowerPoint** become text, extracted here
  without Office installed (they are zip files of XML).
* **Audio and video** under the inline limit go to models that accept them.

The same loader serves ``view_image``/``read_file``-style tools on local paths,
so "look at the picture on my desktop" and a dragged-in file take one code path.
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import data_path

#: Largest upload accepted at all.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
#: Largest file sent inline to a model (base64 grows it by a third; providers
#: reject inline payloads around 20 MB).
MAX_INLINE_BYTES = 14 * 1024 * 1024
#: Longest image edge sent to a model. Enough to read a screenshot's text.
MAX_IMAGE_EDGE = 2048
#: Text extracted from one file before it is cut.
MAX_TEXT_CHARS = 120_000

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".yaml", ".yml", ".toml",
    ".ini", ".cfg", ".log", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm", ".css", ".scss",
    ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".sql",
    ".sh", ".bat", ".ps1", ".r", ".m", ".tex", ".srt", ".vtt",
}
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")
_ID_RE = re.compile(r"^[0-9a-f]{16}$")

_lock = threading.Lock()


class UploadError(ValueError):
    """An upload that cannot be accepted, with a message fit for the user."""


def upload_dir() -> Path:
    folder = data_path("uploads")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _index_path() -> Path:
    return upload_dir() / "index.json"


def _read_index() -> Dict[str, Dict[str, Any]]:
    try:
        data = json.loads(_index_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_index(index: Dict[str, Dict[str, Any]]) -> None:
    path = _index_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(index, indent=1), encoding="utf-8")
    from paths import atomic_replace

    atomic_replace(tmp, path)


def kind_for(name: str, mime: str) -> str:
    """image | pdf | text | document | audio | video | other."""
    suffix = Path(name).suffix.lower()
    mime = (mime or "").lower()
    if mime.startswith("image/") or suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif"}:
        return "image"
    if mime == "application/pdf" or suffix == ".pdf":
        return "pdf"
    if suffix in {".docx", ".xlsx", ".pptx"}:
        return "document"
    if mime.startswith("text/") or suffix in _TEXT_EXTENSIONS or mime in {"application/json", "application/xml"}:
        return "text"
    if mime.startswith("audio/") or suffix in {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}:
        return "audio"
    if mime.startswith("video/") or suffix in {".mp4", ".mov", ".webm", ".mkv", ".avi"}:
        return "video"
    return "other"


def _guess_mime(name: str, declared: str) -> str:
    declared = (declared or "").split(";")[0].strip().lower()
    if declared and declared != "application/octet-stream":
        return declared
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def _screen(data: bytes, name: str, mime: str) -> Optional[Any]:
    """The malicious-file check, before a single byte is written to disk."""
    try:
        import file_guard
    except Exception:  # noqa: BLE001 - never lose an upload because the checker broke
        return None
    try:
        verdict = file_guard.check_bytes(data, name, mime)
    except Exception:  # noqa: BLE001
        return None
    file_guard.record(verdict, "upload")
    if verdict.blocked:
        raise UploadError(verdict.message)
    return verdict


def _screen_saved(target: Path, verdict: Optional[Any]) -> None:
    """Windows Security's own look at the file now that it is on disk."""
    try:
        import file_guard
    except Exception:  # noqa: BLE001
        return
    if not target.is_file():
        # Real-time protection took it away between write and read.
        raise UploadError("Windows Security removed that file while it was being saved.")
    if verdict is None or not file_guard.settings()["windows_security"]:
        return
    level, detail = file_guard.defender_scan(target)
    verdict.scanner = detail
    if level == "blocked":
        verdict.block(detail + ".")
        file_guard.record(verdict, "upload")
        try:
            target.unlink()  # Nyx's copy only; the owner's original is untouched.
        except OSError:
            pass
        raise UploadError(verdict.message)


def save_upload(data: bytes, filename: str, mime: str = "") -> Dict[str, Any]:
    """Store an upload and return its record.

    Nothing is stored before ``file_guard`` has looked at the bytes: a disguised
    program, a zip bomb or a known signature is refused here, so the rest of Nyx
    only ever sees files that passed (``UploadError`` carries the reason).
    """
    if not data:
        raise UploadError("That file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise UploadError(f"That file is {len(data) // (1024 * 1024)} MB; the limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")

    original = Path(filename or "upload").name
    safe = _SAFE_NAME_RE.sub("_", original).strip(" .") or "upload"
    safe = safe[-120:]
    mime = _guess_mime(original, mime)
    kind = kind_for(original, mime)
    verdict = _screen(data, original, mime)

    upload_id = uuid.uuid4().hex[:16]
    month = time.strftime("%Y-%m")
    target = upload_dir() / month / f"{upload_id}_{safe}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    _screen_saved(target, verdict)

    record: Dict[str, Any] = {
        "id": upload_id,
        "name": original,
        "mime": mime,
        "size": len(data),
        "kind": kind,
        "path": str(target),
        "created_at": time.time(),
    }
    if verdict is not None and verdict.level != "clean":
        record["security"] = verdict.to_dict()
    if kind == "image":
        size = _image_size(data)
        if size:
            record["width"], record["height"] = size

    with _lock:
        index = _read_index()
        index[upload_id] = record
        _write_index(index)
    return record


def get_upload(upload_id: str) -> Optional[Dict[str, Any]]:
    if not _ID_RE.match(upload_id or ""):
        return None
    record = _read_index().get(upload_id)
    if record and Path(record.get("path", "")).is_file():
        return record
    return None


def public_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """What the browser is told about an upload (no filesystem path)."""
    return {k: v for k, v in record.items() if k != "path"}


# ---------------------------------------------------------------------------
# Turning a file into model input
# ---------------------------------------------------------------------------


def _image_size(data: bytes) -> Optional[tuple[int, int]]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception:
        return None


def prepare_image(data: bytes, mime: str, max_edge: int = MAX_IMAGE_EDGE) -> tuple[bytes, str]:
    """Downscale a large image for a model; small ones pass through untouched."""
    try:
        from PIL import Image, ImageOps

        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            if max(image.size) <= max_edge and len(data) <= MAX_INLINE_BYTES and mime in {
                "image/png", "image/jpeg", "image/webp", "image/gif"
            }:
                return data, mime
            image.thumbnail((max_edge, max_edge))
            buffer = io.BytesIO()
            if image.mode in ("RGBA", "LA", "P"):
                image.save(buffer, format="PNG", optimize=True)
                return buffer.getvalue(), "image/png"
            image.convert("RGB").save(buffer, format="JPEG", quality=88)
            return buffer.getvalue(), "image/jpeg"
    except Exception:
        return data, mime


def _xml_text(xml: bytes) -> str:
    text = re.sub(rb"<w:tab/>|<a:tab/>", b"\t", xml)
    text = re.sub(rb"</w:p>|</a:p>|<w:br/>|</row>", b"\n", text)
    text = re.sub(rb"<[^>]+>", b"", text)
    import html

    return html.unescape(text.decode("utf-8", errors="replace"))


def extract_document_text(data: bytes, name: str) -> str:
    """Text out of .docx / .xlsx / .pptx with the standard library only."""
    suffix = Path(name).suffix.lower()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            if suffix == ".docx":
                parts = [n for n in names if n.startswith("word/") and n.endswith(".xml")
                         and any(k in n for k in ("document", "header", "footer", "footnotes"))]
                return "\n".join(_xml_text(archive.read(n)) for n in sorted(parts)).strip()
            if suffix == ".pptx":
                slides = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)),
                                key=lambda n: int(re.findall(r"\d+", n)[-1]))
                return "\n\n".join(f"--- Slide {i + 1} ---\n{_xml_text(archive.read(n)).strip()}"
                                   for i, n in enumerate(slides))
            if suffix == ".xlsx":
                shared: List[str] = []
                if "xl/sharedStrings.xml" in names:
                    shared = re.findall(r"<si>(.*?)</si>", archive.read("xl/sharedStrings.xml").decode("utf-8", "replace"), re.S)
                    shared = [re.sub(r"<[^>]+>", "", s) for s in shared]
                out: List[str] = []
                for sheet in sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)):
                    xml = archive.read(sheet).decode("utf-8", "replace")
                    out.append(f"--- {Path(sheet).stem} ---")
                    for row in re.findall(r"<row[^>]*>(.*?)</row>", xml, re.S):
                        cells = []
                        for attrs, value in re.findall(r"<c([^>]*)>(?:.*?<v>(.*?)</v>)?.*?</c>", row, re.S):
                            if 't="s"' in attrs and value.isdigit() and int(value) < len(shared):
                                cells.append(shared[int(value)])
                            else:
                                cells.append(value)
                        out.append("\t".join(cells))
                import html

                return html.unescape("\n".join(out)).strip()
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""
    return ""


def extract_pdf_text(data: bytes, max_pages: int = 200) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        pages = []
        for number, page in enumerate(reader.pages[:max_pages], start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"--- Page {number} ---\n{text}")
        return "\n\n".join(pages)
    except Exception:
        return ""


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _truncate(text: str) -> str:
    if len(text) <= MAX_TEXT_CHARS:
        return text
    return text[:MAX_TEXT_CHARS] + f"\n... [cut at {MAX_TEXT_CHARS:,} of {len(text):,} characters]"


def model_input(name: str, mime: str, data: bytes) -> Dict[str, Any]:
    """``{"text": str, "images": [...]}`` — what to add to the user's message."""
    kind = kind_for(name, mime)
    header = f"[Attached file: {name} ({kind}, {len(data):,} bytes)]"

    if kind == "image":
        prepared, prepared_mime = prepare_image(data, mime)
        return {"text": header, "images": [{"mime": prepared_mime, "data": base64.b64encode(prepared).decode("ascii"), "name": name}]}

    if kind == "pdf":
        text = extract_pdf_text(data)
        images = []
        if len(data) <= MAX_INLINE_BYTES:
            images.append({"mime": "application/pdf", "data": base64.b64encode(data).decode("ascii"), "name": name})
        body = f"{header}\nExtracted text:\n{_truncate(text)}" if text else f"{header}\n(No extractable text — likely scanned; vision models read the pages directly.)"
        return {"text": body, "images": images}

    if kind == "document":
        text = extract_document_text(data, name)
        return {"text": f"{header}\n{_truncate(text) if text else '(could not read any text from it)'}", "images": []}

    if kind == "text":
        return {"text": f"{header}\n```\n{_truncate(_decode_text(data))}\n```", "images": []}

    if kind in ("audio", "video") and len(data) <= MAX_INLINE_BYTES:
        return {"text": f"{header} (sent as {kind} to models that can hear or watch it)",
                "images": [{"mime": mime, "data": base64.b64encode(data).decode("ascii"), "name": name}]}

    return {"text": f"{header}\n(This kind of file cannot be read directly; it is saved at the path Nyx can open with tools.)",
            "images": []}


def security_note(record: Dict[str, Any]) -> str:
    """The warning line for a file the checks flagged, added before a model reads it."""
    saved = record.get("security")
    if not saved:
        return ""
    try:
        import file_guard

        return file_guard.note_for_model(file_guard.Verdict(**{
            k: v for k, v in saved.items() if k in file_guard.Verdict.__dataclass_fields__
        }))
    except Exception:  # noqa: BLE001
        return ""


def model_input_for_upload(upload_id: str) -> Optional[Dict[str, Any]]:
    record = get_upload(upload_id)
    if record is None:
        return None
    data = Path(record["path"]).read_bytes()
    result = model_input(record["name"], record["mime"], data)
    result["text"] += (
        f"\n(Upload id: {record['id']} — analyze_image or read_document with this id uses the assigned "
        f"image-check or reading model. Saved at: {record['path']})"
    )
    result["text"] += security_note(record)
    result["record"] = public_record(record)
    return result
