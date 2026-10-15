"""A project's knowledge base (Drive doc 1, item 1.28): notes are cut into passages, the passages that fit a task are
found by BM25, and they reach that thread's brief along with the project's instructions. Local files only."""

import pytest


@pytest.fixture()
def kb(tmp_path, monkeypatch):
    import project_knowledge
    import projects

    monkeypatch.setattr(project_knowledge, "_path", lambda: tmp_path / "project_knowledge.json")
    monkeypatch.setattr(projects, "_path", lambda: tmp_path / "projects.json")
    return project_knowledge


def test_the_passage_that_fits_the_task_is_found(kb):
    kb.add("pr-1", "Style guide", "Buttons are pill shaped.\n\nThe dashboard palette is warm amber on charcoal.")
    kb.add("pr-1", "Server notes", "The API runs on port 8000 behind the local proxy.")
    found = kb.search("pr-1", "restyle the dashboard palette")
    assert found and found[0]["title"] == "Style guide" and "amber" in found[0]["text"]
    assert kb.search("pr-1", "zebra migration") == []
    assert kb.search("pr-2", "dashboard") == []  # another project's notes stay out


def test_long_text_is_cut_into_passages_and_the_brief_stays_short(kb):
    kb.add("pr-1", "Spec", ("The export button writes a CSV of the trades. " * 60) + "\n\nUnrelated closing words.")
    brief = kb.brief("pr-1", "export trades csv")
    assert brief.startswith("From the project's knowledge") and len(brief) <= kb.BRIEF_CHARS + 200
    assert all(len(p) <= kb.PASSAGE for p in kb._passages("word. " * 500))


def test_add_list_delete_and_refuse_empty(kb):
    doc = kb.add("pr-1", "", "First line becomes the title\nmore")
    assert doc["title"] == "First line becomes the title" and kb.list_docs("pr-1")[0]["id"] == doc["id"]
    with pytest.raises(kb.KnowledgeError):
        kb.add("pr-1", "x", "   ")
    assert kb.delete("pr-1", doc["id"]) and not kb.delete("pr-1", doc["id"])


def test_instructions_and_star_live_on_the_project(kb):
    import projects

    a = projects.create("Alpha")
    b = projects.create("Beta")
    projects.update(a["id"], {"instructions": "Always write tests first.", "starred": True})
    assert projects.list_projects()[0]["id"] == a["id"]  # starred first, even though Beta is newer
    assert "Always write tests first." in projects.project_note(a["id"])
    assert "instructions" not in projects.project_note(b["id"])
