"""Copy a Nyx skill into other AI assistants.

"Also copy for other AI like Opus, GPT Sol and Astra, Fable 5.1 and more." A
skill is plain instructions plus triggers, so it travels well — each assistant
just wants it in its own shape. Templates come from ``skill_export_templates.json``
(curated content) with built-in fallbacks so export works before that file exists.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from paths import project_path

_FALLBACK_FORMATS: List[Dict[str, str]] = [
    {
        "id": "claude",
        "label": "Claude (Opus 5 / Fable 5.1 / Sonnet 5) — SKILL.md",
        "filename": "{{slug}}/SKILL.md",
        "template": (
            "---\nname: {{slug}}\ndescription: {{description}} Use when: {{triggers_inline}}.\n---\n\n"
            "# {{name}}\n\n{{instructions}}\n\n## When to use\n{{triggers_bullets}}\n"
        ),
    },
    {
        "id": "openai",
        "label": "ChatGPT / custom GPT instructions",
        "filename": "{{slug}}-gpt-instructions.md",
        "template": (
            "# {{name}}\n\n{{description}}\n\n## Instructions\n{{instructions}}\n\n"
            "## Apply this when the user\n{{triggers_bullets}}\n"
        ),
    },
    {
        "id": "gemini",
        "label": "Gemini Gem (also Astra-style assistants)",
        "filename": "{{slug}}-gem.md",
        "template": (
            "Name: {{name}}\n\nInstructions:\nYou are a specialist in {{description_lower}}\n\n{{instructions}}\n\n"
            "Use this approach whenever the conversation involves: {{triggers_inline}}.\n"
        ),
    },
    {
        "id": "agents_md",
        "label": "AGENTS.md section (Codex, Cursor, Antigravity)",
        "filename": "AGENTS.md",
        "template": "## Skill: {{name}}\n\n{{description}}\n\n{{instructions}}\n\nTriggers: {{triggers_inline}}\n",
    },
    {
        "id": "generic",
        "label": "Portable prompt (any AI)",
        "filename": "{{slug}}.txt",
        "template": "{{name}} — {{description}}\n\n{{instructions}}\n\n(Use when: {{triggers_inline}})\n",
    },
]


def export_formats() -> List[Dict[str, str]]:
    try:
        raw = json.loads(project_path("skill_export_templates.json").read_text(encoding="utf-8"))
        formats = [f for f in raw.get("formats", []) if isinstance(f, dict) and f.get("id") and f.get("template")]
        if formats:
            return formats
    except (OSError, ValueError):
        pass
    return _FALLBACK_FORMATS


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "skill").lower()).strip("-")[:60] or "skill"


def render_skill(skill: Dict[str, Any], format_id: str) -> Tuple[str, str]:
    """Return (suggested filename, file content). KeyError for an unknown format."""
    fmt = next((f for f in export_formats() if f["id"] == format_id), None)
    if fmt is None:
        raise KeyError(format_id)
    triggers = [str(t) for t in skill.get("triggers", [])]
    description = str(skill.get("description") or skill.get("name") or "").strip()
    values = {
        "name": str(skill.get("name", "Skill")),
        "slug": _slug(str(skill.get("name", "skill"))),
        "description": description,
        "description_lower": description[:1].lower() + description[1:] if description else "",
        "instructions": str(skill.get("instructions", "")).strip(),
        "triggers_bullets": "\n".join(f"- {t}" for t in triggers) or "- (whenever it fits)",
        "triggers_inline": ", ".join(triggers) or "whenever it fits",
    }

    def fill(template: str) -> str:
        return re.sub(r"\{\{(\w+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)

    return fill(fmt.get("filename", "{{slug}}.md")), fill(fmt["template"])
