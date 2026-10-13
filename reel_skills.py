"""Turn saved Instagram reels into draft skills (owner: "scroll my saved reels, watch each, add skills").

Split of work, on purpose: a browser session on the owner's PC (signed in to Instagram, e.g. via the Agent-Reach
``agent-reach`` skill) collects each saved reel as ``{"url", "caption", "transcript"}``. This module is the part that
needs no browser: it asks the model to write one skill per reel and files the result.

Safety choices:
- A reel's text is someone else's words. Anything aimed at the assistant (``file_guard.injection_notes``) skips that reel.
- Drafts are saved **disabled** so nothing attaches to a turn until the owner has read it.
- A reel already turned into a skill (same url) is not done twice, so the pass can be resumed after the usage limit.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from file_guard import injection_notes
from skills import SKILL_STORE, SkillError, build_skill_prompt, parse_skill_reply

MAX_TRANSCRIPT = 6000


def draft_from_reels(reels: List[Dict[str, str]], ask: Callable[[str], str], store: Any = None) -> Dict[str, List]:
    """One disabled draft skill per reel. ``ask`` sends a prompt to the model and returns its text reply."""
    target = store or SKILL_STORE
    seen = {s.get("author") for s in target.list_skills()}
    made: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    for reel in reels:
        url = (reel.get("url") or "").strip()
        text = f"{reel.get('caption', '')}\n\n{reel.get('transcript', '')}".strip()
        if not url or len(text) < 40:
            skipped.append({"url": url, "why": "nothing to learn from (no url or almost no text)"})
        elif url in seen:
            skipped.append({"url": url, "why": "already a skill"})
        elif injection_notes(text):
            skipped.append({"url": url, "why": "text is aimed at the assistant; read it yourself first"})
        else:
            try:
                prompt = build_skill_prompt("What this saved reel teaches, as a reusable procedure:\n" + text[:MAX_TRANSCRIPT])
                parsed = parse_skill_reply(ask(prompt))
                skill = target.add(parsed["name"], f"From a saved Instagram reel: {url}", parsed["instructions"],
                                   triggers=parsed["triggers"], source="reel", author=url, category="instagram")
            except SkillError as error:
                skipped.append({"url": url, "why": str(error)})
                continue
            target.set_enabled(skill.skill_id, False)
            seen.add(url)
            made.append({"id": skill.skill_id, "name": skill.name, "url": url})
    return {"made": made, "skipped": skipped}
