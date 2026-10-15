"""Chat tools for Nyx's own memory and model: recall, remember, study a folder, report growth."""

from __future__ import annotations

from typing import Any


def tool_brain_recall(query: str, limit: int = 6) -> str:
    import super_brain

    memories = super_brain.BRAIN.recall(query, limit=max(1, min(int(limit or 6), 15)))
    if not memories:
        return "Nothing in Nyx's memory matches that yet."
    return "\n".join(f"- ({m['source']}) {m['text'][:400]}" for m in memories)


def tool_brain_remember(text: str, source: str = "files") -> str:
    import avatars
    import super_brain

    avatar_id = avatars._current_avatar_id()
    if avatar_id:
        # An avatar's memories go to its own bank, never the brain every other chat reads (persona_scope.py).
        avatars.add_note(avatar_id, str(text or "")[:400])
        return "Remembered in your own notes (only you read them)."

    super_brain.BRAIN.ingest(text, source=source or "files", kind="remembered")
    return "Remembered — it's in the super brain now."


def _truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "1", "keep", "on")


def tool_save_memory(topic: str, content: str, keep: Any = False, why: str = "") -> str:
    """Save a lasting memory (Settings > Memory lists them with their id and date)."""
    import avatars
    from memory import MemoryStore

    avatar_id = avatars._current_avatar_id()
    if avatar_id:
        # Same rule as brain_remember: an avatar never writes the memory every other chat reads.
        avatars.add_note(avatar_id, f"{topic}: {content}"[:400])
        return "Remembered in your own notes (only you read them)."
    try:
        entry = MemoryStore().remember_important(topic, content, source="chat", keep=_truthy(keep), keep_reason=why or "")
    except ValueError as error:
        return f"Error: {error}"
    kept = " and marked to keep long term" if entry["keep"] else ""
    return f"Saved as memory {entry['id']}{kept}. It is in Settings > Memory to see or edit."


def tool_forget_memory(ref: str) -> str:
    """Remove one lasting memory by its id or topic."""
    from memory import MemoryStore

    return "Forgotten." if MemoryStore().remove_important(ref) else f"No memory found for {ref}."


def tool_brain_study_folder(path: str) -> str:
    import super_brain
    from pathlib import Path

    folder = Path(path).expanduser()
    if not folder.is_dir():
        return f"Error: {folder} is not a folder."
    state = super_brain.BRAIN.seed(["folder"], folder=str(folder))
    return (f"Studying {folder} in the background (text, notes and code files; up to 20,000). "
            f"Watch the Brain grow on the Nyx tab.{' Already studying something else.' if state.get('current') not in ('', 'folder') else ''}")


def tool_nyx_core_status() -> str:
    import nyx_core
    import super_brain

    snap = nyx_core.CORE.snapshot()
    brain = super_brain.BRAIN.counts()
    parts = ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in snap["parts"].items())
    accuracy = f"{snap['domain_accuracy']:.0%}" if snap["domain_accuracy"] is not None else "not measured yet"
    return (f"Nyx Core is level {snap['level']} “{snap['name']}” ({snap['parameters']:,} learned parameters — about {snap['like']}). "
            f"Parts: {parts}. Network {snap['widths']} after {snap['examples']} turns; domain accuracy {accuracy}. "
            f"Answers from its own memory: {snap['independence']:.0%}. Super brain: {brain['nodes']:,} nodes, {brain['edges']:,} links.")


def register_intelligence_tools(registry: Any) -> None:
    from tools import ToolParam as P

    registry.register("brain_recall", "Search Nyx's super brain (everything it has read, said and learned) for memories about a topic.",
                      [P("query", "string", "What to recall"), P("limit", "number", "How many memories (default 6)", required=False)],
                      tool_brain_recall, category="memory", label=lambda a: f"Remembering: {str(a.get('query', ''))[:40]}")
    registry.register("brain_remember", "Store something in the super brain so Nyx remembers it later.",
                      [P("text", "string", "What to remember"),
                       P("source", "string", "chat, web, files, code, knowledge, design, email…", required=False)],
                      tool_brain_remember, category="memory", label="Remembering this")
    registry.register("save_memory", "Save a lasting fact about the owner when they say 'remember this' or share something worth keeping. "
                      "It gets an id and the date. Set keep=true (with why) when they want it kept for the long term.",
                      [P("topic", "string", "A short name for it, e.g. 'favourite editor'"),
                       P("content", "string", "The fact itself, in one or two sentences"),
                       P("keep", "boolean", "true when it is meant to be kept long term", required=False),
                       P("why", "string", "Why it is worth keeping", required=False)],
                      tool_save_memory, category="memory", label=lambda a: f"Saving memory: {str(a.get('topic', ''))[:40]}")
    registry.register("forget_memory", "Forget one saved memory by its id (mem_…) or topic, when the owner asks.",
                      [P("ref", "string", "The memory id or topic")], tool_forget_memory, category="memory", label="Forgetting a memory")
    registry.register("brain_study_folder", "Read a whole folder into the super brain in the background (when the owner asks Nyx to study or learn their files).",
                      [P("path", "string", "Folder path")], tool_brain_study_folder, category="files.read",
                      label=lambda a: f"Studying {str(a.get('path', ''))[:40]}")
    registry.register("nyx_core_status", "Report how far Nyx's own model has grown: level, parameters, network size, accuracy, independence from API models.",
                      [], tool_nyx_core_status, category="general", label="Checking my own growth")
