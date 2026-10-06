"""Tests for the permanent general knowledge store."""

from knowledge import GeneralKnowledge, get_knowledge


def test_knowledge_loads_sections():
    knowledge = get_knowledge()
    assert knowledge.chunks
    assert "Mathematics" in knowledge.sections
    assert "History" in knowledge.sections
    assert "Units & Conversions" in knowledge.sections


def test_knowledge_search_finds_math_formulas():
    knowledge = get_knowledge()
    results = knowledge.search("quadratic formula")
    assert results
    assert results[0]["section"] == "Mathematics"
    assert "quadratic" in results[0]["text"].lower()


def test_knowledge_search_abbreviation_expansion():
    knowledge = get_knowledge()
    results = knowledge.search("WW2 dates")
    assert results
    assert results[0]["section"] == "History"


def test_knowledge_search_units_conversion():
    knowledge = get_knowledge()
    results = knowledge.search("km to miles")
    assert results
    assert results[0]["section"] == "Units & Conversions"


def test_knowledge_search_geography():
    knowledge = get_knowledge()
    results = knowledge.search("largest ocean")
    assert results
    assert results[0]["section"] == "Geography"


def test_knowledge_search_no_results():
    knowledge = get_knowledge()
    assert knowledge.search("zzqxwv nonsense") == []


def test_knowledge_search_text_human_readable():
    knowledge = get_knowledge()
    text = knowledge.search_text("cold war")
    assert "General knowledge for 'cold war'" in text
    assert "History" in text


def test_knowledge_build_context_prompt():
    knowledge = get_knowledge()
    prompt = knowledge.build_context_prompt()
    assert "[General Knowledge]" in prompt
    assert "search_knowledge" in prompt


def test_knowledge_missing_file_is_empty(tmp_path):
    knowledge = GeneralKnowledge(path=str(tmp_path / "nope.md"))
    assert not knowledge.chunks
    assert knowledge.search("anything") == []
    assert knowledge.build_context_prompt() == ""


def test_knowledge_is_found_whatever_folder_nyx_was_started_from(tmp_path, monkeypatch):
    """A CWD-relative path made an engine started from the outer folder load an empty knowledge base."""
    monkeypatch.chdir(tmp_path)
    knowledge = GeneralKnowledge()
    assert knowledge.chunks
    assert knowledge.path.is_absolute()
