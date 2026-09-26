"""Chat tools for Big Kahuna, so Nyx can use its own main brain while talking (Request S).

``kahuna_collaborate`` is "contact and collaborate with multiple AI models" on demand: the question goes
to several members at once and their answers come back side by side for the model to combine.
Templates are found and used through ``kahuna_templates``; files are written only into a folder the
owner named. Nothing here runs code.
"""

from __future__ import annotations

from typing import Any, List


def _router() -> Any:
    from identity0.provider import shared_router

    return shared_router()


def tool_kahuna_status() -> str:
    from identity0 import competence, provider

    router = _router()
    status = provider.status(router)
    members = ", ".join(m["id"] for m in status["members"]) or "none reachable"
    stages = {}
    for domain, info in status["domains"].items():
        stages.setdefault(info["stage"], []).append(domain)
    try:
        from identity0.model import registry

        current = registry.current()
    except Exception:  # noqa: BLE001
        current = None
    line = (f"Big Kahuna (Identity 0) is {'leading every chat' if status['available'] else 'not leading right now'}. "
            f"Members: {members}. Stages: " + "; ".join(f"{k}: {', '.join(v)}" for k, v in stages.items()) + ". ")
    line += (f"Own model: {current['version']} ({current.get('params') or 0:,} parameters)." if current
             else "Own model: not trained yet.")
    graduated = [d for d, g in competence.table()["graduated"].items() if g]
    if graduated:
        line += f" It leads on its own in: {', '.join(graduated)}."
    return line


def tool_kahuna_collaborate(question: str, members: str = "", count: int = 3) -> str:
    from identity0 import collab, members as members_module

    router = _router()
    pool = members_module.available(router) if router is not None else []
    wanted = [m.strip() for m in (members or "").split(",") if m.strip()]
    chosen: List[str] = [m.id for m in pool if not wanted or any(w in m.id for w in wanted)]
    chosen = [m for m in chosen if not m.startswith("self:")][:max(1, min(int(count or 3), 5))]
    if not chosen:
        return "No model is reachable to collaborate with right now."
    result = collab.panel([{"role": "user", "content": question}], chosen, budget_s=45, max_tokens=700)
    parts = [f"[{a['member']}]\n{a['text'][:1800]}" if a["ok"] else f"[{a['member']}] did not answer ({a['error'][:80]})"
             for a in result["answers"]]
    return "Answers from the collaborating models (combine what is right):\n\n" + "\n\n".join(parts)


def tool_kahuna_templates(query: str = "", use: str = "", folder: str = "", name: str = "") -> str:
    from identity0 import templates

    if use:
        try:
            made = templates.instantiate(use, folder=folder, name=name)
        except templates.TemplateError as error:
            return f"Could not use that template: {error}"
        if made["kind"] == "files":
            return f"Created {made['folder']} with {len(made['files'])} files: {', '.join(made['files'][:12])}."
        if made["kind"] == "tab":
            return f"Made the tab “{made['label']}”."
        return made.get("text", "")
    found = templates.search(query, limit=8)
    if not found:
        return "No template matches that."
    return "\n".join(f"- {t['id']}: {t['title']} ({t['category']}) — {t['description']}" for t in found)


def tool_kahuna_suggest_tabs() -> str:
    from identity0 import tabs

    found = tabs.refresh()
    if not found:
        return "No new tab suggestions — nothing you ask about often is missing a tab."
    return "\n".join(f"- {p['title']}: {p['why']} (id {p['id']})" for p in found)


def register_identity0_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register("kahuna_status", "Report what Big Kahuna (Identity 0, Nyx's main brain) is doing: which models it works with, "
                      "the stage per area (collaborate / twin / solo) and its own model.", [], tool_kahuna_status,
                      category="general", label="Checking Big Kahuna")
    registry.register("kahuna_collaborate", "Ask several AI models the same question at once (local and cloud) and get their answers "
                      "side by side, to combine into the best answer. Use for hard or important questions.",
                      [P("question", "string", "The question to put to the models"),
                       P("members", "string", "Optional comma-separated model names to include (e.g. ollama, nvidia)", required=False),
                       P("count", "number", "How many models (default 3, max 5)", required=False)],
                      tool_kahuna_collaborate, category="general", label="Asking several models")
    registry.register("kahuna_templates", "Find a starter template (code projects, websites, DevOps, documents, tabs, prompts) or use one. "
                      "To use: give `use` = template id and `folder` = an existing folder the owner named.",
                      [P("query", "string", "What to look for, e.g. 'react app' or 'resume'", required=False),
                       P("use", "string", "Template id to create", required=False),
                       P("folder", "string", "Existing folder to create it in (absolute path)", required=False),
                       P("name", "string", "Project or tab name", required=False)],
                      tool_kahuna_templates, category="files.write", label="Looking at templates")
    registry.register("kahuna_suggest_tabs", "List the tabs Big Kahuna thinks the owner needs, from what they ask about often.",
                      [], tool_kahuna_suggest_tabs, category="ui", label="Thinking about useful tabs")
