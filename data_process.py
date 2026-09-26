"""Data Process Use: give Nyx data and ask for anything (Request R7–R8).

The owner (2026-09-17): "I can tell it to analyze data like a resume or group of resume or a code or spread sheet or
whatever and it will be able to look at that and using its data analyze features explain what's in it, sort, or do
whatever the user wants. Put a lot of effort into what the ai can do with this it is very free range. Even financial
analyzers can use this. Also the ai can suggest changes it can make to itself based on documents and only the user
can approve. Make sure each big idea is condensed into separate boxes which can be expanded."

A **job** takes files (uploads), links and a request in words, and works in visible steps:

1. **Read** every item: spreadsheets and CSV/JSON become tables (``data_tables``), documents become text, code stays
   code, pictures are transcribed by the image-check model.
2. **Profile** offline: column types and statistics, outliers and correlations for tables; for documents what kind
   they are (resume, financial statement, contract, code, paper) and the facts that kind carries — a resume's
   contact details, skills and years of experience; code's functions, imports and TODOs; a statement's line items
   and ratios.
3. **Plan** — a model reads the request and the profiles (not the raw data) and answers with *operations*
   (filter, sort, group, derive a formula, trend, outliers, correlate, describe), an optional chart, and ranking
   criteria when the request compares documents.
4. **Compute** the operations here, safely; rank documents per criterion (model scores in small batches, keyword
   coverage when no model answers).
5. **Explain** — findings, each its own box: a title, one line, the details, and the table or chart behind it.
6. **Suggest** — changes Nyx could make to itself because of these documents (a skill, an agent, extra expertise
   for an agent, a speed-up). They are boxes too, and nothing happens until the owner approves one.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import statistics
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import absorb_text
import data_tables
from paths import data_path

_LOG = logging.getLogger("nyx.data_process")

STEPS = ("read", "profile", "plan", "compute", "explain", "suggest")
MAX_ITEMS = 40
MAX_DOC_CHARS = 120_000
ModelFn = Callable[..., str]

PRESETS: List[Dict[str, str]] = [
    {"id": "rank_resumes", "label": "Rank resumes for a role", "request": "Rank these resumes for this role: <describe the role>. "
     "Score each on the must-haves, show a ranked table with reasons, and flag gaps."},
    {"id": "explain_code", "label": "Explain this code", "request": "Explain what this code does, how the parts fit together, and "
     "anything risky or slow in it."},
    {"id": "spreadsheet", "label": "Analyse a spreadsheet", "request": "Summarise this spreadsheet: totals, trends over time, "
     "unusual values, and what stands out. Chart the most important trend."},
    {"id": "financials", "label": "Financial statement analysis", "request": "Analyse these financial statements: revenue and "
     "profit trends, margins, growth rates, liquidity and debt ratios, and red flags."},
    {"id": "risks", "label": "Find problems and risks", "request": "Read these and list every problem, risk or inconsistency, "
     "most serious first, with where each one is."},
    {"id": "compare", "label": "Compare documents", "request": "Compare these documents side by side: what they agree on, "
     "where they differ, and which is stronger for my purpose."},
    {"id": "extract", "label": "Pull out a table", "request": "Pull every <thing> out of these into a table with columns for "
     "<fields>."},
    {"id": "sort", "label": "Sort and group", "request": "Group the rows by <column>, total <column> for each group, and sort "
     "from highest to lowest."},
]

_SKILLS = sorted({
    "python", "java", "javascript", "typescript", "react", "node.js", "sql", "postgresql", "mysql", "mongodb", "aws", "azure",
    "gcp", "docker", "kubernetes", "terraform", "linux", "git", "c++", "c#", "golang", "rust", "swift", "kotlin", "php", "ruby",
    "html", "css", "tailwind", "django", "flask", "fastapi", "spring", ".net", "pandas", "numpy", "tensorflow", "pytorch",
    "scikit-learn", "machine learning", "deep learning", "nlp", "llm", "data analysis", "excel", "tableau", "power bi",
    "statistics", "matlab", "spark", "hadoop", "airflow", "etl", "figma", "photoshop", "illustrator", "ui design",
    "ux", "product management", "agile", "scrum", "jira", "leadership", "communication", "project management", "sales",
    "marketing", "seo", "accounting", "financial modeling", "valuation", "budgeting", "forecasting", "quickbooks", "sap",
    "salesforce", "crm", "customer service", "autocad", "solidworks", "cad", "labview", "arduino", "embedded systems",
    "networking", "cybersecurity", "penetration testing", "devops", "ci/cd", "graphql", "rest api", "microservices",
    "selenium", "cypress", "jest", "unit testing", "java ee", "spring boot", "vue", "angular", "next.js", "redis", "kafka",
})
_SECTION = re.compile(r"^\s*(experience|work experience|professional experience|employment|education|skills|technical skills|"
                      r"projects|certifications|summary|objective|awards|publications|languages|volunteer)\b[:\s]*$", re.I | re.M)
_RANGE = re.compile(r"((?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+)?((?:19|20)\d{2})\s*(?:-|–|—|to)\s*"
                    r"((?:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+)?(?:(?:19|20)\d{2})|present|current|now)", re.I)
_DEGREES = [("PhD", r"\b(ph\.?d|doctor of philosophy|doctorate)\b"), ("Master's", r"\b(master'?s?|m\.?s\.?c?|mba|m\.?eng)\b"),
            ("Bachelor's", r"\b(bachelor'?s?|b\.?s\.?c?|b\.?a\.?|b\.?eng|b\.?tech)\b"), ("Associate", r"\bassociate'?s? degree\b"),
            ("High school", r"\b(high school|ged|diploma)\b")]
_LINE_ITEMS = {
    "revenue": r"^(total )?(net )?(revenues?|sales)\b", "cost_of_revenue": r"^(cost of (revenues?|sales|goods sold)|cogs)\b",
    "gross_profit": r"^gross (profit|margin)\b", "operating_income": r"^(operating (income|profit)|income from operations|ebit)\b",
    "net_income": r"^net (income|profit|earnings)\b", "total_assets": r"^total assets\b", "total_liabilities": r"^total liabilities\b",
    "equity": r"^(total )?(stockholders'?|shareholders'?) equity\b|^total equity\b", "current_assets": r"^total current assets\b",
    "current_liabilities": r"^total current liabilities\b", "cash": r"^cash( and cash equivalents)?\b",
    "operating_cash_flow": r"^(net )?cash (provided by|from|generated by) operating activities\b", "capex": r"^(capital expenditures?|purchases? of property)",
    "debt": r"^(long-term debt|total debt)\b", "interest_expense": r"^interest expense\b", "eps": r"^(diluted |basic )?earnings per share\b",
}


class DataError(RuntimeError):
    """What went wrong, in words fit for the job card."""


def default_model(prompt: str, *, system: str = "", max_tokens: int = 1500) -> str:
    from model_roles import MODEL_ROLES

    # Reasoning models otherwise spend the whole budget before the JSON (same fix as absorb_engine).
    return MODEL_ROLES.run("data_absorption", prompt, system="detailed thinking off\n" + system, max_tokens=max_tokens).text


# ---------------------------------------------------------------------------
# Reading and profiling
# ---------------------------------------------------------------------------

_CODE_EXT = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".java": "Java",
             ".c": "C", ".h": "C", ".cpp": "C++", ".hpp": "C++", ".cs": "C#", ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
             ".swift": "Swift", ".kt": "Kotlin", ".m": "MATLAB", ".r": "R", ".sql": "SQL", ".sh": "Shell", ".ps1": "PowerShell",
             ".ino": "Arduino", ".html": "HTML", ".css": "CSS", ".scala": "Scala", ".lua": "Lua", ".dart": "Dart"}


def detect_kind(name: str, text: str) -> str:
    lowered = (name or "").lower()
    suffix = Path(lowered).suffix
    if suffix in _CODE_EXT and suffix not in (".html",):
        return "code"
    head = (text or "")[:6000].lower()
    sections = len(_SECTION.findall(text[:8000] if text else ""))
    if sections >= 2 and re.search(r"@\w+\.\w+|linkedin|github\.com|\(\d{3}\)|\+\d{1,3}\s?\d", head):
        return "resume"
    finance_hits = sum(1 for word in ("revenue", "net income", "total assets", "balance sheet", "cash flow", "operating income",
                                      "earnings per share", "liabilities", "fiscal year") if word in head)
    if finance_hits >= 3:
        return "financial"
    if sum(1 for word in ("agreement", "party", "parties", "shall", "hereby", "termination", "governing law", "indemnif") if word in head) >= 4:
        return "contract"
    if sum(1 for word in ("abstract", "introduction", "references", "methodology", "et al") if word in head) >= 3:
        return "paper"
    return "document"


def resume_profile(text: str) -> Dict[str, Any]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    phone = re.search(r"(\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", text)
    links = re.findall(r"(?:https?://)?(?:www\.)?(?:linkedin\.com/in/|github\.com/)[\w-]+", text, re.I)
    lowered = text.lower()
    skills = [s for s in _SKILLS if re.search(rf"(?<![\w+#.]){re.escape(s)}(?![\w+#])", lowered)]
    periods: List[Tuple[int, int]] = []
    this_year = date.today().year
    for match in _RANGE.finditer(text):
        start = int(match.group(2))
        end_text = match.group(3).lower()
        end = this_year if end_text in ("present", "current", "now") else int(re.findall(r"\d{4}", end_text)[0])
        if 1950 <= start <= end <= this_year + 1:
            periods.append((start, end))
    merged: List[List[int]] = []
    for start, end in sorted(periods):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    years = sum(end - start for start, end in merged)
    degree = next((label for label, pattern in _DEGREES if re.search(pattern, lowered)), "")
    name = next((l for l in lines[:5] if 2 <= len(l.split()) <= 4 and not re.search(r"[@\d|:/]", l) and l[0].isupper()), "")
    sections = sorted({m.group(1).title() for m in _SECTION.finditer(text)})
    return {"name": name, "email": email.group(0) if email else "", "phone": phone.group(0) if phone else "",
            "links": sorted(set(links))[:4], "skills": skills[:40], "years_experience": years, "degree": degree,
            "sections": sections, "roles": len(periods)}


def code_profile(text: str, name: str) -> Dict[str, Any]:
    suffix = Path(name.lower()).suffix
    language = _CODE_EXT.get(suffix, "code")
    lines = text.splitlines()
    blank = sum(1 for l in lines if not l.strip())
    comments = sum(1 for l in lines if l.strip().startswith(("#", "//", "/*", "*", "--", "'")))
    functions: List[Dict[str, Any]] = []
    classes: List[str] = []
    imports: List[str] = []
    if language == "Python":
        try:
            tree = ast.parse(text)  # parsing only: nothing in the file runs
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    length = (getattr(node, "end_lineno", node.lineno) or node.lineno) - node.lineno + 1
                    functions.append({"name": node.name, "line": node.lineno, "lines": length})
                elif isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, ast.Import):
                    imports += [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
        except SyntaxError as error:
            functions.append({"name": f"(does not parse: line {error.lineno})", "line": error.lineno or 0, "lines": 0})
    else:
        for number, line in enumerate(lines, 1):
            match = re.match(r"\s*(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(|"
                             r"(?:public|private|protected|static|\s)*[\w<>\[\],]+\s+(\w+)\s*\([^;]*\)\s*\{|func\s+(\w+)|fn\s+(\w+)|def\s+(\w+))", line)
            if match:
                functions.append({"name": next(g for g in match.groups() if g), "line": number, "lines": 0})
            class_match = re.match(r"\s*(?:export\s+)?(?:public\s+)?(?:class|struct|interface|trait)\s+(\w+)", line)
            if class_match:
                classes.append(class_match.group(1))
            import_match = re.match(r"\s*(?:import\s+.*?from\s+['\"](.+?)['\"]|#include\s+[<\"](.+?)[>\"]|using\s+([\w.]+);|require\(['\"](.+?)['\"]\))", line)
            if import_match:
                imports.append(next(g for g in import_match.groups() if g))
    todos = [{"line": n, "text": l.strip()[:120]} for n, l in enumerate(lines, 1) if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", l)]
    branches = len(re.findall(r"\b(if|elif|else if|for|while|case|catch|except)\b", text))
    return {"language": language, "lines": len(lines), "code_lines": len(lines) - blank - comments, "comment_lines": comments,
            "functions": functions[:80], "classes": classes[:40], "imports": sorted(set(imports))[:40], "todos": todos[:20],
            "branches": branches, "longest": sorted(functions, key=lambda f: -f["lines"])[:5]}


def financial_profile(text: str) -> Dict[str, Any]:
    items: Dict[str, List[float]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        label = re.split(r"\s{2,}|\t|\s(?=[-($]?\d)", line, maxsplit=1)[0].strip().lower()
        for key, pattern in _LINE_ITEMS.items():
            if key in items or not re.search(pattern, label):
                continue
            numbers = [data_tables.to_number(n) for n in re.findall(r"\(?-?\$?\d[\d,]*(?:\.\d+)?\)?", line[len(label):])]
            numbers = [n for n in numbers if n is not None and not (1900 <= n <= 2100 and float(n).is_integer())]
            if numbers:
                items[key] = numbers[:6]
    latest = {k: v[0] for k, v in items.items()}
    prior = {k: v[1] for k, v in items.items() if len(v) > 1}

    def ratio(a: str, b: str, source: Dict[str, float]) -> Optional[float]:
        return round(source[a] / source[b], 4) if a in source and b in source and source[b] else None

    ratios = {
        "gross_margin": ratio("gross_profit", "revenue", latest), "operating_margin": ratio("operating_income", "revenue", latest),
        "net_margin": ratio("net_income", "revenue", latest), "current_ratio": ratio("current_assets", "current_liabilities", latest),
        "debt_to_equity": ratio("total_liabilities", "equity", latest), "return_on_assets": ratio("net_income", "total_assets", latest),
        "return_on_equity": ratio("net_income", "equity", latest), "interest_cover": ratio("operating_income", "interest_expense", latest),
    }
    if "gross_margin" in ratios and ratios["gross_margin"] is None and "revenue" in latest and "cost_of_revenue" in latest and latest["revenue"]:
        ratios["gross_margin"] = round((latest["revenue"] - abs(latest["cost_of_revenue"])) / latest["revenue"], 4)
    growth = {k: round((latest[k] - prior[k]) / abs(prior[k]), 4) for k in prior if prior[k]}
    free_cash_flow = (latest["operating_cash_flow"] - abs(latest["capex"])) if "operating_cash_flow" in latest and "capex" in latest else None
    flags = []
    if ratios.get("current_ratio") is not None and ratios["current_ratio"] < 1:
        flags.append(f"Current ratio {ratios['current_ratio']:.2f} — short-term liabilities exceed short-term assets.")
    if ratios.get("debt_to_equity") is not None and ratios["debt_to_equity"] > 2:
        flags.append(f"Liabilities are {ratios['debt_to_equity']:.1f}× equity.")
    if growth.get("revenue") is not None and growth.get("net_income") is not None and growth["revenue"] > 0 > growth["net_income"]:
        flags.append("Revenue grew while net income fell.")
    if free_cash_flow is not None and free_cash_flow < 0:
        flags.append("Free cash flow is negative.")
    if ratios.get("interest_cover") is not None and ratios["interest_cover"] < 2:
        flags.append(f"Operating income covers interest only {ratios['interest_cover']:.1f}×.")
    return {"items": items, "ratios": {k: v for k, v in ratios.items() if v is not None}, "growth": growth,
            "free_cash_flow": free_cash_flow, "flags": flags}


def document_profile(text: str) -> Dict[str, Any]:
    words = len(re.findall(r"\w+", text))
    headings = [l.strip("# ").strip()[:80] for l in text.splitlines() if re.match(r"^\s*(#{1,4}\s+\S|[A-Z][A-Z0-9 &/,-]{4,60}$)", l)][:20]
    money = re.findall(r"[$€£]\s?\d[\d,]*(?:\.\d+)?\s?(?:million|billion|k|m|bn)?", text, re.I)[:12]
    dates = re.findall(r"\b(?:\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.? \d{1,2},? \d{4})\b", text, re.I)[:12]
    return {"words": words, "reading_minutes": max(1, round(words / 230)), "headings": headings, "key_phrases": absorb_text.keyphrases(text, 12),
            "names": absorb_text.entities(text, 12), "money": money, "dates": dates,
            "percentages": re.findall(r"\b\d+(?:\.\d+)?\s?%", text)[:12]}


def read_item(item: Dict[str, Any], *, get: Any = None) -> Dict[str, Any]:
    """An upload or a link → ``{"name", "kind", "text", "tables"}``."""
    import absorb_sources
    import uploads

    if item.get("upload_id"):
        record = uploads.get_upload(item["upload_id"])
        if record is None:
            raise DataError("That upload is gone.")
        data = Path(record["path"]).read_bytes()
        name, mime = record["name"], record.get("mime", "")
    elif item.get("url"):
        absorb_sources._web_allowed()
        data, mime, _final = absorb_sources.fetch(item["url"], get=get)
        name = Path(item["url"].split("?")[0]).name or item["url"]
    elif item.get("text"):
        data, name, mime = str(item["text"]).encode("utf-8"), item.get("name") or "pasted text", "text/plain"
    else:
        raise DataError("Nothing to read.")
    suffix = Path(name.lower()).suffix
    tables: List[Dict[str, Any]] = []
    text = ""
    if uploads.kind_for(name, mime) == "image":
        from model_roles import MODEL_ROLES

        run = MODEL_ROLES.run("image_check", "Transcribe all text in this image exactly. Put any table in Markdown table form. "
                              "Then describe charts or diagrams in numbers and parts.", images=[(data, mime or "image/png")], max_tokens=1800)
        text = run.text
        tables = data_tables.markdown_tables(text, name)
    elif suffix in (".csv", ".tsv"):
        text = uploads._decode_text(data)
        tables = [data_tables.read_csv(text, name)]
    elif suffix == ".xlsx":
        text = uploads.extract_document_text(data, name)
        tables = data_tables.read_sheets(text, name)
    elif suffix == ".json":
        text = uploads._decode_text(data)
        table = data_tables.read_json(text, name)
        tables = [table] if table else []
    else:
        _title, text = absorb_sources.text_from(data, mime, name=name)
        if not text and data:
            text = uploads._decode_text(data)
        tables = data_tables.markdown_tables(text, name)
        if not tables and data_tables.looks_tabular(text):
            # Pasted or plain-text spreadsheet data: read it as a table rather than as prose.
            try:
                tables = [data_tables.read_csv(text, name)]
            except data_tables.TableError:
                tables = []
    return {"name": name, "kind": "table" if tables else detect_kind(name, text),
            "text": text[:MAX_DOC_CHARS], "tables": tables, "size": len(data)}


def profile_item(doc: Dict[str, Any]) -> Dict[str, Any]:
    kind = doc["kind"]
    text = doc.get("text") or ""
    out: Dict[str, Any] = {"name": doc["name"], "kind": kind, "size": doc.get("size", 0)}
    if doc.get("tables"):
        out["tables"] = [data_tables.profile(t) for t in doc["tables"][:6]]
    if kind == "resume":
        out["resume"] = resume_profile(text)
    elif kind == "code":
        out["code"] = code_profile(text, doc["name"])
    elif kind == "financial":
        out["financial"] = financial_profile(text)
    if kind not in ("table", "code"):
        out["document"] = document_profile(text)
    return out


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


class DataJobs:
    def __init__(self, *, store_dir: Optional[Path] = None, model_fn: Optional[ModelFn] = None, threaded: bool = True,
                 reader: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None) -> None:
        self._store_dir = store_dir
        self._model_fn = model_fn
        self._threaded = threaded
        self._reader = reader
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._stops: Dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._loaded = False

    def _dir(self) -> Path:
        path = self._store_dir or data_path("data_process")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load(self) -> None:
        if self._loaded:
            return
        with self._lock:
            for file in sorted(self._dir().glob("*.json")):
                try:
                    job = json.loads(file.read_text(encoding="utf-8"))
                    if job.get("status") == "running":
                        job["status"] = "interrupted"
                    self._jobs[job["id"]] = job
                except Exception:  # noqa: BLE001
                    continue
            self._loaded = True

    def _save(self, job: Dict[str, Any]) -> None:
        public = {k: v for k, v in job.items() if not k.startswith("_")}
        path = self._dir() / f"{job['id']}.json"
        try:
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(public, ensure_ascii=False, default=str), encoding="utf-8")
            temp.replace(path)
        except OSError as error:
            _LOG.warning("could not save data job: %s", error)

    def _publish(self, job: Dict[str, Any]) -> None:
        try:
            from agent_events import publish_ui

            publish_ui("data_process.update", job={"id": job["id"], "status": job["status"], "step": job.get("step")})
        except Exception:  # noqa: BLE001
            pass

    def list(self) -> List[Dict[str, Any]]:
        self._load()
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: -j.get("created_at", 0))
        return [{k: j.get(k) for k in ("id", "request", "status", "created_at", "items", "step")}
                | {"summary": (j.get("result") or {}).get("summary", "")[:200]} for j in jobs]

    def get(self, job_id: str) -> Dict[str, Any]:
        self._load()
        job = self._jobs.get(job_id)
        if job is None:
            raise DataError("No such analysis.")
        return {k: v for k, v in job.items() if not k.startswith("_")}

    def delete(self, job_id: str) -> None:
        self.get(job_id)
        with self._lock:
            self._jobs.pop(job_id, None)
        try:
            (self._dir() / f"{job_id}.json").unlink()
        except OSError:
            pass

    def stop(self, job_id: str) -> Dict[str, Any]:
        self.get(job_id)
        event = self._stops.get(job_id)
        if event is not None:
            event.set()
        return self.get(job_id)

    def start(self, request: str, *, uploads: Sequence[str] = (), links: Sequence[str] = (), text: str = "",
              parent: str = "") -> Dict[str, Any]:
        request = (request or "").strip()
        if len(request) < 3:
            raise DataError("Say what you want done with the data.")
        items = [{"upload_id": u} for u in uploads if str(u).strip()] + [{"url": l.strip()} for l in links if str(l).strip()]
        if text.strip():
            items.append({"text": text, "name": "pasted text"})
        if parent and not items:
            items = list(self.get(parent).get("sources") or [])
        if not items:
            raise DataError("Add at least one file, link or pasted text.")
        if len(items) > MAX_ITEMS:
            raise DataError(f"At most {MAX_ITEMS} items at once.")
        for item in items:
            if item.get("url") and not re.match(r"^https?://", item["url"]):
                raise DataError(f"Not a web link: {item['url'][:80]}")
        job = {"id": uuid.uuid4().hex[:10], "request": request[:4000], "status": "running", "created_at": time.time(), "parent": parent,
               "sources": items, "items": [], "step": "read", "steps": {s: "waiting" for s in STEPS}, "log": [], "result": None, "error": ""}
        with self._lock:
            self._load()
            self._jobs[job["id"]] = job
            self._stops[job["id"]] = threading.Event()
        self._save(job)
        if self._threaded:
            threading.Thread(target=self._run, args=(job,), name=f"nyx-data-{job['id']}", daemon=True).start()
        else:
            self._run(job)
        return self.get(job["id"])

    # --- running --------------------------------------------------------------------------------

    def _note(self, job: Dict[str, Any], text: str) -> None:
        job["log"].append({"t": time.time(), "text": str(text)[:300]})
        job["log"] = job["log"][-120:]

    def _step(self, job: Dict[str, Any], step: str, state: str = "working") -> None:
        job["step"] = step
        job["steps"][step] = state
        self._publish(job)

    def _stopped(self, job: Dict[str, Any]) -> bool:
        event = self._stops.get(job["id"])
        return bool(event and event.is_set())

    def _ask(self, job: Dict[str, Any], prompt: str, *, system: str, max_tokens: int = 1500) -> str:
        try:
            return (self._model_fn or default_model)(prompt, system=system, max_tokens=max_tokens) or ""
        except Exception as error:  # noqa: BLE001 - offline analysis still answers
            self._note(job, f"Model unavailable ({str(error)[:100]}); working from the numbers alone")
            return ""

    def _run(self, job: Dict[str, Any]) -> None:
        from absorb_engine import json_from

        try:
            # 1. Read
            self._step(job, "read")
            docs: List[Dict[str, Any]] = [None] * len(job["sources"])  # type: ignore[list-item]
            reader = self._reader or read_item

            def load(index: int) -> None:
                source = job["sources"][index]
                try:
                    docs[index] = reader(source)
                except Exception as error:  # noqa: BLE001
                    label = source.get("url") or source.get("upload_id") or source.get("name") or "item"
                    docs[index] = {"name": label, "kind": "error", "text": "", "tables": [], "error": str(error)[:200]}

            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(load, range(len(docs))))
            readable = [d for d in docs if d and d["kind"] != "error"]
            for doc in docs:
                if doc and doc["kind"] == "error":
                    self._note(job, f"Could not read {doc['name']}: {doc['error']}")
            if not readable:
                raise DataError("None of the items could be read.")
            self._note(job, f"Read {len(readable)} item(s): " + ", ".join(f"{d['name']} ({d['kind']})" for d in readable[:8]))
            self._step(job, "read", "done")
            # 2. Profile
            self._step(job, "profile")
            profiles = [profile_item(d) for d in readable]
            job["items"] = profiles
            tables: Dict[str, Dict[str, Any]] = {}
            for doc in readable:
                for table in doc.get("tables") or []:
                    tables[table["name"]] = table
            self._step(job, "profile", "done")
            self._save(job)
            if self._stopped(job):
                raise DataError("Stopped.")
            # 3. Plan
            self._step(job, "plan")
            plan = self._plan(job, readable, profiles, tables, json_from)
            job["plan"] = plan
            self._step(job, "plan", "done")
            # 4. Compute
            self._step(job, "compute")
            computed = self._compute(job, plan, readable, tables, json_from)
            self._step(job, "compute", "done")
            if self._stopped(job):
                raise DataError("Stopped.")
            # 5. Explain
            self._step(job, "explain")
            result = self._explain(job, readable, profiles, computed, json_from)
            self._step(job, "explain", "done")
            # 6. Suggest
            self._step(job, "suggest")
            result["suggestions"] = self._suggest(job, readable, profiles, result, json_from)
            self._step(job, "suggest", "done")
            job["result"] = result
            job["status"] = "done"
        except DataError as error:
            job["error"] = str(error)
            job["status"] = "stopped" if str(error) == "Stopped." else "error"
        except Exception as error:  # noqa: BLE001
            _LOG.exception("data job failed")
            job["error"] = f"{type(error).__name__}: {str(error)[:300]}"
            job["status"] = "error"
        job["finished_at"] = time.time()
        self._save(job)
        self._publish(job)

    def _plan(self, job: Dict[str, Any], docs: List[Dict[str, Any]], profiles: List[Dict[str, Any]],
              tables: Dict[str, Dict[str, Any]], json_from: Callable[[str], Any]) -> Dict[str, Any]:
        brief = []
        for doc, prof in zip(docs, profiles):
            entry: Dict[str, Any] = {"name": doc["name"], "kind": doc["kind"]}
            for table in doc.get("tables") or []:
                entry.setdefault("tables", []).append({"name": table["name"], "rows": len(table["rows"]), "columns": [
                    {"name": c["name"], "type": c["type"]} for c in data_tables.profile(table)["columns"]][:40],
                    "sample": table["rows"][:4]})
            for key in ("resume", "code", "financial"):
                if key in prof:
                    entry[key] = {k: v for k, v in prof[key].items() if k not in ("functions",)}
            if doc["kind"] not in ("table",):
                entry["start"] = (doc.get("text") or "")[:600]
            brief.append(entry)
        reply = self._ask(job, (
            f"The owner's request: {job['request']}\n\nThe data (profiles, not everything):\n"
            + json.dumps(brief, ensure_ascii=False, default=str)[:14000] + "\n\n"
            "Plan the analysis. Table operations you can use, run in order on one table:\n"
            '  {"op":"filter","where":[{"col":"","cmp":"= != > >= < <= contains not_contains starts in missing not_missing","value":""}],"any":false}\n'
            '  {"op":"sort","by":[{"col":"","desc":true}]}  {"op":"select","cols":[]}  {"op":"top","n":10}\n'
            '  {"op":"derive","name":"margin","expr":"(revenue - cost) / revenue"}  (arithmetic, columns with _ for spaces, abs round min max sqrt log)\n'
            '  {"op":"group","by":["col"],"agg":[{"col":"","fn":"sum|mean|median|min|max|count|std|unique"}]}\n'
            '  {"op":"describe","cols":[]}  {"op":"outliers","col":""}  {"op":"correlate","cols":[]}  {"op":"trend","x":"date col","y":"number col"}\n'
            "Reply with JSON only: {\"approach\": \"one sentence\", \"table_steps\": [{\"table\": \"exact table name\", \"title\": \"what it shows\", "
            "\"operations\": [], \"chart\": {\"type\": \"bar|line|scatter|area\", \"x\": \"col\", \"y\": [\"col\"]} or null}], "
            "\"rank\": {\"criteria\": [{\"name\": \"\", \"weight\": 1, \"look_for\": [\"keyword\"]}]} or null (only when documents are compared or ranked), "
            "\"per_item\": \"a question to answer about each document, or empty\"}"),
            system="You plan data analyses as JSON. Use only the operations listed. Reply with JSON only.", max_tokens=1600)
        plan = json_from(reply) if reply else None
        if not isinstance(plan, dict):
            plan = self._offline_plan(job, docs, tables)
            self._note(job, "Planned offline: " + plan["approach"])
        else:
            self._note(job, "Plan: " + str(plan.get("approach", ""))[:200])
        return plan

    def _offline_plan(self, job: Dict[str, Any], docs: List[Dict[str, Any]], tables: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        steps = []
        request = job["request"].lower()
        for name, table in list(tables.items())[:4]:
            prof = data_tables.profile(table)
            numeric = [c["name"] for c in prof["columns"] if c["type"] == "number"]
            dates = [c["name"] for c in prof["columns"] if c["type"] == "date"]
            steps.append({"table": name, "title": f"Summary of {name}", "operations": [{"op": "describe"}], "chart": None})
            if dates and numeric:
                steps.append({"table": name, "title": f"{numeric[0]} over {dates[0]}", "operations": [{"op": "sort", "by": [{"col": dates[0]}]}],
                              "chart": {"type": "line", "x": dates[0], "y": numeric[:2]}})
            if numeric:
                steps.append({"table": name, "title": f"Unusual {numeric[0]} values", "operations": [{"op": "outliers", "col": numeric[0]}], "chart": None})
        rank = None
        documents = [d for d in docs if not d.get("tables")]
        if len(documents) >= 2 or "rank" in request or "compare" in request:
            words = [w for w in absorb_text.content_words(job["request"]) if w not in ("rank", "resumes", "resume", "compare", "these", "role")]
            rank = {"criteria": [{"name": "Matches the request", "weight": 1, "look_for": words[:12]}]}
        return {"approach": "Describe each table, chart what changes over time, flag unusual values"
                + ("; rank the documents by how well they match the request" if rank else ""), "table_steps": steps, "rank": rank, "per_item": ""}

    def _compute(self, job: Dict[str, Any], plan: Dict[str, Any], docs: List[Dict[str, Any]], tables: Dict[str, Dict[str, Any]],
                 json_from: Callable[[str], Any]) -> Dict[str, Any]:
        out_tables: List[Dict[str, Any]] = []
        charts: List[Dict[str, Any]] = []
        for index, step in enumerate((plan.get("table_steps") or [])[:8]):
            if not isinstance(step, dict):
                continue
            name = str(step.get("table") or "")
            table = tables.get(name) or next((t for n, t in tables.items() if name and name.lower() in n.lower()), None) \
                or (next(iter(tables.values())) if len(tables) == 1 else None)
            if table is None:
                self._note(job, f"No table called {name}")
                continue
            try:
                result, notes = data_tables.run_operations(table, step.get("operations") or [])
            except data_tables.TableError as error:
                self._note(job, f"Skipped “{step.get('title', name)}”: {error}")
                continue
            for note in notes:
                self._note(job, note)
            table_id = f"t{index + 1}"
            preview = data_tables.preview(result)
            out_tables.append({"id": table_id, "title": str(step.get("title") or result["name"])[:120], **preview})
            chart = self._chart(step.get("chart"), result, str(step.get("title") or ""))
            if chart:
                charts.append({"id": f"c{index + 1}", "table": table_id, "spec": chart})
            job.setdefault("_full", {})[table_id] = result
        rankings = self._rank(job, plan.get("rank"), docs, json_from) if plan.get("rank") else []
        answers = self._per_item(job, str(plan.get("per_item") or ""), docs, json_from)
        return {"tables": out_tables, "charts": charts, "rankings": rankings, "answers": answers}

    @staticmethod
    def _chart(spec: Any, table: Dict[str, Any], title: str) -> Optional[Dict[str, Any]]:
        if not isinstance(spec, dict) or not table["rows"]:
            return None
        try:
            x_col = data_tables._column(table, spec.get("x"))
            ys = [data_tables._column(table, y) for y in (spec.get("y") or [])[:4]]
        except data_tables.TableError:
            return None
        rows = table["rows"][:200]
        series = []
        for y in ys:
            values = [data_tables.to_number(r.get(y)) for r in rows]
            if sum(1 for v in values if v is not None) >= 2:
                series.append({"name": y, "values": [v if v is not None else 0 for v in values]})
        if not series:
            return None
        kind = spec.get("type") if spec.get("type") in ("bar", "line", "scatter", "area") else "bar"
        return {"type": kind, "title": title[:80], "x": [str(r.get(x_col, ""))[:24] for r in rows], "series": series, "xLabel": x_col,
                "yLabel": ys[0] if len(ys) == 1 else ""}

    def _rank(self, job: Dict[str, Any], rank: Dict[str, Any], docs: List[Dict[str, Any]], json_from: Callable[[str], Any]) -> List[Dict[str, Any]]:
        criteria = [c for c in (rank.get("criteria") or []) if isinstance(c, dict) and c.get("name")][:8]
        documents = [d for d in docs if (d.get("text") or "").strip()]
        if not criteria or not documents:
            return []
        scores: Dict[str, Dict[str, Any]] = {}
        for doc in documents:
            lowered = doc["text"].lower()
            per = {}
            for criterion in criteria:
                terms = [str(t).lower() for t in criterion.get("look_for") or [] if str(t).strip()]
                per[criterion["name"]] = round(10 * sum(1 for t in terms if t in lowered) / len(terms), 1) if terms else 5.0
            scores[doc["name"]] = {"scores": per, "reasons": "", "by": "keywords"}
        for start in range(0, len(documents), 4):
            if self._stopped(job):
                break
            batch = documents[start:start + 4]
            reply = self._ask(job, (
                f"Request: {job['request']}\nCriteria (score each 0–10): " + "; ".join(f"{c['name']}" for c in criteria) + "\n\n"
                + "\n\n".join(f"### {d['name']}\n{d['text'][:3000]}" for d in batch)
                + '\n\nReply with JSON only: {"items": [{"name": "exact heading", "scores": {"criterion": 0}, "reasons": "two sentences, specific"}]}'),
                system="You score documents fairly against criteria, citing what is actually in them. Reply with JSON only.", max_tokens=1400)
            data = json_from(reply) if reply else None
            for entry in (data or {}).get("items", []) if isinstance(data, dict) else []:
                name = str(entry.get("name", ""))
                target = scores.get(name) or next((v for k, v in scores.items() if name and (name in k or k in name)), None)
                if target is None or not isinstance(entry.get("scores"), dict):
                    continue
                for criterion in criteria:
                    value = data_tables.to_number(entry["scores"].get(criterion["name"]))
                    if value is not None:
                        target["scores"][criterion["name"]] = max(0.0, min(10.0, value))
                target["reasons"] = str(entry.get("reasons") or "")[:500]
                target["by"] = "model"
            self._note(job, f"Scored {min(start + 4, len(documents))} of {len(documents)} documents")
        total_weight = sum(float(data_tables.to_number(c.get("weight")) or 1) for c in criteria) or 1
        ranked = []
        for name, entry in scores.items():
            total = sum(entry["scores"][c["name"]] * float(data_tables.to_number(c.get("weight")) or 1) for c in criteria) / total_weight
            ranked.append({"name": name, "score": round(total, 2), "scores": entry["scores"], "reasons": entry["reasons"], "by": entry["by"]})
        ranked.sort(key=lambda r: -r["score"])
        for position, entry in enumerate(ranked, 1):
            entry["rank"] = position
        return ranked

    def _per_item(self, job: Dict[str, Any], question: str, docs: List[Dict[str, Any]], json_from: Callable[[str], Any]) -> List[Dict[str, Any]]:
        if not question.strip():
            return []
        answers = []
        for start in range(0, min(len(docs), 16), 4):
            batch = [d for d in docs[start:start + 4] if (d.get("text") or "").strip()]
            if not batch:
                continue
            reply = self._ask(job, (
                f"Question for each document: {question}\n\n" + "\n\n".join(f"### {d['name']}\n{d['text'][:3000]}" for d in batch)
                + '\n\nReply with JSON only: {"items": [{"name": "exact heading", "answer": "short, specific"}]}'),
                system="You answer the same question about several documents. Reply with JSON only.", max_tokens=1200)
            data = json_from(reply) if reply else None
            for entry in (data or {}).get("items", []) if isinstance(data, dict) else []:
                answers.append({"name": str(entry.get("name", ""))[:120], "answer": str(entry.get("answer", ""))[:800]})
        return answers

    def _explain(self, job: Dict[str, Any], docs: List[Dict[str, Any]], profiles: List[Dict[str, Any]], computed: Dict[str, Any],
                 json_from: Callable[[str], Any]) -> Dict[str, Any]:
        evidence = {
            "tables": [{"id": t["id"], "title": t["title"], "columns": t["columns"], "rows": t["rows"][:15], "total": t["total"]} for t in computed["tables"]],
            "rankings": computed["rankings"][:20], "answers": computed["answers"][:20],
            "profiles": [{k: v for k, v in p.items() if k != "tables"} | ({"tables": [{"name": t["name"], "rows": t["rows"],
                          "columns": t["columns"][:20], "correlations": t["correlations"]} for t in p["tables"]]} if p.get("tables") else {})
                         for p in profiles],
        }
        reply = self._ask(job, (
            f"The owner's request: {job['request']}\n\nWhat was computed (numbers are exact; use them):\n"
            + json.dumps(evidence, ensure_ascii=False, default=str)[:20000] + "\n\n"
            "Answer the request. Split it into separate big ideas, each its own box. Reply with JSON only: "
            '{"summary": "3-4 sentences that answer the request directly", "findings": [{"title": "", "gist": "one sentence", '
            '"details": "markdown: the specifics, with numbers and where they are", "severity": "good|info|warn|risk", '
            '"evidence": "table id like t1, chart id like c1, rankings, or empty"}], "follow_ups": ["a next question the owner could ask"]}\n'
            "4 to 10 findings. Only claim what the data shows."),
            system="You are a precise data analyst. Every number you state must come from the evidence. Reply with JSON only.", max_tokens=2600)
        data = json_from(reply) if reply else None
        if isinstance(data, dict) and data.get("findings"):
            findings = []
            for entry in data["findings"][:12]:
                if not isinstance(entry, dict) or not entry.get("title"):
                    continue
                findings.append({"id": uuid.uuid4().hex[:6], "title": str(entry["title"])[:120], "gist": str(entry.get("gist") or "")[:300],
                                 "details": str(entry.get("details") or "")[:4000],
                                 "severity": entry.get("severity") if entry.get("severity") in ("good", "info", "warn", "risk") else "info",
                                 "evidence": str(entry.get("evidence") or "")[:40]})
            summary, follow_ups, written = str(data.get("summary") or "")[:1500], [str(f)[:160] for f in (data.get("follow_ups") or [])][:5], "model"
        else:
            findings, summary = self._offline_findings(job, docs, profiles, computed)
            follow_ups, written = [], "offline"
        return {"summary": summary, "findings": findings, "tables": computed["tables"], "charts": computed["charts"],
                "rankings": computed["rankings"], "answers": computed["answers"], "follow_ups": follow_ups, "written_by": written}

    def _offline_findings(self, job: Dict[str, Any], docs: List[Dict[str, Any]], profiles: List[Dict[str, Any]],
                          computed: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
        findings: List[Dict[str, Any]] = []

        def add(title: str, gist: str, details: str, severity: str = "info", evidence: str = "") -> None:
            findings.append({"id": uuid.uuid4().hex[:6], "title": title, "gist": gist, "details": details, "severity": severity, "evidence": evidence})

        for prof in profiles:
            for table in prof.get("tables") or []:
                gaps = [c for c in table["columns"] if c["missing"]]
                add(f"{table['name']}: {table['rows']} rows, {len(table['columns'])} columns",
                    ", ".join(f"{c['name']} ({c['type']})" for c in table["columns"][:8]),
                    "\n".join(f"- **{c['name']}** — {c['type']}" + (f", {c['min']:g} to {c['max']:g}, total {c['sum']:g}, average {c['mean']:g}" if c["type"] == "number" and "min" in c else "")
                              + (f", {c['missing']} missing" if c["missing"] else "") for c in table["columns"][:30]),
                    "warn" if gaps else "info")
                for column in table["columns"]:
                    if column.get("outliers"):
                        add(f"Unusual values in {column['name']}", f"{column['outliers']} value(s) far outside the usual range.",
                            f"The middle half of {column['name']} sits well inside {column['min']:g}–{column['max']:g}; {column['outliers']} value(s) fall far outside it.", "warn")
                for corr in table.get("correlations") or []:
                    add(f"{corr['a']} moves with {corr['b']}", f"Correlation {corr['r']:+.2f}.",
                        f"When {corr['a']} is higher, {corr['b']} tends to be {'higher' if corr['r'] > 0 else 'lower'} (r = {corr['r']:+.2f}). That is association, not cause.")
            if prof.get("resume"):
                r = prof["resume"]
                add(f"{r['name'] or prof['name']}: about {r['years_experience']} years' experience", f"{r['degree'] or 'No degree found'}; {len(r['skills'])} known skills.",
                    f"- Contact: {r['email'] or '—'} {r['phone'] or ''}\n- Skills: {', '.join(r['skills'][:20]) or '—'}\n- Sections: {', '.join(r['sections']) or '—'}")
            if prof.get("code"):
                c = prof["code"]
                add(f"{prof['name']}: {c['code_lines']} lines of {c['language']}", f"{len(c['functions'])} functions, {len(c['classes'])} classes, {len(c['todos'])} TODOs.",
                    "- Longest: " + ", ".join(f"{f['name']} ({f['lines']} lines)" for f in c["longest"] if f["lines"]) + "\n- Imports: " + ", ".join(c["imports"][:15]),
                    "warn" if c["todos"] else "info")
            if prof.get("financial"):
                f = prof["financial"]
                add(f"{prof['name']}: key ratios", ", ".join(f"{k.replace('_', ' ')} {v:.2%}" if 'margin' in k or 'return' in k else f"{k.replace('_', ' ')} {v:.2f}" for k, v in list(f["ratios"].items())[:4]),
                    "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in f["ratios"].items()) + "\n" + "\n".join(f"- growth in {k.replace('_', ' ')}: {v:+.1%}" for k, v in f["growth"].items()))
                for flag in f["flags"]:
                    add("Red flag", flag, flag, "risk")
        if computed["rankings"]:
            best = computed["rankings"][0]
            add(f"Best match: {best['name']}", f"Score {best['score']} of 10.",
                "\n".join(f"{r['rank']}. **{r['name']}** — {r['score']}" for r in computed["rankings"][:15]), "good", "rankings")
        summary = (f"Read {len(docs)} item(s) for “{job['request'][:120]}”. No model was available, so this is what the numbers and "
                   "structure show on their own; ask again when a model is reachable for a written answer.")
        return findings, summary

    def _suggest(self, job: Dict[str, Any], docs: List[Dict[str, Any]], profiles: List[Dict[str, Any]], result: Dict[str, Any],
                 json_from: Callable[[str], Any]) -> List[Dict[str, Any]]:
        from absorb_engine import ENGINE

        kinds = sorted({p["kind"] for p in profiles})
        reply = self._ask(job, (
            f"Nyx (an AI assistant) just did this for its owner: {job['request']}\nKinds of data: {', '.join(kinds)}.\n"
            f"What it found: {result.get('summary', '')}\n\n"
            "Suggest 1 to 4 changes Nyx could make to ITSELF so it does this kind of work better next time. Kinds: skill (name, "
            "description, instructions, triggers), agent (name, goal, instructions, expertise, emoji), agent_feature (agent, "
            "add_expertise, add_instructions), speedup (title, description, target). Be specific to this data.\n"
            'Reply with JSON only: {"suggestions": [{"kind": "", "title": "", "why": "", "spec": {}}]}'),
            system="You suggest concrete self-improvements. Reply with JSON only.", max_tokens=1200)
        data = json_from(reply) if reply else None
        out = []
        for item in (data or {}).get("suggestions", []) if isinstance(data, dict) else []:
            if isinstance(item, dict):
                suggestion = ENGINE._suggestion(item)
                if suggestion is not None:
                    out.append(suggestion)
        if not out and "resume" in kinds:
            out.append({"id": uuid.uuid4().hex[:8], "kind": "skill", "title": "Resume screening", "why": "You ranked resumes here.",
                        "spec": {"name": "Resume screening", "description": "Score resumes against a role, fairly and specifically",
                                 "instructions": "List the role's must-haves first. Score each resume 0–10 per must-have using only what the "
                                                 "resume says, quote the evidence, never guess age, gender or ethnicity, and flag gaps.",
                                 "triggers": ["resume", "cv", "candidate", "hiring"]}, "state": "pending", "result": ""})
        if not out and "financial" in kinds:
            out.append({"id": uuid.uuid4().hex[:8], "kind": "skill", "title": "Financial statement checklist", "why": "You analysed statements here.",
                        "spec": {"name": "Financial statement checklist", "description": "The ratios and red flags to check every time",
                                 "instructions": "Compute gross, operating and net margin; revenue and profit growth; current ratio; debt to "
                                                 "equity; free cash flow; interest cover. Flag falling margins with rising revenue, negative "
                                                 "free cash flow and current ratio under 1. Show the numbers used.",
                                 "triggers": ["balance sheet", "income statement", "10-k", "financials", "cash flow"]}, "state": "pending", "result": ""})
        return out

    def decide(self, job_id: str, suggestion_id: str, decision: str, by: str = "Owner") -> Dict[str, Any]:
        from absorb_engine import AbsorbError, apply_suggestion

        self.get(job_id)
        job = self._jobs[job_id]
        item = next((s for s in (job.get("result") or {}).get("suggestions", []) if s["id"] == suggestion_id), None)
        if item is None:
            raise DataError("No such suggestion.")
        if item["state"] != "pending":
            raise DataError(f"Already {item['state']}.")
        if decision == "dismiss":
            item["state"], item["result"] = "dismissed", "Dismissed"
        elif decision == "approve":
            try:
                item["result"] = apply_suggestion(item, by, origin=f"Data Process Use analysis {job_id}")
                item["state"] = "applied"
            except (AbsorbError, Exception) as error:  # noqa: BLE001
                item["state"], item["result"] = "failed", f"{type(error).__name__}: {str(error)[:200]}"
        else:
            raise DataError("Approve or dismiss.")
        self._save(job)
        return item

    def export(self, job_id: str, what: str = "report") -> Dict[str, str]:
        job = self.get(job_id)
        result = job.get("result") or {}
        if what.startswith("table:"):
            table_id = what.split(":", 1)[1]
            full = (self._jobs[job_id].get("_full") or {}).get(table_id)
            table = next((t for t in result.get("tables", []) if t["id"] == table_id), None)
            if table is None:
                raise DataError("No such table.")
            data = full or {"columns": table["columns"], "rows": [dict(zip(table["columns"], r)) for r in table["rows"]]}
            return {"filename": f"{re.sub(r'[^A-Za-z0-9]+', '-', table['title'])[:40] or 'table'}.csv", "mime": "text/csv",
                    "content": data_tables.to_csv(data)}
        lines = [f"# {job['request'][:120]}", "", result.get("summary", ""), ""]
        for finding in result.get("findings", []):
            lines += [f"## {finding['title']}", "", f"_{finding['gist']}_", "", finding["details"], ""]
        if result.get("rankings"):
            lines += ["## Ranking", "", "| # | Name | Score | Why |", "|---|---|---|---|"]
            lines += [f"| {r['rank']} | {r['name']} | {r['score']} | {r['reasons'].replace('|', '/')} |" for r in result["rankings"]]
        return {"filename": f"analysis-{job_id}.md", "mime": "text/markdown", "content": "\n".join(lines)}


JOBS = DataJobs()


def tool_analyze_data(request: str, upload_ids: str = "", links: str = "") -> str:
    """Chat: run Data Process Use on uploads/links and summarise the answer."""
    uploads = [u for u in re.split(r"[\s,]+", upload_ids or "") if u]
    urls = [u for u in re.split(r"[\s,]+", links or "") if u.startswith(("http://", "https://"))]
    try:
        job = JOBS.start(request, uploads=uploads, links=urls)
    except DataError as error:
        return f"Not started: {error}"
    return (f"Started analysis {job['id']}. It runs in the Data Absorption tab under Data Process Use, where the findings "
            "appear as boxes and any changes Nyx suggests wait for the owner's approval.")


def register_data_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="analyze_data",
        description=("Analyse data the owner gave (uploaded spreadsheets, CSVs, resumes, code, financial statements, documents, or "
                     "links): explain, sort, rank, compute ratios and trends, find outliers and risks. Runs in the Data Process Use view."),
        parameters=[ToolParam("request", "string", "What to do with the data, in the owner's words"),
                    ToolParam("upload_ids", "string", "Upload ids from the attached files, separated by spaces", required=False),
                    ToolParam("links", "string", "Links to read, separated by spaces", required=False)],
        handler=tool_analyze_data,
        category="learning",
    )
