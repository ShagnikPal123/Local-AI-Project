"""Data Process Use: tables, safe formulas, resumes, code, financial statements, jobs and approvals (Request R7–R8)."""

import json

import pytest

import data_process
import data_tables

SALES_CSV = """date,region,units,price,cost
2026-01-01,North,120,9.5,6.1
2026-02-01,North,135,9.5,6.0
2026-03-01,South,90,10,6.5
2026-04-01,South,150,10,6.4
2026-05-01,North,800,9.5,6.2
2026-06-01,South,160,10.5,6.6
"""


def test_numbers_dates_and_types_are_read_like_a_person_would():
    assert data_tables.to_number("$1,234.50") == 1234.5
    assert data_tables.to_number("(120)") == -120
    assert data_tables.to_number("12%") == 12 and data_tables.to_number("3.4k") == 3400
    assert data_tables.to_number("abc") is None and data_tables.to_number(True) is None
    assert str(data_tables.to_date("Jan 2020")) == "2020-01-01" and str(data_tables.to_date("03/15/2021")) == "2021-03-15"
    table = data_tables.read_csv(SALES_CSV, "sales.csv")
    kinds = {c["name"]: c["type"] for c in data_tables.profile(table)["columns"]}
    assert kinds == {"date": "date", "region": "text", "units": "number", "price": "number", "cost": "number"}


def test_operations_filter_derive_group_sort_and_trend():
    table = data_tables.read_csv(SALES_CSV, "sales.csv")
    result, notes = data_tables.run_operations(table, [
        {"op": "derive", "name": "margin", "expr": "(price - cost) / price"},
        {"op": "filter", "where": [{"col": "units", "cmp": ">=", "value": 100}]},
        {"op": "group", "by": ["region"], "agg": [{"col": "units", "fn": "sum"}, {"col": "margin", "fn": "mean"}]},
        {"op": "sort", "by": [{"col": "sum of units", "desc": True}]},
    ])
    assert [r["region"] for r in result["rows"]] == ["North", "South"]
    assert result["rows"][0]["sum of units"] == 1055
    assert len(notes) == 4 and notes[1].startswith("Kept 5 of 6 rows")
    trend, _ = data_tables.run_operations(table, [{"op": "trend", "x": "date", "y": "units"}])
    measures = {r["measure"]: r["value"] for r in trend["rows"]}
    assert measures["first"] == 120 and measures["last"] == 160 and measures["change %"] == pytest.approx(33.33, abs=0.01)
    outliers, _ = data_tables.run_operations(table, [{"op": "outliers", "col": "units"}])
    assert [r["units"] for r in outliers["rows"]] == ["800"]


def test_a_column_named_a_different_way_still_matches():
    """Found live: the model asked for "units_sum" after a group produced "sum of units"."""
    table = {"name": "x", "columns": ["month", "sum of units", "average margin"], "rows": []}
    assert data_tables._column(table, "units_sum") == "sum of units"
    assert data_tables._column(table, "Units Sum") == "sum of units"
    assert data_tables._column(table, "margin") == "average margin"
    with pytest.raises(data_tables.TableError):
        data_tables._column(table, "profit")


def test_formulas_refuse_anything_but_arithmetic():
    table = data_tables.read_csv(SALES_CSV)
    for bad in ("__import__('os').system('calc')", "price.__class__", "[x for x in price]", "open('x')", "lambda: 1", "price if cost else 1"):
        with pytest.raises(data_tables.TableError):
            data_tables.run_operations(table, [{"op": "derive", "name": "x", "expr": bad}])
    with pytest.raises(data_tables.TableError):
        data_tables.run_operations(table, [{"op": "derive", "name": "x", "expr": "nosuchcolumn * 2"}])
    result, _ = data_tables.run_operations(table, [{"op": "derive", "name": "revenue", "expr": "round(units * price, 1)"}])
    assert result["rows"][0]["revenue"] == 1140.0


RESUME = """Jordan Rivera
jordan.rivera@example.com | (555) 123-4567 | linkedin.com/in/jrivera

Summary
Backend engineer who builds data pipelines.

Experience
Senior Engineer, Acme Corp — Jan 2020 - Present
Built Python and FastAPI services on AWS with Docker and Kubernetes.
Engineer, Beta LLC — 2016 - 2019
SQL reporting and machine learning experiments.

Education
B.S. Computer Science, State University, 2016

Skills
Python, SQL, AWS, Docker, Kubernetes, React
"""


def test_resumes_are_recognised_and_profiled():
    assert data_process.detect_kind("jordan.pdf", RESUME) == "resume"
    profile = data_process.resume_profile(RESUME)
    assert profile["name"] == "Jordan Rivera" and profile["email"] == "jordan.rivera@example.com"
    assert {"python", "sql", "aws", "docker", "kubernetes", "machine learning", "fastapi"} <= set(profile["skills"])
    assert profile["years_experience"] >= 9 and profile["degree"] == "Bachelor's"


def test_code_is_profiled_by_parsing_not_running():
    code = "import os\n\nclass A:\n    def run(self):\n        # TODO: handle errors\n        if os.name:\n            return 1\n\ndef helper(x):\n    return x * 2\n"
    profile = data_process.code_profile(code, "tool.py")
    assert profile["language"] == "Python" and profile["classes"] == ["A"]
    assert {f["name"] for f in profile["functions"]} == {"run", "helper"} and profile["imports"] == ["os"]
    assert profile["todos"][0]["line"] == 5
    js = data_process.code_profile("import x from 'react'\nexport function App() {\n}\nconst go = async () => {}\n", "App.tsx")
    assert js["language"] == "TypeScript" and {"App", "go"} <= {f["name"] for f in js["functions"]} and js["imports"] == ["react"]


STATEMENT = """Consolidated statements (in millions)          2026      2025
Total revenues                                   1,200     1,000
Cost of revenues                                   700       560
Gross profit                                       500       440
Operating income                                   150       160
Net income                                          90       110
Total current assets                               300       320
Total current liabilities                          350       300
Total assets                                     2,000     1,900
Total liabilities                                1,500     1,300
Total stockholders' equity                         500       600
Net cash provided by operating activities          120       140
Capital expenditures                              (180)     (100)
Interest expense                                    95        80
"""


def test_financial_statements_give_ratios_growth_and_red_flags():
    assert data_process.detect_kind("10k.pdf", STATEMENT) == "financial"
    profile = data_process.financial_profile(STATEMENT)
    assert profile["items"]["revenue"][:2] == [1200, 1000]
    assert profile["ratios"]["gross_margin"] == pytest.approx(0.4167, abs=1e-3)
    assert profile["ratios"]["current_ratio"] == pytest.approx(0.857, abs=1e-3)
    assert profile["growth"]["revenue"] == pytest.approx(0.2) and profile["growth"]["net_income"] < 0
    assert profile["free_cash_flow"] == -60
    flags = " ".join(profile["flags"])
    assert "Current ratio" in flags and "Revenue grew while net income fell" in flags and "Free cash flow is negative" in flags
    assert "3.0× equity" in flags and "interest only 1.6×" in flags


def _fake_reader(item):
    if item.get("name") == "sales.csv":
        return {"name": "sales.csv", "kind": "table", "text": SALES_CSV, "tables": [data_tables.read_csv(SALES_CSV, "sales.csv")], "size": 200}
    return {"name": item["name"], "kind": data_process.detect_kind(item["name"], item["text"]), "text": item["text"], "tables": [], "size": 100}


def test_a_job_plans_computes_explains_and_waits_for_approval(tmp_path, monkeypatch):
    def model(prompt, *, system="", max_tokens=1500):
        if "Plan the analysis" in prompt:
            return json.dumps({"approach": "Total units by region and chart units over time", "table_steps": [
                {"table": "sales.csv", "title": "Units by region", "operations": [{"op": "group", "by": ["region"], "agg": [{"col": "units", "fn": "sum"}]}],
                 "chart": {"type": "bar", "x": "region", "y": ["sum of units"]}},
                {"table": "sales.csv", "title": "Nonsense", "operations": [{"op": "explode"}]}], "rank": None, "per_item": ""})
        if "Answer the request" in prompt:
            assert '"sum of units"' in prompt  # the explanation is written from computed numbers
            return json.dumps({"summary": "North sold 1055 units.", "findings": [
                {"title": "North leads", "gist": "1055 units", "details": "North 1055, South 400.", "severity": "good", "evidence": "t1"}],
                "follow_ups": ["Why did May spike?"]})
        if "Suggest 1 to 4 changes" in prompt:
            return json.dumps({"suggestions": [{"kind": "skill", "title": "Sales roll-ups", "why": "x",
                                                "spec": {"name": "Sales roll-ups", "instructions": "Group by region first.", "triggers": ["sales"]}}]})
        return ""

    jobs = data_process.DataJobs(store_dir=tmp_path / "jobs", model_fn=model, threaded=False,
                                 reader=lambda item: _fake_reader({"name": "sales.csv"}))
    job = jobs.start("total units by region", uploads=["sales"])
    assert job["status"] == "done", job["error"]
    result = job["result"]
    assert result["tables"][0]["rows"] == [["North", 1055.0], ["South", 400.0]]
    assert result["charts"][0]["spec"]["series"][0]["values"] == [1055.0, 400.0]
    assert any("Skipped" in e["text"] for e in job["log"])
    assert result["findings"][0]["title"] == "North leads" and result["written_by"] == "model"
    assert result["suggestions"][0]["state"] == "pending"
    csv_export = jobs.export(job["id"], "table:t1")
    assert csv_export["content"].splitlines()[0] == "region,sum of units"
    assert "North leads" in jobs.export(job["id"])["content"]
    import skills

    store = skills.SkillStore(tmp_path / "skills.json", tmp_path / "library.json")
    monkeypatch.setattr(skills, "SKILL_STORE", store)
    decided = jobs.decide(job["id"], result["suggestions"][0]["id"], "approve")
    assert decided["state"] == "applied" and any(s["name"] == "Sales roll-ups" for s in store.list_skills())


def test_ranking_resumes_offline_and_with_a_model(tmp_path):
    other = RESUME.replace("Jordan Rivera", "Sam Lee").replace("Python", "Excel").replace("AWS", "Salesforce").replace("Kubernetes", "CRM")
    texts = {"jordan": RESUME, "sam": other}

    def reader(item):
        uid = item["upload_id"]
        return {"name": f"{uid}.txt", "kind": "resume", "text": texts[uid], "tables": [], "size": 1}

    def offline(prompt, **kw):
        raise RuntimeError("no model")

    jobs = data_process.DataJobs(store_dir=tmp_path / "offline", model_fn=offline, threaded=False, reader=reader)
    job = jobs.start("rank these resumes for a python aws kubernetes backend role", uploads=["sam", "jordan"])
    assert job["status"] == "done", job["error"]
    ranking = job["result"]["rankings"]
    assert [r["name"] for r in ranking] == ["jordan.txt", "sam.txt"]
    assert ranking[0]["by"] == "keywords" and ranking[0]["score"] > ranking[1]["score"]
    assert job["result"]["written_by"] == "offline"
    assert any(f["title"].startswith("Best match: jordan.txt") for f in job["result"]["findings"])
    assert job["result"]["suggestions"][0]["title"] == "Resume screening"

    def model(prompt, **kw):
        if "Plan the analysis" in prompt:
            return json.dumps({"approach": "rank", "table_steps": [], "per_item": "",
                               "rank": {"criteria": [{"name": "Backend fit", "weight": 1, "look_for": ["python"]}]}})
        if "score each 0" in prompt:
            return json.dumps({"items": [{"name": "jordan.txt", "scores": {"Backend fit": 9}, "reasons": "Python services on AWS."},
                                         {"name": "sam.txt", "scores": {"Backend fit": 2}, "reasons": "Sales tools only."}]})
        return ""

    jobs = data_process.DataJobs(store_dir=tmp_path / "model", model_fn=model, threaded=False, reader=reader)
    ranking = jobs.start("rank these resumes for a backend role", uploads=["sam", "jordan"])["result"]["rankings"]
    assert ranking[0]["name"] == "jordan.txt" and ranking[0]["score"] == 9 and ranking[0]["by"] == "model"
    assert ranking[1]["reasons"] == "Sales tools only."


def test_pasted_spreadsheet_text_becomes_a_table_not_prose(tmp_path):
    """Found live: a pasted CSV was read as a document, so every table operation had nothing to run on."""
    assert data_tables.looks_tabular(SALES_CSV)
    assert not data_tables.looks_tabular("The quick brown fox jumps over the lazy dog.\nIt did so twice, in fact.")
    item = data_process.read_item({"text": SALES_CSV, "name": "pasted text"})
    assert item["kind"] == "table" and item["tables"] and item["tables"][0]["columns"][:2] == ["date", "region"]

    jobs = data_process.DataJobs(store_dir=tmp_path / "j", model_fn=lambda *a, **k: "", threaded=False)
    job = jobs.start("group units by region", text=SALES_CSV)
    assert job["status"] == "done", job["error"]
    assert job["result"]["tables"], job["log"]


def test_requests_need_words_and_data(tmp_path):
    jobs = data_process.DataJobs(store_dir=tmp_path / "j", threaded=False)
    with pytest.raises(data_process.DataError):
        jobs.start("hi")
    with pytest.raises(data_process.DataError):
        jobs.start("analyse this please")
    with pytest.raises(data_process.DataError):
        jobs.start("analyse this please", links=["javascript:alert(1)"])
