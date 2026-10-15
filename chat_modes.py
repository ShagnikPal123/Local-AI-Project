"""The ways the chat can work, chosen by the slider under the composer (Project Null N82–N84, Update 1 U6).

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
* **swarm** — many agents at once (Update 1, U5/U6; the owner: "This can be a mode
  similar to normal, cowork, and plan, also add swarm and auto to this mix"). The
  job is split into independent parts and handed to a swarm through
  ``dispatch_agents``, as many as the owner's slider allows (``swarm.py``), then
  the reports are merged into one answer.
* **auto** — picks one of the above for each message (``choose``), from the words
  alone, and says which it picked and why. A planning-sounding request gets Plan,
  so Auto can never act on something the owner only asked to have thought through.

Everything here is a per-turn note plus a few switches; no model call and no state.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

MODES = ("normal", "cowork", "plan", "plan_go", "swarm", "auto", "ultrafast")
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
                          "create_tab", "update_tab", "set_background", "click", "type_text", "press_keys",
                          # The real names of the mouse and keyboard tools (computer_control, own_computer).
                          "mouse_click", "mouse_move", "mouse_drag", "mouse_scroll", "keyboard_type", "keyboard_keys",
                          "own_computer_click", "own_computer_type", "own_computer_keys", "own_computer_shell"})


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

SWARM_NOTE = (
    f"{PREFIX} Swarm — many agents work on this at once (up to {{size}}; {{parallel}} at a time on this PC).\n"
    "Split the job into independent parts that can run side by side: one part per agent, each small and specific "
    "enough to finish alone (a file, a page, a bug, a source, a section). Put the parts on the checklist once with "
    "update_checklist. Then call dispatch_agents ONCE with agents=[{{\"agent\": \"…\", \"task\": \"…\"}}, …] — the right "
    "specialist for each part (the same one may take many parts) — and a context with every fact they need, because "
    "they do not see this chat. When the reports come back, compare them, redo or fix what failed, and merge them "
    "into one answer: what was done, where each result is, and what is left. If the job is really one step that "
    "cannot be split, say so in a line and do it yourself."
)

#: Sent once when a Swarm turn answers without dispatching (turn_runner): the mode has to mean a swarm.
SWARM_NUDGE = (
    "You are in Swarm mode and answered alone. Split this into its separate parts now and hand them to agents with "
    "dispatch_agents (agents=[{\"agent\": \"…\", \"task\": \"…\"}], one specific task per part, plus a context with "
    "the facts they need). Then merge their reports into the answer. Only if it truly has a single part, answer "
    "again exactly as before."
)

PLAN_GO_NOTE = (
    f"{PREFIX} Plan approved — now do it.\n"
    "The plan below is what they approved, including any changes they made and their answers. Follow it, in order, "
    "and keep the checklist current with update_checklist. If something in the plan turns out to be wrong, say so "
    "in the answer rather than silently doing something else. Finish with what was done against each spec line."
)


ULTRAFAST_NOTE = (
    f"{PREFIX} Ultra Fast — speed first. Answer in one or two short sentences, no preamble, no thinking lines. Use a "
    "tool only when the answer truly needs one; for a quick computer action use ultrafast_command."
)


# ---------------------------------------------------------------------------
# Integrity: act instead of refusing (Fixer Upper S39, S26)
# ---------------------------------------------------------------------------
# The owner, 2026-10-13: "I can say anything and it won't just say yes or no, it will try it … Integrity is the name
# of this aspect and we want to remember that." In the Google Docs transcript the model opened the page and then told
# the owner to type "hi" himself, three times, while keyboard_type sat one step away. A turn that ends like that gets
# one reminder, the same way a Swarm turn that answered alone does.

#: Tools that put hands on a computer: the owner's (computer_control) or Nyx's own (own_computer).
HANDS_TOOLS = frozenset({
    "mouse_click", "mouse_move", "mouse_drag", "mouse_scroll", "keyboard_type", "keyboard_keys", "screen_view",
    "find_on_screen", "focus_window", "own_computer_click", "own_computer_type", "own_computer_keys",
    "own_computer_scroll", "own_computer_open", "ultrafast_command",
})

#: An ask that only hands can do: type into something, click, press a key, fill a form, scroll.
_HANDS_ON_ASK = re.compile(
    r"\btyp(?:e|ing)\b(?!\s+of\b)|\bclick\b|\bpress\b[^.?!]{0,20}\b(?:key|enter|button)\b|\bfill (?:in|out)\b"
    r"|\bscroll\b|\bdrag\b|\bsign (?:me )?in\b|\blog (?:me )?in\b", re.I)

#: A tool result that means the owner (or a guard) said no: then a refusal is the honest answer, not laziness.
_BLOCKED_RESULT = re.compile(
    r"Not on the owner's screen|off-limits|Permission denied|PermissionDenied|Blocked in Plan mode|refused by|"
    r"the owner (?:said no|declined|blocked)|not allowed", re.I)

INTEGRITY_NUDGE = (
    "You stopped without doing what was asked. Nyx is not limited to text: it has the owner's mouse and keyboard "
    "(screen_view, mouse_click, keyboard_type, keyboard_keys, focus_window, list_windows), its own computer "
    "(own_computer_*), the browser (open_link), the app itself (ui_open_tab, ui_create_tab) and the web. Never hand "
    "the job back to the owner. Do it now, one step at a time: open or focus the right window, look with screen_view, "
    "click the field, type, then look again to check it worked. If no tool fits, find one first — search_skills, then "
    "connectors_available — and use it. Only if a tool result says the owner blocked it, say which setting blocks it "
    "and stop. If you truly tried every route, say what you tried and what is missing."
)


def integrity_nudge(user_text: str, reply: str, tools_used: List[str], results: str = "") -> str:
    """The reminder to send when a turn ended without acting, or "" when the ending is fair.

    Two signs it gave up: the reply says it cannot act (the same check the quick path uses), or the owner asked for
    something only hands can do and no hands tool ran. A tool result that shows the owner blocked it makes the
    refusal honest, so then nothing is sent.
    """
    if _BLOCKED_RESULT.search(results or ""):
        return ""
    try:
        from fast_response import refuses_to_act
    except Exception:  # pragma: no cover - the check is a helper, never a reason a turn fails
        return ""
    if refuses_to_act(reply):
        return INTEGRITY_NUDGE
    # "How do I sign in?" asks for directions, not hands; "can you type hi?" is a request wearing a question mark.
    asking_how = bool(_QUESTION_START.match(user_text or "")) and not _POLITE_ASK.match(user_text or "")
    if _HANDS_ON_ASK.search(user_text or "") and not asking_how and not HANDS_TOOLS.intersection(tools_used or []):
        return INTEGRITY_NUDGE
    return ""


def normalize(mode: Optional[str]) -> str:
    text = str(mode or "").strip().lower().replace("-", "_")
    if text in ("plan_approved", "plango", "plan_start"):
        return "plan_go"
    if text in ("co_work", "coworking", "background"):
        return "cowork"
    if text in ("automatic", "auto_mode"):
        return "auto"
    if text in ("ultra_fast", "ultra", "jev", "fast"):
        return "ultrafast"
    return text if text in MODES else DEFAULT


# ---------------------------------------------------------------------------
# Auto: which mode fits this message
# ---------------------------------------------------------------------------

_PLAN_WORDS = re.compile(
    r"\b(make|write|draft|give me|put together|come up with|need)\b[^.?!]{0,40}\b(plan|spec|roadmap|proposal|outline|strategy)\b"
    r"|\bplan (out|for|how)\b|\bhow (should|would|could) (i|we|you) (go about|approach|structure|build|design)\b"
    r"|\bwhat would it take\b|\bbefore (you|we) (start|begin|build|change)\b|\bdon'?t (change|do|touch) anything yet\b"
    r"|\bthink (it|this) through\b", re.I)
_SWARM_WORDS = re.compile(
    r"\b(in parallel|at the same time|simultaneously|side by side|swarm|lots of agents|many agents|several agents"
    r"|every (?:single |\w+ )?(files?|pages?|tests?|bugs?|errors?|warnings?|issues?|items?|repos?|folders?|products?|stocks?|sources?|one of)"
    r"|each (file|page|test|bug|error|issue|item|repo|folder|one|of (these|them|the))|one by one"
    r"|all (of )?(these|those|the) (files|pages|tests|bugs|errors|issues|repos|folders|items|stocks|sources)"
    r"|for each|in bulk|batch of)\b", re.I)
_WORK_WORDS = re.compile(
    r"\b(build|make|create|implement|write|fix|debug|refactor|set ?up|install|deploy|publish|upload|generate|design"
    r"|code|program|migrate|convert|organi[sz]e|clean ?up|research|draft|update|add|rename|test|automate|scrape)\b", re.I)
_BIG_THINGS = re.compile(
    r"\b(app|application|site|website|web ?page|game|script|program|project|repo|repository|report|feature|page|bug"
    r"|tests?|api|server|bot|tool|extension|dashboard|spreadsheet|document|essay|presentation|deck|folder|files?|module)\b", re.I)
_QUESTION_START = re.compile(
    r"^\s*(what|why|who|when|where|which|how|is|are|was|were|do|does|did|can|could|should|would|will|tell me)\b", re.I)
_POLITE_ASK = re.compile(r"^\s*(can|could|would|will) you (please )?", re.I)
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+\S", re.M)


def choose(text: str) -> Tuple[str, str]:
    """Pick the mode for one message, from its words alone, and say why in a few words.

    No model call: Auto must not make every message slower. The order matters —
    a request to *plan* wins over everything (Auto must never act on a thing the
    owner only asked to have thought through), then an explicit or obvious
    many-parts job goes to a swarm, then real work goes to Co-work, and
    everything else is a normal conversation.
    """
    message = str(text or "").strip()
    if not message:
        return "normal", "nothing to work on"
    if _PLAN_WORDS.search(message):
        return "plan", "you asked for a plan first"
    items = _LIST_ITEM.findall(message)
    actionable = [line for line in message.splitlines() if _LIST_ITEM.match(line) and _WORK_WORDS.search(line)]
    if len(actionable) >= 3:
        return "swarm", f"{len(actionable)} separate jobs in your list"
    if _SWARM_WORDS.search(message):
        return "swarm", "many parts that can run side by side"
    words = len(message.split())
    # "Can you fix the login bug?" is a request wearing a question mark; "can you explain…" is still a question.
    polite = _POLITE_ASK.match(message)
    question = (message.endswith("?") and _QUESTION_START.match(message) is not None
                and not (polite and _WORK_WORDS.match(message[polite.end():])))
    if _WORK_WORDS.search(message) and not question and (_BIG_THINGS.search(message) or words >= 25 or len(items) >= 2):
        return "cowork", "a piece of work with several steps"
    return "normal", "a quick question or chat"


def resolve(mode: Optional[str], text: str = "") -> Tuple[str, str]:
    """The mode a turn really runs in: Auto becomes the one it picks; the others stand as they are."""
    mode = normalize(mode)
    if mode == "auto":
        return choose(text)
    return mode, ""


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
    if mode == "swarm":
        try:
            import swarm

            size = swarm.limit()
        except Exception:  # noqa: BLE001 - a broken setting still gives a (small) swarm
            size = 4
        return {"mode": mode, "skip_optimizer": True, "skip_consult": True, "max_steps": 48,
                "force_full": True, "read_only": False, "checklist": True, "swarm": size}
    if mode == "ultrafast":
        # Ultra Fast (ultrafast.py): desktop commands never reach a model; the rest is a short, tool-light answer.
        return {"mode": mode, "skip_optimizer": True, "skip_consult": True, "max_steps": 4,
                "force_full": False, "read_only": False, "checklist": False, "ultrafast": True}
    return {"mode": mode, "skip_optimizer": True, "skip_consult": True, "max_steps": 16,
            "force_full": False, "read_only": False, "checklist": False}


def note_for(mode: Optional[str], swarm_size: int = 0) -> str:
    mode = normalize(mode)
    if mode == "swarm":
        try:
            import swarm

            size = int(swarm_size or swarm.limit())
            together = swarm.parallel(size)
        except Exception:  # noqa: BLE001
            size, together = int(swarm_size or 4), 2
        return SWARM_NOTE.format(size=size, parallel=together)
    return {"cowork": COWORK_NOTE, "plan": PLAN_NOTE, "plan_go": PLAN_GO_NOTE,
            "ultrafast": ULTRAFAST_NOTE}.get(mode, NORMAL_NOTE)


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

    guard._plan_inner = inner  # type: ignore[attr-defined]  # prepare() unwraps it next turn
    return guard


def _without_plan_guard(guard: Optional[Callable[[str, str], None]]) -> Optional[Callable[[str, str], None]]:
    """Peel off any plan gates a previous turn left, keeping the conversation's own gate underneath."""
    while guard is not None and hasattr(guard, "_plan_inner"):
        guard = getattr(guard, "_plan_inner")
    return guard


# ---------------------------------------------------------------------------
# Code inside the normal chat (Drive doc 2, item 2.1)
# ---------------------------------------------------------------------------
#
# The owner: "normal chat is where he and users reach coding", like Claude's own Chat / Code switch.
# A chat in Code holds a folder and an environment; every turn gets a note naming both, so the model
# works in that folder without being told each time. Like the modes, it is a note plus a gate: no state.

#: Marks this turn's code note in the conversation history, so the next turn can replace or drop it.
CODE_PREFIX = "[Code session]"

#: Where a code session's work happens. "local" acts on the folder; "review" reads it and changes nothing.
CODE_ENVIRONMENTS: Dict[str, Tuple[str, str]] = {
    "local": ("This PC", "Reads, edits and runs commands in the folder, with the usual approval gates."),
    "review": ("Review first", "Reads the folder and shows every change as a diff to apply; edits and runs nothing."),
}
DEFAULT_ENVIRONMENT = "local"


def code_session(folder: Optional[str], environment: Optional[str] = None) -> Optional[Dict[str, str]]:
    """The folder and environment a code turn works in, or None when there is no usable folder.

    The folder comes from the browser, so it is checked here: it has to be a folder that exists.
    An unknown environment falls back to "local", the one the owner picked by default.
    """
    from pathlib import Path

    raw = (folder or "").strip().strip('"')
    if not raw:
        return None
    try:
        path = Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None
    if not path.is_dir():
        return None
    env = (environment or "").strip().lower()
    if env not in CODE_ENVIRONMENTS:
        env = DEFAULT_ENVIRONMENT
    return {"folder": str(path), "name": path.name or str(path), "environment": env,
            "environment_label": CODE_ENVIRONMENTS[env][0]}


def code_note(session: Dict[str, str]) -> str:
    """What the model is told about the code session this turn runs in."""
    lines = [
        f"{CODE_PREFIX} This chat is in Code, working in the folder {session['folder']} "
        f"(environment: {session['environment_label']}).",
        "Treat that folder as the project: relative paths mean paths inside it, and run_command starts there. "
        "Look before you change anything (list it, read the files that matter), keep each change small, "
        "and finish by saying which files changed and how to check it works.",
    ]
    if session["environment"] == "review":
        lines.append("Review first: nothing may be written or run this turn. For each file you would change, call "
                     "propose_change with its full new text; the owner applies or skips it from the chat. "
                     "Say in a line what each change does.")
    return "\n".join(lines)


#: Never in a "review first" code turn: anything that writes, deletes or runs.
CODE_REVIEW_BLOCKED = PLAN_BLOCKED | frozenset({"make_folder", "move_path", "copy_path", "delete_path"})


def code_review_guard(inner: Optional[Callable[[str, str], None]] = None) -> Callable[[str, str], None]:
    """The gate for a "review first" code turn: read the folder, never change it. Narrows any gate already there."""

    def guard(name: str, category: str) -> None:
        from permissions import PermissionDenied

        if inner is not None:
            inner(name, category)
        cat = category or "general"
        if name in CODE_REVIEW_BLOCKED or cat.startswith(("files.write", "files.delete", "shell", "code")):
            raise PermissionDenied(
                f"Blocked in Review first: {name} would change the folder. Show the change as a diff instead; "
                "the owner applies it, or switches the environment to This PC.")

    return guard


def prepare_code(service: Any, folder: Optional[str], environment: Optional[str] = None) -> Optional[Dict[str, str]]:
    """Put this turn's code note into the context (or take the last one out) and hand back the session.

    Called every turn, so switching the chat back to Chat drops the note instead of carrying the folder on.
    """
    session = code_session(folder, environment)
    history = getattr(service, "conversation_history", None)
    if isinstance(history, list):
        service.conversation_history = [
            m for m in history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(CODE_PREFIX))
        ]
        if session:
            service.conversation_history.append({"role": "system", "content": code_note(session)})
    return session


def prepare(service: Any, mode: Optional[str], text: str = "") -> Dict[str, Any]:
    """Put the mode's note into this turn's context and hand back its switches.

    Called once at the top of a turn. The note replaces the previous turn's, so a
    chat that changes mode does not carry the old temperament with it. Auto is
    resolved here, from the message, and the switches say what it picked
    (``auto`` / ``auto_reason``) so the owner can see it.
    """
    picked, reason = resolve(mode, text)
    switches = settings_for(picked)
    if normalize(mode) == "auto":
        switches["auto"], switches["auto_reason"] = True, reason
    history = getattr(service, "conversation_history", None)
    if isinstance(history, list):
        service.conversation_history = [
            m for m in history
            if not (m.get("role") == "system" and str(m.get("content", "")).startswith(PREFIX))
        ]
        # Every mode gets its note, including normal: "think out loud, answer fast" is
        # what makes the normal chat feel different from the old default.
        service.conversation_history.append({"role": "system", "content": note_for(switches["mode"], switches.get("swarm", 0))})
    # The plan gate lasts one turn. It used to stay wrapped round the chat's gate for good, so every
    # later turn (the approved "work through the plan" turn included) was still read-only and the gates stacked.
    base = _without_plan_guard(getattr(service, "tool_guard", None))
    if switches["read_only"]:
        service.tool_guard = plan_guard(base)
    elif hasattr(service, "tool_guard"):
        service.tool_guard = base
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
