"""HTTP routes for the Research tab (Request L).

Research is an ordinary signed-in action (it reads the public web and scholarly indexes and writes into this install's
research folder), so every route uses the chat gate.
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from server_auth import RequireChat

router = APIRouter()


def _call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    import research_engine

    try:
        return fn(*args, **kwargs)
    except research_engine.ResearchError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


class StartBody(BaseModel):
    question: str
    mode: str = "standard"
    web: bool = True
    papers: bool = True
    max_sources: int = Field(default=0, ge=0, le=60)


class PaperBody(BaseModel):
    title: str = ""
    style: str = "apa"
    sections: List[str] = Field(default_factory=list)
    length: str = "medium"
    author: str = ""


class SettingsBody(BaseModel):
    auto_teach: bool | None = None
    style: str | None = None


@router.get("/api/research")
def research_list(_user=RequireChat) -> Dict[str, Any]:
    import research_engine

    return {"jobs": research_engine.RESEARCH.list(), "settings": research_engine.settings(),
            "styles": list(research_engine.STYLES), "sections": research_engine.PAPER_SECTIONS}


@router.post("/api/research")
def research_start(body: StartBody, _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    return {"job": _call(research_engine.RESEARCH.start, body.question, mode=body.mode, include_web=body.web,
                         include_papers=body.papers, max_sources=body.max_sources)}


@router.put("/api/research/settings")
def research_settings(body: SettingsBody, _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    return research_engine.save_settings(**{k: v for k, v in body.model_dump().items() if v is not None})


@router.get("/api/research/papers")
def research_papers(q: str, limit: int = 10, _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    if len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Type what to search for.")
    text = q.strip()[:300]
    # A question typed here is searched by its topic words — the indexes match every word, so a sentence finds nothing.
    query = research_engine.scholarly_query(text) if research_engine.looks_like_question(text) else text
    papers = research_engine.search_papers(query, max(1, min(limit, 25)))
    # Every style comes with the result, so switching style or pressing Copy never searches again.
    for paper in papers:
        paper["cite"] = {style: research_engine.format_citation(paper, style) for style in research_engine.STYLES}
    return {"papers": papers, "query": query}


@router.get("/api/research/cite")
def research_cite(doi: str = "", title: str = "", style: str = "apa", _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    if doi:
        source = _call(research_engine.crossref, doi)
    else:
        found = research_engine.search_papers(title, 1) if title.strip() else []
        if not found:
            raise HTTPException(status_code=404, detail="Nothing found to cite.")
        source = found[0]
    return {"source": source, "citation": research_engine.format_citation(source, style),
            "all": {s: research_engine.format_citation(source, s) for s in research_engine.STYLES}}


@router.get("/api/research/{job_id}")
def research_get(job_id: str, _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    return {"job": _call(research_engine.RESEARCH.get, job_id).view()}


@router.get("/api/research/{job_id}/citations")
def research_citations(job_id: str, style: str = "apa", _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    return _call(research_engine.RESEARCH.citations, job_id, style)


@router.post("/api/research/{job_id}/stop")
def research_stop(job_id: str, _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    return {"job": _call(research_engine.RESEARCH.stop, job_id)}


@router.delete("/api/research/{job_id}")
def research_delete(job_id: str, _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    _call(research_engine.RESEARCH.delete, job_id)
    return {"deleted": job_id}


@router.post("/api/research/{job_id}/paper")
def research_paper(job_id: str, body: PaperBody, _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    return {"paper": _call(research_engine.RESEARCH.draft_paper, job_id, title=body.title, style=body.style,
                           sections=body.sections or None, length=body.length, author=body.author)}


@router.post("/api/research/{job_id}/teach")
def research_teach(job_id: str, _user=RequireChat) -> Dict[str, Any]:
    import research_engine

    return {"taught": _call(research_engine.RESEARCH.teach, job_id)}


@router.get("/api/research/{job_id}/export")
def research_export(job_id: str, format: str = "md", style: str = "apa", what: str = "report", _user=RequireChat) -> Response:
    import research_engine

    result = _call(research_engine.RESEARCH.export, job_id, format, style, what)
    return Response(content=result["content"], media_type=f"{result['mime']}; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename=\"{result['filename']}\""})
