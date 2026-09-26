# START HERE — Nyx Ichos resume point

**Last updated:** 2026-09-26 by Claude (Opus 5.5) — website overhaul + GitHub push (below). Update this file whenever you stop.

## PROJECT NULL — the overhaul: `AI_HANDOFF/PROJECT_NULL.md` (recorded 2026-09-21, building since 2026-09-22)

**That file is the handoff doc for the overhaul: what is done, what each session is building right now, and what comes
next.** Read it first; this file holds the detail of every finished request.

The owner sent a very large list (Super control + voice, Office Space with hundreds of agents, Super Work, connectors,
voice upgrades, site download button, finance, bugs…) and said: "make sure this is known as plan null … Do not act on it
prepare for it but thats it. Not changes." It was called Plan Null then, and renamed **Project Null** on 2026-09-22 at
the owner's request. On that day they handed parts of it to seven Claude sessions, so most of it is under way.
**Anything no session has claimed stays prepare-only until the owner says to start it.**

## DONE — 2026-09-26, later (session 1da8a0) — repo public, the jumping mode switch, Accounts, the ideas file

**Future ideas the owner wants next are in `AI_HANDOFF/UPDATE_IDEAS.md`** (U1–U15: Research tab fix, image drawing tab,
working Collab + repo link, "super free create", Swarm + Swarm/Auto chat modes, a Cloud environment button and Cloud
mode, any-site connectors, better 3D / game / web dev with ways to try the result, remove Agent City, several offices at
once, memory-field clutter). Ideas only — nothing there is built until the owner picks one.

- **GitHub is public** (owner: "publish the github"). Before that, main's history was rewritten with git-filter-repo to
  replace the owner's Obsidian key in two old files; every commit hash changed (main is 6da8606 and later), the latest
  tree was byte-identical. GitHub still serves the pre-scrub commits to anyone who has their exact IDs, and the repo's
  Activity page shows the force-push, so the owner should still reset the key in Obsidian.
- **Normal · Co-work · Plan no longer jump under the mouse.** Hovering an option swapped in that option's description;
  a longer one wrapped to another line, the row grew, the switch moved out from under the pointer, the hover ended, the
  row shrank back under the pointer — a loop. The three descriptions now share one grid cell and only one is visible,
  so the box keeps the tallest one's height (`components/chat/ModeSlider.tsx`, `chat.css`). Measured at a 330 px chat
  sheet: the old box was 16 px for Normal and 32 px for Co-work/Plan; now 32 px whichever shows, switch top unchanged.
- **Accounts** (owner: "add an accounts next to the logout place … a separate file division between account … account
  creation with password if wanted, name of account … and add a purpose to semi feed the AI"):
  - `paths.py`: an account is a folder. `ACCOUNT_SCOPED` stores (chats, internal chats, memory, personality, speech
    patterns, predictions, notes, slides, brain, learning, uploads, attachments, research, absorb, data_process,
    diagrams, offices) resolve inside `accounts/<id>/`; keys, sign-in, settings, models, tabs, skills, trading and
    kahuna/ stay shared. "main" is the old data where it always was — nothing moved. `ACTIVE_ACCOUNT` is fixed at
    import (from `accounts/index.json`, or `NYX_ACCOUNT`), because most stores open their file once.
  - `local_accounts.py`: create (name, optional purpose, optional password ≥ 6 chars, scrypt hash only), update,
    switch, remove (moves the folder to `accounts/_removed/`, never deletes; Main and the open account can't be
    removed), 5 wrong passwords → 60 s lockout, `purpose_note()`.
  - `routes_accounts.py` (`/api/accounts*`): the OWNER only — admins and testers are refused like Big Kahuna; absent
    from hosted builds. Switching restarts the engine through the launcher; an engine started by hand says "Restart
    Nyx to open …".
  - `chat_service.py`: a "## This account" section in the standing instructions (and on the fast path) with the name,
    the fact that other accounts' data is invisible, and the purpose in the owner's words.
  - UI `components/accounts/AccountsButton.tsx` + `accounts.css`: the bar button (colour dot + name) before Log Out, the
    Accounts sheet (list, Switch / Unlock & Switch, Edit, Remove, + New Account), and an "Opening …" screen above
    the engine-off screen while it restarts.
  - Tests `tests/test_local_accounts.py` (17) + the account block in `tests/test_server_auth.py`. LIVE-VERIFIED on a
    scratch NYX_DATA_DIR: made "NIS" with a password, wrong password refused, switched, restarted into NIS, a new chat
    landed in `accounts/nis/chats.json` and not Main's, and the model's prompt carried the purpose.
  - `accounts/` is git-ignored and never ships in the release zip.

## DONE — 2026-09-26 (session 1da8a0) — website overhaul, GitHub push, publish (= Project Null N91, N4 in part)

Owner: "I want my site to have a link to github, full over hall and redesign to match the design of the AI now …
on the site I want there to be a download link … next to github. Make sure github is fully updated. Then publish it."
Then: "Site as in the website not the AI … if you could rename it. I would rather just have the AI name in there and
add to the github." → the address is **https://nyx-ichos.vercel.app** (not the long per-deploy URL).

- `site/index.html` rebuilt with /apple-design on the app's own tokens (theme.css): black-first, violet #A594FF,
  glass bar with the app's wordmark, a live **memory field** hero (star band, four coloured clusters with tags, impulses
  along links; still under reduced motion, paused off screen), **Download for Windows** + **View on GitHub** side by
  side (and in the bar), `#install` as three numbered steps + Launch Nyx + "If Windows stops it" + "Run from source",
  What's inside (8 tabs), Privacy. The download button is dc471e's N91 spec: hover fills half, click fills with the
  real percentage (a black copy of the label clipped to the fill keeps it readable), Cancel, a live region, and if the
  zip is not on the site it becomes a GitHub link and says so. `site/404.html` matches. Checked at 375 px and 1280 px.
- Removed from `site/`: the stale hosted `/app` build and old launcher scripts. `site/.vercelignore` keeps `beta/`,
  `collab/`, `api/` off the public site until docs/COLLAB_SETUP.md is done (step 5 now says to delete those lines).
- `build_release.py`: public digests (EICAR) no longer stop the build; `AI_HANDOFF/*` and IDEAS_ROUND2.md never ship.
  Tests `tests/test_build_release.py` (3). The zip was extracted and booted from its own folder (GET / serves the UI).
- `.gitignore`: model_roles.json, research/, security/, curiosity/, feature_catalog.json, voice_gestures.json,
  finance_lab/*.json are runtime state. NYX_WORKPLAN.md had the owner's Obsidian key in it — redacted; it is still in
  three OLD pushed commits, so the owner should rotate it (Obsidian → Local REST API) before the repo goes public.
- `tests/test_trading_runmode.py`: teardown now stops and joins the autopilot thread one test starts — it used to keep
  scanning into the next test's store and, between tests, the owner's real one (no orders were placed).
- README.md rewritten for the current app. Found, not fixed (chip task): server.py's shutdown hook awaits every asyncio
  task, including the server's own, so shutdown can hang. NOTE: `NYX_NO_BACKGROUND=1` does not stop the trading
  autopilot — any engine started in this folder resumes the owner's AI trader (ai.enabled, run_mode always).
- The GitHub repo was made **public** later the same day (see the next entry), after the Obsidian key was scrubbed from
  its history.
- How to publish the site again: build the zip from a clean checkout of the pushed commit (`git worktree add`, copy
  `frontend/nyx-pulse/dist` in, run its `build_release.py`), copy it to `site/downloads/NyxIchos-Windows.zip`, then from
  `site/`: `npx vercel deploy --prod --yes` (the CLI was signed in as shagnikpal-5976 on 2026-09-26; `site/.vercel`
  links the nyx-ichos project and is git-ignored). Check that `curl -s https://nyx-ichos.vercel.app/ | sha1sum` matches
  `site/index.html`.

## DONE (2026-09-22 → 25, session be872d) — Project Null N19b + N20–N25 = rows N80–N89

Verbatim in PROJECT_NULL.md § "Added 2026-09-22 (session be872d …)". All ten rows are built, tested and live-checked
against the running engine except where noted. Full suite green (2019 passed) after the last change.

- [x] **N87 console windows never steal typing** — `quiet_windows.py`: `install()` (called from `server.py` and
      `launcher.py` before anything spawns) makes `CREATE_NO_WINDOW` the default for every `subprocess.Popen` and
      replaces `os.system`; an explicit `CREATE_NEW_CONSOLE`/`DETACHED_PROCESS` is respected. Call sites that were
      missing the flag were fixed too (voice.py ×5, ollama_setup, connectors/system_control ×5, app_launcher,
      device_profile ×2). `check_call_sites()` + `tests/test_quiet_windows.py` (7) keep new ones honest.
      LIVE: a real spawn was counted as hidden. NOTE FOR THE OWNER: the disabled `NyxIchosEngine` logon task still
      points at `run-nyx-background.cmd`; a task running a .cmd flashes a console at logon. Point it at
      `.venv\Scripts\pythonw.exe launcher.py --background` if it is ever re-enabled.
- [x] **N80 run modes** — `trading/autopilot.py`: `market` (sleeps to the opening bell and starts itself), `always`
      (24/7 until stopped), `until` (stops itself at a time). `set_run_mode` / `stop` / `run_status`, resumes after a
      restart. `trading/market.py` gained the real clock: New York DST, NYSE holidays, 1 pm early closes, `session()`
      and `next_open()`. `POST /api/trading/run-mode`, `/autopilot/stop`, `GET /api/trading/run`.
- [x] **N81 practice vs real** — `PaperBroker` is "Practice money (simulated — no real money)": fills cross the spread
      and slip, a commission is charged, an order given while the market is shut waits for the opening bell, and an
      equity curve + vs-SPY benchmark are kept (`stats()`, `paper_settings()`). `Broker.money()` → "practice" | "real"
      is the single source for every label. Trading tab: a money band across the top, the run-mode control, and a
      "Practice account" card (value, costs, worst dip, start again with $50/$1k/$10k/$100k, realism settings).
      Tests `tests/test_trading_runmode.py` (12). LIVE-VERIFIED in the browser.
- [x] **N85 question cards** — a ```question block (also `<question>` tags, and bare JSON with no fence, because
      small models drop it) renders as `components/chat/QuestionCard.tsx`: options with what each one means, a
      "would pick" badge, and a box for an approach it did not list. Clicking sends the answer as the next message
      (`nyx:chat-send`). Rule 11 in the system prompt (`question_cards.FORMAT_RULE`). LIVE: qwen3.5 asked a real
      question, the card rendered from unfenced JSON, clicking it answered.
- [x] **N82–N84 chat modes** — `chat_modes.py` + `components/chat/ModeSlider.tsx` under the composer (shares
      `.chat-bottom-row` with fc578b's toolbar). Normal: skips the prompt optimizer and second opinions, keeps the
      quick path, and is told to think out loud in short lines. Co-work: full pipeline, 48 tool steps, a live
      checklist (`update_checklist` tool → `checklist` event → the bubble), and a message sent while it is working
      runs alongside instead of queueing. Plan: writes a ```plan block and **may not change anything** — a
      deny-by-default guard wraps any guard already on the chat — then `PlanCard.tsx` lets the owner tick spec lines,
      answer its questions and press Approve and Start, which sends the approved plan as a `plan_go` turn.
      `mode` on `/api/chat/stream` → `ChatService.chat_turn` → `TurnRunner`. Tests `tests/test_chat_modes.py` (12).
      LIVE: Plan mode produced a plan and touched nothing; the card rendered with Approve and Start.
      NOT live-exercised: the Co-work checklist rendering (the tool and the reducer are unit-tested).
- [x] **N89 Notes slides** — `slide_reader.py` reads .pptx straight from its zip (per-slide title, body, and the
      speaker notes followed through the rels file), PDFs a page per slide, and text; groups slides into sections and
      hands a study action only the slides asked for. `POST /api/notes/slides`, `GET /api/notes/{id}/slides`,
      `POST /api/notes/{id}/slides/study`; new study actions `slides_notes`, `slides_questions`, `custom` (a typed
      request routes itself: "quiz me" makes a quiz). UI `panels/notes/SlidesStudy.tsx` (drop zone, sections, slide
      chips, buttons, "ask for anything" box). `notes_store.KINDS` gained "slides". Tests `tests/test_slide_reader.py`
      (10, including the whole route path). LIVE: a 6-slide deck → questions on slides 3–4 only, using the speaker note.
- [x] **N86 Clap** — `voice_gestures.py` + `routes_voice_gestures.py` (`/api/voice/gestures*`, `/api/voice/greeting`)
      and `src/voice/clapDetector.ts`: claps and whistles by shape, anything else (a rhythm, a knock, a phrase) taught
      from three takes and matched with DTW over 12 band energies — all offline, nothing recorded. It listens only
      when away / offline / with Proto Voice, borrows dc471e's echo-cancelled mic (`vadStream()`) when voice is on,
      and goes deaf while Nyx speaks. Every voice start says a line ("Nyx here. Listening." — owner-editable, every
      time / first each day / never). Settings → Clap (`components/clap/*`). Tests `tests/test_voice_gestures.py` (9).
      LIVE: the panel loads both gestures; the greeting and a "heard" response came back from the engine.
      NOT tested: real audio detection (no microphone in this session) — the owner should clap at it once.
- [x] **N88 design sense** — `design_sense.py`: `build_brief()` / `brief_for_prompt()` / `record_decision()` +
      `/api/design/brief|taste|decisions` and the `design_brief` / `design_decision` tools. A brief is built from the
      owner's own past UI words (mined from 01_GOALS.md), what they kept and undid, this app's real tokens, their
      other tabs, the Apple library, optional web references — then the model decides intent, mood, 2–3 directions,
      the chosen one, tokens, layout, states and **what to avoid**; the standing "no default design" list always
      survives. Wired into both tab-creation paths (`landscape_tools._design_blocks`, `POST /api/tabs/design`).
      Tests `tests/test_design_sense.py` (8). The Redesign tab (c69db1) was told the contract; that session ended, so
      whoever picks it up should call `build_brief(request, tab_id=…, sources=[{kind,value,label}])`.

Also from this session: `trading/guard.py` calls dc471e's `finance_lab.capital_guard.check_order` on every AI order
(fails open; with no pot allocated it allows and says so, so an unopened finance lab cannot stop a working trader).

## IN PROGRESS (2026-09-22, session dc471e) — Project Null N11–N19 = rows N90–N110

Voice, the website, Proto Voice, files, Screen Share and the finance lab (verbatim + rows in PROJECT_NULL.md § "Added
2026-09-22 (session dc471e …)"). Handed over to this session today: `ActiveTalk.tsx`, `screen_share.py`,
`routes_screen.py`, `panels/screen/**`, `freewill.py`, `routes_freewill.py`, `panels/freewill/**`.
Order: shared pieces other sessions wait on first (voiceBus, fileIntake, file_guard, capital_guard) → links + caret →
voice → Proto Voice → feature catalog → Curiosity → finance lab → Screen Share → site.
- [ ] N90 voice engine · [ ] N92 Proto Voice · [ ] N93/N94/N95 files · [ ] N101 caret · [ ] N102 links
- [ ] N100 feature catalog · [ ] N103 Curiosity · [ ] N104–N110 finance lab · [ ] N96–N99 Screen Share · [ ] N91 site

## IN PROGRESS — Request S (2026-09-18 → 24): Identity 0, a.k.a. "Big Kahuna" — the new main brain

Verbatim + goal table (S1–S22): `01_GOALS.md` § Request S. Design record: `docs/adr/ADR-001-identity-0.md` (amended
2026-09-21: the own model is ours from scratch; Qwen is only a teacher). **Living design, contracts, build notes,
first measured results and progress log: `docs/IDENTITY0.md` — read it before touching `identity0/`.**

Built and tested (`tests/test_identity0_*.py`, ~145; full suite 2026-09-24: **1,857 passed, 0 failed**):
- [x] S1/S2/S3/S20 Big Kahuna is router provider `identity0`, first in the chain; picks the lead per domain from a learned
      competence table, streams through the router (key failover kept), shadows + order-swapped judge + lessons.
      LIVE: a real chat turn went through it (1.8 s). The owner's default provider is `identity0`, and it now appears in
      **Keys & Models** as "Main brain · no key — always on".
- [x] S4/S5/S7 own model: `identity0/model/` (our transformer, tokenizer, trainer, AirLLM layered mode + int8/NF4,
      registry, serve on 127.0.0.1:11500, client). Twin stage starts by itself once a version is promoted.
- [x] S6 Safe-mix corpus + teacher distillation (`kahuna/datasets/sft.jsonl`).
- [x] S8 supercore: versioned constitution (`identity0/supercore.py`, `kahuna/constitution.json`) — the owner edits,
      Big Kahuna may only propose; every version kept, rollback available. It is also selectable for any model role.
- [x] S10/S18 tab planner, S11 templates (69), S12 scoreboard, S15–S17 predictions (+ learning from 👍/👎), S19 fast
      path for voice/trading, S21 ID0 + All companion (own chat, thoughts, early voice actions; email → Gmail draft,
      never sent), S22 voice turns go through Big Kahuna's fast path. UI: tab `kahuna` ("Big Kahuna"), companion window.
- [x] Owner-only: every `/api/identity0/*` route refuses anonymous, beta **and admin** callers (tests prove it).
- [~] S4 quality: `nano-v1` trained and promoted, but it is weak — scoreboard 0.15 vs the teacher's 0.90
      (`docs/IDENTITY0.md` §5.1). Cause: 8.5M tokens of text for 32M parameters. The corpus is now 341M characters
      (18k+ documents) and growing, and training is resumable, so `nano-v2` is the first honest attempt.
- [ ] S14 shrink the disk size (last step), then T GitHub → U beta link → V accounts (Google + Apple).

**Other features call Big Kahuna through `identity0/api.py` only** — `best_models(task_or_domain)`, `domain_of(text)`,
`competence()`, `voice_intent(text, final=, tabs=)`, `suggest(text, current_tab=)`. They never raise and never write.

Running jobs (check with `.venv/Scripts/python.exe -c "from identity0 import jobs; print(jobs.list_jobs()[0])"`):
a `train_nano` run (150 min) and a `corpus` run (~30k articles). A job whose process dies now shows as `interrupted`
and can be resumed: `POST /api/identity0/jobs/{id}/resume`, or `jobs.resume("<id>")`.

Environment (owner consent): torch 2.11.0+cu128 in `.venv`; Ollama 0.34.2 + `qwen3.5:9b` (start it with
`identity0.members.maybe_start_ollama()` — it had quietly stopped and cost a distillation run); `.env.local`
`OLLAMA_MODEL=qwen3.5:9b`. No full-precision base weights (owner: "don't download yet").

## DONE — 2026-09-24 — "At times the AI seems to close the app or stops working"

- Cause: the AI's own PC tools could end Nyx mid-reply — `window_action close` matched by program name ("chrome")
  landed on the Nyx tab, `press_keys alt+f4/ctrl+w` hit the Nyx window, `kill_process python/chrome/ollama` and
  `run_command taskkill …` ended the engine, its browser or Big Kahuna's Ollama.
- Fix: `self_guard.py` — every one of those paths asks it first and gets a refusal sentence back. Wired into
  `computer_control._match_window` (prefers non-Nyx windows), `window_action`, `press_keys`,
  `machine_tools.kill_process`, `run_command`, `run_python`. Shell shutdown/restart is sent to `system_power`
  (which has a cancel delay). Tests: `tests/test_self_guard.py` (14).
- Not changed: the improvement autopilot still restarts the engine when idle after applying changes
  (`improve_autopilot._maybe_restart`, control `restart_when_idle`) — that is a planned restart, not a crash.

## DONE — 2026-09-23 (session 6bd7de) — "Add checks to ensure files are not malicious" (= Project Null N94)

- `file_guard.py` — one check in front of every way a file reaches Nyx, layered and never running the file:
  what the bytes really are (magic vs extension: a `.png` that is a PE is blocked, so are `invoice.pdf.exe` and
  right-to-left-override names); shape traps (zip bombs, archive entries that escape the folder, programs inside an
  archive, Office macros / remote templates / DDE, PDF `/Launch` blocked and `/JavaScript` flagged, SVG or HTML
  carrying script, image pixel bombs); known-bad command shapes (encoded PowerShell, `curl | sh`, reverse shells,
  `vssadmin delete shadows`, miners, mimikatz, `eval(atob(...))`); weights that run code (pickle opcodes of
  `.pt/.ckpt/.bin` read with `pickletools`, `os`/`subprocess`/`builtins` imports blocked, `.gguf`/`.safetensors`
  headers verified); a real **Windows Security** scan (`MpCmdRun -Scan -ScanType 3 -DisableRemediation`, found under
  `%ProgramData%\Microsoft\Windows Defender\Platform\`, 0.1 s on a small file, skipped over 256 MB); and text
  aimed at the assistant ("ignore all previous instructions…") which becomes a warning wrapped around the file's
  content (`note_for_model`) rather than a refusal.
- Verdicts are `clean | caution | blocked`: blocked means nothing is stored (the owner's original is untouched),
  caution means the file is kept and used with the reason attached to the record and shown in the chat.
- Wired into: `uploads.save_upload` (before a byte is written; `record["security"]` carries the verdict and
  `message`), `GET /api/uploads/{id}` (nosniff + CSP sandbox, HTML/SVG served as an inert attachment),
  `uploads.model_input_for_upload`, `media_tools._load_source`, `machine_tools.download_file` (deletes a bad
  download), `beta_channel.download` (update zips), `local_models.add_file` (a renamed pickle is not a .gguf),
  and the tester site `site/api/_lib/collab.js` (`scanMalicious` + `.github`/`.vscode`/binaries denied).
- `routes_security.py`, owner-only: `GET /api/security/files` (log + settings + scanner), `PUT /api/security/files/settings`,
  `POST /api/security/files/check`. Tool `check_file` for "is this safe?" in chat. Settings can turn any check off.
- Tests: `tests/test_file_guard.py` (39, incl. end-to-end through `POST /api/uploads`) + 2 in `collab.test.mjs`.
  The Windows Security path was checked for real against a harmless file; no virus signature is written to disk anywhere.
- Open, deliberately left to the file's owner: `file_guard.injection_notes(text)` inside `absorb_sources.text_from`
  (session 5575be) so fetched pages and papers get the same prompt-injection warning.

## DONE — Request Q (2026-09-17, Claude Opus 5 session 959c551b): context bar + compact context skill

- `context_budget.py`: token estimate (≈3.8 chars/token, images +1100) split into instructions / memory & skills /
  earlier summary / conversation / tool results / images, against the answering model's window (`WINDOWS` table;
  `/api/chats/{id}/context` fills in the provider's default model — Kimi's is 8k). `compact()` swaps older messages for
  one "[Earlier in this chat — summary]" system message (fast_chat role, offline extract if no model answers), keeps the
  last N word for word (starting on a user message), saves `context_summary`/`compacted_upto` on the chat
  (`chat_sessions.set_compaction`) so `ChatService.__init__` reloads from the summary; the stored transcript never
  changes. `undo()` restores. `maybe_auto_compact()` runs in `turn_runner._run` before the model loop (default on at 85%).
- Routes `routes_context.py`: GET `/api/chats/{id}/context`, POST `/compact`, POST `/compact/undo`, GET/PUT `/api/context/settings`.
- `/compact [what to keep]` client command, tool `compact_context`, built-in skill "Compact context" (skills.py).
- UI `components/chat/ContextBar.tsx` (+ chat.css) under the usage bar in both chat layouts: meter with words for the
  level, details panel (parts, keep-exactly box, auto threshold, keep-last), inline confirmation with Undo.
  Designed with /apple-design (gauges.md, feedback.md, generative-ai.md). LIVE-VERIFIED in the browser.
- Tests: `tests/test_context_budget.py` (7). FINDING for later: Nyx's own instructions + tool schema are ~12.7k tokens
  (90% of a short chat's context) — trimming the tool list per turn would make every model call cheaper and faster.

## IN PROGRESS — Request L: Research tab. Backend DONE (`research_engine.py`, `routes_research.py`, tools research /
research_status / search_papers / cite, model role `research`; `tests/test_research_engine.py` 7). UI NOT STARTED:
`panels/research/ResearchPanel.tsx` (new research box standard/deep, live job, cited report, sources with citation
styles, Paper mode, exports, Teach Nyx, paper search) + tab id `research` in tabs.ts/App.tsx.

## DONE (session ai-dev-folder-0d, 2026-09-17/18) — Request R, verbatim in `01_GOALS.md` § Request R
Every item R1–R17 is built, tested and (where it could be without the owner's keys or screen) live-checked. Open for
the owner: restart Nyx to load the R10/R15/R16 backends; allow Free Will on first open. Screen Share now looks
through the local `qwen3.5:9b` (Ollama reports "vision"), so no picture of the screen leaves the PC.
Ownership moved (2026-09-22): Screen Share (`screen_share.py`, `routes_screen.py`, `panels/screen/**`), Free Will
(`freewill.py`, `routes_freewill.py`, `panels/freewill/**`) and `components/chat/ActiveTalk.tsx` now belong to session
dc471e (Project Null N11/N14/N18: voice rework, Screen Share IDE, Curiosity). The rules below still hold.

Two sessions share this tree. Session "ai-dev-folder-0d" owns R; the other session owns L and Q. R stays out of
`research_engine.py`, `routes_research.py`, `context_budget.py`, `ContextBar.tsx`; shared files (App.tsx, server.py,
tool_setup.py, KeysPanel.tsx, ChatPanel.tsx, Composer.tsx, these handoff files) get small Edit insertions only.
Order: R17 Qwen → R9 line counts → R1–R6 Data Absorption (Data Analysis) → R7–R8 Data Process Use → R12 local
models + R13 Model Finder → R14 diagram/image overlay → R11 voice active talk (covers N) → R10 Screen Share →
R16 Apply → R15 Free Will.
- [x] R17 Qwen provider — `providers/qwen_provider.py` (Model Studio / DashScope, OpenAI-compatible; the address follows
      the key's region and is saved with it: `QWEN_API_KEY` + `QWEN_BASE_URL`, `DASHSCOPE_*` read too). Wired into
      config, router (`_PAID_PROVIDERS`, order, status), key_pool, provider_specs, model_hub (`_qwen_chat_url`),
      model_roles (alternates qwen-plus/flash/max/coder, vision qwen-vl), routes_models `_FIELDS` (key + region box,
      https://…aliyuncs.com only), routes_key_pool COMPANIES, tools `switch_model`, consult, Dashboard.
      Tests `tests/test_qwen_provider.py` (11). NOT tried against a real Qwen key — the owner has none yet.
- [x] R9 lines + file on every edit — `diff_stats.py` (exact from both versions; per file: lines affected, +added
      −removed, line ranges) → `improve_review.implement_change` step messages and outcome `lines`, `improve_deep` items,
      `code_workspace.propose` proposals. UI `components/DiffSummary.tsx` (+ diffsummary.css) in the Code tab cards and
      while it writes, Improve → What it changed, Review changes and Deep mode. Tests `tests/test_diff_stats.py` (5).
- [x] R1–R6 Data Absorption · Data analysis — `absorb_text.py` (lines, key phrases, topic model with highlights that
      learn, LaTeX/heading stripping), `absorb_sources.py` (papers via research_engine, GitHub, Wikipedia, web; SSRF-safe
      capped fetch), `absorb_engine.py` (runs auto/given/prompt, paced visible reading + parallel skimming, claims
      grounded in the document, facts → super brain `absorb:<run>:<doc>`, Q/A → Nyx Core distillation, report +
      suggestions, forget, again/deeper, storage prune, tools `study` / `study_status`), `routes_absorb.py`,
      super_brain `known_concepts` / `related_concepts` / `forget_ref`, model role `data_absorption`,
      learning_hooks → study facts reach every chat turn. UI `panels/absorb/*` (start, live board with reader →
      curved threads → topic bars, queue, dataset, coverage, gain chart, report with approval boxes).
- [x] R7–R8 Data process use — `data_tables.py` (CSV/XLSX/JSON/markdown/pasted tables, profiles, safe ast formulas,
      filter/sort/group/derive/describe/outliers/correlate/trend), `data_process.py` (read → profile → plan → compute →
      explain → suggest; resume, code, financial and document profiles; ranking with reasons; exports; tool
      `analyze_data`), routes under `/api/data-process`. Suggestions share `absorb_engine.apply_suggestion`.
      Tests: `tests/test_absorb.py` (19), `tests/test_data_process.py` (11), `tests/test_absorb_brain.py` (3).
      LIVE-VERIFIED 2026-09-17: two Wikipedia articles read on screen (threads + bars + dataset), report written by
      Nemotron with 5 approval boxes, "Add Skill" really created the skill (removed again — the owner approves, not me);
      pasted CSV → grouped table + findings + chart suggestion + skill/agent boxes.
- [x] R12 local models — `local_models.py` (Ollama status/scan, pull with progress via `/api/pull`, add a GGUF file via
      `ollama create`, remove, use as default or for a role, install Ollama via winget from the owner's button only,
      probe other local servers), `routes_local_models.py` (`/api/local-models*`), Keys → "Local models"
      (`panels/LocalModelsSections.tsx`). Tests `tests/test_local_models.py` (12). This PC: no Ollama yet, RTX 5080 16 GB.
- [x] R13 Model Finder — `model_finder.py` (13-provider catalogue, OpenRouter's public zero-price list, deep web search
      judged by a model; every result has the page to get a key), `/api/model-finder*`, bottom of Keys. "Use This
      Above" pre-fills the custom-model form.
- [x] R14 diagram / picture overlay — `diagram_engine.py` (spec cleaning, self-portrait built from the live roster,
      tools, model roles, skills, brain and core; 1 model pass, 2 for big asks; Openverse → Wikimedia pictures; saved in
      `data/diagrams`), `routes_diagram.py`, tools `show_diagram` / `show_image`, `/diagram` and `/showimage` commands (not `/picture`: that word leads to `/image`),
      `components/diagram/DiagramOverlay.tsx` (portal over the whole window, group columns with headings, long lines on
      lanes above/below, Zoom to Fit / Actual Size, Draw with pens/eraser/undo, Save PNG, Save PDF, Put In Chat).
      Tests `tests/test_diagram_engine.py` (8). LIVE-VERIFIED: "/diagram how you work" draws 26 boxes from this install.
- [x] R11 active talk — `components/chat/ActiveTalk.tsx` (continuous recognition, sends after 1.15 s of silence, queues
      while busy, barge-in, speaks the steps and the answer), Talk switch in the chat bar, fastest available provider
      (ollama → groq → nvidia → gemini), `routes_live` `voice: true` adds a spoken-answer note to the turn context.
      Tests `tests/test_voice_mode.py` (3). Microphone not exercised in the preview pane.
- [x] R10 Screen Share — `screen_share.py` (one session in memory; share a screen or ONE window — PrintWindow sees
      it behind Nyx; frames never saved; idle stop 15 min; the page stops it on leaving the tab; local Ollama vision
      first (qwen2.5vl/gemma3/llava…), the online `ui_pointing` model only after "Allow for This Session"; one
      proposed step at a time, expires in 2 min; Show Me = Nyx's own cursor only (`computer_control.point_at`), Ask
      First = one approved click/type/keys/scroll; no typing secrets, keys from an allowed list, caution on
      irreversible words; corner / Esc×3 / Stop still abort), `routes_screen.py` (`/api/screen*`, owner-only, Stop
      open to chat), tab `screen` (`panels/screen/ScreenSharePanel.tsx` + screen.css). Tests
      `tests/test_screen_share.py` (12). LIVE-VERIFIED: sharing screen 1 streams frames (~170 ms each), window
      capture 131 ms and not blank, leaving the tab stops sharing. No question about the owner's real screen was
      sent anywhere. 2026-09-18, once Ollama + qwen3.5:9b arrived: the local model is picked from Ollama's
      `/api/show` capabilities (its name does not say "vl"), called directly with `think: false` + `num_predict 700`
      (6.7 s cold, 2 s warm) and given a faint 0–1000 grid on its copy of the picture (`grid_overlay`); points are
      asked for as `{"x", "y"}` (Qwen writes [x, y], Gemini [y, x]). On a synthetic spreadsheet it found the right
      column every time and the right row 2 times out of 3 — the owner sees the marker before any Do It.
- [x] R16 Apply tab — `apply_engine.py` (a request + uploads + links → read pictures for LAYOUT via `image_check`,
      documents via `absorb_sources`; for visual asks the local Apple HIG library (`connectors/apple_design_connector`)
      + general design principles + Nyx's design skills; optional web search; the plan comes from `code_generation`,
      at most 5 changes, each vetted: tab (a validated `dynamic_tabs` spec — data), skill / agent / agent_feature
      (`absorb_engine.apply_suggestion`), code (Python only, `self_patch.resolve_target`, protected files refused →
      `CHANGE_LOG` + `REVIEW_QUEUE.approve(implement=True)`: sandbox tests + critic + rollback), ui (an existing
      TSX/CSS file under `frontend/nyx-pulse/src`, written as a `code_workspace` diff first, applied only on Apply,
      Undo restores it; "Rebuild the App" runs `npm run build`). Nothing lands until the owner presses Apply on a box.
      Jobs kept in `data/apply/jobs.json` (30). `routes_apply.py` (`/api/apply*`, owner-only), tab `apply`
      (`panels/apply/*`). Tests `tests/test_apply_engine.py` (10). LIVE-VERIFIED: "Add a tab for tracking my study
      hours…" → Nemotron planned a Study Tracker tab (timer + chart) from Apple's charting guidance, Nyx's two design
      skills and a web search; left un-applied for the owner to Apply or Skip.
- [x] R15 Free Will tab — `freewill.py`: consent on first open (`data/freewill/state.json`), pause, opinions of its own
      (`form_opinion` / `my_opinions`, only inside Free Will turns; `data/freewill/opinions.json`, revisions kept,
      erase one / all), the turn note (freer voice, "agent decides", what it already thinks) and a DENY-BY-DEFAULT guard
      checked in `tools.call_tool` via `ToolContext.guard` (set by `turn_runner` from `service.tool_guard`): web,
      general, learning + pictures, diagrams, new tabs, `propose_idea` allowed; files, computer, windows, shell, code,
      email, clipboard, apps, trading orders, settings, agents, memory writes, `improve_self` refused.
      The chat is `/api/chat/stream` with chat id `__freewill__` (internal store, not in the chat list);
      `routes_live.start_turn` refuses it until allowed and for non-owners. `routes_freewill.py` (`/api/freewill*`),
      tab `freewill` (`panels/freewill/*`: consent sheet, chat with live steps, opinions, the guard). Tests
      `tests/test_freewill.py` (8). UI checked against simulated responses: the owner's running launcher predates this
      backend and was not restarted.
- Auth lists: `tests/test_server_auth.py` now refuses anonymous + beta callers on every new owner-only R route and on
  a beta tester's Free Will turn.

Found while verifying R1–R8 (all fixed, each with a test): reasoning models spent their whole budget thinking before the
JSON (system now starts "detailed thinking off"), a model echoed the JSON template as "facts" (every kept fact must now
share 60% of its words with the document — `_grounding`), replies cut off mid-JSON are salvaged, Wikipedia LaTeX and
`== headings ==` are stripped, a pasted CSV was read as prose (`data_tables.looks_tabular`), and a model naming a
computed column "units_sum" when it is "sum of units" now matches.

## NEXT GOALS, in the owner's order: K → L → M → N → O → P (verbatim in `01_GOALS.md`)

- [x] K DONE 2026-09-16 — Collab. Website `site/collab/index.html` (live list, refresh 30 s, filters, search, send
      files/feedback with a NYX1- access key) + Vercel functions `site/api/collab/{feed,submit,verify}.js` (shared
      `site/api/_lib/collab.js`: Ed25519 key check with public keys from env, path deny-list, size limits, secret scan,
      10/h limit, branch `beta/<tester>/<slug>-<id>` + PR labelled `beta-change`, feedback → issue `beta-feedback`,
      never merges). Nyx side: `beta_collab.py` (candidates: Improve-applied code, Code-tab edits inside Nyx, tabs,
      skills, agents; preview + local secret scan; send; feed), `routes_collab.py` `/api/collab/*`, Collab tab
      (`panels/CollabPanel.tsx`, tab id `collab`). Tests: `tests/test_beta_collab.py` (10, incl. Node tests and a
      Python-signed key verifying in Node). LIVE-VERIFIED against a local fake GitHub: key check, feedback sent → issue,
      feed updated itself; Nyx tab listed 10 real candidates and the feed. NOT DEPLOYED: owner steps in
      `docs/COLLAB_SETUP.md` (GitHub fine-grained token, branch protection, `beta_collab.py --vercel-env`, Vercel env).
- [ ] L Research tab: standard + deep research, citations, paper publishing mode, search/read research papers, research
      feeds Nyx's training. Builds on `web_access.py`, `sources.py`, `super_brain.py`, `nyx_core.py`, `study_tools.py`.
      NOTE: a dynamic tab named "research" already exists in the owner's tab bar (made in chat) — check it first.
- [ ] M Keys & Models: a job for the 3D model center with several models working together; Ollama running several
      copies offline for heavy work; download offline models on request (`ollama_setup.py`, `providers/ollama_provider.py`).
- [ ] N Voice Conversation switch: hands-free (talk → answer aloud at once → listen again), and it talks while it thinks.
      Builds on `voice/voicePlayer.ts`, Composer dictation, `tts.py`.
- [ ] O Tab creation/editing: more freedom, less default-template, buttons/lists/talk-to-AI blocks, many examples,
      apple-design skill. Builds on `dynamic_tabs.py`, `tab_editor.py`, `spec_ai.py`, `panels/DynamicTab.tsx`.
- [ ] P Local models of any size: detect "too big" → AirLLM-style layer-by-layer loading from flat per-layer files, flash
      attention, only at the highest power setting, OFF by default. Builds on `resource_governor.py` (power modes),
      `providers/ollama_provider.py`, `nyx_core.py`; needs an optional dependency decision (torch/transformers/airllm).

## DONE — Request J (2026-09-16, Claude Opus 5). Verbatim + root causes: `01_GOALS.md` § Request J

- [x] J1 `model_roles.fallback_candidates`: same-provider alternates (`_ALTERNATES`, filtered by a cached catalog),
      every configured provider, the owner's custom models; models that failed moments ago go LAST instead of being
      skipped; 429 → 60 s cool-down; 401/402/no key → skip that provider; 404/410 → benched a day; ≤10 calls.
      Image generation keeps its old skip rule (a 504 costs 25 s). Model-role calls now count in `GLOBAL_METRICS`.
- [x] J2 Why auto-approve never worked: the critic saw an empty diff and blocked 94/101. Now (autopilot and review queue
      share `improve_review.implement_change`): duplicate check (offline; `counts_as_decision` ignores the old critic's
      refusals) → research (`file_excerpt` reads the target, optional web, model verdict JSON; reasoning models' thinking
      is skipped, "detailed thinking off"; no readable verdict = no recommendation) → approve → `self_patch.prepare`
      (edit + sandbox tests; a red run is re-run without the edit and only NEW failures count; warnings off; -x off) →
      one retry with the error as feedback → critic reads the REAL diff → `self_patch.commit`. Engine dedupes at filing and
      tells the model the known titles. Study replies: 3000 tokens + cut-off JSON salvage (it said "Nothing new to learn").
      "Apply all"/"approve these"/"deny duplicates" typed in Improve or said in chat → `review_intent` → review queue.
- [x] J3 Improve → Review changes (`panels/improve/ReviewQueue.tsx`, `/api/improve/review*`, `/api/improve/changes/{id}/
      approve|deny|implement`): filters, select + bulk, Analyze All (+web), Apply Recommendations, Let Nyx Decide and
      Apply (confirm), Deny Duplicates, job progress/log/Stop, per-change research + implement state, and the
      "Implement approved changes" switch explained in place (Off = "approved only", Implement Now later).
      LIVE 2026-09-16: 748 open → 704 duplicates, 37 need a decision; one real change researched → approve, low risk.
- [x] J4 Deep & specific (`improve_deep.py`, `/api/improve/deep*`, `panels/improve/DeepMode.tsx`): big box, offline
      plan + estimate while typing (items, guessed file, kind, minutes), tries per item, apply-when-green, take longer
      if needed (extends the budget or stops and leaves the rest in review). UI items are filed, not auto-applied
      (self_patch edits Python only). LIVE: 4 items → ≈ 1 h 9 min estimate.
- [x] J5 Add a model: URL box for every company (overrides its address), base URLs completed, `localhost:1234` → local
      server with no key (`allow_local`), Check button (`/api/custom-models/check`: /models list + 1-token call, says
      "Nothing answered" when nothing is there). LIVE-VERIFIED.
- [x] J6 Agents are / commands (`commands.agent_commands`, kind "agent"); `/coder [3] task` or `/coder` + Enter opens
      `DispatchSheet` (portal) with a box per copy; `agent_dispatch.DISPATCHES` runs copies in parallel (≤12 boxes,
      ≤8 per agent, Power-bounded), each copy is told the others' parts, + another box while running, Stop, results
      written into the chat (`chat.appended`). Chat shows a live tray of dispatches. `/api/dispatch*`.
      LIVE: 2× Coder answered "OK"/"YES" in 1.5 s/2.7 s; slash menu + sheet verified.
- [x] J7 `agent_match.py`: offline scoring (name ×3, expertise ×2, goal ×1, aliases, made-agent bonus, no small talk) →
      "[Sub-agent match]" system note + full pipeline + `agents.suggested` event; Manager prompt tells it to bring agents
      in and to create_agent for recurring needs; tool `dispatch_agents` (count/tasks/agents); `made_by` nyx/owner shown
      in Sub-agents tab ("Run Copies"), Core view, slash menu.
- [x] J8 Core view (`components/brain/CoreView.tsx` + `core.css`, `routes_core.py` `/api/core/overview`): three.js core
      + particle field that brightens while thinking/speaking, top light arc, gauges (CPU, memory, GPU, Nyx process),
      APIs (calls, ok %, latency, sparkline, limits, key health), Markets (Trading watchlist), Sub-agents (drag, Run, +
      make, filter), Processes (turns, autopilot, analysis, review, dispatches), Project dock (project picker: Code
      folders + Build projects; boxes; Run), voice channel waveform, status line. LIVE-VERIFIED in the browser.
- [x] J9 `handoff_tools.py`: tool `read_handoff` (current, goals, howto, stopped, all, search) + `/handoff` command.

Tests added: `test_improve_review.py` (14), `test_improve_deep.py` (7), `test_agent_dispatch.py` (8), plus new cases in
`test_model_roles.py`, `test_self_patch.py`, `test_improve_autopilot.py`, `test_routes_providers.py`. Full suite: 1394+
passed (2026-09-16). NOTE: the owner quit Nyx at 16:22; Claude verified with a preview server on port 8000 and stopped it.

## PREVIOUS GOAL — Request H (2026-09-15, after the usage reset). Verbatim + table: `01_GOALS.md` § Request H

Owner's words: "These are the main things to fix". MAIN FOCUS = H1 (Code tab folder picker). Finish with a new handoff.
Order: H3 → H9 → H11 → H6 → H1 → H12 → H2 → H8 → H13 → H15 → H10 → H17 → H16 → H4 → H5 → H7 → H14, then G2 UI, G10.
- [x] H3 `ToolRegistry.call_tool(self, name, /, **kwargs)` — `name` positional-only. Tools with their own `name`
      argument (create_agent, update_agent, notes…) crashed the whole turn; this is also why "make a sub-agent" never
      created one. `turn_runner` now turns any tool exception into a tool result instead of ending the turn.
- [x] H9 Causes fixed: (a) `useTurns` kept no handle on a finished local turn, so its fold could be skipped → now
      `lastTurnId`; (b) `ChatPanel.loadChats` could jump a brand-new chat to the server's "active" chat mid-turn → keeps a
      chat with a running turn, and moves to the real chat id at `turn.start`; (c) switching back to a chat kept a stale
      transcript → server copy wins when it has more messages; (d) backend: an answer written *before* a tool call was
      wiped by `answer.reset` and the last step said "Saved." → `_tool_loop` keeps `written_before_tools` (≥400 chars).
- [x] H11 `key_pool.py`: a key is "needs payment" only when its API said so (402 / insufficient_quota / credit balance;
      a free-tier 429 is `quota`, not payment). Providers now surface the API's own message (`providers/base.api_error_detail`,
      no retries on 400/401/402/403/404). Picking a billable provider yourself = consent (`model_choice.allowed_paid`,
      `Router.unavailable_reason(explicit=True)`); free-only still keeps un-picked ones out of automatic fallback.
- [x] H6 (a) the chat's fallback toast no longer moves the model menu to the stand-in (that WAS the "keeps going back to
      Gemini"); (b) the pick survives restarts (`model_choice.py` → `data/model_choice.json`, applied in config.py);
      (c) recently failing providers drop behind healthy ones for 5 min; (d) Gemini is now the "other model" consultant
      on hard questions (`consult.py`) instead of the default answerer.
- [x] H1 `native_dialogs.py`: Windows IFileOpenDialog via ctypes (FOS_PICKFOLDERS|ALLOWMULTISELECT), no owner window (an
      owned cross-process dialog freezes the browser), centred on the monitor you clicked from, raised to the front
      (AttachThreadInput; taskbar flash fallback). `POST /api/code/pick-folders` (loopback only). Code tab "Open Folders…"
      + opened-folder list with close. LIVE-VERIFIED: dialog appeared centred on the 2nd monitor, in front; OK → folder opened.
- [x] H12 `code_workspace.create_file/create_folder/start_project` (starters: empty, python, website, node, arduino),
      `propose_files` (new files for an empty folder → review → Create Files → Undo removes them). Routes new-file,
      new-folder, templates, start, propose-files. UI: New File / New Folder in the tree, Start From Scratch sheet,
      "Build Files" when no file is open. LIVE-VERIFIED new file + starter folder (test folders deleted).
- [x] H2 H3 fix made "make a sub agent…" work (LIVE: created). Agents gain purpose, consult (off/heavy/always),
      consult_with, consult_models (same/other/both); `create_agent` takes provider/model/purpose/consult. `consult.py`
      seats: same model fresh look + strongest other model + named agents, parallel, 25 s budget; used by the Manager
      turn (its own Properties) and by specialists. `GET /api/agents/details`, `POST /api/agents/subagents` (+ task),
      `DELETE /api/agents/subagents/{name}`. UI: `SubAgentsPanel.tsx` (tab `subagents`), `AgentDetails.tsx` ("Details" next
      to Team (N)), consult fields in Properties. LIVE-VERIFIED: details sheet, edit+save, heavy question consulted nvidia.
- [x] Launcher restart race: successor waits up to 60 s for the old engine to let go (it gave up at 20 s and left Nyx down).
- [x] H8 `key_pool.py` (fingerprints only; failed key skipped, retried every 5th request; alert after ≥3 fails over
      20 min; `resolve(drop|keep)` removes only that key) + router key failover (`key.failover` event). `routes_key_pool.py`:
      `/api/keys/{p}/pool` GET/POST/DELETE, `/api/keys/alerts` + answer, `/api/custom-models` (name, company from
      COMPANIES table of OpenAI-compatible URLs, model, key, special use, free flag). UI `panels/KeyPoolSections.tsx`
      (KeyAlerts banner, KeyPool per provider, CustomModelsSection) in Keys & Models. LIVE: nvidia shows env key ✓ +
      stored key ○. Tests in `tests/test_key_pool.py`, `tests/test_routes_providers.py`.
- [x] H13 `commands.find_inline/brief_for`: known /commands anywhere (not paths/URLs), skills' full instructions inserted
      FIRST in the turn's system context, status "Reading /x, /y first", forces the full pipeline. Composer: inline "/"
      menu at the caret inserts the name; "Nyx reads /a, /b first" line. LIVE-VERIFIED.
- [x] H15 `sources.py` (clean links, titles, dedupe; saved on the chat message as `sources`); runner collects from tool
      results + url arguments; `done.sources`. Bubble "Sources (N)" disclosure with numbered links (new tab, noopener).
      Remote https images render through `GET /api/image-proxy` (https, public IPs re-checked per redirect, raster only,
      ≤8 MB). NVIDIA's `【tool†L1-L4】` marks stripped. LIVE-VERIFIED.
- [x] H10 ```chart JSON blocks → `ChartBox.tsx` (line/bar/scatter/area + function plots via a safe arithmetic parser,
      markers+dashes, numbers table); ```python → `PythonBox.tsx` (edit, copy, Save .py, Explain, Check for Bugs —
      NO run: AGENTS.md §7 forbids executing LLM-generated code; ask the owner before adding a sandboxed runner).
      System prompt rule 10 teaches the chart format. LIVE-VERIFIED: "Graph sin(x) and x^2/10" drew.
- [x] H17 `components/QuitButton.tsx`: "Log Out" (blue fills left→right on hover/focus) → centred alertdialog (band
      fills on open, primary fills bottom→top, Cancel focused) → `/api/engine/stop` + sign-out → "Nyx has stopped".
      LIVE-VERIFIED quit (port closed, tray gone) and restarted via launcher.
- [x] H16 tab editing freedom: the existing validated tab specs now render in the UI — safe colour/gradient/image
      backgrounds, themed cards, real lists/charts/trackers, countdown/stopwatch timers, user-confirmed AI actions,
      tic-tac-toe/connect-four competition, and memory/snake games inside the tab. Built and live-verified; the
      temporary verification tab was removed afterwards.
      Also this session (same request): Tab specs gained `background` (colour/gradient/uploaded picture/https picture, dim, blur) and `theme`
      (surface solid|glass|clear, font, text colour, radius), plus block types chart, tracker, timer, ai_task,
      competition, game — all validated data (`dynamic_tabs._clean_block_config`). The tab Edit panel got direct
      controls (`panels/tabs/TabLook.tsx`): one-click Add a block, look presets, colour, picture upload, dim, text-box
      surface and font. NOTE: another agent implemented the block *renderers* in `panels/DynamicTab.tsx` during the same
      session; this session's duplicate `panels/tabs/TabBlocks.tsx` was deleted and TabLook wired into their panel.
      Tests: `tests/test_tab_freedom.py`.
- [x] H7 `google_oauth.py`: Google sign-in instead of app passwords (PKCE + single-use state, loopback callback,
      refresh token in secret_store, IMAP/SMTP XOAUTH2 in `email_client`). `/api/google/oauth/{status,client,start}`
      owner-only; `/api/google/oauth/callback` public (in `PUBLIC_PATHS` + `tests/test_server_auth.py`), loopback-only,
      state expires in 10 min. UI: Keys & Models → "Gmail with Google sign-in" with the three Google Cloud steps.
      Tests: `tests/test_google_oauth.py`. NOT tried against a real Google client yet — the owner has to make one.
- [x] H14 `intent_md.py` — Anthropic's intent.md (problem, proposed outcome, affected users and systems, constraints,
      open questions). Built-in skill "Capture intent" (analyst questions first), `/intent` command, Start From Scratch
      writes an intent.md, and Code-tab proposals read the nearest intent.md as context.
- [ ] H4 Build tab (NOT STARTED — see CODEX_HANDOFF.md §1)
- [ ] H5 Game Studio tab (NOT STARTED)

### Request I (same day, sent while H was being built) — verbatim in `01_GOALS.md` § Request I

- [x] I1 `storage_budget.py`: code backups ≤150 MB/30 days (newest 20 kept), voice cache ≤50 MB, learning logs ≤20 MB each
      (newest lines kept), extra chats.backup-* pruned to 3, brain.db VACUUMed when ≥25% free pages — never deletes
      memories, uploads or chats. Runs 60 s after start, then daily. `GET /api/storage`, `POST /api/storage/clean`,
      `DELETE /api/storage/leftovers/{key}` (fixed list only). Settings → Storage shows sizes + Remove… per leftover.
      MEASURED 2026-09-15: 666 MB total; ~17 MB grows with use; 275 MB of old build leftovers listed for the owner.
- [x] I2 `components/brain/AgentCity.tsx` (three.js): Manager spire centre, built-ins inner ring, made-in-chat agents
      outer ring; floors = tasks done (grows as it works); working agents get a pulsing green beacon; new buildings rise.
      Drag/scroll/arrow keys, click a building → its goal, model, current step and its finished tasks as floors, plus
      Open properties. Toggle "Memory field | Agent city" in the Nyx stage (`nyx.stage.view`). LIVE-VERIFIED.
- [x] I3 `content_mode.py`: `data/content_mode.json`, system-prompt line when on, image prompts checked before any model
      call. Four hard limits stay in both modes (minors, real people, force/no-consent, illegal) — `refusal_for()`.
      Settings → Content states them on screen. `GET/PUT /api/content-mode`. Tests: `tests/test_content_mode.py`.
- [x] I4 A chat can belong to one agent: `chat_sessions.set_agent/agent_for/chats_for_agent` (+ `agent` in summaries),
      `TurnRunner._answer_as_agent` routes every message there to `run_specialist` (report wrapper stripped by
      `_as_conversation`), `POST /api/chats/{id}/agent`, `GET /api/agents/{name}/chats`, and `POST /api/agents/subagents`
      takes `start_chat`. Sub-agents tab: "Just create it / Start a task now / Open its own chat" + Give It a Chat +
      its chats listed; ChatPanel shows "This chat belongs to X" with Hand back to the Manager. LIVE-VERIFIED.
- [x] I5 City drag reversed (drag right → the city turns right), arrow keys to match.

### Still open after H and I

- [ ] H4 Build tab, [ ] H5 Game Studio — the two big unbuilt tabs (`CODEX_HANDOFF.md` §1 has where to start).
- [ ] G2 Settings → Updates panel (backend done), [ ] G10 beta-tester site (do last; never link site/downloads).
- Ask the owner: run `extensions/vscode-nyx/install.ps1`? Remove the 275 MB of leftovers listed in Settings → Storage?
  Add a sandboxed Python runner as a written exception to AGENTS.md §7? The Kimi key answers 401.

## PREVIOUS GOAL — Request G (2026-09-15). Verbatim + status table: `01_GOALS.md` § Request G

Root causes found before coding (so nobody re-investigates):
- G9 dropdown: `useTurns.send` never sent the picked provider; `StreamRequest` had no `provider` field. Chat
  "switch to X" worked only because the `switch_model` tool sets `SETTINGS.preferred_online_provider`.
- G11 leak: a failed turn left its user message in `conversation_history` looking like pending work, so the
  next turn ("sweitch to nvidia") did both. Empty answers: `parse_tool_calls` dropped `<tool_call>` blocks
  with Windows paths (`C:\Users` = invalid JSON escape) or no closing tag → `visible_answer` → "" →
  "I did not get a usable answer back". Raw `<tool_call>` text was also saved as replies (chat 83c9e4ff).
- G4 hard-to-read names: the Nyx sheet used a native `<select>` whose popup painted light text on the
  near-transparent select background.

Order (tick as you go): G3 → G4 → G9 → G11 → G15 → G17 → G16 → G5 → G12 → G6 → G8 → G13 → G7 → G1 → G2 → G10.
- [x] G3 brain drag x-axis (`BrainField.tsx` `theta += dx`; arrow keys left as they were)
- [x] G4 `ChatSwitcher.tsx` (pop-up menu #F5F5F7 on #15151C, search >7 chats, ✎ rename; AI naming kept via
      `title_locked`); native `<option>` colours fixed globally in `chat.css`. Browser-verified.
- [x] G9 `StreamRequest.provider` → `TurnRunner(provider=)` → `router.stream(prefer=, exclude=)`;
      `router.unavailable_reason()`; `/api/models/switch` accepts any router provider and 409s with the reason;
      `GET /api/models/active`; events `provider.fallback`, `model.switched` (from `switch_model`); ChatPanel
      `pickProvider` + once-per-turn effect moves the dropdown. `routes_providers._resolve_key` now sees Gemini's key
      (dropdown said "gemini (no key)"). LIVE-VERIFIED 2026-09-15: dropdown→nvidia answered; "switch to gemini" →
      only switched, dropdown followed; claude/openai → "Can't switch… paid provider and free-only mode is on".
- [x] G11 lenient `parse_tool_calls` (`_loads_lenient`, unclosed blocks), repair loop in `_tool_loop`
      (`_MAX_REPAIRS`), `FAILED_TURN_NOTE` + system-prompt rules 8–9, Gemini "reasoning only" and compat
      "no content" now raise `ProviderError` so the router falls back. Tests `tests/test_turn_runner.py`.
- [x] G15 New chat = one empty chat (useTurns transcript keyed by chat id); `chat_sessions.duplicate/branch`
      (+ fork kind), routes `/api/chats/{id}/duplicate|branch|fork`, `chat_tools.py` (chat_new/duplicate/branch/
      fork/rename, `chat.created` opens it), `ChatActions.tsx` "⋯" menu, message "Branch" button. Browser-verified New.
- [x] G17 Nyx sheet width: drag grip / arrow keys / double-click reset, Expand/Shrink, `--sheet-w`, remembered.
- [x] Launcher restart fixed (`CREATE_BREAKAWAY_FROM_JOB`; successor died with the logon task's job).
- [x] G16b `components/AgentProperties.tsx` (objective, provider+model w/ catalog, instructions, expertise, tools, give a
      task, recent work) from the Team dock ⓘ, Agents tab "Properties", agent chips. Backend: `agent_runtime.update_agent/
      agent_properties` (built-ins → `data/agent_overrides.json` overlay; made-in-chat → custom_agents.json), tool
      `update_agent`, `GET /api/agents/{name}/properties`, `PATCH /api/agents/{name}`; specialists really use their model
      (`router.stream(prefer=, prefer_model=)`, compat providers take a per-call model). Browser-verified.
- [x] G5 `commands.py` (built-ins, skills as commands, owner commands in data/commands.json, rank + synonyms, guess via
      `mini_model.race` 4 s → offline suggestion), routes `/api/commands` GET/POST/DELETE, `/api/commands/guess`;
      `SlashMenu.tsx` above the composer (↑↓ Tab Enter Esc), "Make /xyz", "Create a skill instead" (opens Add capability
      with the words via `nyx:open-tab` + sessionStorage), "Send as a message". Browser-verified.
- [x] G12 `turn_advice.py` (rules + 3 s mini model), `POST /api/turns/advise`; Composer split button with Nyx's pick
      + menu; ChatPanel queue (flushes when `!busy && !sending`), interrupt (stop + first in queue), parallel (fork +
      background stream + "Answer ready" toast), branch (branch + switch; useTurns keeps a local turn with its own chat).
      LIVE-VERIFIED queue: second message sent itself after the first answer.
- [x] Also: `mini_model.py` races small models (Gemini flaky/NVIDIA 503 on 2026-09-15); prompt optimizer uses it
      (was 10 s sequential); fast path no longer shortens explicit lists ("1 to 40" stopped at 18).
- [x] G6 `usage_limits.py` (x-ratelimit/anthropic headers, Gemini 429 QuotaFailure → counted daily, DeepSeek/Kimi
      balance), hooked into compat/openai/gemini providers + model_hub; `GET /api/usage/limits?provider=`;
      `components/UsageBar.tsx` in both chat layouts, hidden when empty. Live: none of the owner's providers report
      limits yet (NVIDIA sends no headers; Kimi key answers 401 Invalid Authentication — tell the owner).
- [x] G8 `backgrounds.py` (upload image/GIF/MP4/WebM or `generate()` → image_gen wallpaper prompt; motion presets
      still/drift/breathe/parallax/embers/time picked from the words; dim/blur), routes `/api/backgrounds*`, tool
      `set_background`; `components/BackgroundLayer.tsx` (fixed layer, `has-custom-bg` class), Settings → Background
      (`panels/BackgroundsSection.tsx`); BrainField canvas goes transparent with a background (alpha follows brightness).
      LIVE-VERIFIED with a Pollinations picture + time rings (test item deleted afterwards).
- [x] G13 Notes tab (`panels/notes/`: NotesPanel, DrawingPad, StudyViews, speech.ts, notes.css; tab id `notes`, pinned).
      Backend `notes_store.py` (notebooks, notes, quizzes/decks/steps/drawings), `study_tools.py` (role `study_notes`:
      detail, organize, summarize, clean, glossary, study_guide, exam, ask, cite, study_plan; quiz/flashcards/steps JSON →
      validated specs; `read_drawing` via image_check; short-answer grading via mini model), `routes_notes.py`
      (`/api/notes*`, tools notes_search/read/create/study). Lecture = Web Speech API, audio never stored (keepAlive
      restarts). Focus timer. LIVE-VERIFIED: Quiz Me → 10 questions in 5 s, checking works (test note deleted).
- [x] G7 `code_workspace.py` (opened folders/files only; chunked reads; propose = search/replace blocks validated to
      match once → unified diff, nothing written; apply with hash check + backup in data/code_backups; undo while
      unchanged; CRLF kept; ask), `routes_code.py` (`/api/code/*`, owner/loopback only, blocked on hosted builds),
      `panels/code/CodePanel.tsx` (tree, search, editor ≤300 KB, virtualised viewer for huge files with line
      selection, Propose/Explain/Use in Chat, diff cards Accept/Reject/Undo), `extensions/vscode-nyx/` (plain JS:
      Edit with Instruction → vscode.diff → Accept applies via WorkspaceEdit; Ask; Chat webview; Open in Nyx; Sign In;
      `install.ps1` copies to ~/.vscode/extensions — NOT run yet, ask the owner). API calls to models get 120 s
      (`api.post(..., timeoutMs)`). LIVE-VERIFIED: Nemotron proposal in 10 s → Accept wrote → Undo restored.
- [x] G1 `trading/` (store, market via FinanceConnector, brokers: Paper simulator / Alpaca REST paper+live / SnapTrade
      aggregator with HMAC-signed requests + connection portal — SnapTrade & Alpaca UNTESTED against real keys; guard:
      live switch needs typed "I understand this uses real money", AI budget (per trade, max invested, trades/day,
      loss stop, allowed symbols, market hours), approvals (default always, 15-min expiry), AI may only sell what it
      bought, Halt, audit log; signals: SMA/momentum/RSI/volatility/volume with reasons + graded track record;
      autopilot: schedule thread, research budget → search_web + fast_chat model VERDICT OK/AVOID). `routes_trading.py`
      (`/api/trading/*`, owner/loopback only, hosted-blocked), tools trading_status/signal/order (category `finance`,
      restricted for invited accounts). `panels/trading/TradingPanel.tsx` (approvals first, KPIs + budget meter,
      watchlist w/ sparklines + reasons, ticket, positions/orders, AI rules, accounts, live switch, activity log).
      Tests `tests/test_trading.py` (7). LIVE: signals from Yahoo render; no order was placed.
- [ ] G2 beta update channel (reviewed branch → testers)
- [ ] G10 beta-tester site (`site/beta/`)
- [ ] G14 keep `CODEX_HANDOFF.md` current

## PREVIOUS GOAL — Request F (2026-09-14)

Project: `C:\Users\shagn\Desktop\Ai Dev Folder\Ai Dev Folder\` · Engine: http://localhost:8000
(started by the tray launcher; restart after Python changes with
`curl -X POST http://127.0.0.1:8000/api/engine/restart`).

## CURRENT GOAL — Request F (2026-09-14 night). Verbatim + status table: `01_GOALS.md` § Request F

Plan, in order (tick as you go; each item ships backend + tests + UI + a live check):

- [x] F8 Nemotron 3 Ultra on NVIDIA (catalog, aliases, notes; verified live). ALSO FOUND: NVIDIA retired
      `meta/llama-3.3-70b-instruct` (410 Gone since 2026-08-26) — it was the NVIDIA default and the `code_generation`
      role. Now `nvidia/nemotron-3-super-120b-a12b` (1.0 s); `model_roles` falls back to the same provider's default
      and benches a retired model for 24 h (a 503 for 90 s).
- [x] F1 Improve autopilot — `improve_autopilot.py` (runs from words: phases study/improve/detox/rest, loops, time
      window, auto-approve window; controls.json the AI extends), `self_patch.py` (approved change → model edit JSON →
      sandbox copy + tests → apply only on green, exact rollback; protected files), tools `improve_schedule`,
      `improve_stop`, `improve_add_control`, `improve_set_control`; routes `/api/improve/autopilot*`, `/controls*`,
      `/changes*`; Improve tab rebuilt (console, presets, live run, controls, lessons, diffs + Roll back); runs resume after
      restarts. Tests: `test_improve_autopilot.py` (17), `test_self_patch.py` (7). Live: study cycle wrote a real lesson.
- [x] F3 Prompt optimizer — `prompt_optimizer.py` (sensor keep/expand/polish, rules offline, online model with
      8 s budget, checker, overlay "owner's words first"), wired in `turn_runner._optimize_prompt`, 👎 teaches it,
      Settings → Prompt refining (+ Try it), chat bubble "Expanded your request" with "Stop refining". Tests (19).
- [x] F6 Super brain + Nyx Core — `super_brain.py` (SQLite + FTS5; seeded 29k nodes / 214k links on first start; every
      turn, tool result, lesson), `nyx_core.py` (growing numpy MLP 12→512 wide, up to 4 layers; word model; crutch ledger;
      distillation set; levels Seed→Frontier), `intelligence_tools.py` (brain_recall/remember/study_folder, nyx_core_status),
      `routes_intelligence.py`. Offline turns answer from memory. Tests: `test_super_brain.py` (11).
- [x] F10 (first pass) Black theme (`theme.css`, `nyx.css`), Nyx tab = `BrainField.tsx` (three.js, 1 draw call, live
      impulses, cluster tags + threads) + `NyxPanel.tsx` (HUD, search, node inspector, chat sheet, voice auto-speak,
      dictation + predictive text in Composer) + `LearnPanel.tsx` (level, live network, charts w/ table views).
      Browser-verified. Debug hook `window.__nyxBrain` (size/alpha/lines) for tuning the field.
- [x] F4 Predictions — `predictor.py` (next-tab Markov by daypart, usual hours, model hints via Nyx Core; IdleScheduler:
      one Nyx-made tab/day, GitHub update check/install (clean tree only), daily detox hour in quiet hours),
      `/api/predict*`, `/api/updates*`, presence heartbeat from the UI, "Next: …" shortcut, Settings → Predictions.
      Tests: `test_predictor.py` (9).
- [ ] F7 Providers with uses — any new provider, name + uses (text/vision/image/OCR/all), by the owner or Nyx.
- [ ] F2 3D design tab — `design_studio.py` (projects, parts, netlist, rule checks, long generation jobs) + three.js editor.
- [ ] F5 VS Code extension — `extensions/vscode-nyx/` (plain JS, no build) + `code_workspace.py` live edits.
- [ ] F9 GitHub + Vercel + web mode — secret scan, push `origin main`, Vercel from GitHub, hosted site runs the web app.

## Previous owner request (2026-09-14, verbatim)

```text
Antigrav made a folder for you with what it ahs done
Also get the dev for adding API keys for multiple things. Allow image gen, image and file intake and more, and make sureree I can input different mdoels and have boith me and the AI say its use likle if I give an AI model from bnvidia for image ccheck or a AWS one for reading text. [/goal] Hello, Claude has done alot. Use this site and link to this for when online. Allow to generate the APi keys it has here, no cost: https://build.nvidia.com/models   . Use this githuib for deigns and also allow the AI to access for their design skills so abscially both you and my AI access this guthub and all in it for the best apple based sdesigns: https://github.com/dickwu/apple-design-skill. Run and fix these thuiings and find more stuff to add until Usage runs out and make a fodler that claude will for sure find so it know what to do next
```
All earlier requests: `01_GOALS.md`.

## What happened in the last sessions (so you don't redo it)

- **Antigravity (2026-09-13 ~21:45–21:56, died on a 429)** added: `providers/nvidia_provider.py`
  (NVIDIA NIM, build.nvidia.com), `model_roles.py` + `model_roles.json` (purpose → provider/model
  store, tool `assign_model_role`), `image_gen.py` (NVIDIA Flux / DALL·E / Imagen) + tool
  `generate_image`, `connectors/apple_design_connector.py` + tools `apple_design_lookup` /
  `apple_design_read`, the apple-design skill copied to `skills/apple-design/` (and to
  `../.claude/skills` and `../.agents/skills`), NVIDIA in `router.py`/`config.py`/`provider_specs.py`.
  Its planned `HANDOFF_FOR_CLAUDE/` folder was never written.
- **Claude round-2 subagents (died on the session limit)** left: `access_keys.py`, `routes_access.py`,
  `admin_server.py` (admin access server, port 8765), `learning.py`, `response_cache.py`,
  `client_state.py`, `routes_learning.py`, `learning_hooks.py`, `routes_providers.py` (API keys),
  `system_info.py` + `routes_system.py`, frontend `src/stream.ts`, `src/state/*`, `src/hooks/useTurns.ts`,
  redesigned `src/components/chat/*`, new `ChatPanel.tsx`/`App.tsx` (built 22:54).
- **Claude lead** added: `turn_registry.py` (chats run outside their tab; `/api/turns*`),
  agent updates broadcast workspace-wide with provenance (`agent.update`, `agent.created`),
  `@mention` → delegation, `/api/agents/{name}/tasks`, gzip + immutable asset caching, connector
  availability cache (Connectors tab 4 s → 6 ms), one-click engine (`Start Nyx.bat`, tray, `nyx://`).

## Next tasks, in order (tick them here as you go)

- [x] 1. Suite green (1045 → fixed `system_info.register_system_tools` passing dicts as params, which broke
      every ChatService prompt), tsc clean.
- [x] 2. **Model roles actually used** — `model_hub.py` (exact provider+model calls: OpenAI-compatible,
      Gemini, Anthropic, **AWS Bedrock with hand-rolled SigV4**, Ollama; image gen: NVIDIA genai with
      NVCF polling, OpenAI, Gemini, AWS Nova Canvas, **Pollinations free keyless fallback**),
      `model_roles.py` (roles, open fallback + announcement, outage cooldown, `model.role` events),
      `media_tools.py` (tools `analyze_image`, `read_document`, `generate_image`, `set_model_purpose`,
      `list_model_roles`), roles in the system prompt, `vision.py` uses `image_check`/`ui_pointing`.
      Verified live 2026-09-14: chat turn → analyze_image → NVIDIA Llama 3.2 Vision (1.4–17 s) → reply
      names the model; image gen: NVIDIA FLUX 504 (their outage) → Pollinations, announced.
- [x] 3. **Keys API** `routes_models.py`: `GET /api/keys`, `POST|DELETE /api/keys/{provider}` (AWS takes
      access_key_id/secret/region/session_token), `POST /api/keys/{provider}/test` (free checks),
      `GET|PUT|DELETE /api/model-roles[/{role}]`, `POST /api/model-roles/{role}/test`,
      `GET /api/models/catalog?provider=&job=`. Tests: `tests/test_model_roles.py` (22).
- [x] Router: optional smart model (gemini-3.5-flash) gets one 15 s try, then a 10-minute cooldown —
      it had made a simple image question take 125 s.
- [x] 4. **Keys & Models tab** (`src/panels/KeysPanel.tsx`, tab id `keys`): every provider with its key fields
      (AWS: 4 fields), "Get a free key" links (build.nvidia.com/models), Test/Remove; job table with
      provider/model pickers fed by `/api/models/catalog`, Test, Reset, "Add a job". Verified in the browser.
- [x] 5. Orphans wired: `learning_hooks.before_turn/after_turn` in `turn_runner.py` (cache hit → `cache.hit`
      event + "cache (provider)" label, `[fresh]` prefix skips cache, learned style hints as a system note,
      learned route can force the full pipeline); `ClientCookieMiddleware` in `server.py` (nyx_client cookie);
      admin console from tray menu item and `POST /api/engine/admin-console` (port 8765).
      Verified live: repeat question 2.15 s → 0.16 s from cache; learning observations recorded.
- [x] 6. Chat UI fixes (browser-verified): live turn bubble while streaming (was only shown at the end), stuck
      "Starting" placeholder removed (`turnStore.replaceLocalTurn`), generated pictures shown in the answer and
      saved into the transcript (`TurnRunner._attach_generated`), `model.role` chips ("NVIDIA Llama 3.2 Vision ·
      image check · 1.4s"), reload reopens the active chat (`nyx.chat.active`, `/api/chats/default/*`).
- [x] Engine restart/stop no longer hang with a browser open (uvicorn `timeout_graceful_shutdown=3`; old process
      force-exits; successor waits for the single-instance lock).
- [x] 7a. `machine_tools.py` — 25 tools: `run_command`, `run_python`, write/move/copy/delete (Recycle Bin),
      search/file_info/drives, `view_image`, `download_file`, processes/`kill_process` (never itself), volume,
      media keys, lock/sleep/restart, toast, clipboard, open app/path/url, environment. `tests/test_machine_tools.py` (11).
      Loaded live (engine restart 2026-09-14).
- [x] 7b. `email_client.py` + `routes_email.py` + Keys tab "Email" section — accounts (address + app password, verified
      by IMAP login; password only in `secret_store`), send via SMTP → Outlook COM (only if a mail profile exists) →
      pre-filled Gmail/Outlook-web/mailto draft that says NOT SENT YET; `email_list` (IMAP search), `email_read`,
      `email_reply` (threaded, reply-all skips self), `email_compose`, `email_accounts`. `tests/test_email_client.py` (14).
      Live: chat "which email accounts…" → `email_accounts` tool → honest answer. This PC: no account yet; classic
      Outlook installed but no profile, so drafts open in the browser until the owner adds an app password.
- [x] 7d. PC specs + live data visible and correct (goal B11) — see `01_GOALS.md` B11 for the five bugs fixed.
      Browser-verified on the Dashboard 2026-09-14.
- [x] 7e. Voices (goal B8): `tts.py`, `routes_voice.py`, `tests/test_tts.py` (10), `src/voice/voicePlayer.ts`, chat "Listen",
      Settings → Voices. Browser-verified 2026-09-14 (audio decoded; `voice.say` played once, with `play()` stubbed so
      nothing was audible). Note: `tool_setup` status now lists tools a module *replaced* (tts upgrades `speak`, `list_voices`).
- [x] 7c. Computer control (goal B7): `computer_control.py` (11 tools), `cursor_overlay.py`, `routes_computer.py`,
      `ComputerBanner.tsx`, `tests/test_computer_control.py` (16, all input faked). Live: overlay rendered on the real
      2-monitor desktop (5120×1967, uneven screens → dead-zone-aware clamping and failsafe corners), banner + Stop in
      browser. **Not yet done live: an actual mouse click/typing run — do it with the owner watching** ("open Notepad
      and type hello" is a good first test). Live "Computer" tab with screenshots (`/api/computer/screenshot`) not built.
- [ ] 8. Tests never written by the interrupted coders: `tests/test_client_state.py`, `tests/test_routes_learning.py`,
      `tests/test_admin_server.py`.
- [ ] 9. Frontend: send `PATCH /api/client/state` for drafts/tabs (server side exists); Access/beta UI in Admin
      panel; site `site/beta/` page (not present).
- [ ] 10. Keep `01_GOALS.md` statuses and `02_FEATURES.md` current; `API_ROUTES.md` regenerated 2026-09-14.

## Rules that cost people hours
See `05_RUNBOOK.md`. Never make a start path depend on a home-built .exe (Smart App Control).
Don't run many subagents in parallel — every parallel team so far died on the usage limit.
