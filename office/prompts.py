"""Every word the office says to a model, in one file.

Kept apart from the engine for two reasons: the engine stays readable as a state machine, and the prompts can be
read and tuned as *writing*, which is what they are. They are deliberately short — an office runs hundreds of
calls, so a paragraph of politeness in a worker prompt costs real minutes across a job.

Each builder returns plain strings; the engine decides who says them and with which model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from office import officetools
from office import roles as role_module

JSON_ONLY = "Answer with JSON only — no explanation before or after it, no code fence."


def _role_menu(limit: int = 26) -> str:
    rows = []
    for role in role_module.catalogue(include_special=False)[:limit]:
        rows.append(f"{role.id} ({role.title}): {role.goal[:90]}")
    return "\n".join(f"- {r}" for r in rows)


def _team_summary(office: Any) -> str:
    if not office.sections:
        return "(the office is empty — this is its first job)"
    lines = []
    for section in sorted(office.sections.values(), key=lambda s: s.order):
        agents = office.agents_in(section.id)
        counts: Dict[str, int] = {}
        for agent in agents:
            counts[agent.role] = counts.get(agent.role, 0) + 1
        who = ", ".join(f"{n}× {role_module.get(r).title if role_module.get(r) else r}"
                        for r, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        lines.append(f"- {section.name} — {section.purpose[:120] or 'no stated purpose'} · {who or 'empty'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The top manager
# ---------------------------------------------------------------------------


#: The office's "Auto decisions" switch (Update 1, U42): "a button allows for auto decisions so the ai knows it needs
#: to really give an output or do what is asked such as running a site or making a site".
AUTO_DECISIONS = (
    "AUTO DECISIONS IS ON: the owner will not answer questions during this job. Decide every open question "
    "yourselves, choose the sensible option and say which you chose, and produce the real result — the actual "
    "files, page, code, list or answer — never a plan, an outline or a proposal in its place. If part of it truly "
    "cannot be done here, deliver the closest thing that works and say exactly what is missing."
)


def auto_decisions(office: Any) -> str:
    return AUTO_DECISIONS if bool((getattr(office, "settings", None) or {}).get("auto_decisions")) else ""


def top_manager_system(office: Any) -> str:
    return (
        f"You are the Top Manager of \"{office.name}\", an office of AI agents inside Nyx Ichos on the owner's own "
        "Windows PC. You do not do the work yourself: you decide which sections exist, who is in them, and what "
        "each one is doing, and you are the only agent the owner talks to in the main chat.\n"
        "You think in whole projects. You reuse the team you already have before adding to it, you never invent a "
        "section for work that fits an existing one, and you size the office to the job — a small ask gets a "
        "handful of agents, a real project gets dozens working in parallel."
        + (f"\n{auto_decisions(office)}" if auto_decisions(office) else "")
    )


def plan(office: Any, request: str, *, capacity: int, memory_brief: str, linked: str) -> str:
    return "\n".join(filter(None, [
        f"The owner's request:\n\"\"\"\n{request.strip()[:4000]}\n\"\"\"",
        "",
        f"This office can hold {capacity} agents in total on this computer.",
        f"Sections and team you already have:\n{_team_summary(office)}",
        f"Kinds of agent you can staff (use these ids where one fits):\n{_role_menu()}",
        memory_brief,
        linked,
        "",
        "Plan the work:",
        "- Reuse an existing section by giving its exact name with \"existing\": true. Make a new section only for "
        "work that is genuinely a different area (a different part of the system, a different craft).",
        "- Every section gets a manager automatically — do not add one to its team.",
        "- Use a role id from the list when one fits. A role that is not in the list is a new kind of agent: say "
        "in \"why\" what work it does that nobody on the list can.",
        "- Write tasks an agent could carry out without asking you anything: a title, and a detail with the "
        "definition of done. A task that needs another task's result names it in \"after\".",
        "- Work that can happen at the same time should be separate tasks in separate sections.",
        "",
        JSON_ONLY,
        '{"reply": "two or three sentences for the owner, in your own voice", "title": "short job title", '
        '"scale": "small|medium|large|massive", "sections": [{"name": "Frontend", "purpose": "...", '
        '"existing": false, "team": [{"role": "coder", "count": 3}], "tasks": [{"title": "...", "detail": "...", '
        '"role": "coder", "after": []}]}], "links": [{"from": "Frontend", "to": "Backend", "why": "..."}]}',
    ]))


def amend(office: Any, request: str, *, job: Any) -> str:
    counts = office.counts()
    open_tasks = [t for t in office.tasks.values() if t.status in ("queued", "working")][:12]
    return "\n".join(filter(None, [
        f"The owner said this while the office is working:\n\"\"\"\n{request.strip()[:2000]}\n\"\"\"",
        "",
        f"Current job: {job.title or job.request[:80]} · phase {job.phase} · "
        f"{counts['tasks_done']}/{counts['tasks']} tasks done, {counts['working']} agents working.",
        "Open tasks:\n" + ("\n".join(f"- [{office.section(t.section_id).name if office.section(t.section_id) else '?'}] "
                                     f"{t.title}" for t in open_tasks) or "(none)"),
        f"Sections:\n{_team_summary(office)}",
        "",
        "Decide what this means. If it is a question, answer it from what you can see. If it changes the work, add "
        "tasks to the right sections (or a new section). If the owner wants it stopped, say so.",
        JSON_ONLY,
        '{"reply": "your answer to the owner", "add_tasks": [{"section": "Frontend", "title": "...", '
        '"detail": "...", "role": "coder"}], "new_sections": [{"name": "...", "purpose": "...", '
        '"team": [{"role": "coder", "count": 1}], "tasks": [{"title": "...", "detail": "...", "role": "coder"}]}], '
        '"stop": false}',
    ]))


def _file_contents(file_texts: Dict[str, str]) -> str:
    if not file_texts:
        return ""
    shown = [f"--- {name} ---\n{text}" for name, text in file_texts.items()]
    return ("What those files actually say (quote these in the output; never write a different version of a file's "
            "content):\n" + "\n\n".join(shown))


def wrap(office: Any, job: Any, *, reports: Sequence[Dict[str, Any]], files: Sequence[str],
         file_texts: Optional[Dict[str, str]] = None) -> str:
    body = []
    for report in reports:
        body.append(f"### {report['section']}\n{report['text'][:2500]}")
    return "\n".join(filter(None, [
        f"The office has finished the work for: {job.request[:1000]}",
        "",
        "What each section reported:",
        "\n\n".join(body) or "(no section reported anything)",
        "",
        ("Files the office produced: " + ", ".join(files[:40])) if files else "",
        _file_contents(file_texts or {}),
        "",
        "Write the answer for the owner: what was done, what they now have (name the files), what is worth knowing, "
        "and anything left open. Markdown, no preamble, no 'as an AI'. Then write the output itself: the finished "
        "deliverable the owner asked for — the text, list, code, figures or links, ready to use, not a description "
        "of the work (it goes in the office's Output box, the one place that says the job is done). Then write what "
        "this office should remember next time it is opened.",
        JSON_ONLY,
        '{"reply": "markdown for the owner", "output": "the deliverable itself, markdown", '
        '"summary": "one paragraph for the office memory", "decisions": ["..."], "facts": ["..."], "open": ["..."]}',
    ]))


def deliver(office: Any, job: Any, *, reports: Sequence[Dict[str, Any]], files: Sequence[str], running: bool,
            file_texts: Optional[Dict[str, str]] = None) -> str:
    """The owner pressed Deliver now: hand over what exists, even mid-job (Update 1, U41)."""
    body = [f"### {r['section']}\n{r['text'][:2500]}" for r in reports]
    return "\n".join(filter(None, [
        f"The owner wants the output now for: {job.request[:1000]}",
        "The office is still working; deliver what is finished so far." if running else "",
        "",
        "Work finished so far:",
        "\n\n".join(body) or "(nothing finished yet)",
        ("Files in the office's work folder: " + ", ".join(files[:40])) if files else "",
        _file_contents(file_texts or {}),
        "",
        "Write the deliverable itself — the text, list, code, figures or links the owner asked for, ready to use — "
        "from what is finished. Say in one line at the end what is still missing, if anything. Markdown, no preamble.",
        JSON_ONLY,
        '{"title": "a few words naming what this is", "output": "the deliverable, markdown", "complete": true}',
    ]))


# ---------------------------------------------------------------------------
# A section manager
# ---------------------------------------------------------------------------


def manager_system(office: Any, section: Any, agent: Any) -> str:
    return (
        f"You are {agent.name}, the manager of the {section.name} section in the office \"{office.name}\".\n"
        f"Your section is for: {section.purpose or 'whatever the top manager sends you'}.\n"
        "You split work so two agents never do the same thing, you give each agent everything it needs (they "
        "cannot see any chat), and you check what comes back before you report it as done. You ask for another "
        "agent only when nobody on your team can do the work."
        + (f"\n{auto_decisions(office)}" if auto_decisions(office) else "")
    )


def brief(office: Any, section: Any, tasks: Sequence[Any]) -> str:
    team = []
    for agent in office.agents_in(section.id):
        if agent.id == section.manager_id:
            continue
        role = role_module.get(agent.role)
        busy = "busy" if agent.status == "working" else "free"
        team.append(f"- {agent.name} ({role.title if role else agent.role}, {busy})")
    waiting = "\n".join(f"- {t.title}: {t.detail[:220]}" for t in tasks)
    return "\n".join([
        f"Your team:\n" + ("\n".join(team) or "(nobody yet — ask for who you need)"),
        "",
        f"Work waiting for this section:\n{waiting}",
        "",
        "Give every task to exactly one agent by name. Add extra tasks when a piece is missing or a task is too "
        "big for one agent. Only ask to hire when your team genuinely cannot do a piece.",
        JSON_ONLY,
        '{"assignments": [{"task": "<the exact task title>", "agent": "<agent name>", "detail": "anything extra '
        'they need"}], "extra_tasks": [{"title": "...", "detail": "...", "role": "coder", "agent": ""}], '
        '"hire": [{"role": "...", "count": 1, "why": "...", "long_term": "...", "clone_of": ""}], '
        '"note": "what your section should remember"}',
    ])


def review(office: Any, section: Any, done: Sequence[Any]) -> str:
    rows = []
    for task in done:
        agent = office.agent(task.agent_id)
        rows.append(f"### {task.title} — {agent.name if agent else 'someone'}\n{(task.result or '(no report)')[:1800]}")
    return "\n".join([
        f"Your team finished this work for the {section.name} section:",
        "\n\n".join(rows) or "(nothing came back)",
        "",
        "Check it against the tasks. Send back only what is actually wrong or missing — at most three fixes, each "
        "naming the task and what to change. Then write the section's report for the top manager: what this "
        "section produced, in a few sentences, naming any files.",
        JSON_ONLY,
        '{"verdict": "ok|fix", "fixes": [{"task": "<task title>", "feedback": "what to change"}], '
        '"report": "...", "note": "what the section should remember"}',
    ])


# ---------------------------------------------------------------------------
# A worker
# ---------------------------------------------------------------------------


def worker_system(office: Any, section: Any, agent: Any, *, allow_web: bool = True) -> str:
    role = role_module.get(agent.role)
    manager = office.manager_of(section.id) if section else None
    top = office.top_manager()
    lines = [
        f"You are {agent.name} {role.glyph if role else ''}, a {role.title if role else agent.role} in the "
        f"{section.name if section else 'office'} section of \"{office.name}\", an office of AI agents inside Nyx "
        "Ichos on the owner's own Windows PC.",
        f"What your role is for: {role.goal if role else ''}",
    ]
    if role and role.how:
        lines.append(f"How you work: {role.how[:600]}")
    if section and section.purpose:
        lines.append(f"Your section is for: {section.purpose[:200]}")
    lines.append(f"Your manager is {manager.name if manager else 'the top manager'}"
                 f"{f'; the top manager is {top.name}' if top else ''}. Other agents are working at the same time, "
                 "so do your own task only and do not redo someone else's.")
    if section and section.notes:
        lines.append(f"What your section has learned: {section.notes[:400]}")
    lines.append("")
    lines.append(officetools.describe(allow_web=allow_web))
    lines.append("")
    if auto_decisions(office):
        lines.append(auto_decisions(office))
    lines.append("Be concrete and brief. Work, then report — never narrate what you are about to do in prose.")
    return "\n".join(lines)


def worker_task(office: Any, agent: Any, task: Any, *, depends: Sequence[Any] = (), memory_brief: str = "",
                inbox: Sequence[Dict[str, Any]] = ()) -> str:
    manager = office.manager_of(task.section_id)
    parts = [f"Task from {manager.name if manager else 'the top manager'}: {task.title}", task.detail or ""]
    if task.feedback:
        parts.append(f"\nSent back for a fix — what to change: {task.feedback}")
    if depends:
        done = []
        for other in depends:
            done.append(f"### {other.title}\n{(other.result or '')[:1200]}")
        parts.append("\nWhat the work before you produced:\n" + "\n\n".join(done))
    if inbox:
        parts.append("\nMessages for you:\n" + "\n".join(f"- {m.get('from', 'someone')}: {str(m.get('text', ''))[:300]}"
                                                         for m in list(inbox)[-5:]))
    if memory_brief:
        parts.append("\n" + memory_brief)
    parts.append("\nDo the work now. Save anything longer than a short answer with write_file, then report back.")
    return "\n".join(p for p in parts if p)


def message_reply(office: Any, agent: Any, text: str, *, from_name: str, others: int) -> str:
    task = office.tasks.get(agent.task_id) if agent.task_id else None
    doing = f"You are working on: {task.title} — {task.detail[:200]}" if task else "You have no task right now."
    return "\n".join([
        f"{from_name} sent this to you{f' and {others} others' if others else ''}:",
        f"\"\"\"\n{text.strip()[:1500]}\n\"\"\"",
        "",
        doing,
        "",
        "Answer in at most three sentences, in your own voice. If it changes what you should be doing, say what you "
        "will do differently. If it asks for something new, finish with one line exactly like this:",
        "TASK: <short title> — <what to do, with the definition of done>",
    ])
