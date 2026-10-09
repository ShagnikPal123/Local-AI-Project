"""Real time against game time (U38).

The owner: *"It understands real time vs game time in this case. How if I want it to work for 5 days it knows how long
that is and gives the user its own timeline."* Two clocks, never confused:

* **real time** — what a deadline means. "Work for 5 days" is five days on the wall clock, whatever the speed.
* **game time** — the world's own calendar (360-day years), which runs faster at higher speeds while the world is
  running and stands still while it is paused. It is how old the civilisation is, not a promise about delivery.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

DAYS_PER_YEAR = 360

_UNITS = {
    "second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400, "night": 86400,
    "week": 7 * 86400, "fortnight": 14 * 86400, "month": 30 * 86400, "year": 365 * 86400,
}
_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "a couple of": 2, "a few": 3,
                 "couple of": 2, "few": 3, "half a": 0.5, "half an": 0.5}
_UNIT_RE = "(second|sec|minute|min|hour|hr|day|night|week|fortnight|month|year)s?"
_NUMBER_RE = r"(\d+(?:\.\d+)?|half an?|a couple of|couple of|a few|few|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_DURATION = re.compile(rf"\b(?:for|over|during|in|within|next)\s+(?:the\s+)?{_NUMBER_RE}\s+{_UNIT_RE}\b", re.IGNORECASE)
_BARE = re.compile(rf"^\s*{_NUMBER_RE}\s+{_UNIT_RE}\s*$", re.IGNORECASE)
_UNTIL_DONE = re.compile(r"\b(until|till|til)\s+(it'?s\s+|it\s+is\s+)?(done|finished|complete)\b", re.IGNORECASE)
_OVERNIGHT = re.compile(r"\bovernight\b", re.IGNORECASE)

#: The longest a world may be told to run in one go. Months are allowed (the owner's words), years are not.
MAX_SECONDS = 366 * 86400


def _number(text: str) -> float:
    text = text.strip().lower()
    if text in _NUMBER_WORDS:
        return float(_NUMBER_WORDS[text])
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_duration(text: str) -> Optional[int]:
    """Seconds of real time the owner asked for, 0 for "until it is done", None when they did not say.

    Accepts a sentence ("work on this for 5 days") or a bare amount from the form ("3 hours", "2 weeks").
    """
    words = (text or "").strip()
    if not words:
        return None
    if _UNTIL_DONE.search(words) or words.lower() in ("until done", "done", "0"):
        return 0
    match = _BARE.match(words) or _DURATION.search(words)
    if match:
        amount, unit = match.group(1), match.group(2).lower()
        seconds = _number(amount) * _UNITS.get(unit.rstrip("s"), _UNITS.get(unit, 0))
        if seconds > 0:
            return int(min(MAX_SECONDS, seconds))
    if _OVERNIGHT.search(words):
        return 10 * 3600
    return None


def describe_seconds(seconds: float) -> str:
    """"5 days", "3 h 20 min", "45 s" — how long, in the fewest words that are still exact enough."""
    total = max(0, int(seconds))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days} day{'s' if days != 1 else ''}" + (f" {hours} h" if hours else "")
    if hours:
        return f"{hours} h" + (f" {minutes} min" if minutes else "")
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"


def game_date(game_days: float) -> Tuple[int, int]:
    """(year, day) of the world's own calendar. Year 1, day 1 is the moment it was founded."""
    days = max(0.0, float(game_days))
    year = int(days // DAYS_PER_YEAR) + 1
    day = int(days % DAYS_PER_YEAR) + 1
    return year, day


def game_date_words(game_days: float) -> str:
    year, day = game_date(game_days)
    return f"Year {year}, day {day}"


def advance(game_days: float, real_seconds: float, days_per_minute: float) -> float:
    """The game clock after ``real_seconds`` of running at a speed."""
    return float(game_days) + max(0.0, float(real_seconds)) / 60.0 * max(0.0, float(days_per_minute))
