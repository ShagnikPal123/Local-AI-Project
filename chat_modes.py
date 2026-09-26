"""Three ways the chat can work, chosen by the slider under the composer (Project Null N82–N84).

The owner: "Make a new slider at the bottom of the chat. Here there are 3 different
types. 1 is for normal where it chats and make sure the chat is better and faster.
As it thinks it can talk and list it out as it thinks it. Basically just much faster.
2. Co work is basically the same to Claude cowork where it works at the same time and
works in the background. 3. Is plan mode. In here it first makes a script/spec list and
makes questions and makes a scheme and ask the user to check it. After the user approves
or adds more it confirms and starts working. Basically a better confirm."

* **normal** — the quick conversation. The slow extras (prompt refining, second
  opinions from other models) are skipped, the quick path is preferred, and the
  model is asked to think out loud in short lines so the thinking appears as a
  live list instead of a silent wait.
* **cowork** — it works while you carry on. The turn already runs on a worker
  thread, so what this adds is the working temperament: keep going without
  checking in, keep a visible checklist (``update_checklist``), finish with what
  was done. The chat panel sends these alongside instead of queueing them.
* **plan** — nothing is done yet. It writes a spec list, the questions it needs
  answered and the scheme it would follow, and stops. Tools that change anything
  are refused for that turn, so "plan" cannot quietly act. When the owner presses
  Approve (adding to it if they like) the next turn arrives as ``plan_go`` with
  the approved plan, and that one works.

Everything here is a per-turn note plus a few switches; no model call and no state.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

MODES = ("normal", "cowork", "plan", "plan_go")
DEFAULT = "normal"

#: Marks this turn's mode note in the conversation history, so the next turn can replace it.
PREFIX = "[How this chat is working]"

#: Tool categories a planning turn may use: reading and looking things up, nothing else.
PLAN_CATEGORIES = frozenset({"web", "general", "learning", "research"})
PLAN_TOOLS = frozenset({
    "search_web", "fetch_webpage", "open_link", "read_handoff", "brain_recall", "known_concepts",
    "file_excerpt", "read_document", "list_files", "file_info", "search_files", "notes_search",
    "notes_read", "list_model_roles", "trading_status", "trading_signal", "research_status",
})
#: Never in a planning turn, whatever their category says.
PLAN_BLOCKED = frozenset({"run_command", "run_python", "write_file", "delete_file", "move_file", "copy_file",
                          "improve_self", "self_patch", "trading_order", "send_email", "email_reply",
                          "create_tab", "update_tab", "set_background", "click", "type_text", "press_keys"})


NORMAL_NOTE = (
    f"{PREFIX} Normal — a quick conversation.\n"
    "Answer fast and plainly. Think out loud while you work: put each step on its own short line inside "
    "<thinking>…</thinking> as you have it (\"checking the file\", \"comparing the two numbers\"), so the person "
    "sees the list grow instead of waiting. Keep those lines to a handful of words. Start writing the answer as "
    "soon as you can and keep it short unless they asked for depth; offer the longer version instead of writing it."
)

COWORK_NOTE = (
    f"{PREFIX} Co-work — you are working alongside them in the background.\n"
    "They are getting on with something else and will read this later, so do not stop to ask unless you are "
    "genuinely blocked; choose the sensible option, say which you chose, and carry on. Use the tools to actually "
    "do the work rather than describing it. Keep the checklist current with update_checklist as you go — set the "
    "items once at the start, then mark each one done when it is. Finish with what you did, anything you decided "
    "for them, where the result is, and what is left."
)

PLAN_NOTE = (
    f"{PREFIX} Plan — do not do the work yet.\n"
    "This turn produces a plan for them to check. You may look things up and read, but nothing may change: no "
    "writing, running, sending, ordering or editing. Answer with one ```plan block (JSON) and nothing else "
    "after it:\n"
    "```plan\n"
    "{\n"
    '  "goal": "one sentence on what they get at the end",\n'
    '  "spec": ["each thing the result must do — short, checkable, one per line"],\n'
    '  "steps": [{"title": "the step", "detail": "how, and with what", "minutes": 5}],\n'
    '  "questions": [{"question": "what you need decided", "options": [{"label": "…", "means": "what picking this '
    'leads to", "recommended": true}], "multi": false}],\n'
    '  "risks": ["what could go wrong or is unknown"],\n'
    '  "assumptions": ["what you are taking as given unless they say otherwise"]\n'
    "}\n"
    "```\n"
    "Ask only questions whose answer changes the plan — at most three, each with two to four options and what each "
    "option means. Write a spec list they can tick through, not prose. Keep any text before the block to one line."
)

PLAN_GO_NOTE = (
    f"{PREFIX} Plan approved — now do it.\n"
    "The plan below is what they approved, including any changes they made and their answers. Follow it, in order, "
    "and keep the checklist current with update_checklist. If something in the plan turns out to be wrong, say so "
    "in the answer rather than silently doing something else. Finish with what was done against each spec line."
)


def normalize(mode: Optional[str]) -> str:
    text = str(mode or "").strip().lower().replace("-", "_")
    if text in ("plan_approved", "plango", "plan_start"):
        return "plan_go"
    if text in ("co_work", "coworking", "background"):
        return "cowork"
    return text if text in MODES else DEFAULT


def settings_for(mode: Optional[str]) -> Dict[str, Any]:
    """The switches a turn reads: what to skip, how many tool steps, whether tools are gated."""
    mode = normalize(mode)
    if mode == "cowork":
        return {"mode": mode, "skip_optimizer": False, "skip_consult": False, "max_steps": 48,
                "force_full": True, "read_only": False, "checklist": True}
    if mode == "plan":
        return {"mode": mode, "skip_optimizer": True, "skip_consult": False, "max_steps": 8,
                "force_full": True, "read_only": True, "checklist": False}
    if mode == "plan_go":
        return {"mode": mode, "skip_optimizer": True, "skip_consult": True, "max_steps": 48,
                "force_full": True, "read_only": False, "checklist": True}
    return {"mode": mode, "skip_optimizer": True, "skip_consult": True, "max_steps": 16,
            "force_full": False, "read_only": False, "checklist": False}


def note_for(mode: Optional[str]) -> str:
    return {"cowork": COWORK_NOTE, "plan": PLAN_NOTE, "plan_go": PLAN_GO_NOTE}.get(normalize(mode), NORMAL_NOTE)


def plan_guard(inner: Optional[Callable[[str, str], None]] = None) -> Callable[[str, str], None]:
    """A gate for a planning turn: it may read and look up, never change anything.

    Wraps any gate the conversation already has (the Free Will tab's), so a mode
    can only ever narrow what is allowed, never widen it.
    """

    def guard(name: str, category: str) -> None:
        from permissions import PermissionDenied

        if inner is not None:
            inner(name, category)
        if name in PLAN_BLOCKED or not (name in PLAN_TOOLS or (category or "general") in PLAN_CATEGORIES):
            raise PermissionDenied(
                f"Blocked in Plan mode: {name} would change something, and this turn only writes the plan. "
                "Put it in the plan as a step instead — it runs once they approve.")

    return guard


def prepare(service: Any, mode: Optional[str]) -> Dict[str, Any]:
    """Put the mode's note into this turn's context and hand back its switches.

    Called once at the top of a turn. The note replaces the previous turn's, so a
    chat that changes mode does not carry the old temperament with it.
    """
    switches = settings_for(mode)
    history = getattr(service, "conversation_history", None)
    if isinstance(history, list):
        service.conversation_history = [
            m for m in history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(PREFIX))
        ]
        # Every mode gets its note, including normal: "think out loud, answer fast" is
        # what makes the normal chat feel different from the old default.
        service.conversation_history.append({"role": "system", "content": note_for(switches["mode"])})
    if switches["read_only"]:
        service.tool_guard = plan_guard(getattr(service, "tool_guard", None))
    return switches


# ---------------------------------------------------------------------------
# The checklist a co-work turn keeps in front of the owner
# ---------------------------------------------------------------------------


def _clean_items(items: Any) -> List[Dict[str, str]]:
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except ValueError:
            items = [line.strip("-• ").strip() for line in items.splitlines() if line.strip()]
    cleaned: List[Dict[str, str]] = []
    for item in list(items or [])[:20]:
        if isinstance(item, str):
            text, status = item, "todo"
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("title") or item.get("step") or "").strip()
            status = str(item.get("status") or "todo").strip().lower()
        else:
            continue
        if not text:
            continue
        if status not in ("todo", "doing", "done", "skipped", "blocked"):
            status = "todo"
        cleaned.append({"text": text[:160], "status": status})
    return cleaned


def tool_update_checklist(items: Any = None) -> str:
    """Show the owner what this piece of work is made of, and how far it has got."""
    from tool_context import current

    cleaned = _clean_items(items)
    if not cleaned:
        return "Give the checklist as a list of items, each {\"text\": \"…\", \"status\": \"todo|doing|done\"}."
    context = current()
    if context is not None:
        context.emit("checklist", items=cleaned)
    done = sum(1 for item in cleaned if item["status"] == "done")
    return (f"Checklist shown to the owner ({done}/{len(cleaned)} done). Keep it current: call this again when a "
            "step starts and when it finishes.")


def register_chat_mode_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        "update_checklist",
        "Show or update the checklist for the work you are doing now (Co-work and approved plans). "
        "Call it once with every step as todo, then again as each one starts (doing) and finishes (done).",
        [ToolParam("items", "array", "The whole list, in order: [{\"text\": \"…\", \"status\": \"todo|doing|done|blocked|skipped\"}]")],
        tool_update_checklist,
        category="general",
        label=lambda a: "Updating the checklist",
    )
