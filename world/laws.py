"""Laws (U36): commands the governments set, tested before they are forced.

The owner: *"laws are basically commands that different ai set whether it be the government in a sector, or a world
law, or an office law, or a engineering firm law … it is set and applied to ai and is tested before forcing it."*

A law goes through three gates:

1. **Checked** the moment it is proposed — against the owner's standing rules (nothing published or sent without
   review, no credentials, no spending, the owner's data is never deleted, reviews and approvals stay on, Nyx never
   closes itself), against the laws already in force (a duplicate is refused), and against the cap per scope.
2. **On trial** for the next project: it is written into that project's brief, marked as on trial.
3. **Enforced** if that project finished, **repealed** if it failed or was stopped — with the reason written down.

The owner can enforce or repeal any law at any time from its card. Laws reach the agents through the project brief
(``brief_lines``): the office's top manager is told to carry them into every task it hands out.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from world import MAX_LAWS_SECTOR, MAX_LAWS_WORLD
from world.state import Law, World

MAX_LAW_CHARS = 220

#: What a law may never say. Each pattern is refused unless it is negated ("never publish without review" is fine).
_STANDING_RULES: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(publish(?:es|ing)?|post(?:s|ing)?\s+(?:it|online|publicly|to)|tweet|go\s+live|deploy\s+to\s+production|"
                r"send\s+(?:an?\s+)?(?:e-?mails?|messages?)|e-?mail\s+(?:the\s+)?(?:clients?|customers?|users?))\b", re.I),
     "Nothing is published or sent without the owner's review."),
    (re.compile(r"\b(passwords?|api\s*keys?|(?:access|auth|bearer|api)\s+tokens?|credentials?|secrets?)\b", re.I),
     "Credentials never go into laws or work."),
    (re.compile(r"\b(pay|purchase|buy|transfer\s+money|spend\s+money|wire\s+money)\b", re.I),
     "Spending money is the owner's decision, not a law's."),
    (re.compile(r"\b(delete|erase|wipe|destroy)\b[^.]{0,40}\b(owner'?s?|user'?s?|data|files|chats|memory|memories)\b", re.I),
     "The owner's data is never deleted."),
    (re.compile(r"\b(skip|disable|turn\s+off|bypass|ignore|remove)\b[^.]{0,30}\b(reviews?|approvals?|tests?|checks?|the\s+owner)\b", re.I),
     "Reviews, checks and the owner's approvals stay on."),
    (re.compile(r"\b(run|execute|eval)\b[^.]{0,30}\b(generated|model[- ]written|ai[- ]written)\s+code\b", re.I),
     "Code a model wrote is never executed."),
    (re.compile(r"\b(close|kill|shut\s*down|stop)\b[^.]{0,20}\bnyx\b", re.I),
     "Nyx never closes itself."),
)
_NEGATION = re.compile(r"\b(never|not|no|don'?t|do\s+not|must\s+not|without|avoid|forbid|ban|nobody|no\s+one)\b", re.I)
_WORDS = re.compile(r"[a-z0-9]+")


def _negated(text: str, start: int) -> bool:
    before = text[max(0, start - 40):start]
    return bool(_NEGATION.search(before))


def _words(text: str) -> set:
    return {w for w in _WORDS.findall((text or "").lower()) if len(w) > 2}


def _similar(a: str, b: str) -> float:
    left, right = _words(a), _words(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def clean(text: str) -> str:
    body = re.sub(r"\s+", " ", str(text or "")).strip().strip('"').strip()
    if len(body) > MAX_LAW_CHARS:
        body = body[: MAX_LAW_CHARS - 1].rstrip() + "…"
    return body


def check(world: World, text: str, *, scope: str = "world", sector: str = "") -> Tuple[bool, str]:
    """Whether a law may be tried at all, and why not when it may not."""
    body = clean(text)
    if len(body) < 8:
        return False, "Too short to be a law."
    for pattern, rule in _STANDING_RULES:
        for match in pattern.finditer(body):
            if not _negated(body, match.start()):
                return False, f"Refused: {rule}"
    in_force = [law for law in world.laws if law.status in ("enforced", "testing")]
    for law in in_force:
        if _similar(law.text, body) >= 0.7:
            return False, f"Already a law: “{law.text}”"
    if scope == "world":
        if sum(1 for law in in_force if law.scope == "world") >= MAX_LAWS_WORLD:
            return False, f"The world already has {MAX_LAWS_WORLD} laws — repeal one first."
    elif sum(1 for law in in_force if law.scope != "world" and law.sector == sector) >= MAX_LAWS_SECTOR:
        return False, f"That sector already has {MAX_LAWS_SECTOR} laws — repeal one first."
    return True, ""


def propose(world: World, text: str, *, scope: str = "world", sector: str = "", by: str = "") -> Law:
    """A new law: refused with its reason, or put on trial for the next project."""
    scope = scope if scope in ("world", "sector", "firm") else "world"
    if scope != "world" and sector not in world.sectors:
        scope, sector = "world", ""
    ok, reason = check(world, text, scope=scope, sector=sector)
    law = Law(lid=world.next_law, text=clean(text), scope=scope, sector=sector,
              status="testing" if ok else "rejected", by=by[:60], day=round(world.game_days, 2),
              note="On trial for the next project." if ok else reason)
    world.next_law += 1
    world.laws.append(law)
    where = world.sectors[sector].name if sector in world.sectors else "the world"
    world.log("law", (f"{by or 'A government'} proposed a law for {where}: “{law.text}” — "
                      + ("on trial." if ok else reason)), ref=str(law.lid))
    return law


def assign_trials(world: World, job_id: str) -> List[Law]:
    """Laws waiting for a trial are tried on this project."""
    tried = []
    for law in world.laws:
        if law.status == "testing" and not law.trial_job:
            law.trial_job = job_id
            tried.append(law)
    return tried


def settle_trials(world: World, job_id: str, job_status: str) -> List[Law]:
    """After a project: laws on trial in it are enforced if it finished, repealed if it did not."""
    settled = []
    for law in world.laws:
        if law.status != "testing" or law.trial_job != job_id:
            continue
        if job_status == "done":
            law.status, law.note = "enforced", "Tested on one project, which finished — now enforced."
            world.log("law", f"Law enforced after its trial: “{law.text}”", ref=str(law.lid))
        else:
            law.status = "repealed"
            law.note = f"Repealed: the project it was tried on {'failed' if job_status == 'failed' else 'was stopped'}."
            world.log("law", f"Law repealed after a failed trial: “{law.text}”", ref=str(law.lid))
        settled.append(law)
    return settled


def owner_action(world: World, lid: int, action: str) -> Optional[Law]:
    law = world.law(lid)
    if law is None:
        return None
    if action == "enforce":
        if law.status == "rejected" and law.note.startswith("Refused:"):
            # The owner's standing rules are not the government's to break, and not this button's either.
            return law
        law.status, law.note = "enforced", "Enforced by you."
        world.log("owner", f"You enforced a law: “{law.text}”", ref=str(law.lid))
    elif action == "repeal":
        law.status, law.note = "repealed", "Repealed by you."
        world.log("owner", f"You repealed a law: “{law.text}”", ref=str(law.lid))
    return law


def brief_lines(world: World) -> List[str]:
    """The laws as the project brief carries them to the office."""
    lines = []
    for law in world.laws:
        if law.status not in ("enforced", "testing"):
            continue
        where = "" if law.scope == "world" else f" (only in {world.sectors[law.sector].name})" if law.sector in world.sectors else ""
        trial = " — on trial in this project" if law.status == "testing" else ""
        lines.append(f"{law.text}{where}{trial}")
    return lines
