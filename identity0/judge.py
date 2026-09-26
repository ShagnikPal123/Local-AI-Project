"""Pairwise judging: which of two answers is better, asked twice with the order swapped.

LLM judges prefer whichever answer they read first (position bias), so ``compare`` asks both ways
and only counts a winner when both readings agree; a disagreement is a tie. The judge is never one of
the two contestants, local models judge first (free, private, no quota), and the hourly budget in
``collab.JUDGE_BUDGET`` caps how often any of this runs. Nothing here raises: an unreadable or
missing verdict is "no verdict", never a guess.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from identity0 import collab

_JSON = re.compile(r"\{.*\}", re.S)

COMPARE_SYSTEM = (
    "detailed thinking off\nYou are a strict, fair judge of AI answers. Judge correctness first, then how "
    "completely and directly the answer helps the user, then clarity. Length is not quality. "
    'Reply with ONLY a JSON object: {"winner": "A" | "B" | "tie", "confidence": 0.0-1.0, "reason": "<one sentence>"}'
)
GRADE_SYSTEM = (
    "detailed thinking off\nYou grade one AI answer from 0 to 10 for correctness and usefulness. When a "
    'reference is given, judge against it. Reply with ONLY a JSON object: {"score": 0-10, "reason": "<one sentence>"}'
)


def _parse(text: str) -> Optional[Dict[str, Any]]:
    match = _JSON.search(text or "")
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def pick_judge(exclude: Sequence[str] = (), router: Any = None) -> Optional[str]:
    """The best available judge that is not a contestant: a local model first, then a free online one."""
    try:
        if router is None:
            from identity0.provider import shared_router

            router = shared_router()
        from identity0 import members as members_module

        pool = members_module.available(router) if router is not None else []
    except Exception:  # noqa: BLE001
        return None
    excluded = set(exclude)
    candidates = [m for m in pool if m.id not in excluded and m.provider != "self"]
    try:
        from identity0.state import get_settings

        local_only = bool(get_settings().get("shadow_local_only", True))
    except Exception:  # noqa: BLE001
        local_only = True
    local = [m for m in candidates if m.local]
    if local:
        return local[0].id
    if local_only:
        return None
    online = [m for m in candidates if m.free]
    return online[0].id if online else None


def _ask(judge: str, system: str, prompt: str, budget_s: float) -> Optional[Dict[str, Any]]:
    answer = collab.complete(judge, [{"role": "user", "content": prompt}], system=system, max_tokens=200,
                             temperature=0.0, timeout=budget_s)
    return _parse(answer["text"]) if answer["ok"] else None


def compare(question: str, a: str, b: str, *, context: str = "", exclude: Sequence[str] = (),
            budget_s: float = 30, judge: Optional[str] = None) -> Dict[str, Any]:
    verdict: Dict[str, Any] = {"winner": "tie", "confidence": 0.0, "reason": "", "by": "", "ok": False}
    judge = judge or pick_judge(exclude)
    if not judge:
        verdict["reason"] = "no judge available"
        return verdict
    if not collab.JUDGE_BUDGET.spend():
        verdict["reason"] = "judge budget for this hour is used up"
        return verdict
    # Both readings are real calls: an online judge takes two from the hour's allowance, not one.
    if not judge.startswith("ollama:") and not collab.API_BUDGET.spend(2):
        verdict["reason"] = "online budget for this hour is used up"
        return verdict
    verdict["by"] = judge
    head = f"Context (may be empty): {context[:1500]}\n\nUser request:\n{question[:3000]}\n\n"

    def frame(first: str, second: str) -> str:
        # Concatenation, not str.format: answers are full of braces (code, JSON).
        return head + "Answer A:\n" + first[:4000] + "\n\nAnswer B:\n" + second[:4000] + "\n\nWhich answer is better?"

    one = _ask(judge, COMPARE_SYSTEM, frame(a, b), budget_s)
    two = _ask(judge, COMPARE_SYSTEM, frame(b, a), budget_s)
    if not one or not two:
        verdict["reason"] = "the judge's reply could not be read"
        return verdict
    first = str(one.get("winner", "")).strip().upper()
    second = {"A": "B", "B": "A"}.get(str(two.get("winner", "")).strip().upper(), "TIE")
    verdict["ok"] = True
    if first == second and first in ("A", "B"):
        try:
            confidence = (float(one.get("confidence", 0.5)) + float(two.get("confidence", 0.5))) / 2
        except (TypeError, ValueError):
            confidence = 0.5
        verdict.update(winner=first.lower(), confidence=round(max(0.0, min(1.0, confidence)), 2),
                       reason=str(one.get("reason", ""))[:300])
    else:
        verdict.update(winner="tie", confidence=0.0,
                       reason="the two readings disagreed" if first != second else str(one.get("reason", ""))[:300])
    return verdict


def grade(question: str, answer: str, *, reference: str = "", rubric: str = "", budget_s: float = 30,
          judge: Optional[str] = None, exclude: Sequence[str] = ()) -> Dict[str, Any]:
    result: Dict[str, Any] = {"score": None, "reason": "", "by": "", "ok": False}
    judge = judge or pick_judge(exclude)
    if not judge:
        result["reason"] = "no judge available"
        return result
    if not judge.startswith("ollama:") and not collab.API_BUDGET.spend():
        result["reason"] = "online budget for this hour is used up"
        return result
    result["by"] = judge
    prompt = f"User request:\n{question[:3000]}\n\n"
    if reference:
        prompt += f"Reference answer:\n{reference[:2000]}\n\n"
    if rubric:
        prompt += f"Rubric:\n{rubric[:1000]}\n\n"
    prompt += f"Answer to grade:\n{answer[:4000]}"
    data = _ask(judge, GRADE_SYSTEM, prompt, budget_s)
    if not data:
        result["reason"] = "the judge's reply could not be read"
        return result
    try:
        result.update(score=max(0.0, min(10.0, float(data.get("score")))), reason=str(data.get("reason", ""))[:300],
                      ok=True)
    except (TypeError, ValueError):
        result["reason"] = "the judge gave no number"
    return result

