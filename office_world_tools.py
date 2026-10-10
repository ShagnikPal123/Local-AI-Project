"""Make an office or a world from normal chat (owner, 2026-10-10: "Have the ability to create office/world in normal
chat"). Both open beside the chat in the merged Office & World window; nothing here runs work by itself — an office
starts working when the owner (or Nyx, asked) gives it a job, exactly as from its own tab."""

from __future__ import annotations

from typing import Any


def _open(kind: str, **props: Any) -> None:
    try:
        from agent_events import publish_ui

        publish_ui("ui.open_window", kind=kind, title="Office & World", props=props or None)
    except Exception:  # noqa: BLE001
        pass


def tool_office_create(name: str = "", job: str = "") -> str:
    from office import library
    from office.api import say

    try:
        office, _directory = library.create_office(name.strip()[:80])
    except Exception as error:  # noqa: BLE001
        return f"Error: could not make the office: {error}"
    note = ""
    if job.strip():
        try:
            say(job.strip()[:4000], office_id=office.id)
            note = " and gave it the job"
        except Exception as error:  # noqa: BLE001
            note = f" (the job was not sent: {error})"
    _open("office")
    return f"Made the office '{office.name}'{note}. It is open beside the chat."


def tool_world_create(name: str = "", goal: str = "") -> str:
    from world.engine import ENGINE

    try:
        world = ENGINE.create(name=name.strip()[:80], goal=goal.strip()[:600])
    except Exception as error:  # noqa: BLE001
        return f"Error: could not make the world: {error}"
    _open("world")
    label = world.get("name") if isinstance(world, dict) else name
    return f"Made the world '{label or name}'. It is open beside the chat."


def register_office_world_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="office_create",
        description="Make a new office of agents (Office Space) from chat, optionally giving it its first job, and open "
                    "it beside the chat.",
        parameters=[ToolParam("name", "string", "Office name", required=False),
                    ToolParam("job", "string", "The first job for the office, if the owner gave one", required=False)],
        handler=tool_office_create, category="general", label="Making an office",
    )
    registry.register(
        name="world_create",
        description="Make a new World (an office grown into a planet that develops as its agents deliver) and open it "
                    "beside the chat.",
        parameters=[ToolParam("name", "string", "World name", required=False),
                    ToolParam("goal", "string", "What the world is for", required=False)],
        handler=tool_world_create, category="general", label="Making a world",
    )
