"""The Predict tab's routes (predict.py)."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server_auth import RequireChat

router = APIRouter()


class Seed(BaseModel):
    kind: str = "text"
    value: str = ""


class StartBody(BaseModel):
    question: str
    scale: str = "quick"
    seeds: List[Seed] = []


class TextBody(BaseModel):
    text: str = ""


class ChatBody(BaseModel):
    who: str = "report"
    question: str


def _job(job_id: str) -> Dict[str, Any]:
    import predict

    job = predict.load(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No such prediction.")
    return job


@router.get("/api/predict/scales")
def scales(_user=RequireChat) -> Dict[str, Any]:
    import predict

    return {"scales": [{"id": k, **v, "calls": predict.estimate_calls(k)} for k, v in predict.SCALES.items()]}


@router.get("/api/predict/jobs")
def jobs(_user=RequireChat) -> Dict[str, Any]:
    import predict

    return {"jobs": predict.list_jobs()}


@router.post("/api/predict/jobs")
def start(body: StartBody, _user=RequireChat) -> Dict[str, Any]:
    import predict

    try:
        return predict.start(body.question, [s.model_dump() for s in body.seeds], body.scale)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/api/predict/jobs/{job_id}")
def job(job_id: str, _user=RequireChat) -> Dict[str, Any]:
    import predict

    return predict.summary(_job(job_id))


@router.get("/api/predict/jobs/{job_id}/agents/{agent_id}")
def agent(job_id: str, agent_id: str, _user=RequireChat) -> Dict[str, Any]:
    found = next((a for a in _job(job_id).get("agents", []) if a["id"] == agent_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="No such agent.")
    return found


@router.post("/api/predict/jobs/{job_id}/chat")
def ask(job_id: str, body: ChatBody, _user=RequireChat) -> Dict[str, Any]:
    import predict

    _job(job_id)
    try:
        return {"answer": predict.chat(job_id, body.who, body.question)}
    except KeyError as error:
        raise HTTPException(status_code=404, detail="No such agent.") from error


@router.post("/api/predict/jobs/{job_id}/{action}")
def control(job_id: str, action: str, body: TextBody = TextBody(), _user=RequireChat) -> Dict[str, Any]:
    import predict

    _job(job_id)
    if action == "pause":
        predict.pause(job_id)
    elif action == "resume":
        return predict.resume(job_id)
    elif action == "stop":
        predict.stop(job_id)
    elif action == "inject":
        try:
            return predict.inject(job_id, body.text)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
    else:
        raise HTTPException(status_code=404, detail="Unknown action.")
    return predict.summary(_job(job_id))


try:  # a run that was mid-flight when the engine stopped is shown as paused, ready to resume
    import predict as _predict

    _predict.recover()
except Exception:  # noqa: BLE001
    pass
