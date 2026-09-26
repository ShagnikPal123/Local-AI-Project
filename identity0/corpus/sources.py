"""Fetchers for the Safe-mix sources. Polite (a real User-Agent, ``maxlag``, pauses) and capped.

Every fetcher takes ``get`` so tests run offline; in a job it is a ``requests`` session. Nothing here
decides licensing — ``CorpusStore.add`` refuses anything ``policy.source_license`` does not allow.

Articles are fetched with a few workers (``workers``), because the corpus has to be big enough to
train on: one request at a time meant a thousand articles an hour. ``maxlag=5`` tells Wikipedia to
refuse us first when its servers are behind, which is the deal for reading it at this rate.
"""

from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

USER_AGENT = "NyxIchos-Identity0/0.1 (local assistant; https://github.com/ShagnikPal123/Local-AI-Project)"
WIKI_API = "https://en.wikipedia.org/w/api.php"
GUTENDEX = "https://gutendex.com/books/"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
ARXIV = "https://export.arxiv.org/api/query"

Getter = Callable[..., Any]


_local = threading.local()


def _get(get: Optional[Getter]) -> Getter:
    if get is not None:
        return get
    import requests

    session = getattr(_local, "session", None)  # one session per thread: connections are not shared
    if session is None:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        _local.session = session
    return session.get


def clean_wiki(text: str) -> str:
    """Plain-text extracts still carry section markers and leftover formula markup."""
    text = re.sub(r"\n=+ *(See also|References|External links|Further reading|Notes|Bibliography|Sources)\b.*", "",
                  text or "", flags=re.S | re.I)
    text = re.sub(r"\n=+ *([^=\n]+?) *=+\n", r"\n\n\1\n", text)
    text = re.sub(r"\{\\displaystyle[^}]*\}", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def wikipedia_titles(list_page: str = "Wikipedia:Vital articles", limit: int = 1000, get: Optional[Getter] = None) -> List[str]:
    """Article titles linked from a list page (the Vital articles list is a well-rounded curriculum)."""
    fetch = _get(get)
    titles: List[str] = []
    params: Dict[str, Any] = {"action": "query", "format": "json", "prop": "links", "titles": list_page,
                              "plnamespace": 0, "pllimit": "max"}
    while len(titles) < limit:
        data = fetch(WIKI_API, params=params, timeout=30).json()
        for page in (data.get("query", {}).get("pages", {}) or {}).values():
            titles += [link["title"] for link in page.get("links", [])]
        if "continue" not in data:
            break
        params.update(data["continue"])
    return titles[:limit]


def category_titles(category: str, limit: int = 1000, *, seed: int = 7, pages: int = 120,
                    get: Optional[Getter] = None) -> List[str]:
    """A random sample of the articles in a category (read in full, then shuffled).

    Categories list members alphabetically, so taking the first N would teach the corpus everything
    about topics starting with "A" and nothing else.
    """
    import random

    fetch = _get(get)
    titles: List[str] = []
    params: Dict[str, Any] = {"action": "query", "format": "json", "list": "categorymembers",
                              "cmtitle": category, "cmnamespace": 0, "cmlimit": "max", "maxlag": 5}
    for _ in range(max(1, pages)):
        data = fetch(WIKI_API, params=params, timeout=30).json()
        titles += [m["title"] for m in data.get("query", {}).get("categorymembers", [])]
        if "continue" not in data:
            break
        params.update(data["continue"])
    random.Random(seed).shuffle(titles)
    return titles[:limit]


def featured_titles(limit: int = 1000, *, seed: int = 7, get: Optional[Getter] = None) -> List[str]:
    """A random sample of Wikipedia's Featured articles — its best-written, best-sourced pages."""
    return category_titles("Category:Featured articles", limit, seed=seed, pages=40, get=get)


def good_titles(limit: int = 20000, *, seed: int = 7, get: Optional[Getter] = None) -> List[str]:
    """Wikipedia's Good articles: about 40,000 pages that passed review — the bulk of a real corpus."""
    return category_titles("Category:Good articles", limit, seed=seed, pages=120, get=get)


def article_titles(limit: int, *, seed: int = 7, get: Optional[Getter] = None) -> List[str]:
    """The best Wikipedia has, in quality order: every Featured article first, then Good ones."""
    titles = featured_titles(limit, seed=seed, get=get)
    if len(titles) < limit:
        have = set(titles)
        titles += [t for t in good_titles(limit - len(titles) + 500, seed=seed, get=get) if t not in have]
    return titles[:limit]


def _article(title: str, get: Optional[Getter], pause: float) -> List[Dict[str, str]]:
    fetch = _get(get)
    out: List[Dict[str, str]] = []
    for attempt in range(3):
        try:
            data = fetch(WIKI_API, params={"action": "query", "format": "json", "prop": "extracts", "explaintext": 1,
                                           "redirects": 1, "maxlag": 5, "titles": title}, timeout=30).json()
        except Exception:  # noqa: BLE001 - one missing page is not a failed corpus
            time.sleep(1.0 + attempt)
            continue
        if isinstance(data, dict) and data.get("error", {}).get("code") == "maxlag":
            time.sleep(5.0 * (attempt + 1))  # Wikipedia is behind: back off, it asked us to
            continue
        for page in (data.get("query", {}).get("pages", {}) or {}).values():
            text = clean_wiki(page.get("extract", ""))
            if text:
                name = page.get("title", title)
                out.append({"title": name, "text": text,
                            "url": f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}"})
        break
    if pause:
        time.sleep(pause)
    return out


def wikipedia_articles(titles: Sequence[str], *, get: Optional[Getter] = None, pause: float = 0.15,
                       stop: Optional[Callable[[], bool]] = None, workers: int = 1) -> Iterator[Dict[str, str]]:
    """Full plain text of each article (the API gives one full extract per request).

    ``workers`` > 1 fetches several at a time — the difference between a thousand articles an hour and
    ten thousand. Results come back as they finish, so the caller still writes them one at a time.
    """
    titles = list(titles)
    if workers <= 1:
        for title in titles:
            if stop is not None and stop():
                return
            for item in _article(title, get, pause):
                yield item
        return
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kahuna-wiki") as pool:
        step = workers * 8
        for start in range(0, len(titles), step):
            if stop is not None and stop():
                return
            for items in pool.map(lambda t: _article(t, get, pause), titles[start:start + step]):
                for item in items:
                    yield item


def wikipedia_intros(titles: Sequence[str], *, get: Optional[Getter] = None, pause: float = 0.2) -> Iterator[Dict[str, str]]:
    """Lead sections, 20 per request (the API allows several extracts only for intros)."""
    fetch = _get(get)
    titles = list(titles)
    for start in range(0, len(titles), 20):
        batch = titles[start:start + 20]
        try:
            data = fetch(WIKI_API, params={"action": "query", "format": "json", "prop": "extracts", "explaintext": 1,
                                           "exintro": 1, "exlimit": 20, "redirects": 1, "titles": "|".join(batch)},
                         timeout=30).json()
        except Exception:  # noqa: BLE001
            continue
        for page in (data.get("query", {}).get("pages", {}) or {}).values():
            text = clean_wiki(page.get("extract", ""))
            if text:
                name = page.get("title", "")
                yield {"title": name, "text": text, "url": f"https://en.wikipedia.org/wiki/{name.replace(' ', '_')}"}
        time.sleep(pause)


_PG_START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I)
_PG_END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG", re.I)


def strip_gutenberg(text: str) -> str:
    start = _PG_START.search(text or "")
    end = _PG_END.search(text or "")
    body = text[start.end() if start else 0: end.start() if end else len(text)]
    return re.sub(r"\r\n?", "\n", body).strip()


#: Well-known public-domain books (Project Gutenberg ids), used when the gutendex catalogue is unreachable.
CLASSICS = [1342, 84, 11, 1661, 2701, 98, 74, 76, 345, 1232, 5200, 174, 1400, 43, 120, 219, 158, 768, 1260, 36, 35,
            55, 45, 514, 1727, 6130, 25344, 205, 996, 1497, 2554, 3207, 7370, 5827, 16328, 1952, 2542, 4300, 1184, 28054]


def gutenberg_books(limit: int = 20, *, get: Optional[Getter] = None, pause: float = 2.0,
                    max_chars: int = 1_200_000, stop: Optional[Callable[[], bool]] = None,
                    skip: Optional[Callable[[str], bool]] = None) -> Iterator[Dict[str, str]]:
    """Popular English public-domain books, header and licence footer removed.

    The popularity list comes from gutendex; when that service is down the built-in classics list is
    used and each book is read straight from gutenberg.org.
    """
    fetch = _get(get)
    try:
        listing = fetch(GUTENDEX, params={"languages": "en", "sort": "popular", "copyright": "false"}, timeout=12).json()
    except Exception:  # noqa: BLE001 - gutendex is a convenience, not a dependency
        listing = None
    if listing is None:
        found = 0
        for book_id in CLASSICS:
            if found >= limit or (stop is not None and stop()):
                return
            url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
            try:
                raw = fetch(url, timeout=60)
                raw.encoding = "utf-8"
                text = strip_gutenberg(raw.text)[:max_chars]
            except Exception:  # noqa: BLE001
                continue
            title = next((line.split(":", 1)[1].strip() for line in raw.text[:3000].splitlines()
                          if line.lower().startswith("title:")), f"Gutenberg #{book_id}")
            if len(text) > 2000:
                found += 1
                yield {"title": title, "text": text, "url": url}
            time.sleep(pause)
        return
    url: Optional[str] = GUTENDEX
    params: Optional[Dict[str, Any]] = None
    data = listing
    found = 0
    while url and found < limit:
        if data is None:
            try:
                data = fetch(url, params=params, timeout=30).json()
            except Exception:  # noqa: BLE001
                return
        params = None
        for book in data.get("results", []):
            if found >= limit or (stop is not None and stop()):
                return
            formats = book.get("formats", {})
            text_url = next((v for k, v in formats.items() if k.startswith("text/plain") and not v.endswith(".zip")), "")
            if not text_url or book.get("copyright"):
                continue
            if skip is not None and skip(text_url):
                found += 1  # already collected: it still counts towards the number asked for
                continue
            try:
                raw = fetch(text_url, timeout=60)
                raw.encoding = "utf-8"
                text = strip_gutenberg(raw.text)[:max_chars]
            except Exception:  # noqa: BLE001
                continue
            if len(text) > 2000:
                found += 1
                authors = ", ".join(a.get("name", "") for a in book.get("authors", []))
                yield {"title": f"{book.get('title', '')} — {authors}".strip(" —"), "text": text, "url": text_url}
            time.sleep(pause)
        url = data.get("next")
        data = None


FILM_QUERY = """
SELECT ?film ?title ?year ?directorLabel WHERE {
  ?film wdt:P31 wd:Q11424; wikibase:sitelinks ?links.
  FILTER(?links > %d)
  ?article schema:about ?film; schema:isPartOf <https://en.wikipedia.org/>; schema:name ?title.
  OPTIONAL { ?film wdt:P577 ?date. BIND(YEAR(?date) AS ?year) }
  OPTIONAL { ?film wdt:P57 ?director }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} LIMIT %d
"""


def films(limit: int = 300, *, min_sitelinks: int = 70, get: Optional[Getter] = None) -> Iterator[Dict[str, str]]:
    """Well-known films: Wikidata facts (CC0) and each film's Wikipedia lead (CC BY-SA)."""
    fetch = _get(get)
    data = fetch(WIKIDATA_SPARQL, params={"query": FILM_QUERY % (min_sitelinks, limit), "format": "json"},
                 headers={"Accept": "application/sparql-results+json"}, timeout=90).json()
    rows: Dict[str, Dict[str, Any]] = {}
    for row in data.get("results", {}).get("bindings", []):
        title = row.get("title", {}).get("value")
        if not title:
            continue
        entry = rows.setdefault(title, {"year": row.get("year", {}).get("value", ""), "directors": set()})
        if row.get("directorLabel"):
            entry["directors"].add(row["directorLabel"]["value"])
    for intro in wikipedia_intros(list(rows), get=get):
        facts = rows.get(intro["title"], {})
        who = ", ".join(sorted(facts.get("directors", []))) if facts else ""
        lead = f"{intro['title']} is a film" + (f" from {facts.get('year')}" if facts.get("year") else "") + \
               (f" directed by {who}." if who else ".")
        yield {"title": intro["title"], "text": f"{lead}\n\n{intro['text']}", "url": intro["url"]}


def arxiv_abstracts(query: str = "cat:cs.AI", limit: int = 100, *, get: Optional[Getter] = None) -> Iterator[Dict[str, str]]:
    fetch = _get(get)
    response = fetch(ARXIV, params={"search_query": query, "max_results": limit, "sortBy": "submittedDate"}, timeout=60)
    root = ET.fromstring(response.text)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("a:entry", ns):
        title = " ".join((entry.findtext("a:title", "", ns) or "").split())
        summary = " ".join((entry.findtext("a:summary", "", ns) or "").split())
        link = entry.findtext("a:id", "", ns) or ""
        if summary:
            yield {"title": title, "text": f"{title}\n\n{summary}", "url": link}


def owner_questions(limit: int = 400) -> List[str]:
    """What the owner has asked Nyx (their own words, PII-scrubbed) — prompts for the teacher, never its old answers.

    The assistant replies stored in chats came from Gemini, NVIDIA and others; many of those providers'
    terms forbid training on their outputs, so only the questions are used and a permitted teacher answers.
    """
    import json

    from identity0.policy import scrub_pii
    from paths import data_path

    try:
        data = json.loads(data_path("chats.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    questions: List[str] = []
    for chat in (data.get("chats") or {}).values():
        for message in chat.get("messages", []):
            text = str(message.get("content", "") or "")
            if message.get("role") == "user" and 12 <= len(text) <= 1500 and "[Attached:" not in text:
                questions.append(scrub_pii(text.strip()))
    seen, unique = set(), []
    for q in reversed(questions):
        key = q.lower()[:120]
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return unique[:limit]
