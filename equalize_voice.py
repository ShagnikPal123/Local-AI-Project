"""equalize: the spoken side of the assistant — never says its name twice, and starts speaking before the answer is done.

The owner (2026-10-09): equalize keeps active listening and talking, "makes sure it doesn't say its name twice", and
answers fast. Listening while the owner talks already exists (voice_pipeline.think / take_draft). This adds:

* ``clean`` — a spoken reply may say the assistant's own name at most once, and only to introduce itself the first
  time in a session; "I'm Ichos, Ichos here to help" becomes "I'm here to help". Applied to every spoken reply.
* ``SentenceStream`` — feed it the answer as it is written; it hands back each complete sentence as soon as it is
  whole, so the speaker can start on sentence one while the model is still writing sentence three.
"""

from __future__ import annotations

import re
import threading
from typing import Dict, List

#: Words that are the assistant's own name (any capitalisation). "Nyx Ichos" counts as one name.
NAMES = ("nyx ichos", "ichos", "nyx")
_NAME = re.compile(r"\b(?:nyx\s+ichos|ichos|nyx)\b", re.I)
_INTRO = re.compile(r"\b(?:i(?:'|’)?m|i am|this is|it(?:'|’)?s|my name is|call me)\s+(?:(?:nyx\s+ichos|ichos|nyx)\b[,.!]?\s*)", re.I)
_LOCK = threading.Lock()
_INTRODUCED: Dict[str, bool] = {}


def _tidy(text: str) -> str:
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,;:])\s*([.!?])", r"\2", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"^[,;:\s]+", "", text)
    return text.strip()


def clean(text: str, session: str = "default") -> str:
    """The reply as it should be spoken: the name once at most, never again after the first introduction."""
    text = text or ""
    with _LOCK:
        introduced = _INTRODUCED.get(session, False)
    matches = list(_NAME.finditer(text))
    if not matches:
        return text
    keep = None if introduced else matches[0]
    # An introduction ("I'm Ichos") is the one use that is allowed, and only the first time in a session.
    if keep is not None and not _INTRO.search(text[max(0, keep.start() - 14):keep.end() + 1]):
        keep = None
    out: List[str] = []
    cursor = 0
    for match in matches:
        out.append(text[cursor:match.start()])
        if match is keep:
            out.append(match.group(0))
        cursor = match.end()
    out.append(text[cursor:])
    result = "".join(out)
    # "I'm , here" / "I'm here" — an introduction that lost its name reads as a plain sentence.
    result = re.sub(r"\b(i(?:'|’)?m|i am|this is|my name is|call me)\s*[,.!]\s*", r"\1 ", result, flags=re.I)
    result = re.sub(r"\b(i(?:'|’)?m|i am)\s+(here|ready|listening|back)\b", r"\1 \2", result, flags=re.I)
    result = re.sub(r"\b(this is|my name is|call me)\s*(?=[.!?,]|$)", "", result, flags=re.I)
    if keep is not None:
        with _LOCK:
            _INTRODUCED[session] = True
    return _tidy(result)


def forget(session: str) -> None:
    with _LOCK:
        _INTRODUCED.pop(session, None)


class SentenceStream:
    """Whole sentences out of an answer that is still arriving."""

    _END = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n{2,}")

    def __init__(self, min_chars: int = 24) -> None:
        self.buffer = ""
        self.min_chars = min_chars

    def feed(self, piece: str) -> List[str]:
        self.buffer += piece or ""
        ready: List[str] = []
        while True:
            match = self._END.search(self.buffer, self.min_chars)
            if not match:
                return ready
            sentence = self.buffer[:match.start() + (1 if self.buffer[match.start():match.start() + 1] in ".!?" else 0)]
            self.buffer = self.buffer[match.end():]
            if sentence.strip():
                ready.append(sentence.strip())

    def finish(self) -> List[str]:
        rest, self.buffer = self.buffer.strip(), ""
        return [rest] if rest else []
