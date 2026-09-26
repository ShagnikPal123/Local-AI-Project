"""The only things an office agent can actually do.

A worker writes and reads files **inside its own office folder**, looks something up on the web, talks to
another agent, hands a piece of work to a teammate, asks for a new teammate, and keeps a note in the office's
memory. That is the entire surface — deliberately. Hundreds of agents with the whole tool registry between them
is not an office, it is an incident; and this repo's rule stands: nothing here executes anything a model wrote.

The call syntax is the one every Nyx model already knows::

    <tool_call>
    name: write_file
    arguments: {"path": "plan.md", "content": "# Plan\\n..."}
    </tool_call>

Paths are sanitised to the office's ``work/`` folder (``..`` and drive letters cannot escape it), files are
capped, and a linked folder's offices can be read through ``linked/<office name>/<path>`` — read-only, because
one office writing into another's work is how linked work flows would become unexplainable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_FILE_BYTES = 400_000
MAX_OFFICE_BYTES = 40_000_000
MAX_TOOL_RESULT = 4000
_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9 ._()\[\]#&+-]")


@dataclass
class ToolSpec:
    name: str
    args: str
    what: str
    for_roles: Tuple[str, ...] = ()


TOOLS: List[ToolSpec] = [
    ToolSpec("write_file", '{"path": "notes/plan.md", "content": "..."}',
             "Save a file in this office's work folder. This is how you hand over anything longer than a note."),
    ToolSpec("read_file", '{"path": "notes/plan.md"}',
             "Read a file from this office's work folder (or linked/<office>/<path> from a linked office)."),
    ToolSpec("list_files", '{"folder": ""}', "See what the office has produced so far."),
    ToolSpec("search_web", '{"query": "..."}', "Look something up online when your answer depends on current facts."),
    ToolSpec("read_link", '{"url": "https://..."}', "Read one public page you found."),
    ToolSpec("message", '{"to": "Coder #2 | the Backend section | managers", "text": "..."}',
             "Say something to another agent, a section, or a kind of agent. They see it on their next step."),
    ToolSpec("delegate", '{"to": "Coder #2 | reviewer", "task": "short title", "detail": "everything they need"}',
             "Hand a piece of your work to a teammate who is better placed to do it."),
    ToolSpec("hire", '{"role": "data engineer", "why": "...", "long_term": "...", "count": 1, "clone_of": ""}',
             "Ask for another agent. Say why, and whether the office will keep needing it."),
    ToolSpec("recall", '{"query": "..."}', "Ask the office what it already knows about this."),
    ToolSpec("note", '{"text": "..."}', "Keep one fact or decision in the office's memory for future sessions."),
]


def describe(*, allow_web: bool = True) -> str:
    """The tool list as it appears in an agent's prompt."""
    lines = ["Use a tool by writing exactly:", "<tool_call>", "name: tool_name",
             'arguments: {"key": "value"}', "</tool_call>",
             "The result comes back to you and you continue. Tools:"]
    for tool in TOOLS:
        if not allow_web and tool.name in ("search_web", "read_link"):
            continue
        lines.append(f"- {tool.name} {tool.args} — {tool.what}")
    lines.append("When you have finished, write your report as plain text with no tool call: what you did, what "
                 "you produced (name the files), and anything you could not do and why.")
    return "\n".join(lines)


def safe_relative(path: str) -> str:
    """A path that cannot leave the office's work folder, keeping the shape the agent asked for."""
    raw = str(path or "").replace("\\", "/").strip().strip("/")
    parts: List[str] = []
    for segment in raw.split("/"):
        segment = segment.strip()
        if not segment or segment in (".", ".."):
            continue
        if re.fullmatch(r"[A-Za-z]:", segment):
            continue
        parts.append(_SAFE_SEGMENT.sub("_", segment)[:80])
    return "/".join(parts[:8]) or "untitled.md"


def _folder_size(folder: Path) -> int:
    total = 0
    try:
        for item in folder.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        pass
    return total


class Toolbox:
    """One agent's tools for one task. Every call returns a string the agent reads next."""

    def __init__(self, engine: Any, office: Any, agent: Any, task: Any = None, *, allow_web: bool = True) -> None:
        self.engine = engine
        self.office = office
        self.agent = agent
        self.task = task
        self.allow_web = allow_web
        self.files: List[str] = []
        self.used: List[str] = []

    # --- files ---------------------------------------------------------------

    def _work_dir(self) -> Path:
        from office import library

        return library.work_dir(self.office.id)

    def write_file(self, path: str = "", content: str = "", **_extra: Any) -> str:
        relative = safe_relative(path)
        body = str(content or "")
        if not body.strip():
            return "Nothing was written: content was empty."
        data = body.encode("utf-8")[:MAX_FILE_BYTES]
        work = self._work_dir()
        if _folder_size(work) + len(data) > MAX_OFFICE_BYTES:
            return ("This office has used all the room it is allowed on disk. Summarise instead of writing "
                    "another file, or ask the owner to clear the work folder.")
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if relative not in self.files:
            self.files.append(relative)
        self.engine.on_file_written(self.office, self.agent, relative)
        return f"Saved work/{relative} ({len(data)} bytes)."

    def read_file(self, path: str = "", **_extra: Any) -> str:
        raw = str(path or "").replace("\\", "/").strip().strip("/")
        if raw.lower().startswith("linked/"):
            return self._read_linked(raw[len("linked/"):])
        target = self._work_dir() / safe_relative(raw)
        if not target.exists() or not target.is_file():
            return f"There is no file at work/{safe_relative(raw)} yet."
        try:
            return target.read_text(encoding="utf-8", errors="replace")[:MAX_TOOL_RESULT]
        except OSError as error:
            return f"Could not read that file: {error}"

    def _read_linked(self, rest: str) -> str:
        from office import library

        name, _, inner = rest.partition("/")
        sibling = next((s for s in library.linked_siblings(self.office.id)
                        if s.name.lower() == name.strip().lower()), None)
        if sibling is None:
            names = ", ".join(s.name for s in library.linked_siblings(self.office.id)) or "none"
            return f"No linked office called {name!r}. Linked offices: {names}."
        target = Path(sibling.path) / "work" / safe_relative(inner)
        if not target.exists() or not target.is_file():
            return f"{sibling.name} has no file at work/{safe_relative(inner)}."
        try:
            return target.read_text(encoding="utf-8", errors="replace")[:MAX_TOOL_RESULT]
        except OSError as error:
            return f"Could not read that file: {error}"

    def list_files(self, folder: str = "", **_extra: Any) -> str:
        work = self._work_dir()
        base = work / safe_relative(folder) if folder else work
        if not base.exists():
            return "The work folder is empty so far."
        rows: List[str] = []
        try:
            for item in sorted(base.rglob("*"))[:120]:
                if item.is_file():
                    rows.append(f"- {item.relative_to(work).as_posix()} ({item.stat().st_size} bytes)")
        except OSError:
            pass
        return "\n".join(rows) if rows else "The work folder is empty so far."

    # --- the world outside ---------------------------------------------------

    def search_web(self, query: str = "", **_extra: Any) -> str:
        if not self.allow_web:
            return "Web access is switched off for this office."
        return self._call_nyx_tool("search_web", query=str(query or "")[:300])

    def read_link(self, url: str = "", **_extra: Any) -> str:
        if not self.allow_web:
            return "Web access is switched off for this office."
        return self._call_nyx_tool("open_link", url=str(url or "")[:500])

    @staticmethod
    def _call_nyx_tool(name: str, **kwargs: Any) -> str:
        try:
            from tools import TOOL_REGISTRY

            if name not in TOOL_REGISTRY.tools:
                return f"{name} is not available on this install."
            return str(TOOL_REGISTRY.call_tool(name, **kwargs))[:MAX_TOOL_RESULT]
        except Exception as error:  # noqa: BLE001 - a failing tool is a result, not a crash
            return f"{name} failed: {type(error).__name__}: {str(error)[:200]}"

    # --- the office ----------------------------------------------------------

    def message(self, to: str = "", text: str = "", **_extra: Any) -> str:
        return self.engine.agent_message(self.office, self.agent, str(to or ""), str(text or ""))

    def delegate(self, to: str = "", task: str = "", detail: str = "", **_extra: Any) -> str:
        return self.engine.agent_delegate(self.office, self.agent, str(to or ""), str(task or ""),
                                          str(detail or ""), parent=self.task)

    def hire(self, role: str = "", why: str = "", long_term: str = "", count: Any = 1, clone_of: str = "",
             **_extra: Any) -> str:
        try:
            number = max(1, min(8, int(count or 1)))
        except (TypeError, ValueError):
            number = 1
        return self.engine.agent_hire(self.office, self.agent, role=str(role or ""), why=str(why or ""),
                                      long_term=str(long_term or ""), count=number, clone_of=str(clone_of or ""))

    def recall(self, query: str = "", **_extra: Any) -> str:
        from office import memory

        rows = memory.recall(self.office.id, str(query or ""), limit=5)
        if not rows:
            return "The office has nothing on that yet."
        return "\n".join(f"- {r['kind']}{' (from ' + r['from'] + ')' if r.get('from') else ''}: {r['text'][:300]}"
                         for r in rows)

    def note(self, text: str = "", **_extra: Any) -> str:
        from office import memory

        entry = memory.add(self.office.id, str(text or ""), kind="note", by=self.agent.name,
                           job_id=getattr(self.task, "job_id", ""))
        return "Kept in the office's memory." if entry else "Nothing to keep."

    # --- dispatch ------------------------------------------------------------

    def run(self, name: str, arguments: Dict[str, Any]) -> str:
        handler: Optional[Callable[..., str]] = getattr(self, name, None) if name in {t.name for t in TOOLS} else None
        if handler is None:
            known = ", ".join(t.name for t in TOOLS)
            return f"There is no tool called {name!r}. You can use: {known}."
        self.used.append(name)
        try:
            clean = {str(k): v for k, v in (arguments or {}).items()}
            return str(handler(**clean))[:MAX_TOOL_RESULT]
        except TypeError as error:
            return f"{name} was called with the wrong arguments ({error}). Expected: " \
                   f"{next(t.args for t in TOOLS if t.name == name)}"
        except Exception as error:  # noqa: BLE001
            return f"{name} failed: {type(error).__name__}: {str(error)[:200]}"


def parse_calls(text: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Tool calls in a reply, using Nyx's own lenient parser (Windows paths, unclosed blocks and all)."""
    try:
        from tools import TOOL_REGISTRY

        return [(name, args) for name, args in TOOL_REGISTRY.parse_tool_calls(text or "")]
    except Exception:  # noqa: BLE001 - never let a parser problem end an agent's turn
        return []
