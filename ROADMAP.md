# Nyx Pulse — Master Roadmap

**Created by:** Shagnik
**Owner:** Shagnik
**Purpose:** The permanent, itemised backlog of every request. This file is the
source of truth across sessions. `PROJECT_STATE.md` tracks live progress against it.

**Read this file and `PROJECT_STATE.md` at the start of every session before planning anything.**

## Status legend

| Mark | Meaning |
|------|---------|
| `[ ]` | Not started |
| `[~]` | In progress |
| `[x]` | Done, tested, suite green |
| `[?]` | Needs a decision or a key from Shagnik |
| `[!]` | Blocked, or declined with reason |

## Goals (standing constraints — every increment is judged against these)

1. **Free to run and free to publish.** Anything requiring a paid service must be optional with a local fallback.
2. **Local-first.** Works offline; online capability is an enhancement, never a requirement.
3. **Smarter and faster.** Latency and answer quality are features, not afterthoughts.
4. **Self-collaboration and cross-AI collaboration.** User-supplied API keys enable extra models.
5. **Never leave the suite red.** Currently 816 tests.

---

# A. Foundation & Repair

- [x] **A1** — Repair venv orphaned by USB transfer (base interpreter was a deleted Codex cache)
- [x] **A2** — Reinstall dependencies against Python 3.14.7
- [x] **A3** — Add missing `numpy` + `httpx2` to `requirements.txt` (broke all server/voice test collection)
- [x] **A4** — Full suite green: 298/298
- [x] **A5** — Pin VS Code interpreter at both workspace levels
- [x] **A6** — Create four subagents: manager, planner, core coder, interface coder
- [x] **A7** — This roadmap + `PROJECT_STATE.md` for cross-session continuity
- [x] **A8** — Attribute the project to Shagnik in settings/about surfaces (CLI banner, `server.py` metadata, frontend footer)
- [ ] **A9** — Clean up stray artefacts: `.venv.broken`, `local_pytest_tmp - Copy`, `openai_mcp - Copy`, `tmp_*.json`
- [ ] **A10** — Decide whether vendored `openai_mcp/` (2031 files) should be a dependency instead of vendored

# B. Agent Orchestration & Self-Collaboration

- [x] **B1** — Master/worker agent hierarchy *(session 4 — `agent_team.py`; exactly one master, auto-created if absent)*. A master agent manages the others by default.
      *Note: implementing as "master/worker" — standard, unambiguous terminology for the
      controller/controlled relationship you described.*
- [x] **B2** — On-demand sub-agent spawning with per-agent goals *(session 4 — `POST /api/agents` takes a list, each with its own goal and role)*
      (e.g. "create 3 sub-agents: one for X, one for Y, one managing the others")
- [ ] **B3** — Inter-agent messaging bus so agents/sessions/chats talk to each other directly
- [x] **B4** — Live side panel showing per-agent progress *(session 4 — Agents tab, 3s refresh)*:
      status, current step, throughput, whether a local process is starving them, whether a prompt looks wrong
- [x] **B5** — Detect and surface local resource contention *(session 4 — reads the safety monitor; panel says when the machine is throttling rather than the agent being stuck)*
- [ ] **B6** — Auto scale-up/scale-down of agent count for peak efficiency
- [ ] **B7** — Agent self-conversation: model talks to itself in its own chat room to develop code/ideas
- [ ] **B8** — Cross-model collaboration between different providers, on by default
- [ ] **B9** — Multi-threaded chat: several active conversations at once without degradation
- [ ] **B10** — Auto-creation of multiple bots/sub-agents without being asked

# C. Thought Continuity & Reasoning  ← **highest priority bug**

- [x] **C1** — **Fix premature turn end.** *Fixed session 1.* The agent announced a search,
      then the turn died and a second prompt was needed to get the result.
      Root cause was in `chat_service.chat()`: when the tool-iteration budget ran out the
      loop exited holding the raw tool-call text, which a post-loop check rewrote into a
      generic failure — and nothing was persisted to history, so the next turn had no record.
      Fixed with a forced tool-free synthesis pass, guaranteed persistence, tool-markup
      stripping, and a one-shot guard on auto-search. 4 regression tests in
      `tests/test_function_calling.py`.
- [ ] **C2** — Thought continuity: finish multi-step work without needing a new prompt
- [ ] **C3** — Non-blocking background work — research/study runs without answering immediately
- [ ] **C4** — Flawless detection of "still working" vs "ready to answer"
- [ ] **C5** — Visible thinking stream: what it is thinking, transitions, how thoughts link
- [ ] **C6** — Richer thought-linking as capability grows (more connections at higher tiers)
- [ ] **C7** — Core thinking file (deliberate, user-directed reasoning) + multiple auxiliary thought files
- [ ] **C8** — Auto-apply all `approaches.py` strategies without over-weighting any single one
- [ ] **C9** — Command-less by default: intent detection replaces slash commands
- [ ] **C10** — Never go silent mid-task; keep talking while continuing to think

# D. Search & Freshness  ← **known correctness bug**

- [~] **D1** — **Fix stale answers.** *Partly addressed session 2* — the model was never reaching a provider at all (see chat outage below), so it answered from parametric memory. Re-test now that chat works before doing more.
- [ ] **D1b** — Original note: It reported a president three years out of date.
      Recency must beat cached/parametric knowledge for time-sensitive facts.
- [ ] **D2** — Combine relevance + recency in ranking
- [ ] **D3** — Self-correction when a stale answer is detected
- [ ] **D4** — Regression tests using current-events questions with known answers
- [ ] **D5** — General search quality and speed improvements

# E. Memory & Retrieval

- [ ] **E1** — High-performance RAG with modern retrieval algorithms (fast + precise)
- [ ] **E2** — Obsidian as the primary memory store; existing memory demoted to secondary
- [ ] **E3** — `general_knowledge.md` as permanent general memory (history, math, etc.) — file exists, wire it in
- [ ] **E4** — Dual-layer memory: dynamic working memory + permanent general memory
- [ ] **E5** — Prompt compression: consolidate large inputs into one optimised file
- [ ] **E6** — Custom database for structured storage
- [ ] **E7** — Local storage, cookies, session storage on the web surface
- [ ] **E8** — Permanent memory for finance context specifically

# F. Self-Modification & Safety

- [x] **F1** — Weighted self-update *(session 4 — `overlay.py`; published changes land in an overlay layer, never in shipped modules. Targets are validated as flat keys, so a change cannot reach a filesystem path)*
- [x] **F2** — Auto checkpointing *(session 4 — a checkpoint is taken before every apply and every revert; bounded to 20)*
- [x] **F3** — **Self code revival** *(session 4 — `health_check.py` runs after every apply; a change that breaks a subsystem is reverted inside the same request and the publish refused with 409)*
- [ ] **F4** — Permission tiers: minor optimisations autonomous, large/architectural changes need Shagnik
- [~] **F5** — Autonomous error detection *(session 4 — post-change health verification detects and self-corrects a bad publish; continuous background detection is not built)*
- [ ] **F6** — Discover new features/improvements online and propose them
- [~] **F7** — Diff/comparison *(session 4 — every change keeps `content` and `previous_content`, so a rollback restores rather than guesses; no visual diff yet)*

# G. Voice & Speech

- [ ] **G1** — Voice detection / wake handling
- [ ] **G2** — Voice ID; optional voice scan on app open
- [ ] **G3** — Text-to-speech with installable/switchable voices
- [ ] **G4** — Spoken code approval: permanent approval vs this-session-only, recognised by speech
- [ ] **G5** — Set mode by voice (plan / code / chat), with auto-detection when unspecified
- [ ] **G6** — Voice-driven tab switching
- [ ] **G7** — Mockup image of the voice-mode screen
- [ ] **G8** — Mockup image of the connections screen

# H. Modes & Personality

- [ ] **H1** — Plan mode, code mode, chat mode — settable explicitly, auto-detected otherwise
- [ ] **H2** — Fast on-the-fly mode creation from instructions
- [ ] **H3** — On overlap, offer: use existing mode / improve it for this situation / create a new one
- [ ] **H4** — Serious mode
- [ ] **H5** — Focus mode, able to close itself
- [ ] **H6** — Multiple personalities including a Gen-Z slang one
- [ ] **H7** — Personas as modes-with-context ("different people")
- [ ] **H8** — Sliders for tone/behaviour attributes
- [ ] **H9** — Task bubble showing everything in flight
- [ ] **H10** — Connectors listed in the UI

# I. UI, Avatar & Frontend

- [ ] **I1** — Cute side avatar with emotional expression
- [ ] **I2** — Avatar reflects current activity (coding → typing, essay → paper, finance → money eyes)
- [ ] **I3** — Avatar self-generates new expressions for unseen situations
- [x] **I4** — Logo / symbol *(session 5 — `favicon.svg`, a simplified form of the header avatar: thicker strokes and one fewer ring, because the thin rings vanish at 16px. Served by both the site and the local engine.)*
- [ ] **I5** — Streamlined high-performance UI for web and mobile
- [ ] **I6** — Streamline CLI/terminal output
- [ ] **I7** — Tabbed shell for the full app
- [ ] **I8** — Auto tab-switching on request (esp. voice mode)

# J. Tabs & Mini-Apps

- [ ] **J1** — Games tab: tic-tac-toe, super tic-tac-toe, minesweeper
- [ ] **J2** — Desmos tab — read the graph, explain, assist
- [ ] **J3** — 3D modelling tab + printer connectors
- [ ] **J4** — Part search across stores, linked to the object being built
- [ ] **J5** — Finance tab (separate mode/surface)
- [ ] **J6** — Homework help surface

# K. Math, Graphs & Media

- [ ] **K1** — Symbolic math engine — advanced notation, correct solutions (`math_engine.py` exists, extend)
- [ ] **K2** — Recognise math symbols: `sqrt`, `/`, `*`, `+`, `-`, and advanced operators (calculus, etc.)
- [ ] **K3** — Graph reading
- [ ] **K4** — Graph creation
- [ ] **K5** — Image reading
- [ ] **K6** — Video analysis
- [ ] **K7** — File and folder reading (codebases, documents)
- [ ] **K8** — Data understanding and interpretation
- [ ] **K9** — CNN — confirm whether present, add if not

# L. Connectors & System Control

- [ ] **L1** — YouTube integration, reliable
- [ ] **L2** — Browser control
- [ ] **L3** — Google control
- [ ] **L4** — Computer control; open apps on request
- [ ] **L5** — Full system access (opt-in, gated by policy)
- [ ] **L6** — Amazon access
- [ ] **L7** — MCP support (`connectors/mcp.py` exists, verify and extend)
- [ ] **L8** — Obsidian connector
- [ ] **L9** — Messaging systems incl. iMessage
- [ ] **L10** — Stock/market connectors when online
- [ ] **L11** — OmniRoute integration; connect to Shagnik's own AI
- [ ] **L12** — Connectors for "all apps" — enumerate and prioritise
- [ ] **L13** — Finger tracking with air-touch input

# M. Models & Providers

- [ ] **M1** — Additional models beyond the main one, mixed local and online
- [ ] **M2** — Multi-provider routing (9 providers exist in `providers/` — audit and extend)
- [ ] **M3** — Collaboration mode across providers
- [ ] **M4** — Report which API keys are needed → see `KEYS_NEEDED.md`
- [ ] **M5** — Training pipeline and own dataset to stay current
- [ ] **M6** — Fine-tuning support

# N. Platform, Deploy & Ops

- [ ] **N1** — Prepare for web + mobile app deployment
- [ ] **N2** — Vercel deployment for the website
- [ ] **N3** — Vercel add-on so Shagnik can build sites himself
- [ ] **N4** — Automated server provisioning
- [ ] **N5** — Error handling for 24/7 stability
- [ ] **N6** — Self-running / autonomous operation
- [ ] **N7** — Speed optimisation pass

# O. Finance

- [ ] **O1** — Finance mode as its own tab
- [ ] **O2** — Live stock/market data when online
- [ ] **O3** — Financial literacy education content
- [ ] **O4** — Permanent memory for finance context
- [?] **O5** — Buy/sell timing advice.
      *Needs your decision.* Building a tool that issues personalised buy/sell calls is a
      different thing from a tool that teaches and shows data. I will build O1–O4 fully —
      live data, charts, literacy, portfolio tracking, scenario modelling — and surface
      analysis with its reasoning shown. I am not going to ship something that emits
      "sell now" as if it were qualified advice, because it isn't, and presenting it that
      way would be actively harmful to anyone who trusts it. Tell me which framing you
      want and I'll build to it.

# P. Modularity

- [ ] **P1** — Scan a file or take a command and absorb it as a new capability
- [ ] **P2** — Self-sufficient extension — new functions register themselves into the app/webpage
- [ ] **P3** — Dynamic tool registration (`connectors/dynamic_tools.py` exists, extend)

# Q. Study / SAT Content

- [ ] **Q1** — SAT math support
- [ ] **Q2** — "Why randomize x" — clarify and implement
- [ ] **Q3** — Similar triangles
- [ ] **Q4** — Vocabulary practice and memorisation
- [ ] **Q5** — Punctuation improvement
- [ ] **Q6** — Plural vs singular verb agreement — find the odd one out
- [ ] **Q7** — Desmos tricks knowledge base
- [?] **Q8** — "Look at the last TikTok save for Claude Code" / "see all saved TikTok".
      *Blocked — I have no access to your TikTok saves.* Export them or paste the content
      and I'll fold it into Q1–Q7.

# S. App Designer  ← *added session 2*

The equivalent of Claude Artifacts / ChatGPT Canvas / Codex: describe an app, watch it
get built, run it, iterate on it. Must drive the machine, adapt to the hardware it finds,
and stay fast.

- [ ] **S1** — App scaffolding from a natural-language description (pick stack, lay out files, install deps)
- [ ] **S2** — Live preview surface — render the app as it is built, iterate without restarting
- [ ] **S3** — Iterative edit loop: "make the button blue", "add a login page" against the running app
- [ ] **S4** — Multi-file project awareness so edits stay coherent across a real codebase
- [ ] **S5** — Run, test, and debug the generated app autonomously; fix its own build errors
- [ ] **S6** — Hardware-adaptive execution: read `device_profile.py`, scale worker count, model
      size, and preview fidelity to the machine actually present
- [ ] **S7** — Computer control for the build loop — install toolchains, run servers, open browsers
      (`connectors/system_control.py` and `connectors/app_launcher.py` already exist; extend)
- [ ] **S8** — Templates/starters: web app, CLI, API, game, data dashboard
- [ ] **S9** — Export and deploy — local run, or ship to Vercel (ties to N2/N3)
- [ ] **S10** — Speed: incremental rebuilds, warm processes, diff-only edits rather than full rewrites
- [ ] **S11** — Checkpoint each generated app so a bad edit can be rolled back (reuses F2/F3)

**Already in the repo to build on:** `device_profile.py` (tier/hardware detection),
`hardware_safety.py` (thermal/VRAM gating), `connectors/system_control.py`,
`connectors/app_launcher.py`, `folder_reader.py` (multi-file reading), `self_improvement.py`.
S6 and S7 are extensions, not new subsystems.

# T. Auto-Everything  ← *added session 3*

Standing principle: **nothing should require a settings change to work well.** Defaults are
correct for the machine and the task; expert controls exist but are never mandatory.

- [ ] **T1** — Auto mode as the global default across every subsystem
- [ ] **T2** — Auto-detect when the user wants more sub-agents, and spawn them without being asked
- [ ] **T3** — Auto-select model and quality tier from live device specs
- [ ] **T4** — Auto-toggle to fast-response mode when the turn only needs a quick answer
- [ ] **T5** — Auto-escalate out of fast mode into coding/reasoning when complexity demands it
- [ ] **T6** — Auto-compose its own system prompt from the conversation, or take a user-dictated one

# U. Skills System  ← *added session 3*

Claude-style skills: packaged capability the agent loads on demand.

- [x] **U1** — Skill format and loader *(session 4 — `skills.py`; a skill is instructions + triggers, never executed code)*
- [x] **U2** — Create a skill from conversation *(session 4 — `POST /api/skills/from-conversation`; a malformed model reply is refused rather than stored half-formed)*
- [x] **U3** — Auto-attach *(session 4 — wired into `ChatService.chat()`; matched skills attach, unmatched cost nothing, capped at 3 so they do not cancel each other out)*
- [x] **U4** — Bundled library *(session 4 — 6 built-ins: Debugging, Code review, Explaining, Maths, Writing, Research. Disableable but not deletable, so an app update can improve them)*
- [x] **U5** — "Add capability" tab *(session 4 — real library UI with a live preview showing which skills a message would attach)*

# V. Permissions & Machine Control  ← *added session 3*

Full hands-off machine operation by prompt. **This is the highest-risk surface in the product**
and must be built with the gates in `.claude/agents/nyx-platform.md`.

- [x] **V1** — Permission model *(session 4 — `machine_control.py`: explicit, scoped, expiring grants per capability, deny-by-default)*
- [ ] **V2** — Filesystem read/write access
- [ ] **V3** — Desktop/OS control
- [ ] **V4** — Chrome/browser control
- [ ] **V5** — Full-access mode, opt-in, clearly indicated in the UI while active
- [x] **V6** — Audit log *(session 4 — every attempt recorded, allowed or refused; a trail of successes only cannot answer "what did it try to do")*
- [x] **V7** — Confirmation for destructive actions *(session 4 — required even with a standing grant; a grant to write is not consent to delete)*
- [x] **V8** — Kill switch *(session 4 — `revoke_all()` + `POST /api/machine/revoke {all:true}`)*

# W. Fast Response  ← *added session 3, stated top priority*

- [ ] **W1** — Fast-response path: minimal prompt, cheap model, no tool loop for simple turns
- [ ] **W2** — Complexity classifier deciding fast vs full per turn
- [x] **W3** — Auto-toggle, with manual override *(session 4 — `/api/speed` + Settings tab; auto is default)*
- [ ] **W4** — Seamless escalation mid-turn when a "simple" question turns out not to be
- [ ] **W5** — Streaming responses so first token arrives fast even when the full answer is slow
- [ ] **W6** — Latency budget per mode, measured and enforced in tests

# X. Hardware Safety & Quality Tiers  ← *added session 3, stated constant priority*

- [ ] **X1** — Continuous device capability + health monitoring (not just at startup)
- [ ] **X2** — Hard guarantee: never crash, hang, thermally damage, or OOM the host
- [ ] **X3** — Quality tiers derived from device specs
- [ ] **X4** — Explicit warning on low-spec machines, naming what will be slow
- [ ] **X5** — Load shedding under pressure
- [ ] **X6** — Verify the existing detection in `device_profile.py` / `hardware_safety.py` is correct
- [ ] **X7** — Probes must be cheap and cached (session 2 found a 4s probe run twice per turn)

# Y. Training Modes  ← *added session 3*

Two distinct modes, deliberately separate.

- [ ] **Y1** — **Auto-training**: builds memory and its own training data from conversations and searches
- [ ] **Y2** — **Knowledge injection**: user adds information to the AI directly
- [ ] **Y3** — Keep both separate from "what the user wants from the AI" (preferences ≠ knowledge)
- [ ] **Y4** — Per-model training divergence on a shared base, so models improve differently

# Z. Personalities v2  ← *added session 3*

Personalities have **two independent axes**:

- [ ] **Z1** — Axis 1: **output style** (concise, verbose, formal, Gen-Z slang, …)
- [ ] **Z2** — Axis 2: **how the AI functions** (reasoning depth, tool eagerness, autonomy)
- [~] **Z3** — Per-sub-agent personality assignment *(session 4 — agents carry a `personality_id`; not yet applied to their prompts)*
- [ ] **Z4** — The prompt weighs heavily in how it responds
- [ ] **Z5** — User-defined personalities from conversation

# AA. Accounts, Admin & Distribution  ← *added session 3*

- [x] **AA1** — Local account login *(session 4 — `auth.py`, scrypt hashes, 48 tests)*
- [~] **AA2** — Google OAuth login *(account-binding done in `auth.py`; still needs the Google token-verification round trip + a button in `AuthScreen.tsx`)*
- [x] **AA3** — Owner admin account for `shagnikpal@gmail.com` *(session 4)*.
      Built as designed: `python admin_setup.py claim shagnikpal@gmail.com` creates the
      account with **no password**, then prompts for one at a hidden prompt and stores only
      a salted scrypt hash. No credential exists anywhere in the repo. The password shared
      in chat was never used and must not be — treat it as compromised.
- [x] **AA4** — Role/permission system *(session 4 — owner/admin/beta/user, deny-by-default, machine control owner-only)*
- [x] **AA5** — Beta invites *(session 4 — single-use tokens, 14-day expiry, optional email pinning, `admin_setup.py`)*
- [~] **AA6** — Admin developer tooling *(session 4 — API auth layer + admin routes done; the developer UI is not)*
- [x] **AA7** — Admin ability to modify the base AI *(session 4 — owner-only; `target: base_ai` requires MODIFY_BASE_AI, which only OWNER holds)*
- [ ] **AA8** — Per-tab "change mode" for editing each tab in place
- [x] **AA9** — **Admin Changes tab** *(session 4 — `change_review.py` + 7 endpoints + `AdminPanel.tsx`: propose, AI-review, approve, reject, publish, rollback, with a before/after diff. Tab is hidden for non-admins)*
- [x] **AA10** — Publish changes *(session 4 — publish now applies to the overlay and rollback reverts it; if the apply fails the publish is refused so record and reality never disagree)*
- [ ] **AA11** — Prompt existing users to accept an update
- [ ] **AA12** — Users keep local personal mods (personalities, chats, their own tweaks)
- [ ] **AA13** — Version dropdown in downloads, defaulting to newest/best
- [ ] **AA14** — AI Models section: Auto default, expert override, per-model quality modes

# BB. Front End Implementation  ← *added session 3*

Design handoff at `C:\Users\shagn\Downloads\Local AI Agent Platform-handoff\`.
Target `frontend/nyx-pulse` (React + TS + Vite, already scaffolded).

- [x] **BB1** — Tabbed shell: rail (206px) and strip layouts *(built session 4; drag-reorder still to do)*
- [x] **BB2** — Chat tab *(built session 4 — live, wired to /api/chat, shows provider + latency)*
- [x] **BB3** — Dashboard tab *(built session 4 — live hardware/routing/provider health, 5s poll)*
- [x] **BB4** — Sessions & Memory tab
- [x] **BB5** — Models tab
- [x] **BB6** — Agents tab (ties to B4 live progress panel)
- [x] **BB7** — Connectors tab
- [ ] **BB8** — Add capability / store tab (ties to U5)
- [x] **BB9** — Settings tab
- [x] **BB10** — NyxAvatar component *(built session 4 — state-reactive SVG core)*
- [~] **BB11** — Wire panels to FastAPI *(chat + dashboard fully wired; auth/login/join wired session 4; other panels render live JSON)*
- [x] **BB12** — **Deployed and public** at <https://nyx-ichos.vercel.app> *(session 5 — `deploy_mode.py` splits local/hosted; the site is a static landing page carrying no API and no secrets. The long team URL still has Vercel SSO on it; the short alias is the public one.)*

# CC. Dynamic Tabs — AI-Managed Workspace  ← *added session 4*

Tabs stop being a fixed set and become something the agent creates, finds, and edits on
request. The base app ships a starting set; each user's install diverges from it.

**Finding and navigating**

- [~] **CC1** — AI-managed tabs *(session 4 — create, open, edit, combine, delete are all exposed; the agent driving them from a chat turn is not wired)*
- [x] **CC2** — Fuzzy tab search *(session 4 — matches label, description, and block titles across both user and shipped tabs, and reports which words matched)*
- [ ] **CC3** — Voice-driven tab switching (ties to G6)

**Creating**

- [x] **CC4** — "New tab" by request *(session 4 — `POST /api/tabs/from-description`)*
- [x] **CC5** — Purpose-built tabs from a description *(session 4 — stored per user in `tabs.json`, never shipped)*
- [x] **CC6** — An unmatched search offers creation *(session 4 — `offer_create` in the search reply)*
- [x] **CC7** — Per-user tabs persisted locally *(session 4 — separate file; an invalid stored tab is skipped, never fatal to the nav)*

**Editing**

- [x] **CC8** — Side edit tool *(session 4 — a panel on the edge of the tab it edits, with suggestions and a history showing whether each edit was read locally or needed the model)*
- [x] **CC9** — Edit by conversation *(session 4 — `tab_editor.py` + `POST /api/tabs/{id}/edit`. Colour, rename, add/remove block are read locally so they are instant and work offline; anything else goes to the model, whose reply is validated like any other write)*
- [~] **CC10** — Add or remove aspects of a tab *(session 4 — works for user tabs; overriding a shipped tab is not built)*
- [x] **CC11** — Combine two tabs *(session 4 — originals left intact; refuses when the merge would exceed the block limit)*
- [ ] **CC12** — Reset a modified base tab back to its shipped version

**Design notes / open questions**

- A user-created tab is *generated UI*. The safe version is a declarative tab spec
  (layout + which connectors it may call + styling) that the app renders — **not** arbitrary
  generated code executed in the client. Free-form codegen into the running app is an XSS and
  RCE surface, and it would break the base-app update path in AA10–AA11.
- Tab specs are per-user data and must round-trip through the local store, so a base-app
  update never wipes them.
- Overlaps deliberately with **H2/H3** (fast on-the-fly mode creation, and the
  "this already exists — use it, improve it, or make a new one?" prompt). The same
  disambiguation should serve both.

# DD. Strands — the HUD Tab  ← *added session 4*

The flagship tab. A JARVIS-style heads-up display: a live map of how ideas connect, a speech
core that breathes with the voice, and widgets around the edges showing whatever the user
cares about. Reference image supplied by Shagnik (dark teal/cyan HUD, radial centre, panel
grid, log column, waveform, "AWAITING COMMAND").

**The centre**

- [x] **DD1** — **Strands** *(session 4 — `strands.py` + `StrandsPanel.tsx`)*: a live radial graph of connected ideas.
- [x] **DD2** — Built from real state *(session 4 — memory, agent goals, chats; links require ≥2 shared significant terms so unrelated things stay unconnected)*
- [~] **DD3** — Speech core *(session 4 — reacts to live mic amplitude; speaking side needs TTS from G3)*
- [ ] **DD4** — Idle / listening / thinking / speaking states, visually distinct at a glance
- [x] **DD5** — Waveform driven by live audio level *(session 4 — flat and says so when mic is denied)*

**Widgets**

- [x] **DD6** — Widget grid *(session 4 — `widgets.py`, layout persists per user)*
- [~] **DD7** — Widget types *(session 4 — system, agents, events, sources render live data; finance/tab/prompt are declared and addable but their content is not wired)*
- [~] **DD8** — Widgets can be bound to a tab *(session 4 — binding + target validation done; live embedding not built)*
- [~] **DD9** — Widgets bound to a saved prompt *(session 4 — binding done; running saved prompts not built)*
- [x] **DD10** — Widget showing live AI processes *(session 4)*
- [~] **DD11** — Add, remove, rearrange widgets *(session 4 — drag-to-reorder + add/remove/reset; resize not built)*
- [x] **DD12** — Log column streaming **real** system events *(session 4 — `event_log.py`; router latency/failures and safety throttle transitions are recorded)*

**Design notes**

- The reference is a *mockup*: every number in it is fake. Every panel here must show real
  data or say it has none. A HUD that displays invented telemetry is worse than a blank one,
  because it looks authoritative.
- Ties to **B4** (agent progress already live), **X1** (hardware telemetry already live),
  **O1** (finance), **CC** (tab binding).
- Performance matters: this is animated and always-on. It must not cost frames on a weak
  machine — see **X3** tiers. Consider degrading to a static layout on `tiny`/`small`.

# EE. Resource Governor  ← *added session 4*

Give the user direct control over how much of their machine the AI may use.

- [x] **EE1** — Power modes *(session 4 — `resource_governor.py`, `/api/power`)*: **low / medium / high / max / auto**
- [x] **EE2** — **Auto (machine)** *(session 4)* — derive the ceiling from detected hardware
- [x] **EE3** — **Auto (task)** *(session 4 — `auto_task` mode; simple turns take 1 worker, complex take more)*
- [ ] **EE4** — Explicit RAM ceiling
- [x] **EE5** — Explicit CPU / worker-count ceiling *(session 4)*
- [ ] **EE6** — GPU / power-draw ceiling
- [~] **EE7** — Its own tab *(session 4 — Power tab shows the ceiling and every mode's effect on this machine; live usage plot still to add)*
- [~] **EE8** — Enforcement, not advice *(session 4 — `AgentPool` now obeys the ceiling; model size and inference concurrency still to wire)*
- [x] **EE9** — Warn before a mode is chosen that this machine cannot sustain *(session 4 — `can_sustain()` per mode)*

*Depends on `device_profile.py` and `hardware_safety.py`, both already live. The safety floor
in **X2** always wins: a user may not select a mode that would damage or hang the machine.*

# FF. Voice v2  ← *added session 4*

Extends section G with what Shagnik asked for on the HUD.

- [ ] **FF1** — Installable voice packages
- [ ] **FF2** — **Create a voice by hearing it** — capture a sample and synthesise from it
- [ ] **FF3** — Voice recognition as access control: only the owner, plus one or two approved
      people, can drive the system by voice
- [ ] **FF4** — Per-speaker identification, so the agent knows which approved person is talking
- [ ] **FF5** — Voice auth binds to the account/permission model in **AA4** / **V1**

**Serious notes before building FF2 and FF3**

- **Voice cloning is consent-gated.** FF2 must only capture a voice from someone present and
  agreeing. Do not build a path that clones a voice from an arbitrary recording — that is the
  difference between a feature and an impersonation tool.
- **Voice alone is not a strong credential.** Recordings and synthesis defeat it, and the
  agent will hold machine-control permission. FF3 should gate *convenience* actions on voice,
  and keep anything destructive, financial, or permission-changing behind the real session
  from **AA1–AA4**. Ask Shagnik before wiring voice to anything privileged.

# R. Declined / Needs Reframing

- [!] **R1** — "Make a skill to not pay for pay-for-use, table 5, apply to Opus."
      **Declined.** I'm not going to build something to avoid paying for metered API usage —
      that's circumventing billing for a service. Everything else here is unaffected, and the
      free-to-run goal is well served legitimately: Ollama local models cost nothing, and the
      routing layer already prefers local. If I misread this and you meant something else
      (a rate-limit backoff, a cost dashboard, a local-first routing policy), say so and I'll
      build it.
- [?] **R2** — "/radio for Claude" — unclear. Clarify what this should do.
- [?] **R3** — "Look at GPT for what I wanted" — no access to your ChatGPT history. Paste it here.
- [?] **R4** — `.freebuff` — undocumented file in repo root. What is it?

---

## Cross-cutting rules for every increment

1. Suite must be green before an item is marked `[x]`.
2. Every online feature needs an offline path.
3. No secrets in code — `.env.local` via `config.py` / `secret_store.py`.
4. Agent self-modification is additive-only, into the overlay area, checkpointed.
5. New dependency ⇒ line in `requirements.txt` with a comment naming the consumer.
