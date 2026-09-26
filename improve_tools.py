"""Chat tools for self-improvement: "Nyx, improve yourself" as a sentence.

The Improve tab is the cockpit; these tools are the conversation. The owner
says what they want (optionally a time budget or full power), Nyx starts a
session, and every outcome still lands as a draft in the change-review gate —
a chat tool can commission analysis, never apply changes.
"""

from __future__ import annotations

from typing import Any


def tool_improve_self(goal: str, minutes: float = 0, max_power: bool = False) -> str:
    """Start one self-improvement session; the draft queue does the rest."""
    from improvement_engine import ENGINE

    try:
        session = ENGINE.start(
            goal,
            time_budget_seconds=float(minutes or 0) * 60,
            max_power=bool(max_power),
        )
    except (ValueError, RuntimeError) as error:
        return f"Error: {error}"
    tail = f" Budget: {int(minutes)} minutes." if minutes else ""
    if max_power:
        tail += " Full power: four analysis angles."
    return (
        f"Self-improvement session started ({session['session_id']}). I'll map my own base code "
        f"and file what I find as proposals for {('the owner').strip()}'s approval in Admin → changes."
        f"{tail} Watch it live in the Improve tab."
    )


def tool_improvement_status() -> str:
    """Sessions this engine run, newest first — the same list the Improve tab shows."""
    from improvement_engine import ENGINE

    sessions = ENGINE.list_sessions()
    lines = []
    try:
        from improve_autopilot import AUTOPILOT

        run = AUTOPILOT.active()
        if run:
            phase = run["phase"]
            lines.append(f"Autopilot [{run['status']}]: {run['work']} — phase {phase['kind']} "
                         f"({int((run['phase_remaining_seconds'] or 0) / 60)} min left), auto-approve "
                         f"{'on' if run['auto_approve'] else 'off'}, stats {run['stats']}")
    except Exception:  # noqa: BLE001
        pass
    if not sessions and not lines:
        return "No self-improvement sessions yet. Ask me to improve something specific."
    for s in sessions[:5]:
        detail = s["progress"]
        if s["proposals_filed"]:
            detail += f" — {s['proposals_filed']} proposals filed"
        if s["error"]:
            detail += f" — {s['error']}"
        lines.append(f"[{s['status']}] {s['goal']} ({int(s['elapsed_seconds'])}s): {detail}")
    return "\n".join(lines)


def tool_improve_schedule(instruction: str, hours: float = 0, auto_approve: Any = None, loop: Any = None,
                          phases: Any = None) -> str:
    """Start an autopilot run from the owner's own words (plus optional structure)."""
    import json

    from improve_autopilot import AUTOPILOT, AutopilotError
    import improve_review

    intent = improve_review.review_intent(instruction) if not (phases or hours) else None
    if intent:
        # "approve all the pending changes" is about the review queue, not a new improve run.
        outcome = improve_review.run_intent(intent, by="Owner (asked in chat)")
        return f"{outcome['message']} Progress and every decision show in the Improve tab's review queue."

    parsed_phases = None
    if phases:
        try:
            parsed_phases = json.loads(phases) if isinstance(phases, str) else list(phases)
        except (ValueError, TypeError):
            return "Error: phases must be a JSON list like [{\"kind\": \"study\", \"minutes\": 60}]."
    try:
        run = AUTOPILOT.start(instruction, phases=parsed_phases, hours=float(hours) if hours else None,
                              auto_approve=None if auto_approve is None else bool(auto_approve),
                              loop=None if loop is None else bool(loop), started_by="nyx (asked by the owner)")
    except AutopilotError as error:
        return f"Error: {error}"
    plan = " → ".join(f"{p['kind']} {int(p['minutes'])} min" for p in run["phases"])
    window = (f"for {run['remaining_seconds'] / 3600:.1f} hours" if run["remaining_seconds"] else "until the owner stops it")
    approval = ("Auto-approve is ON: each change is researched first, written and tested in a sandbox, a critic reads the "
                "real diff, and it is applied only then (every change can be rolled back in the Improve tab)." if run["auto_approve"]
                else "Auto-approve is off: findings wait for the owner in the Improve tab.")
    return (f"Autopilot started ({run['run_id']}): {plan}{' (looping)' if run['loop'] else ''}, {window}. {approval} "
            "Tell the owner exactly this plan so they can correct it.")


def tool_improve_stop(reason: str = "") -> str:
    from improve_autopilot import AUTOPILOT, AutopilotError

    try:
        run = AUTOPILOT.stop(reason=reason or "Stopped by the owner from chat")
    except AutopilotError as error:
        return f"Error: {error}"
    stats = run["stats"]
    return (f"Autopilot stopped. It studied {stats['study_cycles']} times ({stats['lessons']} lessons), found "
            f"{stats['proposals']} improvements, applied {stats['applied']}, rejected {stats['rejected'] + stats['failed']}.")


def tool_improve_add_control(label: str, kind: str = "slider", affects: str = "", minimum: float = 0, maximum: float = 10,
                             step: float = 1, value: Any = None, options: Any = None, key: str = "") -> str:
    from improve_autopilot import AUTOPILOT, AutopilotError

    option_list = options if isinstance(options, list) else [o.strip() for o in str(options or "").split(",") if o.strip()]
    spec = {"key": key or label, "label": label, "kind": kind, "affects": affects, "description": affects,
            "min": minimum, "max": maximum, "step": step, "options": option_list}
    if value is not None:
        spec["value"] = value
    try:
        control = AUTOPILOT.add_control(spec, by="nyx")
    except AutopilotError as error:
        return f"Error: {error}"
    return f"Added the {control['kind']} “{control['label']}” to the Improve tab (value {control['value']}). It steers: {control['affects'] or 'the autopilot'}."


def tool_improve_set_control(key: str, value: Any) -> str:
    from improve_autopilot import AUTOPILOT, AutopilotError

    try:
        control = AUTOPILOT.set_control(key, value, by="nyx")
    except AutopilotError as error:
        names = ", ".join(c["key"] for c in AUTOPILOT.controls())
        return f"Error: {error} Controls: {names}."
    return f"{control['label']} is now {control['value']}."


def register_improve_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        "improve_schedule",
        "Start the self-improvement AUTOPILOT from the owner's words: timed phases (study / improve / detox / rest), "
        "optional looping, an optional time window, and an optional auto-approve window. Use for \"improve and auto "
        "approve everything for 22 hours\", \"study 1 hour then improve 1 hour, loop until I stop\", \"take a detox "
        "hour\". Pass the owner's sentence as instruction; add hours/auto_approve/loop/phases only to override.",
        [ToolParam("instruction", "string", "The owner's request, verbatim"),
         ToolParam("hours", "number", "Total run length in hours (omit = from the sentence / until stopped)", required=False),
         ToolParam("auto_approve", "boolean", "True only if the owner said to auto-approve", required=False),
         ToolParam("loop", "boolean", "Repeat the phases until stopped", required=False),
         ToolParam("phases", "string", "Optional JSON list [{\"kind\":\"study|improve|detox|rest\",\"minutes\":60,\"focus\":\"...\"}]", required=False)],
        tool_improve_schedule, category="self", label=lambda a: f"Scheduling self-improvement: {str(a.get('instruction', ''))[:50]}",
    )
    registry.register(
        "improve_stop", "Stop the self-improvement autopilot.",
        [ToolParam("reason", "string", "Why, in a few words", required=False)],
        tool_improve_stop, category="self", label="Stopping the autopilot",
    )
    registry.register(
        "improve_add_control",
        "Add a control (slider, toggle, select, multiselect or text) to the Improve tab when the owner asks for a new "
        "way to steer self-improvement (e.g. \"a slider for how many web searches to do\"). Say in 'affects' what it "
        "controls; the autopilot follows every control's value.",
        [ToolParam("label", "string", "What the owner sees"),
         ToolParam("kind", "string", "Control type", required=False, enum_values=["slider", "toggle", "select", "multiselect", "text"]),
         ToolParam("affects", "string", "What this control should change about self-improvement"),
         ToolParam("minimum", "number", "Slider minimum", required=False),
         ToolParam("maximum", "number", "Slider maximum", required=False),
         ToolParam("step", "number", "Slider step", required=False),
         ToolParam("value", "string", "Starting value", required=False),
         ToolParam("options", "string", "Comma-separated options for select/multiselect", required=False),
         ToolParam("key", "string", "Stable id (defaults from the label)", required=False)],
        tool_improve_add_control, category="self", label=lambda a: f"Adding “{a.get('label', '')}” to the Improve tab",
    )
    registry.register(
        "improve_set_control", "Change the value of an Improve-tab control (built-in or added).",
        [ToolParam("key", "string", "Control key, e.g. max_changes_per_hour"), ToolParam("value", "string", "New value")],
        tool_improve_set_control, category="self", label=lambda a: f"Setting {a.get('key', '')}",
    )

    registry.register(
        "improve_self",
        "Start a self-improvement session on Nyx's own base code when the owner asks for it "
        "(\"improve yourself\", \"refactor your chat module\", \"spend 30 minutes analyzing your "
        "code\"). Files proposals for owner approval; nothing is applied automatically.",
        [ToolParam("goal", "string", "What to improve, in the owner's words"),
         ToolParam("minutes", "number", "Analysis time budget in minutes; 0 = no limit", required=False),
         ToolParam("max_power", "boolean", "True for the four-angle, higher-cap analysis pass", required=False)],
        tool_improve_self,
        category="self",
        label=lambda a: f"Improving self: {str(a.get('goal', ''))[:50]}",
    )
    registry.register(
        "improvement_status",
        "Report the state of self-improvement sessions (running, filed proposals, errors).",
        [],
        tool_improvement_status,
        category="self",
        label=lambda a: "Checking improvement sessions",
    )
