# Troubleshooting

Real problems that were hit on a real machine, what caused them, and the fix.
Each one wasted hours, so the symptom is written the way you actually experience
it rather than the way the bug is described in the code.

---

## "Nyx never turns on" / "the engine won't start"

**Symptom.** Double-clicking `Nyx.exe`, or signing in to Windows with the
"NyxIchosEngine" logon task, does nothing. No window, no error, and
`localhost:8000` says the site can't be reached. The task's *Last Result* reads
**4551**.

**Cause.** Windows **Smart App Control** was blocking the packaged `Nyx.exe`
before a single line of Nyx ran. It refuses unsigned programs it has no
reputation for, and a PyInstaller build is exactly that. 4551 is
`ERROR_SYSTEM_INTEGRITY_POLICY_VIOLATION`; the proof is in Event Viewer under
*Applications and Services Logs → Microsoft → Windows → CodeIntegrity →
Operational*, event **3077**, naming `dist\Nyx\Nyx.exe`. Check whether it is on
with:

```powershell
(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy').VerifiedAndReputablePolicyState   # 1 = on
```

**Fix (2026-09-13).** Nothing that starts Nyx points at a home-built exe any more.
Every entry point runs `launcher.py` on Python's own `pythonw.exe`, which is signed
by the Python Software Foundation and allowed:

- **`Start Nyx.bat`** — double-click once. It installs Python if needed (winget,
  per-user), installs the packages, creates the **Nyx Ichos** desktop and Start
  Menu shortcuts, registers the `nyx://` link, turns on start-with-Windows, and
  starts Nyx. Every later run just starts Nyx and closes itself.
- **The desktop icon** starts Nyx in the background (tray icon near the clock) and
  opens it. Clicking it again while Nyx runs just opens the page.
- **`nyx://start` / `nyx://open`** — the website's *Launch Nyx* button and the
  app's *Turn on Nyx* screen use these.
- **Start with Windows** is a per-user Run entry (tray icon → *Start with Windows*,
  or Settings → Engine). The old logon task was disabled; it only ever tried the
  blocked exe.

Signing the exe would also fix it, but needs a paid code-signing certificate.

**If it still does not start:** right-click the tray icon → *View engine log*, or
open `logs\engine.log` in the Nyx folder. Double-clicking `Start Nyx.bat` again
repairs anything missing.

---

## "The AI keeps telling me its name instead of answering"

**Symptom.** Every message gets the same reply, whatever you ask:

> *I can help you build this step by step. Let's define the goal, isolate the minimum working version…*

or

> *Hello! I'm Nyx Ichos, and I'm currently in offline mode…*

It looks like the model is stuck in a loop reciting its identity. It is not. The
model is never reached at all — you are seeing an offline fallback wearing a
disguise. Three separate defects stacked up:

**1. Your API keys were never loaded.** `config.py` called
`load_dotenv(".env.local")` with a path relative to the *current working
directory*. Launch from the parent folder — which is what `.vscode/settings.json`
makes the workspace root, so VS Code's Run button did exactly this — and Python
looked for `.env.local` in the wrong place, found nothing, and every provider
reported "no API key configured" while a perfectly good key sat one directory
below. About fourteen other stores had the same bug, so a whole second, empty set
of `chats.json` / `memory.json` quietly appeared in the parent folder.

**2. The real error was thrown away.** `router.py` built an excellent diagnostic
naming every provider it tried and why each failed, and `chat_service.py` caught
`ProviderError` and discarded the message.

**3. The fallback guessed a topic by substring.** It tested `"app" in message` —
and the CLI prepends `[MULTI-APPROACH PROTOCOL: AUTO]` to every message, which
contains **app**roach. So branch four fired for *every message ever sent*.
Separately `"hi"` matches inside `"this"`, which produced the greeting reply.

**Fixed by:** a new `paths.py` that anchors every persistent file to the project
directory instead of the CWD; `split_directives()`, which moves those bracketed
directive blocks into a system message so they stop polluting the user's text,
history, memory and RAG; word-anchored matching; and passing the router's real
diagnostic through to the user.

**If you see it again:** the reply now tells you the actual reason, e.g.
*"Reason: Every available provider failed. gemini: 401 …"*. Run `/doctor`, or:

```bash
.venv/Scripts/python.exe -c "from config import SETTINGS; print(bool(SETTINGS.gemini_api_key))"
```

---

## "I open the app, send a message, and get an empty reply bubble"

**Symptom.** The message sends, the provider name and latency appear, and the
assistant's bubble is blank. No error anywhere. The network tab shows
`POST /api/chat → 200 OK`.

**Cause.** A field-name mismatch. `server.py` returns `reply`; the chat panel
read `result.data.response`. Reading a missing key gives `undefined`, React
renders nothing, and because the request genuinely succeeded there is no error to
notice. `DynamicTab.tsx` read `reply` correctly, which is how the two drifted
apart without anyone seeing it.

**Fixed by:** correcting the client to read `reply`, and correcting the
TypeScript interface so the compiler catches the next drift.

**The part that makes this bite twice:** the bug was baked into the built bundle
in `dist/`. FastAPI serves the *build*, not your source, so editing the `.tsx`
changes nothing until you run:

```bash
cd frontend/nyx-pulse && npm run build
```

If a frontend change seems to have no effect, this is almost always why.

---

## "The website says 'Engine not running' even though it is running"

**Symptom.** You started the engine, `http://localhost:8000` works in another
tab, but the landing page still shows a red dot and the "Open the workspace"
button never enables.

**Two different causes, depending on where the page is served from.**

**a) You opened the page over HTTPS (the hosted site).** A page served over
`https://` is not allowed to fetch `http://127.0.0.1:8000` — browsers block it as
mixed content / a private-network request, *before* any CORS check. This is not
fixable from the page; the page now detects the scheme and shows instructions
instead of a probe that can never succeed.

**b) You opened the page from `file://` or a different port.** The engine's CORS
policy is a fixed localhost allowlist, and it is credentialed, so it deliberately
refuses unknown origins. The probe threw and the page assumed the engine was
down.

**Fixed by:** exempting `/api/health` alone — it now answers any origin with
`Access-Control-Allow-Origin: *` and, importantly, **credentials disabled**. A
wildcard origin *with* credentials would let any page you visit call the API as
you; liveness returns no personal data, so it is safe to expose and nothing else
was widened. Verified from `localhost:8080`, an origin deliberately outside the
allowlist.

---

## "Double-clicking chat.bat flashes a window and closes"

**Cause.** It ran bare `python`, which on Windows resolves to the Microsoft Store
stub — an interpreter with none of the dependencies — so it died on
`ModuleNotFoundError` behind a `pause` you never got to read.

**Fix.** `chat.bat` now uses the project's own interpreter
(`.venv\Scripts\python.exe cli.py`) and runs the one-time setup if the
environment is missing. To start the app itself, double-click **Start Nyx.bat**
(or the **Nyx Ichos** desktop icon it creates) — never a bare `python` command.

---

## "Replies are slow"

**Measured, so you do not have to guess.** The code is not the bottleneck. On the
free tier, `gemini-flash-lite-latest` had a **median of 1.30s** but spikes to
**10.42s** — the variance is the provider, not Nyx. The fast path is working; a
trivial question is correctly routed to it.

**What actually helps:**
- A second free provider with steadier latency (Groq is consistently sub-second).
- Streaming the response so tokens appear immediately — this changes perceived
  speed far more than raw provider latency.

**What does not help:** disabling tools. Measured at 8.53s vs 9.41s — the 8KB
tool schema is not the cost.

**Watch out:** a valid API key can still fail. A configured `OPENAI_API_KEY` here
listed 119 models successfully but returned `429 Too Many Requests` on every
chat call — the key was fine, the account had no quota. "Key present" and "key
works" are different things, which is why the status page now probes rather than
just checking that a string is non-empty.

---

## "Saving failed" / a setting did not stick (Windows)

**Cause.** Saves are atomic: write a temp file, then `os.replace` it over the
target. On Windows that fails with `PermissionError` (WinError 5/32) whenever
anything holds the target for even a moment — usually a virus scanner or the
search indexer reacting to the file just written. It showed up as a *different*
test failing on each run.

**Fix.** `paths.atomic_replace()` retries with a short backoff. A lost
`auth.json` write means a lost password change, so this is worth the retries; the
final attempt still raises rather than silently swallowing a save that truly
cannot happen.

---

## Golden rules

1. **Run from the project folder** (`Ai Dev Folder\Ai Dev Folder\`), never the
   parent. This single mistake caused the biggest bug in this file.
2. **Use `.venv\Scripts\python.exe`**, never bare `python`.
3. **Run `npm run build` after any frontend change.** The server serves the build.
4. **A green `pytest` is the gate.** From the project folder:
   `.venv\Scripts\python.exe -m pytest -q`
