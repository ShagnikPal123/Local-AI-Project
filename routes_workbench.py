"""The chat's workbench (redesign v3, owner 2026-10-10: "it can open files, emails, texts, whatsapp, docs … drag it";
"add functions for math, if I want a graph it makes it, and more").

Backs the windows the chat opens beside itself: a file preview, a mail reader, and a graph plotter with symbolic
maths. Owner-only and read-only — nothing here writes, sends or deletes. Maths never ``eval``s raw text: plotting goes
through math_engine's AST evaluator, and symbolic work through sympy only after every word in the expression has been
checked against a short list of known functions and variables.
"""

from __future__ import annotations

import base64
import json
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

    register_s2c_tool(registry)
    register_quiz_tool(registry)

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


# --- screenshot → code (owner, 2026-10-10: "https://github.com/abi/screenshot-to-code. Add this to yourself then to
# the AI") — the method adapted from abi/screenshot-to-code (MIT, (c) 2023 Abi Raja): faithful one-file pages, repeated
# items in full, placeholder images, pinned CDN versions. The page is previewed in a sandboxed iframe (srcdoc, no
# same-origin), so generated scripts can never reach Ichos's own storage.

S2C_STACKS = {
    "html_tailwind": "HTML + Tailwind. Include <script src=\"https://cdn.tailwindcss.com\"></script>.",
    "html_css": "Plain HTML, CSS and JS only. Do not use Tailwind.",
    "react_tailwind": ("React + Tailwind on one standalone page: react@18.0.0 and react-dom@18.0.0 UMD from "
                       "cdn.jsdelivr.net, https://unpkg.com/@babel/standalone@7.25.6/babel.min.js (exactly this version), "
                       "and https://cdn.tailwindcss.com."),
    "vue_tailwind": ("Vue 3 global build from https://registry.npmmirror.com/vue/3.3.11/files/dist/vue.global.js with "
                     "createApp, plus https://cdn.tailwindcss.com."),
    "bootstrap": "Bootstrap 5.3.2 from cdn.jsdelivr.net.",
}

S2C_RULES = (
    "You are an expert front-end developer. Build a single, complete HTML file that looks exactly like the screenshot.\n"
    "- Match it exactly: the same text (verbatim), order, layout, spacing, colours, font sizes, radii and shadows.\n"
    "- Repeat repeated elements in full: every list item, card and link. Never write placeholder comments such as "
    "'<!-- add more items -->'.\n"
    "- For images use https://placehold.co/WIDTHxHEIGHT with an alt text that describes the original image. Never embed "
    "the screenshot itself.\n"
    "- Icons: Font Awesome 5.15.3 (https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.3/css/all.min.css). Fonts: "
    "Google Fonts are fine.\n"
    "- Accessible: real headings, labelled inputs, alt text, visible focus.\n"
    "Reply with the full HTML file only, starting with <!DOCTYPE html>, no explanation."
)


def _html_from(text: str) -> str:
    fenced = re.search(r"```(?:html)?\s*(.*?)```", text or "", re.S)
    body = fenced.group(1) if fenced else (text or "")
    start = body.lower().find("<!doctype")
    if start < 0:
        start = body.lower().find("<html")
    return body[start:].strip() if start >= 0 else body.strip()


def _s2c_dir() -> Path:
    from paths import data_path

    folder = data_path("screenshot_code")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def screenshot_to_code(image: bytes, mime: str, stack: str = "html_tailwind", notes: str = "",
                       current: str = "", instruction: str = "", ask: Any = None) -> Dict[str, Any]:
    if stack not in S2C_STACKS:
        raise ValueError(f"Stack must be one of {', '.join(S2C_STACKS)}.")
    prompt = f"{S2C_RULES}\n\nStack: {S2C_STACKS[stack]}"
    if notes.strip():
        prompt += f"\nThe owner adds: {notes.strip()[:800]}"
    if current.strip() and instruction.strip():
        prompt += (f"\n\nThis is the current code:\n{current[:60000]}\n\nChange it as asked and return the whole updated "
                   f"file: {instruction.strip()[:800]}")
    if ask is None:
        from model_roles import MODEL_ROLES

        text = MODEL_ROLES.run("image_check", prompt, images=[(image, mime or "image/png")], max_tokens=12000).text
    else:
        text = ask(prompt, image, mime)
    html = _html_from(text)
    if "<" not in html:
        raise ValueError("The model did not return HTML. Try again, or add a note about what the image shows.")
    import uuid

    job_id = uuid.uuid4().hex[:10]
    (_s2c_dir() / f"{job_id}.html").write_text(html, encoding="utf-8")
    return {"id": job_id, "stack": stack, "html": html}


class S2CBody(BaseModel):
    upload_id: str = ""
    path: str = ""
    stack: str = "html_tailwind"
    notes: str = ""
    current: str = ""
    instruction: str = ""


def _image_from(body: "S2CBody") -> tuple:
    if body.upload_id:
        import uploads

        record = uploads.get_upload(body.upload_id)
        if not record:
            raise ValueError("That upload is gone; drop the image again.")
        return Path(record["path"]).read_bytes(), record.get("mime") or "image/png"
    target = Path(body.path).expanduser()
    if not target.is_file():
        raise ValueError("Give an image: drop one in, or a file path.")
    return target.read_bytes(), mimetypes.guess_type(target.name)[0] or "image/png"


@router.post("/api/s2c")
def s2c(body: S2CBody, _owner=Owner) -> Dict[str, Any]:
    try:
        image, mime = _image_from(body)
        return screenshot_to_code(image, mime, body.stack, body.notes, body.current, body.instruction)
    except Exception as error:  # noqa: BLE001 - no vision model, bad image: one sentence
        raise HTTPException(status_code=400, detail=str(error)[:300]) from error


class S2CSave(BaseModel):
    path: str
    html: str


@router.post("/api/s2c/save")
def s2c_save(body: S2CSave, _owner=Owner) -> Dict[str, Any]:
    """Save the generated page where the owner says (a .html file), never over an existing file."""
    target = Path(body.path).expanduser()
    if target.suffix.lower() not in (".html", ".htm") or target.exists():
        raise HTTPException(status_code=400, detail="Give a new .html file path (existing files are never overwritten).")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.html, encoding="utf-8")
    return {"saved": str(target)}


def tool_screenshot_to_code(path: str = "", stack: str = "html_tailwind", notes: str = "") -> str:
    try:
        from agent_events import publish_ui

        publish_ui("ui.open_window", kind="s2c", title="Screenshot to Code",
                   props={"path": path, "stack": stack, "notes": notes})
    except Exception:  # noqa: BLE001
        pass
    return ("Opened Screenshot to Code beside the chat" + (f" with {Path(path).name}" if path else "") +
            ". It writes the page with the vision model and previews it; the owner can refine and save it there.")


def register_s2c_tool(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="screenshot_to_code",
        description="Turn a screenshot or mockup of a UI into a working web page (HTML + Tailwind, HTML/CSS, React, "
                    "Vue or Bootstrap) in a window beside the chat, with a live preview, refine box and save. Use when "
                    "the owner shares an image of a UI and wants it built or cloned.",
        parameters=[ToolParam("path", "string", "Image file path, if known", required=False),
                    ToolParam("stack", "string", "html_tailwind, html_css, react_tailwind, vue_tailwind or bootstrap",
                              required=False, enum_values=list(S2C_STACKS)),
                    ToolParam("notes", "string", "Anything the owner said about the design", required=False)],
        handler=tool_screenshot_to_code, category="general", label="Opening Screenshot to Code",
    )


# --- quizzes and flashcards (owner, 2026-10-10: "allow for the creation of quizzes similar to gemini so it opens on the
# right as a bar the user can use and they can have flashcards, the AI analyses the time they take and answers") -----


def build_quiz(topic: str, kind: str = "quiz", count: int = 8, notes: str = "", ask: Any = None) -> Dict[str, Any]:
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("Say what the quiz is about.")
    kind = kind if kind in ("quiz", "flashcards", "both") else "quiz"
    count = max(3, min(20, int(count or 8)))
    prompt = (f"Make a study set about: {topic}\n{('Use this material: ' + notes[:6000]) if notes.strip() else ''}\n"
              f"Reply with JSON only: {{\"title\": \"<short>\", \"questions\": [{{\"q\": \"…\", \"choices\": [\"…\", \"…\", "
              f"\"…\", \"…\"], \"answer\": \"<exactly one of the choices>\", \"explain\": \"<one sentence>\"}}], "
              f"\"cards\": [{{\"front\": \"…\", \"back\": \"…\"}}]}}. "
              + ("Give " + str(count) + " multiple-choice questions, mixing easy and hard, and no cards. " if kind == "quiz" else "")
              + ("Give " + str(count) + " flashcards and no questions. " if kind == "flashcards" else "")
              + ("Give " + str(count) + " questions and " + str(count) + " flashcards. " if kind == "both" else "")
              + "Facts must be correct; skip anything you are unsure of.")
    if ask is None:
        from agent_runtime import _router

        reply, _provider = _router().chat([{"role": "user", "content": prompt}])
    else:
        reply = ask(prompt)
    match = re.search(r"\{.*\}", reply or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except ValueError:
        data = {}
    questions = []
    for item in data.get("questions") or []:
        if not isinstance(item, dict) or not item.get("q") or not item.get("answer"):
            continue
        choices = [str(c)[:200] for c in (item.get("choices") or [])][:6]
        answer = str(item["answer"])[:200]
        if choices and answer not in choices:
            continue
        questions.append({"q": str(item["q"])[:400], "choices": choices, "answer": answer,
                          "explain": str(item.get("explain", ""))[:400]})
    cards = [{"front": str(c.get("front", ""))[:300], "back": str(c.get("back", ""))[:400]}
             for c in (data.get("cards") or []) if isinstance(c, dict) and c.get("front") and c.get("back")]
    if not questions and not cards:
        raise ValueError("The model did not return a usable quiz. Try a more specific topic.")
    return {"title": str(data.get("title") or topic)[:80], "questions": questions[:count], "cards": cards[:count]}


def tool_make_quiz(topic: str, kind: str = "quiz", count: int = 8, notes: str = "") -> str:
    try:
        quiz = build_quiz(topic, kind, count, notes)
    except Exception as error:  # noqa: BLE001
        return f"Error: {error}"
    try:
        from agent_events import publish_ui

        publish_ui("ui.open_window", kind="quiz", title=quiz["title"], props=quiz)
    except Exception:  # noqa: BLE001
        pass
    return (f"Opened '{quiz['title']}' as a bar on the right: {len(quiz['questions'])} questions, {len(quiz['cards'])} "
            "flashcards. It times every answer; when the owner finishes it sends the results here — then analyse what "
            "they know, what they guessed (fast but wrong, slow but right) and what to review. Do not list the questions in chat.")


def register_quiz_tool(registry: Any) -> None:
    from tools import ToolParam

    registry.register(
        name="make_quiz",
        description="Make a quiz (multiple choice) and/or flashcards on a topic; they open as a bar on the right where "
                    "the owner answers, timed. Use when the owner asks to be quizzed, tested, or wants flashcards.",
        parameters=[ToolParam("topic", "string", "What to quiz on"),
                    ToolParam("kind", "string", "quiz, flashcards or both", required=False,
                              enum_values=["quiz", "flashcards", "both"]),
                    ToolParam("count", "number", "How many (3-20)", required=False),
                    ToolParam("notes", "string", "Material to quiz from (notes, a chapter), if any", required=False)],
        handler=tool_make_quiz, category="general", label="Making a quiz",
    )
