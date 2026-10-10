"""Tools that let the assistant reshape the workspace itself.

"Make it feel like a night sky", "give me a tab for my classes", "open settings",
"put my study notes next to the timer" — requests about Nyx's own interface.
Each tool changes validated data (the theme in ``ui_state``, tab specs in
``dynamic_tabs``) and announces it on the UI bus, so every open window updates
while the user watches. Nothing here generates or runs interface code.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

#: Built-in tabs the assistant can open by name.
CORE_TABS = {
    # Redesign 2026-10-10: merged tabs. Old ids (screen, store, dashboard, power, work, settings, games…) still open
    # their new home in the app (frontend src/tabs.ts REDIRECTS), so they stay listed for the model to use.
    "nyx": "Chat", "build": "Build", "research": "Research Lab", "learn": "Learn", "notes": "Notes",
    "code": "Code", "agents": "Agents", "collab": "Collab", "trading": "Trading", "improve": "Improve",
    "freewill": "Free Will", "kahuna": "Big Kahuna", "office": "Office & World", "world": "World",
    "equalize": "Equalize", "computer": "Computer", "connectors": "Connections", "admin": "Admin",
    "screen": "Screen Share", "absorb": "Data Absorption", "apply": "Apply", "subagents": "Sub-agents",
    "models": "Models", "keys": "Keys & Models", "store": "Add capability", "settings": "Settings",
    "dashboard": "Dashboard", "power": "Power", "work": "Sessions & Memory", "design_research": "Design Research",
    "games": "Game Studio",
}


def _publish(event_type: str, **payload: Any) -> None:
    try:
        from agent_events import publish_ui

        publish_ui(event_type, **payload)
    except Exception:
        pass


def _find_user_tab(name: str) -> Optional[Any]:
    from dynamic_tabs import TAB_STORE

    wanted = (name or "").strip().lower()
    tabs = TAB_STORE.list_tabs()
    for tab in tabs:
        if tab["id"].lower() == wanted or tab["label"].lower() == wanted:
            return TAB_STORE.get(tab["id"])
    for tab in tabs:
        if wanted and (wanted in tab["label"].lower() or tab["label"].lower() in wanted):
            return TAB_STORE.get(tab["id"])
    return None


# --- theme ----------------------------------------------------------------------


def tool_ui_set_theme(accent: str = "", accent2: str = "", background: str = "", surface: str = "",
                      nav: str = "", text: str = "", radius: Any = None, font: str = "", density: str = "",
                      motion: str = "", glass: Any = None, wallpaper: str = "", wallpaper_color: str = "") -> str:
    from ui_state import UI_STATE, ThemeError

    changes: Dict[str, Any] = {
        "accent": accent, "accent2": accent2, "background": background, "surface": surface, "nav": nav,
        "text": text, "radius": radius, "font": font, "density": density, "motion": motion, "glass": glass,
    }
    if wallpaper:
        changes["wallpaper"] = {"type": wallpaper, "value": wallpaper_color}
    changes = {k: v for k, v in changes.items() if v not in (None, "")}
    if not changes:
        return "Nothing to change — name at least one setting (accent, background, font, wallpaper…)."
    try:
        theme = UI_STATE.update_theme(changes)
    except ThemeError as error:
        return f"Error: {error}"
    applied = ", ".join(f"{k}={v}" for k, v in changes.items())
    return f"Theme updated live ({applied}). The user can say 'undo that' to go back. Current theme: {json.dumps(theme)}"


def tool_ui_reset_theme() -> str:
    from ui_state import UI_STATE

    UI_STATE.reset_theme()
    return "Theme reset to Nyx's default look."


def tool_ui_undo_theme() -> str:
    from ui_state import UI_STATE

    return "Reverted the last theme change." if UI_STATE.undo_theme() is not None else "There is no theme change to undo."


# --- tabs ------------------------------------------------------------------------


def tool_ui_list_tabs() -> str:
    from dynamic_tabs import TAB_STORE

    user = TAB_STORE.list_tabs()
    lines = ["Built-in tabs: " + ", ".join(CORE_TABS.values())]
    if user:
        lines.append("The user's own tabs:")
        for tab in user:
            blocks = ", ".join(f"{b['type']} '{b['title']}'" for b in tab["blocks"])
            lines.append(f"- {tab['label']} (id {tab['id']}): {tab['description']} — blocks: {blocks}")
    else:
        lines.append("The user has no tabs of their own yet.")
    return "\n".join(lines)


def tool_ui_open_tab(tab: str) -> str:
    wanted = (tab or "").strip().lower()
    for core_id, label in CORE_TABS.items():
        if wanted in (core_id, label.lower()):
            _publish("ui.open_tab", tab_id=core_id)
            return f"Opened the {label} tab."
    spec = _find_user_tab(tab)
    if spec is not None:
        _publish("ui.open_tab", tab_id=spec.tab_id)
        return f"Opened the {spec.label} tab."
    return f"No tab called {tab!r}. {tool_ui_list_tabs()}"


def _design_blocks(description: str) -> Dict[str, Any]:
    """Ask the model for a tab design when the caller gave only a description."""
    from agent_runtime import _router
    from dynamic_tabs import build_tab_prompt, parse_tab_reply

    prompt = build_tab_prompt(description)
    try:
        # Decide how this one should look before designing it, from the owner's own
        # past decisions rather than the model's average tab (Project Null N88).
        import design_sense

        prompt += "\n\n" + design_sense.brief_for_prompt(description)
    except Exception:  # pragma: no cover - a tab must still be makeable without the brief
        pass
    reply, _provider = _router().chat([{"role": "user", "content": prompt}])
    return parse_tab_reply(reply)


def tool_ui_create_tab(name: str, description: str = "", blocks: Any = None, accent: str = "", icon: str = "") -> str:
    from dynamic_tabs import TAB_STORE, TabSpecError, build_spec

    parsed_blocks: Optional[List[Dict[str, Any]]] = None
    if isinstance(blocks, str) and blocks.strip():
        try:
            parsed_blocks = json.loads(blocks)
        except ValueError:
            return 'Error: blocks must be JSON, e.g. [{"type": "checklist", "title": "Today", "config": {"items": ["a"]}}].'
    elif isinstance(blocks, list):
        parsed_blocks = blocks

    design: Dict[str, Any] = {}
    if not parsed_blocks:
        try:
            design = _design_blocks(f"{name}: {description}")
        except Exception as error:  # noqa: BLE001 - fall back to a sensible starter layout
            design = {"blocks": [{"type": "notes", "title": "Notes"}, {"type": "checklist", "title": "To do"}],
                      "note": str(error)}
        parsed_blocks = design.get("blocks", [])

    try:
        spec = build_spec(
            label=name or design.get("label", "New tab"),
            blocks=parsed_blocks,
            icon=icon or design.get("icon", "ph-squares-four"),
            description=description or design.get("description", ""),
            connectors=design.get("connectors", []),
            accent=accent,
            author="assistant",
            source="agent",
        )
    except TabSpecError as error:
        return f"Error: {error}"
    TAB_STORE.create(spec)
    _publish("tabs.changed", tab_id=spec.tab_id, action="created")
    _publish("ui.open_tab", tab_id=spec.tab_id)
    summary = ", ".join(f"{b.type.value} '{b.title}'" for b in spec.blocks)
    return f"Created and opened the '{spec.label}' tab with: {summary}."


def tool_ui_edit_tab(tab: str, instruction: str) -> str:
    from dynamic_tabs import TAB_STORE, TabSpecError
    from tab_editor import build_edit_prompt, interpret_locally, parse_edit_reply

    spec = _find_user_tab(tab)
    if spec is None:
        return f"No tab called {tab!r}. {tool_ui_list_tabs()}"
    changes = interpret_locally(spec, instruction)
    source = "local"
    if changes is None:
        source = "model"
        try:
            from agent_runtime import _router

            reply, _provider = _router().chat([{"role": "user", "content": build_edit_prompt(spec, instruction)}])
            changes = parse_edit_reply(reply)
        except TabSpecError as error:
            return f"Error: {error}"
        except Exception as error:  # noqa: BLE001
            return f"Error: could not work out that edit ({error})."
    try:
        updated = TAB_STORE.update(spec.tab_id, request=instruction, edit_source=f"assistant-{source}", **changes)
    except TabSpecError as error:
        return f"Error: {error}"
    summary = updated.edits[-1].summary if updated.edits and updated.edits[-1].request == instruction[:200] else ""
    _publish("tabs.changed", tab_id=updated.tab_id, action="edited")
    return f"Edited '{updated.label}': {summary or 'no visible change — it already looked like that'}."


def tool_ui_delete_tab(tab: str) -> str:
    from dynamic_tabs import TAB_STORE

    spec = _find_user_tab(tab)
    if spec is None:
        return f"No tab called {tab!r}."
    TAB_STORE.delete(spec.tab_id)
    _publish("tabs.changed", tab_id=spec.tab_id, action="deleted")
    return f"Deleted the '{spec.label}' tab."


def tool_ui_notify(message: str, level: str = "info") -> str:
    level = level if level in ("info", "ok", "warn", "error") else "info"
    _publish("notify", text=str(message)[:300], level=level)
    return "Shown to the user."


def register_landscape_tools(registry: Any) -> None:
    from dynamic_tabs import BLOCK_GUIDE, BlockType
    from tools import ToolParam

    color_hint = "A #rrggbb colour or a name like violet, teal, rose, gold"
    registry.register(
        name="ui_set_theme",
        description="Restyle Nyx's own interface live: colours, corner radius, font, density, motion, glass, wallpaper. "
                    "Only pass what should change.",
        parameters=[
            ToolParam("accent", "string", f"Main accent. {color_hint}", required=False),
            ToolParam("accent2", "string", "Secondary accent colour", required=False),
            ToolParam("background", "string", "Page background colour", required=False),
            ToolParam("surface", "string", "Card/panel colour", required=False),
            ToolParam("nav", "string", "Header/tab bar colour", required=False),
            ToolParam("text", "string", "Text colour", required=False),
            ToolParam("radius", "number", "Corner radius 0-24", required=False),
            ToolParam("font", "string", "Inter, System, Segoe UI, Roboto, Georgia, JetBrains Mono, Comic Neue", required=False),
            ToolParam("density", "string", "comfortable or compact", required=False, enum_values=["comfortable", "compact"]),
            ToolParam("motion", "string", "full, reduced or off", required=False, enum_values=["full", "reduced", "off"]),
            ToolParam("glass", "boolean", "Frosted-glass panels", required=False),
            ToolParam("wallpaper", "string", "none, gradient, orb, aurora or grid", required=False),
            ToolParam("wallpaper_color", "string", "Tint for the wallpaper", required=False),
        ],
        handler=tool_ui_set_theme,
        category="ui",
        label="Restyling the workspace",
    )
    registry.register(name="ui_reset_theme", description="Put Nyx's look back to the default theme.",
                      parameters=[], handler=tool_ui_reset_theme, category="ui", label="Resetting the theme")
    registry.register(name="ui_undo_theme", description="Undo the last theme change.",
                      parameters=[], handler=tool_ui_undo_theme, category="ui", label="Undoing the theme change")
    registry.register(name="ui_list_tabs", description="List Nyx's built-in tabs and the user's own tabs with their blocks.",
                      parameters=[], handler=tool_ui_list_tabs, category="general", label="Looking at the tabs")
    registry.register(
        name="ui_open_tab", description="Switch the user's view to a tab (built-in or their own).",
        parameters=[ToolParam("tab", "string", "Tab name or id, e.g. Settings, Agents, or a user tab name")],
        handler=tool_ui_open_tab, category="ui", label=lambda a: f"Opening {a.get('tab', '')}",
    )
    registry.register(
        name="ui_create_tab",
        description="Create a new tab in Nyx and open it. Give blocks as JSON for full control, or just a "
                    "description and it will be designed for you. Block types: "
                    + ", ".join(b.value for b in BlockType) + ". " + BLOCK_GUIDE,
        parameters=[
            ToolParam("name", "string", "Tab name (max 40 characters)"),
            ToolParam("description", "string", "What the tab is for", required=False),
            ToolParam("blocks", "array", "Optional JSON list of {type, title, config}", required=False),
            ToolParam("accent", "string", "Optional #rrggbb accent", required=False),
            ToolParam("icon", "string", "Optional Phosphor icon like ph-book", required=False),
        ],
        handler=tool_ui_create_tab, category="ui", label=lambda a: f"Creating the {a.get('name', 'new')} tab",
    )
    registry.register(
        name="ui_edit_tab", description="Change one of the user's tabs by describing the change.",
        parameters=[ToolParam("tab", "string", "Tab name or id"), ToolParam("instruction", "string", "The change")],
        handler=tool_ui_edit_tab, category="ui", label=lambda a: f"Editing {a.get('tab', 'a tab')}: {str(a.get('instruction', ''))[:50]}",
    )
    registry.register(
        name="ui_delete_tab", description="Delete one of the user's own tabs (built-in tabs cannot be deleted).",
        parameters=[ToolParam("tab", "string", "Tab name or id")],
        handler=tool_ui_delete_tab, category="ui", label=lambda a: f"Deleting the {a.get('tab', '')} tab",
    )
    registry.register(
        name="ui_notify", description="Show the user a brief notification toast in the app.",
        parameters=[ToolParam("message", "string", "Text to show"),
                    ToolParam("level", "string", "info, ok, warn or error", required=False)],
        handler=tool_ui_notify, category="ui", label="Notifying you",
    )
