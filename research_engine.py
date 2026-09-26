"""Research: standard and deep research with real sources, citations, paper drafting, and teaching Nyx (Request L).

The owner (2026-09-16): "Create a research (deep and standard) tab for research and add lots of stuff as well as
citations, paper publishing mode, and it can search and research papers. It can also help train the model so it
can upgrade."

A **research job** runs in the background and is saved, so it survives the tab closing:

* **Standard** — search the web and scholarly papers for the question, read the best few sources, and write a
  short report where every claim carries a numbered citation. About a minute.
* **Deep** — plan sub-questions first, search each one (web + papers), read many more sources, extract claims with
  the sources that support them, then write a long report with findings, disagreements and gaps. Several minutes.

Every ``[n]`` in a report points at a real source the job collected; numbers the model invents are removed and
said so. Papers come from OpenAlex (free, no key), with arXiv as a second source; any DOI can be looked up on
Crossref for a citation. Citations are formatted in APA, MLA, Chicago, IEEE, Harvard or BibTeX.

**Paper mode** drafts an academic paper (title, abstract, sections, references) from a finished job, in the chosen
citation style, exportable as Markdown, LaTeX + BibTeX or HTML.

**Teach Nyx** writes what a job found into Nyx's super brain (as research findings with their sources) and adds the
question and answer to Nyx Core's distillation set — the examples Nyx learns from to depend less on outside models.
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from paths import data_path

_LOG = logging.getLogger("nyx.research")

MODES: Dict[str, Dict[str, int]] = {
    "standard": {"subquestions": 0, "web": 5, "papers": 4, "read": 5, "max_sources": 12, "report_tokens": 2200},
    "deep": {"subquestions": 5, "web": 5, "papers": 5, "read": 16, "max_sources": 36, "report_tokens": 5000},
}
STYLES = ("apa", "mla", "chicago", "ieee", "harvard", "bibtex")
PAPER_SECTIONS = ["Abstract", "Introduction", "Related Work", "Methods", "Results", "Discussion", "Conclusion"]
_UA = {"User-Agent": "NyxIchos-Research/1.0 (local assistant; mailto:research@nyx.local)"}

ModelFn = Callable[..., str]


class ResearchError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


@dataclass
class Source:
    n: int
    kind: str                      # web | paper
    title: str
    url: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: str = ""
    doi: str = ""
    pdf_url: str = ""
    citations: Optional[int] = None
    abstract: str = ""
    snippet: str = ""
    excerpt: str = ""
    read: bool = False
    error: str = ""
    found_by: str = ""


def _abstract_from_index(index: Optional[Dict[str, List[int]]]) -> str:
    if not index:
        return ""
    words: Dict[int, str] = {}
    for word, positions in index.items():
        for position in positions:
            words[position] = word
    return " ".join(words[i] for i in sorted(words))[:3000]


def search_openalex(query: str, limit: int = 5, get: Optional[Callable[..., Any]] = None) -> List[Dict[str, Any]]:
    import requests

    fetch = get or requests.get
    params = {"search": query, "per-page": max(1, min(limit, 25)),
              "select": "id,display_name,publication_year,cited_by_count,doi,authorships,primary_location,best_oa_location,abstract_inverted_index,type"}
    response = fetch("https://api.openalex.org/works", params=params, headers=_UA, timeout=20)
    if response.status_code != 200:
        raise ResearchError(f"OpenAlex answered {response.status_code}")
    papers = []
    for work in response.json().get("results", []):
        location = work.get("primary_location") or {}
        best = work.get("best_oa_location") or {}
        doi = str(work.get("doi") or "").replace("https://doi.org/", "")
        papers.append({
            "kind": "paper", "title": work.get("display_name") or "", "year": work.get("publication_year"),
            "authors": [a.get("author", {}).get("display_name", "") for a in (work.get("authorships") or [])][:12],
            "venue": ((location.get("source") or {}).get("display_name") or ""), "doi": doi,
            "url": (f"https://doi.org/{doi}" if doi else location.get("landing_page_url") or work.get("id") or ""),
            "pdf_url": best.get("pdf_url") or "", "citations": work.get("cited_by_count"),
            "abstract": _abstract_from_index(work.get("abstract_inverted_index")), "found_by": "OpenAlex",
        })
    return papers


def search_arxiv(query: str, limit: int = 5, get: Optional[Callable[..., Any]] = None) -> List[Dict[str, Any]]:
    import requests

    fetch = get or requests.get
    response = fetch("https://export.arxiv.org/api/query", params={"search_query": f"all:{query}", "max_results": max(1, min(limit, 20))},
                     headers=_UA, timeout=20)
    if response.status_code != 200 or "<feed" not in response.text:
        raise ResearchError("arXiv is busy right now")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(response.text)
    papers = []
    for entry in root.findall("a:entry", ns):
        link = entry.findtext("a:id", default="", namespaces=ns)
        pdf = next((l.get("href", "") for l in entry.findall("a:link", ns) if l.get("title") == "pdf"), "")
        published = entry.findtext("a:published", default="", namespaces=ns)
        papers.append({
            "kind": "paper", "title": " ".join(entry.findtext("a:title", default="", namespaces=ns).split()),
            "authors": [a.findtext("a:name", default="", namespaces=ns) for a in entry.findall("a:author", ns)][:12],
            "year": int(published[:4]) if published[:4].isdigit() else None, "venue": "arXiv", "doi": "",
            "url": link, "pdf_url": pdf, "citations": None,
            "abstract": " ".join(entry.findtext("a:summary", default="", namespaces=ns).split())[:3000], "found_by": "arXiv",
        })
    return papers


def search_papers(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Scholarly papers for a query: OpenAlex first, arXiv to fill in. Never raises; an empty list means none found."""
    found: List[Dict[str, Any]] = []
    errors = []
    for search in (search_openalex, search_arxiv):
        if len(found) >= limit:
            break
        try:
            for paper in search(query, limit):
                if not _duplicate(paper, found):
                    found.append(paper)
        except Exception as error:  # noqa: BLE001 - one index down is not a failed search
            errors.append(str(error)[:80])
    return found[:limit]


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _duplicate(item: Dict[str, Any], existing: List[Dict[str, Any]]) -> bool:
    for other in existing:
        if item.get("doi") and item.get("doi") == other.get("doi"):
            return True
        if item.get("url") and item.get("url") == other.get("url"):
            return True
        if _norm_title(item.get("title", "")) and _norm_title(item.get("title", "")) == _norm_title(other.get("title", "")):
            return True
    return False


def crossref(doi: str) -> Dict[str, Any]:
    """Citation metadata for a DOI (Crossref, free)."""
    import requests

    clean = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", (doi or "").strip(), flags=re.I)
    if not re.match(r"^10\.\d{4,9}/\S+$", clean):
        raise ResearchError("That doesn't look like a DOI (10.xxxx/…).")
    response = requests.get(f"https://api.crossref.org/works/{clean}", headers=_UA, timeout=20)
    if response.status_code != 200:
        raise ResearchError(f"Crossref has no record of {clean}.")
    item = response.json().get("message", {})
    date = (item.get("published") or item.get("issued") or {}).get("date-parts", [[None]])[0]
    return {"kind": "paper", "title": " ".join((item.get("title") or [""])[0].split()), "doi": clean, "url": f"https://doi.org/{clean}",
            "authors": [" ".join(x for x in (a.get("given", ""), a.get("family", "")) if x) for a in item.get("author", [])][:12],
            "year": date[0] if date and date[0] else None, "venue": (item.get("container-title") or [""])[0],
            "citations": item.get("is-referenced-by-count"), "abstract": re.sub(r"<[^>]+>", "", item.get("abstract", ""))[:3000],
            "found_by": "Crossref"}


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


def _split_name(name: str) -> tuple:
    parts = [p for p in re.split(r"\s+", (name or "").strip()) if p]
    if not parts:
        return "", []
    if "," in name:
        last, _, rest = name.partition(",")
        return last.strip(), [p for p in rest.split() if p]
    return parts[-1], parts[:-1]


def _initials(given: List[str]) -> str:
    return " ".join(f"{g[0]}." for g in given if g and g[0].isalpha())


def _authors(source: Dict[str, Any], style: str) -> str:
    names = [a for a in source.get("authors") or [] if a]
    if not names:
        return source.get("venue") or (re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*", r"\1", source.get("url", ""))) if source.get("url") else "")
    if style in ("apa", "harvard"):
        formatted = [f"{_split_name(n)[0]}, {_initials(_split_name(n)[1])}".strip().rstrip(",") for n in names]
        if len(formatted) > 20:
            formatted = formatted[:19] + ["…", formatted[-1]]
        return formatted[0] if len(formatted) == 1 else ", ".join(formatted[:-1]) + ", & " + formatted[-1]
    if style == "mla":
        last, given = _split_name(names[0])
        first = f"{last}, {' '.join(given)}".strip().rstrip(",")
        return first if len(names) == 1 else (f"{first}, and {names[1]}" if len(names) == 2 else f"{first}, et al.")
    if style == "chicago":
        last, given = _split_name(names[0])
        first = f"{last}, {' '.join(given)}".strip().rstrip(",")
        rest = names[1:3]
        if len(names) > 3:
            return f"{first}, et al."
        return first if not rest else first + ", " + ", ".join(rest[:-1]) + (", and " if len(rest) > 1 else " and ") + rest[-1]
    if style == "ieee":
        formatted = [f"{_initials(_split_name(n)[1])} {_split_name(n)[0]}".strip() for n in names]
        if len(formatted) > 6:
            return f"{formatted[0]} et al."
        return formatted[0] if len(formatted) == 1 else ", ".join(formatted[:-1]) + ", and " + formatted[-1]
    return ", ".join(names)


def bibtex_key(source: Dict[str, Any]) -> str:
    last = _split_name((source.get("authors") or ["source"])[0])[0] or "source"
    word = next((w for w in _norm_title(source.get("title", "")).split() if len(w) > 3), "work")
    return re.sub(r"[^A-Za-z0-9]", "", f"{last}{source.get('year') or 'nd'}{word}").lower()


def format_citation(source: Dict[str, Any], style: str = "apa", number: Optional[int] = None) -> str:
    style = style if style in STYLES else "apa"
    title = (source.get("title") or "Untitled").rstrip(".")
    year = source.get("year") or "n.d."
    venue = source.get("venue") or ""
    link = f"https://doi.org/{source['doi']}" if source.get("doi") else source.get("url", "")
    authors = _authors(source, style)
    if style == "bibtex":
        entry = "article" if source.get("kind") == "paper" else "misc"
        fields = {"title": title, "author": " and ".join(source.get("authors") or []) or venue, "year": str(year),
                  "journal" if entry == "article" else "howpublished": venue or link, "doi": source.get("doi", ""), "url": link}
        body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
        return f"@{entry}{{{bibtex_key(source)},\n{body}\n}}"
    if style == "apa":
        return f"{authors} ({year}). {title}. {f'*{venue}*. ' if venue else ''}{link}".strip()
    if style == "harvard":
        return f"{authors} ({year}) {title}. {f'*{venue}*. ' if venue else ''}Available at: {link}".strip()
    if style == "mla":
        return f"{authors.rstrip('.')}. \"{title}.\" {f'*{venue}*, ' if venue else ''}{year}, {link}.".strip()
    if style == "chicago":
        return f"{authors.rstrip('.')}. {year}. \"{title}.\" {f'*{venue}*. ' if venue else ''}{link}.".strip()
    return f"[{number or source.get('n', '?')}] {authors}, \"{title},\" {f'*{venue}*, ' if venue else ''}{year}. {link}".strip()


def bibliography(sources: List[Dict[str, Any]], style: str = "apa") -> str:
    if style == "bibtex":
        return "\n\n".join(format_citation(s, "bibtex") for s in sources)
    if style == "ieee":
        return "\n".join(format_citation(s, "ieee", s.get("n")) for s in sources)
    ordered = sorted(sources, key=lambda s: _authors(s, style).lower())
    return "\n".join(f"- {format_citation(s, style)}" for s in ordered)


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


@dataclass
class Job:
    job_id: str
    question: str
    mode: str = "standard"
    include_web: bool = True
    include_papers: bool = True
    max_sources: int = 12
    status: str = "queued"          # queued | planning | searching | reading | analyzing | writing | done | stopped | error
    progress: float = 0.0
    step: str = "Waiting to start"
    log: List[Dict[str, Any]] = field(default_factory=list)
    plan: List[str] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[Dict[str, Any]] = field(default_factory=list)
    report: str = ""
    summary: str = ""
    removed_citations: List[str] = field(default_factory=list)
    paper: Dict[str, Any] = field(default_factory=dict)
    taught: Dict[str, Any] = field(default_factory=dict)
    models: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    error: str = ""

    def view(self, full: bool = True) -> Dict[str, Any]:
        data = asdict(self)
        data["elapsed_seconds"] = round((self.ended_at or time.time()) - self.created_at, 1)
        if not full:
            for key in ("sources", "notes", "report", "paper", "log"):
                data.pop(key, None)
            data["source_count"] = len(self.sources)
        return data


def _strip_thinking(text: str) -> str:
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    return text.strip()


def _json_from(text: str) -> Any:
    text = _strip_thinking(text)
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    body = fence.group(1) if fence else text
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = body.find(opener), body.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(body[start:end + 1])
            except ValueError:
                continue
    return None


class ResearchJobs:
    def __init__(self, *, model_fn: Optional[ModelFn] = None, web_search: Optional[Callable[[str], List[Dict[str, str]]]] = None,
                 paper_search: Optional[Callable[[str, int], List[Dict[str, Any]]]] = None, fetch: Optional[Callable[[str], str]] = None,
                 store_dir: Optional[Path] = None, threaded: bool = True) -> None:
        self._model_fn = model_fn
        self._web_search = web_search
        self._paper_search = paper_search or search_papers
        self._fetch = fetch
        self._store_dir = store_dir
        self._threaded = threaded
        self._lock = threading.RLock()
        self._jobs: Dict[str, Job] = {}
        self._stops: Dict[str, threading.Event] = {}
        self._loaded = False

    # --- storage -----------------------------------------------------------------------

    def _dir(self) -> Path:
        path = self._store_dir or data_path("research")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        for file in sorted(self._dir().glob("*.json"))[-200:]:
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                job = Job(**{k: v for k, v in data.items() if k in Job.__dataclass_fields__})
                if job.status not in ("done", "stopped", "error"):
                    job.status, job.error = "error", "Nyx restarted while this was running — start it again."
                self._jobs[job.job_id] = job
            except (OSError, ValueError, TypeError):
                continue

    def _save(self, job: Job) -> None:
        try:
            (self._dir() / f"{job.job_id}.json").write_text(json.dumps(asdict(job), ensure_ascii=False), encoding="utf-8")
        except OSError as error:
            _LOG.warning("could not save research job: %s", error)

    def _publish(self, job: Job) -> None:
        try:
            from agent_events import publish_ui

            publish_ui("research.job", job=job.view(full=False))
        except Exception:  # noqa: BLE001
            pass

    # --- reads --------------------------------------------------------------------------

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._load()
            return [j.view(full=False) for j in sorted(self._jobs.values(), key=lambda j: -j.created_at)]

    def get(self, job_id: str) -> Job:
        with self._lock:
            self._load()
            job = self._jobs.get(job_id)
        if job is None:
            raise ResearchError("No such research.")
        return job

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._load()
            job = self._jobs.pop(job_id, None)
            if job is None:
                raise ResearchError("No such research.")
            stop = self._stops.get(job_id)
            if stop:
                stop.set()
        try:
            (self._dir() / f"{job_id}.json").unlink()
        except OSError:
            pass

    def stop(self, job_id: str) -> Dict[str, Any]:
        job = self.get(job_id)
        stop = self._stops.get(job_id)
        if stop:
            stop.set()
        return job.view()

    # --- the pipeline ---------------------------------------------------------------------

    def start(self, question: str, *, mode: str = "standard", include_web: bool = True, include_papers: bool = True,
              max_sources: int = 0) -> Dict[str, Any]:
        question = (question or "").strip()
        if len(question) < 8:
            raise ResearchError("Ask a research question (a sentence or more).")
        if mode not in MODES:
            raise ResearchError("Mode must be standard or deep.")
        if not include_web and not include_papers:
            raise ResearchError("Search the web, papers, or both.")
        limits = MODES[mode]
        job = Job(job_id=uuid.uuid4().hex[:10], question=question[:2000], mode=mode, include_web=include_web,
                  include_papers=include_papers, max_sources=max(3, min(int(max_sources or limits["max_sources"]), 60)))
        with self._lock:
            self._load()
            self._jobs[job.job_id] = job
            self._stops[job.job_id] = threading.Event()
        self._save(job)
        if self._threaded:
            threading.Thread(target=self._run, args=(job,), name=f"nyx-research-{job.job_id}", daemon=True).start()
        else:
            self._run(job)
        return job.view()

    def _note(self, job: Job, status: str, step: str, progress: float) -> None:
        with self._lock:
            job.status, job.step, job.progress = status, step[:200], round(max(job.progress, progress), 3)
            job.log.append({"ts": time.time(), "text": step[:300]})
            del job.log[:-80]
        self._save(job)
        self._publish(job)

    def _stopped(self, job: Job) -> bool:
        stop = self._stops.get(job.job_id)
        return bool(stop and stop.is_set())

    def _model(self, job: Job, prompt: str, *, system: str, max_tokens: int) -> str:
        if self._model_fn is not None:
            return self._model_fn(prompt, system=system, max_tokens=max_tokens)
        from model_roles import MODEL_ROLES

        run = MODEL_ROLES.run("research", prompt, system="detailed thinking off\n" + system, max_tokens=max_tokens)
        label = run.label
        if label not in job.models:
            job.models.append(label)
        return run.text

    def _run(self, job: Job) -> None:
        limits = MODES[job.mode]
        try:
            # 1. Plan
            queries = [job.question]
            if limits["subquestions"]:
                self._note(job, "planning", "Planning the research — breaking the question into parts", 0.05)
                reply = self._model(job, (
                    f"Research question: {job.question}\n\nBreak it into at most {limits['subquestions']} focused sub-questions that "
                    "together answer it, each phrased as a search query. Reply with JSON only: {\"subquestions\": [\"...\"]}"),
                    system="You plan research. JSON only.", max_tokens=700)
                data = _json_from(reply) or {}
                plan = [str(q).strip() for q in (data.get("subquestions") if isinstance(data, dict) else data or []) if str(q).strip()]
                job.plan = plan[: limits["subquestions"]]
                queries += job.plan
            if self._stopped(job):
                return self._finish(job, "stopped")

            # 2. Search
            collected: List[Dict[str, Any]] = []
            for index, query in enumerate(queries):
                if self._stopped(job):
                    return self._finish(job, "stopped")
                self._note(job, "searching", f"Searching: {query[:120]}", 0.1 + 0.25 * index / max(1, len(queries)))
                if job.include_papers:
                    try:
                        for paper in self._paper_search(query, limits["papers"]):
                            if not _duplicate(paper, collected):
                                collected.append(paper)
                    except Exception as error:  # noqa: BLE001
                        job.log.append({"ts": time.time(), "text": f"Paper search failed: {str(error)[:120]}"})
                if job.include_web:
                    for result in self._web(query)[: limits["web"]]:
                        item = {"kind": "web", "title": result.get("title", "") or result.get("url", ""), "url": result.get("url", ""),
                                "snippet": str(result.get("snippet", ""))[:600], "found_by": "web search"}
                        if item["url"] and not _duplicate(item, collected):
                            collected.append(item)
            # Papers with abstracts and many citations first, then the web, keeping both kinds represented.
            papers = sorted((c for c in collected if c["kind"] == "paper"), key=lambda c: (-(bool(c.get("abstract"))), -(c.get("citations") or 0)))
            web = [c for c in collected if c["kind"] == "web"]
            mixed: List[Dict[str, Any]] = []
            while (papers or web) and len(mixed) < job.max_sources:
                if papers:
                    mixed.append(papers.pop(0))
                if web and len(mixed) < job.max_sources:
                    mixed.append(web.pop(0))
            job.sources = [asdict(Source(n=i + 1, **{k: v for k, v in s.items() if k in Source.__dataclass_fields__ and k != "n"}))
                           for i, s in enumerate(mixed)]
            if not job.sources:
                raise ResearchError("No sources were found. Try other words, or turn on both web and papers.")
            self._note(job, "reading", f"Found {len(job.sources)} sources", 0.38)

            # 3. Read
            to_read = job.sources[: limits["read"]]
            with ThreadPoolExecutor(max_workers=4) as pool:
                for done, _ in enumerate(pool.map(self._read, to_read), 1):
                    if done % 3 == 0 or done == len(to_read):
                        self._note(job, "reading", f"Read {done} of {len(to_read)} sources", 0.38 + 0.22 * done / len(to_read))
                    if self._stopped(job):
                        break
            if self._stopped(job):
                return self._finish(job, "stopped")

            # 4. Analyze (deep): claims with the sources that support them
            if job.mode == "deep":
                readable = [s for s in job.sources if s.get("excerpt") or s.get("abstract") or s.get("snippet")]
                batches = [readable[i:i + 5] for i in range(0, len(readable), 5)]
                for index, batch in enumerate(batches):
                    if self._stopped(job):
                        return self._finish(job, "stopped")
                    self._note(job, "analyzing", f"Extracting claims ({index + 1}/{len(batches)})", 0.6 + 0.2 * index / max(1, len(batches)))
                    reply = self._model(job, (
                        f"Research question: {job.question}\n\nSources:\n{self._source_block(batch, 1500)}\n\n"
                        "List the concrete claims these sources make that help answer the question. Reply with JSON only: "
                        "{\"claims\": [{\"claim\": \"...\", \"sources\": [n], \"confidence\": \"high|medium|low\"}]}. "
                        "Use only the source numbers shown. At most 8 claims."),
                        system="You extract evidence precisely. JSON only.", max_tokens=1600)
                    data = _json_from(reply) or {}
                    valid = {s["n"] for s in batch}
                    for claim in (data.get("claims") if isinstance(data, dict) else []) or []:
                        refs = [int(n) for n in claim.get("sources", []) if str(n).isdigit() and int(n) in valid]
                        if claim.get("claim") and refs:
                            job.notes.append({"claim": str(claim["claim"])[:500], "sources": refs,
                                              "confidence": str(claim.get("confidence", "medium"))[:10]})

            # 5. Write
            self._note(job, "writing", "Writing the report with citations", 0.82)
            job.report = self._write_report(job, limits)
            job.summary = self._summary(job.report)
            self._finish(job, "done")
        except Exception as error:  # noqa: BLE001 - a failed job says why
            job.error = str(error)[:400]
            self._finish(job, "error")

    def _web(self, query: str) -> List[Dict[str, str]]:
        try:
            if self._web_search is not None:
                return self._web_search(query)
            import web_access

            return web_access.search_results(query, freshness="any")
        except Exception:  # noqa: BLE001
            return []

    def _read(self, source: Dict[str, Any]) -> None:
        if source["kind"] == "paper":
            source["excerpt"] = source.get("abstract", "")[:3000]
            source["read"] = bool(source["excerpt"])
            if not source["read"]:
                source["error"] = "No abstract available"
            return
        try:
            if self._fetch is not None:
                text = self._fetch(source["url"])
            else:
                import web_access

                text = web_access.fetch(source["url"])
            source["excerpt"], source["read"] = _relevant(text, source.get("snippet", ""), 3500), True
        except Exception as error:  # noqa: BLE001
            source["error"] = f"Could not read: {type(error).__name__}"

    @staticmethod
    def _source_block(sources: List[Dict[str, Any]], chars: int) -> str:
        lines = []
        for s in sources:
            who = ", ".join((s.get("authors") or [])[:3]) or s.get("venue") or s.get("url", "")
            body = s.get("excerpt") or s.get("abstract") or s.get("snippet") or ""
            lines.append(f"[{s['n']}] {s['title']} ({who}, {s.get('year') or 'n.d.'}; {s['kind']})\n{body[:chars]}")
        return "\n\n".join(lines)

    def _write_report(self, job: Job, limits: Dict[str, int]) -> str:
        usable = [s for s in job.sources if s.get("excerpt") or s.get("abstract") or s.get("snippet")]
        notes = "\n".join(f"- {n['claim']} {''.join(f'[{x}]' for x in n['sources'])} ({n['confidence']})" for n in job.notes[:60])
        shape = ("## Summary\n## Key findings (one ### per theme)\n## Where sources disagree or evidence is thin\n## Open questions\n"
                 "## Conclusion" if job.mode == "deep" else "## Summary\n## Findings\n## Conclusion")
        prompt = (
            f"Research question: {job.question}\n\n"
            + (f"Claims already extracted:\n{notes}\n\n" if notes else "")
            + f"Sources:\n{self._source_block(usable, 1800 if job.mode == 'deep' else 1200)}\n\n"
            f"Write a {'thorough' if job.mode == 'deep' else 'concise'} research report in Markdown with these sections:\n{shape}\n\n"
            "Rules: support every factual sentence with numbered citations like [2] or [1][4] that refer ONLY to the sources "
            "above; never invent a source, number or statistic; say plainly when the sources don't settle something; do not "
            "add a references list (it is added for you)."
        )
        reply = _strip_thinking(self._model(job, prompt, system="You are a careful research analyst who cites every claim.",
                                            max_tokens=limits["report_tokens"]))
        valid = {s["n"] for s in job.sources}
        removed: List[str] = []

        def check(match: "re.Match[str]") -> str:
            number = int(match.group(1))
            if number in valid:
                return match.group(0)
            removed.append(match.group(0))
            return ""

        report = re.sub(r"\[(\d{1,3})\]", check, reply)
        job.removed_citations = removed[:20]
        cited = sorted({int(n) for n in re.findall(r"\[(\d{1,3})\]", report)})
        references = [s for s in job.sources if s["n"] in cited]
        report = report.rstrip() + "\n\n## References\n" + "\n".join(format_citation(s, "ieee", s["n"]) for s in references)
        return report

    @staticmethod
    def _summary(report: str) -> str:
        match = re.search(r"##\s*Summary\s*\n+(.+?)(?:\n##|\Z)", report, re.S)
        text = match.group(1) if match else report
        return re.sub(r"\s+", " ", re.sub(r"\[\d+\]", "", text)).strip()[:700]

    def _finish(self, job: Job, status: str) -> None:
        job.ended_at = time.time()
        job.progress = 1.0 if status == "done" else job.progress
        step = {"done": "Finished", "stopped": "Stopped", "error": f"Failed: {job.error}"}.get(status, status)
        self._note(job, status, step, job.progress)
        if status == "done":
            try:
                if _auto_teach():
                    self.teach(job.job_id)
            except Exception:  # noqa: BLE001
                pass

    # --- after a job ------------------------------------------------------------------------------

    def draft_paper(self, job_id: str, *, title: str = "", style: str = "apa", sections: Optional[List[str]] = None,
                    length: str = "medium", author: str = "") -> Dict[str, Any]:
        job = self.get(job_id)
        if job.status != "done":
            raise ResearchError("Finish the research first.")
        style = style if style in STYLES and style != "bibtex" else "apa"
        chosen = [s for s in (sections or PAPER_SECTIONS) if str(s).strip()][:12] or PAPER_SECTIONS
        words = {"short": 1200, "medium": 2500, "long": 5000}.get(length, 2500)
        in_text = "(Author, Year) author-year citations" if style in ("apa", "harvard", "chicago") else (
            "(Author page) MLA citations" if style == "mla" else "numbered [n] citations")
        prompt = (
            f"Write an academic paper from this research.\nQuestion: {job.question}\n"
            f"Title: {title or '(choose a precise title)'}\nSections, in order: {', '.join(chosen)}\n"
            f"Length: about {words} words. Citation style: {style.upper()} using {in_text}.\n\n"
            f"Research report:\n{job.report[:12000]}\n\nSources (use these numbers to know who said what):\n"
            f"{self._source_block(job.sources, 700)}\n\n"
            "Reply in Markdown: '# Title' first, then '## Section' headings in the order given. Formal academic register, "
            "claims only from the sources, no invented data or results — if the Methods/Results are a literature review, say so. "
            "Do not write the references list; it is added for you. For author-year styles, cite as (Lastname, Year) using the "
            "sources' authors and years; for numbered styles use [n]."
        )
        body = _strip_thinking(self._model(job, prompt, system="You write rigorous academic papers.", max_tokens=min(9000, words * 3)))
        cited_numbers = {int(n) for n in re.findall(r"\[(\d{1,3})\]", body)}
        cited = [s for s in job.sources if s["n"] in cited_numbers or re.search(
            rf"\(({re.escape(_split_name((s.get('authors') or [''])[0])[0])})[^)]*{s.get('year') or '§'}", body)]
        references = cited or [s for s in job.sources if s.get("read")]
        heading = "## References" if style in ("apa", "harvard", "ieee") else "## Works Cited" if style == "mla" else "## Bibliography"
        markdown = body.rstrip() + f"\n\n{heading}\n" + bibliography(references, style)
        job.paper = {"markdown": markdown, "style": style, "sections": chosen, "title": _title_of(markdown) or title,
                     "words": len(re.findall(r"\w+", body)), "references": [s["n"] for s in references], "created_at": time.time(),
                     "author": author[:120]}
        self._save(job)
        self._publish(job)
        return job.paper

    def export(self, job_id: str, fmt: str = "md", style: str = "apa", what: str = "report") -> Dict[str, str]:
        job = self.get(job_id)
        text = job.paper.get("markdown", "") if what == "paper" and job.paper else job.report
        if not text:
            raise ResearchError("Nothing to export yet.")
        stem = re.sub(r"[^a-z0-9]+", "-", (job.paper.get("title") if what == "paper" and job.paper else job.question).lower()).strip("-")[:60] or "research"
        if fmt == "md":
            return {"filename": f"{stem}.md", "mime": "text/markdown", "content": text}
        if fmt == "bib":
            return {"filename": f"{stem}.bib", "mime": "application/x-bibtex", "content": bibliography(job.sources, "bibtex")}
        if fmt == "tex":
            return {"filename": f"{stem}.tex", "mime": "application/x-tex", "content": markdown_to_latex(text, job.sources)}
        if fmt == "html":
            return {"filename": f"{stem}.html", "mime": "text/html", "content": markdown_to_html(text, job.question)}
        if fmt == "citations":
            return {"filename": f"{stem}-{style}.txt", "mime": "text/plain", "content": bibliography(job.sources, style)}
        raise ResearchError("Export as md, bib, tex, html or citations.")

    def teach(self, job_id: str) -> Dict[str, Any]:
        """Put what the research found into Nyx's memory and its learning set, so Nyx grows from it."""
        job = self.get(job_id)
        if job.status != "done" or not job.report:
            raise ResearchError("Finish the research first.")
        facts = 0
        try:
            import super_brain

            by_n = {s["n"]: s for s in job.sources}
            super_brain.BRAIN.ingest(f"Research: {job.question}\n{job.summary}", source="research", kind="finding", ref=job.job_id)
            facts += 1
            for note in job.notes[:40] or [{"claim": sentence, "sources": []} for sentence in re.split(r"(?<=[.!?])\s+", job.summary)[:8]]:
                where = "; ".join(by_n[n]["title"][:80] for n in note.get("sources", []) if n in by_n)
                super_brain.BRAIN.ingest(f"{note['claim']}" + (f" (sources: {where})" if where else ""), source="research", kind="finding",
                                         ref=job.job_id)
                facts += 1
        except Exception as error:  # noqa: BLE001
            _LOG.warning("research teach (brain) failed: %s", error)
        examples = 0
        try:
            import nyx_core

            core = getattr(nyx_core, "CORE", None) or getattr(nyx_core, "NYX_CORE", None)
            if core is not None and hasattr(core, "_append_distill"):
                core._append_distill({"ts": time.time(), "turn_id": f"research-{job.job_id}", "prompt": job.question[:4000],
                                      "answer": re.sub(r"\n## References[\s\S]*$", "", job.report)[:8000], "source": "research",
                                      "rating": 1})
                examples += 1
        except Exception as error:  # noqa: BLE001
            _LOG.warning("research teach (core) failed: %s", error)
        job.taught = {"facts": facts, "examples": examples, "at": time.time()}
        self._save(job)
        self._publish(job)
        return job.taught


def _title_of(markdown: str) -> str:
    match = re.search(r"^#\s+(.+)$", markdown, re.M)
    return match.group(1).strip() if match else ""


def _relevant(text: str, hint: str, limit: int) -> str:
    """The part of a long page most related to what the search snippet said."""
    text = re.sub(r"\s+", " ", text or "")
    if len(text) <= limit:
        return text
    words = {w for w in re.findall(r"[a-z]{4,}", (hint or "").lower())}
    if not words:
        return text[:limit]
    best, best_score = 0, -1
    for start in range(0, max(1, len(text) - limit), max(500, limit // 3)):
        window = text[start:start + limit].lower()
        score = sum(window.count(w) for w in words)
        if score > best_score:
            best, best_score = start, score
    return text[best:best + limit]


def markdown_to_html(markdown: str, title: str = "") -> str:
    lines, out, in_list = markdown.splitlines(), [], False
    for line in lines:
        escaped = html.escape(line)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"\*(.+?)\*", r"<em>\1</em>", escaped)
        heading = re.match(r"^(#{1,4})\s+(.*)$", escaped)
        item = re.match(r"^\s*[-*]\s+(.*)$", escaped)
        if item:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{item.group(1)}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{heading.group(2)}</h{level}>")
        elif escaped.strip():
            out.append(f"<p>{escaped}</p>")
    if in_list:
        out.append("</ul>")
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>{html.escape(title[:120])}</title>"
            "<style>body{font:17px/1.65 Georgia,serif;max-width:760px;margin:40px auto;padding:0 16px;color:#1c1c1e}"
            "h1,h2,h3{font-family:-apple-system,Segoe UI,sans-serif;line-height:1.25}</style></head><body>"
            + "\n".join(out) + "</body></html>")


def _tex_escape(text: str) -> str:
    return re.sub(r"([&%$#_{}~^\\])", lambda m: {"\\": r"\textbackslash{}", "~": r"\textasciitilde{}", "^": r"\^{}"}.get(m.group(1), "\\" + m.group(1)), text)


def markdown_to_latex(markdown: str, sources: List[Dict[str, Any]]) -> str:
    keys = {s["n"]: bibtex_key(s) for s in sources}
    body, title, in_list = [], "Research", False
    for line in markdown.splitlines():
        if re.match(r"^##\s+(References|Works Cited|Bibliography)\s*$", line):
            break
        heading = re.match(r"^(#{1,4})\s+(.*)$", line)
        item = re.match(r"^\s*[-*]\s+(.*)$", line)
        text = _tex_escape(heading.group(2) if heading else item.group(1) if item else line)
        text = re.sub(r"\\\[(\d{1,3})\\\]|\[(\d{1,3})\]", lambda m: f"\\cite{{{keys.get(int(m.group(1) or m.group(2)), 'ref')}}}", text)
        text = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", text)
        text = re.sub(r"\*(.+?)\*", r"\\emph{\1}", text)
        if item:
            if not in_list:
                body.append("\\begin{itemize}")
                in_list = True
            body.append(f"  \\item {text}")
            continue
        if in_list:
            body.append("\\end{itemize}")
            in_list = False
        if heading:
            level = len(heading.group(1))
            if level == 1:
                title = text
            else:
                body.append(("\\section{" if level == 2 else "\\subsection{") + text + "}")
        elif text.strip():
            body.append(text + "\n")
    if in_list:
        body.append("\\end{itemize}")
    return ("\\documentclass[11pt]{article}\n\\usepackage[utf8]{inputenc}\n\\usepackage{hyperref}\n"
            f"\\title{{{title}}}\n\\date{{\\today}}\n\\begin{{document}}\n\\maketitle\n\n" + "\n".join(body)
            + "\n\n\\bibliographystyle{plain}\n\\bibliography{references}\n\\end{document}\n")


def _settings_path() -> Path:
    return data_path("research/settings.json")


def settings() -> Dict[str, Any]:
    try:
        data = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"auto_teach": bool(data.get("auto_teach", True)), "style": data.get("style") if data.get("style") in STYLES else "apa"}


def save_settings(**changes: Any) -> Dict[str, Any]:
    current = settings()
    if "auto_teach" in changes:
        current["auto_teach"] = bool(changes["auto_teach"])
    if changes.get("style") in STYLES:
        current["style"] = changes["style"]
    _settings_path().parent.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(current), encoding="utf-8")
    return current


def _auto_teach() -> bool:
    return settings()["auto_teach"]


RESEARCH = ResearchJobs()


# ---------------------------------------------------------------------------
# Chat tools
# ---------------------------------------------------------------------------


def tool_research(question: str, mode: str = "standard") -> str:
    try:
        job = RESEARCH.start(question, mode=mode if mode in MODES else "standard")
    except ResearchError as error:
        return f"Error: {error}"
    return (f"Started {job['mode']} research ({job['job_id']}) on: {job['question'][:160]}. It runs in the background; the "
            "Research tab shows its progress, sources and the cited report. Tell the owner it's running and where to watch it.")


def tool_research_status(job_id: str = "") -> str:
    jobs = RESEARCH.list()
    if not jobs:
        return "No research yet."
    target = next((j for j in jobs if j["job_id"] == job_id), jobs[0]) if job_id else jobs[0]
    job = RESEARCH.get(target["job_id"])
    if job.status == "done":
        return f"Research {job.job_id} is done ({len(job.sources)} sources). Report:\n{job.report[:6000]}"
    return f"Research {job.job_id} is {job.status}: {job.step} ({int(job.progress * 100)}%)."


def tool_search_papers(query: str, limit: int = 6) -> str:
    papers = search_papers(query, max(1, min(int(limit or 6), 12)))
    if not papers:
        return f"No papers found for {query!r}."
    lines = []
    for i, p in enumerate(papers, 1):
        lines.append(f"[{i}] {p['title']} — {', '.join(p['authors'][:3])}{' et al.' if len(p['authors']) > 3 else ''} "
                     f"({p.get('year') or 'n.d.'}, {p.get('venue') or p.get('found_by')}; cited {p.get('citations') if p.get('citations') is not None else '?'}×) "
                     f"{p['url']}\n    {p.get('abstract', '')[:300]}")
    return "Papers (cite them by their links):\n" + "\n".join(lines)


def tool_cite(doi_or_title: str, style: str = "apa") -> str:
    text = (doi_or_title or "").strip()
    try:
        source = crossref(text) if re.search(r"10\.\d{4,9}/", text) else (search_papers(text, 1) or [None])[0]
    except ResearchError as error:
        return f"Error: {error}"
    if not source:
        return f"Couldn't find {text!r}."
    return format_citation(source, style if style in STYLES else "apa")


def register_research_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(name="research", description="Start a background research job with real, cited sources (web + scholarly papers). "
                      "mode: standard (about a minute) or deep (plans sub-questions, reads many sources, several minutes).",
                      parameters=[ToolParam("question", "string", "The research question"),
                                  ToolParam("mode", "string", "standard or deep", required=False, enum_values=["standard", "deep"])],
                      handler=tool_research, category="web", label=lambda a: f"Researching: {str(a.get('question', ''))[:60]}")
    registry.register(name="research_status", description="Progress of a research job, or its cited report when done.",
                      parameters=[ToolParam("job_id", "string", "Research id (latest when empty)", required=False)],
                      handler=tool_research_status, category="web", label="Checking the research")
    registry.register(name="search_papers", description="Search scholarly papers (OpenAlex, arXiv): titles, authors, year, venue, "
                      "citation counts, abstracts and links.", parameters=[ToolParam("query", "string", "What to find"),
                                                                             ToolParam("limit", "integer", "How many (≤12)", required=False)],
                      handler=tool_search_papers, category="web", label=lambda a: f"Searching papers: {str(a.get('query', ''))[:60]}")
    registry.register(name="cite", description="Format a citation for a DOI or paper title in apa, mla, chicago, ieee, harvard or bibtex.",
                      parameters=[ToolParam("doi_or_title", "string", "A DOI (10.xxxx/…) or a paper title"),
                                  ToolParam("style", "string", "Citation style", required=False, enum_values=list(STYLES))],
                      handler=tool_cite, category="web", label="Formatting a citation")
