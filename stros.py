"""Stros: Nyx's own security checker — the in-house stand-in for an outside pentest tool.

The owner liked the idea of Strix but not the outside dependency (Docker, a Kali sandbox, a tool that attacks targets).
Stros keeps the parts the app needs and stays on the owner's side of the fence:

1. **Leak sweep** — finds API keys, tokens, private keys and personal details (emails, phone numbers, Windows user
   paths) in text, a git diff or a folder. This is the check the owner wants before every push.
2. **Route check** — asks the owner's *own running app* (localhost only) for its API routes with no login and reports
   any that answer. That tests invariant 1, deny by default (AGENTS.md).

Safety choices: findings never contain the full secret (masked), and the route check refuses any address that is not
this PC, so Stros cannot be pointed at someone else's server.

    .venv/Scripts/python.exe stros.py leaks [folder]        # sweep a folder (default: the project)
    git diff origin/main | .venv/Scripts/python.exe stros.py diff   # sweep what is about to be pushed
"""

from __future__ import annotations

import ipaddress
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import urlparse

# Secrets recognisable by shape. Kept here (not imported) so Stros works even when the app cannot start.
_SECRET_SHAPES = [
    ("api key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("api key", re.compile(r"\bsk-(?:ant-|proj-)?[0-9A-Za-z_\-]{20,}")),
    ("api key", re.compile(r"\b(?:nvapi-|gsk_)[0-9A-Za-z_\-]{20,}")),
    ("github token", re.compile(r"\b(?:ghp|gho|ghu|ghs|github_pat)_[0-9A-Za-z_]{20,}")),
    ("private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
    ("secret assignment", re.compile(r"(?i)(?:api_key|secret|token|password)\s*[=:]\s*['\"]?([A-Za-z0-9_\-\.]{20,})")),
]
_PERSONAL_SHAPES = [
    ("email address", re.compile(r"\b[\w.+-]+@(?!example\.|users\.noreply\.github\.com|noreply\.)[\w-]+\.[a-z]{2,}\b", re.I)),
    ("phone number", re.compile(r"(?<![\w.])\+?\d{1,2}[ .-]?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")),
    ("local user path", re.compile(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+(?!<|%|\{|Public|Default|name|user\b)[^\\/\s\"']+")),
    ("home folder path", re.compile(r"(?:/home|/Users)/(?!claude\b|runner\b|user\b|name\b|<)[a-z][\w.-]{2,}/")),
]
# Values that look like tokens but are placeholders in docs and tests.
_PLACEHOLDER = re.compile(r"(?i)x{4,}|your[-_ ]?|example|placeholder|changeme|<[^>]+>|\.\.\.|\$\{|\bos\.getenv")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "local_pytest_tmp"}
SKIP_FILES = {".env.example"}


def mask(value: str) -> str:
    """Enough to find the spot, never enough to use the secret."""
    return value[:4] + "…" + f"({len(value)} chars)" if len(value) > 8 else "…"


def scan_text(name: str, text: str, personal: bool = True) -> List[Dict[str, Any]]:
    """Findings in one text: ``{file, line, kind, sample}``. Placeholders and obvious docs examples are ignored."""
    found: List[Dict[str, Any]] = []
    shapes = _SECRET_SHAPES + (_PERSONAL_SHAPES if personal else [])
    for number, line in enumerate((text or "").splitlines(), 1):
        if len(line) > 2000:
            line = line[:2000]
        seen = set()  # one finding per value per line, even when two shapes both recognise it
        for kind, pattern in shapes:
            for match in pattern.finditer(line):
                value = match.group(1) if pattern.groups else match.group(0)
                if value in seen:
                    continue
                seen.add(value)
                if _PLACEHOLDER.search(value) or _PLACEHOLDER.search(line) and kind == "secret assignment":
                    continue
                found.append({"file": name, "line": number, "kind": kind, "sample": mask(value)})
    return found


def scan_diff(diff: str) -> List[Dict[str, Any]]:
    """Only the lines a diff *adds* — old leaks already in history are a different job."""
    found: List[Dict[str, Any]] = []
    current = ""
    for line in (diff or "").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            found += [dict(f, file=current or "diff") for f in scan_text(current, line[1:])]
    return found


def scan_tree(root: Path, extra_skip: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """Every text file under ``root`` (skipping build folders and binaries)."""
    found: List[Dict[str, Any]] = []
    skip = SKIP_DIRS | set(extra_skip)
    for path in sorted(Path(root).rglob("*")):
        if not path.is_file() or skip & set(path.relative_to(root).parts) or path.name in SKIP_FILES:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found += scan_text(str(path.relative_to(root)).replace("\\", "/"), text)
    return found


def _is_this_pc(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def probe_routes(base_url: str, routes: Iterable[str], allowed_open: Iterable[str] = (),
                 get: Optional[Callable[[str], int]] = None) -> Dict[str, Any]:
    """Which API routes answer with no login. ``get(url)`` returns the HTTP status and is injectable for tests.

    A 401/403 is the right answer. A 200 on a route not in ``allowed_open`` breaks deny-by-default.
    """
    if not _is_this_pc(base_url):
        raise ValueError("Stros only checks this PC (localhost). It will not probe other addresses.")
    if get is None:
        import requests
        get = lambda url: requests.get(url, timeout=5).status_code  # noqa: E731
    open_ok = set(allowed_open)
    exposed, fine = [], []
    for route in routes:
        status = get(base_url.rstrip("/") + route)
        (exposed if status == 200 and route not in open_ok else fine).append({"route": route, "status": status})
    return {"exposed": exposed, "checked": len(exposed) + len(fine)}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "leaks"
    results = scan_diff(sys.stdin.read()) if mode == "diff" else scan_tree(Path(sys.argv[2] if len(sys.argv) > 2 else "."))
    for row in results:
        print(f"{row['file']}:{row['line']}  {row['kind']}  {row['sample']}")
    print(f"{len(results)} finding(s).")
    sys.exit(1 if results else 0)
