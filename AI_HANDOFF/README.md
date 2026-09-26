# AI_HANDOFF — give this folder to any AI to continue Nyx Ichos

Nyx Ichos is Shagnik's local-first AI assistant: a Python 3.14 FastAPI engine that runs on his
Windows PC, a React/TypeScript web UI served by that engine, and a small public website. This
folder is written so a different AI (Claude, GPT, Gemini, Codex, Cursor, Antigravity…) can pick the
work up cold.

**Read in this order:**

| File | What it gives you |
|---|---|
| `PROJECT_NULL.md` | **The overhaul under way now**: what is done, what each session is building, what is next, and the owner's words for all of it |
| `START_HERE.md` | The resume point: every request, finished or not, with what was built and where it lives |
| `01_GOALS.md` | Every request the owner made, **verbatim**, plus what each one means as a buildable goal and its status |
| `02_FEATURES.md` | Every feature that exists in the app today, where it lives, and how complete it is |
| `03_ARCHITECTURE.md` | How the pieces fit: engine, turn streaming, events, tools, permissions, agents, skills, frontend |
| `05_RUNBOOK.md` | Commands, tests, build, and the traps that cost previous agents hours |
| `API_ROUTES.md` | Generated list of every HTTP route (`generate_routes.py` rebuilds it) |

**Where the project is:** `C:\Users\shagn\Desktop\Ai Dev Folder\Ai Dev Folder\` (the *nested*
folder — the outer one is only a container). In-repo docs that go deeper: `AGENTS.md` (how to work
here; tool-neutral), `OVERHAUL_CONTRACTS.md` (interfaces and event schemas),
`NYX_WORKPLAN.md` (task board), `IDEAS_OVERHAUL.md` (product ideas), `DESIGN_HANDOFF.md` (design layer,
when present).

**Prompt to paste into another AI:**

> You are continuing work on Nyx Ichos. Read AI_HANDOFF/README.md, then PROJECT_NULL.md,
> START_HERE.md and 05_RUNBOOK.md. Pick the highest-priority unfinished goal, restate it in
> one line with its acceptance criterion, implement it with a test, run the test suite, and report
> what you changed and how you verified it. Never commit secrets; never delete the owner's data files.
