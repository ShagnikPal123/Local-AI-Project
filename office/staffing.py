"""The office as a company: part-time, letting go, promotions and demotions (Update 1, U42).

The owner (2026-10-04): "for office AI I want to make sure alongside hiring being shown firing and part time work is
shown for AI that are unneeded and AI that are needed every couple times if the main heads believe so ... Add
promotions and demotions to ensure health is kept."

After each finished job the office looks at who did what, offline and in milliseconds (no model call — this runs
after every job, and a rule the owner can read beats a model's mood):

* **Part-time** — a worker given nothing in the last ``IDLE_TO_PART_TIME`` jobs. It keeps its desk and its notes and
  is called in when its kind of work comes up. Busy in two jobs in a row, it goes back to full time.
* **Let go** — a part-time worker still idle after ``IDLE_TO_LET_GO`` jobs, while the office is bigger than a real
  team (``office.MIN_AGENTS``). Its desk is freed; its record stays in the staffing list. It can be hired again.
* **Promoted** — clean work this job (at least two tasks done, none failed or sent back) and a long enough record
  for the next rank: junior → normal → senior → lead.
* **Demoted** — more failed or sent-back tasks than finished ones this job, with at least two problems.

The top manager and the Hiring Board are never moved. Section managers can be promoted or demoted, never made
part-time or let go — a section without its manager stops.
"""

from __future__ import annotations

from typing import Dict, List

from office import MIN_AGENTS
from office.roles import HIRING_BOARD, SECTION_MANAGER, TOP_MANAGER
from office.state import AGENT_WORKING, TASK_DONE, TASK_FAILED, Job, Office, StaffChange, new_id

IDLE_TO_PART_TIME = 2
IDLE_TO_LET_GO = 4
#: Tasks done in total before each rank: to reach normal (from junior), senior, lead.
TASKS_FOR_RANK = {0: 2, 1: 6, 2: 14}
RANK_NAMES = {-1: "Junior", 0: "", 1: "Senior", 2: "Lead"}

_UNMOVABLE = {TOP_MANAGER, HIRING_BOARD}


def rank_name(rank: int) -> str:
    return RANK_NAMES.get(max(-1, min(2, rank)), "")


def _job_record(office: Office, job: Job) -> Dict[str, Dict[str, int]]:
    """Per agent, this job: tasks done, failed, and sent back by a manager."""
    record: Dict[str, Dict[str, int]] = {}
    for task in office.tasks.values():
        if task.job_id != job.id or not task.agent_id:
            continue
        row = record.setdefault(task.agent_id, {"done": 0, "failed": 0, "sent_back": 0})
        if task.status == TASK_DONE:
            row["done"] += 1
        elif task.status == TASK_FAILED:
            row["failed"] += 1
        if task.feedback:
            row["sent_back"] += 1
    return record


def review(office: Office, job: Job) -> List[StaffChange]:
    """Apply this job's staffing changes to the office and return them, in the order they happened."""
    record = _job_record(office, job)
    changes: List[StaffChange] = []

    def note(agent, change: str, why: str) -> None:
        changes.append(office.add_staff_change(StaffChange(
            id=new_id("staff"), agent_id=agent.id, agent_name=agent.name, change=change, why=why,
            role=agent.role, job_id=job.id)))

    for agent in sorted(office.agents.values(), key=lambda a: a.desk):
        if agent.role in _UNMOVABLE or agent.id == office.gatekeeper_id:
            continue
        mine = record.get(agent.id)
        if mine:
            agent.jobs_idle = 0
            agent.jobs_busy += 1
            if agent.employment == "part_time" and agent.jobs_busy >= 2:
                agent.employment = "full"
                note(agent, "full_time", "Busy in two jobs in a row — back to full time.")
            problems = mine["failed"] + mine["sent_back"]
            if mine["done"] >= 2 and problems == 0 and agent.rank < 2 and agent.tasks_done >= TASKS_FOR_RANK[agent.rank + 1]:
                agent.rank += 1
                note(agent, "promoted", f"Clean work: {mine['done']} tasks done this job, {agent.tasks_done} in all"
                                        f" — now {rank_name(agent.rank) or 'a full member of the team'}.")
            elif problems >= 2 and problems > mine["done"] and agent.rank > -1:
                agent.rank -= 1
                note(agent, "demoted", f"{problems} tasks failed or sent back against {mine['done']} done this job"
                                       f" — now {rank_name(agent.rank) or 'back to a normal rank'}.")
            continue

        agent.jobs_idle += 1
        agent.jobs_busy = 0
        if agent.role == SECTION_MANAGER or agent.status == AGENT_WORKING:
            continue
        if agent.employment == "full" and agent.jobs_idle >= IDLE_TO_PART_TIME:
            agent.employment = "part_time"
            note(agent, "part_time", f"Nothing to do in the last {agent.jobs_idle} jobs — called in when its kind "
                                     "of work comes up.")
        elif (agent.employment == "part_time" and agent.jobs_idle >= IDLE_TO_LET_GO
              and len(office.agents) > MIN_AGENTS):
            note(agent, "let_go", f"Idle for {agent.jobs_idle} jobs in a row. Its desk is free; it can be hired again.")
            office.agents.pop(agent.id, None)
    return changes
