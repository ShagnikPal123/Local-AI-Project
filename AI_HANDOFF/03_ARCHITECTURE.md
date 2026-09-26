# 03 — Architecture

```
Browser (React, served by the engine at http://localhost:8000)
   │  fetch /api/*            SSE /api/chat/stream (one turn)      SSE /api/events/stream (workspace)
   ▼
server.py (FastAPI) ── includes routes_live.py (+ routes_system/computer/email/access/voice when present)
   │
   ├─ ChatService (chat_service.py) ── one per chat id (server._services)
   │     ├─ chat()        blocking turn (legacy /api/chat)
   │     └─ chat_turn()   → TurnRunner (turn_runner.py) streaming turn on a worker thread
   │            ├─ Router (router.py) → providers/* (Gemini streams + thought summaries + images)
   │            ├─ TOOL_REGISTRY.call_tool (tools.py): permission check → handler → tool.start/end events
   │            │     tools registered by tool_setup.register_all_tools():
   │            │     agent_runtime · landscape_tools · (system_info · machine_tools · computer_control · email_client · tts)
   │            ├─ skills.py (attach by trigger) · memory · RAG · personality
   │            └─ ToolContext (tool_context.py): turn id, role, sink, pending images, cancel flag
   │
   ├─ agent_events.BUS   pub/sub with replay: channels ui, activity, turn:<id>
   ├─ permissions.POLICY per-category allow/ask/block (default allow), approvals
   ├─ agent_team.AGENT_TEAM live team state; agent_runtime syncs it from agent_roster.json
   ├─ ui_state (theme tokens the AI may change) · uploads (files/images) · vision (Gemini)
   └─ auth / server_auth: deny-by-default session middleware once an owner exists
launcher.py (pythonw, tray) runs uvicorn on a thread; setup_nyx.py installs shortcuts/link/autostart
```

## Key invariants (from AGENTS.md)
1. Every `/api/*` route is gated once the install is claimed (`server_auth.PUBLIC_PATHS` allowlist).
2. Declarative specs (tabs, skills, widgets, theme) are data, never executed code. Tools that run
   commands or code are explicit, permissioned, visible tools.
3. Overlay/profile customization never mutates base modules.
4. Nothing publishes without human review (change pipeline).
5. No credential in source, logs, HTTP responses or chat history. Keys: `.env.local` / `secret_store.py`.
6. Every persistent file path goes through `paths.py` (`data_path`, `project_path`) — never CWD-relative.
7. Never depend on a home-built `.exe` to start (Windows Smart App Control blocks it).

## Turn event schema (SSE `data: {json}`)
`turn.start {turn_id, chat_id, mode}` · `status {text, phase}` · `thought` / `thought.delta {text, agent?}`
· `agent.update {agent_id, name, emoji, status: working|done|error, step, result_preview?}`
· `skill.used {skills}` · `skill.created {skill}` · `tool.start {call_id, name, label, args, category}`
· `tool.progress {call_id, text}` · `tool.image {call_id, data_url, width, height}` · `tool.end {call_id, ok, preview, ms}`
· `approval.request {id, category, summary, detail}` · `approval.resolved {id, approved}`
· `answer.delta {text}` · `answer.reset {}` · `done {reply, provider, elapsed_ms, chat_id, turn_id}` · `error {message}`

## Workspace event schema (`/api/events/stream?channels=ui,activity`)
`ui.theme {theme}` · `ui.open_tab {tab_id}` · `tabs.changed` · `agents.changed` · `skills.changed`
· `notify {text, level}` · `computer.action {kind, x, y, label}` · `voice.say {text, role}`

Full contracts (every route shape and component prop): `OVERHAUL_CONTRACTS.md` in the project root.

## Frontend
`frontend/nyx-pulse/` — Vite + React 19 + TypeScript, no router; `App.tsx` holds the shell and the
active tab; panels in `src/panels/`; `src/api.ts` is the typed fetch client (adds the bearer token);
`npm run build` writes `dist/`, which the engine serves. There is no frontend test runner — `tsc` is
the gate.
