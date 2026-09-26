"""The corpus and the distillation set: licenses enforced, duplicates dropped, capped, teachers permitted only."""

import json

import pytest

from identity0.corpus import dataset, sources
from identity0.corpus.store import CorpusStore, simhash

ARTICLE = ("Photosynthesis is the process by which green plants and some other organisms use sunlight to "
           "synthesize foods from carbon dioxide and water. ") * 8


def test_store_keeps_licensed_text_and_refuses_the_rest(tmp_path):
    store = CorpusStore(tmp_path)
    assert store.add(ARTICLE, source="wikipedia", title="Photosynthesis") == "added"
    assert store.add(ARTICLE + " Extra words at the end.", source="wikipedia", title="Photosynthesis 2") == "duplicate"
    assert store.add(ARTICLE.replace("plants", "algae"), source="web", title="A blog") == "not allowed"
    assert store.add("too short", source="wikipedia") == "empty"
    assert store.stats()["by_source"] == {"wikipedia": 1}
    assert "CC BY-SA" in store.card()


def test_store_stops_at_its_cap(tmp_path):
    import random

    store = CorpusStore(tmp_path, cap_mb=0.001)
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet"]
    results = [store.add(" ".join(random.Random(i).choices(words, k=4000)), source="gutenberg", title=f"b{i}")
               for i in range(10)]
    assert "full" in results


def test_simhash_is_close_for_near_copies_and_far_for_different_text():
    a, b = simhash(ARTICLE), simhash(ARTICLE + " and one more sentence here.")
    c = simhash("The stock market fell sharply on Tuesday after the central bank raised interest rates again.")
    assert bin(a ^ b).count("1") <= 6 < bin(a ^ c).count("1")


def test_gutenberg_header_and_footer_are_removed():
    raw = "Title\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\nIt was a dark night.\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\nlicense"
    assert sources.strip_gutenberg(raw) == "It was a dark night."


def test_wikipedia_fetchers_work_offline_with_a_fake_getter():
    class Response:
        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

    def fake_get(url, params=None, **kwargs):
        if params.get("prop") == "links":
            return Response({"query": {"pages": {"1": {"links": [{"title": "Moon"}, {"title": "Sun"}]}}}})
        titles = params["titles"].split("|")
        return Response({"query": {"pages": {str(i): {"title": t, "extract": f"{t} text.\n== References ==\nx"}
                                            for i, t in enumerate(titles)}}})

    assert sources.wikipedia_titles(get=fake_get) == ["Moon", "Sun"]
    docs = list(sources.wikipedia_articles(["Moon"], get=fake_get, pause=0))
    assert docs[0]["text"] == "Moon text." and "References" not in docs[0]["text"]


def test_distillation_refuses_teachers_whose_terms_forbid_it(tmp_path):
    with pytest.raises(ValueError):
        dataset.distill([{"prompt": "hi"}], teacher="gemini:gemini-flash", out=tmp_path / "x.jsonl",
                        complete=lambda *a, **k: {"ok": True, "text": "x" * 50})


def test_distillation_keeps_good_answers_from_a_permitted_teacher(tmp_path):
    out = tmp_path / "sft.jsonl"
    answers = iter([{"ok": True, "text": "Plants turn light into sugar; that is photosynthesis, in short."},
                    {"ok": False, "text": ""}, {"ok": True, "text": "<tool_call>{}</tool_call> and more text here"}])
    result = dataset.distill([{"prompt": "a"}, {"prompt": "b"}, {"prompt": "c"}], teacher="ollama:qwen3.5:9b", out=out,
                             complete=lambda *a, **k: next(answers))
    assert result == {"kept": 1, "skipped": 2, "teacher": "ollama:qwen3.5:9b", "note": ""}
    row = json.loads(out.read_text().splitlines()[0])
    assert row["messages"][-1]["role"] == "assistant" and row["teacher"] == "ollama:qwen3.5:9b"


def test_identity_examples_say_it_is_its_own_model():
    text = json.dumps(dataset.identity_examples(repeat=1))
    assert "Identity 0" in text and "Big Kahuna" in text and "No. Qwen is one of my teachers" in text


def test_only_trainable_experiences_become_examples(tmp_path):
    path = tmp_path / "experiences.jsonl"
    good = {"prompt": "What is a river?", "trainable": {"lead": True}, "lead": {"member": "ollama:qwen3.5:9b",
            "text": "A river is a natural stream of water flowing toward an ocean or lake."}, "verdict": None}
    bad = {"prompt": "x", "trainable": {"lead": False}, "lead": {"member": "gemini:g", "text": "y" * 80}, "verdict": None}
    path.write_text("\n".join(json.dumps(r) for r in (good, bad)), encoding="utf-8")
    rows = dataset.experience_examples(path)
    assert len(rows) == 1 and rows[0]["teacher"] == "ollama:qwen3.5:9b"


def test_distillation_stops_when_the_teacher_stops_answering(tmp_path):
    """A dead Ollama used to burn the whole time budget on empty answers; now it stops and says so."""
    out = tmp_path / "sft.jsonl"
    result = dataset.distill([{"prompt": str(i)} for i in range(40)], teacher="ollama:qwen3.5:9b", out=out,
                             complete=lambda *a, **k: {"ok": False, "text": "", "error": "connection refused"})
    assert result["kept"] == 0
    assert result["skipped"] < 20, "it kept asking a teacher that was not there"
    assert "stopped answering" in result["note"]


def test_synthetic_examples_are_computed_from_the_text_not_invented():
    """Thousands of instruction examples need no teacher, and every answer is checkable."""
    doc = {"title": "Photosynthesis", "source": "wikipedia",
           "text": ("Photosynthesis is how plants make food from light. It was first described in 1779 by Jan "
                    "Ingenhousz. The leaves hold the green pigment that catches the light. Water and carbon "
                    "dioxide are the raw materials it needs. Sugar and oxygen come out of the process.")}
    rows = dataset.synthetic_examples([doc], limit=50, rng=__import__("random").Random(1))
    asked = {row["messages"][1]["content"].split("\n")[0]: row["messages"][2]["content"] for row in rows}
    assert rows and all(row["source"] == "synthetic" and row["teacher"] == "self" for row in rows)
    for question, answer in asked.items():
        if question.startswith("What is the first year"):
            assert answer == "1779"
        elif question.startswith("Give this text a short title"):
            assert answer == "Photosynthesis"
        elif question.startswith("Rewrite this in lowercase"):
            assert answer == answer.lower()
        elif question.startswith("Give the first 3 words"):
            assert answer == "Photosynthesis is how"
        elif question.startswith('Does this text mention the word "bicycle"'):
            assert answer == "no"
