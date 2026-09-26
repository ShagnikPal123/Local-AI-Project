"""Find and use templates (Request S11). Writing is the only thing this does to disk, and only where asked.

``instantiate`` writes a files-template into ``<folder>/<name>/`` — the folder must already exist, every
path is checked to stay inside it, and nothing is overwritten. A tab template becomes a validated
dynamic tab; documents and prompts are returned as text (and written as a Markdown file when a folder is
given). Nothing is ever executed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from identity0.templates.catalog import TEMPLATES

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,59}$")


class TemplateError(ValueError):
    pass


def categories() -> List[str]:
    seen: List[str] = []
    for t in TEMPLATES:
        if t["category"] not in seen:
            seen.append(t["category"])
    return seen


def _summary(t: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: t[k] for k in ("id", "category", "kind", "title", "description", "tags")}
    if t["kind"] == "files":
        out["files"] = sorted(t["files"])
    return out


def search(query: str = "", *, category: str = "", limit: int = 100) -> List[Dict[str, Any]]:
    words = [w for w in re.findall(r"[a-z0-9+#]+", (query or "").lower()) if len(w) > 1]
    rows = []
    for t in TEMPLATES:
        if category and t["category"].lower() != category.lower():
            continue
        hay = " ".join([t["id"], t["title"], t["description"], " ".join(t["tags"])]).lower()
        score = sum(3 if w in t["tags"] else 1 for w in words if w in hay) if words else 1
        if score:
            rows.append((score, t))
    rows.sort(key=lambda pair: -pair[0])
    return [_summary(t) for _, t in rows[:limit]]


def get(template_id: str) -> Optional[Dict[str, Any]]:
    return next((dict(t) for t in TEMPLATES if t["id"] == template_id), None)


def best_for(request: str) -> Optional[Dict[str, Any]]:
    """The template a request most likely wants ("make me a portfolio website"), or None."""
    found = search(request, limit=1)
    return found[0] if found and any(w in request.lower() for w in found[0]["tags"]) else None


def _fill(text: str, name: str) -> str:
    return text.replace("{{name}}", name)


def instantiate(template_id: str, *, folder: str = "", name: str = "") -> Dict[str, Any]:
    template = get(template_id)
    if template is None:
        raise TemplateError("No template with that id.")
    given = (name or "").strip()
    if given and not _NAME.match(given):
        raise TemplateError("Use a simple name: letters, numbers, spaces, dots, dashes.")
    name = given or template_id.split("-")[0] + "-project"
    safe = re.sub(r"\s+", "-", name)
    if "python" in template["tags"]:
        safe = safe.replace("-", "_").replace(".", "_")  # a Python package name must be importable

    if template["kind"] == "tab":
        from dynamic_tabs import TAB_STORE, build_spec

        spec = template["spec"]
        created = TAB_STORE.create(build_spec(label=given or spec["label"], blocks=spec["blocks"], icon=spec["icon"],
                                              description=spec["description"], author="Big Kahuna", source="template"))
        return {"kind": "tab", "tab_id": created.tab_id, "label": created.label}

    if template["kind"] == "doc":
        text = _fill(template["text"], name)
        if not folder:
            return {"kind": "doc", "text": text}
        target_dir = _checked_folder(folder)
        target = target_dir / f"{safe}.md"
        if target.exists():
            raise TemplateError(f"{target.name} already exists there.")
        target.write_text(text, encoding="utf-8")
        return {"kind": "doc", "text": text, "written": str(target)}

    root = _checked_folder(folder) / safe
    if root.exists():
        raise TemplateError(f"{root.name} already exists in that folder.")
    planned: Dict[Path, str] = {}
    for rel, content in template["files"].items():
        rel_path = Path(_fill(rel, safe))
        if rel_path.is_absolute() or ".." in rel_path.parts:
            raise TemplateError("A template path tried to leave its folder.")
        target = (root / rel_path).resolve()
        if root.resolve() not in target.parents:
            raise TemplateError("A template path tried to leave its folder.")
        planned[target] = _fill(content, safe)
    for target, content in planned.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return {"kind": "files", "folder": str(root), "files": sorted(str(p.relative_to(root.resolve())) for p in planned)}


def _checked_folder(folder: str) -> Path:
    if not folder:
        raise TemplateError("Pick the folder to create it in.")
    path = Path(folder).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise TemplateError("That folder does not exist.")
    return path.resolve()
