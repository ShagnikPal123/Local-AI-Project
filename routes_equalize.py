"""The equalize page's data (from the Jarvis projects the owner pointed at, 2026-10-09): what needs the owner right now,
and every Claude Code session on this PC. All the owner's, all read-only, absent from hosted builds."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Request

router = APIRouter()


def _owner(request: Request) -> Any:
    from server import require_local_owner

    return require_local_owner(request, request.headers.get("authorization"))


@router.get("/api/equalize/sessions")
def equalize_sessions(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import claude_sessions

    return {"sessions": claude_sessions.sessions()}


def needs_you() -> List[Dict[str, Any]]:
    """Everything waiting on the owner, from every part of Nyx that can wait, plus Claude Code. Never raises."""
    items: List[Dict[str, Any]] = []
    try:
        import permissions

        for p in permissions.pending_approvals():
            items.append({"kind": "approval", "id": p["id"], "title": p["summary"], "detail": p.get("detail", ""),
                          "where": "chat", "since": p.get("created", 0)})
    except Exception:  # noqa: BLE001
        pass
    try:
        import claude_sessions

        for s in claude_sessions.sessions():
            if s["state"] == "needs_you":
                items.append({"kind": "claude", "id": s["id"], "where": "claude", "since": s["last"],
                              "title": f"Claude Code · {s['project']}: {s['title']}", "detail": s["why"]})
    except Exception:  # noqa: BLE001
        pass
    return sorted(items, key=lambda i: -float(i.get("since") or 0))


@router.get("/api/equalize/needs-you")
def equalize_needs_you(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    return {"items": needs_you()}


# --- Morning Digest (morning_digest.py) ----------------------------------------------------------------------------


@router.get("/api/equalize/digest")
def digest_state(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import morning_digest

    return morning_digest.settings()


@router.put("/api/equalize/digest")
def digest_save(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import morning_digest
    from fastapi import HTTPException

    try:
        return morning_digest.save(body or {})
    except morning_digest.DigestError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/equalize/digest/run")
def digest_run(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Make today's digest now (it may take a few seconds: several sources and one short model call)."""
    import morning_digest

    return morning_digest.build()


# --- skills from GitHub (skill_import.py; OpenJarvis's agentskills import) -----------------------------------------


@router.post("/api/skills/github/preview")
def skills_github_preview(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import skill_import
    from fastapi import HTTPException

    try:
        return skill_import.find(str((body or {}).get("url") or ""))
    except skill_import.SkillImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/skills/github/import")
def skills_github_import(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import skill_import
    from fastapi import HTTPException

    try:
        return {"added": skill_import.import_skills(str(body.get("url") or ""), [str(p) for p in body.get("paths") or []])}
    except skill_import.SkillImportError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


# --- safety: the taint gate (taint_gate.py; from ethanplusai/jarvis's design) ---------------------------------------


@router.get("/api/safety/taint-gate")
def taint_gate_state(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import taint_gate

    return {"enabled": taint_gate.enabled(), "acting": sorted(taint_gate.ACTING_CATEGORIES),
            "sources": sorted(taint_gate.SOURCE_CATEGORIES)}


@router.put("/api/safety/taint-gate")
def taint_gate_save(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import taint_gate

    taint_gate.set_enabled(bool((body or {}).get("enabled", True)))
    return taint_gate_state(_owner_user)


# --- design research (design_research.py; the DESIGN_MASTERPLAN research log as a Nyx feature) ----------------------


@router.get("/api/design-research")
def design_research_list(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import design_research

    return {"entries": design_research.entries(), "masterplan": design_research.masterplan_path().is_file()}


@router.post("/api/design-research")
def design_research_study(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import design_research
    from fastapi import HTTPException

    try:
        return {"entry": design_research.study(str(body.get("url") or ""), str(body.get("name") or ""),
                                               str(body.get("focus") or ""))}
    except design_research.ResearchError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.delete("/api/design-research/{entry_id}")
def design_research_remove(entry_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import design_research

    return {"removed": design_research.remove(entry_id)}


@router.post("/api/design-research/{entry_id}/masterplan")
def design_research_to_masterplan(entry_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """Append the entry to the owner's DESIGN_MASTERPLAN.md, where Claude sessions read it."""
    import design_research
    from fastapi import HTTPException

    try:
        return design_research.add_to_masterplan(entry_id)
    except design_research.ResearchError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


# ---------------------------------------------------------------------------
# The notch assistant (equalize_assistant.py) and Ultra Fast (ultrafast.py) — owner, 2026-10-11
# ---------------------------------------------------------------------------

def _bad(error: Exception) -> Any:
    from fastapi import HTTPException

    return HTTPException(status_code=400, detail=str(error))


@router.get("/api/equalize/assistant")
def assistant_state(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return {"settings": ea.settings(), "agents": ea.agents()}


@router.put("/api/equalize/assistant")
def assistant_save(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return ea.update(body)


@router.get("/api/equalize/agents")
def assistant_agents(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return {"agents": ea.agents(), "catalog": ea.catalog()}


@router.post("/api/equalize/agents/drop")
def assistant_drop(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return ea.drop_agent(str(body.get("id") or ""), remove=bool(body.get("remove")))


@router.get("/api/equalize/agents/{agent_id}/work")
def assistant_work(agent_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return ea.work(agent_id)


@router.post("/api/equalize/tasks")
def assistant_task(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    try:
        return ea.start_task(str(body.get("agent") or "ichos"), str(body.get("task") or ""),
                             folder=str(body.get("folder") or ""), new_name=str(body.get("new_name") or ""),
                             app=str(body.get("app") or ""))
    except ValueError as error:
        raise _bad(error) from error


@router.get("/api/equalize/tasks/{job_id}")
def assistant_job(job_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    found = ea.job(job_id)
    if found is None:
        raise _bad(ValueError("No such task."))
    return found


@router.post("/api/equalize/tasks/{job_id}/stop")
def assistant_job_stop(job_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return {"stopped": ea.stop_job(job_id)}


@router.get("/api/equalize/files/{upload_id}")
def assistant_read_file(upload_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    try:
        return ea.read_file(upload_id)
    except (ValueError, OSError) as error:
        raise _bad(error) from error


@router.post("/api/equalize/intent")
def assistant_intent(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return ea.intent(str(body.get("text") or ""), has_file=bool(body.get("has_file")))


@router.post("/api/equalize/mail")
def assistant_mail(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    """The notch's Send button — the only way this sends."""
    import equalize_assistant as ea
    import email_client

    try:
        return ea.send_mail(str(body.get("to") or ""), str(body.get("subject") or ""), str(body.get("body") or ""),
                            [str(u) for u in body.get("upload_ids") or []])
    except (email_client.EmailError, ValueError) as error:
        raise _bad(error) from error


@router.post("/api/equalize/timers")
def assistant_timer(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return ea.add_timer(float(body.get("seconds") or 60), str(body.get("label") or ""))


@router.delete("/api/equalize/timers/{timer_id}")
def assistant_timer_remove(timer_id: str, _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return {"removed": ea.remove_timer(timer_id)}


@router.post("/api/equalize/voice")
def assistant_voice(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    return ea.set_voice(str(body.get("mode") or "default"), str(body.get("description") or ""),
                        body.get("sample") if isinstance(body.get("sample"), dict) else None)


@router.post("/api/equalize/avatar")
def assistant_avatar(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import equalize_assistant as ea

    if body.get("reset"):
        return ea.reset_avatar()
    keep = body.get("keep_personality")
    return ea.set_avatar(name=str(body.get("name") or ""), image=str(body.get("image") or ""),
                         avatar_id=str(body.get("avatar_id") or ""), personality=str(body.get("personality") or ""),
                         keep_personality=None if keep is None else bool(keep))


@router.get("/api/equalize/sound")
def assistant_sound(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import system_audio

    return system_audio.level()


@router.get("/api/ultrafast")
def ultrafast_status(_owner_user=Depends(_owner)) -> Dict[str, Any]:
    import ultrafast

    return ultrafast.status()


@router.post("/api/ultrafast")
def ultrafast_run(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import ultrafast

    return ultrafast.handle(str(body.get("text") or ""), dry_run=bool(body.get("dry_run")))


@router.post("/api/ultrafast/judge")
def ultrafast_judge(body: Dict[str, Any], _owner_user=Depends(_owner)) -> Dict[str, Any]:
    import ultrafast

    return ultrafast.judge(str(body.get("conversation") or ""), str(body.get("me") or "me"))
