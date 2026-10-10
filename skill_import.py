"""Import skills from GitHub — the ``SKILL.md`` format (agentskills.io) that Claude Code, OpenJarvis and others use.

From OpenJarvis (Apache-2.0), which the owner pointed at on 2026-10-09: "Skills can be imported from … any GitHub
repo, following the agentskills.io standard." A skill there is a folder with a ``SKILL.md``: YAML-ish front matter
(``name``, ``description``) and Markdown instructions. Nyx's skills are the same idea — text the model reads — so a
SKILL.md becomes a Nyx skill directly (``skills.SKILL_STORE``, source "imported").

What is NOT imported: scripts, binaries or anything else in the skill's folder. Nothing from a repo is ever run
(AGENTS.md, invariant 2). Each SKILL.md is shown first with any text in it aimed at the assistant flagged by
``file_guard.injection_notes``; the owner picks which ones to add.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

MAX_FILES = 60
MAX_BYTES = 60_000
TIMEOUT = 20
_GITHUB = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?"
                     r"(?:/(?:tree|blob)/([^/]+)(?:/(.*))?)?/?$")


class SkillImportError(RuntimeError):
    """Something the owner can act on."""


def parse_url(url: str) -> Tuple[str, str, str, str]:
    """(owner, repo, branch or "", path or "") from a GitHub link to a repo, a folder or a SKILL.md."""
    match = _GITHUB.match((url or "").strip())
    if not match:
        raise SkillImportError("Paste a GitHub link, e.g. https://github.com/anthropics/skills or a folder inside one.")
    owner, repo, branch, path = match.groups()
    return owner, repo, branch or "", (path or "").strip("/")


def parse_skill_md(text: str, fallback_name: str = "") -> Dict[str, Any]:
    """Front matter + body → name, description, instructions, triggers. Tolerant of missing front matter."""
    text = (text or "").replace("\r\n", "\n")
    meta: Dict[str, str] = {}
    body = text
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if match:
        body = match.group(2)
        current = ""
        for line in match.group(1).splitlines():
            key, sep, value = line.partition(":")
            if sep and key.strip() and not line.startswith((" ", "\t")):
                current = key.strip().lower()
                value = value.strip()
                # YAML block scalars (description: > or |-) continue on the indented lines that follow.
                meta[current] = "" if value in (">", ">-", "|", "|-", ">+", "|+") else value.strip("\"'")
            elif current and line.startswith((" ", "\t")) and line.strip():
                meta[current] = (meta[current] + " " + line.strip()).strip()
    heading = re.search(r"^#\s+(.+)$", body, re.M)
    name = meta.get("name") or (heading.group(1).strip() if heading else "") or fallback_name or "Imported skill"
    description = meta.get("description") or next((p.strip() for p in body.split("\n\n") if p.strip() and not p.startswith("#")), "")
    words = re.findall(r"[a-z][a-z0-9-]{2,}", f"{name.replace('-', ' ')} {description}".lower())
    stop = {"this", "that", "with", "when", "from", "your", "skill", "uses", "used", "them", "into", "about", "should",
            "the", "and", "for", "you", "are", "use", "any", "can", "its", "not", "all", "one", "out", "how"}
    triggers = sorted({w for w in words if w not in stop})[:12]
    return {"name": name[:80], "description": description[:400], "instructions": body.strip()[:MAX_BYTES],
            "triggers": triggers}


def _get(url: str, *, raw: bool = False) -> Any:
    import requests

    headers = {"Accept": "application/vnd.github+json", "User-Agent": "Nyx-Ichos-skill-import"}
    try:
        response = requests.get(url, headers=headers, timeout=TIMEOUT)
    except requests.RequestException as error:
        raise SkillImportError(f"GitHub could not be reached: {error}") from error
    if response.status_code == 404:
        raise SkillImportError("Nothing there — check the link, and that the repo is public.")
    if response.status_code == 403:
        raise SkillImportError("GitHub is rate-limiting this PC right now; try again in a while.")
    if response.status_code != 200:
        raise SkillImportError(f"GitHub answered {response.status_code}.")
    return response.text if raw else response.json()


def find(url: str, fetch: Any = None) -> Dict[str, Any]:
    """Every SKILL.md under the link (max 60), read and checked, ready for the owner to pick from."""
    from file_guard import injection_notes

    get = fetch or _get
    owner, repo, branch, path = parse_url(url)
    if not branch:
        branch = str(get(f"https://api.github.com/repos/{owner}/{repo}").get("default_branch") or "main")
    tree = get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
    files = [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"
             and item["path"].split("/")[-1].lower() == "skill.md"
             and (not path or item["path"] == path or item["path"].startswith(path.rstrip("/") + "/"))][:MAX_FILES]
    if not files:
        raise SkillImportError("No SKILL.md files there. A skill is a folder with a SKILL.md inside it.")
    found = []
    for file_path in files:
        text = get(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}", raw=True)
        folder = file_path.rsplit("/", 1)[0] if "/" in file_path else repo
        skill = parse_skill_md(text, fallback_name=folder.split("/")[-1])
        found.append({"path": file_path, "url": f"https://github.com/{owner}/{repo}/blob/{branch}/{file_path}",
                      "name": skill["name"], "description": skill["description"], "size": len(text),
                      "warnings": injection_notes(text), "too_big": len(text) > MAX_BYTES})
    return {"repo": f"{owner}/{repo}", "branch": branch, "skills": found}


def import_skills(url: str, paths: List[str], fetch: Any = None, store: Any = None) -> List[Dict[str, Any]]:
    """Add the chosen SKILL.md files as Nyx skills. Returns what was added."""
    from skills import SKILL_STORE

    get = fetch or _get
    target = store or SKILL_STORE
    owner, repo, branch, _path = parse_url(url)
    if not branch:
        branch = str(get(f"https://api.github.com/repos/{owner}/{repo}").get("default_branch") or "main")
    added = []
    for file_path in paths[:MAX_FILES]:
        if not file_path.lower().endswith("skill.md") or ".." in file_path:
            continue
        text = get(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{file_path}", raw=True)
        folder = file_path.rsplit("/", 1)[0] if "/" in file_path else repo
        skill = parse_skill_md(text, fallback_name=folder.split("/")[-1])
        source = f"https://github.com/{owner}/{repo}/blob/{branch}/{file_path}"
        instructions = (f"(Imported from {source}. Files this skill mentions — scripts, references — were not "
                        f"imported; do not assume they exist.)\n\n{skill['instructions']}")
        made = target.add(skill["name"], skill["description"] or f"Imported from {owner}/{repo}", instructions,
                          triggers=skill["triggers"], source="imported", author=f"{owner}/{repo}", category="github")
        added.append({"id": made.skill_id, "name": made.name, "from": source})
    if not added:
        raise SkillImportError("Pick at least one SKILL.md to add.")
    return added
