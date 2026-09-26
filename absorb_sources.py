"""Where Data Absorption finds documents, and how it reads them without filling the disk (Request R2–R4).

The owner: "it pull up the document (papers, GitHub's, anything and everything for high data collection keep in mind it
shouldn't take too much storage on a computer)".

* **Finding** — scholarly papers (OpenAlex + arXiv through ``research_engine.search_papers``), GitHub repositories
  (search API), Wikipedia articles and the web (``web_access.search_results``). Each finder returns *candidates*:
  a title, a link and whatever text came with the search (a paper's abstract), never a download.
* **Reading** — one candidate, link or upload becomes plain text. Downloads are streamed with a byte cap (6 MB) and
  only the extracted text is kept, in memory, for as long as the reader needs it; the engine stores the lines it
  showed and the facts it kept, not the document.
* **Safety** — pages found on the web can link anywhere, including this machine. Every fetch is http(s) to a public
  address only, re-checked after each redirect, so a page cannot point the reader at ``127.0.0.1:8000/api/...``.
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

MAX_BYTES = 6 * 1024 * 1024
MAX_TEXT = 200_000
TIMEOUT = 20
_UA = {"User-Agent": "NyxIchos-DataAbsorption/1.0 (local assistant; learning from public sources)"}

HttpGet = Callable[..., Any]


class SourceError(RuntimeError):
    """A document could not be found or read. The message is fit to show in the queue."""


# ---------------------------------------------------------------------------
# Fetching safely
# ---------------------------------------------------------------------------


def _public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False
        if not address.is_global:
            return False
    return bool(infos)


def check_url(url: str) -> str:
    clean = (url or "").strip()
    parsed = urllib.parse.urlparse(clean)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SourceError("Only http:// and https:// links can be read.")
    if not _public_host(parsed.hostname):
        raise SourceError(f"{parsed.hostname} is not a public address, so it was not opened.")
    return clean


def _web_allowed() -> None:
    try:
        import web_access

        web_access._ensure_access()  # the owner's "web access off" switch applies here too
    except RuntimeError as error:  # "Web access is disabled…" / "Internet is currently unreachable."
        raise SourceError(str(error)) from error


def fetch(url: str, *, get: Optional[HttpGet] = None, max_bytes: int = MAX_BYTES, check: bool = True,
          headers: Optional[Dict[str, str]] = None) -> Tuple[bytes, str, str]:
    """``(body, content_type, final_url)`` — streamed, capped, redirects followed by hand and re-checked."""
    http = get or requests.get
    current = url
    for _hop in range(5):
        if check:
            current = check_url(current)
        response = http(current, headers={**_UA, **(headers or {})}, timeout=TIMEOUT, stream=True, allow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
            current = urllib.parse.urljoin(current, response.headers["location"])
            continue
        if response.status_code >= 400:
            raise SourceError(f"{urllib.parse.urlparse(current).hostname} answered {response.status_code}.")
        declared = int(response.headers.get("content-length") or 0)
        if declared > max_bytes:
            raise SourceError(f"Too big to read ({declared // 1_048_576} MB).")
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > max_bytes:
                break  # keep what fits: the start of a long document is still worth reading
        return bytes(body[:max_bytes]), str(response.headers.get("content-type") or "").lower(), current
    raise SourceError("Too many redirects.")


def _get_json(url: str, *, get: Optional[HttpGet] = None, params: Optional[Dict[str, Any]] = None,
              headers: Optional[Dict[str, str]] = None) -> Any:
    http = get or requests.get
    response = http(url, params=params or {}, headers={**_UA, **(headers or {})}, timeout=TIMEOUT)
    if response.status_code != 200:
        raise SourceError(f"{urllib.parse.urlparse(url).hostname} answered {response.status_code}.")
    return response.json()


def html_to_text(markup: str) -> Tuple[str, str]:
    """``(title, text)`` from a web page: scripts, navigation and footers dropped, headings kept as lines."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", markup or "", re.I | re.S)
    title = html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip() if title_match else ""
    body = re.sub(r"<(script|style|noscript|svg|nav|footer|header|aside|form)\b[^>]*>.*?</\1>", " ", markup or "", flags=re.I | re.S)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    body = re.sub(r"</(p|div|li|h[1-6]|tr|section|article|blockquote|pre)>|<br\s*/?>", "\n", body, flags=re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = html.unescape(body)
    body = re.sub(r"[ \t ]+", " ", body)
    body = re.sub(r"\n\s*\n+", "\n\n", body)
    return title[:300], body.strip()[:MAX_TEXT]


def text_from(body: bytes, content_type: str, url: str = "", name: str = "") -> Tuple[str, str]:
    """Plain text out of whatever came back: PDF, Office files, HTML, Markdown or text."""
    import uploads

    lowered = (name or urllib.parse.urlparse(url).path or "").lower()
    if "pdf" in content_type or lowered.endswith(".pdf") or body[:5] == b"%PDF-":
        return "", uploads.extract_pdf_text(body, max_pages=40)[:MAX_TEXT]
    if lowered.endswith((".docx", ".xlsx", ".pptx")):
        return "", uploads.extract_document_text(body, lowered)[:MAX_TEXT]
    text = uploads._decode_text(body)
    if "html" in content_type or re.search(r"<html|<body|<p[\s>]", text[:2000], re.I):
        return html_to_text(text)
    return "", text[:MAX_TEXT]


# ---------------------------------------------------------------------------
# Finding
# ---------------------------------------------------------------------------


def _candidate(kind: str, title: str, url: str, source: str, text: str = "", **extra: Any) -> Dict[str, Any]:
    return {"kind": kind, "title": re.sub(r"\s+", " ", title or "").strip()[:240] or url, "url": url, "source": source,
            "text": (text or "")[:MAX_TEXT], **extra}


def find_papers(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    import research_engine

    found = []
    for paper in research_engine.search_papers(query, limit):
        abstract = paper.get("abstract") or ""
        if len(abstract) < 200:
            continue  # nothing to read without the PDF; plenty of other papers have abstracts
        who = ", ".join((paper.get("authors") or [])[:3])
        found.append(_candidate("paper", paper.get("title", ""), paper.get("url") or paper.get("pdf_url") or "",
                                paper.get("found_by") or "Papers", abstract, year=paper.get("year"), authors=who,
                                venue=paper.get("venue", ""), citations=paper.get("citations"), pdf_url=paper.get("pdf_url", "")))
    return found


def find_github(query: str, limit: int = 3, *, get: Optional[HttpGet] = None) -> List[Dict[str, Any]]:
    data = _get_json("https://api.github.com/search/repositories", get=get,
                     params={"q": f"{query} in:name,description,readme", "sort": "stars", "per_page": max(1, min(limit, 10))},
                     headers={"Accept": "application/vnd.github+json"})
    found = []
    for repo in (data.get("items") or [])[:limit]:
        found.append(_candidate("github", repo.get("full_name", ""), repo.get("html_url", ""), "GitHub",
                                repo.get("description") or "", stars=repo.get("stargazers_count"),
                                full_name=repo.get("full_name", ""), branch=repo.get("default_branch") or "HEAD"))
    return found


def find_wikipedia(query: str, limit: int = 2, *, get: Optional[HttpGet] = None) -> List[Dict[str, Any]]:
    data = _get_json("https://en.wikipedia.org/w/api.php", get=get,
                     params={"action": "query", "list": "search", "srsearch": query, "srlimit": max(1, min(limit, 10)),
                             "format": "json"})
    return [_candidate("wiki", item.get("title", ""), "https://en.wikipedia.org/wiki/" + urllib.parse.quote(item.get("title", "").replace(" ", "_")),
                       "Wikipedia", re.sub(r"<[^>]+>", "", html.unescape(item.get("snippet", ""))))
            for item in (data.get("query", {}).get("search") or [])[:limit]]


def find_web(query: str, limit: int = 3) -> List[Dict[str, Any]]:
    import web_access

    results = web_access.search_results(query, freshness="any")
    return [_candidate("web", item.get("title", ""), item.get("url", ""), item.get("domain") or "Web")
            for item in results[:limit] if str(item.get("url", "")).startswith(("http://", "https://"))]


FINDERS: Dict[str, Callable[..., List[Dict[str, Any]]]] = {
    "papers": find_papers, "github": find_github, "wiki": find_wikipedia, "web": find_web,
}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _read_github(candidate: Dict[str, Any], get: Optional[HttpGet] = None) -> Dict[str, Any]:
    full = candidate.get("full_name") or "/".join(urllib.parse.urlparse(candidate["url"]).path.strip("/").split("/")[:2])
    branch = candidate.get("branch") or "HEAD"
    text = ""
    for name in ("README.md", "readme.md", "README.rst", "README"):
        try:
            body, _kind, _final = fetch(f"https://raw.githubusercontent.com/{full}/{branch}/{name}", get=get, max_bytes=600_000)
            text = body.decode("utf-8", errors="replace")
            if text.strip():
                break
        except SourceError:
            continue
    if not text:
        raise SourceError(f"{full} has no README to read.")
    description = candidate.get("text") or ""
    return {**candidate, "text": f"{description}\n\n{text}"[:MAX_TEXT], "title": candidate.get("title") or full}


def _read_wikipedia(candidate: Dict[str, Any], get: Optional[HttpGet] = None) -> Dict[str, Any]:
    title = urllib.parse.unquote(candidate["url"].rsplit("/wiki/", 1)[-1]).replace("_", " ")
    data = _get_json("https://en.wikipedia.org/w/api.php", get=get,
                     params={"action": "query", "prop": "extracts", "explaintext": 1, "titles": title, "format": "json",
                             "redirects": 1})
    pages = (data.get("query", {}).get("pages") or {}).values()
    text = next((p.get("extract", "") for p in pages if p.get("extract")), "")
    if not text:
        raise SourceError(f"Wikipedia has no article text for {title}.")
    # The tail sections of an article are lists of links, not prose worth reading or learning from.
    cut = re.search(r"^==\s*(See also|References|External links|Further reading|Notes|Bibliography|Sources)\s*==\s*$", text, re.I | re.M)
    return {**candidate, "title": title, "text": (text[:cut.start()] if cut else text)[:MAX_TEXT]}


def read(candidate: Dict[str, Any], *, get: Optional[HttpGet] = None) -> Dict[str, Any]:
    """Fill in ``text`` (and a better ``title``) for a candidate. Raises SourceError with a short reason."""
    kind = candidate.get("kind")
    if kind == "upload":
        return candidate  # read_upload already extracted it
    if kind == "paper" and len(candidate.get("text") or "") >= 200:
        return candidate
    _web_allowed()
    if kind == "github" or re.match(r"^https?://github\.com/[^/]+/[^/]+/?$", candidate.get("url", "")):
        return _read_github({**candidate, "kind": "github", "source": "GitHub"}, get)
    if kind == "wiki" or "wikipedia.org/wiki/" in candidate.get("url", ""):
        return _read_wikipedia({**candidate, "kind": "wiki", "source": "Wikipedia"}, get)
    url = candidate.get("url") or ""
    if re.match(r"^https?://arxiv\.org/abs/", url):
        url = url.replace("/abs/", "/pdf/")
    body, kind_header, final = fetch(url, get=get)
    title, text = text_from(body, kind_header, final)
    if len(text.strip()) < 80:
        raise SourceError("No readable text on that page.")
    return {**candidate, "url": candidate.get("url") or final, "title": candidate.get("title") if candidate.get("title") not in ("", url) else (title or final),
            "text": text}


def link_candidate(url: str) -> Dict[str, Any]:
    clean = (url or "").strip()
    host = urllib.parse.urlparse(clean).hostname or ""
    kind = "github" if host.endswith("github.com") else "wiki" if "wikipedia.org" in host else \
        "paper" if host.endswith(("arxiv.org", "doi.org", "openalex.org")) else "link"
    source = {"github": "GitHub", "wiki": "Wikipedia", "paper": host.replace("www.", "")}.get(kind, host.replace("www.", "") or "Link")
    return _candidate(kind, clean, clean, source)


def read_upload(upload_id: str) -> Dict[str, Any]:
    """An uploaded file as a document. The file stays in uploads; nothing is copied."""
    import uploads

    record = uploads.get_upload(upload_id)
    if record is None:
        raise SourceError("That upload is gone.")
    from pathlib import Path

    data = Path(record["path"]).read_bytes()
    kind = uploads.kind_for(record["name"], record.get("mime", ""))
    if kind == "image":
        text = ""
        try:
            from model_roles import MODEL_ROLES

            run = MODEL_ROLES.run("image_check", "Transcribe every piece of text in this image, then describe what it shows "
                                                 "(charts: the numbers and trends; diagrams: the parts and links).",
                                  images=[(data, record.get("mime") or "image/png")], max_tokens=1200)
            text = run.text
        except Exception as error:  # noqa: BLE001
            raise SourceError(f"Could not read the picture: {str(error)[:120]}") from error
    else:
        _title, text = text_from(data, record.get("mime", ""), name=record["name"])
    if len(text.strip()) < 40:
        raise SourceError(f"No readable text in {record['name']}.")
    return _candidate("upload", record["name"], "", "Your file", text, upload_id=upload_id, size=len(data))


def dump(candidate: Dict[str, Any]) -> str:
    """For logs: a candidate without its text."""
    return json.dumps({k: v for k, v in candidate.items() if k != "text"}, ensure_ascii=False)[:400]
