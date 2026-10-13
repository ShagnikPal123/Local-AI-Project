> Copied from the project's shared plan. The reference images it names (`images/p..-*.png`) and the
> source document are in the Claude project's shared files under `fixer-upper/`, not in this repo, because they
> hold personal screenshots.

# Fixer Upper — triage and split

Source: Shagnik's "Fixer uper" document (41 pages, 23 images), 2026-10-13.
Copies in this folder: `Fixer_uper.pdf`, `Fixer_uper.txt` (plain text; line numbers below are `Lnnn` in that file),
and every image in `images/`, named by the page it sits on.

Main repo: `ShagnikPal123/Local-AI-Project` (Nyx Ichos: Python FastAPI backend + React/Vite frontend in
`frontend/nyx-pulse/`). Checked at `102d659` (2026-10-13); notch commits up to `50d49be` landed during the check and are noted under S34. Read `AGENTS.md` there before touching code.
Second repo: `ShagnikPal123/mission-control` (the Claude Code mod with the band above the chat box), checked at `5637094`.

---

## How the document was read

- **Page 1, first paragraph (L1–21)** is the cover note: what the document is for and how to split it.
- **Page 1, second paragraph (L23–57)** is the newest writing and the statement of purpose ("Integrity": the AI tries,
  finds or builds what it lacks, never just says no; plus the newest bugs).
- **Everything below it was written bottom to top.** Page 41 (the mascot) is the oldest note and the paragraphs get
  newer going up. Shagnik said to read bottom-up and work top-down, so: the section index below is listed oldest
  first, and the **start order** at the end follows his stated priorities, newest asks first.
- His own explicit priorities, which override the reading order:
  - **First:** "add all skills from the GitHubs I have added and then begin work" (L26). That is workstream 13 and
    it goes before the rest.
  - **Last four, in order** (L647–673): self-improve (4th last), flexibility mod (3rd last), rules & laws (2nd last),
    Slack team huddle (very last).
  - **Transitions after everything else** (L149–153). **VS Code extension later** (L182).
- **The two splits:**
  1. **New project folder = the Projects / command-center feature.** He chose Claude because of its new Projects
     features (images p16 and p27 are this very Projects screen). His words: "creating a new project has its
     folder/file, and it shows its connections to chats, splits, sectors" (L462) and "the main chat we type in is the
     delegator and sends to the different threads" (L692). That is workstream 2 and it is the headline item.
  2. **Trading tab → standalone app** in its own repo, linked from the main README (L93–137). Workstream 1.
  - A possible third: the lightweight **Ichos** app (L732–814, "a separate app"). Proposed as a new folder inside the
    main repo so it shares the engine; see workstream 3.
- **Images without a description are style ideas**, not specs: copy what makes them look good without replacing the
  current design unless he asks (L51–53).

---

## Rules every team follows

1. **Check before building.** For every item in your slice, search the code and `git log` first. Many items are
   partly or fully done (see the status column). Mark each one Done / Partial / Not started in your first reply,
   with the commit or `file:line` as evidence. Do not rebuild something that works.
2. **Push after each change, many small commits** (he asked for this explicitly). Before every push:
   `git fetch origin main && git rebase origin/main`. Several teams share `main`, so keep commits small and rebase
   often. Files that more than one team touches are listed under "Shared files" below; the named owner edits them,
   others send changes through the coordinator.
3. **The five invariants in `AGENTS.md` §4 stay**, unless Shagnik decides otherwise (see Decisions). Invariant 4
   (nothing publishes without human review) and invariant 2 (specs are data, never executed code) conflict with the
   self-improve and flexibility-mod asks; those teams raise it, they do not quietly weaken it.
4. **His standards:** plain-language comments, docstrings that say why, a mocked pytest test for each part (no real
   GPU, network or keys), and a short explanation of what you did in his style. After changing anything in
   `frontend/nyx-pulse/src/`, run `npm run build`.
5. **This is a Windows app.** Cloud threads run on Linux: run what tests can run, and say plainly which checks need
   his PC (anything `ctypes`/`SendInput`, the notch window, audio, Ollama on the GPU). Use Remote Control on his
   device for those when needed.
6. **Use the images in `images/`** that your workstream lists; open them, don't guess.

---

## Section index (oldest first) with status

Status checked against code and git at `102d659`. "Partial" means a base exists that the team builds on.

| # | Pages | Lines | Ask (short) | Status and evidence | WS |
|---|---|---|---|---|---|
| S1 | 39–41 | L849–863 | Main icon (p39); replace the octopus mascot with a multi-armed character (animal, maths concept or space object) in the same pixel style, arms show tasks, animated around the chat bar, stuck animations | Not started. Current mark is the hooded "Ichnos" wizard (`site/ichnos.png`, `frontend/nyx-pulse/src/assets/ichnos.png`); no octopus or new icon in the repo. The new Coucou notch uses a character named Io (`11835b6`); the new mascot should match or replace it | 12 |
| S2 | 33–38 | L831–848 | Sidebar like p38 with a hands-off mode merged with the personal assistant; sidebar + notch draggable and lockable; wake by sound + phrase; faster voice that listens; copy kaymen99/AI-Voice-assistant and vannu07/jarvis architecture; face recognition later; copy Louis-CFM/coucou notch build | Partial. Coucou-style notch built today (`equalize_assistant.py:1-20`, `5f0617b`); desktop notch `notch.py` (`8ed7767`); claps/phrases `voice_gestures.py` (N86); wake phrase in `proto_voice.py`. Not started: p38 sidebar, hands-off mode, face recognition, the two voice repos (`docs/JARVIS.md` lists other Jarvis repos only) | 7, 6 |
| S3 | 33 | L823–828 | New icon (asymmetric, one colour, gradient top-left→bottom-right) and new pixel-art mascot that can be shown doing actions | Not started | 12 |
| S4 | 33 | L815–820 | Fixes: tab position changeable in every look (only Studio Glass now); Code, Learn, Research Lab follow the theme; sync with the desktop's colours; agents and sub-agents show 0 with an error; Trading follows colours; drag to reorder tabs | Partial. Nav bar left/right/top/bottom in Settings › Appearance (`706fa21`), verify it works in every look. `/api/agents` f-string crash fixed (`340b49a`), verify the 0/0 is gone. Not started: desktop colour sync, drag-reorder (ROADMAP BB1 still open) | 11 |
| S5 | 28–32 | L732–814 | **Ichos (lightweight app)**: always-auto normal chat, projects, coding, design; Claude/Codex look (p31); phone-compatible; 2-click Google/Microsoft connect; settings (other models, auto sort, auto category, personality, notifications, storage, voice, notch, colours with site replica); student mode; effort tiers incl. a super-max with a maths name; super-light fast model with speed tests; iPhone notch; GitHub + Vercel connectors; code stats; accounts; phone pairing by a 1-minute key; phone voice screen (p32); semi-notch at top middle with fully rounded edges; sliding model-change animation | Not started as an app. Pieces exist to reuse: chat modes incl. Auto (`chat_modes.py`), Projects (`f033e45`), Ultra Fast (`615aa7a`), homework helper, connectors catalog (GitHub, Vercel present) | 3 |
| S6 | 28 | L725–727 | Voice to action: user sets a sound + phrase ("clap, open chrome") that runs instantly like Jev | Partial. Taught claps/whistles/phrases (`voice_gestures.py`, `routes_voice_gestures.py`) and Jev-style one-step desktop commands (`ultrafast.py`, `615aa7a`). Wire them together and measure | 6 |
| S7 | 28 | L720–722 | Move "copy site look" out of Settings into the Design tab, to restyle a user's site or the app itself | Partial. Design Research tab (`db611a0`, `panels/design/DesignResearchPanel.tsx`), screenshot to code (`3ec5258`) | 12 |
| S8 | 27–28 | L698–718 | Modes (web & app dev, finance, coder, worker, student, general) with preloaded skills; Auto mode that predicts the mode; beta computer share (knows open apps/tabs, links bots to chats); background "file helper" | Partial. Turn modes exist (normal, cowork, plan, swarm, auto, ultrafast in `chat_modes.py:41`) but not these persona modes; Screen Share window exists (`b93a010`). File helper not started | 4 |
| S9 | 26–27 | L686–693 | **Projects with divisions / threads** in both apps: tasks auto-assigned to models, divisions on the right, the main chat is the delegator (p27) | Partial. Projects as tab groups with helpers (`f033e45`), sidebar Constellations (`6c3549d`). No threads, delegator or right-side division panel | 2 |
| S10 | 26 | L681–684 | Every page of the app on a Figma-style board to edit; a Design tab for websites that recognises a design and offers it | Not started (design templates under "Fractal", `6c3549d`, are the nearest piece) | 12 |
| S11 | 26 | L675–678 | "Emotions" in the AI panel: what the AI wants/feels, with a neutral AI that helps it stay healthy | Not started (the third mind in `curiosity.py` has wants and mistakes; reuse) | 15 |
| S12 | 25–26 | L647–673 | Self-improve section (4th last), flexibility mod with self mods (3rd last), rules & laws (2nd last), Slack team huddle (last) | Partial bases: `improvement_engine.py`, `self_patch.py`, `improve_autopilot.py`, `mods.py` (`61b729f`), Slack connector in `connectors/catalog.py:607`. Self-approval and self-written code conflict with invariants 2 and 4. Rules & laws and huddle not started | 15 |
| S13 | 25 | L626–642 | **Commander mod** replacing the command center: side panel instead of the band above the text box, shows every chat, auto picks model + effort, one prompt fans out to other chats and manages their tokens/context; then a "Commander" mode in the app beside normal/hard/mid/super with the chats split on the right; model select moves down next to effort | Partial. The current "command center" is Mission Control's band (`mission-control/README.md`, has a side panel and a Haiku router) and the in-app Command Zone (`command_zone.py`: usage, inbox, dispatch). No cross-chat fan-out | 2 |
| S14 | 23–25 | L520–623 | Model lineup and names: Pico (Pulse, Echo, Harmonic, Resonance, Overtone) for light devices; Monolith in the middle (Argon, Boron, Carbon, Silicon, Xenon); Crescendo (Photon, Azure, Radiance, Nexus, Abyss, Eclipse); coding (Bit, Byte, Decimal, Giga, Exa); code version "Zencode"; picker expands smoothly from the main model; effort slider glows through the spectrum to rainbow; drop "Nyx absorbed" | Not started (no names in code). Big Kahuna exists as the main router (`README.md:47`). Note "Pulse" clashes with the old "Nyx Pulse" name in docs | 5 |
| S15 | 22–23 | L494–518 | Install plugins: thedotmack/claude-mem, tghastings/strix-claude-code, Panniantong/Agent-Reach, anthropics claude-code-setup, worldflowai/everything-claude-code; VoxCPM for voice; vercel-labs/skills for project skills | Not started (no references). The app can already import SKILL.md from GitHub (`skill_import.py`, `0bb7602`) and skill packs (`e31ea73`) | 13, 6 |
| S16 | 22 | L476–489 | Office/World/Court fold into normal chat: court self-activates when the AI struggles; normal + coding + office/world merge, with a suggestion to move a hard question to an office that carries the chat over; office upscales to world; right panel with running offices | Partial. Office/World/Court open as windows beside chat (`b93a010`), made from chat (`c108df7`). No self-activating court, no auto-suggest/transfer, no progress panel | 10 |
| S17 | 18–21 | L475 | Glass as a new design option (glassy CRM dashboards, p19–21) | Partial. "Studio Glass" look exists (`8979f6a`); the dark frosted CRM style is new | 12 |
| S18 | 17 | L465–474 | Editing code or a document splits a live panel showing the work with tabs; click/hover/highlight to prompt about a section; transitions and colour palettes like the Instagram reel; scroll his Instagram saved items, learn skills, publish them as skill repos | Not started for the live panel (things now open as boxes, `2948cb1`). Instagram part needs his signed-in browser | 10, 12, 13 |
| S19 | 16 | L454–464 | Use Obsidian as Claude's brain too; make both AIs real apps (app by default, browser optional); file access like Claude; projects look like p16 | Partial. Obsidian connector exists; app window option (`05c47d6`, U25) but no installable desktop app | 13, 14, 2 |
| S20 | 11–15 | L300–453 | Avatar bot design settings like MausBot (p11: Overview, Identity, Soul, Skills, Memory, Routines, Access, Model, Permissions, Voice & alerts, History, Usage); bot hierarchy (master, co-leader, hiring bot); bots talk to each other; "consult with team"; Avatars tab higher and in the lightweight app; teams without an office | Partial. Avatars with functions, goals, schedules, personalities (`590fc5d`, `c6fa34c`, `f851a17`), MausBot ideas credited (`docs/AVATARS.md`). No hierarchy, roles, avatar-to-avatar messages | 8 |
| S21 | 9–10 | L292–299 | MausBot-style calendar in the app (p9); the AI can generate a new calendar look; drag tabs; adding a tab by dragging; pasted images show as images; "where it works" computer panel (p10) | Partial. Calendar only when Google Calendar is connected (`1ea472a`); paste handled in `files/FileDropOverlay.tsx:60` (verify it renders as an image) | 11 |
| S22 | 9 | L285–290 | Avatars tab: scroll jumps back up near Recent activity; avatar list drifted right; Save button never changes; an avatars section (dropdown) in normal chat | Open bugs (not fixed in git) | 8 |
| S23 | 8–9 | L279–283 | Drag and drop: pick up an avatar, chat or the assistant and drop it on a tab or app; Google sign-in error | Partial. Some drag already (`AgentBoxes.tsx:101`, `ActivityRail.tsx:111`). Google sign-in error open (`panels/GoogleSignIn.tsx`, `google_oauth.py`) | 11, 9 |
| S24 | 8 | L274–277 | Integrate OpenMausBot's look and features as selectable styles, keep current cool designs | Partial (ideas only in avatars, `docs/AVATARS.md:19`) | 12 |
| S25 | 8 | L271–272 | Delete a chat from the three dots by the chat name and from the left panel; auto filter and auto delete chats | Partial. Delete exists in the chat list (`ChatPanel.tsx:1011`); auto filter/delete not started | 11 |
| S26 | 7–8 | L187–269 | It can't type or use the mouse even with access; transcript shows Normal mode on qwen3.5:9b refusing to type "hi" in Google Docs | Open bug. Tools exist (`computer_control.py`: `SendInput`, `type_text`, mouse) but Normal mode and the local model do not reach for them | 4 |
| S27 | 6 | L184–186 | Use the loading widgets everywhere, big enough, visibly progressing while a tab opens | Partial (orbs and bigger loaders, `dab295b`, `e31afce`) | 11 |
| S28 | 6 | L180–183 | Test the harness so coding works; watch it code in VS Code; a VS Code extension (later) | Partial. `extensions/vscode-nyx` v0.1 exists (diff-first edits); `tell_claude` (`c358c85`) | 14 |
| S29 | 5–6 | L174–179 | Split the personal assistant layout using the FlowAI images (p5–6); coding agent lives in normal chat; make normal-chat modules useful (brain waves aren't) | Not started | 10 |
| S30 | 4–5 | L159–173 | Notch: system and search controls, sound, settings, light/dark toggle for the OS, launch apps, File Explorer, cmd with a preset prompt (e.g. Claude Code); default view (apps, music, weather, calendar, videos) customizable; triple-click or an H button switches the default; import notch looks; image p5 | Partial (notch + Coucou layout exist; these controls do not) | 7 |
| S31 | 4 | L142–157 | Notifications (top-left/right/middle/bottom-right) when a chat finishes, needs help or texts; a phone number per AI and per avatar; WhatsApp better with cloud and auto models; send and receive files over WhatsApp; transitions later | Partial. Toasts, "text me when an Office job finishes" (`a54435f`), WhatsApp line (`7333802`). No per-avatar numbers or file send/receive | 9 |
| S32 | 3–4 | L93–137 | **Trading → standalone app** (see workstream 1) | Partial base: trading desk with several AI traders (`00a266b`, `40a84ea`), Adaptive hands-off mode, `trading/` package, Finance Lab simulator (`finance_lab/simulator.py`). Not split | 1 |
| S33 | 2–3 | L85–91 | Assistant thinking: rounder/spherical look; thinking too long; repeats itself; voice tests slow; repeats the phrase it was given; every answer doubled | Open bugs. Earlier fixes: `b13912e` (name not twice), `511cec6` (Voice2 ordering and barge-in) — the doubling is still reported | 6 |
| S34 | 2 | L77–83 | Equalize notch: white box outline behind it; let him pick which avatar it uses; double intro phrase; no response, or very slow | Open, may be partly fixed: pushed at 15:08–15:12 UTC today, `1243cb7` makes the notch window transparent and sized to the island (likely the white box) and `10d12d1` carries the chosen personality into notch answers. Verify both; avatar choice, double intro and no-response still open | 6, 7 |
| S35 | 2 | L74–76 | WhatsApp: a different avatar per line; ask for or create an avatar from the general chat; Gmail access and sending fail | Open | 9 |
| S36 | 2 | L68–72 | Storage tab is slow; RAM and GPU power ceilings (EE4, EE6) with live usage vs the limit; model size and inference concurrency obey the mode (EE8) | Not started. `ROADMAP.md:454-458` (EE4/EE6 open, EE8 partial); the Power panel lists them as "still to build" (`PowerPanel.tsx:176`) | 5 |
| S37 | 2 | L64–66 | Avatar tasks: a time for daily, a weekday for weekly, and "predict if it is being asked" | Partial. `avatars.py:93` repeats daily/weekly with no time or weekday | 8 |
| S38 | 2 | L59–62 | Phone: a Claude-style remote connection; accounts linked by number or login; phone sees ongoing and new chats | Not started (WhatsApp line is the only phone link) | 9 |
| S39 | 1–2 | L23–57 | **Purpose and newest bugs:** add the GitHub skills first; "Integrity", the AI tries, finds skills, builds what it lacks; the design studio is for the AI too; any online service; remove Free Will mode and move the third mind to the main info tab; it won't open a tab or go to Finances; finish the tab design if not done after the notch redesign; it is slow in WhatsApp and the UI, needs a speed skill or restructure; copy what looks good in the images; Electron app; more machine learning, say it is ML + AI; projects work like Claude Code | Mostly open. Free Will is still a core tab (`tabs.ts:83`); third mind in `curiosity.py`. `ui.open_tab` exists (`dynamic_tabs.py:81`, `avatars.py:972`) yet he reports it failing. No Electron | 4, 5, 13, 14 |

---

## Workstreams

Effort means the thread's reasoning effort. Model suggestions use the current Claude lineup.

### WS1 — Trading as its own app (split #2)
- **Doc:** S32, p3–4, L93–137. Also S4 "trading follows colours" (moot once split, design it in).
- **Images:** p19–21 glass dashboards as a style idea for the trading dashboard.
- **Repo:** new repo, proposed `ShagnikPal123/ichos-trader` (creating it is outward-facing; the thread asks Shagnik
  first). Seed from `trading/`, `finance_lab/`, `routes_trading.py`, `finance.py`, `frontend/nyx-pulse/src/panels/trading/`
  and `panels/financelab/`. Main repo keeps nothing but a README link "the trader moved here", then removes the tab.
- **Scope:** dashboard (markets, gains, what it is thinking, agents running, next plan, predictions, money and predicted
  increase, research, win rate); scan hundreds of markets, rank by liquidity, spread, depth and order flow; rotate
  BTC/ETH/others; any market or currency; 24/7 with auto shut-down when slow or losing; a team of trader, manager,
  advisor and a mild-skeptic bot, which can add bots; learn-first mode and paper trading before real money; fully auto
  by default plus a tuning section with dials and graphs; cloud-capable with Google or GitHub login so nobody else can
  use his keys or account; latency tests with a stated target for "fast"; recommended broker/exchange connectors; an
  opt-in Claude connector used only when he asks.
- **Effort / model:** xhigh, Opus. Big enough to use sub-agents (engine, UI, connectors).
- **Depends on:** nothing to start. Real-money trading, cloud deploy and new accounts wait for Shagnik's word.

### WS2 — Projects and Commander: the command center (split #1, headline)
- **Doc:** S13 (L626–642), S9 (L686–693), S19 projects part (L462–464), S39 "projects like Claude Code" (L56).
- **Images:** p16 (project overview), p27 (threads panel: the delegator), p31 Claude Code home (usage card).
- **Repos:** `Local-AI-Project` (`projects.py`, `routes_projects.py`, `command_zone.py`, `routes_command_zone.py`,
  `panels/constellations/`, `panels/command/`) and `mission-control` (needs push access attached).
- **Scope:** a project is a folder with its chats, threads ("divisions"), sectors and links shown; the main chat is the
  delegator that sends work to threads, picks model and effort per thread, tracks each thread's tokens and context and
  briefs fresh ones; a right-side panel of divisions (Waiting on you / Idle / Resolved as in p27); auto-assign from past
  assignments; the same in normal chat via a setting. Then **Commander**: in Mission Control, a side panel instead of the
  band, listing every chat; in the app, a "Commander" mode beside the effort levels with chats split on the right,
  movable into Projects; model select moves down next to effort.
- **Effort / model:** xhigh, Opus.
- **Depends on:** WS5 for model names in the picker (use placeholders until then).

### WS3 — Ichos, the lightweight app (possible split #3)
- **Doc:** S5, p28–32, L732–814.
- **Images:** p31 Claude app and Claude Code home (the look to copy), p32 phone voice screen.
- **Repo:** proposed new folder `apps/ichos/` in `Local-AI-Project` so it reuses the engine (providers, router,
  avatars, connectors) and can "convert to the more powerful app or have both". Own frontend, phone-sized layout.
- **Scope:** everything in S5; the new mark for the lighter app lives with WS12.
- **Effort / model:** xhigh, Opus.
- **Depends on:** WS2 (projects, auto sort/category), WS5 (model tiers and the fast light model), WS9 (phone pairing).
  Can start on the shell, settings and onboarding right away.

### WS4 — Integrity: the AI acts instead of refusing
- **Doc:** S39 freedom parts (L27–46), S26 (L187–269), S8 (L698–718).
- **Images:** p10 ("where Pearl works": Auto, cloud computer, local VM, this PC, browser).
- **Repo:** main. `chat_modes.py`, `turn_runner.py`, `tools.py`, `computer_control.py`, `machine_control.py`,
  `permissions.py`, `freewill.py`, `curiosity.py`, `panels/freewill/`, `dynamic_tabs.py`.
- **Scope:** fix "open a tab" and "take me to Finances"; give Normal mode the mouse and keyboard and make the local
  model use them (reproduce the Google Docs transcript); when a skill or connector is missing, find it (GitHub, web) and
  add it, then do the task; the AI may use the design studio itself; remove Free Will mode and move the third mind into
  the main info tab; persona modes with preloaded skills plus Auto mode; beta computer share; file helper.
- **Effort / model:** high, Opus.
- **Depends on:** WS13 for the skill sources. Safety gates (taint gate, confirmation gate) stay unless Shagnik decides.

### WS5 — Speed, model lineup and machine learning
- **Doc:** S39 speed and ML (L48–56), S14 (L520–623), S36 (L68–72), S5 speed parts (L796–799).
- **Repo:** main. `router.py`, `model_choice.py`, `model_roles.py`, `fast_response.py`, `ultrafast.py`,
  `resource_governor.py`, `storage_budget.py`, `panels/PowerPanel.tsx`, `panels/StorageSection.tsx`, the model picker.
- **Scope:** measure first (UI turn, WhatsApp turn, voice turn) and publish the numbers; a speed restructure or skill;
  a super-light auto-sized model path, with speed tests; the named lineup (Pico, Monolith, Crescendo, coding Bit→Exa,
  Zencode) with a smooth expanding picker and the rainbow effort slider; drop "Nyx absorbed"; EE4, EE6, EE8; Storage
  tab speed; more ML (learned routing, prediction) and say in the README it is ML + AI.
- **Effort / model:** xhigh, Opus.
- **Depends on:** nothing. Owns the model picker component; WS2/WS3 consume it.

### WS6 — Voice and the Equalize assistant
- **Doc:** S33 (L85–91), S34 (L77–83), S6 (L725–727), S2 voice parts (L838–845), S15 VoxCPM (L514–517).
- **Images:** p32 phone voice screen.
- **Repo:** main. `voice_pipeline.py`, `voice.py`, `tts.py`, `proto_voice.py`, `equalize_voice.py`,
  `routes_equalize.py`, `voice_gestures.py`, `frontend/nyx-pulse/src/voice/`, `panels/equalize/`.
- **Scope:** fix doubled answers, the double intro phrase, repeating, no response, slow voice tests; shorter thinking;
  a rounder thinking visual; choose which avatar Equalize uses; really listens; study kaymen99/AI-Voice-assistant,
  vannu07/jarvis and VoxCPM and adopt what is faster (licences checked, ideas or permitted code only); voice-to-action
  bound to taught sounds; face recognition later.
- **Effort / model:** high, Opus.
- **Depends on:** WS5's measurements help; not blocking.

### WS7 — Notch, sidebar and hands-off mode
- **Doc:** S30 (L159–173), S2 notch/sidebar parts (L831–838, L847–848), S34 white outline (L77–79).
- **Images:** p05 notch widgets, p34–36 Coucou notch, p37 notch dropdown and pill, p38 sidebar.
- **Repo:** main. `notch.py`, `routes_notch.py`, `equalize_assistant.py` (UI side), the notch window code.
- **Scope:** remove the white box behind the notch; system controls, app launchers, cmd with a preset prompt, default
  view (music, weather, calendar, videos) and how to switch it (triple click, H button); importable notch looks; the
  p38-style sidebar merged with the assistant as a hands-off mode; sidebar and notch draggable and lockable; wake by a
  recorded sound + phrase, notch expands while listening.
- **Effort / model:** high, Opus.
- **Left open by the notch rebuild** (`AI_HANDOFF/START_HERE.md` on his PC): the wake phrase is saved but not listened
  for; voice cloning is pitch-matched only; agents' approvals and questions don't pop the notch open yet; real mic,
  real email send and dragging a file from Explorer onto the notch are untested.
- **Depends on:** WS6 for wake and voice. Shared file: `equalize_assistant.py` — WS6 owns the voice parts, WS7 the
  notch parts.

### WS8 — Avatars and bot teams
- **Doc:** S20 (L300–453), S22 (L285–290), S37 (L64–66).
- **Images:** p11 MausBot bot settings, p15 MausBot team chat, p10 computer panel.
- **Repo:** main. `avatars.py`, `routes_avatars.py`, `panels/avatars/`, `agent_team.py`.
- **Scope:** fix scroll jump, drifted list, Save button; per-avatar settings sections like p11; hierarchy (master,
  co-leader, hiring bot) and avatar-to-avatar messages, "consult with team"; teams without an office; Avatars tab moves
  up; avatars dropdown in normal chat; daily time, weekly weekday and "predict when asked".
- **Effort / model:** high, Sonnet.
- **Depends on:** nothing.

### WS9 — Phone, WhatsApp, Gmail and notifications
- **Doc:** S35 (L74–76), S31 (L142–157), S38 (L59–62), S23 Google sign-in (L282–283), S5 phone pairing key (L804–806).
- **Repo:** main. `whatsapp_link.py`, `whatsapp_worker/`, `routes_whatsapp.py`, `email_client.py`, `google_oauth.py`,
  `panels/GoogleSignIn.tsx`, the toast store.
- **Scope:** fix Google sign-in and Gmail read/send (also from WhatsApp); an avatar per line and picking or creating an
  avatar from the general line; send and receive files and images; notifications on PC and phone when a chat finishes,
  needs help or texts; a number per AI/avatar where possible; a Claude-style remote connection from the phone with a
  1-minute pairing key fallback.
- **Effort / model:** high, Sonnet.
- **Depends on:** WS8 for per-avatar lines. Extra phone numbers cost money or need accounts: Shagnik decides.

### WS10 — Normal chat as the one place to work
- **Doc:** S16 (L476–489), S18 live panel (L465–468), S29 (L174–179).
- **Images:** p05–06 FlowAI dashboard with the assistant panel.
- **Repo:** main. `panels/ChatPanel.tsx`, `components/chat/`, `components/windows/`, `office/`, `court.py`,
  `office_world_tools.py`.
- **Scope:** Court self-activates when the AI struggles; normal + coding + office/world in one chat, with an offer to
  move a hard question to an office that carries the chat; office scales up to world; right panel of running offices;
  the live editing panel with tabs and highlight-to-prompt; the personal-assistant layout from the FlowAI images;
  useful modules in normal chat instead of brain waves.
- **Effort / model:** high, Opus.
- **Depends on:** WS2 (the right-side panel pattern). **Owns `ChatPanel.tsx`.**

### WS11 — UI fixes, drag and drop, loading
- **Doc:** S4 (L815–820), S21 (L292–299), S23 drag and drop (L279–282), S25 (L271–272), S27 (L184–186),
  S39 "finish the tab design" (L46–48).
- **Images:** p09 MausBot calendar, p10 computer panel.
- **Repo:** main. `App.tsx`, `components/TopTabs.tsx`, `tabs.ts`, theme files, `panels/code`, `panels/LearnPanel.tsx`,
  `panels/research`, `files/`.
- **Scope:** tab position in every look; Code, Learn, Research Lab follow the theme; sync with the desktop's colours;
  agents/sub-agents 0 + error; drag to reorder and drag in new tabs; drag avatars, chats and the assistant onto tabs or
  apps; in-app calendar like p9 that the AI can restyle; pasted images show as images; delete from the chat's three dots
  and the left panel; auto filter and auto delete; loading widgets everywhere; finish the boxy tab design.
- **Effort / model:** medium–high, Sonnet.
- **Depends on:** none. Hands `ChatPanel.tsx` changes to WS10.

### WS12 — Design system, brand and motion
- **Doc:** S17 (L475), S18 transitions/palettes (L469–470), S1 + S3 (L823–863), S10 (L681–684), S7 (L720–722),
  S24 (L274–277), S39 "copy what looks good" (L51–53), S31 transitions (L149–153).
- **Images:** p19–21 glass CRM, p39 main icon, p41 mascot reference.
- **Repo:** main. Theme/style files, `assets/`, `site/`, `panels/design/`, `design_studio.py`, `design_research.py`.
- **Scope:** glass as a selectable look; OpenMausBot styles as selectable looks; new icon and a multi-armed pixel
  mascot that shows tasks per arm and animates around the chat bar; Figma-style board of every page; Design tab for
  websites, with copy-site-look moved there; colour palettes; **transitions and sound last**, after every other team.
- **Effort / model:** high, Opus.
- **Depends on:** most UI teams for the final transitions pass.

### WS13 — Skills, plugins and Obsidian (goes first)
- **Doc:** S39 "add all skills first" (L26), S15 (L494–518), S18 Instagram (L470–474), S19 Obsidian (L454–459).
- **Repo:** main (skills for the app via `skill_import.py` / `skill_packs.py`; `.claude/` skills for Claude sessions)
  plus his device for Claude Code plugins and Obsidian.
- **Scope:** review the five Claude Code repos, vercel-labs/skills and VoxCPM; add the useful skills to the repo and
  to the app; list what must be installed on his PC (Remote Control); Obsidian as a shared brain for Claude sessions and
  both apps; the Instagram saved-reels pass needs his signed-in browser, so it waits until a thread has browser access
  on his device; skills he writes go to new skill repos only with his OK.
- **Effort / model:** medium, Sonnet.
- **Depends on:** nothing. Others wait on its skill list, not on all of it.

### WS14 — Real desktop app and VS Code
- **Doc:** S39 Electron (L53–54), S19 "both AI an actual app" (L455–459), S28 (L180–183).
- **Repo:** main. `launcher.py`, `nyx.spec`, `build_release.py`, `Start Nyx.bat`, `extensions/vscode-nyx/`.
- **Scope:** an installable desktop app (Electron or similar) that opens as an app by default, browser optional, for
  both the full app and Ichos; anti-crash and stay-on; harness tests for coding; watch it code in VS Code; grow the VS
  Code extension (later priority).
- **Effort / model:** high, Opus.
- **Depends on:** WS3 for the second app.

### WS15 — Autonomy layer (his last four, in order)
- **Doc:** S12 (L647–673), S11 (L675–678).
- **Repo:** main. `improvement_engine.py`, `self_patch.py`, `improve_*.py`, `mods.py`, `change_review.py`, a new rules
  module, the Slack connector.
- **Scope, in his order:** self-improve section (rewrite and self-approve), flexibility mod (self mods, add abilities
  like Bluetooth), rules & laws (numbered, nested, user-made, with a slider for how much the AI may add), emotions panel,
  then the Slack team huddle (human-named bots running a business) last.
- **Effort / model:** xhigh, Opus.
- **Depends on:** his decision on invariants 2 and 4; runs last.

### WS0 — Handoff reorder (done in this thread)
- `NYX_WORKPLAN.md` (the in-repo handoff/task board): this document's request is now §0 at the top, the older request
  and the rest follow below. The real handoff, `AI_HANDOFF/START_HERE.md`, is git-ignored and lives only on his PC;
  it needs the same reorder through Remote Control on his device.

---

## Earlier work each team should read

On his PC, `AI_HANDOFF/` (git-ignored) holds `01_GOALS.md` with every past request verbatim, `START_HERE.md` (the
resume point, now with this plan on top) and `FIXER_UPPER/` (this plan, the text and the images). A team that needs
them uses the folder on his device.

GitHub matches the PC: the latest local session ("Equalizer4 assistant redesign") pushed its notch rebuild to
`main` at `50d49be` on 2026-10-13 and left only two unrelated local files out. Most past AI Dev chats ran in the
Claude desktop app and are not readable from a cloud thread; their results are in git history (checked above), the
session log in `PROJECT_STATE.md`, and the docs named here. If a team needs a specific old chat, ask the coordinator,
or open a session on his PC. Chat titles are as they appear in his sidebar.

| WS | Past chats (sidebar titles) | Docs and logs in the repo |
|---|---|---|
| 1 Trader | AAI trader optimization and settings; Finance simulation and chat interface; Apple Design trading/finances feature | `PROJECT_STATE.md` session 2026-09-22→24; `finance_knowledge.md` |
| 2 Command center | Command zone chat screen; Claude code usage audit | `command_zone.py` header; `mission-control/README.md` |
| 3 Ichos app | Nyx Ichos AI naming | `docs/DESIGN.md` |
| 4 Integrity | Engine single-click activation; AI improvement plan | `ROADMAP.md` V (machine control), T (auto-everything) |
| 5 Speed and models | Context window size increase; Identity 0 core AI model | `docs/IDENTITY0.md`, `docs/adr/ADR-001-identity-0.md`, `ROADMAP.md` W, EE |
| 6 Voice | Voice animation states and feedback; Voice interface and site improvements; Thinking-orbs integration and design | `ROADMAP.md` G, FF; `docs/JARVIS.md` |
| 7 Notch | Equalizer4 assistant redesign (pushed at `50d49be`) | `equalize_assistant.py` header; `docs/WINDOWS_IN_CHAT_PLAN.md` |
| 8 Avatars | AI bot integrations and avatars; AI chat collaboration design | `docs/AVATARS.md` |
| 9 Phone | WhatsApp connector for phone texting | `docs/WHATSAPP.md` |
| 10 Normal chat | World upscaling and structure; Startup animation and office space | `docs/WORLD.md`, `docs/WINDOWS_IN_CHAT_PLAN.md` |
| 11 UI fixes | Startup animation and tab redesign; AI app crashes/freezes | `docs/DESIGN_FIX_PLAN.md` |
| 12 Design | Design research for AI layout; Design skills announcement; Site redesign with GitHub link; Google Docs design reference | `docs/DESIGN.md`, `reports/Ichos design research sweep.md` |
| 13 Skills | AI skills and Instagram saved content; Obsidian API integration (two chats, Sep 5 and Sep 8); Mods integration for AI application | `NYX_WORKPLAN.md` §0b (Obsidian decisions) |
| 14 Desktop app | Fix engine shutdown hook; Save and publish to GitHub; 3D build studio performance | `AGENTS.md` §3 (Smart App Control blocks unsigned .exe) |
| 15 Autonomy | AI improvement plan (fork); Handoff continuation | `change_review.py` header; `AGENTS.md` §4 |

## Start order

| Wave | Workstreams | Why |
|---|---|---|
| 1 | WS13 | He said skills first; quick |
| 1 | WS2, WS1, WS4, WS5, WS6 | The headline split, the trading split, and his newest and loudest bugs (restrictions, speed, voice) |
| 2 | WS8, WS9, WS11, WS7, WS10, WS14 | Bugs and features that build on wave 1 |
| 2 | WS3 | Once WS2 and WS5 have shapes to reuse |
| 3 | WS12 | Brand can start any time; the transitions pass is last by his word |
| 3 | WS15 | His four "last" items, after his invariant decision |

## Shared files and owners

| File | Owner | Others |
|---|---|---|
| `frontend/nyx-pulse/src/panels/ChatPanel.tsx` | WS10 | WS2, WS4, WS11 send changes through the coordinator |
| `frontend/nyx-pulse/src/App.tsx`, `tabs.ts` | WS11 | WS4 (Free Will removal), WS8 (Avatars position) |
| Model picker / effort control | WS5 | WS2, WS3 |
| `equalize_assistant.py` | WS6 voice parts, WS7 notch parts | |
| `chat_modes.py` | WS4 | WS2 (Commander mode) |
| `NYX_WORKPLAN.md`, `PROJECT_STATE.md` | each team appends its own section only | |

## Decisions for Shagnik

1. **Invariants 2 and 4** (`AGENTS.md` §4): self-improve wants self-approval and the flexibility mod wants
   self-written code. Keep the human approval step, or relax it inside the self-improve section only?
2. **New repos:** `ichos-trader` for the trader, and whether Ichos Lite is a folder in this repo (proposed) or its own repo.
3. **Real money and paid services:** live trading, cloud hosting for the trader, extra phone numbers per avatar.
4. **Device-only work:** Claude Code plugin installs, the Obsidian vault, the Instagram saved reels and the local
   `AI_HANDOFF/START_HERE.md` need a session on his PC.
