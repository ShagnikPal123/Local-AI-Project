"""Leak sweep: look at what is about to be pushed and stop if a key or anything personal is in it.

Shagnik's standing rule (2026-10-13): "Ensure each time there is a sweep for any leaks in API or
anything personal." So before every push this runs over the lines being added and refuses when it
finds one of these:

* **Keys and tokens** - the shapes real providers use (OpenAI, Anthropic, Google, Groq, GitHub,
  AWS, Slack, Alpaca, private key blocks, JSON web tokens) and any ``key = "long value"`` line.
* **Secret files** - ``.env``, ``.secrets.json`` and friends being added at all.
* **Personal details** - email addresses, phone numbers, and local paths that carry a user name
  (``C:\\Users\\<name>``, ``/Users/<name>``, ``/home/<name>``).
* **Pictures** - any new image is listed so a person checks it is not a personal screenshot.

Why only *added* lines: old lines were already swept when they went in, and a sweep that shouts
about the whole history every time gets ignored. Why a plain script and not a git hook: it has to
work the same on Shagnik's Windows PC, in a cloud session and inside the trader's own repo later.

Usage::

    python apps/ichos-trader/tools/leak_sweep.py              # staged changes
    python apps/ichos-trader/tools/leak_sweep.py origin/main  # everything not pushed yet
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, List, Optional

KEY_PATTERNS = [
    ("OpenAI key", re.compile(r"\bsk-(?:proj-)?[0-9A-Za-z_\-]{20,}")),
    ("Anthropic key", re.compile(r"\bsk-ant-[0-9A-Za-z_\-]{20,}")),
    ("Google key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("Groq key", re.compile(r"\bgsk_[0-9A-Za-z]{20,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z]{30,}|\bgithub_pat_[0-9A-Za-z_]{30,}")),
    ("AWS key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[0-9A-Za-z\-]{10,}")),
    ("Alpaca key", re.compile(r"\b[PA]K[0-9A-Z]{16,20}\b")),
    ("Private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Web token", re.compile(r"\beyJ[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}\.[0-9A-Za-z_\-]{10,}")),
    ("Long hex token", re.compile(r"\b[0-9a-f]{48,}\b")),
    # key = "…" / "secret": "…" with a long value that is not obviously a placeholder.
    ("Key in an assignment", re.compile(
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|client[_-]?secret)\b\s*[\"']?\s*[:=]\s*[\"']([^\"'\s]{16,})[\"']")),
]

EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(r"(?<![\w.])(?:\+?1[\s.\-]?)?\(?\b[2-9]\d{2}\)?[\s.\-]\d{3}[\s.\-]\d{4}\b")
USER_PATH = re.compile(r"(?i)(?:[A-Z]:\\+Users\\+|/Users/|/home/)([A-Za-z0-9._\-]+)")

#: Addresses and names that are safe to commit: robots, examples and placeholders.
SAFE_EMAIL = re.compile(r"(?i)@(?:anthropic\.com|example\.(?:com|org|net)|users\.noreply\.github\.com|localhost)$|^noreply@|^you@|^owner@")
SAFE_PATH_USERS = {"claude", "runner", "user", "you", "name", "username", "<name>", "me", "public", "default"}
PLACEHOLDER = re.compile(r"(?i)^(?:x+|\*+|your[_\-].*|change[_\-]?me.*|<.*>|\$\{.*\}|example.*|test.*|fake.*|dummy.*)$")

SECRET_FILES = re.compile(r"(?i)(?:^|/)(?:\.env(?:\..*)?|\.secrets\.json|secrets\.json|id_rsa|id_ed25519|.*\.pem|.*\.p12|.*\.pfx)$")
IMAGE_FILES = re.compile(r"(?i)\.(?:png|jpe?g|gif|webp|heic|bmp)$")

#: This file describes the patterns, so its own lines would match them.
SELF = "apps/ichos-trader/tools/leak_sweep.py"


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    text: str

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{where}  {self.kind}: {self.text}"


def _mask(text: str) -> str:
    """Show enough to find it, never the whole value: a sweep report must not be a leak itself."""
    text = text.strip()
    return text if len(text) <= 8 else f"{text[:4]}…{text[-2:]}"


def scan_line(path: str, number: int, line: str) -> List[Finding]:
    """Everything wrong with one added line. Pure, so it is easy to test."""
    found: List[Finding] = []
    for kind, pattern in KEY_PATTERNS:
        for match in pattern.finditer(line):
            value = match.group(match.lastindex or 0)
            if kind == "Key in an assignment" and PLACEHOLDER.match(value):
                continue
            found.append(Finding(path, number, kind, _mask(value)))
    for match in EMAIL.finditer(line):
        if not SAFE_EMAIL.search(match.group(0)):
            found.append(Finding(path, number, "Email address", _mask(match.group(0))))
    for match in PHONE.finditer(line):
        found.append(Finding(path, number, "Phone number", _mask(match.group(0))))
    for match in USER_PATH.finditer(line):
        if match.group(1).lower() not in SAFE_PATH_USERS:
            found.append(Finding(path, number, "Local path with a user name", _mask(match.group(0))))
    return found


def scan_diff(diff: str) -> List[Finding]:
    """Walk a unified diff (``git diff -U0``) and scan only the lines it adds."""
    findings: List[Finding] = []
    path: Optional[str] = None
    number = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else target[2:] if target.startswith("b/") else target
            if path and SECRET_FILES.search(path):
                findings.append(Finding(path, 0, "Secret file", "this kind of file should never be committed"))
            if path and IMAGE_FILES.search(path):
                findings.append(Finding(path, 0, "New picture", "check it is not a personal screenshot"))
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            number = int(match.group(1)) if match else 0
            continue
        if raw.startswith("+") and path and path != SELF:
            findings.extend(scan_line(path, number, raw[1:]))
            number += 1
        elif raw.startswith(" "):
            number += 1
    return findings


def _diff(base: Optional[str]) -> str:
    args = ["git", "diff", "-U0", "--no-color"]
    args += [f"{base}...HEAD"] if base else ["--cached"]
    # CREATE_NO_WINDOW keeps a console from flashing on Windows (0 elsewhere); see quiet_windows.py.
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    base = args[0] if args else None
    findings = scan_diff(_diff(base))
    pictures = [f for f in findings if f.kind == "New picture"]
    problems = [f for f in findings if f.kind != "New picture"]
    for finding in pictures:
        print(f"CHECK  {finding}")
    for finding in problems:
        print(f"LEAK   {finding}")
    if problems:
        print(f"\nStopped: {len(problems)} possible leak(s). Remove them, then sweep again.")
        return 1
    print("Leak sweep clean." + (f" {len(pictures)} picture(s) to eyeball." if pictures else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
