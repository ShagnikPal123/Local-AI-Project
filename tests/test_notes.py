"""Notes tab: notebooks, study material as validated specs, drawings read into notes (Request G13)."""

from __future__ import annotations

import json
import types

import pytest
from fastapi.testclient import TestClient

import notes_store
import study_tools


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(notes_store, "_path", lambda: tmp_path / "notes" / "notes.json")


@pytest.fixture()
def client():
    import server

    return TestClient(server.app, client=("127.0.0.1", 50003))


def _fake_model(monkeypatch, replies):
    queue = list(replies)
    monkeypatch.setattr(study_tools, "_run", lambda prompt, max_tokens=2400: (queue.pop(0), "Test · model"))


def test_notes_live_in_notebooks_and_deleting_a_notebook_keeps_its_notes():
    book = notes_store.add_notebook("Biology 101")
    note = notes_store.create("Cells", "Mitochondria make ATP.", book["id"])
    notes_store.update(note["id"], append="Ribosomes make proteins.")
    assert "Ribosomes" in notes_store.get(note["id"])["body"]
    notes_store.delete_notebook(book["id"])
    assert notes_store.get(note["id"])["notebook_id"] != book["id"]
    assert notes_store.search("ribosomes")[0]["id"] == note["id"]


def test_quiz_json_is_validated_into_a_spec_and_bad_questions_are_dropped(monkeypatch):
    _fake_model(monkeypatch, ["Here you go: " + json.dumps({"title": "Cells", "questions": [
        {"type": "mc", "question": "What makes ATP?", "options": ["Ribosome", "Mitochondria", "Nucleus"], "answer": 1, "explanation": "Powerhouse."},
        {"type": "tf", "question": "Ribosomes make proteins.", "answer": "true"},
        {"type": "mc", "question": "Broken", "options": ["A"], "answer": "B"},
        {"type": "short", "question": "Define ATP.", "answer": "The cell's energy currency."},
    ]})])
    result = study_tools.run_action("quiz", "Cells", "Mitochondria make ATP.")
    questions = result["spec"]["questions"]
    assert [q["type"] for q in questions] == ["mc", "tf", "short"]
    assert questions[0]["answer"] == "Mitochondria" and questions[1]["answer"] is True


def test_steps_need_a_question_and_text_actions_append_through_the_route(monkeypatch, client):
    with pytest.raises(study_tools.StudyError):
        study_tools.run_action("steps", "Math", "x", question="")
    note = client.post("/api/notes", json={"title": "Lecture 3", "body": "um so entropy always increases uh", "kind": "lecture"}).json()["note"]
    _fake_model(monkeypatch, ["# Entropy\n- Entropy of an isolated system never decreases."])
    response = client.post(f"/api/notes/{note['id']}/study", json={"action": "organize", "save": "append"})
    assert response.status_code == 200, response.text
    assert "## Organize into notes" in response.json()["note"]["body"]
    assert response.json()["model"] == "Test · model"


def test_a_drawing_is_read_into_the_note(monkeypatch, client, tmp_path):
    import uploads

    image = tmp_path / "sketch.png"
    image.write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(uploads, "get_upload", lambda upload_id: {"path": str(image), "mime": "image/png", "name": "sketch.png"})
    monkeypatch.setattr(study_tools, "read_drawing", lambda data, mime, hint="": {"text": "$E = mc^2$", "model": "Vision · test"})
    note = client.post("/api/notes", json={"title": "Physics"}).json()["note"]
    response = client.post(f"/api/notes/{note['id']}/drawing", json={"upload_id": "u1"})
    assert response.status_code == 200, response.text
    body = response.json()["note"]["body"]
    assert "![Sketch](/api/uploads/u1)" in body and "$E = mc^2$" in body
