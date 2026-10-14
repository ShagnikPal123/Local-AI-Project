"""Builds docs/CHANGELOG.md: every change in the git history, grouped by team, with a code name and a pushed tick.

Why it exists: the owner asked for one "Fixes, changes, and updates" log where each update has a code name
(Greek, maths, cosmic) and a number, ticked once it is on GitHub. Writing it by hand drifts the moment a team
pushes, so it is generated from ``git log`` and can be rerun whenever a team lands something.

Why names come from position: commit number N always gets the Nth name, so a rerun never renames old rows and
new commits only add rows at the end. ``docs/changelog_overrides.json`` pins a team, title or name for one
commit when the keyword rules guess wrong; it is data, never code.

Usage::

    python changelog_gen.py                       # rewrite docs/CHANGELOG.md
    python changelog_gen.py --threads t.json      # also list the teams still working (title/status/note)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import paths

REPO_URL = "https://github.com/ShagnikPal123/Local-AI-Project"
OUT = Path(paths.PROJECT_DIR) / "docs" / "CHANGELOG.md"
OVERRIDES = Path(paths.PROJECT_DIR) / "docs" / "changelog_overrides.json"

# Greek first, then maths, then cosmic. Io, Stros, the sidebar tab names and the model lineup are left out
# on purpose so a code name never collides with something that already means another thing in the app.
GREEK = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta", "Iota", "Kappa", "Lambda", "Mu",
         "Nu", "Xi", "Omicron", "Pi", "Rho", "Sigma", "Tau", "Upsilon", "Phi", "Chi", "Psi", "Omega"]
MATHS = ["Euler", "Gauss", "Fermat", "Noether", "Riemann", "Fibonacci", "Mobius", "Cantor", "Hilbert", "Pascal",
         "Turing", "Kepler", "Ramanujan", "Galois", "Laplace", "Fourier", "Bernoulli", "Lagrange", "Cauchy",
         "Poincare", "Godel", "Napier", "Archimedes", "Euclid", "Hypatia", "Leibniz", "Mandelbrot", "Dirac"]
COSMIC = ["Nova", "Pulsar", "Nebula", "Vega", "Sirius", "Rigel", "Altair", "Deneb", "Orion", "Lyra", "Draco",
          "Cygnus", "Andromeda", "Perseus", "Hydra", "Titan", "Europa", "Callisto", "Triton", "Phobos",
          "Halley", "Hubble", "Aurora", "Eclipse", "Zenith", "Corona", "Comet", "Helios"]
NAMES = GREEK + MATHS + COSMIC

# First match wins. Subjects are lower-cased; order matters (specific before broad).
TEAM_RULES = [
    ("WS1 Trading app", r"\btrad(?:er|ing)\b"),
    ("WS13 Skills, plugins, Obsidian", r"\bskills?\b|obsidian|\breels?\b|second brain"),
    ("WS4 Integrity (act, don't refuse)", r"integrity|refus|\btaint|safety:"),
    ("WS7 Notch", r"\bnotch\b"),
    ("WS6 Voice and Equalize", r"\bvoices?\b|equalize|speech|jarvis|morning digest|claude code sessions"),
    ("WS8 Avatars and bot teams", r"avatar|personalit"),
    ("WS9 Phone, WhatsApp, Gmail", r"whatsapp|gmail|e-?mail|\bmail\b"),
    ("WS2 Command center", r"constellation|quasar|orbits|commander|\bprojects?\b|scheduled tasks"),
    ("WS5 Speed and models", r"ultra fast|local context|\bmodels?:|\b1m\b|speed|router"),
    ("WS12 Design and motion", r"design|redesign|glass|tokens|orb|motion|theme|winui|\blook\b"),
    ("WS11 UI fixes", r"\btabs?\b|scroll|dialog|log out|sidebar|finder|settings|accounts|appearance|layout|"
                      r"cut off|crash|loading"),
    ("WS10 Normal chat", r"\bchat|composer|quiz|context bar"),
    ("WS14 Desktop app", r"launcher|desktop app|\.exe|windows build|logon task|app window|engine as"),
    ("Plans and docs", r"^docs?:|workplan|\bplan\b|session log"),
]
DEFAULT_TEAM = "Core and earlier features"


def classify(subject: str) -> str:
    low = subject.lower()
    for team, pattern in TEAM_RULES:
        if re.search(pattern, low):
            return team
    return DEFAULT_TEAM


def code_name(number: int) -> str:
    """Nth name; once the pool wraps the lap number follows (Alpha II), so every name stays unique."""
    lap, index = divmod(number - 1, len(NAMES))
    return NAMES[index] if lap == 0 else f"{NAMES[index]} {_roman(lap + 1)}"


def _roman(n: int) -> str:
    out = ""
    for value, sym in ((10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out, n = out + sym, n - value
    return out


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=paths.PROJECT_DIR, capture_output=True, text=True, check=True).stdout


def read_log(run: Callable[..., str] = _git, ref: str = "HEAD", pushed_ref: str = "origin/main") -> List[dict]:
    """Oldest-first commits (merges skipped), each with a ``pushed`` flag from the remote branch."""
    pushed = set(run("rev-list", pushed_ref).split())
    raw = run("log", "--reverse", "--no-merges", "--format=%H|%ad|%s", "--date=short", ref)
    out = []
    for line in raw.splitlines():
        full, day, subject = (line.split("|", 2) + ["", ""])[:3]
        if full:
            out.append({"hash": full[:7], "date": day, "subject": subject.strip(), "pushed": full in pushed})
    return out


def _clean(text: str, limit: int = 170) -> str:
    text = text.replace("|", "/").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def build(commits: Iterable[dict], overrides: Optional[Dict[str, dict]] = None) -> List[dict]:
    overrides = overrides or {}
    rows = []
    for number, c in enumerate(commits, start=1):
        pin = overrides.get(c["hash"], {})
        rows.append({
            **c,
            "number": number,
            "name": pin.get("name") or code_name(number),
            "team": pin.get("team") or classify(c["subject"]),
            "title": _clean(pin.get("title") or c["subject"]),
        })
    return rows


def render(rows: List[dict], threads: Optional[List[dict]] = None, today: Optional[str] = None) -> str:
    teams: "OrderedDict[str, List[dict]]" = OrderedDict()
    for row in rows:
        teams.setdefault(row["team"], []).append(row)
    ordered = sorted(teams.items(), key=lambda kv: (kv[0] == DEFAULT_TEAM, kv[0] == "Plans and docs", kv[0]))
    pushed = sum(1 for r in rows if r["pushed"])
    lines = [
        "# Fixes, changes, and updates",
        "",
        f"Generated by `changelog_gen.py` from the git history of {REPO_URL.split('github.com/')[1]} "
        f"on {today or date.today().isoformat()}. Do not edit by hand; rerun the script or pin a row in "
        "`docs/changelog_overrides.json`.",
        "",
        f"**{len(rows)} updates, {pushed} pushed to GitHub.** ✅ = on GitHub (`main`), ⬜ = not pushed yet. "
        "Numbers run oldest to newest; each number keeps its code name. Teams (WS numbers) come from the "
        "Fixer Upper plan; work from before the split is grouped by the area it touched.",
        "",
        "| Team | Updates | Pushed |",
        "|---|---|---|",
    ]
    for team, items in ordered:
        lines.append(f"| {team} | {len(items)} | {sum(1 for i in items if i['pushed'])} |")
    lines += ["", "## Latest 12", "", "| # | Code name | Date | Team | Change | Pushed |", "|---|---|---|---|---|---|"]
    for r in reversed(rows[-12:]):
        lines.append(_row(r, with_team=True))
    if threads:
        lines += ["", "## Teams still working (not pushed yet)", "", "| Team thread | Status | Latest |", "|---|---|---|"]
        for t in threads:
            lines.append(f"| {_clean(t.get('title', ''), 80)} | {_clean(t.get('status', ''), 40)} | {_clean(t.get('note', ''), 200)} |")
    for team, items in ordered:
        lines += ["", f"## {team}", "", "| # | Code name | Date | Change | Pushed |", "|---|---|---|---|---|"]
        lines += [_row(r) for r in items]
    return "\n".join(lines) + "\n"


def _row(r: dict, with_team: bool = False) -> str:
    link = f"[`{r['hash']}`]({REPO_URL}/commit/{r['hash']})"
    tick = "✅" if r["pushed"] else "⬜"
    cells = [str(r["number"]), f"**{r['name']}**", r["date"]]
    if with_team:
        cells.append(r["team"])
    cells += [f"{r['title']} ({link})", tick]
    return "| " + " | ".join(cells) + " |"


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--threads", help="JSON list of {title,status,note} for teams still working")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args(argv)
    threads = _load(Path(args.threads), []) if args.threads else None
    rows = build(read_log(), _load(OVERRIDES, {}))
    Path(args.out).write_text(render(rows, threads), encoding="utf-8")
    print(f"wrote {args.out}: {len(rows)} updates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
