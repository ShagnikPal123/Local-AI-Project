"""The curated list of skills Shagnik asked for ("first add all skills from the GitHubs I have added"), and the installer.

Why this exists: ``skill_packs.py`` can hold a big library, but someone has to say *which* SKILL.md files from the
owner's repos are worth keeping. Dumping every file would attach duplicates (claude-mem ships the same ``do`` skill in
four plugin folders) and tools tied to services the app does not use. This module is that decision, written down.

What it does NOT do: copy scripts, run anything, or fetch from a repo the owner has not approved. Each entry marked
``needs_ok`` is skipped unless the caller passes ``include_needs_ok=True`` (e.g. strix, which attacks targets).

Run on the PC (packs are git-ignored and live in the data folder):

    .venv/Scripts/python.exe skill_catalog.py            # install everything approved
    .venv/Scripts/python.exe skill_catalog.py --list     # just show the plan
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import skill_packs
from skill_import import SkillImportError, _get

# pack name -> where it comes from and which SKILL.md files to keep (paths are inside the repo).
CATALOG: Dict[str, Dict[str, Any]] = {
    "claude-mem": {
        "title": "claude-mem skills (planning, memory, handoff, code exploration)",
        "repo": "thedotmack/claude-mem",
        "needs_ok": False,
        "paths": [f"plugin/skills/{n}/SKILL.md" for n in (
            "make-plan", "do", "mem-search", "knowledge-agent", "handoff", "smart-explore", "learn-codebase",
            "pathfinder", "babysit", "standup", "design-is", "wowerpoint", "what-the", "timeline-report")],
    },
    "official-plugins": {
        "title": "Anthropic official plugin skills (skill writing, MCP, frontend, setup)",
        "repo": "anthropics/claude-plugins-official",
        "needs_ok": False,
        "paths": [
            "plugins/claude-code-setup/skills/claude-automation-recommender/SKILL.md",
            "plugins/claude-md-management/skills/claude-md-improver/SKILL.md",
            "plugins/frontend-design/skills/frontend-design/SKILL.md",
            "plugins/playground/skills/playground/SKILL.md",
            "plugins/skill-creator/skills/skill-creator/SKILL.md",
            "plugins/mcp-server-dev/skills/build-mcp-server/SKILL.md",
            "plugins/mcp-server-dev/skills/build-mcp-app/SKILL.md",
            "plugins/plugin-dev/skills/skill-development/SKILL.md",
            "plugins/plugin-dev/skills/agent-development/SKILL.md",
            "plugins/plugin-dev/skills/hook-development/SKILL.md",
        ],
    },
    "ecc": {
        "title": "everything-claude-code (testing, security and coding standards)",
        "repo": "worldflowai/everything-claude-code",
        "needs_ok": False,
        "paths": [f"skills/{n}/SKILL.md" for n in (
            "tdd-workflow", "verification-loop", "eval-harness", "coding-standards", "backend-patterns",
            "frontend-patterns", "security-review")],
    },
    "agent-reach": {
        "title": "Agent-Reach: read 16 internet platforms (Instagram, YouTube, Reddit, X, RSS...)",
        "repo": "Panniantong/Agent-Reach",
        "needs_ok": False,
        "paths": ["agent_reach/skill/SKILL.md"],
    },
    "find-skills": {
        "title": "vercel-labs find-skills: look up and install a skill that is missing",
        "repo": "vercel-labs/skills",
        "needs_ok": False,
        "paths": ["skills/find-skills/SKILL.md"],
    },
    "strix": {
        "title": "Strix penetration testing (Docker + Kali; only against the owner's own targets)",
        "repo": "tghastings/strix-claude-code",
        "needs_ok": True,
        "paths": ["SKILL.md"],
    },
}


def plan(include_needs_ok: bool = False) -> List[Dict[str, Any]]:
    """What would be installed: one row per pack, with the skipped ones marked."""
    return [{"pack": name, "repo": entry["repo"], "count": len(entry["paths"]),
             "skipped": bool(entry["needs_ok"] and not include_needs_ok)} for name, entry in CATALOG.items()]


def install(include_needs_ok: bool = False, only: Optional[List[str]] = None, root: Path | None = None,
            fetch: Callable[..., Any] | None = None) -> Dict[str, Any]:
    """Fetch the chosen SKILL.md files and install each pack. ``fetch`` is injectable so tests never touch the network.

    One bad file (renamed upstream, 404) is reported and skipped; it never stops the other skills from installing.
    """
    get = fetch or _get
    done: Dict[str, int] = {}
    problems: List[str] = []
    for pack, entry in CATALOG.items():
        if only and pack not in only:
            continue
        if entry["needs_ok"] and not include_needs_ok:
            problems.append(f"{pack}: skipped (needs the owner's OK)")
            continue
        repo = entry["repo"]
        try:
            branch = str(get(f"https://api.github.com/repos/{repo}").get("default_branch") or "main")
        except SkillImportError as error:
            problems.append(f"{pack}: {error}")
            continue
        with tempfile.TemporaryDirectory() as tmp:
            for path in entry["paths"]:
                # Stage as <name>/SKILL.md because install_pack reads that layout and names the skill from the folder.
                folder = Path(path).parent.name if "/" in path else pack
                try:
                    text = get(f"https://raw.githubusercontent.com/{repo}/{branch}/{path}", raw=True)
                except SkillImportError as error:
                    problems.append(f"{pack}/{path}: {error}")
                    continue
                (Path(tmp) / folder).mkdir(parents=True, exist_ok=True)
                (Path(tmp) / folder / "SKILL.md").write_text(text, encoding="utf-8")
            done[pack] = skill_packs.install_pack(pack, Path(tmp), entry["title"],
                                                  f"https://github.com/{repo}", root=root)
    return {"installed": done, "problems": problems}


if __name__ == "__main__":
    if "--list" in sys.argv:
        for row in plan():
            print(row)
    else:
        print(install())
