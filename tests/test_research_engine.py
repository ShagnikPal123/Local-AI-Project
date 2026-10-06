"""Research tab (Request L): sources, standard/deep jobs, honest citations, paper mode, exports, teaching Nyx."""

from __future__ import annotations

import json

import pytest

import research_engine as re_eng

PAPER = {"kind": "paper", "title": "FlashAttention: Fast and Memory-Efficient Exact Attention", "authors": ["Tri Dao", "Daniel Y. Fu", "Stefano Ermon"],
         "year": 2022, "venue": "NeurIPS", "doi": "10.48550/arXiv.2205.14135", "url": "https://doi.org/10.48550/arXiv.2205.14135",
         "citations": 3000, "abstract": "Transformers are slow and memory-hungry on long sequences. FlashAttention is IO-aware.", "found_by": "OpenAlex"}
PAPER2 = {**PAPER, "title": "AirLLM: layer-wise inference", "authors": ["Gavin Li"], "year": 2023, "venue": "", "doi": "", "url": "https://example.org/airllm",
          "citations": 10, "abstract": "Run 70B models on 4 GB GPUs by loading one layer at a time."}


class Reply:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text

    def json(self):
        return self._payload


def test_openalex_results_are_normalized_with_abstracts_rebuilt():
    payload = {"results": [{"display_name": "Paper A", "publication_year": 2024, "cited_by_count": 5, "doi": "https://doi.org/10.1/abc",
                            "authorships": [{"author": {"display_name": "Ada Lovelace"}}], "primary_location": {"source": {"display_name": "Nature"}},
                            "best_oa_location": {"pdf_url": "https://x/p.pdf"}, "abstract_inverted_index": {"Hello": [0], "world": [1]}}]}
    papers = re_eng.search_openalex("q", 1, get=lambda *a, **k: Reply(200, payload))
    assert papers[0] == {**papers[0], "title": "Paper A", "doi": "10.1/abc", "url": "https://doi.org/10.1/abc", "venue": "Nature",
                         "abstract": "Hello world", "authors": ["Ada Lovelace"], "pdf_url": "https://x/p.pdf"}


def test_arxiv_atom_is_parsed():
    atom = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/1</id><title> Big  Model </title>'
            '<summary>Layers one by one.</summary><published>2023-05-01T00:00:00Z</published><author><name>Gavin Li</name></author>'
            '<link title="pdf" href="http://arxiv.org/pdf/1"/></entry></feed>')
    papers = re_eng.search_arxiv("q", 1, get=lambda *a, **k: Reply(200, text=atom))
    assert papers[0]["title"] == "Big Model" and papers[0]["year"] == 2023 and papers[0]["pdf_url"].endswith("/pdf/1")


def test_citation_styles():
    assert re_eng.format_citation(PAPER, "apa").startswith("Dao, T., Fu, D. Y., & Ermon, S. (2022). FlashAttention")
    assert re_eng.format_citation(PAPER, "mla").startswith('Dao, Tri, et al. "FlashAttention')
    assert re_eng.format_citation(PAPER, "ieee", 3).startswith("[3] T. Dao, D. Y. Fu, and S. Ermon,")
    assert "Available at: https://doi.org/" in re_eng.format_citation(PAPER, "harvard")
    bib = re_eng.format_citation(PAPER, "bibtex")
    assert bib.startswith("@article{dao2022flashattention,") and "author = {Tri Dao and Daniel Y. Fu and Stefano Ermon}" in bib
    web = re_eng.format_citation({"kind": "web", "title": "Guide", "url": "https://www.example.com/a"}, "apa")
    assert web.startswith("example.com (n.d.). Guide.")


def make_jobs(tmp_path, replies, fetched=None):
    prompts = []

    def model(prompt, system="", max_tokens=0):
        prompts.append(prompt)
        for marker, reply in replies.items():
            if marker in prompt:
                return reply
        return "{}"

    jobs = re_eng.ResearchJobs(model_fn=model, web_search=lambda q: [{"title": "Blog on layers", "url": "https://blog.example/airllm",
                                                                        "snippet": "loads layers one at a time"}],
                               paper_search=lambda q, n: [PAPER, PAPER2], fetch=lambda url: fetched or "AirLLM loads layers one at a time from disk.",
                               store_dir=tmp_path / "research", threaded=False)
    return jobs, prompts


@pytest.fixture(autouse=True)
def no_auto_teach(monkeypatch):
    monkeypatch.setattr(re_eng, "_auto_teach", lambda: False)


def test_standard_research_cites_only_real_sources(tmp_path):
    jobs, prompts = make_jobs(tmp_path, {"Write a concise research report": "## Summary\nLayer-wise loading works [3] and attention is IO-aware [1]. Also [9].\n## Findings\nx [2]\n## Conclusion\nok"})
    job = jobs.start("How can huge language models run on small GPUs?")
    assert job["status"] == "done", job["error"]
    assert [s["kind"] for s in job["sources"]] == ["paper", "web", "paper"]
    assert "[9]" not in job["report"] and job["removed_citations"] == ["[9]"], "an invented citation is removed"
    assert "## References" in job["report"] and "[1] T. Dao" in job["report"]
    assert job["summary"].startswith("Layer-wise loading works")
    assert not any("sub-questions" in p for p in prompts), "standard mode doesn't plan"


def test_deep_research_plans_extracts_claims_and_writes_long_report(tmp_path):
    jobs, prompts = make_jobs(tmp_path, {
        "sub-questions": json.dumps({"subquestions": ["What is layer-wise inference?", "What does flash attention change?"]}),
        "List the concrete claims": json.dumps({"claims": [{"claim": "One layer at a time fits 70B in 4 GB", "sources": [3], "confidence": "high"},
                                                           {"claim": "Bogus", "sources": [99]}]}),
        "Write a thorough research report": "## Summary\nIt works [3].\n## Key findings\n### Memory\nIO-aware [1]\n## Where sources disagree or evidence is thin\nn/a\n## Open questions\n?\n## Conclusion\nyes",
    })
    job = jobs.start("How can huge language models run on small GPUs?", mode="deep")
    assert job["status"] == "done", job["error"]
    assert job["plan"] == ["What is layer-wise inference?", "What does flash attention change?"]
    assert job["notes"] == [{"claim": "One layer at a time fits 70B in 4 GB", "sources": [3], "confidence": "high"}], "claims need real sources"
    report_prompt = next(p for p in prompts if "Write a thorough research report" in p)
    assert "Claims already extracted" in report_prompt


def test_paper_mode_exports_and_teaching(tmp_path, monkeypatch):
    jobs, _ = make_jobs(tmp_path, {"Write a concise research report": "## Summary\nWorks [1].\n## Findings\nMore [3].\n## Conclusion\nDone.",
                                   "Write an academic paper": "# Running Giants\n## Abstract\nWe review [1] and (Li, 2023).\n## Introduction\nIntro [3]."})
    job = jobs.start("How can huge language models run on small GPUs?")
    paper = jobs.draft_paper(job["job_id"], style="apa")
    assert paper["title"] == "Running Giants" and "## References" in paper["markdown"] and "Dao, T." in paper["markdown"]
    tex = jobs.export(job["job_id"], "tex", what="paper")["content"]
    assert "\\section{Abstract}" in tex and "\\cite{dao2022flashattention}" in tex and "\\title{Running Giants}" in tex
    assert "@article{dao2022flashattention" in jobs.export(job["job_id"], "bib")["content"]
    assert "<h2>Summary</h2>" in jobs.export(job["job_id"], "html")["content"]

    ingested, distilled = [], []
    import nyx_core
    import super_brain

    monkeypatch.setattr(super_brain.BRAIN, "ingest", lambda text, **kw: ingested.append((text, kw)))
    monkeypatch.setattr(nyx_core.CORE, "_append_distill", lambda record: distilled.append(record))
    taught = jobs.teach(job["job_id"])
    assert taught["facts"] >= 2 and taught["examples"] == 1
    assert all(kw["source"] == "research" for _, kw in ingested)
    assert distilled[0]["prompt"].startswith("How can huge") and "## References" not in distilled[0]["answer"]


def test_jobs_are_saved_and_a_restart_marks_running_ones(tmp_path):
    jobs, _ = make_jobs(tmp_path, {"Write a concise research report": "## Summary\nok [1]"})
    job = jobs.start("How can huge language models run on small GPUs?")
    reloaded = re_eng.ResearchJobs(store_dir=tmp_path / "research", threaded=False)
    assert reloaded.get(job["job_id"]).report.startswith("## Summary")
    with pytest.raises(re_eng.ResearchError):
        jobs.start("short")
    with pytest.raises(re_eng.ResearchError):
        jobs.start("A proper research question here", include_web=False, include_papers=False)


def test_routes(tmp_path, monkeypatch):
    import server
    from fastapi.testclient import TestClient

    jobs, _ = make_jobs(tmp_path, {"Write a concise research report": "## Summary\nok [1]"})
    monkeypatch.setattr(re_eng, "RESEARCH", jobs)
    monkeypatch.setattr(re_eng, "search_papers", lambda q, n=8: [PAPER])
    client = TestClient(server.app, client=("127.0.0.1", 50121))
    job = client.post("/api/research", json={"question": "How do huge models run on small GPUs?"}).json()["job"]
    assert job["status"] == "done"
    assert client.get("/api/research").json()["jobs"][0]["job_id"] == job["job_id"]
    exported = client.get(f"/api/research/{job['job_id']}/export?format=citations&style=mla")
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"] and 'Dao, Tri' in exported.text
    found = client.get("/api/research/papers?q=flash").json()["papers"][0]
    assert found["title"].startswith("FlashAttention")
    assert found["cite"]["mla"].startswith('Dao, Tri, et al.') and set(found["cite"]) == set(re_eng.STYLES), "every style, no second search"
    assert client.get("/api/research/papers?q=What is flash attention?").json()["query"] == "flash attention"
    cited = client.get(f"/api/research/{job['job_id']}/citations?style=apa").json()
    assert cited["style"] == "apa" and cited["citations"][0]["text"].startswith("Dao, T., Fu, D. Y., & Ermon, S. (2022)")
    assert client.get("/api/research/nope/citations").status_code == 409
    assert client.get("/api/research/cite?title=flash&style=ieee").json()["citation"].startswith("[")
    assert client.delete(f"/api/research/{job['job_id']}").json()["deleted"] == job["job_id"]


def test_switching_citation_style_needs_no_model(tmp_path):
    jobs, prompts = make_jobs(tmp_path, {"Write a concise research report": "## Summary\nWorks [1]."})
    job = jobs.start("How can huge language models run on small GPUs?")
    asked = len(prompts)
    mla = jobs.citations(job["job_id"], "mla")
    assert mla["style"] == "mla" and [c["n"] for c in mla["citations"]] == [s["n"] for s in job["sources"]]
    assert mla["citations"][0]["text"].startswith('Dao, Tri, et al. "FlashAttention')
    assert jobs.citations(job["job_id"], "ieee")["citations"][0]["text"].startswith("[1] T. Dao")
    assert jobs.citations(job["job_id"], "made-up")["style"] == "apa"
    assert len(prompts) == asked


def test_a_running_job_is_reported_to_the_processes_view(tmp_path, monkeypatch):
    """U31: research shows in Core → Processes while it works, once, with the tab that shows it."""
    import threading

    import feature_catalog

    release = threading.Event()

    def slow(prompt, system="", max_tokens=0):
        release.wait(10)
        return "## Summary\nok [1]"

    jobs = re_eng.ResearchJobs(model_fn=slow, web_search=lambda q: [], paper_search=lambda q, n: [PAPER],
                               store_dir=tmp_path / "research")
    monkeypatch.setattr(re_eng, "RESEARCH", jobs)
    job = jobs.start("How can huge language models run on small GPUs?", mode="standard")
    try:
        status = re_eng.background_status()
        rows = [row for row in feature_catalog.live_processes() if job["job_id"] in row["id"]]
    finally:
        release.set()
        for thread in threading.enumerate():
            if thread.name == f"nyx-research-{job['job_id']}":
                thread.join(10)
    assert [row["id"] for row in status] == [job["job_id"]] and status[0]["tab"] == "research"
    assert len(rows) == 1 and rows[0]["source"] == "module", "the job, not also its thread"
    assert jobs.get(job["job_id"]).status == "done" and re_eng.background_status() == []


def test_papers_are_searched_by_the_topic_words_of_the_question(tmp_path):
    """OpenAlex matches every word: the whole sentence found nothing relevant, so a job came back web-only (U1)."""
    assert re_eng.scholarly_query("What does the evidence say about spaced repetition for long-term retention?") == \
        "spaced repetition long-term retention"
    assert re_eng.looks_like_question("How do huge models run on small GPUs?")
    assert not re_eng.looks_like_question("FlashAttention: Fast and Memory-Efficient Exact Attention")

    asked = []

    def papers(query, n):
        asked.append(query)
        return [] if len(query.split()) > 3 else [PAPER]

    jobs = re_eng.ResearchJobs(model_fn=lambda prompt, **k: "## Summary\nok [1]", web_search=lambda q: [], paper_search=papers,
                               store_dir=tmp_path / "research", threaded=False)
    job = jobs.start("How well does layer-by-layer offloading let a 70B model run on a 16 GB GPU?")
    assert asked == ["layer-by-layer offloading 70b model run 16", "layer-by-layer offloading 70b"], "fewer words when none match"
    assert job["status"] == "done" and job["sources"][0]["kind"] == "paper"
    assert any(entry["text"].startswith("Papers for “layer-by-layer offloading 70b”: 1 found") for entry in job["log"])


def test_the_summary_drops_the_brackets_a_removed_citation_leaves():
    text = re_eng.ResearchJobs._summary("## Summary\nThe monograph by Sorokina (source [1]) shows it works [2].\n## Findings\nx")
    assert text == "The monograph by Sorokina shows it works."


def test_full_width_citation_marks_are_checked_like_the_rest(tmp_path):
    jobs, _ = make_jobs(tmp_path, {"Write a concise research report": "## Summary\nWorks 【1】 and ［7］."})
    job = jobs.start("How can huge language models run on small GPUs?")
    assert "Works [1]" in job["report"] and job["removed_citations"] == ["[7]"]
