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

MODES = ("normal", "cowork", "plan", "plan_go", "swarm", "auto")
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


def normalize(mode: Optional[str]) -> str:
    text = str(mode or "").strip().lower().replace("-", "_")
    if text in ("plan_approved", "plango", "plan_start"):
        return "plan_go"
    if text in ("co_work", "coworking", "background"):
        return "cowork"
    if text in ("automatic", "auto_mode"):
        return "auto"
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
    return {"cowork": COWORK_NOTE, "plan": PLAN_NOTE, "plan_go": PLAN_GO_NOTE}.get(mode, NORMAL_NOTE)


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
