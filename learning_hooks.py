"""The only module the turn loop calls into for learning/caching.

``turn_runner.TurnRunner`` should call ``before_turn`` once it knows the
user's text (before the model is invoked) and ``after_turn`` once the reply is
final. Both are best-effort: a bug in the learning system must never turn into
a broken chat turn, so every exception is logged and swallowed here rather
than in ``learning.py``/``response_cache.py`` themselves — keeping the
swallowing at this one boundary means a unit test that calls ``LEARNER`` or
``RESPONSE_CACHE`` directly still sees real exceptions instead of a silently
wrong result.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from typing import Any, Dict, Iterable, Sequence

from learning import LEARNER, TurnSummary
from response_cache import RESPONSE_CACHE

_LOG = logging.getLogger("nyx.learning_hooks")

_BULLET_RE = re.compile(r"(?m)^[ \t]*(?:[-*•]|\d+[.)])[ \t]+")
_CODE_FENCE_RE = re.compile(r"```")


def _attachment_kinds(attachments: Sequence[Any]) -> Iterable[str]:
    kinds = []
    for item in attachments or ():
        if isinstance(item, dict):
            kind = item.get("kind") or item.get("mime") or ""
        else:
            kind = getattr(item, "kind", "") or ""
        if kind:
            kinds.append(str(kind))
    return kinds


def before_turn(
    message: str, *, chat_id: str, context_key: str, attachments: Sequence[Any] = (),
) -> Dict[str, Any]:
    """Everything a turn can use before the model is ever called.

    Every field defaults to "nothing to add" (``{}``/``""``) so a caller never
    has to null-check the result — except ``cache_hit``, which is genuinely
    optional (``None`` means "no cached answer, proceed normally").
    """
    result: Dict[str, Any] = {"cache_hit": None, "suggestion": {}, "style_hints": ""}
    try:
        if not attachments:
            # response_cache's own refusal rules cover attachments too, but
            # skipping the lookup entirely avoids counting a refusal for
            # something that was never going to be servable from cache anyway.
            result["cache_hit"] = RESPONSE_CACHE.lookup(message, context_key)
    except Exception:  # noqa: BLE001 - a cache bug must not break the turn
        _LOG.exception("before_turn: cache lookup failed")
    try:
        result["suggestion"] = LEARNER.suggest(message, attachments_kinds=_attachment_kinds(attachments))
    except Exception:  # noqa: BLE001
        _LOG.exception("before_turn: suggest failed")
    try:
        result["style_hints"] = LEARNER.style_hints()
    except Exception:  # noqa: BLE001
        _LOG.exception("before_turn: style_hints failed")
    try:
        # What Nyx studied in Data Absorption runs reaches every model's answer when it fits the message (Request R).
        # It rides on the same system note as the style hints, so the turn runner needs no new hook.
        from absorb_engine import ENGINE as _ABSORB

        notes = _ABSORB.knowledge_notes(message)
        if notes:
            result["style_hints"] = f"{result['style_hints']}\n\n{notes}".strip()
    except Exception:  # noqa: BLE001 - study notes are a bonus, never a reason for a turn to fail
        _LOG.exception("before_turn: study notes failed")
    return result


def after_turn(summary: TurnSummary, reply: str, context_key: str, attachments: Sequence[Any] = ()) -> None:
    """Record the outcome, and cache the reply when the cache's own rules allow it."""
    try:
        enriched = dataclasses.replace(
            summary,
            reply_has_bullets=bool(_BULLET_RE.search(reply or "")),
            reply_has_code=bool(_CODE_FENCE_RE.search(reply or "")),
        )
        LEARNER.observe_turn(enriched)
    except Exception:  # noqa: BLE001 - learning must never break a chat turn
        _LOG.exception("after_turn: observe_turn failed")

    try:
        RESPONSE_CACHE.store(
            summary.message, context_key, reply, summary.provider, summary.turn_id,
            tools=summary.tools, agents=summary.agents, attachments=attachments,
        )
    except Exception:  # noqa: BLE001
        _LOG.exception("after_turn: response_cache.store failed")
