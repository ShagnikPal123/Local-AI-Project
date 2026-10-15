"""Blast radius: risky shell commands stop and ask the owner first, saying what they would change.

Doc 2 item 2.3, the Nyx side of the combined Claude Code mod (``claude-mods/combined-mod/hooks/risk.ts``). The same
rules, plus PowerShell and Command Prompt ones, run before ``run_command`` and other shell tools: a command that
deletes files, throws away uncommitted work, force-pushes or wipes a disk shows an approval card naming the damage
and what it would touch (the files a delete would remove, the uncommitted changes a hard reset would lose).

Everything else runs as before. A shell category already set to "ask" is not asked twice. The owner can switch it
off in Settings → Safety; it is on by default.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import data_path

SETTINGS_FILE = "blast_radius.json"
#: Tool categories whose ``command`` argument is a shell command.
SHELL_CATEGORIES = frozenset({"shell"})


@dataclass
class Risk:
    why: str
    targets: List[str] = field(default_factory=list)
    probe: str = ""  # "paths" (count what a delete removes) or "git-dirty" (what uncommitted work is lost)


_I = re.IGNORECASE
RULES = [
    (re.compile(r"\brm\s+(-[a-z]*[rf][a-z]*\s+)+", _I), "deletes files", "paths"),
    (re.compile(r"\b(remove-item|ri)\b.*-(recurse|force)\b", _I), "deletes files", "paths"),
    (re.compile(r"\b(rd|rmdir)\s+/s\b|\bdel\s+/[sqf]\b|\berase\s+/[sq]\b", _I), "deletes files", "paths"),
    (re.compile(r"\bgit\s+reset\s+--hard\b", _I), "throws away uncommitted changes", "git-dirty"),
    (re.compile(r"\bgit\s+clean\s+-[a-z]*f", _I), "deletes untracked files", "git-dirty"),
    (re.compile(r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)", _I), "throws away uncommitted changes", "git-dirty"),
    (re.compile(r"\bgit\s+push\b.*(--force\b|--force-with-lease\b|\s-f\b)", _I), "rewrites history on the remote", ""),
    (re.compile(r"\bgit\s+branch\s+-D\b"), "deletes a branch that may not be merged", ""),
    (re.compile(r"\bgit\s+stash\s+(drop|clear)\b", _I), "deletes stashed work", ""),
    (re.compile(r"\b(drop\s+(table|database|schema)|truncate\s+table)\b", _I), "deletes database data", ""),
    (re.compile(r"\b(mkfs|diskpart|format-volume|clear-disk)\b|\bformat\s+[a-z]:|\bdd\s+if=", _I), "can wipe a disk", ""),
    (re.compile(r"\b(chmod|chown)\s+-R\b|\bicacls\b.*/(grant|reset)\b.*/t\b|\btakeown\b.*/r\b", _I),
     "changes permissions on a whole tree", ""),
    (re.compile(r"\b(curl|wget|iwr|irm|invoke-webrequest|invoke-restmethod)\b[^|]*\|\s*(sh|bash|iex|invoke-expression|python)\b", _I),
     "runs a script straight from the internet", ""),
    (re.compile(r"\b(npm|pnpm|yarn)\s+publish\b|\btwine\s+upload\b", _I), "publishes a package", ""),
    (re.compile(r"\bdocker\s+(system|volume|image)\s+prune\b|\bkubectl\s+delete\b", _I), "deletes containers or cluster objects", ""),
    (re.compile(r"\bshutdown\b|\bstop-computer\b|\brestart-computer\b", _I), "turns the computer off or restarts it", ""),
    (re.compile(r"\breg\s+delete\b|\bremove-itemproperty\b", _I), "deletes registry entries", ""),
    (re.compile(r"\bset-executionpolicy\s+(unrestricted|bypass)\b", _I), "turns off PowerShell's script safety", ""),
]

_DELETE_WORDS = re.compile(r"^(rm|remove-item|ri|rd|rmdir|del|erase)$", _I)


def enabled() -> bool:
    try:
        return bool(json.loads(data_path(SETTINGS_FILE).read_text(encoding="utf-8")).get("enabled", True))
    except (OSError, ValueError, AttributeError):
        return True


def set_enabled(on: bool) -> bool:
    data_path(SETTINGS_FILE).write_text(json.dumps({"enabled": bool(on)}), encoding="utf-8")
    return bool(on)


def delete_targets(command: str) -> List[str]:
    """The path arguments of a delete: every word after the delete command that is not a flag."""
    first = re.split(r"&&|\|\||;|\|", command)[0]
    try:
        words = shlex.split(first, posix=False)
    except ValueError:
        words = first.split()
    start = next((i for i, w in enumerate(words) if _DELETE_WORDS.match(w)), -1)
    if start < 0:
        return []
    out = [w.strip("\"'") for w in words[start + 1:] if not re.match(r"^-|^/[a-z]$", w, _I)]
    return out[:8]


def assess(command: str) -> Optional[Risk]:
    """The first rule a command breaks, or None when it can run without a hold."""
    text = (command or "").strip()
    for pattern, why, probe in RULES:
        if pattern.search(text):
            return Risk(why, delete_targets(text) if probe == "paths" else [], probe)
    return None


def summarize_dirty(porcelain: str, most: int = 6) -> str:
    """``git status --porcelain`` lines as "M src/a.py, ?? notes.md and 3 more"."""
    lines = [line.strip() for line in porcelain.splitlines() if line.strip()]
    if not lines:
        return "nothing uncommitted would be lost"
    shown = ", ".join(lines[:most])
    return f"{shown} and {len(lines) - most} more" if len(lines) > most else shown


def _count(path: Path, cap: int = 20000) -> int:
    if path.is_file():
        return 1
    total = 0
    for _ in path.rglob("*"):
        total += 1
        if total >= cap:
            break
    return total


def probe(risk: Risk, cwd: str = "") -> str:
    """The live part: what the command would actually touch here. Never raises."""
    base = Path(cwd or ".").expanduser()
    try:
        if risk.probe == "git-dirty":
            done = subprocess.run(["git", "status", "--porcelain"], cwd=str(base), capture_output=True,
                                  text=True, timeout=10)
            if done.returncode != 0:
                return ""
            return "Would lose: " + summarize_dirty(done.stdout)
        if risk.probe == "paths" and risk.targets:
            parts = []
            for target in risk.targets:
                path = Path(target).expanduser()
                path = path if path.is_absolute() else base / path
                if path.exists():
                    count = _count(path)
                    parts.append(f"{target} ({count} file{'s' if count != 1 else ''}{'+' if count >= 20000 else ''})")
                else:
                    parts.append(f"{target} (not there now)")
            return "Would remove: " + ", ".join(parts)
    except Exception:  # noqa: BLE001 - the probe only adds detail; the hold itself still happens
        return ""
    return ""


def check(ctx: Any, name: str, category: str, args: Dict[str, Any]) -> None:
    """Before a tool runs: hold a risky shell command for the owner. Raises PermissionDenied when they say no."""
    if category not in SHELL_CATEGORIES or not enabled():
        return
    command = str((args or {}).get("command") or "")
    risk = assess(command)
    if risk is None:
        return
    from permissions import POLICY, ask

    if POLICY.mode_for(category, getattr(ctx, "role", "local") if ctx is not None else "local") == "ask":
        return  # permissions.require has just asked about this command
    cwd = str((args or {}).get("cwd") or getattr(ctx, "code_root", "") or "")
    detail = "\n".join(part for part in (f"Command: {command[:600]}", probe(risk, cwd)) if part)
    ask(category, f"Risky command: it {risk.why}", detail=detail)
