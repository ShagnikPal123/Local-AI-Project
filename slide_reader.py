"""Slides in, study material out (Project Null N89).

The owner: "In notes add an upload place so if I upload slides it can make detailed
notes, quizzes, Flashcards, questions for specific parts, and has a text box where
I can say to generate a specific study tool."

"Questions for specific parts" is the part that decides the shape of this module:
a deck has to stay a *list of slides*, not one lump of text, so the owner can say
"slides 12–18" or "the section on enzymes" and get questions about exactly that.
So a deck is read here into numbered slides (title, body, the lecturer's speaker
notes — which are often the best material in the file) grouped into sections, and
``material_for`` hands the study actions only the slides that were asked for.

PowerPoint is read directly from the file: a .pptx is a zip of XML, so no extra
dependency is needed. PDFs go through the PDF reader already used for uploads,
one page per slide. A photo of a slide goes to the vision model instead
(``study_tools.read_drawing``), which is why images are not handled here.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from typing import Any, Dict, List, Optional, Sequence

#: PresentationML namespaces (the only two needed to walk a slide).
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_R = "{http://schemas.openxmlformats.org/package/2006/relationships}"

MAX_SLIDES = 400
MAX_SLIDE_CHARS = 6000
#: How much material one study action may be given, so a 200-slide deck still answers.
MAX_MATERIAL_CHARS = 60_000


class SlideError(ValueError):
    """The file could not be read as slides; the message says what to do instead."""


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _text_of(node: ET.Element) -> str:
    """Every run of text under a shape, keeping paragraph breaks."""
    lines: List[str] = []
    for paragraph in node.iter(f"{_A}p"):
        run = "".join(t.text or "" for t in paragraph.iter(f"{_A}t"))
        run = run.strip()
        if run:
            lines.append(run)
    return "\n".join(lines)


def _slide_number(name: str) -> int:
    match = re.search(r"(\d+)", name.rsplit("/", 1)[-1])
    return int(match.group(1)) if match else 0


def _notes_for(archive: zipfile.ZipFile, slide_name: str) -> str:
    """The speaker notes attached to this slide, followed through its relationships.

    Notes files are numbered independently of slides — notesSlide1.xml can belong
    to slide 7 — so the rels file is the only reliable link.
    """
    rels = f"{slide_name.rsplit('/', 1)[0]}/_rels/{slide_name.rsplit('/', 1)[-1]}.rels"
    try:
        root = ET.fromstring(archive.read(rels))
    except (KeyError, ET.ParseError):
        return ""
    for relationship in root.iter(f"{_R}Relationship"):
        if str(relationship.get("Type", "")).endswith("notesSlide"):
            target = str(relationship.get("Target", "")).replace("../", "ppt/")
            try:
                notes = ET.fromstring(archive.read(target))
            except (KeyError, ET.ParseError):
                return ""
            text = "\n".join(_text_of(shape) for shape in notes.iter(f"{_P}sp"))
            # PowerPoint puts the slide number placeholder in the notes too.
            return re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE).strip()
    return ""


def _from_pptx(data: bytes) -> List[Dict[str, Any]]:
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as error:
        raise SlideError("That .pptx could not be opened. Try re-saving it, or export the deck as PDF.") from error
    names = sorted((n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_slide_number)
    if not names:
        raise SlideError("No slides were found in that file. If it is a .ppt (the old format), save it as .pptx or PDF.")

    slides: List[Dict[str, Any]] = []
    for index, name in enumerate(names[:MAX_SLIDES], start=1):
        try:
            root = ET.fromstring(archive.read(name))
        except ET.ParseError:
            continue
        title, body = "", []
        for shape in root.iter(f"{_P}sp"):
            placeholder = next((ph for ph in shape.iter(f"{_P}ph")), None)
            kind = str(placeholder.get("type", "")) if placeholder is not None else ""
            text = _text_of(shape)
            if not text:
                continue
            if not title and kind in ("title", "ctrTitle"):
                title = text.splitlines()[0][:200]
                rest = "\n".join(text.splitlines()[1:]).strip()
                if rest:
                    body.append(rest)
            else:
                body.append(text)
        pictures = sum(1 for _ in root.iter(f"{_P}pic"))
        if not title and body:
            # No title placeholder (a picture-led slide): the first line stands in.
            first = body[0].splitlines()[0]
            if len(first) <= 90:
                title = first
        slides.append(_slide(index, title, "\n".join(body), _notes_for(archive, name), pictures))
    if not slides:
        raise SlideError("That deck has no readable text — it may be pictures of slides. Export it as PDF, or upload a photo of a slide instead.")
    return slides


_PAGE_MARK = re.compile(r"^--- Page (\d+) ---$", re.MULTILINE)


def _from_pdf(data: bytes) -> List[Dict[str, Any]]:
    import uploads

    text = uploads.extract_pdf_text(data, max_pages=MAX_SLIDES)
    if not text.strip():
        raise SlideError("No text could be read from that PDF — it may be scanned pictures. Upload a photo of a slide instead and Nyx will read it.")
    parts = _PAGE_MARK.split(text)
    slides: List[Dict[str, Any]] = []
    # split() gives [before, number, body, number, body, …]
    for number, body in zip(parts[1::2], parts[2::2]):
        lines = [line.strip() for line in body.strip().splitlines() if line.strip()]
        if not lines:
            continue
        title = lines[0][:200] if len(lines[0]) <= 120 else ""
        rest = "\n".join(lines[1:] if title else lines)
        slides.append(_slide(int(number), title, rest, "", 0))
    if not slides:
        slides = [_slide(1, "", text, "", 0)]
    return slides


def _from_text(text: str) -> List[Dict[str, Any]]:
    """Pasted or plain-text slides: split on slide markers, "---", or headings."""
    chunks = re.split(r"\n\s*(?:---+|===+|\f)\s*\n|\n(?=#{1,3} )|\n(?=Slide \d+[:.])", text.strip())
    slides = []
    for index, chunk in enumerate([c for c in chunks if c.strip()][:MAX_SLIDES], start=1):
        lines = [line.strip() for line in chunk.strip().splitlines() if line.strip()]
        title = re.sub(r"^#+\s*|^Slide \d+[:.]\s*", "", lines[0])[:200] if lines else ""
        slides.append(_slide(index, title, "\n".join(lines[1:]), "", 0))
    return slides or [_slide(1, "", text, "", 0)]


def _slide(number: int, title: str, body: str, notes: str, pictures: int) -> Dict[str, Any]:
    return {"n": number, "title": (title or "").strip()[:200], "text": (body or "").strip()[:MAX_SLIDE_CHARS],
            "notes": (notes or "").strip()[:MAX_SLIDE_CHARS], "pictures": int(pictures)}


def read_bytes(data: bytes, name: str = "", mime: str = "") -> Dict[str, Any]:
    """A deck from a file's bytes: .pptx, PDF, or text."""
    lowered = (name or "").lower()
    if data[:4] == b"PK\x03\x04" and (lowered.endswith(".pptx") or "presentation" in (mime or "")):
        slides = _from_pptx(data)
        kind = "pptx"
    elif data[:5] == b"%PDF-" or lowered.endswith(".pdf") or "pdf" in (mime or ""):
        slides = _from_pdf(data)
        kind = "pdf"
    elif lowered.endswith((".ppt", ".key", ".odp")):
        raise SlideError("Nyx can read .pptx and PDF decks. Open this one and use File → Export as PDF, then upload that.")
    else:
        import uploads

        slides = _from_text(uploads._decode_text(data))
        kind = "text"
    title = _deck_title(slides, name)
    return {"title": title, "kind": kind, "name": name, "slides": slides, "sections": sections(slides)}


def read_upload(upload_id: str) -> Dict[str, Any]:
    """A deck from something the owner dropped on the Notes tab."""
    import uploads

    record = uploads.get_upload(upload_id)
    if record is None:
        raise SlideError("That upload is no longer there — add the file again.")
    try:
        data = open(record["path"], "rb").read()
    except OSError as error:
        raise SlideError("That file could not be read.") from error
    return read_bytes(data, record.get("name", ""), record.get("mime", ""))


def _deck_title(slides: Sequence[Dict[str, Any]], name: str) -> str:
    first = slides[0] if slides else {}
    title = str(first.get("title") or "").strip()
    if title:
        return title[:120]
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", name or "").replace("_", " ").replace("-", " ").strip()
    return (stem or "Slides")[:120]


# ---------------------------------------------------------------------------
# Parts of a deck
# ---------------------------------------------------------------------------


def sections(slides: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group slides into the parts a person would name.

    A slide with a title and almost no body is how decks mark a new part; when a
    deck has none, fall back to blocks of eight so "specific parts" still means
    something on a long deck.
    """
    marks: List[int] = []
    for slide in slides:
        if slide["title"] and len(slide["text"]) < 90:
            marks.append(slide["n"])
    if len(marks) < 2 or len(marks) > max(2, len(slides) // 2):
        marks = [slide["n"] for index, slide in enumerate(slides) if index % 8 == 0]
    out: List[Dict[str, Any]] = []
    for position, start in enumerate(marks):
        end = (marks[position + 1] - 1) if position + 1 < len(marks) else (slides[-1]["n"] if slides else start)
        named = next((s for s in slides if s["n"] == start), None)
        title = (named or {}).get("title") or f"Slides {start}–{end}"
        out.append({"title": str(title)[:120], "from": start, "to": max(start, end)})
    return out


def pick(deck: Dict[str, Any], slides: Optional[Sequence[int]] = None) -> List[Dict[str, Any]]:
    """The chosen slides, in order; every slide when nothing is chosen."""
    if not slides:
        return list(deck.get("slides") or [])
    wanted = {int(n) for n in slides}
    return [s for s in deck.get("slides") or [] if s["n"] in wanted]


def parse_range(text: str) -> List[int]:
    """"12-18, 21" → [12…18, 21]. What the owner types into the parts box."""
    numbers: List[int] = []
    for part in re.split(r"[,;]", text or ""):
        part = part.strip()
        match = re.fullmatch(r"(\d+)\s*(?:-|–|to|through)\s*(\d+)", part, re.IGNORECASE)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            numbers.extend(range(min(start, end), min(max(start, end), start + 200) + 1))
        elif part.isdigit():
            numbers.append(int(part))
    return sorted(dict.fromkeys(numbers))


def outline(deck: Dict[str, Any], slides: Optional[Sequence[int]] = None) -> str:
    """The deck as Markdown — what gets saved as the note, and what the model reads."""
    lines: List[str] = []
    for slide in pick(deck, slides):
        heading = f"## Slide {slide['n']}" + (f" — {slide['title']}" if slide["title"] else "")
        lines.append(heading)
        if slide["text"]:
            lines.append(slide["text"])
        if slide["notes"]:
            lines.append(f"_Speaker notes:_ {slide['notes']}")
        if slide["pictures"] and not slide["text"]:
            lines.append(f"_({slide['pictures']} picture(s) on this slide, no text.)_")
        lines.append("")
    return "\n".join(lines).strip()


def material_for(deck: Dict[str, Any], slides: Optional[Sequence[int]] = None) -> str:
    """What a study action is given: the chosen slides, capped so long decks still answer."""
    text = outline(deck, slides)
    if len(text) <= MAX_MATERIAL_CHARS:
        return text
    return text[:MAX_MATERIAL_CHARS] + "\n\n… (the rest of the deck was left out to keep this answer quick — " \
                                       "choose fewer slides for the whole detail.)"


# ---------------------------------------------------------------------------
# Keeping a deck next to its note
# ---------------------------------------------------------------------------


def _deck_path(note_id: str):
    from paths import data_path

    folder = data_path("slides")
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{re.sub(r'[^A-Za-z0-9_-]', '', note_id)[:64]}.json"


def save_deck(note_id: str, deck: Dict[str, Any]) -> None:
    """Keep the slides beside the note, not inside it.

    The note's body already holds the readable outline; the deck is kept here so
    "questions on slides 12–18" still knows where slide 12 ends, without doubling
    the size of notes.json.
    """
    import json

    from paths import atomic_replace

    target = _deck_path(note_id)
    temp = target.with_suffix(".json.tmp")
    temp.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    atomic_replace(temp, target)


def load_deck(note_id: str) -> Optional[Dict[str, Any]]:
    import json

    try:
        data = json.loads(_deck_path(note_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("slides") else None


def forget_deck(note_id: str) -> None:
    try:
        _deck_path(note_id).unlink()
    except OSError:
        pass


def summary(deck: Dict[str, Any]) -> Dict[str, Any]:
    """What the Notes tab shows about a deck without sending every slide again."""
    slides = deck.get("slides") or []
    return {"title": deck.get("title"), "kind": deck.get("kind"), "name": deck.get("name"), "slides": len(slides),
            "with_notes": sum(1 for s in slides if s["notes"]), "sections": deck.get("sections") or [],
            "titles": [{"n": s["n"], "title": s["title"], "chars": len(s["text"]) + len(s["notes"])} for s in slides]}
