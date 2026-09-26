# CODEX HANDOFF — read this first, Codex

Written by Claude (Opus 5) for OpenAI Codex. If usage ran out mid-task, **Where Claude stopped** is the truth.

**Last updated:** 2026-09-16, end of Request J (Claude Opus 5). Next: K → L → M → N → O — see START_HERE.md.

## 0. Ground rules (2 minutes)

1. Project root is the NESTED folder `C:\Users\shagn\Desktop\Ai Dev Folder\Ai Dev Folder\`. Run everything from
   there with `.venv\Scripts\python.exe` (bare `python` is the Store stub).
2. Read `AGENTS.md` (commands, the five invariants, never-do list), then `AI_HANDOFF/START_HERE.md` (ordered checklist
   with root causes already found). Owner requests verbatim: `AI_HANDOFF/01_GOALS.md`.
3. Gates: `.venv\Scripts\python.exe -m pytest -q` and `cd frontend\nyx-pulse && npm run build` after any `src/` change
   — the server serves `dist/app/`.
4. Engine: http://localhost:8000 (tray launcher). Restart after Python edits:
   `curl -X POST http://127.0.0.1:8000/api/engine/restart`, then wait ~20 s and check it answered; the successor waits
   up to 60 s for the old one to let go.
5. Never commit/push unless the owner asks. Keys only in `.env.local` / `.secrets.json`; responses carry `last4` only.
   Never execute LLM-generated code (this is why the chat's Python boxes have no Run button). New `/api/*` routes are
   gated by default; a public one goes in `server_auth.PUBLIC_PATHS` AND `tests/test_server_auth.py`.
6. **Another agent works in this repo at the same time.** On 2026-09-15 `panels/DynamicTab.tsx` was rewritten by one
   while this session was building the same feature. Before editing a file, re-read it; if it already does what you
   were about to add, keep theirs and delete your duplicate (that is what happened to `panels/tabs/TabBlocks.tsx`).

## 1. Where Claude stopped

**2026-09-16:** Request J is done and live-verified (Improve review queue + deep mode, model fallback, agent /commands
with parallel boxes, auto sub-agent matching, Second Brain → Core view, Add-model URL, `read_handoff`). The owner then
queued K (beta-tester website #2 with GitHub + collaboration page), L (Research tab), M (3D model center multi-model job,
Ollama replication, download local models), N (hands-free voice conversation that talks while thinking) and O (tab
creation/editing freedom + apple-design). Details and starting points: `START_HERE.md` → NEXT GOALS.

Earlier (2026-09-15):

Request H (H1–H17) and Request I are done except the four below. Each item's details, root cause and live-verification
note are in `START_HERE.md` — read that, not this summary.

**Not started, in the order the owner asked for them:**

| Id | What the owner wants | Where to start | Est. |
|---|---|---|---|
| H4 | Finish the **Build tab**: circuit info, 3D-print and build info, connect to 3D-print apps, find materials online, compare solutions (store an AI → Pi vs Arduino) and build the chosen one | `panels/BuildPanel.tsx` is still a placeholder; `design_studio.py` exists. Model the comparison as a validated spec (invariant 2), not generated code. The Code tab's `arduino` starter and `intent_md.py` pair with this. | 8–12 h |
| H5 | **Game Studio tab**: 2D and 3D games (Hollow Knight-like), export to Unity | New tab. Unity export = files written to a folder the owner opened in the Code tab (`code_workspace.create_file`), never executed. | 10–16 h |
| G2 | Settings → Updates UI (channel, rollback, install a staged zip) | `beta_channel.py` + `/api/updates*` are done and tested; only the panel is missing. | 1–2 h |
| G10 | Beta-tester website (`site/beta/`) | Do last. **Do not link `site/downloads/NyxIchos-windows-x64.zip`** — it is the old Sep 6 PyInstaller build, blocked by Smart App Control, and it contains `device_profile.json`. | 2–3 h |

**Known, reported, not acted on:** the Kimi key answers 401; `extensions/vscode-nyx/install.ps1` has never been run
(it writes into `~/.vscode`); `site/downloads` and the other build leftovers are listed in Settings → Storage for the
owner to remove.

## 2. Subagents for Codex to spawn (Codex's own workers, not Nyx's)

Run at most two at once — every parallel team on this project so far died on usage limits. Each must finish with tests
green and `npm run build` clean.

| Name | Owns | Prompt seed |
|---|---|---|
| `codex-build-tab` | `design_studio.py`, `routes_build.py`, `panels/BuildPanel.tsx` | "Implement H4 per 01_GOALS.md. A build plan is a validated spec the client renders: parts, circuit, steps, printables. Compare two or more approaches with real trade-offs and prices from `search_web`. Never execute generated code; never order anything." |
| `codex-game-studio` | `game_studio.py`, `panels/GameStudioPanel.tsx` | "Implement H5. A game is a data spec plus assets; Unity export writes a folder of C# and scene files into a workspace the owner opened, and says what to do with it. Nothing is compiled or run by Nyx." |
| `codex-updates-ui` | `panels/SettingsPanel.tsx` | "Implement the G2 panel against the existing `/api/updates` routes: channel select, check, download (shows the sha256 match), install on next start, rollback." |
| `codex-site` | `site/beta/` | "Implement G10 last. Static HTML, detailed Windows steps, link only the release zip built by `release_beta.py --publish` (secret-scanned). Never link site/downloads." |
| `codex-reviewer` | read-only | "Review the diff against AGENTS.md §4 invariants and for secrets; report, do not edit." |

## 3. What Claude thinks should be added next (after H and I)

1. **Server-side AI timers.** Tab `ai_task` blocks only run while that tab is open (browser interval). Move the
   schedule into the engine so "every 30 minutes, give me 3 headlines" survives a closed tab — `improve_autopilot.py`
   already shows the pattern for a background loop that reports into a chat.
2. **A sandbox decision for Python boxes.** The owner asked for runnable Python (H10); AGENTS.md §7 forbids executing
   LLM-generated code, so the box has Edit/Copy/Save/Explain but no Run. Ask the owner whether they want a
   browser-side WASM sandbox (Pyodide, no filesystem, explicit click per run) as a written exception.
3. **Consult budget telemetry.** `consult.py` spends a parallel call on heavy turns. Record how often its notes changed
   the answer (learning already stores turns) so the feature can be tuned or dropped on evidence.
4. **Key pool for image/vision roles.** `key_pool` failover is wired into `router.stream`; `model_hub.complete` (roles,
   consult, notes) still uses the single live key.
5. **The city as the agents' home.** Buildings could show live work as lit floors, and dragging a task onto a building
   could delegate it. The data is already there (`/api/agents/details`).
