"""Study actions for the Notes tab: the AI side of Request G13.

Each action is one model call through the "study notes" role (so the owner can
point it at any provider in Keys & Models, and the answer says which model did
it). Text actions return Markdown; quizzes, flashcards and step-by-step
solutions return JSON that is validated into a spec here and rendered by the
UI — the model never produces executable anything (invariant 2).

Drawings go to the image-check role: handwriting, equations and diagrams come
back as Markdown notes.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

SYSTEM = (
    "You are Nyx's study partner for a college student. Be accurate and clear. Use the student's own material first; "
    "when you add facts beyond it, keep them standard textbook knowledge and say so briefly. Write math with plain "
    "symbols or LaTeX between $…$. Never invent citations, page numbers or quotes."
)

TEXT_ACTIONS: Dict[str, Tuple[str, str]] = {
    "detail": ("More detail", "Rewrite these notes with more detail: explain each point, add a short example or analogy, define "
               "technical terms the first time they appear, and keep the original headings and order. Markdown."),
    "organize": ("Organize into notes", "Turn this raw material (it may be a lecture transcript) into clean study notes: a title, "
                 "headings per topic, bullet key points, **bold** key terms with one-line definitions, worked examples "
                 "where the material has them, and a final 'Questions to review' list. Remove filler and repetition. Markdown."),
    "summarize": ("Summary", "Summarize in 5–8 bullet points, most important first, then one sentence on how the ideas connect. Markdown."),
    "clean": ("Clean transcript", "Clean this speech-to-text transcript: fix punctuation, obvious mis-heard words and "
              "paragraphing. Keep the speaker's meaning and wording otherwise. Mark anything unclear as [unclear]. Plain text."),
    "glossary": ("Key terms", "List the key terms in this material as a Markdown table with columns Term | Definition | Example. "
                 "Definitions one sentence each."),
    "study_guide": ("Study guide", "Make a study guide: learning objectives, an outline of the material, the 5 most important "
                    "concepts explained simply, common mistakes to avoid, and a short self-check list. Markdown."),
    "exam": ("Likely exam questions", "Write 8 questions an instructor would likely ask about this material — a mix of recall, "
             "application and explain-why — each followed by a concise model answer. Markdown."),
    "ask": ("Answer", "Answer the student's question using the material. If the material doesn't cover it, say so and answer "
            "from standard knowledge, clearly labelled. Markdown."),
    "cite": ("Citation", "Format a citation for the source the student describes in both APA 7 and MLA 9. If required details "
             "are missing, show the citation with placeholders like [Year] and list what to look up. Markdown."),
    "study_plan": ("Study plan", "Make a day-by-day study plan up to the exam date the student gives, using spaced review and "
                   "practice testing, 45–90 minute sessions, and a light final day. Markdown table plus short tips."),
    # Slides (Project Null N89). A deck is mostly headings: the work is filling in what the
    # lecturer said around them, which is why the speaker notes are handed over too.
    "slides_notes": ("Detailed notes", "Turn these lecture slides into the detailed notes a student would want: follow the "
                     "deck's own order and section headings, and for each slide write what it is actually saying in full "
                     "sentences — expand the bullet points, define every term the first time, add the worked example or "
                     "analogy the lecturer would give, and use the speaker notes where they are given. Keep the slide "
                     "numbers as references like (slides 4–6). End with 'Worth memorising' and 'Likely to be examined'. Markdown."),
    "slides_questions": ("Questions on this part", "Write questions on exactly this part of the deck: 6–10 of them, ordered "
                         "easy to hard, mixing recall, 'explain why' and one application problem. After each question give a "
                         "short model answer and the slide number it comes from. Markdown."),
    "custom": ("Study tool", "Make exactly what the student asks for from this material. Use the material first; say plainly "
               "if it does not contain what they asked about. Markdown, with headings if it is long."),
}

SPEC_ACTIONS = ("quiz", "flashcards", "steps")


class StudyError(ValueError):
    """The model could not produce usable study material; the message says why."""


def _run(prompt: str, max_tokens: int = 2400) -> Tuple[str, str]:
    from model_roles import MODEL_ROLES

    run = MODEL_ROLES.run("study_notes", prompt, system=SYSTEM, max_tokens=max_tokens)
    return run.text, run.label


def _material(title: str, body: str, selection: str = "") -> str:
    text = (selection or body or "").strip()
    if not text:
        raise StudyError("There is nothing in this note yet — write, dictate or record something first.")
    return f"Material ({'selected part of ' if selection else ''}note “{title}”):\n\"\"\"\n{text[:60000]}\n\"\"\""


def _json_block(text: str) -> Any:
    from tools import _loads_lenient

    start, end = text.find("{"), text.rfind("}")
    return _loads_lenient(text[start:end + 1]) if start != -1 and end > start else None


def _clean_quiz(data: Any) -> Dict[str, Any]:
    questions: List[Dict[str, Any]] = []
    for raw in (data or {}).get("questions", []) if isinstance(data, dict) else []:
        if not isinstance(raw, dict) or not str(raw.get("question", "")).strip():
            continue
        kind = str(raw.get("type", "mc")).lower()
        q: Dict[str, Any] = {"question": str(raw["question"]).strip()[:600], "explanation": str(raw.get("explanation", "")).strip()[:800]}
        if kind in ("mc", "multiple_choice", "multiple-choice"):
            options = [str(o).strip()[:300] for o in raw.get("options", []) if str(o).strip()][:6]
            answer = raw.get("answer")
            if isinstance(answer, int) and 0 <= answer < len(options):
                answer = options[answer]
            answer = str(answer or "").strip()
            match = next((o for o in options if o.lower() == answer.lower()), None)
            if len(options) < 2 or match is None:
                continue
            q.update(type="mc", options=options, answer=match)
        elif kind in ("tf", "true_false", "true-false", "truefalse"):
            answer = raw.get("answer")
            if isinstance(answer, str):
                answer = answer.strip().lower() in ("true", "t", "yes")
            q.update(type="tf", answer=bool(answer))
        else:
            if not str(raw.get("answer", "")).strip():
                continue
            q.update(type="short", answer=str(raw["answer"]).strip()[:800])
        questions.append(q)
    if len(questions) < 2:
        raise StudyError("The model's quiz was not usable. Try again, or add more material to the note.")
    return {"title": str((data or {}).get("title") or "Practice quiz")[:120], "questions": questions[:25]}


def _clean_deck(data: Any) -> Dict[str, Any]:
    cards = []
    for index, raw in enumerate((data or {}).get("cards", []) if isinstance(data, dict) else []):
        if isinstance(raw, dict) and str(raw.get("front", "")).strip() and str(raw.get("back", "")).strip():
            cards.append({"id": f"c{index}", "front": str(raw["front"]).strip()[:400], "back": str(raw["back"]).strip()[:800], "box": 1})
    if not cards:
        raise StudyError("The model's flashcards were not usable. Try again.")
    return {"title": str((data or {}).get("title") or "Flashcards")[:120], "cards": cards[:80]}


def _clean_steps(data: Any, question: str) -> Dict[str, Any]:
    steps = []
    for raw in (data or {}).get("steps", []) if isinstance(data, dict) else []:
        if isinstance(raw, dict) and (str(raw.get("detail", "")).strip() or str(raw.get("title", "")).strip()):
            steps.append({"title": str(raw.get("title", "")).strip()[:160], "detail": str(raw.get("detail", "")).strip()[:1500]})
    if not steps:
        raise StudyError("The model did not return usable steps. Try rephrasing the question.")
    return {"question": question[:600], "steps": steps[:15], "answer": str((data or {}).get("answer", "")).strip()[:1500],
            "check": str((data or {}).get("check", "")).strip()[:600]}


SPEC_PROMPTS = {
    "quiz": ('Make a practice quiz of {count} questions from the material: mostly multiple choice (4 options), some true/false and '
             '1–2 short answer. Test understanding, not trivia. Reply with JSON only: {{"title": "…", "questions": [{{"type": "mc"|"tf"|"short", '
             '"question": "…", "options": ["…"] (mc only), "answer": "exact option text" | true/false | "model answer", '
             '"explanation": "why, in one or two sentences"}}]}}'),
    "flashcards": ('Make {count} flashcards from the material: one idea per card, the term or question on the front, a short '
                   'answer on the back. Reply with JSON only: {{"title": "…", "cards": [{{"front": "…", "back": "…"}}]}}'),
    "steps": ('Solve or explain this step by step for a student: "{question}". Each step does one thing and says why. '
              'Reply with JSON only: {{"steps": [{{"title": "short step name", "detail": "what to do and why"}}], '
              '"answer": "the final answer", "check": "how to check the answer"}}'),
}


def run_action(action: str, title: str, body: str, *, selection: str = "", question: str = "",
               count: Optional[int] = None) -> Dict[str, Any]:
    """Do one study action. Returns {"kind": "text"|"quiz"|"deck"|"steps", ..., "model": label}."""
    if action in TEXT_ACTIONS:
        label, instruction = TEXT_ACTIONS[action]
        needs_question = action in ("ask", "cite", "study_plan", "custom")
        if needs_question and not question.strip():
            raise StudyError({"ask": "Type your question first.", "cite": "Describe the source: title, author, year, link.",
                              "study_plan": "Say the exam date and topics, e.g. “Midterm Oct 20: chapters 3–6”.",
                              "custom": "Say what you want made, e.g. “a one-page cheat sheet of the formulas”."}[action])
        material = _material(title, body, selection) if action not in ("cite", "study_plan") or body.strip() or selection.strip() else ""
        prompt = f"{instruction}\n\n" + (f"Student: {question.strip()}\n\n" if question.strip() else "") + material
        text, model = _run(prompt)
        if not text.strip():
            raise StudyError("The model returned nothing. Try again.")
        return {"kind": "text", "action": action, "title": label, "text": text.strip(), "model": model}

    if action not in SPEC_ACTIONS:
        raise StudyError(f"Unknown study action {action!r}.")
    if action == "steps" and not question.strip():
        raise StudyError("Type the question or problem to solve step by step.")
    amount = max(3, min(int(count or (10 if action == "quiz" else 15)), 40))
    prompt = SPEC_PROMPTS[action].format(count=amount, question=question.strip().replace('"', "'"))
    if body.strip() or selection.strip():
        prompt += "\n\n" + _material(title, body, selection)
    data = None
    model = ""
    for attempt in range(2):
        text, model = _run(prompt if attempt == 0 else prompt + "\n\nYour last reply was not valid JSON. Reply with the JSON object only.", 4000)
        data = _json_block(text)
        if isinstance(data, dict):
            break
    if action == "quiz":
        return {"kind": "quiz", "spec": _clean_quiz(data), "model": model}
    if action == "flashcards":
        return {"kind": "deck", "spec": _clean_deck(data), "model": model}
    return {"kind": "steps", "spec": _clean_steps(data, question), "model": model}


#: Words in a free-text request that mean "make me the interactive version", so
#: "quiz me on the enzymes part" produces a real quiz and not a page about quizzes.
_CUSTOM_ROUTES = (
    ("quiz", ("quiz", "test me", "practice questions", "mcq", "multiple choice", "exam me")),
    ("flashcards", ("flashcard", "flash card", "anki", "cards to memorise", "cards to memorize")),
    ("steps", ("step by step", "step-by-step", "work through", "solve this")),
)


def route_custom(instruction: str) -> str:
    """Which action a typed request really wants ("make flashcards" → flashcards)."""
    text = (instruction or "").lower()
    for action, words in _CUSTOM_ROUTES:
        if any(word in text for word in words):
            return action
    return "custom"


def read_drawing(image: bytes, mime: str, hint: str = "") -> Dict[str, str]:
    """Handwriting, equations and diagrams from a sketch, as Markdown notes."""
    from model_roles import MODEL_ROLES

    import uploads

    prepared, prepared_mime = uploads.prepare_image(image, mime or "image/png")
    prompt = (
        "This is a student's hand-drawn sketch from class. Transcribe any handwriting exactly, write equations in LaTeX between "
        "$…$, and describe diagrams as structured notes (what the parts are, arrows and relationships, labels). Then add "
        "'## What this shows' with a two-sentence explanation of the concept. Markdown only."
        + (f" Context from the student: {hint.strip()[:300]}" if hint.strip() else "")
    )
    run = MODEL_ROLES.run("image_check", prompt, images=[(prepared, prepared_mime)], max_tokens=1800)
    return {"text": run.text.strip(), "model": run.label}


def grade_short_answer(question: str, expected: str, given: str) -> Dict[str, Any]:
    """A quick fair check of a short answer: right, partly right or not yet, with one line of feedback."""
    from mini_model import quick_text

    reply = quick_text(
        f"Question: {question}\nModel answer: {expected}\nStudent answer: {given}\n"
        'Grade fairly (meaning matters, not wording). Reply JSON only: {"verdict": "correct"|"partial"|"incorrect", "feedback": "one sentence"}',
        budget_seconds=6.0, max_tokens=120) or ""
    data = _json_block(reply)
    if isinstance(data, dict) and data.get("verdict") in ("correct", "partial", "incorrect"):
        return {"verdict": data["verdict"], "feedback": str(data.get("feedback", ""))[:300]}
    overlap = len(set(re.findall(r"\w{4,}", expected.lower())) & set(re.findall(r"\w{4,}", given.lower())))
    return {"verdict": "partial" if overlap else "incorrect",
            "feedback": "Compare your answer with the model answer below." if overlap else "Not yet — see the model answer."}
