"""Uploaded slides become study material (Project Null N89).

The owner uploads a deck and asks for "questions for specific parts", so the test
that matters most is that a deck stays a list of numbered slides — with the
lecturer's speaker notes — and that asking about slides 2–3 hands the model only
those slides.

A .pptx is built here from XML rather than committed as a fixture: it keeps the
repo small, and it documents exactly which parts of the format are relied on.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest

import slide_reader


def _slide_xml(title: str, bullets: list[str]) -> str:
    body = "".join(
        f'<p:sp><p:nvSpPr><p:nvPr/></p:nvSpPr><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
        for text in bullets
    )
    return (
        '<?xml version="1.0"?>'
        '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
        '<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r>'
        f'<a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>{body}'
        "</p:spTree></p:cSld></p:sld>"
    )


def _notes_xml(text: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'
        ' xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree>'
        f'<p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp>'
        "</p:spTree></p:cSld></p:notes>"
    )


def _rels(target: str) -> str:
    return (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"'
        f' Target="{target}"/></Relationships>'
    )


@pytest.fixture
def deck_bytes() -> bytes:
    """A four-slide lecture: a section divider, two content slides, one with speaker notes."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", _slide_xml("Enzymes", []))
        archive.writestr("ppt/slides/slide2.xml", _slide_xml("What an enzyme does", ["Lowers activation energy", "Is not used up"]))
        archive.writestr("ppt/slides/slide3.xml", _slide_xml("Induced fit", ["The site changes shape", "Binding is specific"]))
        archive.writestr("ppt/slides/slide4.xml", _slide_xml("Inhibition", ["Competitive", "Non-competitive"]))
        # Notes numbering does not follow slide numbering: slide 3's notes are notesSlide1.
        archive.writestr("ppt/notesSlides/notesSlide1.xml", _notes_xml("3\nSay the glove analogy here, they always ask."))
        archive.writestr("ppt/slides/_rels/slide3.xml.rels", _rels("../notesSlides/notesSlide1.xml"))
    return buffer.getvalue()


def test_a_deck_is_read_as_numbered_slides_with_the_speaker_notes(deck_bytes):
    deck = slide_reader.read_bytes(deck_bytes, "Lecture 4 enzymes.pptx")
    assert deck["kind"] == "pptx" and deck["title"] == "Enzymes"
    assert [s["n"] for s in deck["slides"]] == [1, 2, 3, 4]
    assert deck["slides"][1]["title"] == "What an enzyme does"
    assert "Lowers activation energy" in deck["slides"][1]["text"]
    # The notes belong to slide 3 (through the rels file), and the stray page number is gone.
    assert deck["slides"][2]["notes"].startswith("Say the glove analogy")
    assert deck["slides"][0]["notes"] == ""


def test_questions_about_one_part_only_see_that_part(deck_bytes):
    deck = slide_reader.read_bytes(deck_bytes, "lecture.pptx")
    material = slide_reader.material_for(deck, [3, 4])
    assert "Induced fit" in material and "Inhibition" in material
    assert "Lowers activation energy" not in material, "slide 2 was not asked for"
    assert "_Speaker notes:_ Say the glove analogy" in material


def test_slide_ranges_are_read_the_way_people_write_them():
    assert slide_reader.parse_range("12-14, 20") == [12, 13, 14, 20]
    assert slide_reader.parse_range("3 to 5") == [3, 4, 5]
    assert slide_reader.parse_range("9–7") == [7, 8, 9]  # an en dash, and backwards
    assert slide_reader.parse_range("nonsense") == []


def test_a_deck_is_grouped_into_the_parts_a_person_would_name(deck_bytes):
    deck = slide_reader.read_bytes(deck_bytes, "lecture.pptx")
    sections = deck["sections"]
    assert sections and sections[0]["title"] == "Enzymes" and sections[0]["from"] == 1
    assert sections[-1]["to"] == 4


def test_the_outline_is_readable_markdown_with_slide_numbers(deck_bytes):
    deck = slide_reader.read_bytes(deck_bytes, "lecture.pptx")
    outline = slide_reader.outline(deck)
    assert "## Slide 2 — What an enzyme does" in outline
    assert outline.index("Slide 2") < outline.index("Slide 3"), "slides stay in order"


def test_a_pdf_deck_becomes_one_slide_per_page(monkeypatch):
    import uploads

    monkeypatch.setattr(uploads, "extract_pdf_text", lambda data, max_pages=200:
                        "--- Page 1 ---\nTitration\nAcid into base\n\n--- Page 2 ---\nEnd point\nColour change")
    deck = slide_reader.read_bytes(b"%PDF-1.4 fake", "chem.pdf")
    assert deck["kind"] == "pdf" and len(deck["slides"]) == 2
    assert deck["slides"][0]["title"] == "Titration" and "Acid into base" in deck["slides"][0]["text"]


def test_formats_nyx_cannot_read_say_what_to_do_instead():
    with pytest.raises(slide_reader.SlideError) as old:
        slide_reader.read_bytes(b"\xd0\xcf\x11\xe0 old binary", "lecture.ppt")
    assert "Export as PDF" in str(old.value) or "export" in str(old.value).lower()

    with pytest.raises(slide_reader.SlideError):
        slide_reader.read_bytes(b"PK\x03\x04 not really a deck", "deck.pptx")


def test_a_deck_is_kept_beside_its_note_not_inside_it(tmp_path, monkeypatch, deck_bytes):
    import paths

    monkeypatch.setattr(paths, "data_path", lambda *parts: tmp_path.joinpath(*parts))
    deck = slide_reader.read_bytes(deck_bytes, "lecture.pptx")
    slide_reader.save_deck("note-1", deck)
    assert slide_reader.load_deck("note-1")["slides"][1]["title"] == "What an enzyme does"

    slide_reader.forget_deck("note-1")
    assert slide_reader.load_deck("note-1") is None


def test_an_uploaded_deck_becomes_a_note_you_can_study_from(tmp_path, monkeypatch, deck_bytes):
    """The whole path: upload → note → deck → questions on chosen slides.

    This is the test that would have caught the store refusing a "slides" note,
    which no amount of parser testing did.
    """
    import notes_store
    import paths
    import slide_reader as reader
    import study_tools
    import uploads
    from fastapi.testclient import TestClient

    monkeypatch.setattr(paths, "data_path", lambda *parts: tmp_path.joinpath(*parts))
    monkeypatch.setattr(notes_store, "_path", lambda: tmp_path / "notes.json")
    monkeypatch.setattr(uploads, "get_upload", lambda upload_id: {"path": str(deck_file), "name": "lecture.pptx",
                                                                  "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation"})
    deck_file = tmp_path / "lecture.pptx"
    deck_file.write_bytes(deck_bytes)

    seen: dict = {}

    def fake_action(action, title, body, **kwargs):
        seen.update(action=action, title=title, body=body, question=kwargs.get("question", ""))
        return {"kind": "text", "action": action, "title": "Questions on this part", "text": "1. What is induced fit?", "model": "test"}

    monkeypatch.setattr(study_tools, "run_action", fake_action)

    import server

    client = TestClient(server.app)
    made = client.post("/api/notes/slides", json={"upload_id": "up1"})
    assert made.status_code == 200, made.text
    note = made.json()["note"]
    assert note["kind"] == "slides" and "Slide 2" in note["body"]
    assert made.json()["deck"]["slides"] == 4

    shown = client.get(f"/api/notes/{note['id']}/slides")
    assert shown.json()["deck"]["with_notes"] == 1

    asked = client.post(f"/api/notes/{note['id']}/slides/study",
                        json={"action": "slides_questions", "slides": [3, 4]})
    assert asked.status_code == 200, asked.text
    assert asked.json()["where"] == "slides 3–4"
    assert "Induced fit" in seen["body"] and "Lowers activation energy" not in seen["body"]

    # A typed request routes itself: "quiz me" makes a quiz, not an essay about quizzes.
    assert study_tools.route_custom("quiz me on the enzymes part") == "quiz"
    assert study_tools.route_custom("make me a one-page cheat sheet") == "custom"

    client.delete(f"/api/notes/{note['id']}")
    assert reader.load_deck(note["id"]) is None, "the deck goes when the note goes"


def test_the_summary_says_what_is_there_without_resending_every_slide(deck_bytes):
    deck = slide_reader.read_bytes(deck_bytes, "lecture.pptx")
    summary = slide_reader.summary(deck)
    assert summary["slides"] == 4 and summary["with_notes"] == 1
    assert [t["n"] for t in summary["titles"]] == [1, 2, 3, 4]
    assert "text" not in str(summary["titles"][0]), "titles only — the slide bodies stay on the server"
