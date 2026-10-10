"""The chat's workbench (redesign v3, owner 2026-10-10: "it can open files, emails, texts, whatsapp, docs … drag it";
"add functions for math, if I want a graph it makes it, and more").

Backs the windows the chat opens beside itself: a file preview, a mail reader, and a graph plotter with symbolic
maths. Owner-only and read-only — nothing here writes, sends or deletes. Maths never ``eval``s raw text: plotting goes
through math_engine's AST evaluator, and symbolic work through sympy only after every word in the expression has been
checked against a short list of known functions and variables.
"""

from __future__ import annotations

import base64
import math
import mimetypes
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()

TEXT_LIMIT = 400_000
IMAGE_LIMIT = 8_000_000


def _owner_dep():
    def dependency(http_request: Request, authorization: Optional[str] = Header(default=None)) -> Any:
        from server import require_local_owner

        return require_local_owner(http_request, authorization)
    return Depends(dependency)


Owner = _owner_dep()


# --- files ---------------------------------------------------------------------------------------------------


def preview_file(path: str) -> Dict[str, Any]:
    target = Path(path).expanduser()
    if not target.is_file():
        raise FileNotFoundError(f"No file at {target}.")
    size = target.stat().st_size
    mime = mimetypes.guess_type(target.name)[0] or ""
    base = {"name": target.name, "path": str(target), "size": size, "mime": mime}
    if mime.startswith("image/") and size <= IMAGE_LIMIT:
        data = base64.b64encode(target.read_bytes()).decode("ascii")
        return {**base, "kind": "image", "data_url": f"data:{mime};base64,{data}"}
    raw = target.read_bytes()[:TEXT_LIMIT]
    if b"\x00" in raw[:4096]:
        return {**base, "kind": "binary", "text": ""}
    return {**base, "kind": "text", "text": raw.decode("utf-8", errors="replace"), "truncated": size > TEXT_LIMIT}


@router.get("/api/files/preview")
def files_preview(path: str, _owner=Owner) -> Dict[str, Any]:
    try:
        return preview_file(path)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(status_code=400, detail=f"Could not read it: {error}") from error


# --- email ---------------------------------------------------------------------------------------------------


@router.get("/api/email/list")
def email_list(query: str = "", limit: int = 20, account: str = "", _owner=Owner) -> Dict[str, Any]:
    import email_client

    try:
        return {"messages": email_client.list_emails(account, "INBOX", query, False, max(1, min(50, limit)))}
    except Exception as error:  # noqa: BLE001 - no account / offline reads as a sentence
        raise HTTPException(status_code=400, detail=str(error)[:300]) from error


@router.get("/api/email/message/{message_id}")
def email_message(message_id: str, account: str = "", _owner=Owner) -> Dict[str, Any]:
    import email_client

    try:
        return email_client.read_email(message_id, account)
    except Exception as error:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(error)[:300]) from error


# --- maths ---------------------------------------------------------------------------------------------------

ALLOWED_WORDS = {
    "x", "y", "z", "t", "n", "a", "b", "c", "k", "pi", "e", "E", "I", "oo",
    "sin", "cos", "tan", "cot", "sec", "csc", "asin", "acos", "atan", "sinh", "cosh", "tanh",
    "log", "ln", "exp", "sqrt", "abs", "Abs", "floor", "ceil", "factorial",
}
_WORD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def check_expression(expression: str) -> str:
    text = (expression or "").strip().replace("^", "**")
    if not text or len(text) > 300:
        raise ValueError("Give an expression up to 300 characters.")
    if re.search(r"__|[;\[\]{}'\"`\\@!$#]", text):
        raise ValueError("That expression has characters maths does not need.")
    for word in _WORD.findall(text):
        if word not in ALLOWED_WORDS:
            raise ValueError(f"Unknown name '{word}'. Use x as the variable and functions like sin, log, sqrt.")
    return text


def sample(expressions: List[str], x_min: float, x_max: float, points: int = 400) -> List[Dict[str, Any]]:
    from math_engine import evaluate

    if not (math.isfinite(x_min) and math.isfinite(x_max)) or x_max <= x_min:
        raise ValueError("The range must go from a smaller to a larger number.")
    points = max(20, min(2000, int(points)))
    out = []
    for expression in expressions[:6]:
        text = check_expression(expression)
        ys: List[Optional[float]] = []
        for i in range(points):
            x = x_min + (x_max - x_min) * i / (points - 1)
            try:
                y = float(evaluate(text.replace("**", "^"), {"x": x}))
                ys.append(y if math.isfinite(y) else None)
            except Exception:  # noqa: BLE001 - outside the domain (log of a negative, 1/0): a gap in the line
                ys.append(None)
        out.append({"expression": expression, "ys": ys})
    return out


def symbolic(op: str, expression: str, variable: str = "x", extra: str = "") -> Dict[str, Any]:
    import sympy

    text = check_expression(expression)
    if variable not in ALLOWED_WORDS:
        raise ValueError("Use x, y, z, t or n as the variable.")
    locals_ = {"ln": sympy.log, "e": sympy.E, "pi": sympy.pi, "abs": sympy.Abs}
    if "=" in text:
        left, right = text.split("=", 1)
        expr = sympy.sympify(left, locals=locals_) - sympy.sympify(right, locals=locals_)
        op = op or "solve"
    else:
        expr = sympy.sympify(text, locals=locals_)
    var = sympy.Symbol(variable)
    if op == "derivative":
        result = sympy.diff(expr, var)
    elif op == "integral":
        result = sympy.integrate(expr, var)
    elif op == "solve":
        result = sympy.solve(expr, var)
    elif op == "simplify":
        result = sympy.simplify(expr)
    elif op == "factor":
        result = sympy.factor(expr)
    elif op == "expand":
        result = sympy.expand(expr)
    elif op == "limit":
        point = sympy.sympify(check_expression(extra or "0"), locals=locals_)
        result = sympy.limit(expr, var, point)
    elif op == "series":
        result = sympy.series(expr, var, 0, 6).removeO()
    else:
        raise ValueError("op must be derivative, integral, solve, simplify, factor, expand, limit or series.")
    return {"op": op, "input": expression, "result": str(result), "latex": sympy.latex(result)}


class SampleBody(BaseModel):
    expressions: List[str]
    x_min: float = -10
    x_max: float = 10
    points: int = 400


class SymbolicBody(BaseModel):
    op: str
    expression: str
    variable: str = "x"
    extra: str = ""


@router.post("/api/math/sample")
def math_sample(body: SampleBody, _owner=Owner) -> Dict[str, Any]:
    try:
        return {"curves": sample(body.expressions, body.x_min, body.x_max, body.points)}
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/api/math/symbolic")
def math_symbolic(body: SymbolicBody, _owner=Owner) -> Dict[str, Any]:
    try:
        return symbolic(body.op, body.expression, body.variable, body.extra)
    except Exception as error:  # noqa: BLE001 - sympy raises many kinds; the owner reads one sentence
        raise HTTPException(status_code=400, detail=str(error)[:300]) from error


# --- chat tools ----------------------------------------------------------------------------------------------


def tool_plot_function(expressions: str, x_min: float = -10, x_max: float = 10, title: str = "") -> str:
    exprs = [e.strip() for e in re.split(r"[\n;]+|,(?![^()]*\))", expressions or "") if e.strip()][:6]
    try:
        for e in exprs:
            check_expression(e)
    except ValueError as error:
        return f"Error: {error}"
    if not exprs:
        return "Error: give at least one function of x, e.g. sin(x) or x^2 - 3."
    try:
        from agent_events import publish_ui

        publish_ui("ui.open_window", kind="graph", title=title or "Graph",
                   props={"expressions": exprs, "xMin": float(x_min), "xMax": float(x_max)})
    except Exception:  # noqa: BLE001
        pass
    return (f"Opened a graph of {', '.join(exprs)} from x={x_min} to {x_max} beside the chat; the owner can zoom, pan "
            "and add curves there. Mention anything notable (roots, maxima) briefly — do not draw it in text.")


def tool_math_symbolic(op: str, expression: str, variable: str = "x", extra: str = "") -> str:
    try:
        out = symbolic(op, expression, variable, extra)
    except Exception as error:  # noqa: BLE001
        return f"Error: {error}"
    return f"{out['op']} of {out['input']}: {out['result']}  (LaTeX: {out['latex']})"


def tool_open_file(path: str) -> str:
    target = Path(path or "").expanduser()
    if not target.is_file():
        return f"Error: no file at {target}."
    try:
        from agent_events import publish_ui

        publish_ui("ui.open_window", kind="file", title=target.name, props={"path": str(target)})
    except Exception:  # noqa: BLE001
        pass
    return f"Opened {target.name} in a window beside the chat."


def register_workbench_tools(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="plot_function",
        description="Draw a graph of one or more functions of x in an interactive window beside the chat (zoom, pan, "
                    "add curves). Use whenever the owner wants a graph or plot of a function. Write ^ for powers.",
        parameters=[ToolParam("expressions", "string", "Functions of x, separated by ';' — e.g. 'sin(x); x^2/10'"),
                    ToolParam("x_min", "number", "Left end of x", required=False),
                    ToolParam("x_max", "number", "Right end of x", required=False),
                    ToolParam("title", "string", "Window title", required=False)],
        handler=tool_plot_function, category="general", label="Drawing a graph",
    )
    registry.register(
        name="math_symbolic",
        description="Exact symbolic maths with sympy: derivative, integral, solve (also 'lhs = rhs'), simplify, "
                    "factor, expand, limit (extra = the point), series. Use for calculus and algebra.",
        parameters=[ToolParam("op", "string", "The operation",
                              enum_values=["derivative", "integral", "solve", "simplify", "factor", "expand", "limit", "series"]),
                    ToolParam("expression", "string", "The expression, e.g. x^2*sin(x)"),
                    ToolParam("variable", "string", "Variable (default x)", required=False),
                    ToolParam("extra", "string", "For limit: the point x approaches", required=False)],
        handler=tool_math_symbolic, category="general", label="Working it out exactly",
    )
    registry.register(
        name="open_file_window",
        description="Show a file from this PC (document, code, text or image) in a window beside the chat, so the "
                    "owner sees what you are reading or referring to.",
        parameters=[ToolParam("path", "string", "Full path of the file")],
        handler=tool_open_file, category="files.read", label=lambda a: f"Opening {Path(str(a.get('path', ''))).name}",
    )
