"""Where an answer came from, as links that work, and pictures the chat can show (Request H15).

"Add a sources drop down in the AI respond bubble where I can click on links. Also make sure the
links work correctly. Also make sure it can show images in the chat."

* :func:`extract` pulls clean http(s) links (with a title when there is one) out of tool results
  and the reply itself: trailing punctuation and unbalanced brackets are trimmed, tracking
  parameters dropped, duplicates merged. The turn sends them with ``done`` and saves them with the
  message, so the drop-down is still there after a reload.
* :func:`fetch_image` lets the chat show a remote picture without the browser contacting the
  remote site: the engine fetches it — https only, public addresses only (no localhost, LAN or
  cloud metadata IPs, re-checked on every redirect), images only (no SVG), at most 8 MB.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

MAX_SOURCES = 12
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp")

_MD_LINK = re.compile(r"\[([^\]\n]{1,200})\]\((https?://[^\s)]+(?:\([^\s)]*\)[^\s)]*)*)\)")
_BARE = re.compile(r"https?://[^\s<>\"'`]+")
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_eid$|ref_src$)")


def clean_url(url: str) -> Optional[str]:
    """A usable http(s) link, or None: punctuation and unbalanced closers trimmed, trackers removed."""
    value = (url or "").strip().strip("<>")
    while value and value[-1] in ".,;:!?\"'*_~":
        value = value[:-1]
    for opener, closer in (("(", ")"), ("[", "]")):
        while value.endswith(closer) and value.count(opener) < value.count(closer):
            value = value[:-1]
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc or " " in parts.netloc:
        return None
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)])
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", query, parts.fragment))


def _domain(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _title_near(line: str, url: str) -> str:
    """"Title — https://…" or "1. Title (https://…)": the words on the line before the link."""
    before = line.split(url, 1)[0]
    before = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", before)
    before = re.sub(r"[\s(\[:—–|-]+$", "", before).strip(" *_")
    if before.lower() in {"link", "links", "source", "sources", "url", "here", "see", "at", "via", "from"}:
        return ""
    return before[:160] if 3 <= len(before) <= 160 else ""


def extract(*texts: str, limit: int = MAX_SOURCES) -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    seen: Dict[str, Dict[str, str]] = {}

    def add(url: str, title: str) -> None:
        clean = clean_url(url)
        if not clean or "/api/" in urlsplit(clean).path[:5]:
            return
        key = clean.rstrip("/").lower()
        if key in seen:
            if title and not seen[key]["title"]:
                seen[key]["title"] = title
            return
        entry = {"url": clean, "title": title, "domain": _domain(clean)}
        seen[key] = entry
        found.append(entry)

    for text in texts:
        for match in _MD_LINK.finditer(text or ""):
            add(match.group(2), match.group(1).strip())
        stripped = _MD_LINK.sub(" ", text or "")
        for line in stripped.splitlines():
            for match in _BARE.finditer(line):
                add(match.group(0), _title_near(line, match.group(0)))
        if len(found) >= limit:
            break
    for entry in found:
        entry["title"] = entry["title"] or entry["domain"]
    return found[:limit]


# --- pictures -----------------------------------------------------------------------------------


class ImageRefused(ValueError):
    """The picture cannot be shown, with a reason fit for the chat."""


def _public_host(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise ImageRefused(f"Could not find {host}.") from error
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if (address.is_private or address.is_loopback or address.is_link_local or address.is_reserved
                or address.is_multicast or address.is_unspecified):
            raise ImageRefused("Pictures from this computer's network are not fetched.")


def fetch_image(url: str, session: Any = None, max_redirects: int = 3) -> Tuple[bytes, str]:
    """The picture's bytes and type, fetched by the engine under the rules in the module docstring."""
    import requests

    http = session or requests
    current = clean_url(url)
    for _ in range(max_redirects + 1):
        if not current or urlsplit(current).scheme != "https":
            raise ImageRefused("Only https pictures are shown.")
        _public_host(urlsplit(current).hostname or "")
        response = http.get(current, stream=True, timeout=10, allow_redirects=False,
                            headers={"User-Agent": "NyxIchos/1.0 (image preview)", "Accept": "image/*"})
        if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
            current = clean_url(urljoin(current, response.headers["location"]))
            continue
        if response.status_code != 200:
            raise ImageRefused(f"The site answered {response.status_code}.")
        kind = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if kind not in IMAGE_TYPES:
            raise ImageRefused("That link is not a picture Nyx can show.")
        declared = int(response.headers.get("content-length") or 0)
        if declared > MAX_IMAGE_BYTES:
            raise ImageRefused("That picture is too large to preview.")
        chunks, size = [], 0
        for chunk in response.iter_content(64 * 1024):
            size += len(chunk)
            if size > MAX_IMAGE_BYTES:
                raise ImageRefused("That picture is too large to preview.")
            chunks.append(chunk)
        return b"".join(chunks), kind
    raise ImageRefused("Too many redirects.")
