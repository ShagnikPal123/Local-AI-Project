"""Permission-aware web access and multi-source verification engine for Nyx Ichos."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
import re
from urllib.parse import parse_qs, quote, unquote, urlparse
from typing import Any, Dict, List, Optional, Tuple

import requests

from config import SETTINGS
from connectivity import is_online

_web_enabled: ContextVar[bool] = ContextVar("web_enabled", default=True)
_TIMEOUT = 10
_MAX_RESULTS = 5
_MAX_COMBINED_RESULTS = 12
_MAX_PAGE_CHARS = 4000
_SEARCH_ENGINES = {"duckgo", "google", "bing", "all"}
_DEFAULT_FRESHNESS = "month"
_FRESHNESS_DAYS = {"day": 1, "week": 7, "month": 31, "any": None}
_SEARCH_CACHE: Dict[Tuple[str, str, str], Tuple[float, List[Dict[str, str]]]] = {}
_CACHE_TTL_SECONDS = 120.0


def set_enabled(enabled: bool) -> None:
    """Set whether web tools may make network requests in this context."""
    _web_enabled.set(enabled)


def is_enabled() -> bool:
    """Return the current web permission."""
    return _web_enabled.get()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    for pattern in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d", "%B %d, %Y", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(value.strip(), pattern)
            return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _age_metadata(timestamp: datetime | None, max_age_days: int | None = 31) -> dict[str, str | bool]:
    checked = _now_utc()
    if timestamp is None:
        return {"published_at": "unknown", "age": "unknown", "is_stale": True}
    age_seconds = max(0, int((checked - timestamp).total_seconds()))
    age_days = age_seconds // 86400
    age = f"{age_days}d" if age_days else f"{max(1, age_seconds // 3600)}h"
    stale = max_age_days is not None and age_seconds > max_age_days * 86400
    return {"published_at": timestamp.isoformat(), "age": age, "is_stale": stale}


def _extract_page_timestamp(html: str, headers: dict[str, str]) -> datetime | None:
    for key in ("Last-Modified", "Date"):
        timestamp = _parse_timestamp(headers.get(key))
        if timestamp:
            return timestamp
    patterns = [
        r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|datePublished|date|last-modified)["\'][^>]+content=["\']([^"\']+)',
        r'"(?:datePublished|dateModified)"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I)
        if match:
            timestamp = _parse_timestamp(match.group(1))
            if timestamp:
                return timestamp
    return None


def _ensure_access() -> None:
    if not is_enabled():
        raise RuntimeError("Web access is disabled. Use /web on before searching.")
    if not is_online():
        raise RuntimeError("Internet is currently unreachable.")


def _search_url(query: str, engine: str, freshness: str = "month") -> str:
    freshness = freshness if freshness in _FRESHNESS_DAYS else _DEFAULT_FRESHNESS
    if engine == "google":
        if not (SETTINGS.google_api_key and SETTINGS.google_cse_id):
            raise RuntimeError("Google search requires GOOGLE_API_KEY and GOOGLE_CSE_ID.")
        url = (
            "https://www.googleapis.com/customsearch/v1?key="
            + quote(SETTINGS.google_api_key)
            + "&cx="
            + quote(SETTINGS.google_cse_id)
            + "&q="
            + quote(query)
        )
        if freshness == "day":
            url += "&dateRestrict=d1"
        elif freshness == "week":
            url += "&dateRestrict=d7"
        elif freshness == "month":
            url += "&dateRestrict=d30"
        return url
    if engine == "bing":
        if not SETTINGS.bing_api_key:
            raise RuntimeError("Bing search requires BING_API_KEY.")
        url = "https://api.bing.microsoft.com/v7.0/search?q=" + quote(query)
        if freshness == "day":
            url += "&freshness=Day"
        elif freshness == "week":
            url += "&freshness=Week"
        elif freshness == "month":
            url += "&freshness=Month"
        return url
    suffix = {"day": "d", "week": "w", "month": "m", "any": ""}.get(freshness, "")
    return "https://html.duckduckgo.com/html/?q=" + quote(query) + (f"&df={suffix}" if suffix else "")


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _real_url(href: str) -> str:
    """The page a result link points at.

    DuckDuckGo's HTML endpoint hands back its own redirector —
    ``//duckduckgo.com/l/?uddg=<the real url>&rut=…`` — with no scheme. Left as
    they were, every result had the same domain (so the diversity and duplicate
    filters saw one site), the link shown to the user was a tracker, and
    fetching the page failed outright because ``//duckduckgo.com/…`` has no
    scheme for requests to use.
    """
    href = (href or "").strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target.startswith("http"):
            return unquote(target)
    return href


def _deduplicate_results(results: list[dict[str, str]], limit: int = _MAX_COMBINED_RESULTS) -> list[dict[str, str]]:
    seen_urls: set[str] = set()
    selected: list[dict[str, str]] = []
    for item in results:
        url = item.get("url", "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        selected.append({**item, "domain": _domain(url)})
        if len(selected) >= limit:
            break
    return selected


def _diversify_results(results: list[dict[str, str]], limit: int = _MAX_COMBINED_RESULTS) -> list[dict[str, str]]:
    """Prefer independent domains before taking multiple pages from one site."""
    selected = []
    used_domains: set[str] = set()
    remaining = []
    for item in results:
        domain = item.get("domain") or _domain(item.get("url", ""))
        if domain not in used_domains:
            used_domains.add(domain)
            selected.append(item)
        else:
            remaining.append(item)
        if len(selected) >= limit:
            return selected
    return (selected + remaining)[:limit]


def search_results(query: str, engine: str = "all", freshness: str = "month") -> list[dict[str, str]]:
    """Search selected engine(s) and return structured result links."""
    query = (query or "").strip()
    if not query:
        raise ValueError("A search query is required.")
    _ensure_access()
    freshness = freshness if freshness in _FRESHNESS_DAYS else _DEFAULT_FRESHNESS
    engine = engine.lower()

    if engine == "all":
        cache_key = (query.casefold(), engine, freshness)
        cached = _SEARCH_CACHE.get(cache_key)
        if cached and (_now_utc().timestamp() - cached[0]) < _CACHE_TTL_SECONDS:
            return list(cached[1])

        combined: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(search_results, query, selected, freshness): selected
                for selected in ("google", "bing", "duckgo")
            }
            for future in as_completed(futures):
                try:
                    combined.extend(future.result())
                except (RuntimeError, requests.RequestException):
                    continue

        result = _diversify_results(_deduplicate_results(combined))
        _SEARCH_CACHE[cache_key] = (_now_utc().timestamp(), result)
        return result

    if engine not in _SEARCH_ENGINES:
        raise ValueError(f"Unsupported search engine: {engine}")

    response = requests.get(
        _search_url(query, engine, freshness),
        headers={
            "User-Agent": "NyxIchos/1.0",
            **({"Ocp-Apim-Subscription-Key": SETTINGS.bing_api_key} if engine == "bing" else {}),
        },
        timeout=_TIMEOUT,
    )
    response.raise_for_status()

    if engine == "google" and response.headers.get("content-type", "").startswith("application/json"):
        items = response.json().get("items", [])
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "published_at": item.get("pagemap", {}).get("metatags", [{}])[0].get("article:published_time", "unknown"),
                "domain": _domain(item.get("link", "")),
            }
            for item in items[:_MAX_RESULTS]
        ]
    if engine == "bing":
        web_pages = response.json().get("webPages", {}).get("value", [])
        return [
            {
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "published_at": item.get("datePublished", "unknown"),
                "domain": _domain(item.get("url", "")),
            }
            for item in web_pages[:_MAX_RESULTS]
        ]

    matches = re.findall(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        response.text,
        flags=re.I | re.S,
    )
    results = []
    for href, title in matches[: _MAX_RESULTS * 2]:
        url = _real_url(unescape(href))
        if not url.startswith("http"):
            continue
        results.append({
            "title": re.sub(r"<[^>]+>", "", unescape(title)).strip(),
            "url": url,
            "published_at": "unknown",
            "domain": _domain(url),
        })
        if len(results) >= _MAX_RESULTS:
            break
    return results


def search(query: str, engine: str = "all", freshness: str = "any") -> str:
    """Search selected engine(s) and return concise titled links."""
    results = search_results(query, engine=engine, freshness=freshness)
    return "No search results found." if not results else "\n".join(f"{item['title']}: {item['url']}" for item in results)


def answer(query: str, engine: str = "all", freshness: str = "any") -> str:
    """Search, fetch result pages, and return source text for model synthesis with double-checking."""
    query = (query or "").strip()
    if not query:
        raise ValueError("A search query is required.")
    freshness = freshness if freshness in {"day", "week", "month", "any"} else _DEFAULT_FRESHNESS
    results = search_results(query, engine=engine, freshness=freshness)
    if not results:
        return "No web results found."

    sources = []
    freshness_days = _FRESHNESS_DAYS.get(freshness)

    for item in _diversify_results(_deduplicate_results(results), limit=6):
        try:
            page = fetch(item["url"])
            if not page:
                continue
            timestamp = _parse_timestamp(item.get("published_at"))
            metadata = _age_metadata(timestamp, max_age_days=freshness_days)
            sources.append({
                "title": item["title"],
                "url": item["url"],
                "domain": item.get("domain") or _domain(item["url"]),
                "metadata": metadata,
                "text": page,
            })
        except Exception:
            continue

    now = _now_utc().isoformat()
    freshness_note = f"within {freshness_days} days" if freshness_days is not None else "with no age limit"
    domains = sorted({source["domain"] for source in sources})
    corroboration = "strong" if len(domains) >= 3 else "moderate" if len(domains) == 2 else "weak"

    header = (
        f"[DOUBLE-CHECK & FACT-VERIFICATION]\n"
        f"Search timestamp: {now} UTC. Freshness scope: {freshness} ({freshness_note}).\n"
        f"Sources collected: {len(sources)} from {len(domains)} independent domains. Corroboration score: {corroboration}.\n"
        f"Instructions: Cross-check claims across independent domains. Discard unverified claims, explicitly highlight contradictions, and report findings with high confidence only when independently corroborated."
    )

    formatted = []
    for source in sources:
        metadata = source["metadata"]
        stale = " [POSSIBLY OUTDATED]" if metadata["is_stale"] else ""
        formatted.append(
            f"Source: {source['title']} ({source['url']})\n"
            f"Domain: {source['domain']} | Published: {metadata['published_at']} (age {metadata['age']}){stale}\n"
            f"{source['text']}"
        )

    return header + "\n\n" + ("\n\n".join(formatted) or "Search results could not be opened.")


def fetch_with_metadata(url: str) -> tuple[str, datetime | None]:
    """Fetch page text and its best available published/modified timestamp."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Only http:// and https:// URLs are allowed.")
    _ensure_access()
    response = requests.get(url, headers={"User-Agent": "NyxIchos/1.0"}, timeout=_TIMEOUT)
    response.raise_for_status()
    timestamp = _extract_page_timestamp(response.text, response.headers)
    text = re.sub(r"<script[^>]*>.*?</script>|<style[^>]*>.*?</style>", " ", response.text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", unescape(text))
    return re.sub(r"\s+", " ", text).strip()[:_MAX_PAGE_CHARS], timestamp


def open_link(url: str) -> str:
    """Open/fetch a discovered link safely; never permits local files or scripts."""
    return fetch(url)


def fetch(url: str) -> str:
    """Fetch a public page and return stripped, bounded text."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Only http:// and https:// URLs are allowed.")
    _ensure_access()
    text, _ = fetch_with_metadata(url)
    return text
