"""HTTP routes for the Notes tab (Request G13). Every route is behind the session middleware."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


class NotebookRequest(BaseModel):
    title: str


class NoteCreateRequest(BaseModel):
    title: str = ""
    body: str = ""
    notebook_id: str = ""
    kind: str = "note"


class NoteUpdateRequest(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    append: Optional[str] = None
    notebook_id: Optional[str] = None
    pinned: Optional[bool] = None


class StudyRequest(BaseModel):
    action: str
    selection: str = ""
    question: str = ""
    count: Optional[int] = None
    #: Text results: "append" adds them to the note, "none" only returns them.
    save: str = "none"


class DrawingRequest(BaseModel):
    upload_id: str
    hint: str = ""


class SlidesRequest(BaseModel):
    """A deck the owner dropped on the Notes tab (Project Null N89)."""

    upload_id: str
    notebook_id: str = ""
    title: str = ""


class SlidesStudyRequest(BaseModel):
    #: A study action, or "custom" with ``instruction`` for anything not on the buttons.
    action: str = "slides_notes"
    #: Which slides this is about: [4, 5, 6] or "12-18, 21". Empty means the whole deck.
    slides: List[int] = []
    slide_range: str = ""
    instruction: str = ""
    count: Optional[int] = None
    save: str = "none"


class ItemUpdateRequest(BaseModel):
    cards: Optional[List[Dict[str, Any]]] = None
    attempt: Optional[Dict[str, Any]] = None


class GradeRequest(BaseModel):
    question: str
    expected: str
    given: str


def _note_or_404(note_id: str) -> Dict[str, Any]:
    import notes_store

    note = notes_store.get(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="That note no longer exists.")
    return note


@router.get("/api/notes")
def notes_library(q: str = "", _user=RequireChat) -> Dict[str, Any]:
    import notes_store

    if q.strip():
        return {"notes": notes_store.search(q, limit=40)}
    return notes_store.library()


@router.post("/api/notes/notebooks")
def create_notebook(body: NotebookRequest, _user=RequireChat) -> Dict[str, Any]:
    import notes_store

    try:
        return {"notebook": notes_store.add_notebook(body.title)}
    except notes_store.NotesError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.patch("/api/notes/notebooks/{notebook_id}")
def rename_notebook(notebook_id: str, body: NotebookRequest, _user=RequireChat) -> Dict[str, Any]:
    import notes_store

    try:
        return {"notebook": notes_store.rename_notebook(notebook_id, body.title)}
    except notes_store.NotesError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/api/notes/notebooks/{notebook_id}")
def delete_notebook(notebook_id: str, _user=RequireChat) -> Dict[str, Any]:
    import notes_store

    try:
        notes_store.delete_notebook(notebook_id)
    except notes_store.NotesError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return notes_store.library()


@router.post("/api/notes")
def create_note(body: NoteCreateRequest, _user=RequireChat) -> Dict[str, Any]:
    import notes_store

    try:
        return {"note": notes_store.create(body.title, body.body, body.notebook_id, body.kind)}
    except notes_store.NotesError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/notes/{note_id}")
def read_note(note_id: str, _user=RequireChat) -> Dict[str, Any]:
    return {"note": _note_or_404(note_id)}


@router.patch("/api/notes/{note_id}")
def update_note(note_id: str, body: NoteUpdateRequest, _user=RequireChat) -> Dict[str, Any]:
    import notes_store

    try:
        return {"note": notes_store.update(note_id, **body.model_dump(exclude_none=True))}
    except KeyError as error:
        raise HTTPException(status_code=404, detail="That note no longer exists.") from error


@router.delete("/api/notes/{note_id}")
def delete_note(note_id: str, _user=RequireChat) -> Dict[str, Any]:
    import notes_store
    import slide_reader

    if not notes_store.delete(note_id):
        raise HTTPException(status_code=404, detail="That note no longer exists.")
    slide_reader.forget_deck(note_id)  # a deck outliving its note is just disk space
    return {"ok": True}


@router.post("/api/notes/{note_id}/study")
def study(note_id: str, body: StudyRequest, _user=RequireChat) -> Dict[str, Any]:
    """Detail, summary, quiz, flashcards, step-by-step… made from this note."""
    import notes_store
    import study_tools
    from model_hub import ModelCallError

    note = _note_or_404(note_id)
    try:
        result = study_tools.run_action(body.action, note["title"], note["body"], selection=body.selection,
                                        question=body.question, count=body.count)
    except study_tools.StudyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ModelCallError as error:
        raise HTTPException(status_code=502, detail=f"No study model could answer: {error}") from error

    if result["kind"] == "quiz":
        result["item"] = notes_store.attach(note_id, "quizzes", {**result["spec"], "model": result["model"]})
    elif result["kind"] == "deck":
        result["item"] = notes_store.attach(note_id, "decks", {**result["spec"], "model": result["model"]})
    elif result["kind"] == "steps":
        result["item"] = notes_store.attach(note_id, "steps", {**result["spec"], "model": result["model"]})
    elif body.save == "append":
        heading = f"## {result['title']}" + (f" — {body.question.strip()[:80]}" if body.question.strip() else "")
        result["note"] = notes_store.update(note_id, append=f"{heading}\n\n{result['text']}")
    elif body.save == "replace":
        result["note"] = notes_store.update(note_id, body=result["text"])
    return result


@router.post("/api/notes/slides")
def add_slides(body: SlidesRequest, _user=RequireChat) -> Dict[str, Any]:
    """Read an uploaded deck into a note you can study from (Project Null N89).

    The note's body is the deck as readable Markdown, so everything the Notes tab
    already does — quizzes, flashcards, summaries, search — works on it at once.
    """
    import notes_store
    import slide_reader

    try:
        deck = slide_reader.read_upload(body.upload_id)
    except slide_reader.SlideError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    title = (body.title.strip() or deck["title"])[:120]
    note = notes_store.create(title, slide_reader.outline(deck), body.notebook_id, "slides")
    slide_reader.save_deck(note["id"], deck)
    return {"note": note, "deck": slide_reader.summary(deck)}


@router.get("/api/notes/{note_id}/slides")
def get_slides(note_id: str, _user=RequireChat) -> Dict[str, Any]:
    import slide_reader

    _note_or_404(note_id)
    deck = slide_reader.load_deck(note_id)
    return {"deck": slide_reader.summary(deck) if deck else None}


@router.post("/api/notes/{note_id}/slides/study")
def study_slides(note_id: str, body: SlidesStudyRequest, _user=RequireChat) -> Dict[str, Any]:
    """Notes, a quiz, flashcards or anything typed — from the whole deck or just the chosen slides."""
    import notes_store
    import slide_reader
    import study_tools
    from model_hub import ModelCallError

    note = _note_or_404(note_id)
    deck = slide_reader.load_deck(note_id)
    if deck is None:
        raise HTTPException(status_code=400, detail="This note has no slides attached. Upload the deck again.")

    chosen = list(body.slides) or slide_reader.parse_range(body.slide_range)
    material = slide_reader.material_for(deck, chosen)
    if not material.strip():
        raise HTTPException(status_code=400, detail="Those slide numbers are not in this deck.")

    action = study_tools.route_custom(body.instruction) if body.action == "custom" else body.action
    where = f"slides {chosen[0]}–{chosen[-1]}" if len(chosen) > 1 else (f"slide {chosen[0]}" if chosen else "the whole deck")
    question = body.instruction.strip()
    if action == "slides_questions" and not question:
        question = f"Ask about {where}."
    try:
        result = study_tools.run_action(action, f"{note['title']} ({where})", material,
                                        question=question, count=body.count)
    except study_tools.StudyError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ModelCallError as error:
        raise HTTPException(status_code=502, detail=f"No study model could answer: {error}") from error

    result["slides"] = chosen
    result["where"] = where
    if result["kind"] == "quiz":
        result["item"] = notes_store.attach(note_id, "quizzes", {**result["spec"], "model": result["model"], "from": where})
    elif result["kind"] == "deck":
        result["item"] = notes_store.attach(note_id, "decks", {**result["spec"], "model": result["model"], "from": where})
    elif result["kind"] == "steps":
        result["item"] = notes_store.attach(note_id, "steps", {**result["spec"], "model": result["model"], "from": where})
    elif body.save == "append":
        heading = f"## {result['title']} — {where}"
        result["note"] = notes_store.update(note_id, append=f"{heading}\n\n{result['text']}")
    return result


@router.post("/api/notes/{note_id}/drawing")
def read_drawing(note_id: str, body: DrawingRequest, _user=RequireChat) -> Dict[str, Any]:
    """Read a sketch (handwriting, equations, diagrams) into the note."""
    import notes_store
    import study_tools
    import uploads
    from model_hub import ModelCallError

    _note_or_404(note_id)
    record = uploads.get_upload(body.upload_id)
    if record is None or not str(record.get("mime", "")).startswith("image/"):
        raise HTTPException(status_code=400, detail="The drawing did not upload — try again.")
    try:
        with open(record["path"], "rb") as handle:
            read = study_tools.read_drawing(handle.read(), record["mime"], body.hint)
    except ModelCallError as error:
        raise HTTPException(status_code=502, detail=f"No image model could read the drawing: {error}") from error
    notes_store.attach(note_id, "drawings", {"upload_id": body.upload_id, "text": read["text"][:4000], "model": read["model"]})
    note = notes_store.update(note_id, append=f"## From my sketch\n\n![Sketch](/api/uploads/{body.upload_id})\n\n{read['text']}")
    return {"note": note, "text": read["text"], "model": read["model"]}


@router.patch("/api/notes/{note_id}/{collection}/{item_id}")
def update_study_item(note_id: str, collection: str, item_id: str, body: ItemUpdateRequest, _user=RequireChat) -> Dict[str, Any]:
    import notes_store

    if collection not in ("quizzes", "decks"):
        raise HTTPException(status_code=404, detail="Unknown study material.")
    try:
        return {"item": notes_store.update_item(note_id, collection, item_id, body.model_dump(exclude_none=True))}
    except KeyError as error:
        raise HTTPException(status_code=404, detail="That study material no longer exists.") from error


@router.delete("/api/notes/{note_id}/{collection}/{item_id}")
def delete_study_item(note_id: str, collection: str, item_id: str, _user=RequireChat) -> Dict[str, Any]:
    import notes_store

    if collection not in ("quizzes", "decks", "steps", "drawings"):
        raise HTTPException(status_code=404, detail="Unknown study material.")
    try:
        notes_store.delete_item(note_id, collection, item_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="That note no longer exists.") from error
    return {"ok": True}


@router.post("/api/notes/grade")
def grade_short_answer(body: GradeRequest, _user=RequireChat) -> Dict[str, Any]:
    import study_tools

    return study_tools.grade_short_answer(body.question, body.expected, body.given)


# ---------------------------------------------------------------------------
# Chat tools: "make a quiz from my biology notes"
# ---------------------------------------------------------------------------


def tool_notes_search(query: str) -> str:
    import notes_store

    found = notes_store.search(query)
    if not found:
        return f"No notes mention {query!r}."
    return "\n".join(f"- {n['title']} (id {n['id']}, {n['words']} words): {n['preview']}" for n in found)


def tool_notes_read(note_id: str) -> str:
    import notes_store

    note = notes_store.get(note_id)
    return f"# {note['title']}\n\n{note['body'][:20000]}" if note else f"No note with id {note_id}."


def tool_notes_create(title: str, body: str) -> str:
    import notes_store

    note = notes_store.create(title, body)
    return f"Saved a note “{note['title']}” (id {note['id']}) in the Notes tab."


def tool_notes_study(note_id: str, action: str, question: str = "") -> str:
    import notes_store
    import study_tools

    note = notes_store.get(note_id)
    if note is None:
        return f"No note with id {note_id}."
    try:
        result = study_tools.run_action(action, note["title"], note["body"], question=question)
    except study_tools.StudyError as error:
        return f"Error: {error}"
    collection = {"quiz": "quizzes", "deck": "decks", "steps": "steps"}.get(result["kind"])
    if collection:
        notes_store.attach(note_id, collection, {**result["spec"], "model": result["model"]})
        return f"Made {result['kind']} “{result['spec'].get('title') or result['spec'].get('question', '')}” and saved it with the note (open the Notes tab to use it). [{result['model']}]"
    return f"[{result['model']}]\n{result['text']}"


def register_notes_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register("notes_search", "Search the owner's notes in the Notes tab.", [ToolParam("query", "string", "Words to find")],
                      tool_notes_search, category="files.read", label=lambda a: f"Searching notes for {str(a.get('query', ''))[:40]}")
    registry.register("notes_read", "Read one note from the Notes tab by id.", [ToolParam("note_id", "string", "Note id from notes_search")],
                      tool_notes_read, category="files.read", label=lambda a: "Reading a note")
    registry.register("notes_create", "Save a new note in the Notes tab.",
                      [ToolParam("title", "string", "Title"), ToolParam("body", "string", "Markdown text")],
                      tool_notes_create, category="files.write", label=lambda a: f"Saving note {str(a.get('title', ''))[:40]}")
    registry.register("notes_study", "Make study material from a note: detail, organize, summarize, clean, glossary, study_guide, exam, "
                      "ask, quiz, flashcards or steps (steps and ask need a question).",
                      [ToolParam("note_id", "string", "Note id"), ToolParam("action", "string", "What to make"),
                       ToolParam("question", "string", "For ask / steps", required=False)],
                      tool_notes_study, category="general", label=lambda a: f"Making {a.get('action', 'study material')} from a note")
