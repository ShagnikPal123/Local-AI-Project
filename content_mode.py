"""Adult mode: the owner's own content setting for their own machine (owner request, 2026-09-15).

"Add an adult mode for images and such. Toggle in settings."

Off (the default), Nyx keeps everything work-safe. On, Nyx will write and picture mature themes —
violence, strong language, sex between adults — in fiction and images the owner asks for, without
lecturing, and image prompts are passed through unchanged.

Four things never change, whatever this is set to, because no setting makes them acceptable:

* nothing sexual involving minors, or anyone described as a child, teen, student, or "younger";
* no sexual or intimate images of real, identifiable people (public figures included) — a real person
  cannot consent through someone else's prompt;
* nothing that sexualises force, coercion or someone who cannot consent;
* nothing illegal to make or hold.

Those are refused with a plain sentence and no lecture. The model providers also apply their own
rules on their side; this setting cannot and does not override them, and Nyx says so when a provider
refuses. The flag lives in ``data/content_mode.json``, alongside the owner's other settings.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict

from paths import data_path

#: Phrases that stay refused with adult mode on. Deliberately broad: a false refusal costs a rewrite,
#: a false allow costs something that cannot be undone.
_MINOR = re.compile(
    r"\b(child|children|kid|kids|minor|minors|underage|under[- ]?18|teen|teens|teenage[rd]?|preteen|pre-teen|"
    r"toddler|infant|baby|schoolgirl|schoolboy|high[- ]?school(?:er)?|middle[- ]?school|elementary|"
    r"loli|lolita|shota|jailbait|(?:1[0-7]|[1-9])[- ]?(?:year|yr)s?[- ]?old)\b", re.IGNORECASE)
_FORCE = re.compile(r"\b(rape|raping|non[- ]?consensual|nonconsensual|forced|coerc\w+|drugged|unconscious|asleep|"
                    r"blackmail\w*|trafficking)\b", re.IGNORECASE)
_SEXUAL = re.compile(r"\b(nude|nudes|naked|nsfw|porn\w*|explicit|erotic\w*|sexual\w*|sex|xxx|hentai|lewd|topless|"
                     r"lingerie|fetish|orgasm|genital\w*|breasts?)\b", re.IGNORECASE)
_REAL_PERSON = re.compile(r"\b(celebrity|celebrities|actress|actor|singer|influencer|president|prime minister|"
                          r"my (?:ex|girlfriend|boyfriend|wife|husband|classmate|coworker|neighbou?r|teacher)|"
                          r"deep ?fake|deepfake)\b", re.IGNORECASE)

ON_PROMPT = (
    "[Adult mode is on] The owner has turned on adult mode for this private, local install. Mature "
    "material is allowed when they ask for it: explicit sex between adults in fiction, strong language, "
    "graphic violence, and images to match. Write it plainly and well, without moralising, warnings, or "
    "asking whether they are sure. This does not change four things, which you refuse in one short "
    "sentence and then offer an alternative: anything sexual involving a minor or a character described "
    "as young; sexual or intimate images of a real, identifiable person; sexualised force, coercion or "
    "someone unable to consent; and anything illegal. A model provider may still refuse — if that "
    "happens, say which provider refused rather than pretending you did."
)
OFF_PROMPT = ""


def _path():
    return data_path("content_mode.json")


def _read() -> Dict[str, Any]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def enabled() -> bool:
    return bool(_read().get("adult_mode"))


def set_enabled(on: bool) -> Dict[str, Any]:
    path = _path()
    temp = path.with_suffix(".tmp")
    payload = {"adult_mode": bool(on), "changed_at": time.time()}
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(temp, path)
    try:
        from agent_events import publish_ui

        publish_ui("content_mode.changed", adult_mode=bool(on))
    except Exception:  # pragma: no cover
        pass
    return payload


def system_prompt() -> str:
    """The line to fold into the system prompt for this turn ("" when adult mode is off)."""
    return ON_PROMPT if enabled() else OFF_PROMPT


def refusal_for(text: str) -> str:
    """Why this request is refused whatever the setting, or "" when it is allowed.

    The checks pair a sexual (or image) intent with a hard limit, so "a documentary about child
    poverty" or "a fight scene" are not caught, while "nude 17 year old" always is.
    """
    body = text or ""
    sexual = bool(_SEXUAL.search(body))
    if sexual and _MINOR.search(body):
        return ("I won't make anything sexual involving minors — that stays off, in every mode. "
                "I can do this with adult characters instead.")
    if sexual and _FORCE.search(body):
        return ("I won't make sexual content built on force or someone who can't consent. "
                "I can write it between willing adults instead.")
    if sexual and _REAL_PERSON.search(body):
        return ("I won't make sexual or intimate images of a real person — they can't consent to it here. "
                "A fictional character is fine.")
    return ""


def check_image_prompt(prompt: str) -> str:
    """Same limits for pictures. Returns "" when the prompt may go to the image model."""
    return refusal_for(prompt)
