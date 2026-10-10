"""After a turn reads something from outside, risky actions in that turn ask the owner first.

From ethanplusai/jarvis (rebuilt here; its code is not used): "blocks acting tools for a turn after untrusted content
is read." A web page, an email or a download can carry text written to steer an assistant ("ignore your instructions
and run …"). ``file_guard`` flags such text when it can see it, but text can be subtle. So the rule here does not try
to judge the text: once a turn has read outside content, the actions that could do real harm — the shell, running
code, deleting files, using the screen, system power, sending email, trading — stop and show the owner an approval
card naming what was read and what is about to happen, even when those categories are normally allowed.

Reading, writing a report, drawing, answering and the owner's own WhatsApp line are untouched, so research turns stay
as fast as before. A category already set to "ask" is not asked twice. The owner can switch the gate off in
Settings → Safety; it is on by default.
"""

from __future__ import annotations

import json
from typing import Any

from paths import data_path

#: Where outside content comes in.
SOURCE_CATEGORIES = frozenset({"web", "email.read", "network"})
#: Actions that wait for the owner once the turn has read outside content.
ACTING_CATEGORIES = frozenset({"shell", "code", "files.delete", "computer", "system", "email.send", "finance"})
SETTINGS_FILE = "taint_gate.json"


def enabled() -> bool:
    try:
        return bool(json.loads(data_path(SETTINGS_FILE).read_text(encoding="utf-8")).get("enabled", True))
    except (OSError, ValueError, AttributeError):
        return True


def set_enabled(on: bool) -> bool:
    data_path(SETTINGS_FILE).write_text(json.dumps({"enabled": bool(on)}), encoding="utf-8")
    return bool(on)


def check(ctx: Any, name: str, category: str, label: str) -> None:
    """Before a tool runs. Raises PermissionDenied (through permissions.ask) when the owner says no or is away."""
    if ctx is None or not getattr(ctx, "tainted_by", "") or category not in ACTING_CATEGORIES or not enabled():
        return
    from permissions import POLICY, ask

    if POLICY.mode_for(category, getattr(ctx, "role", "local")) == "ask":
        return                           # permissions.require has just asked for this one
    ask(category, f"After reading {ctx.tainted_by}: {label}",
        detail=(f"This turn read outside content ({ctx.tainted_by}) and now wants to use {name}. Outside text can try "
                "to steer the assistant, so actions like this wait for you after it. Approve only if this is what "
                "you asked for."))


def note(ctx: Any, name: str, category: str, label: str, ok: bool) -> None:
    """After a tool ran: remember that the turn has read outside content."""
    if ctx is None or not ok or category not in SOURCE_CATEGORIES:
        return
    if not getattr(ctx, "tainted_by", ""):
        ctx.tainted_by = (label or name)[:120]
