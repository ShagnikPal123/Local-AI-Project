"""Chat training data for Identity 0: who it is, and what its teacher answers (sequence-level distillation).

The own model learns *from* the teacher (Qwen on Ollama) the way a student learns from a book: the
teacher's answers are text to learn from; none of its weights are used. Only a teacher that
``policy.may_train_on`` allows is ever asked, and each example records who wrote it.

Prompt sources, in order of value: questions grounded in a corpus document (the document is given, so
the teacher answers from it instead of inventing), the owner's own questions (PII-scrubbed), and
Identity 0's self-description (written here, so it knows its own name, job and limits).

``synthetic_examples`` adds a fourth kind, and thousands of them: tasks whose right answer is *computed*
from a corpus document — its title, its opening sentence, the next sentence, the same sentence in
lowercase, the first year in it, three sentences as a list. No teacher is needed and nothing is invented,
which is why they can be made by the thousand while the teacher manages ten answers a minute. They teach
the part a small model can actually learn: doing what the message asked, in the shape it asked for.
"""

from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import identity0
from identity0.policy import may_train_on, scrub_pii

SYSTEM = (f"You are {identity0.CODENAME}, also called {identity0.NAME}: the owner's own AI model inside the Nyx app, "
          "trained on this computer. Answer clearly and honestly; say when you are not sure.")

IDENTITY = [
    ("Who are you?", f"I'm {identity0.CODENAME} — the owner calls me {identity0.NAME}. I'm the main brain of Nyx, the "
     "owner's own AI, and my neural network was trained from scratch on this computer."),
    ("What is your name?", f"My name is {identity0.CODENAME}. My public name is {identity0.NAME}."),
    ("Are you Qwen?", "No. Qwen is one of my teachers and collaborators. My network is my own: my own code, my own "
     "tokenizer and weights that started from random numbers and were trained here."),
    ("Are you ChatGPT or Claude?", f"No, I'm {identity0.CODENAME}, the owner's own model. I can work with other AI models "
     "when a question needs them, but I'm not any of them."),
    ("What can you do?", "I pick which model should answer each message, ask others when a question is hard, compare "
     "their answers to learn who is best at what, and answer myself in the areas where I've proven I'm good enough."),
    ("How do you learn?", "Every answer is compared with another model's now and then. When I lose, the better answer "
     "becomes a lesson and later part of my training data, so I keep improving."),
    ("What happens when you don't know something?", "I say so, then I bring in other models, and I keep what we find "
     "so I know it next time."),
    ("Where do you run?", "On the owner's own computer. My data and my weights stay here."),
    ("Who made you?", "The owner, Shagnik, built me as part of Nyx, with help from AI coding assistants."),
    ("Can you make mistakes?", "Yes. I'm small and still learning, so check important answers. When I'm wrong I want to "
     "know, because that is how I get better."),
]

TEMPLATES = [
    "Explain {title} in simple terms.",
    "What are the three most important things to know about {title}?",
    "Summarize this text in a few sentences:\n\n{excerpt}",
    "Based on this text, what is {title}?\n\n{excerpt}",
    "Write two questions a student might ask about {title}, and answer them.",
]


_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_YEAR = re.compile(r"\b(1[0-9]{3}|20[0-2][0-9])\b")
_RARE = ("bicycle", "saxophone", "penguin", "volcano", "spreadsheet", "cinnamon", "tractor", "glacier")


def _sentences(text: str, least: int = 40, most: int = 300) -> List[str]:
    out = []
    for piece in _SENTENCE.split((text or "").replace("\n", " ")):
        piece = " ".join(piece.split())
        if least <= len(piece) <= most:
            out.append(piece)
    return out


def _tasks(doc: Dict[str, Any], rng: random.Random) -> List[tuple]:
    """Every (question, answer) pair this document can honestly produce, mechanically."""
    title = str(doc.get("title") or "").strip()
    text = str(doc.get("text") or "")
    lines = _sentences(text)
    if not title or len(lines) < 4:
        return []
    excerpt = " ".join(lines[:6])[:1200]
    pairs: List[tuple] = [
        (f"Give this text a short title.\n\n{excerpt}", title),
        (f"Summarise this in one sentence.\n\n{excerpt}", lines[0]),
        (f"Rewrite this in lowercase only.\n\n{lines[1]}", lines[1].lower()),
        (f"Continue this text with the next sentence.\n\n{lines[2]}", lines[3]),
        (f"List three sentences from this text as bullet points.\n\n{excerpt}",
         "\n".join(f"- {line}" for line in lines[:3])),
        (f"Copy the first sentence of this text exactly.\n\n{excerpt}", lines[0]),
    ]
    if title.lower() in text[:400].lower():
        pairs.append((f"Based on this text, what is {title}?\n\n{excerpt}", lines[0]))
    year = _YEAR.search(excerpt)
    if year:
        pairs.append((f"What is the first year mentioned in this text? Answer with the number only.\n\n{excerpt}",
                      year.group(0)))
    word = next((w for w in lines[0].split() if len(w) > 6 and w.isalpha()), "")
    if word:
        pairs.append((f"Does this text mention the word \"{word}\"? Answer yes or no.\n\n{excerpt}", "yes"))
    missing = next((w for w in _RARE if w not in excerpt.lower()), "")
    if missing:
        pairs.append((f"Does this text mention the word \"{missing}\"? Answer yes or no.\n\n{excerpt}", "no"))
    count = rng.choice((3, 5, 8))
    pairs.append((f"Give the first {count} words of this text, nothing else.\n\n{excerpt}",
                  " ".join(excerpt.split()[:count])))
    return [(q, a) for q, a in pairs if a and 1 <= len(a) <= 1500]


def synthetic_examples(documents: Iterable[Dict[str, Any]], limit: int = 6000,
                       rng: Optional[random.Random] = None) -> List[Dict[str, Any]]:
    """Instruction examples whose answers are computed from the corpus — free, truthful, unlimited."""
    rng = rng or random.Random(5)
    rows: List[Dict[str, Any]] = []
    for doc in documents:
        if len(rows) >= limit:
            break
        pairs = _tasks(doc, rng)
        rng.shuffle(pairs)
        for question, answer in pairs[:3]:  # a few per document, so the corpus is not read for nothing
            rows.append({"messages": [{"role": "system", "content": SYSTEM},
                                      {"role": "user", "content": question},
                                      {"role": "assistant", "content": answer}],
                         "source": "synthetic", "teacher": "self"})
            if len(rows) >= limit:
                break
    rng.shuffle(rows)
    return rows


def identity_examples(repeat: int = 3) -> List[Dict[str, Any]]:
    rows = []
    for _ in range(repeat):
        for question, answer in IDENTITY:
            rows.append({"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question},
                                      {"role": "assistant", "content": answer}], "source": "identity", "teacher": "self"})
    return rows


def grounded_prompts(documents: Iterable[Dict[str, Any]], limit: int, rng: random.Random) -> List[Dict[str, str]]:
    prompts = []
    docs = [d for d in documents if d.get("title") and len(d.get("text", "")) > 400]
    rng.shuffle(docs)
    for doc in docs[:limit]:
        template = rng.choice(TEMPLATES)
        excerpt = doc["text"][:1800].rsplit(" ", 1)[0]
        prompts.append({"prompt": template.format(title=doc["title"], excerpt=excerpt), "source": doc["source"],
                        "title": doc["title"]})
    return prompts


def distill(prompts: List[Dict[str, str]], *, teacher: str, out: Path, complete: Optional[Callable[..., Dict]] = None,
            minutes: float = 30, progress: Optional[Callable[[str, float], None]] = None,
            stop: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """Ask the teacher each prompt and append good answers to ``out`` (JSONL). Stops at the time budget."""
    from identity0.members import split_id

    provider, model = split_id(teacher)
    allowed, why = may_train_on(provider, model)
    if not allowed:
        raise ValueError(f"{teacher} may not teach Identity 0: {why}")
    if complete is None:
        from identity0.collab import complete as complete_fn

        complete = complete_fn
    out.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + minutes * 60
    kept = failed = 0
    # A teacher that has stopped answering (Ollama shut down, the model unloaded) would otherwise burn
    # the whole time budget on empty answers, as it did once: stop and say so instead.
    in_a_row, limit = 0, 12
    note = ""
    with open(out, "a", encoding="utf-8") as handle:
        for index, item in enumerate(prompts):
            if time.time() > deadline or (stop is not None and stop()):
                break
            answer = complete(teacher, [{"role": "user", "content": item["prompt"]}], max_tokens=450, temperature=0.4,
                              timeout=90)
            text = str(answer.get("text", "")).strip()
            if not answer.get("ok"):
                in_a_row += 1
                if in_a_row >= limit:
                    note = f"the teacher stopped answering ({str(answer.get('error', ''))[:120]})"
                    break
            else:
                in_a_row = 0
            if answer.get("ok") and 40 <= len(text) <= 6000 and "<tool_call>" not in text:
                row = {"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": item["prompt"]},
                                    {"role": "assistant", "content": scrub_pii(text)}],
                       "source": item.get("source", ""), "teacher": teacher}
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                kept += 1
            else:
                failed += 1
            if progress is not None:
                progress(f"{kept} answers kept, {failed} skipped", (index + 1) / max(1, len(prompts)))
    return {"kept": kept, "skipped": failed, "teacher": teacher, "note": note}


def experience_examples(path: Path, limit: int = 2000) -> List[Dict[str, Any]]:
    """Trainable answers Big Kahuna already saw in real chats (the better one when there was a verdict)."""
    rows: List[Dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit * 3:]
    except OSError:
        return rows
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        verdict = (record.get("verdict") or {}).get("winner")
        which = "shadow" if verdict == "shadow" else "lead"
        answer = record.get(which) or {}
        if not (record.get("trainable") or {}).get(which) or not record.get("prompt"):
            continue
        text = str(answer.get("text", ""))
        if len(text) < 40 or "<tool_call>" in text:
            continue
        rows.append({"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": scrub_pii(record["prompt"])},
                                  {"role": "assistant", "content": scrub_pii(text)}],
                     "source": "experience", "teacher": answer.get("member", "")})
    return rows[-limit:]


def load_sft(path: Path) -> List[Dict[str, Any]]:
    rows = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row.get("messages"), list):
                rows.append(row)
    except OSError:
        pass
    return rows
