# 05 — Runbook

All commands from the project folder `C:\Users\shagn\Desktop\Ai Dev Folder\Ai Dev Folder\`.

```bash
.venv/Scripts/python.exe -m pytest -q                                   # full suite (~880 tests, ~70 s)
.venv/Scripts/python.exe -m pytest tests/test_x.py -q -p no:cacheprovider --basetemp=local_pytest_tmp/me
.venv/Scripts/python.exe -m uvicorn server:app --host 127.0.0.1 --port 8000   # dev engine in a console
.venv/Scripts/pythonw.exe launcher.py                                   # normal start (tray, browser)
cd frontend/nyx-pulse && npx tsc --noEmit -p tsconfig.json              # type-check
cd frontend/nyx-pulse && npm run build                                  # REQUIRED after any src/ edit
.venv/Scripts/python.exe build_release.py                               # dist/NyxIchos-Windows.zip
.venv/Scripts/python.exe AI_HANDOFF/generate_routes.py                  # refresh API_ROUTES.md
```

Restart a running engine after Python changes: `curl -X POST http://127.0.0.1:8000/api/engine/restart`
(only when started by the launcher), or tray → Restart engine.

## Traps
- **Nested folder.** Run from `Ai Dev Folder\Ai Dev Folder\`. The outer folder only holds wrappers.
- **`python` is the Microsoft Store stub** on this PC. Always `.venv/Scripts/python.exe`.
- **The engine serves `frontend/nyx-pulse/dist/`**, not source. Rebuild after every frontend edit.
- **Smart App Control is ON** on the owner's PC: unsigned `.exe` files are silently killed
  (CodeIntegrity 3077). Start paths use signed `pythonw.exe`.
- **Windows console is cp1252**: set `PYTHONIOENCODING=utf-8` when printing emoji from scripts.
- `SETTINGS` (config.py) is a mutable dataclass read at call time — runtime changes need no restart.
- Sessions are in-memory: an engine restart signs everyone out once the install is claimed.
- Tests must never move the real mouse, type, send email, play audio, or write the registry.
- Gemini: `gemini-flash-lite-latest` is fast (~1.3 s) and returns thought summaries with
  `thinkingConfig.includeThoughts`; newer `gemini-3.x` flash models 503 under load at times.
- The OpenAI key has no quota (429); NVIDIA NIM works but takes ~20 s.
- `git` exists but nothing since 2026-09-06 is committed. Don't commit unless the owner asks.
