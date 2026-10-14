# What is actually left

One list of everything still to do, from three sources, checked against the code on `main` and not just the plans.

- **Checked at:** `main` = `14fac4c` (2026-10-14 02:46 UTC).
- **Sources:**
  1. The **"Fixer uper"** Drive doc (41 pages). Triage: `docs/FIXER_UPPER_PLAN.md` (sections S1 to S39, teams WS1 to WS15).
  2. Drive document **"1"** (items 1.1 to 1.30). Last edited in Drive 2026-10-13 23:55 UTC; nothing newer, and no document "2" yet.
  3. The **updates file**: `docs/CHANGELOG.md`, the code-named change log made by `changelog_gen.py`. Regenerated in
     the same push as this file, so it lists every update up to `14fac4c`.
- **Status key:** **Done** = in the code on main. **Partial** = a real base exists, more is asked for.
  **Not started** = nothing in the code. **Needs PC** = done in code but only his Windows PC can prove it.
- **Evidence** is a commit (short hash) or `file:line` on main.
- **Team state** (2026-10-14 02:47 UTC): **Active** = working now. **Paused** = waits until the coordinator restarts it.
  **Finished** = its slice is done.

## Teams at a glance

| Team | State | Done | Partial | Not started | Biggest thing left |
|---|---|---|---|---|---|
| WS4 Act instead of refusing | Active | 3 | 4 | 5 | Persona modes, file helper, "digging", remove Free Will |
| WS6 Voice and Equalize | Active | 3 (Needs PC) | 3 | 4 | Proof on his PC; avatar choice; faster voice |
| WS2 Projects and Commander | Active | 1 | 4 | 10 | Threads, delegator chat, Waiting on you panel (in progress, nothing pushed yet) |
| WS10 Normal chat | Active (2 handoffs only) | 1 | 6 | 10 | Chat-name menu and Hide empty chats (in progress), then court, offices panel, header |
| WS13 Skills, plugins, Obsidian | Active (PC installs) | 4 | 2 | 2 | Installs on his PC; Instagram reels pass |
| WS7 Notch, sidebar, hands-off | Active | 0 | 3 | 6 | White box check, notch controls, p38 sidebar, hands-off mode |
| WS1 Trading app | Paused (next in line) | 1 | 11 | 14 | The app itself in `apps/ichos-trader/` |
| WS5 Speed and model lineup | Paused | 0 | 5 | 8 | Lineup names, picker, effort slider, speed numbers |
| WS8 Avatars and bot teams | Paused | 0 | 2 | 5 | Three avatar-tab bugs, hierarchy, settings sections |
| WS9 Phone, WhatsApp, notifications | Paused | 2 | 3 | 7 | Files over WhatsApp, notifications, any chat on WhatsApp |
| WS3 Ichos lightweight app | Paused | 0 | 1 | 1 (the whole app) | Everything; `apps/ichos/` does not exist yet |
| WS12 Design, brand, motion | Paused | 0 | 4 | 6 | Icon, mascot, glass look; transitions last |
| WS14 Desktop app and VS Code | Paused (first pass finished) | 2 | 2 | 3 | Console windows popping up (1.18), browser extension |
| WS15 Autonomy layer | Paused (runs last) | 0 | 4 | 4 | Self-approve switch, rules and laws, emotions, Slack huddle |
| WS19 Engine parity | Paused | 1 | 2 | 6 | Tool search, context editing, token counting |
| WS11 UI fixes | Finished | 15 | 1 | 2 | Settings sections like Claude's (1.22), "where it works" panel |
| WS16 Google, Gmail, email | Finished | 5 | 1 | 3 | His Google Cloud step; mail watcher; Drive picker |
| WS17 Update log | Finished | 1 | 1 | 0 | A copy in the Drive folder |
| WS18 Review and beta test | Paused | 2 | 0 | 1 | Final pass before the full push; 4 open findings |

Counts are rows in the tables below. Several asks sit with two teams; each row is listed once, under its main owner.

---

## WS4 — Act instead of refusing (Active)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| "Take me to Finances" and opening tabs by any name | S39, focus | **Done** | `14fac4c` (`landscape_tools.py:33-60`, `tool_ui_open_tab` at `:165`), with tests |
| Normal mode uses the mouse and keyboard instead of refusing | S26, focus | **Done, Needs PC** | `36d2361` (follow-ups get tools, refusals escalate), `e449e36` (a turn that gives up is asked once to act), `ab80a0a` (standing instruction says act, how to type into an app). Reproduce the Google Docs "type hi" transcript on his PC with qwen3.5:9b |
| AI knows it can send email and text him | 1.7 | **Done** | `18ca837` (Gmail via Google sign-in sends), `272f170` (WhatsApp can read mail and email him). Plan mode still blocks sending on purpose |
| Find a missing skill or connector (GitHub, web), add it, then do the task | S39 | **Partial** | Skill import from GitHub exists (`skill_import.py`, `0bb7602`) and the catalog (`skill_catalog.py`, `18b2345`); nothing makes a turn search for and install one on its own |
| The AI may use the design studio itself | S39 | **Partial** | `design_studio.py` exists; no chat tool that drives it end to end was found |
| Beta computer share (knows open apps and tabs, links bots to chats) | S8 | **Partial** | Screen Share window (`b93a010`); no list of open windows given to the AI |
| "Where it works" panel like p10 (Auto, cloud computer, VM, this PC, browser) | S21, p10 | **Partial** | Only the own-computer panel (`panels/computer/OwnComputerPanel.tsx`). WS11 left it to this team |
| Remove Free Will mode, move the third mind to the main info tab | S39 | **Not started** | Still a section: `tabs.ts:28`, `:138`, `:153`; the third mind is in `curiosity.py` |
| Persona modes (web and app dev, finance, coder, worker, student, general) with preloaded skills, plus Auto that picks one | S8 | **Not started** | `chat_modes.py` has only turn modes (normal, cowork, plan, swarm, auto, ultrafast) |
| Background "file helper" | S8 | **Not started** | Nothing in the code |
| "Digging" setting (search outside the usual folders and Drive, by voice too) | 1.20 | **Not started** | File reading stays inside granted folders (`folder_reader.py`, `file_guard.py`). Default: off until he turns it on |
| Screen awareness across tabs | 1.30 | **Not started** | Nothing in the code |

## WS6 — Voice and the Equalize assistant (Active)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Intro said twice, then no answer | S34, 1.5, focus | **Done, Needs PC** | `ebfe572` (intro once per start), `4a1c6d7` ("listening started" once per session). He asked for a yes/no after a real test |
| No response when speaking off the Chat tab | focus | **Done, Needs PC** | `d21d91c` (the chat opens and takes the words) |
| Every answer doubled | S33, focus | **Done, Needs PC** | `f3616df` (the speak tool stays quiet on voice turns) |
| Choose which avatar Equalize uses | S34 | **Partial** | Settings hold an avatar and personality (`equalize_assistant.py:60-61`); check there is a picker he can use |
| Thinking too long, repeats itself, slow voice tests | S33 | **Partial** | Fixes for repeats above; no timing numbers yet (WS5 adds the timing) |
| Rounder, spherical thinking look | S33 | **Partial** | `VoiceFace.tsx` and `BrainField.tsx` exist; no new spherical design pushed |
| Jev speed without the Jev key, also in the assistant | 1.4 | **Not started** | Ultra Fast runs locally (`ultrafast.py:10-11`) but is not measured against Jev and not wired into Equalize |
| Voice to action: a taught sound + phrase runs a command instantly | S6 | **Not started** | Both halves exist (`voice_gestures.py`, `ultrafast.py`); not joined |
| Study kaymen99/AI-Voice-assistant, vannu07/jarvis, VoxCPM; adopt what is faster | S2, S15 | **Not started** | No reference in code; VoxCPM is listed for evaluation in the plugins list |
| Face recognition | S2 | **Not started** | Marked "later" by him |

## WS2 — Projects and Commander command center (Active)

Working now on threads + delegator chat + Waiting on you / Idle / Resolved + two-way relay + "Tasks done/total". **Nothing
from this team is on main yet** (no branch on GitHub at 02:47 UTC).

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Mission Control auto-picks model and effort | S13 | **Done** | Haiku router in the `mission-control` repo (`hooks/route.ts`) |
| A project has its own folder and shows links to chats, splits, sectors (like p16) | S19, S9 | **Partial** | `projects.py` has sectors, helpers, artifacts (`f033e45`); no folder on disk, no chats linked |
| Auto-assign tasks to models, learning from past assignments | S9 | **Partial** | `model_autoassign.py` per fixed job only |
| Track each thread's tokens and context; brief a fresh thread | S13 | **Partial** | `context_budget.py` measure and compact; no fresh-chat hand-off |
| Mission Control side panel instead of the band | S13 | **Partial** | Side layout exists, band is still the default |
| Threads ("divisions") with a right panel: Waiting on you / Idle / Resolved (p27) | S9, focus | **Not started on main** | In progress in the team's thread |
| The main chat is the delegator; two-way relay | S9, focus | **Not started on main** | In progress. The old Command Zone hand-off (`command_zone.py:62-75`) is the base |
| "Tasks done/total" in the Projects side panel | his ask 01:33 UTC | **Not started on main** | In progress |
| Running chats as pills with a coloured dot and a live one-line status (image 01-d) | 1.17 | **Not started** | |
| "Needs you" icon on chats and a short-named waiting section | 1.19 | **Not started** | |
| Commander mode beside the other modes, chats split on the right, movable into Projects | S13 | **Not started** | Mode list has no Commander (`chat_modes.py`) |
| Divisions in normal chat, switched on in Settings | S9 | **Not started** | |
| Mission Control lists every chat; one prompt fans out to other chats | S13 | **Not started** | |
| Projects like Claude's: per-project knowledge base (RAG), instructions, starring, sharing, Library | 1.28 | **Not started** | |
| Agents by role with progress (research, plan, build, test, review); auto-created artifacts | 1.30, 1.26 | **Not started** | Quasars (artifacts) exist (`6c3549d`) but are not made on their own |

## WS10 — Normal chat as the one place (Active for two handoffs only)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Court lives in normal chat (no separate tab) | S16 | **Done** | `b93a010`, `court_case` tool (`court.py:289`) |
| Delete or rename from the three dots by the chat name | S25 | **Partial** | `ChatTitleMenu.tsx` built (`6f5524f`) but not mounted: `ChatPanel.tsx` has no reference. In progress |
| "Hide empty chats" filter in the chat list | S25 | **Not started on main** | Nothing in `ChatRail.tsx`. In progress |
| Normal, coding and office/world in one chat | S16 | **Partial** | Offices and worlds made from chat (`c108df7`) and open as windows |
| Office scales up to a world | S16 | **Partial** | `POST /api/world/upscale`; no suggestion when an office gets big |
| Coding agent in normal chat, where you can watch the edits | S29 | **Partial** | `write_file`, `run_command` in chat (`machine_tools.py`); no live view |
| Constellations and Quasars inside normal chat | 1.14 | **Partial** | Combined into one tab (`ce8b28c`); not inside the chat yet. Compacting is Done (`routes_context.py:73-87`) |
| Court opens by itself when the AI struggles | S16 | **Not started** | Only the tool and `routes_court.py:24` call `court.start` |
| Offer to move a hard question to an office that carries the chat | S16 | **Not started** | |
| Right panel of running offices and worlds with progress | S16 | **Not started** | |
| Live editing panel with tabs; highlight to prompt | S18 | **Not started** | Only a read-only file window |
| Personal-assistant layout from the FlowAI images (p5-6) | S29 | **Not started** | |
| Useful header modules instead of brain waves; usage graph and "what is working" | S29, 1.16 | **Not started** | `StudioHeader.tsx:104-124` still shows memories / brain pulse |
| Thinking phrases like Claude's and new-chat greetings | 1.15 | **Not started** | No phrase list in the code |
| Badges on chats (WhatsApp, connectors) | 1.8 | **Not started** | |
| Answer boxes: approve/deny, checkboxes, multi-select, graphs, image drop | 1.19 | **Partial** | Question cards with a free-text box exist (`question_cards.py`) |
| Slash commands `/context`, `/rewind`, `/goal` | 1.29 | **Not started** | `/compact` exists (`commands.py:79`); the engine side is WS19 |

## WS13 — Skills, plugins and Obsidian (Active: PC installs and doc scrub)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Add the skills from his GitHub links | S39 (first) | **Done** | Curated catalog with a safe installer (`18b2345`, `609c02f`) |
| Transitions and Claude Code guide skills from doc 1 | 1.2 | **Done** | `4fffbe6` |
| Obsidian as a shared brain for Claude and both apps | S19 | **Done in code, Needs PC** | `4a42e1e`, `d7ead1d`. Still to do on his PC: the Local REST API plugin and the `.env.local` settings |
| Instagram saved reels into draft skills | S18 | **Partial** | Code ready (`9d21071`); the pass needs his signed-in browser |
| Install on his PC: skill packs, `claude-mem`, `claude-code-setup`, `everything-claude-code`, Agent-Reach | S15 | **Not started** | In progress through the PC (list in the project's `fixer-upper/plugins-to-install.md`). `strix-claude-code` only if he says yes |
| Advanced sort across files, cloud, email and docs using the brain | 1.21 | **Not started** | Brain format exists; no sorter |
| One directory for skills, connectors and plugins | 1.28 | **Partial** | Connectors catalog and skill catalog are separate pages |
| Doc scrub of personal paths and emails | review | **Done (mostly)** | `689fed5`, `79a47f1`; the team is finishing the last pass |

## WS7 — Notch, sidebar and hands-off mode (Active)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| White box behind the notch | S34, 1.11 | **Partial, Needs PC** | `1243cb7` made the window transparent and sized to the island; he still mentions it, so check on his PC |
| Make the notch look unique (images from the first doc) | 1.11 | **Partial** | Coucou-style notch exists (`5f0617b`) |
| Wake by a recorded sound + phrase; notch expands while listening | S2 | **Partial** | The wake phrase is saved (`equalize_assistant.py`) but nothing listens for it |
| Notch controls: system, search, sound, OS light/dark, launch apps, File Explorer, cmd with a preset prompt | S30 | **Not started** | No such controls in `notch.py` / `routes_notch.py` |
| Default view (apps, music, weather, calendar, videos) and switching it by triple click or an H button | S30 | **Not started** | |
| Import notch looks | S30 | **Not started** | |
| Sidebar like p38, merged with the assistant as a hands-off mode | S2 | **Not started** | |
| Sidebar and notch draggable and lockable | S2 | **Not started** | |
| Agents' approvals and questions pop the notch open | handoff, 1.19 | **Not started** | |

## WS1 — Trading as its own app (Paused, next in the replacement order)

Decision already made: it stays in `apps/ichos-trader/` and is pushed once a first tested pass is ready. Today that
folder holds only the status check and the leak sweep (`165282d`, `24e44a1`). Full item list with evidence:
the project's `fixer-upper/ws1/status-check.md` (26 items, checked at `93dc0be`; nothing trader-related changed since
except `3aa8b82`).

| Item | Status | Evidence / what is left |
|---|---|---|
| Run 24/7 | **Done** | `trading/autopilot.py:39`, `ensure_running` |
| Dashboard; hundreds of markets; best strategies; big team; background agents shown; learn first with fake money; fully auto by default; tuning dials and graphs; best free models; stay-on; connect the right brokers; follows the colours | **Partial** (11) | Pieces on separate cards in the old Trading tab (`trading/`, `finance_lab/`, `panels/trading/`) |
| The split itself; README link "the trader moved here"; ranking by liquidity, spread, depth and order flow; Bitcoin/Ethereum rotation; any market and currency; auto shut-down when slow or losing; named bot roles (manager, advisor, skeptic); adds bots by itself; speed tests and a target for "fast"; cloud login with Google or GitHub; Claude connector on request; profit pays the subscription; redesign | **Not started** (14) | Real money, a hosted copy and its own repo wait for his word |

## WS5 — Speed, model lineup and machine learning (Paused)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Measure speed (UI, WhatsApp, voice) and publish numbers | S39 | **Partial** | Quick paths exist (`fast_response.py`, `ultrafast.py`, `mini_model.py`); only a total time per turn (`turn_runner.py`). Real numbers need his GPU |
| Super-light model that sizes itself, with speed tests | S5 | **Partial** | `local_models.fits()` checks memory; nothing picks or tests |
| Live usage against the limit (EE7) | S36 | **Partial** | Power tab shows the ceiling only |
| Model size and inference concurrency obey the power mode (EE8) | S36 | **Partial** | Agents obey it; `providers/ollama_provider.py` does not; the mode is forgotten on restart |
| More machine learning, and say it is ML + AI | S39 | **Partial** | Real ML runs (`learning.py`, `predictor.py`); the README never says ML |
| Speed skill or restructure | S39 | **Not started** | |
| Named lineup: Pico, Monolith (Argon to Xenon, decided), Crescendo, coding Bit to Exa, Zencode | S14 | **Not started** | No lineup names in code |
| Picker that expands from the main model; model select next to effort | S14, S13 | **Not started** | Plain dropdown (`ProviderPicker.tsx`) |
| Effort slider glowing through the spectrum; seven tiers ending in Aleph | S14, S5 | **Not started** | No effort control in the frontend |
| Drop "Nyx absorbed" | S14 | **Not started** | Still offered: `absorb_engine.py:1256` |
| Storage tab is slow | S36 | **Not started** | Still lists `.venv` and `node_modules` (`storage_budget.py:179-180`) |
| RAM ceiling (EE4) and GPU / power ceiling (EE6) | S36 | **Not started** | |
| `device_profile.json` through `paths.py` | review #4 | **Not started** | `device_profile.py:14` still uses `Path(__file__).with_name` |

## WS8 — Avatars and bot teams (Paused)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Avatars with functions, goals, schedules, personalities | S20 | **Partial** | `590fc5d`, `c6fa34c`, `f851a17` |
| Avatar tasks: a time for daily, a weekday for weekly, "predict when asked" | S37 | **Partial** | Check-in schedules have days and hours (`avatars.py:768`); task repeats are only `daily`/`weekly` with no time (`avatars.py:93`) |
| Drag avatars onto tabs | S23 | **Done by WS11** | `ee1d0c4` (listed here for completeness, not counted) |
| Avatars tab bugs: scroll jumps up, list drifted right, Save never changes | S22 | **Not started** | Open bugs, nothing in git |
| Per-avatar settings sections like p11 (Identity, Soul, Skills, Memory, Routines, Access, Model…) | S20 | **Not started** | |
| Hierarchy (master, co-leader, hiring bot), avatar-to-avatar messages, "consult with team", teams without an office | S20 | **Not started** | No roles in `avatars.py` |
| Avatars tab higher; avatars dropdown in normal chat | S20, S22 | **Not started** | |
| Learn-by-demonstration routines | 1.30 | **Not started** | |

## WS9 — Phone, WhatsApp and notifications (Paused)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Gmail from WhatsApp | S35 | **Done** | `272f170` |
| WhatsApp shorter replies for the phone | S31 | **Done** | `PHONE_NOTE` in `whatsapp_link.py` |
| WhatsApp "a bit better", auto-set models | S31 | **Partial** | Uses the chat's model; `model_autoassign.py` is WS5's |
| Text him when the AI is away / a job finishes | S31 | **Partial** | Office jobs only (`a54435f`) |
| Away mode: approvals go out by WhatsApp or email, his reply counts | 1.24 | **Partial** | Away detection exists (`presence.py`); nothing routes approvals out |
| Avatar per line; pick or create an avatar from the general line | S35 | **Not started** | One chat per line in `whatsapp_link.py` |
| Send and receive files and images on WhatsApp | S31 | **Not started** | `whatsapp_worker/worker.py` reads text only |
| Notifications when a chat finishes, needs help or texts | S31 | **Not started** | Toasts only for `notify` events |
| Choose where notifications appear | S31 | **Not started** | Hard-coded `bottom: 16, right: 16` (`components/chat/Toasts.tsx:26`) |
| Any chat can link to WhatsApp; `/chats` to list and continue | 1.8 | **Not started** | Commands are `/new /status /pause /help` |
| Claude-style remote connection from the phone; 1-minute pairing key | S38, S5 | **Not started** | Only the WhatsApp device pairing exists |
| A phone number per AI / avatar | S31 | **Not started, needs his decision** | Each number is a separate WhatsApp account and costs money |

## WS3 — Ichos, the lightweight app (Paused)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Reusable pieces (Auto mode, Projects, Ultra Fast, homework helper, GitHub and Vercel connectors) | S5 | **Partial** | Listed in the plan; all in the main app |
| The app: Claude/Codex look (p31), phone layout, 2-click Google/Microsoft connect, settings, student mode, effort tiers, fast light model, semi-notch, code stats, accounts, phone pairing, voice screen (p32), sliding model-change animation | S5 | **Not started** | `apps/ichos/` does not exist (only `apps/ichos-trader/`) |

## WS12 — Design system, brand and motion (Paused)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Glass as a design option | S17 | **Partial** | "Studio Glass" exists (`8979f6a`); the dark frosted CRM look (p19-21) is not added |
| Move "copy site look" into the Design tab | S7 | **Partial** | Design Research tab (`db611a0`), screenshot to code (`3ec5258`) |
| OpenMausBot looks as selectable styles | S24 | **Partial** | Ideas only (`docs/AVATARS.md`) |
| Transitions like Claude's (last, by his word) | 1.2, S18, S31 | **Partial** | Lenis, GSAP settle (`e039854`); skills added (`4fffbe6`) |
| New main icon (asymmetric, one colour, gradient) | S1, S3 | **Not started** | |
| Multi-armed pixel mascot, arms show tasks, animated around the chat bar | S1, S3 | **Not started** | |
| Figma-style board of every page | S10 | **Not started** | |
| Design tab for websites that recognises a design | S10 | **Not started** | |
| Colour palettes and transitions from the Instagram reel | S18 | **Not started** | |
| Design-system setup like Claude Design | 1.28 | **Not started** | |

## WS14 — Desktop app and VS Code (Paused, first pass finished)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Opens as an app by default, browser optional | S19, S39 | **Done, Needs PC** | `4f1fc17` (own window on WebView2), `6f76836` (launcher, crash restart) |
| Anti-crash and stay-on | S39 | **Done** | `6f76836` (max 3 restarts in 10 min) |
| Command prompt windows pop up again | 1.18 | **Partial** | Only the trader's sweep got the no-window flag (`3aa8b82`); find the new culprit on his PC |
| VS Code extension; watch it code | S28 | **Partial** | `extensions/vscode-nyx` v0.1 (later priority) |
| Same app shell for Ichos | S19 | **Not started** | Waits on WS3 |
| Harness tests for coding | S28 | **Not started** | |
| Browser extension: an avatar in Gmail and other Google apps to click or drop an email on | 1.10 | **Not started** | Only `extensions/vscode-nyx` exists |

## WS15 — Autonomy layer (Paused, runs last)

His decision: **self-approval is allowed** when the AI judges a change worthy, with a switch and a log, and AGENTS.md
invariants 2 and 4 get updated to say so. That update has **not** been made yet.

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Self-improve section (rewrite and self-approve) | S12, 1.23 | **Partial** | `improvement_engine.py`, `self_patch.py`, `improve_autopilot.py`; `change_review.py` still needs a human approver (`:277`). Add the switch, the log and the AGENTS.md change |
| Flexibility mod: self mods, new abilities (e.g. Bluetooth); users change base features | S12, 1.26 | **Partial** | `mods.py` (`61b729f`) |
| Admin login: push features, schedule auto-approve and auto-improve | 1.25 | **Partial** | `admin_server.py`; Collab and Admin marked WIP (`aa2ae5e`) |
| Improve tab moves into normal and code chat; a loading state that says what it is doing | 1.23 | **Partial** | The Improve tab exists |
| Rules and laws (numbered, nested, user-made, slider for how much the AI may add) | S12 | **Not started** | |
| Emotions panel with a neutral helper AI | S11 | **Not started** | The third mind's wants (`curiosity.py`) is the base |
| Slack team huddle (named bots running a business), very last | S12 | **Not started** | A Slack connector exists in the catalog |
| AGENTS.md invariants 2 and 4 rewritten for self-approval | decision | **Not started** | `AGENTS.md` §4 still says no self-approval |

## WS19 — Engine parity with Claude's platform (Paused)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| 1M context, compaction, `/compact` with undo, skills on demand, computer use | 1.27 | **Done** | `0e8e312`, `routes_context.py:73-87`, `skill_packs.py`, `computer_control.py` |
| Advisor pairing (fast model + stronger advisor in one turn) | 1.27 | **Partial** | `consult.py` advisors, not inside a turn |
| Citations everywhere; structured outputs through Ollama | 1.27 | **Partial** | Research has citations |
| Tool search tool (don't send all tools every turn) | 1.27 | **Not started** | Suggested first |
| Context editing (clear old tool results) | 1.27 | **Not started** | Suggested first |
| Token counting | 1.27 | **Not started** | Suggested first |
| Prompt caching for Ollama (`keep_alive`, KV reuse) | 1.27 | **Not started** | |
| `/rewind` with checkpoints for chat turns | 1.29 | **Not started** | |
| `/goal` loop and user-defined hooks | 1.29 | **Not started** | |

## WS11 — UI fixes, drag and drop, loading (Finished)

Done and on main: tab position in every look (`1381076`), Code / Learn / Research Lab follow the theme (`2aa9d4c`,
`88ef33c`, `f0c455c`), accent survives reload (`8c18227`), desktop colour sync (`20db9fc`, `8ba281c`, Needs PC),
agents 0/0 fixed (`340b49a`, Needs PC), drag to reorder tabs (`f6cbc41`), drag chats, avatars and the assistant onto
tabs (`ee1d0c4`, `9a7b402`), reset tab order (`f5f6d05`), calendar like p9 the AI can restyle (`3642b7c`, `e16424b`),
pasted images show as images (`dda7dcd`), delete from the left panel, auto clean-up of old chats (`fe95785`,
`dc314b0`), big loaders everywhere (`62f30b3`, `ebf1eb7`), rounded pill tabs (`a648436`), 19 tabs down to 12
(`ce8b28c`).

| Left | Source | Status | Evidence / what is left |
|---|---|---|---|
| Settings sections like Claude's (Model capabilities, Tools, Tool infrastructure, Context management, Files) | 1.22, 1.12 | **Not started** | Only "Old chats" was added to Settings |
| Loading widgets in Trading, Free Will and Equalize panels | S27 | **Partial** | Left to those teams |
| "Where it works" panel (p10) | S21 | **Not started** | Moved to WS4 (listed there) |

## WS16 — Google, Gmail and email helpers (Finished)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Gmail signed in through Google can send and reply | S35, 1.7 | **Done** | `18ca837` |
| Google sign-in `redirect_uri_mismatch`: clear help, client JSON, copy button, error wording | 1.3, S23 | **Done in code; his step left** | `5bed727`, `89064e8`, `4a0bcd6`. He still has to add the redirect address in Google Cloud, or make a Desktop app client |
| Connect all Google apps in one sign-in | — | **Done** | `1b5ccac`, `e22a5cf` (PR #6) |
| Email helpers: sort new mail, sender rules, a draft queue, nothing sent without his yes | 1.9 | **Done** | `96ef15e`, `831cbeb`, `d7406d0`. Auto-send is a setting, off by default (his decision) |
| Paste a Docs, Sheets or Drive link in chat and it is read | 1.1 | **Done** | `5aa125a`, `4a26d7a` |
| Drive picker button in the composer; "add a Drive folder as context" | 1.1 | **Not started** | Composer is WS10's |
| A watcher that reads each new email as it arrives | 1.9 | **Not started** | `check_new` exists, nothing runs it on a schedule |
| Calendar-aware replies; opening safe links; summary by text or email | 1.9 | **Not started** | Draft-and-ask stays the rule |
| Gmail auto-reply on arrival | 1.9 | **Partial** | The switch exists (`send_without_asking`, off); nothing replies on arrival yet |

## WS17 — The updates file (Finished)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| Code-named, numbered log of every update with a pushed tick | 1.6 | **Done** | `changelog_gen.py` (`373c063`), `docs/CHANGELOG.md`, regenerated with this file |
| The same log as a document in the AI Dev Drive folder | 1.6 | **Partial** | Only in the repo. He asked for it in the Drive folder |

## WS18 — Review and beta testing (Paused)

| Item | Source | Status | Evidence / what is left |
|---|---|---|---|
| First review pass | 1.13 | **Done** | PR #2 and PR #5 merged (`e0847e5`, `244cdf7`) |
| Tests no longer write into his data folder | review | **Done** | `d116c91`, `82698e2` |
| Final pass before the "full push", plus the beta checklist on his PC | 1.13 | **Not started** | Checklist: the project's `fixer-upper/review/beta-checklist.md` |

Open findings from the review (`fixer-upper/review/findings.md`), still true on main:

1. `tests/test_design_sense.py` reads the gitignored `AI_HANDOFF/01_GOALS.md`, so it fails on every clean clone (no skip yet). Owner: WS12.
2. His email is still in old git history. Recommendation: leave history alone. His call.
3. `AGENTS.md` counts are stale (says ~685 tests in 68 files; main has far more). Low priority.
4. `device_profile.json` is written next to the code, not through `paths.py` (`device_profile.py:14`). Owner: WS5.

---

## What only Shagnik can do

1. **Google Cloud:** add `http://127.0.0.1:8000/api/google/oauth/callback` to his Web client, or make a Desktop app
   client and paste its JSON in the Google panel (1.3).
2. **Test on his PC** (each is done in code): intro said once, answers not doubled, voice off the Chat tab (WS6);
   Normal mode typing into Google Docs (WS4); the notch's white box (WS7); console windows popping up (1.18); desktop
   colour sync; the app window.
3. **Allow the PC installs** for the Skills team: skill packs, Claude Code plugins, Obsidian's Local REST API plugin.
   `strix-claude-code` needs a separate yes.
4. **Decisions still open:** real-money trading and a hosted trader; a phone number per avatar (costs money); which
   folders "digging" may search (default: off, then his user folders only).

## How to keep this file current

Rerun the check when a team merges: search the item's file or `git log`, then change its row. Regenerate the updates
file with `python changelog_gen.py`. A new Drive document ("2", "3", …) adds a new section under its own heading.
