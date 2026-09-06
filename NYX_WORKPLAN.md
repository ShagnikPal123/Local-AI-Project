# NYX_WORKPLAN.md — the live task board

**Read `AGENTS.md` first** (how to work here). This file is *what is left*. Keep it under 200 lines.

---

## 0. The original request — preserved verbatim

Kept here so it survives a context reset or a lost session. Do not edit this block.

```text
[Obsidian API key removed] is the API for obsidian and make
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

## 2. Now (max 3)

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

---

## 7. Handoff

**Last touched:** Phase 1 (AI fix), Phase 2 (site fix), health-probe CORS, Ichnos avatar.

**State:** the app works end to end. Tests went 816 -> 829. Engine runs on :8000, and the landing
page detects it from any origin.

**Half-finished:** nothing. Next task is the standalone installer (P3).

**Watch out:**
- Antigravity added `AgentTeam.ensure_default_subagents()` (the four standing roles) and wired it
  into **GET** `/api/agents`. That is a read with a side effect, and it broke
  `test_three_agents_can_be_spawned_in_one_call`, which assumed an empty team. The test now asserts
  the agents actually created rather than a raw total. Consider moving the seeding out of the GET.
- A pytest warning shows an unverified HTTPS request to 127.0.0.1 from `/api/connectors` - an
  Obsidian connector reaching the Local REST API. Confirm the TLS handling is loopback-scoped.

**Check first:** `.venv/Scripts/python.exe -m pytest -q` from the project folder.

**Reference:** full plan at `C:/Users/shagn/.claude/plans/9814bdd2ca304a785291c5d86cc4e97b3e3e560-cryptic-mochi.md`
