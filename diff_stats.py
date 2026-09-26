"""How many lines an edit touches, and in which file (Request R9).

The owner (2026-09-17): "for both coding and improve make it so that when its working and editing field and I tell it
a specific prompt to approve an improve or whatever it is make it so that it shows how many lines are affected and in
which file."

Every edit in Nyx ends up as a unified diff (``self_patch``, ``code_workspace``), so the numbers come from the diff
itself rather than from what a model says it changed. "Lines affected" counts a replaced line once: an edit that
rewrites 3 lines and adds 2 is ``+5 −3`` and affects 5 lines, which is what someone reviewing it has to read.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _clean_path(header: str) -> str:
    path = header.split("\t", 1)[0].strip()
    if path in ("/dev/null", ""):
        return ""
    return path[2:] if path[:2] in ("a/", "b/") else path


def stats(diff: str) -> Dict[str, Any]:
    """``{"files": [{path, added, removed, affected, ranges, created, deleted}], added, removed, affected}``.

    ``ranges`` are ``[first, last]`` line numbers in the new file (the old file's for a pure deletion), merged
    when hunks touch, so "lines 120–148" reads the way an editor shows it.
    """
    files: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    old_path = ""
    new_line = old_line = 0
    run_add = run_del = 0

    def close_run() -> None:
        nonlocal run_add, run_del
        if current is not None and (run_add or run_del):
            current["affected"] += max(run_add, run_del)
        run_add = run_del = 0

    def mark(line_no: int) -> None:
        ranges = current["ranges"]
        if ranges and line_no <= ranges[-1][1] + 1:
            ranges[-1][1] = max(ranges[-1][1], line_no)
        else:
            ranges.append([line_no, line_no])

    for line in (diff or "").splitlines():
        if line.startswith("--- "):
            close_run()
            old_path = _clean_path(line[4:])
            continue
        if line.startswith("+++ "):
            new_path = _clean_path(line[4:])
            current = {"path": new_path or old_path, "added": 0, "removed": 0, "affected": 0, "ranges": [],
                       "created": not old_path, "deleted": not new_path}
            files.append(current)
            continue
        match = _HUNK.match(line)
        if match:
            close_run()
            if current is None:  # a bare hunk with no file header
                current = {"path": "", "added": 0, "removed": 0, "affected": 0, "ranges": [], "created": False, "deleted": False}
                files.append(current)
            old_line, new_line = int(match.group(1)), int(match.group(3))
            continue
        if current is None or line.startswith("\\"):
            continue
        if line.startswith("+"):
            current["added"] += 1
            run_add += 1
            mark(new_line)
            new_line += 1
        elif line.startswith("-"):
            current["removed"] += 1
            run_del += 1
            mark(max(1, new_line) if not current["deleted"] else old_line)
            old_line += 1
        else:
            close_run()
            old_line += 1
            new_line += 1
    close_run()
    files = [f for f in files if f["added"] or f["removed"] or f["created"]]
    return {
        "files": files,
        "added": sum(f["added"] for f in files),
        "removed": sum(f["removed"] for f in files),
        "affected": sum(f["affected"] for f in files),
    }


def from_texts(before: str, after: str, path: str) -> Dict[str, Any]:
    """Exact numbers from the two versions (a stored diff may have been cut short)."""
    diff = "".join(difflib.unified_diff((before or "").replace("\r\n", "\n").splitlines(True),
                                        (after or "").replace("\r\n", "\n").splitlines(True),
                                        fromfile=f"a/{path}", tofile=f"b/{path}", n=0))
    return stats(diff)


def _ranges_text(ranges: List[List[int]], limit: int = 3) -> str:
    parts = [f"{a}" if a == b else f"{a}–{b}" for a, b in ranges[:limit]]
    more = len(ranges) - limit
    return ", ".join(parts) + (f" and {more} more" if more > 0 else "")


def describe_file(entry: Dict[str, Any]) -> str:
    name = entry.get("path") or "the file"
    lines = entry.get("affected") or 0
    counts = f"+{entry.get('added', 0)} −{entry.get('removed', 0)}"
    if entry.get("created"):
        return f"new file {name}, {entry.get('added', 0)} lines"
    ranges = entry.get("ranges") or []
    where = ""
    if ranges:
        single = len(ranges) == 1 and ranges[0][0] == ranges[0][1]
        where = f" at line{'' if single else 's'} {_ranges_text(ranges)}"
    return f"{name}: {lines} line{'s' if lines != 1 else ''} ({counts}){where}"


def describe(summary: Dict[str, Any], limit: int = 4) -> str:
    """One sentence for a status line or a log: "server.py: 12 lines (+8 −4) at lines 120–131"."""
    files = summary.get("files") or []
    if not files:
        return "no lines changed"
    text = "; ".join(describe_file(entry) for entry in files[:limit])
    if len(files) > limit:
        text += f"; and {len(files) - limit} more files"
    if len(files) > 1:
        text = f"{len(files)} files, {summary.get('affected', 0)} lines — " + text
    return text


def describe_diff(diff: str) -> str:
    return describe(stats(diff))
