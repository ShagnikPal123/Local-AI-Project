# AGENTS.md — how to work in this repo

Tool-neutral instructions for any AI coding agent (Claude Code, Google Antigravity, Cursor, Codex).
If a fact in this file changes, it is because the code changed. No status, no dates, no task lists —
those live in `NYX_WORKPLAN.md`.

---

## 1. What this is

**Nyx Ichos** — a local-first AI assistant. Python 3.14 FastAPI backend + React/TypeScript frontend.

| Part | Location |
|---|---|
| Backend | `server.py` (~1990 lines, 97 routes) + ~60 root modules |
| Providers | `providers/` — 8 LLM adapters behind `router.py` |
| Connectors | `connectors/` — tools the assistant can call |
| Frontend | `frontend/nyx-pulse/` (React + Vite), built into `dist/app/` |
| Tests | `tests/` — 68 files, ~685 test functions |
| CLI | `cli.py` (interactive TUI), `quick_chat.py` (one-shot) |

The frontend is **served by FastAPI itself** (`server.py:1921-1957`). You do not need a second dev
server to use the app.

---

## 2. THE #1 FOOTGUN — read this before running anything

The project root is the **nested** folder:

```
C:\Users\shagn\Desktop\Ai Dev Folder\Ai Dev Folder\     <-- THE PROJECT (run from here)
C:\Users\shagn\Desktop\Ai Dev Folder\                   <-- outer container, NOT the project
```

Historically several stores resolved their paths **relative to the current working directory**, so
running from the outer folder silently created a second, empty `.env.local` / `chats.json` /
`memory.json` world — the app then reported "no API key configured" while a perfectly good key sat
one directory down. This produced a months-long bug where the assistant answered every question with
the same canned sentence.

Paths are now anchored via `paths.py` to the project directory. **Do not reintroduce a bare relative
path for any persistent file.** If you add a store, resolve it through `paths.py`.

`.vscode/settings.json` in the OUTER folder makes the outer folder the workspace root. Be careful.

---

## 3. Commands

Always use the venv interpreter. A bare `python` on this machine resolves to the Microsoft Store stub
and has none of the dependencies.

```bash
# from the PROJECT folder
.venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000   # run the app
.venv/Scripts/python.exe -m pytest                                            # all tests
.venv/Scripts/python.exe -m pytest tests/test_router.py -q                    # one file
.venv/Scripts/python.exe cli.py                                               # interactive CLI
cd frontend/nyx-pulse && npm run build                                        # rebuild the UI
```

**How users start Nyx (one click):** `Start Nyx.bat` → first run does setup via
`setup_nyx.py` (packages, desktop/Start Menu shortcuts, `nyx://` link, start-with-Windows)
and every run starts `launcher.py` under `.venv\Scripts\pythonw.exe` with a tray icon.
`launcher.py` is single-instance, handles `nyx://start|open|stop|restart|redeem`, and logs to
`logs/engine.log`. The engine exposes `/api/engine` (+ `/stop`, `/restart`, `/autostart`).

**Never point an entry point at a home-built `.exe`.** Windows Smart App Control (on for the
owner's PC) blocks unsigned executables — `dist/Nyx/Nyx.exe` was silently refused on every
start (CodeIntegrity 3077, task result 4551). Signed `pythonw.exe` is allowed.

```bash
.venv/Scripts/python.exe launcher.py --console --no-browser   # run under the launcher, in a console
.venv/Scripts/python.exe setup_nyx.py --no-launch             # repair shortcuts / link / autostart
.venv/Scripts/python.exe build_release.py                     # dist/NyxIchos-Windows.zip (secret-scanned)
```

**The frontend has no test runner.** `npm run build` is `tsc -b && vite build` — type-checking is the
only automated frontend gate.

**After changing any file in `frontend/nyx-pulse/src/`, you MUST run `npm run build`.** The server
serves the built bundle in `dist/app/`, not your source. A source-only fix changes nothing.

---

## 4. The five invariants

Each has an enforcement point in code. Do not weaken them.

1. **Deny by default.** Every `/api/*` route is gated unless explicitly public.
   → `server_auth.py:120-160` (path middleware), allowlist at `:109-117`.
   A new route that needs no auth must be added to the allowlist *and* to the parametrized refusal
   lists in `tests/test_server_auth.py` — the middleware exists because hand-gating already missed
   three routes once.

2. **Specs are data, never code.** User- and AI-generated UI is a validated declarative spec that the
   app renders. Never generated code that is executed.
   → `dynamic_tabs.py:1-15`, `skills.py:9-13`, `overlay.py:13-16`.
   This applies to LLM-authored provider specs too.

3. **The overlay/profile layer never mutates base modules.** Customization is a delta applied on top
   of shipped defaults, so a base update cannot clobber a user's changes and a user's changes cannot
   leak into anyone else's install.
   → `overlay.py`, `profiles.py`.

4. **Nothing publishes without human review.** The change pipeline separates "AI reviewed it" from
   "a human approved it" so an AI cannot approve its own change.
   → `change_review.py:53-60` (transition table), `:245-259`.

5. **No credential in source, ever.** Keys come from `.env.local` or `secret_store.py`. Never a
   literal in a `.py`, never in a doc, never in a commit, never echoed into logs or chat history.
   → `auth.py:3-14`, `config.py`, `providers/gemini_provider.py:16-22` (`_scrub_key`, because the
   Gemini API takes the key as a URL parameter and it lands in exception text).

---

## 5. Module map

| Module | Owns |
|---|---|
| `server.py` | HTTP routes, static mount, service cache |
| `server_auth.py` | HTTP auth dependencies + deny-by-default middleware |
| `auth.py` | Roles, permissions, passwords, sessions, invites |
| `router.py` | Provider selection, fallback chain, metrics |
| `chat_service.py` | The conversation loop, tool calls, memory/skill injection |
| `config.py` | `SETTINGS` singleton (mutable; read at call time) |
| `paths.py` | Project-anchored paths for every persistent file |
| `secret_store.py` | API keys: OS keyring, falling back to `.secrets.json` |
| `overlay.py` | Published, install-wide changes + checkpoints |
| `profiles.py` | Per-user layered customization |
| `dynamic_tabs.py` / `widgets.py` / `skills.py` | The three declarative spec systems |
| `change_review.py` | Draft → reviewed → approved → published state machine |
| `machine_control.py` | Capability grants for system access |

---

## 6. Conventions

- **Docstrings say _why_, not _what_.** The code says what. Match the surrounding density.
- **A change ships with its test.** Put it in the existing `tests/test_<module>.py`.
- **Absolute paths on Windows**, and quote them — most paths here contain spaces.
- **Never `git commit`, `git push`, or create a PR unless explicitly asked.**
- **Never delete a user's data file** (`chats.json`, `memory.json`, `auth.json`, `profiles/`).
- **Ask before anything that costs money** (paid model calls beyond a 1-token key test) or that
  touches the system outside this folder.
- Prefer extending an existing module over adding a new one. Several capabilities here already exist
  and are simply not wired up — check before you build.

---

## 7. Never do

- Reintroduce a CWD-relative path for a persistent file (see §2).
- Return an API key value in an HTTP response. Masked `last4` only.
- Widen the CORS policy globally to fix one endpoint.
- Add a route without adding it to the auth test lists.
- Put a secret in any file that is not `.env.local` or `.secrets.json` (both gitignored).
- Execute LLM-generated code.

---

## 8. End-of-session ritual (3 lines)

1. Append what happened to `PROJECT_STATE.md` → `## Session log`.
2. Rewrite `NYX_WORKPLAN.md` → `## Now` and `## Handoff`.
3. Tick statuses in `ROADMAP.md`.

Nothing else. `ROADMAP.md` (33 KB) is what-and-why and is permanent. `PROJECT_STATE.md` (39 KB) is an
append-only log — never read it in full. `NYX_WORKPLAN.md` is a pointer file and holds no prose that
exists elsewhere.
