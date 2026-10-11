"""Skill packs — large SKILL.md libraries the assistant reads on demand (owner, 2026-10-11).

The owner asked for four GitHub skill repos in the AI: ootto-watch (watch a video), diagram-design, K-Dense's 177
scientific skills and mukul975's 818 cybersecurity procedures. Added to the skill store one by one, ~1000 skills would
attach unrelated procedures to ordinary turns (trigger matching is word-based) and rewrite a huge skills.json on every
use. So a pack lives on disk instead: ``skill_packs/<pack>/index.json`` plus one ``<name>.md`` per skill.
``search_skills`` also searches the packs and ``use_skill("pack:<pack>/<name>")`` loads one (agent_runtime.py).

Only the SKILL.md text is kept. Scripts, binaries and assets in the source repos are never copied or run (AGENTS.md,
invariant 2). Install from a local checkout:

    .venv/Scripts/python.exe skill_packs.py install <pack> <folder with */SKILL.md> "<title>" <source url>
"""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from paths import DATA_DIR

PACKS_DIR = DATA_DIR / "skill_packs"
MAX_SKILL_BYTES = 80_000
_WORD = re.compile(r"[a-z0-9][a-z0-9+#.-]{1,}")
_STOP = {"the", "and", "for", "with", "use", "using", "this", "that", "from", "into", "when", "your", "are", "you",
         "skill", "skills", "can", "via", "its", "all", "any", "how", "what", "a", "an", "of", "to", "in", "on", "or"}
_lock = threading.Lock()
_cache: Dict[str, Any] = {"key": None, "packs": {}}


def _words(text: str) -> set:
    return {w.strip(".-") for w in _WORD.findall((text or "").lower().replace("-", " ")) if w not in _STOP}


def install_pack(pack: str, src: Path, title: str, source: str, root: Path | None = None) -> int:
    """Copy every ``*/SKILL.md`` under ``src`` into the pack (text only) and write its index. Returns the count."""
    from skill_import import parse_skill_md

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,40}", pack):
        raise ValueError("Pack names are lowercase letters, digits and dashes.")
    target = (root or PACKS_DIR) / pack
    target.mkdir(parents=True, exist_ok=True)
    entries = []
    files = sorted(Path(src).glob("*/SKILL.md")) or sorted(Path(src).glob("SKILL.md"))
    for md in files:
        text = md.read_text(encoding="utf-8", errors="replace")[:MAX_SKILL_BYTES]
        name = re.sub(r"[^a-z0-9-]+", "-", md.parent.name.lower()).strip("-") or "skill"
        parsed = parse_skill_md(text, fallback_name=name)
        (target / f"{name}.md").write_text(text, encoding="utf-8")
        entries.append({"name": name, "title": parsed["name"], "description": parsed["description"][:400]})
    index = {"pack": pack, "title": title, "source": source, "installed": time.strftime("%Y-%m-%d"), "skills": entries}
    (target / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    with _lock:
        _cache["key"] = None
    return len(entries)


def _packs(root: Path | None = None) -> Dict[str, Dict[str, Any]]:
    base = root or PACKS_DIR
    indexes = sorted(base.glob("*/index.json")) if base.is_dir() else []
    key = (str(base), tuple((str(p), p.stat().st_mtime) for p in indexes))
    with _lock:
        if _cache["key"] == key:
            return _cache["packs"]
    packs: Dict[str, Dict[str, Any]] = {}
    for path in indexes:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in data.get("skills", []):
            entry["_name_words"] = _words(entry.get("name", ""))
            entry["_words"] = _words(entry.get("description", "")) | entry["_name_words"]
        packs[path.parent.name] = data
    with _lock:
        _cache.update(key=key, packs=packs)
    return packs


def list_packs(root: Path | None = None) -> List[Dict[str, Any]]:
    return [{"pack": name, "title": data.get("title", name), "source": data.get("source", ""),
             "count": len(data.get("skills", []))} for name, data in _packs(root).items()]


def search(query: str, limit: int = 5, root: Path | None = None) -> List[Dict[str, Any]]:
    """Best pack skills for a free-text query: name words count double, at least two words must match."""
    words = _words(query)
    if not words:
        return []
    results = []
    for pack, data in _packs(root).items():
        for entry in data.get("skills", []):
            score = 2 * len(words & entry["_name_words"]) + len(words & entry["_words"])
            if score >= 2:
                results.append({"id": f"pack:{pack}/{entry['name']}", "name": entry["name"], "pack": pack,
                                "description": entry.get("description", ""), "score": score})
    results.sort(key=lambda r: (-r["score"], r["name"]))
    return results[: max(1, limit)]


def read(skill_id: str, root: Path | None = None) -> Optional[str]:
    """The SKILL.md text for ``pack:<pack>/<name>`` (or ``<pack>/<name>``), or None."""
    match = re.fullmatch(r"(?:pack:)?([a-z0-9-]+)/([a-z0-9-]+)", (skill_id or "").strip().lower())
    if not match:
        return None
    pack, name = match.groups()
    path = (root or PACKS_DIR) / pack / f"{name}.md"
    if pack not in _packs(root) or not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "install":
        print(sys.argv[2], install_pack(sys.argv[2], Path(sys.argv[3]), sys.argv[4], sys.argv[5]))
    else:
        for row in list_packs():
            print(row)
