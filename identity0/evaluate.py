"""The honest scoreboard: the same questions to every model, checked the same way (Request S12).

"I want to ensure eventually it can have potential to pass other local and non local models." That
has to be measured, not claimed. Each suite item has a check that needs no model to grade it: expected
words, an exact number, a format rule, a Nyx tool-call shape, or Python that must parse and define a
function (parsed with ``ast``, never run). The same items go to Identity 0's own model, the local
teacher and the online members, and every run is appended to ``kahuna/scoreboard.jsonl`` as it was —
nothing is edited afterwards.
"""

from __future__ import annotations

import ast
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from identity0 import state

FILE = "scoreboard.jsonl"
#: Which domain each kind of question speaks for, so a run teaches the competence table something.
DOMAIN_OF = {"code": "code", "tools": "agents", "facts": "knowledge", "summary": "knowledge",
             "math": "chat", "reasoning": "chat", "instructions": "chat", "identity": "chat"}


def _words(*words: str) -> Callable[[str], float]:
    def check(answer: str) -> float:
        text = answer.lower()
        return sum(1 for w in words if w in text) / len(words)
    return check


def _number(value: float) -> Callable[[str], float]:
    def check(answer: str) -> float:
        found = [float(n.replace(",", "")) for n in re.findall(r"-?\d[\d,]*\.?\d*", answer)]
        return 1.0 if any(abs(n - value) < 1e-6 for n in found) else 0.0
    return check


def _word_count(n: int) -> Callable[[str], float]:
    def check(answer: str) -> float:
        return 1.0 if len(re.findall(r"[A-Za-z']+", answer)) == n else 0.0
    return check


def _python_function(name: str) -> Callable[[str], float]:
    def check(answer: str) -> float:
        match = re.search(r"```(?:python)?\s*(.*?)```", answer, re.S)
        code = match.group(1) if match else answer
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return 0.0
        return 1.0 if any(isinstance(n, ast.FunctionDef) and n.name == name for n in ast.walk(tree)) else 0.5
    return check


def _tool_call(tool: str) -> Callable[[str], float]:
    def check(answer: str) -> float:
        try:
            from tools import TOOL_REGISTRY

            calls = TOOL_REGISTRY.parse_tool_calls(answer)
        except Exception:  # noqa: BLE001
            calls = []
        return 1.0 if any(name == tool for name, _ in calls) else 0.0
    return check


TOOL_HINT = ('You can call tools by writing exactly <tool_call>{"name": "TOOL", "arguments": {...}}</tool_call>. '
             "Available: search_web(query), get_weather(city).")

SUITES: Dict[str, List[Dict[str, Any]]] = {
    "core": [
        {"cat": "facts", "q": "What is the capital of France?", "check": _words("paris")},
        {"cat": "facts", "q": "Which planet is known as the Red Planet?", "check": _words("mars")},
        {"cat": "facts", "q": "What gas do plants take in for photosynthesis?", "check": _words("carbon dioxide")},
        {"cat": "facts", "q": "Who wrote Pride and Prejudice?", "check": _words("austen")},
        {"cat": "facts", "q": "What is the largest ocean on Earth?", "check": _words("pacific")},
        {"cat": "facts", "q": "What is H2O commonly called?", "check": _words("water")},
        {"cat": "math", "q": "What is 17 times 23? Answer with the number.", "check": _number(391)},
        {"cat": "math", "q": "A shirt costs $40 and is 25% off. What is the sale price in dollars?", "check": _number(30)},
        {"cat": "math", "q": "If a train goes 60 km in 45 minutes, how many km does it go in one hour at that speed?", "check": _number(80)},
        {"cat": "math", "q": "What is the square root of 144?", "check": _number(12)},
        {"cat": "reasoning", "q": "Tom is taller than Ann. Ann is taller than Joe. Who is the shortest?", "check": _words("joe")},
        {"cat": "reasoning", "q": "If all bloops are razzies and all razzies are lazzies, are all bloops lazzies? Answer yes or no.", "check": _words("yes")},
        {"cat": "instructions", "q": "Reply with exactly three words describing the sea.", "check": _word_count(3)},
        {"cat": "instructions", "q": "Answer in lowercase only: what color is the sky on a clear day?",
         "check": lambda a: 1.0 if a.strip() and a.strip() == a.strip().lower() and "blue" in a.lower() else 0.0},
        {"cat": "code", "q": "Write a Python function named add that returns the sum of two numbers.", "check": _python_function("add")},
        {"cat": "code", "q": "Write a Python function named is_even(n) that returns True for even numbers.", "check": _python_function("is_even")},
        {"cat": "tools", "system": TOOL_HINT, "q": "What's the weather in Chicago right now?", "check": _tool_call("get_weather")},
        {"cat": "tools", "system": TOOL_HINT, "q": "Search the web for the latest news about fusion energy.", "check": _tool_call("search_web")},
        {"cat": "identity", "q": "In one sentence, what are you?", "check": lambda a: 1.0 if len(a.strip()) > 10 else 0.0},
        {"cat": "summary", "q": "Summarize in one sentence: The meeting moved to Friday because the client was sick on Tuesday.",
         "check": _words("friday")},
    ],
}


def suites() -> Dict[str, Dict[str, Any]]:
    return {name: {"items": len(items), "categories": sorted({i["cat"] for i in items})} for name, items in SUITES.items()}


def run(member: str, suite: str = "core", limit: int = 0,
        complete: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    if suite not in SUITES:
        raise ValueError(f"unknown suite {suite}")
    if complete is None:
        from identity0.collab import complete as complete_fn

        complete = complete_fn
    items = SUITES[suite][:limit] if limit else SUITES[suite]
    per: Dict[str, List[float]] = {}
    times: List[float] = []
    details = []
    for item in items:
        messages = ([{"role": "system", "content": item["system"]}] if item.get("system") else []) + \
                   [{"role": "user", "content": item["q"]}]
        answer = complete(member, messages, max_tokens=300, temperature=0.0, timeout=90)
        text = str(answer.get("text", "")) if answer.get("ok") else ""
        score = float(item["check"](text)) if text else 0.0
        per.setdefault(item["cat"], []).append(score)
        times.append(float(answer.get("ms", 0)))
        details.append({"q": item["q"][:80], "score": score, "answer": text[:160]})
    total = [s for scores in per.values() for s in scores]
    row = {"ts": time.time(), "member": member, "suite": suite, "n": len(total),
           "score": round(sum(total) / max(1, len(total)), 3),
           "by_category": {k: round(sum(v) / len(v), 3) for k, v in per.items()},
           "avg_ms": round(sum(times) / max(1, len(times))), "details": details}
    with open(state.path(FILE), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    _teach(member, per)
    return row


def _teach(member: str, per: Dict[str, List[float]]) -> None:
    """Tell the competence table what the exam showed, per domain (never fatal)."""
    try:
        from identity0 import competence

        by_domain: Dict[str, List[float]] = {}
        for category, scores in per.items():
            by_domain.setdefault(DOMAIN_OF.get(category, "chat"), []).extend(scores)
        for domain, scores in by_domain.items():
            competence.record_exam(domain, member, sum(scores) / len(scores))
    except Exception:  # noqa: BLE001 - a scoreboard run is worth keeping even if this fails
        pass


def scoreboard(limit: int = 50) -> List[Dict[str, Any]]:
    """The latest run per (member, suite), best first."""
    try:
        lines = state.path(FILE).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    latest: Dict[tuple, Dict[str, Any]] = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        latest[(row["member"], row["suite"])] = {k: v for k, v in row.items() if k != "details"}
    return sorted(latest.values(), key=lambda r: -r["score"])[:limit]
