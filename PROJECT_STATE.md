# Nyx Pulse — Live Project State

**Created by:** Shagnik
**This file is the resume point.** If a session ends abruptly — credits, crash, closed window —
the next session reads this file plus `ROADMAP.md` and picks up exactly where work stopped.

**Update this file whenever an item changes state. Do not batch it to the end of a session.**

---

## Snapshot

| | |
|---|---|
| **Last updated** | 2026-08-26 (session 4) |
| **Repo health** | Green — 816/816 tests passing |
| **Chat** | **Working.** Was returning canned offline text on every turn. |
| **Chat latency** | ~0.6–3s typical (was 8s–offline, or 55s worst case) |
| **Python** | 3.14.7 at `.venv/` |
| **Roadmap items total** | 279 (sections A–FF) |
| **Done** | 74 |
| **Open** | 197 |
| **Awaiting Shagnik** | 7 |
| **Declined** | 1 |

## 🔴 Security — read before the next session

**1. The password shared in chat is compromised.** `Shagnik2007!` was sent in plaintext
through a chat transcript. It is **not** in the code and never was. Treat it as burned — do
not use it here or anywhere else.
*Resolved in code (session 4):* `python admin_setup.py claim shagnikpal@gmail.com` creates
the owner account with no password, then reads one from a hidden prompt and stores only a
salted scrypt hash. `auth.json` is gitignored. You choose the secret; it never reaches the
repo or me.

**2. Rotate the Gemini key** (from session 2, still outstanding). It appeared in a traceback.
<https://aistudio.google.com/apikey>

**3. Machine control must not ship to a public host.** *Resolved session 4* —
`deploy_mode.py` removes those routes entirely from a hosted build (404, not 403). The
deployed site is a static landing page only; it carries no API and no secrets.

## ⚠️ Action required from Shagnik

**Rotate the Gemini API key.** While diagnosing, the key was printed in a traceback
(the Generative Language API passes credentials as a URL query parameter, and `requests`
embeds the full URL in exception text). Get a new key at <https://aistudio.google.com/apikey>,
replace `GEMINI_API_KEY` in `.env.local`, and delete the old one in the console.
The code no longer leaks it — `_scrub_key()` in `providers/gemini_provider.py` redacts it —
but the exposed value should be treated as burned.

---

## NEXT UP — start here

**Loop ended** at Shagnik's request (job `b0969d67` deleted).

### 🚀 Live and public

**https://nyx-ichos.vercel.app** — 200, publicly reachable, security headers set.

Note the *long* team URL (`nyx-ichos-…-shagnikpal-5976s-projects.vercel.app`) still has
Vercel SSO on it and 302s to a login. The short alias above is the one to share.

The site is a static landing page: no API, no secrets, nothing to attack.

**Session 5 — the engine now serves the workspace itself.** Previously the UI needed a
second terminal running Vite on `:5173`, so pressing "Open the workspace" without it gave
**ERR_CONNECTION_REFUSED**. `server.py` now mounts the built bundle at `/`, so
`uvicorn server:app` is the entire product on one URL. The landing button also starts
**disabled** and only enables once `/api/health` actually answers — re-polling every 4s, so
starting the engine lights it up without a reload. It can no longer navigate to a dead page.

Favicon added (`favicon.svg`) and served by both the site and the local engine, including at
`/favicon.ico` since browsers request that unprompted.

1. **DD remainder.** Widgets, drag-reorder, and the event log all landed. Still open:
   widget *resize* (DD11), live tab embedding inside a bound widget (DD8), running a saved
   prompt on a schedule (DD9), and wiring finance data into its widget (DD7).
2. **AA8** (per-tab change mode) and **AA11** (prompt existing users to accept an update).
   The change pipeline is otherwise complete: propose, review, approve, publish, apply,
   verify, auto-revert, roll back.
3. **Wire the connectors to the gate.** `machine_control.py` decides; `connectors/
   system_control.py` and `local_files.py` do not yet *call* `MACHINE.check()` before acting.
   Until they do, the gate protects the API but not direct connector use.
4. **CC remainder.** Creation, fuzzy search, rendering, conversational editing, the side
   panel, combine and delete all work. Left: overriding a *shipped* tab (CC10), and wiring
   the list/stat/links/embed blocks to real data sources — they render an honest
   "not wired yet" note today.
6. **B3 / B6** — the agent work still outstanding: the inter-agent message bus, and auto
   scale-up/scale-down. B1, B2, B4, B5 landed in session 4.
7. **Wire the team into the chat loop.** Agents can be created and observed, but nothing
   drives them from a conversation yet — the master does not actually delegate.
8. **BB1 remainder** — drag-to-reorder, pin/close for non-core tabs.
9. **D1 re-test** — the stale-answer bug was probably the offline fallback; verify now that
   chat works before building anything for it.

### Latency, after the session-5 sweep

| Endpoint | Before | After |
|---|---|---|
| `/api/models` | 4112ms | 544ms |
| `/api/status` | 2207ms | 720ms |
| everything else | — | under 40ms |

Both remaining costs are first-call-only (cached after). Root cause was the same defect twice:
a probe timeout applies **per resolved address**, and `localhost` resolves to `::1` *and*
`127.0.0.1` — so every budget silently doubled. `_probe_url()` now pins the IPv4 loopback.
`list_models()` also paid its own full timeout after availability had already failed, and
`get_status()` called `is_online()` twice for one fact.

### Still true before beta testers rely on it

- **Sessions are in-memory**, so every backend restart logs everyone out. Fine locally;
  needs a real session store before testers depend on it.
- The deny-by-default middleware only gates `/api/*`. Any non-API route added later is
  outside it — keep new surfaces under `/api/`.
- *Resolved:* CORS is now an explicit allowlist, and the two-build split is built
  (`deploy_mode.py`).

### Known weakness worth fixing early

`_SEARCH_INTENT_PATTERNS` in `chat_service.py` contains very generic phrases —
`"let me check"`, `"let me read"`, `"let me look"`. These fire a **web search** on ordinary
local coding turns ("let me check that file"). The one-shot guard added in session 1 caps
the damage at a single wasted search per turn, but the patterns should be narrowed to
web-directed intent, or gated on the question actually being about external/current facts.
Relevant to C9 (command-less by default) — the more intent detection drives behaviour, the
more false positives cost.

---

## Session log

### Session — 2026-10-08 (Claude Opus 5.5, session aa7147) — Mods

Added `mods.py` (Claude Code-style mods as data): catalogue of parts, validation with named refusals, mod_* tools, a
per-turn `[Your mods]` note, tool blocking at `tools.call_tool`, mod /commands, `/api/mods`, Settings → Mods, the band
above the composer, reminders. Also wired the frontend to the `ui.theme` / `ui.open_tab` / `tabs.changed` events it
had never listened to. Tests: `tests/test_mods.py` (17). Detail: AI_HANDOFF/START_HERE.md → DONE — MODS.

### Session — 2026-09-22 → 25 (Claude Opus 5, session be872d) — Project Null N19b, N20–N25 (rows N80–N89)

Eight sessions worked this tree at once, so the first act was agreeing file ownership by message; that list is in
PROJECT_NULL.md. Built, in this order: **quiet_windows.py** (no child process may open a console window — the fix is
one process-wide default rather than a flag per call site, because one missed call is enough to interrupt typing);
**trading run modes** (market / 24-7 / until, with a real NYSE calendar in `market.py`, so nobody has to start it at
the opening bell); **the practice account** (spread, slippage, commission, orders queued to the open, equity curve,
vs-SPY, and `Broker.money()` so "practice" vs "real" is decided in one place); **question cards**; **the chat mode
slider** (Normal · Co-work · Plan, with a deny-by-default tool gate that makes "Plan changes nothing" true rather
than promised); **Notes slide upload** (a deck stays a numbered list of slides with the speaker notes, so "questions
on slides 12–18" means exactly that); **Clap** (clap/whistle by shape, anything else taught from three takes and
matched with DTW — offline, nothing recorded); **design sense** (a brief built from the owner's own past UI words,
what they undid, this app's tokens and the Apple library, ending in what to avoid).

Two bugs found by verifying rather than by testing: a model wrote a perfect question card and dropped the code
fence, so the owner saw raw JSON — the renderer now finds bare question/plan JSON by balancing braces; and
`notes_store` refused the new "slides" note kind, which no amount of parser testing caught (there is now a
route-level test). Full suite 2019 passed. Live-verified against the running engine: the Trading tab, a real
question card answered by clicking, Plan mode producing a plan and touching nothing, a 6-slide deck → questions on
slides 3–4 using the lecturer's note, and the Clap panel + greeting. Not exercised: real audio detection (no
microphone here) and the Co-work checklist rendering.

### Session — 2026-09-16 (Claude Opus 5, Request J)

Diagnosed from the owner's data before coding: auto-approve blocked 94/101 changes because the critic read an empty
diff; 701 near-duplicate proposals piled up; "Apply all" typed into Improve started new runs; role fallback skipped a
cooling NVIDIA and died on a Gemini 429; study said "Nothing new to learn" because replies were cut at 1500 tokens; the
custom-model URL refused local servers and base URLs. Built J1–J9 (see START_HERE.md): model fallback, research →
sandbox → real-diff critic → apply, review queue + deep mode UI, agent /commands with parallel boxes, auto sub-agent
matching, the Core view, Add-model URL check, `read_handoff`. Full suite 1394 passed; live-verified in the browser.
Queued K–O from the owner's messages during the session.


### Session — 2026-09-15 (Codex, continuing Claude's Request H handoff)

Completed H16 without changing the established workspace layout: `DynamicTab.tsx` now renders the server-validated
background/theme data and turns H16's block types into real UI. Lists and charts render their supplied data; trackers
persist device-local entries; timers only hand work to Nyx after the user clicks; scheduled tasks become ready for
review rather than silently spending a model budget; and tic-tac-toe, Connect Four, Memory, and Snake run inside
the custom tab. Built cleanly and verified `tests/test_tab_freedom.py` (4 passed), then live-tested a temporary
custom tab and removed it. Restarted the launcher-managed engine so its API loaded the background/theme fields.

### Session 1 — 2026-08-26

**Presenting problem:** VS Code reported no Python after the project was moved by USB stick.

**Root cause found.** Not a Python installation problem at all. The project `.venv` had been
built against a Codex CLI cached runtime:

```
home = C:\Users\shagn\.cache\codex-runtimes\codex-primary-runtime\dependencies\python
version = 3.12.13
```

That cache directory no longer exists. A venv is a thin shim over a base interpreter, so the
venv died with it. VS Code had the dead venv selected, so every Python feature reported nothing
available. Its log confirmed: `[interpreterSelection] global: none (source: autoDiscovery)`.

**Fixed:**
- Moved dead venv to `.venv.broken`, rebuilt `.venv` from system Python 3.14.7
- Reinstalled all of `requirements.txt`, including `fastapi`/`uvicorn` which were listed but
  had never actually been installed in the old venv
- Found two dependencies missing from `requirements.txt` entirely: `numpy` and `httpx2`.
  Their absence was breaking collection of every server and voice test — 4 collection errors,
  suite would not run at all.
- Added both to `requirements.txt` with comments explaining why
- Suite went from "will not collect" to **298/298 passing**
- Pinned `python.defaultInterpreterPath` in `.vscode/settings.json` at both the outer workspace
  root and the inner project folder, since the workspace root is the outer `Ai Dev Folder`
  but the project lives in the nested one

**Also delivered:**
- Four subagents in `.claude/agents/` — `nyx-manager`, `nyx-planner`, `nyx-coder-core`,
  `nyx-coder-interface`
- `ROADMAP.md` — all 147 requests itemised with IDs and status
- This file
- `KEYS_NEEDED.md` — API keys required, and what degrades without each

**Then fixed C1 — the "stops after announcing a search" bug.**

Reproduced it first. In `chat_service.chat()` the tool loop had five defects:

1. When the iteration budget (5) ran out, the loop exited still holding the response that
   *contained* the tool call. A post-loop check saw tool markup and replaced it with
   "I could not complete the lookup" — so a turn where the tools had **succeeded** was
   reported to the user as a failure.
2. No final synthesis pass. Nothing ever turned the last tool results into an answer.
3. `_append_assistant_response` was only reached on one exit path. On budget exhaustion the
   assistant turn was **never persisted** — 0 assistant messages in history. This is why a
   re-prompt was needed: the conversation had no record the exchange happened.
4. Auto-search had no repeat guard. A model that kept narrating intent without emitting a
   call re-ran the identical query every iteration, burning the whole budget on duplicates.
5. Raw `<tool_call>` markup could reach the user.

Fixed all five: forced tool-free synthesis pass when an answer is owed, guaranteed
persistence on every path, `_strip_tool_calls` so markup never surfaces, and a one-shot
`auto_searched` guard. Added 4 regression tests. Updated
`test_chat_service_tool_call_max_iterations`, which had been asserting the buggy behaviour.

Suite: **298 → 302 passing.**

**Also:** A8 — attribution added to CLI banner, `server.py` OpenAPI metadata, and README.

**Not started:** the rest of the feature work. This session went to repair, agent setup,
capturing the backlog, and the highest-priority bug.

---

### Session 2 — 2026-08-26

**Presenting problem:** chat replied with generic filler ("let's define the goal, isolate the
minimum working version...") instead of doing anything.

**That filler was the offline fallback.** The chat was never reaching a model at all —
`ChatService` returned provider `offline` on every turn. Four separate faults stacked up:

1. **Retired Gemini model.** `.env.local` pinned `gemini-2.5-flash`, and the provider default
   was `gemini-2.0-flash`. Both now return
   `404 — "no longer available to new users"`. Confusingly `ListModels` still lists them;
   only `generateContent` rejects them. Now `gemini-flash-lite-latest`.
2. **Router gave up after one fallback.** `chat()` tried primary + exactly one alternate, then
   raised. Replaced with `_candidate_chain()`, which walks every available provider and only
   fails once all have failed — reporting each failure by name.
3. **`FREE_ONLY=true`** in `.env.local` excludes all paid providers, so the working OpenAI key
   was never eligible. Left as-is: it is a deliberate setting and matches the free-to-run goal.
   Worth knowing it means Gemini is currently the only online provider.
4. **Ollama probe cost ~4s and ran twice per turn.** With Ollama not installed, `localhost`
   resolves to both `::1` and `127.0.0.1` and Windows burns the full 5s timeout refusing each.
   That was ~8s of dead wait on every single message. Now cached (30s TTL) with a 1s timeout.

**Measured result:** 3 representative prompts went from *offline / 37.3s total* to
**9.8s total, 3.3s average, best case 0.62s.** The test suite also dropped 18s → 12s, since
it was paying the same Ollama probe.

**Also fixed:**
- **API keys leaked into error text.** `requests` embeds the key-bearing URL in exceptions,
  which reach logs, metrics, and saved chat history. Added `_scrub_key()`; errors now surface
  the API's own message instead of the raw URL.
- **Pointless retries on permanent failures.** A 404 was retried 3× with backoff. Retries are
  now limited to `{408, 429, 500, 502, 503, 504}`.
- **The test suite wrote into real user data.** Any test building a bare `ChatService` appended
  to the project's `chats.json` and `memory.json` — ~50 assistant messages per run, 499
  accumulated. This also made `test_chat_sessions` fail intermittently depending on leftover
  state. Added `tests/conftest.py` with an autouse fixture redirecting the default paths to
  `tmp_path`. Verified: 499 before a run, 499 after.

**Tests:** 302 → **311**. New file `tests/test_provider_resilience.py` (9 tests) covering
retired-model handling, key scrubbing, no-retry-on-permanent, probe caching, and the router
cascade.

**Roadmap:** added **section S — App Designer** (11 items) for the Artifacts/Canvas/Codex-style
capability, including hardware-adaptive execution and computer control for the build loop.

---

### Session 3 — 2026-08-26

**Delivered:** front-end design handoff reviewed, 3 new agents, and the two priorities
Shagnik named — hardware safety and response speed.

**Design handoff reviewed.** `C:\Users\shagn\Downloads\Local AI Agent Platform-handoff\`.
Claude Design prototypes using `x-dc`/`sc-if`/`sc-for` templating — mockups, not production
code. 8 core tabs: Chat, Dashboard, Sessions & Memory, Models, Agents, Connectors,
Add capability, Settings. Two layouts (rail 206px / strip). Palette `#161826` bg, `#12141f`
nav, tokens in `_ds/nocturne-*/styles.css`. Target is the existing `frontend/nyx-pulse`
React+TS+Vite app. Captured as roadmap section **BB**; not yet implemented.

**🔴 Hardware safety was blind — fixed.** The monitor only tried `pynvml`, which is not
installed. It fell back to **all-zero readings and then declared the machine safe on the
strength of those zeros**. Meanwhile `nvidia-smi` was working the entire time and reporting
live data (RTX 5080 Laptop, 45°C, 776/16303 MB, 51% util, 40W).

This was the single most dangerous defect found so far: the safety system Shagnik named as
a constant top priority was reporting "within safe limits" without ever reading the hardware.
On a hot or VRAM-starved machine it would have approved the workload anyway.

Fixed with an `nvidia-smi` subprocess fallback (no new dependency — it ships with the driver),
2s telemetry cache, and sanity-checking so garbage readings are rejected rather than trusted.
A machine with no telemetry now reports `no_gpu_telemetry (conservative fallback)` instead of
zeros, so blind is distinguishable from cool-and-idle. Cold read 74ms, cached 0ms.
14 tests in `tests/test_hardware_safety_telemetry.py`.

**Fast response (W1–W4) — 7x on simple turns.** New `fast_response.py`. A per-turn policy
routes simple messages to a lean path: ~600 char prompt instead of the ~8KB tool-schema one,
single call, no tool loop. Auto by default, escalates automatically if the model signals it
needs tools, and leaves no trace of the abandoned attempt in history.

Measured, same three prompts: **27.31s full pipeline → 3.88s auto (7.0x)**, with warm simple
turns landing at 0.5–0.6s.

**A design bug my own session-1 test caught:** the first version of the policy routed
*"who is the president?"* to the tool-less fast path — which would have reintroduced the exact
stale-answer bug (D1) Shagnik reported. Questions about people and roles are the classic
staleness trap, so they now force the full pipeline. `TaskAnalyzer` classifies bare "who" as
SIMPLE, which is right for effort and wrong for freshness; the policy overrides it.

**Tests:** 325 → **355**.

**New agents:** `nyx-frontend` (React from the handoff), `nyx-platform` (auth, permissions,
admin, deploy — carries the security rules), `nyx-safety` (hardware + latency). Seven total.

**Roadmap:** +9 sections capturing every new request — **T** auto-everything, **U** skills,
**V** permissions/machine control, **W** fast response, **X** hardware safety, **Y** training
modes, **Z** personalities v2, **AA** accounts/admin/distribution, **BB** front end.

**Not done:** the bulk of sections T–BB. This session covered the two stated priorities plus
the agents and backlog capture. The app/website build (BB) is a multi-session effort and has
not started.

---

### Session 4 — 2026-08-26 (loop, 10-min cadence)

**Front end shell built and building clean.** `frontend/nyx-pulse` now has the real
workspace from the design handoff:

- `src/theme.css` — the nocturne palette as tokens (`#161826` bg, `#12141f` nav, `#9184d9` accent)
- `src/App.tsx` — header with avatar + host pill, rail (206px) / strip layout toggle
  persisted to `localStorage`, all 8 core tabs
- `src/components/NyxAvatar.tsx` — state-reactive SVG core (idle/thinking/coding/listening/error),
  pure CSS animation so it costs no frames on a weak machine
- `src/components/Panel.tsx` — shared loading/empty/error primitives. The error state detects
  "backend unreachable" and shows the exact uvicorn command, since that is the common case.
- `src/panels/ChatPanel.tsx` — **fully wired**, shows provider and per-turn latency
- `src/panels/DashboardPanel.tsx` — **fully wired**, live hardware/routing/provider health on a
  5s poll. Renders `no_gpu_telemetry` as *unknown*, never as a healthy zero.
- `src/panels/PlaceholderPanels.tsx` — the other 5 tabs render live backend JSON and state
  plainly what is not built. Honest placeholders, not fake screens.
- `src/api.ts` — typed client; every call degrades to a typed error rather than throwing

Build: `tsc -b && vite build` clean. 206 KB JS / 8.3 KB CSS gzipped to 65 KB / 2.8 KB.

**Environment fixes needed to get there:**
- **Node.js was not installed at all.** `node_modules/` had come across in the USB transfer but
  was incomplete and unusable. Installed Node 24.19.0 LTS via winget, ran a clean `npm install`.
- CSS build failure: a comment in `theme.css` contained `*/` inside a path, closing the comment
  early and breaking lightningcss. Fixed.

**8th agent added:** `nyx-improver` — finds improvements, audits for gaps, looks at what
comparable tools do better. Proposes and ranks; does not implement. Shagnik called it "the 5th",
which matches the original four; the roster is now eight.

**Note on `npm`:** Node installs to `C:\Program Files\nodejs`, which is not on this session's
PATH. Prefix commands with
`$env:Path = "$env:ProgramFiles\nodejs;$env:Path"` or open a fresh terminal.

**Accounts, roles, and beta invites shipped (AA1, AA3, AA4, AA5).** New `auth.py` +
`admin_setup.py`, 48 tests, suite 355 → **403**.

- **No credential anywhere in the repo.** `bootstrap_owner` creates the account with *no*
  password; it cannot be logged into until someone sets one at a hidden prompt. That is what
  makes the bootstrap safe to commit and ship.
- **scrypt** (memory-hard, stdlib) with a per-user salt. Hit OpenSSL's 32 MiB default ceiling
  at n=2¹⁵ — raised `maxmem` to 64 MiB rather than weakening the cost factor, since the
  memory hardness is the whole reason to pick scrypt.
- **Deny by default.** `has_permission` returns False for anything unrecognised.
  `MACHINE_CONTROL` is **owner-only** — admins and beta testers cannot drive the machine.
- Login errors do not distinguish "no such user" from "wrong password" (enumeration oracle),
  and comparisons use `hmac.compare_digest`.
- Sessions are in-memory only, so a restart logs everyone out — the safe default for a tool
  with machine access. `auth.json` is gitignored and chmod 600 where supported.
- Invites: single-use, 14-day expiry, optionally pinned to one address. Admins can invite
  testers but **not** other admins; only the owner grows the admin set.

**Frontend login shipped — the loop is now safe to claim.** `AuthScreen.tsx` (login + invite
redemption), token handling in `api.ts`, and an auth gate in `App.tsx`.

- The gate only engages on `claimed === true`. Gating on an *unknown* state would lock the
  user out whenever the backend was briefly down, which is the opposite of what a safety
  gate should do.
- An `?invite=…` URL takes priority over everything — the recipient has no account yet.
- A 401 from any call clears the token and drops to the login screen. Sessions are in-memory,
  so a backend restart does exactly this; without the handler the app would sit there
  showing silent failures.
- The header shows the signed-in role with a sign-out button.

Verified end to end against a live TestClient: fresh install loads with no login → claim →
login screen appears → chat gated (401) → owner signs in → mints an invite link → tester
redeems → tester can chat (400 on empty message, so auth passed) → tester blocked from admin
(403). Frontend build clean, 212 KB / 66.6 KB gzipped.

**Agent team runtime + Agents tab (B1, B2, B4, B5, BB6).** New `agent_team.py`: named agents
with individual goals, a master/worker hierarchy holding exactly one master, per-agent
personality ids, and thread-safe progress reporting. `GET|POST|DELETE /api/agents` drive it —
`POST` takes a list, so "create 3 sub-agents, two with goals, one managing the others" is one
call. 20 unit tests + 4 endpoint tests.

The Agents tab is a standing view refreshing every 3s, and gives the two diagnoses that make
a stalled team distinguishable from an idle one:
- **the machine is throttling you** — reads the safety monitor and says so, with temperature
  and utilisation, rather than leaving a slow agent looking stuck
- **that goal is too vague** — flags workers whose goal is too short to act on, so the prompt
  gets blamed when the prompt is at fault

Design detail worth keeping: an auto-created master is *replaced* by a real one, but a
user-created master is only *demoted*. Deleting an agent the user made would silently discard
their work; deleting a placeholder the team made for itself is just tidying.

**Store tab (BB8)** is an honest empty state rather than a mock storefront — the skills system
does not exist, and a grid of fake cards would imply it does. `PlaceholderPanels.tsx` is gone;
every tab now has its own file.

**Settings tab built (BB9, W3, Z1).** New `/api/speed` GET/POST plus `SettingsPanel.tsx`.
Speed mode is now switchable from the UI — Auto (default, marked recommended), Fast, Full —
with each option stating what it costs, because a settings screen that presents every choice
as equally good pushes people into worse configurations. The Fast entry says plainly that it
cannot search or read files and so can be wrong about anything current. Personality presets
render (Gen Z already exists in the backend); the picker is browser-local for now, and the
panel says so rather than implying it persists.

**Machine control (V1-V8) + the deploy split (BB12).**

`machine_control.py` — deny-by-default capability grants that are scoped, expiring, and
revocable, with a full audit trail. 53 tests, almost all of them attempts to get through the
gate. Four properties hold:
- **Nothing is available until granted**, and grants expire — a permission the user forgot
  they gave is one they did not really give.
- **Some targets are never reachable**, granted or not: `.ssh`, `System32`, `.env.local`,
  `auth.json`, `/etc/shadow`. Checked *before* the grant, so no grant can open one.
- **Destructive actions need confirmation even when granted.** A standing grant to write is
  not consent to delete.
- **`revoke_all()` is a kill switch**, and refusals are logged as well as successes — a trail
  of successes only cannot answer "what did it try to do".

`deploy_mode.py` — the local/hosted split. In hosted mode the machine-control and
overlay-restore routes are **absent, returning 404**, not merely permission-gated. A
permission check protects against the wrong user; it does not protect against a bug in the
permission check. For these two, the safe design is that the code path does not exist.
Local is the default: a hosted build that thinks it is local is a breach, the reverse is a
nuisance.

Also tightened CORS — was `allow_origins=["*"]`, now an explicit localhost list plus whatever
`NYX_ALLOWED_ORIGINS` names.

**Side edit panel (CC8).** Sits on the edge of the tab it edits, so a change and its result
are visible at once. Typed instructions go to the conversational endpoint, and the applied
history labels each edit **local** or **model** — "instant and free" versus "a round trip" is
a difference worth showing rather than hiding.

**Conversational tab editing (CC9).** New `tab_editor.py` + `POST /api/tabs/{id}/edit`.

Two paths, in order. **Common edits are read locally** — colour, rename, add or remove a
block — so "make it green" is instant, free, and works offline; a model round trip to turn
that into `{"accent": "#5ac08a"}` is waste. Anything ambiguous returns `None`, which means
"ask the model" rather than guess: an unknown colour like "chartreuse" defers instead of
inventing one.

The model path treats a reply as a **proposal, not a spec** — unknown keys are dropped (so a
model cannot set `tab_id` or `author`), and the result goes through the same validation as a
hand-written edit.

**A real bug caught by its own test:** the rename capture was greedy, so
"call it Journal and make it green" named the tab *"Journal and make it green"*. Names now
stop at the next clause — and, then, also, plus, but, or a comma.

Verified live: `make it green` → #5ac08a · `call it Journal and make it blue` → label
"Journal", accent #5a9ce0 · `add a checklist` → blocks [notes, checklist]. All three took the
local path, so none cost a model call.

**Dynamic tabs — frontend (CC1, CC2, CC4, CC6, CC8, CC11).** `DynamicTab.tsx` renders a spec;
`TabFinder.tsx` is one box that searches and, when nothing matches, offers to build it.
Ctrl+K opens it. User tabs appear in the nav under "Your tabs".

Notes and checklist blocks work and persist, and say plainly that they are stored in this
browser only — the honest scope until there is a server-side store. The chat block scopes a
conversation to the tab. Blocks that are defined but not yet wired to data say so rather than
rendering an empty box.

Verified end to end: search "notes" on a fresh install offers creation → create an "Inbox" tab
→ searching **"email"** finds it via its description → rename and recolour → an
`expression(alert(1))` accent is refused (400) → a `system_control` connector is refused (400)
→ combine two tabs, originals intact.

**Dynamic tabs (CC1-CC12, backend).** New `dynamic_tabs.py` + 7 endpoints.

A tab is a **declarative spec the client renders, never generated code**. The validator is
where that line is held, and most of the 51 tests attack it:
- **Unknown block types are refused** — the client can only render blocks it knows.
- **Icons must be Phosphor names; accents must be a hex colour or a design token.**
  `<script>`, `javascript:`, and `expression(alert(1))` are all rejected.
- **A generated tab cannot grant itself capability.** `system_control`, `app_launcher`, `mcp`,
  and `dynamic_modularity` are outside the allowed connector list, so a tab written from a
  user description cannot reach machine control by asking for it.
- **Editing is re-validated**, so it is not a way around the rules that applied at creation.

Fuzzy search matches label, description, and block titles across both user and shipped tabs,
and reports which words matched — "email" finds a tab called "Inbox" described as
"my email and messages". An unmatched search sets `offer_create`.

Tabs persist per user in their own file, so a base-app update never wipes them, and an
invalid stored tab is skipped rather than breaking the nav.

**Skills system (U1-U5).** New `skills.py`, wired into the chat loop, with a real Store tab.

A skill is **instructions plus triggers, never executed code** — so a skill the agent writes
from a user description can at worst give bad advice, never run anything. Same line drawn for
tabs, widgets, and the overlay.

Attachment is automatic and costs nothing when nothing matches. Capped at 3 per turn, because
five sets of instructions cancel each other out. Verified ranking on real messages:
"what is the latest news" picks **Research (2 hits)** over Explaining (1); "mmm" picks nothing.

Six built-ins ship: Debugging, Code review, Explaining, Maths, Writing, Research. They can be
disabled but **not deleted**, and shipped text always wins over a stored copy — otherwise an
app update could never improve a built-in the user already had.

The Store tab has a live preview: type a message, see which skills would attach and on how many
triggers. Automatic behaviour is only trustworthy if you can see why it fired.

**Self-revival completed (F3, F5).** New `health_check.py`, wired into publish.

After a change is applied the app is verified — overlay readable, core modules importable,
auth still resolving, widgets loadable, safety monitor reporting. If anything fails, the
change is **reverted inside the same request** and the publish refused with a 409 naming what
broke. A bad change never survives long enough for a user to find it.

Two deliberate design points, both learned from earlier bugs in this project:
- **A check that raises has become the hazard** (the session-3 safety monitor lesson). Every
  check is individually wrapped and a failure is reported, never propagated.
- **`Exception` is caught, `BaseException` is not.** Swallowing a Ctrl-C so a health check
  could finish would itself be a bug — there is a test asserting the interrupt still escapes.

Also added `GET /api/health/deep`, distinct from the cheap `/api/health` liveness ping the
login screen polls.

**Publish now actually applies (AA10, F1, F2, F3).** New `overlay.py`.

Published changes land in an **overlay layer above the shipped app**, never in the base
modules — so the shipped code is always intact and always the fallback, a base-app update
never wipes what was changed, and reverting is deleting a layer rather than un-editing a file.
This is F1's "weighted self-update": the agent may change the app, but it cannot reach the
floor it stands on. Overlay values are **data the app interprets, never executed code**.

A checkpoint is taken before every apply and every revert (F2), bounded to 20.
`restore_latest()` is the panic button (F3). If applying fails, the publish is **refused** and
the overlay change undone, so the record and the running app never disagree about what is live.

**Two real bugs found and fixed while testing this:**
1. Checkpoint filenames carry only whole seconds, so two checkpoints taken in the same second
   sorted by their random suffix — making "restore the latest" non-deterministic exactly during
   rapid changes, which is when someone reaches for it. Now ordered by recorded `created_at`.
2. `_prune_checkpoints` had the same flaw and was worse: it could delete a **newer** checkpoint
   and keep an older one. Now ordered by mtime.

Also moved target validation to proposal time — a path-escaping target used to sit in the
review queue looking approvable and only fail at publish.

**Admin Changes tab (AA9).** `AdminPanel.tsx` — propose, ask the AI to review, approve,
reject, publish, roll back, with a before/after diff view. The UI mirrors the backend rule
rather than working around it: **Publish is only offered on an approved change**, and the AI
review is labelled "notes only, not a decision". Agent-authored changes carry a visible badge.
The tab is hidden for non-admin accounts via `visibleTabs()` — presentation only, since the
server enforces the real boundary on every request.

Verified end to end against a live server: propose -> publish refused (400) -> approve ->
publish -> rollback restored the previous content.

**Admin change pipeline (AA7, AA9, AA10, F7).** New `change_review.py` + 7 endpoints.
Every modification — hand-made or agent-proposed — becomes a reviewable record before it can
reach anyone:

    draft -> in_review -> approved -> published -> rolled_back
                       \-> rejected

Three properties the tests hold:
- **Nothing publishes without passing review.** A draft cannot jump to published, and an
  agent-authored change gets exactly the same gate as a human one. This is what makes leaving
  self-modification switched on defensible.
- **Review is notes, not a verdict.** `attach_review` deliberately does not approve. Collapsing
  the two would let an AI review approve its own change. The review prompt asks for problems
  and explicitly says not to approve or reject.
- **Only the owner may target `base_ai`.** Admins can review and publish tab-level changes;
  rewriting the core is owner-only, enforced server-side and tested with a real admin account.

Every change keeps `previous_content`, so rollback restores rather than guesses.

**HUD widgets + real event log (DD6, DD8, DD9, DD11, DD12).** New `widgets.py` and
`event_log.py`.

Widgets are a **declarative spec, not code** — a widget names a type and some config, and the
client renders it. Storing renderable code would be an injection surface and would break the
update path, the same reasoning as the dynamic-tabs note in section CC. Layout persists to its
own file so a base-app update never silently rearranges someone's HUD, and a corrupt layout
file falls back to defaults: the user loses their arrangement, not the application.

Widgets bound to a tab or a saved prompt **refuse to be created without a target**, because a
widget bound to nothing is a blank box rather than a feature.

The event log is a bounded ring buffer (500) wired into real activity — the router records
provider latency and failures, the safety monitor records throttle *transitions* only (it is
consulted every turn, so logging each poll would flood it). Verified live: the log captured
`gemini answered in 0.66s` from an actual chat.

**Models tab built (BB5, AA14, X3, X4).** `ModelsPanel.tsx` — Auto shown as active and
recommended, live local/online provider state, and a **quality tier derived from the detected
device** rather than chosen by the user. A weak machine gets a named warning: at `small` it
says a large local model will swap; at `tiny` it says local inference can hang the system and
asks the user not to override Auto. Undetected hardware is treated as low-spec, and the panel
says that is deliberate rather than a bug. Also surfaces why free-only mode is hiding a
configured paid provider — a confusing state otherwise.

**Frontend login shipped — safe to claim the owner account now.** `AuthScreen.tsx` (login +
invite redemption), token handling in `api.ts`, auth gate in `App.tsx`.

- The gate engages only on `claimed === true`. Gating on an *unknown* state would lock the
  user out whenever the backend was briefly down — the opposite of what a safety gate is for.
- An `?invite=…` URL takes priority over everything else: the recipient has no account yet.
- A 401 from any call clears the token and returns to the login screen. Sessions are
  in-memory, so a backend restart does exactly this; without the handler the app would sit
  there showing silent failures.
- Header shows the signed-in role with a sign-out button.

Verified end to end against a live TestClient: fresh install loads with no login → claim →
login screen appears → chat gated (401) → owner signs in → mints an invite link → tester
redeems → tester chats (400 on empty message, so auth passed) → tester blocked from admin
(403). Frontend build clean: 212 KB, 66.6 KB gzipped.

**API auth wired in (AA6, V1).** New `server_auth.py` + auth/admin routes, 28 tests, suite
403 → **431**.

The API picks its mode automatically, so there is nothing to configure and no window where a
deployed instance is accidentally open:

- **Unclaimed** (no owner account) — a fresh local install. Chat works without a login.
- **Claimed** (someone ran `admin_setup.py claim`) — every route needs a session.

Privileged routes are refused in **both** modes: with no owner there is nobody who could hold
the permission, and leaving them open would make an unclaimed instance strictly more powerful
than a claimed one, which is backwards.

New routes: `POST /api/auth/login`, `/logout`, `/join` (redeem invite), `GET /api/auth/me`,
`GET|POST /api/admin/invites`, `GET /api/admin/users`, `POST /api/admin/grant`.
`GET /api/health` now reports `claimed` so the UI knows whether to show a login.

**Two bugs found and fixed while wiring this:**
1. The request models were never inserted by the patch that added the routes, but
   `from __future__ import annotations` turned what should have been an import-time
   `NameError` into a runtime 422. The module imported cleanly and every login failed.
   Worth remembering: in this file, a missing model will not fail at import.
2. `logout` and `admin_invites` declared `authorization: Optional[str] = None`, which FastAPI
   reads as a **query parameter**, not a header. Now `Header(default=None)`.


### Session — 2026-09-22 → 24 (Claude, "AAI trader optimization and settings", c36c1d)

Owner asked for a fully optimized, fully automatic AI trader: a realistic $50 start, active buying and selling, no
dumping everything into one dead stock, learning from mistakes however small, an auto stock adder, and a one-button
hands-off **Adaptive mode**. Built (tests: `tests/test_trading_allocator.py` 12, `tests/test_trading_adaptive.py` 19;
all trading tests 49 green):
- `trading/allocator.py` — spreads money over several best-ranked picks, per-stock cap, stop-loss / take-profit /
  sell-signal exits, rotation out of the weakest holding when a clearly better pick waits.
- `trading/signals.py` — `symbol_reliability` (past hit rate shrinks or grows sizing), `rank_watchlist` (parallel scan).
- `trading/lessons.py` — every AI exit recorded; any loss → 3-day cool-down on that stock, two in 14 days → 7 days.
- `trading/discovery.py` — auto stock adder: ~97-symbol universe in slices + tickers from today's news, scored, researched,
  added; only removes symbols it added itself.
- `trading/adaptive.py` — chooses budget (up to 97% of usable money, less in a falling market or a losing streak), spread,
  confidence bar, volatility-based stops, 5-minute pace, no daily trade limit; the owner's on/off schedule.
- `trading/autopilot.py` — scan rewritten: reconcile holdings → discover → adaptive values → sell → rotate → buy (a
  flagged pick's slot goes to the next pick); one scan at a time (`_SCAN_LOCK`); pending queued buys count against money.
- FIXED (pre-existing): `research()` read the echoed instruction "VERDICT: OK or VERDICT: AVOID" in a thinking model's
  reply as a red flag, so the AI trader refused every buy. Now the last verdict line only, thinking off, 6-hour cache.
- Routes `GET/POST /api/trading/adaptive`, `POST /api/trading/discover`; chat tools `trading_adaptive`, `trading_discover`,
  `trading_configure`, `trading_opportunities`. UI `panels/trading/AdaptiveCard.tsx`. LIVE-VERIFIED on port 8031 with a
  scratch `NYX_DATA_DIR`: $50 → 4 buys of ~$12 queued for the open, stock adder added 8 symbols, Stop works.
- Owner's real practice account: $50, AI on, approval "never" (set 2026-09-22). Adaptive mode left OFF for the owner to press.

### Session — 2026-09-26 (Claude Opus 5.5, session 985454) — engine shutdown hang

- FIXED: `server._shutdown_background_work` awaited every task in `asyncio.all_tasks()`, which includes the server's own
  task (uvicorn's serve / TestClient's portal) that is waiting for shutdown to finish, so shutdown waited on itself:
  `with TestClient(server.app)` never exited, and under uvicorn each foreign task cost `SHUTDOWN_TIMEOUT` on every stop or
  restart. Shutdown now waits only on `_BACKGROUND_TASKS` (async work started through the new `server.spawn_background`):
  one bounded wait, then cancel what overran. The scheduler stop is unchanged. Nothing in Nyx starts asyncio tasks yet;
  all background work is threads. Test: `tests/test_server_shutdown.py`. Full suite 2114 passed (on top of d682945).


### Session — 2026-10-04 → 05 (Claude Opus 5.5, session 0757e7, with three Claude sub-agents) — Update 1

- Built "Update 1" from the owner's UPDATE_IDEAS list and pushed it as `update-1`. Details are in
  `AI_HANDOFF/START_HERE.md` § Update 1, which is local only: the handoff is no longer tracked in git.
- **New:**
  - Swarm and Auto chat modes (`swarm.py`, `chat_modes.choose`).
  - Full request and reply shown for every sub-agent hand-off (`agent_runtime`, `components/agents/Handoff.tsx`).
  - /auto and @auto (`auto_team.py`).
  - The Research tab is wired in and finished.
  - The live process list (`feature_catalog.live_processes`).
  - An 88-app connector catalogue (`connectors/catalog.py`, Microsoft Graph, "add any site").
  - Auto-assign for models (`model_autoassign.py`).
  - Office: Output box, Deliver now, Auto decisions, and staffing (`office/staffing.py`).
  - Nyx tab: chats on the left (`ChatRail.tsx`) with a Chat / Second Brain switch.
  - A voice bar (`VoiceTopBar.tsx`).
  - Nyx's own computer through Cua (`own_computer.py`, a worker process, and an owner-screen gate on `computer_control`).
  - The site's download button is now an outline that fills from 0 %.
- **Fixed:**
  - `.gitignore` data rules hid 47 frontend source files from GitHub.
  - The fast-path test read the owner's real accounts file.
  - Tests wrote swarm.json and google_granted.json into the real data folder.
  - A crash in one tab blanked the whole app (`TabBoundary`).
  - The window went blank after a rebuild.
  - The Office focus question could not be dismissed.
  - The Ollama model switch returned 404.
  - The context bar treated Ollama as 8k.
  - Engine shutdown waited on its own task (peer session's fix, reviewed).
- **Tests:** full suite green, with the final count in the Update 1 commit message. `npm run build` green.


### Session — 2026-10-06 (Claude Opus 5.5, session a40a67) — the World tab (AI Environment, U34–U40)

- Built the owner's top-priority item: a planet of AIs that is Office Space upscaled. A world owns a backing office and
  hands it one project at a time, so the work is real (`world/` package, `routes_world.py`, `panels/world/`). Design
  and every default decision: `docs/WORLD.md`. Write-up and open decisions: `AI_HANDOFF/START_HERE.md` § The World tab.
- Shared code touched (small): `office/engine.py` (effort per office, `add_section` / `add_agent`, `say(by_name=)`),
  `office/focus.py` (pin), `office/roles.py` (`invent(exact=)`), `OfficeView.tsx` (Upscale button), and the usual route,
  hosted-build, account-scope, process-name, gitignore and release-exclude lists.
- Live-checked on a scratch engine with real models. The government planned a project, and the office delivered it to
  the Output box. A trial law was enforced. A contest was heard and decided, and the loser's idea was founded as a
  start-up. A child was born. Stop handed the machine back. Two problems found live were fixed and tested: a
  child's name, and the Output card title.
- **Tests:** 62 new world tests and the world auth block. Full suite **2476 passed**. `npm run build` green.
- Not committed (AGENTS.md: only when asked).

---

## Agent roster

Defined in `.claude/agents/`. Invoke by name.

| Agent | Role | Territory |
|---|---|---|
| `nyx-manager` | Orchestrates, sets the coding standard, owns this file | Entry point for multi-step work |
| `nyx-planner` | Designs before code exists; writes plans and ADRs | `docs/`, `ROADMAP.md` — no source |
| `nyx-coder-core` | Backend and engines | `core/`, `providers/`, router, memory, RAG, math, reasoning, `server.py`, `tests/` |
| `nyx-coder-interface` | User-facing and outward-facing | `cli.py`, voice, personalities, `attributes/`, `connectors/` |
| `nyx-frontend` | React UI from the design handoff | `frontend/nyx-pulse` |
| `nyx-platform` | Auth, permissions, admin, deploy | security-critical surfaces |
| `nyx-safety` | Hardware safety + latency | `device_profile.py`, `hardware_safety.py`, perf |
| `nyx-improver` | Finds improvements and gaps | proposes only, `docs/improvements/` |

The manager sets the house style; the other three write to it. Territories are deliberately
non-overlapping — an agent that needs to cross a boundary hands off instead of reaching across.

---

## Open questions for Shagnik

These block or reshape specific items. Answers can be given in any order.

1. **O5 — finance.** Do you want buy/sell calls, or data + literacy + analysis with reasoning
   shown? I'll build the second by default. See the roadmap entry for why.
2. **R2 — "/radio for Claude"** — what should this do?
3. **R1** — if "not pay for pay-for-use" meant a cost dashboard or local-first routing rather
   than bypassing billing, say so and I'll build it.
4. **Q8** — TikTok saves: I can't reach them. Export or paste.
5. **R3** — ChatGPT history: same, paste what you want carried over.
6. **R4** — what is `.freebuff`?
7. **A10** — `openai_mcp/` is 2031 vendored files. Keep vendored, or make it a dependency?

---

## Conventions

- Mark an item `[x]` only after the full suite passes.
- When you finish a work unit, update the Snapshot counts, the Session log, and NEXT UP —
  in that order, before doing anything else.
- If you are running low on context or credits, stop and write the handoff into NEXT UP
  first. An accurate resume point is worth more than one extra half-finished feature.
