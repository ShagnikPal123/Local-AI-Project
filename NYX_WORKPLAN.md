# NYX_WORKPLAN.md — the live task board

**Read `AGENTS.md` first** (how to work here). This file is *what is left*. Keep it under 200 lines.

---

## 0. The original request — preserved verbatim

Kept here so it survives a context reset or a lost session. Do not edit this block.

```text
[Obsidian API key removed — it lives in .env.local] is the API for obsidian and make
sure to link o it for better file usage and make sure it is used in your creation for different
resources as this project continues. spin up 4 sub agents, 1 manager, 1 site/web dev, 1 coder, and
one checker to make sure ideas they put in are solid and work. continue to improve the site, though
it seems to still have issues with opening the site to get into the ai and test it. Also make it
easier to install the app locally and download it rather than on the web. That was issues 1. issue
two is the AI itself, I am worried that it might be in a bugged state since it responds with the same
thing about its name and what it is rather than answering the question, check and see if you can fix
this. Take your time and efficiently and correctly fix the issues. Also make sure the AI stays
versatile and if a user wants to improve on it they can, though it wont affect every version. Also I
need a system to set up admin perms and keys and the windows. Mark those are second highest priority
behind the first issues I said. Also remember to have these listed in a document so if you lose
tokens you are able to find this command again and continue.
```

Follow-ups from the same session:
- "I have google antigravity to collaborate with you. if you need help make a common file so it can
  work in that as well" → `AGENTS.md` + this file + `../CLAUDE_ANTIGRAVITY_SYNC.md`.
- "make another agent to manage this file solely and have it link up with antigravity and act as its
  boss" → the **Liaison** role below.

**The Obsidian token is a secret.** It lives in `.env.local` as `OBSIDIAN_API_KEY`. It is quoted above
only because it was part of the original message; do not copy it anywhere else.

### Decisions already made (do not re-litigate)

| Question | Decision |
|---|---|
| Install format | Standalone `.exe`, no Python needed (PyInstaller) + Inno Setup installer |
| "the windows" | **Both** — in-app panel manager *and* Windows OS integration |
| Providers | All free APIs; users add their own via a window **or by asking the AI**; enable existing OpenAI key; keep Gemini free default; add Ollama |
| Obsidian vault | **Both** — `Ichnos` (has the plugin) and `Real Nyx` |
| Priority | Issues 1 & 2 first → admin/keys/windows second → Obsidian & profiles after |

---

## 1. Agent roles

| Agent | Owns (exclusively) | Never touches |
|---|---|---|
| Manager | `AGENTS.md`, this file, sequencing, phase sign-off | source files |
| Site/Web dev | `frontend/nyx-pulse/src/**`, `site/**`, `infinite-machine/**` | Python |
| Coder | `*.py`, `connectors/**`, `providers/**`, build scripts | frontend |
| Checker | `tests/**` | everything else |
| Liaison | `../CLAUDE_ANTIGRAVITY_SYNC.md` §4 and §6 — **sole Claude-side writer** | all code |

The Checker verifies **by execution, never by reading**, and may reject and hand work back. A phase
is done when tests have run, a real provider call succeeded, and the browser preview was driven.

---

## 1b. Clarification on the agent team (owner, 2026-09-05)

> *"when I said create 4 agents manager, check, coder, and site/web dev I meant for you, claude"*

The four roles are **Claude's own subagents**, not personas inside the app. Claude is the Manager
and delegates to Coder / Site-Web-Dev / Checker subagents, each owning a disjoint file set so two
agents never edit the same file. The in-app `AgentTeam` (`agent_team.py`,
`ensure_default_subagents()`) is a *separate* thing that happens to use the same four names - do not
confuse the two.

Standing file ownership when delegating:
- **Coder** - `*.py` at the root, `providers/`, `connectors/`, `tests/`
- **Site/Web Dev** - `frontend/nyx-pulse/src/` only
- **Checker** - runs pytest, drives the browser, verifies by execution; may reject and hand back
- **Manager (Claude)** - `*.md`, sequencing, merging, and the final report


## 2. Now (max 3)

### 2026-10-05 — Update 1 shipped

- [x] **Update 1** (session 0757e7): Swarm + Auto modes, /auto and @auto, every sub-agent's request and reply shown,
  Research tab, complete process list, 88 connectors, auto-assign models, Office Output box + staffing, Nyx tab with
  chats on the left and the Second Brain one switch away, voice bar, Nyx's own computer (Cua), site download button.
  Write-up: `AI_HANDOFF/START_HERE.md` § Update 1 (the handoff is local only now, not in git).
- [ ] **Owner to do:** Docker Desktop or a Cua Cloud key for Nyx's own computer; redeploy `site/` for the new
  download button; decide whether old commits that still contain `AI_HANDOFF/` should be rewritten.

### 2026-09-15 — current Request H resume point

- [x] **H16 tab editing freedom.** Custom tabs now render their already-validated backgrounds/themes and working
  lists, charts, trackers, timers, user-confirmed AI tasks, AI-vs-human games, and in-tab memory/snake games.
  `npm run build`, `tests/test_tab_freedom.py`, and a live browser check passed. The engine was restarted to load
  the backend schema Claude had already added; it is healthy on port 8000.
- [ ] **Next: H4 Build tab.** Keep the existing visual language; provide reliable circuit/3D-print/build research,
  material options, and a reviewed path to external tools. Do not claim a third-party connection until it is live.
- [ ] **Then: H5 Game Studio, H7 Google OAuth, H14 intent.md.** See `AI_HANDOFF/START_HERE.md` for the ordered
  Request H list and the source-file ownership.

### Historical snapshot — 2026-09-12/13 overhaul — requests verbatim in `OVERHAUL_CONTRACTS.md` §0 (also the owner's
### follow-up: "FIX the glaring issue which is the engine. Make it a single click to turn on for any user.")

- [x] **[E1] One-click engine — DONE AND VERIFIED (2026-09-13).** Root cause: Windows **Smart App
      Control** blocked the unsigned `dist/Nyx/Nyx.exe` on every start (CodeIntegrity 3077; logon task
      result 4551). Fix: `launcher.py` rewritten (tray icon, single-instance mutex per data dir,
      `nyx://start|open|stop|restart|redeem`, log file, error dialogs, per-install autostart) running on
      signed `.venv\Scripts\pythonw.exe`; `setup_nyx.py` (shortcuts, link, autostart, launch);
      `Start Nyx.bat` bootstrap (installs Python via winget if missing); `/api/engine` routes;
      web `EngineGate` ("Turn on Nyx") + service worker so the page loads while the engine is off;
      Settings → Engine; site "Launch Nyx" button; `build_release.py` → `dist/NyxIchos-Windows.zip`
      (4.4 MB, secret-scanned). Verified: nyx://start/stop, restart, second-click, Turn off → gate →
      reconnect, offline reload in real Edge, fresh install from the zip on port 8050. Old logon task
      disabled (re-enable: `schtasks /Change /TN NyxIchosEngine /ENABLE`). 881 tests pass.
- [x] **[SEC] Obsidian token was hardcoded** in `connectors/obsidian_connector.py` (since the baseline
      commit). Moved to `.env.local` as `OBSIDIAN_API_KEY`; the literal is gone from source but remains in
      git history — rotate it in Obsidian's Local REST API settings before the repo is ever made public.
- [ ] **[O1] Rest of the overhaul** — foundation landed (`agent_events.py`, `tool_context.py`,
      `permissions.py`, tool categories/labels/events in `tools.py`, Gemini streaming + thoughts + images
      in `providers/gemini_provider.py`). Next: streaming chat + thinking UI, agents/skills visible,
      machine/computer tools, email, uploads, Chrome tabs, tab-edit streaming, voices, specs, design layer.
      The 4-agent Claude team (Manager/Coder&Dev/Idea Maker/Designer) was launched 2026-09-12 but all
      four hit the account session limit before writing anything; relaunch with fewer in parallel.

- [x] **[P0] Handoff docs** -> `AGENTS.md`, this file, `.claude/CLAUDE.md`, `../CLAUDE_TO_ANTIGRAVITY.md`
- [x] **[P1] Make the AI answer the question** - DONE AND VERIFIED LIVE
      `paths.py` (new) anchors every persistent file; `config.py` loads dotenv from there;
      `chat_service.split_directives()` moves `[MULTI-APPROACH...]` into a system message;
      word-anchored matching; `router.py:214` no longer swallows the diagnostic.
      Verified: "what is 2+2?" -> "2 + 2 equals 4." via gemini, in the browser.
- [x] **[P2] Get into the site and chat** - DONE AND VERIFIED IN THE BROWSER
      `ChatPanel.tsx` `.data.response` -> `.data.reply`; `api.ts` interface corrected;
      app opens on Chat; bundle rebuilt; `/assets/ichnos-*.png` 200s; no console errors.
- [x] **[P2b] "Engine not running" on the landing page** - DONE
      `/api/health` now answers any origin (wildcard, **credential-free**), so a page served
      from `file://`, a hosted origin, or any port can run the liveness probe. Verified from
      `localhost:8080`, deliberately outside the CORS allowlist: "Engine running on this machine".
      Other endpoints still refuse foreign origins - checked `/api/status` returns no ACAO.
- [x] **[Brand] Ichnos avatar** - the source artwork is the avatar, animated with CSS
      (`NyxAvatar.tsx` + `index.css`, and the site header mark). Bob, halo pulse, orbiting
      spark while busy, drifting sparks at large sizes, `prefers-reduced-motion` honoured.

### Done since the last update
- [x] **[U1] Tab rail moved to the top** - `TopTabs.tsx`, horizontal, scrolls rather than wraps,
      with an "All tabs" overflow menu; verified at 375px.
- [x] **[U2] Tab creation takes a name AND a description** - `TabFinder.tsx` two-field form.
- [x] **[U3] Strands has its own composer**; **[U4]** "Awaiting command" replaced with
      "Click Speak to talk, or type in the box below."
- [x] **[S1][S2][S3][S4][S6]** Strands: 4s polling plus immediate refresh after send, a thinking/
      replying state chip, honest labelling of where the voice energy comes from, a real 3D
      perspective field, drag-pan and zoom.
- [x] **[S7] Expands, never turns.** Replaced the per-frame Y/X rotation with a fixed viewing angle
      plus a radial `expansion` scale, so points travel straight outward from the centre while Nyx
      speaks and ease back after. Angles are never modified.
- [x] **[U5-backend] Tab edits are now recorded.** `TabSpec` gained `edits[]` + `updated_at`;
      `TabStore.update()` diffs before/after and stores what actually changed; the edit route
      returns `applied`, `summary` and the history. An edit that is understood but changes nothing
      now says so instead of reporting success.
- [x] **Widgets cleaned** - `widgets.json` held 31 duplicate finance widgets with empty config,
      each rendering "not wired yet". 35 -> 4. Backup at `widgets.json.bak`. The guard that stops
      it recurring belongs in `widgets.py` (`_REQUIRED_CONFIG`) and is still open.
- [x] **[P3] Standalone installer** - `launcher.py`, `nyx.spec`, `nyx.ico`,
      `dist/NyxIchos-windows-x64.zip` (30 MB). Verified with no venv: took port 8001 when 8000 was
      busy, served the UI, answered via gemini. A keyless install reports the real reason.
- [x] **[A1-backend] Accounts** - `POST /api/auth/claim` (loopback-only, 409 once claimed, absent in
      hosted mode); `AuthStore.grant_role_as` so the route stops duplicating owner rules.

## 2b. Next up

- [ ] **[P3] Standalone installer** -> `nyx.spec`, `launcher.py`, `installer.iss`, `build.ps1`


## 2c. Requested 2026-09-05 (owner feedback after first successful use)

Owner could access and use the app; these are the follow-ups, verbatim intent preserved.

### UI / workspace
- [ ] **[U1] Move the tab rail to the top** (horizontal) instead of the left sidebar
      -> `frontend/nyx-pulse/src/App.tsx`, `tabs.ts`
- [ ] **[U2] Better custom-tab creation**: name + a description of what the tab *does*,
      and give the AI more latitude when generating one
      -> `dynamic_tabs.py` (`build_tab_prompt`, `TabSpec.description`), `TabFinder.tsx`
- [ ] **[U3] Strands needs its own text input box** -> `panels/StrandsPanel.tsx`
- [ ] **[U4] "Awaiting command" placeholder is unclear** - say plainly that this is where you
      click to speak/type -> `StrandsPanel.tsx`

### Strands visualisation (owner: "make it huge as users talk to it")
- [ ] **[S1] Update in real time** as the conversation progresses
- [ ] **[S2] A visible "the AI is thinking" state** - currently you cannot tell
- [ ] **[S3] Voice strand correctness is unclear** - verify it reflects real voice state
- [ ] **[S4] Points should float; 3D representation**
- [ ] **[S5] React to speech** - move like a voice while the AI talks
- [ ] **[S6] Draggable / pannable**, and able to grow large over time
      -> all of the above: `panels/StrandsPanel.tsx` (555 lines, largest panel), `widgets.py`
- [ ] **[S7] Expansion on speech - outward only, never rotation.** While the AI is *speaking*
      (not while idle, not while the user types), the field must **expand**: points translate
      **radially outward from the centre** and settle back as speech ends. Explicitly NOT a
      rotation, spin, or orbit - the owner called this out specifically. Implement as a per-point
      radial offset scaled by the speech envelope, i.e. `p.xy += normalize(p.xy - centre) * amp`,
      leaving each point's angle untouched. Any `rotate()` on the field breaks the requirement.

### Tab editing (owner, after using it)
- [ ] **[U5] You cannot tell whether a tab edit worked.** Asking it to "change the background to
      green" gives no visible confirmation, and after clicking done every edit prompt the owner
      typed disappears - so it is impossible to tell whether the change applied, is still running,
      or was thrown away. Needs: optimistic/visible application of the change, a persistent record
      of the edits made to a tab, and an explicit pending/applied/failed state.
      -> `panels/DynamicTab.tsx` (edit panel), `tab_editor.py` (`interpret_locally`,
         `parse_edit_reply`), `dynamic_tabs.py` (`TabStore.update`)
      Note `tab_editor.interpret_locally` already handles colour changes deterministically and
      offline, so "make it green" should be instant and never reach the model - if it feels slow
      or silent, that path is not being hit.

### Accounts & permissions
- [ ] **[A1] Admin permissions surfaced in the UI** + **account creation**
      -> `server.py` `/api/auth/claim` (new), `auth.py` `grant_role_as`,
         `components/AuthScreen.tsx` (SetupScreen), `panels/AdminPanel.tsx` (People tab)
      The RBAC engine already exists with 134 tests; this is UI + a claim route.

### Speed
- [ ] **[SP2] Switching the model must be easy, including by just asking.** Owner: *"when I ask
      the AI it says it can't be done"*. Two halves:
      (a) **UI** - a provider/model picker. In flight with the provider dropdown work.
      (b) **The AI can do it itself.** `/api/models/switch` already exists (`server.py:571-593`) and
      already assigns `SETTINGS.preferred_online_provider` / `SETTINGS.ollama_model` live - the
      settings object is a mutable dataclass read at call time, so this needs **no restart**. What
      is missing is a **tool** in `tools.py`'s `TOOL_REGISTRY` exposing it, which is why the model
      truthfully says it cannot: it genuinely has no way to. Add `switch_model(provider, model)`
      with the same validation the route uses, and let it report the switch back in the reply.
      Guard: refuse a paid provider while `free_only` is on and say why, rather than silently
      ignoring the request.
- [ ] **[SP1] Make replies feel faster.** MEASURED: our code is not the bottleneck.
      `gemini-flash-lite-latest` median **1.30s** but max **10.42s** (free-tier variance).
      The configured `OPENAI_API_KEY` is valid but returns **429 - no quota/credits**, so it
      cannot serve as the fast fallback until billing is added.
      Best fix that does not depend on the provider: **stream the response** (SSE) so tokens
      appear immediately. Second: add a **Groq** free key - consistently sub-second.
      -> `server.py` (SSE endpoint), `chat_service.py`, `panels/ChatPanel.tsx`

### Mobile / distribution (owner: "eventually")
- [ ] **[M1] Phone-accessible from the web, later importable to an app store.**
      The straightforward route is a **PWA**: web app manifest + service worker + the icon set
      (the Ichnos art is already exported at 512/256/192/64/32 in `assets/brand/`), which gives
      "Add to Home Screen" on iOS and Android and installability on desktop Chrome. An app-store
      build later wraps the same PWA (Trusted Web Activity on Android, Capacitor for iOS).

      **The tension to resolve first, before building this.** Nyx is deliberately local-first:
      the engine is Python running on the owner's PC, and `server.py` binds `127.0.0.1` with a
      localhost-only CORS allowlist. A phone cannot run that engine and, by design, cannot reach
      it. So M1 needs an explicit decision:
        (a) **Phone talks to your PC** over the LAN or a tunnel - keeps data local, but means
            binding beyond loopback and a real auth story on the wire. The RBAC engine exists;
            sessions are currently in-memory (see P6.5) and would need to survive.
        (b) **Hosted engine** - easy on mobile, but contradicts the project's stated reason for
            existing (`site/index.html`: "Why there is no cloud version").
        (c) **Read-only companion** - the phone views chats/memory synced through Obsidian, and
            long tasks still run on the PC. Smallest change, keeps the local-first promise.
      Recommend (c) first, then (a) behind an explicit opt-in. Do NOT quietly do (b).

### Naming
- [ ] **[N1] Confirm the brand spelling.** The codebase says **"Nyx Ichos"** in 55 places; the
      owner writes **"Ichnos"**, the Obsidian vault is `Ichnos`, and the avatar artwork letters
      the book `ICHNOS`. The site/app `<title>` has been shortened to `Nyx Ichos` as asked, but
      the spelling was left alone - a rename touches 55 occurrences plus the vault path and is
      the owner's call, not a silent edit.

## 3. Next (max 7)

- [ ] **[P3] Standalone installer** → `nyx.spec`, `launcher.py`, `paths.py`, `installer.iss`, `build.ps1`
- [ ] **[P6.1] First-run claim wizard** → `server.py` `/api/auth/claim`, `AuthScreen.tsx` `SetupScreen`, `App.tsx:174`
- [ ] **[P6.2] Admin console** → `auth.py` `grant_role_as`, `server.py:1886-1900`, `AdminPanel.tsx` People tab
- [ ] **[P6.3] Key manager** → `key_manager.py`, 4 routes, Keys sub-tab
- [ ] **[P6.4] Window/panel manager** → `tabRegistry.tsx`, `tabs.ts` `resolveTabs`, `widgets.py` `repair()`
- [ ] **[P4] Obsidian connector, both vaults** → `connectors/obsidian_connector.py`
- [ ] **[P4b] Free + custom providers** → `provider_specs.json`, `providers/custom.py`

## 4. Later

- [ ] **[P5] Profiles / version isolation** → `profiles.py`, `chat_service.py:450`, `config.py` overrides
- [ ] **[P6.5] Session persistence** → `auth.py` — **reverses a documented decision, needs sign-off**
- [ ] **[P6.6] Windows OS integration** → firewall, run-at-login, optional service
- [ ] **[P6.7] Connector permission gate** → connectors must call `MACHINE.check()`

---

## 5. Blocked

| Item | Unblocked by |
|---|---|
| Parallel work with Antigravity | **`git init`** — there is no version control anywhere in this tree |
| Inno Setup installer (P3.3) | Inno Setup 6 is not installed; fallback is a self-extracting ZIP |
| Obsidian REST transport | Only works while Obsidian is running — filesystem fallback is mandatory |
| Session persistence (P6.5) | Explicit sign-off; breaks `test_sessions_do_not_survive_a_restart` by design |
| **Anyone downloading the app** | **The GitHub repo is private.** Owner must make it public, or publish the release separately |
| Cloud routine "Nyx Ichos — own model prep" | Same cause: Claude Code cloud gets 403 cloning a private repo. See `NYX_MODEL_ROUTINE.md` |

---

## 6. Verified facts (do not re-investigate)

- **Both API keys work.** OpenAI `/v1/models` → 200 (119 models). Gemini `ListModels` → 200 (50).
  `GEMINI_MODEL=gemini-flash-lite-latest` exists. Nothing is wrong with the providers.
- The canned-reply bug is `config.py:11` (CWD-relative dotenv) → `router.py:214` (raises) →
  `chat_service.py:373` (swallows) → `chat_service.py:356` (`"app"` matches inside `"approach"`).
- `ChatPanel.tsx:35` reads `.data.response`; the server sends `.reply` → empty bubble, HTTP 200.
- `SETTINGS` is a **mutable** dataclass read at call time — hot reload needs no restart.
  Precedents: `cli.py:883-887`, `server.py:571-593`.
- `_try_fast_response` (`chat_service.py:550-576`) bypasses personality/memory/skills. Any
  customization work MUST fix this or it silently does nothing on most turns.
- `overlay.py` is fully built but **never read** by the running app.
- `auth.json` does not exist → the API is currently unauthenticated locally.
- `.venv` is healthy (Python 3.14.7). `.venv.broken` is dead and inert.
- PyInstaller 6.22.2 supports Python 3.14.
- Obsidian plugin: HTTPS **27124** only, in the **Ichnos** vault. 27123 disabled.
- **The repo is private** (2026-09-07). `api.github.com/repos/ShagnikPal123/Local-AI-Project` → 404
  unauthenticated, `git ls-remote` → 200 with the owner's credentials. This single setting is why
  the site's "Download for Windows" 404s for every visitor, why no release can be fetched, and why
  the cloud routine cannot clone. `dist/NyxIchos-windows-x64.zip` (31.5 MB) is built and waiting.
- **NVIDIA NIM works but is slow** — free credits, OpenAI-compatible at
  `integrate.api.nvidia.com/v1`. Measured: `nvidia/nemotron-3.5-lightning-30b-a3b` 21.6s,
  `deepseek-v4-pro` 21s, `mistral-nemotron` 46s, `gemma-4-31b-it` 504 after 302s. Many catalogue
  ids answer 404/410. It is a **fallback**, never a primary — Gemini is ~1.3s.
- `providers/compat.py` sends **no `max_tokens`**. Harmless for normal models; a reasoning model
  (`openai/gpt-oss-20b`) then runs unbounded — 5s capped vs **80s** uncapped. Do not default any
  provider to a reasoning model until that adapter caps output.
- The router puts custom providers **behind** shipped ones of the same cost (`_online_order`),
  so adding NVIDIA cannot displace Gemini.

---

## 7. Handoff

**Last touched:** Update 1, 2026-10-05.

**State:** Update 1 is committed and on GitHub (branch `update-1`, merged to `main`, tag `update-1`). Full pytest suite
green; `npm run build` green; live-checked in the browser on a scratch engine.

**Next:** whatever the owner picks from `AI_HANDOFF/UPDATE_IDEAS.md` (still queued: U2–U4, U7, U8, U10–U12, U14, U16,
U18–U20, U22, U23, U25, U27 rest, U28, U32–U40, U42 CEO/CFO split, U43–U45).

**Check first:** `.venv/Scripts/python.exe -m pytest -q -p no:warnings`, then `cd frontend/nyx-pulse && npm run build`.
