# 02 — Features in the app today

Status key: **Live** = works end to end in the UI · **Backend** = API/tools work, no UI (or old UI)
· **Stub** = present but thin · **Planned** = designed, not built.

## Starting and running
| Feature | Where | Status |
|---|---|---|
| One-click start: `Start Nyx.bat` first-run setup (Python via winget, venv, packages, shortcuts) | `Start Nyx.bat`, `setup_nyx.py` | Live |
| Desktop + Start Menu "Nyx Ichos" shortcuts, `nyx://start/open/stop/restart/redeem` link | `setup_nyx.py`, `launcher.py` | Live |
| Tray icon (Open, Restart, Start with Windows, data folder, log, Quit), single instance | `launcher.py` | Live |
| "Turn on Nyx" full-screen gate + offline page via service worker | `EngineGate.tsx`, `engine.ts`, `public/sw.js` | Live |
| Engine control routes (status, stop, restart, autostart) | `server.py` `/api/engine*` | Live |
| Release zip for other PCs (secret-scanned) | `build_release.py` | Live |
| Public download site | `site/index.html` (Vercel) | Live |

## Chat and thinking
| Feature | Where | Status |
|---|---|---|
| Chat with automatic provider routing (Gemini default, Groq, OpenAI, Claude, DeepSeek, Kimi, Perplexity, Ollama, custom OpenAI-compatible) | `router.py`, `providers/` | Live |
| Fast path for simple turns, full tool pipeline otherwise | `fast_response.py`, `chat_service.py` | Live |
| Streaming turns: status, thought summaries, tool steps, images, answer tokens, stop | `turn_runner.py`, `routes_live.py` `/api/chat/stream`, `/api/chat/stop` | Backend |
| Multiple chats as tabs: list, create, rename, delete, messages | `/api/chats/*` | Backend |
| Branch a chat | `/api/chats/fork` | Live |
| Background thinking (long research) | `thought_loop.py`, `/api/think` | Backend |
| Memory (facts, important items), RAG over memory | `memory.py`, `rag_memory.py` | Live (Sessions & Memory tab) |
| Personalities, learned speech style | `personalities.py`, `speech_patterns.py` | Live |
| Knowledge bases (general, finance) and math engine | `knowledge.py`, `math_engine.py` | Backend |

## Agents and skills
| Feature | Where | Status |
|---|---|---|
| 18-agent default roster (Manager + Coder, Web Design, App Design, Finance, Educator, Tech, Hardware, News, Researcher, Writer & Editor, Email & Comms, Computer Operator, Data Analyst, Security, Planner, Creative & Game Design, Travel) | `agent_roster.json`, `agent_runtime.py` | Backend |
| Delegate a task / several in parallel to specialists, with live `agent.update` events | tools `delegate_task`, `delegate_parallel` | Backend |
| Create a new agent from chat | tool `create_agent` | Backend |
| Agent team status | `agent_team.py`, `/api/agents`, Agents tab | Stub (polls, not live) |
| Skills library (built-in + 40 curated), auto-attach by trigger | `skills.py`, `skills_library.json` | Live (Add capability tab) |
| Skill search, temporary task skills, keep a temp skill | tools `search_skills`, `use_skill`, `create_temp_skill`; `/api/skills/search`, `/api/skills/{id}/keep` | Backend |
| Export a skill for Claude / GPT / Gemini / AGENTS.md / generic | `skill_export.py`, `/api/skills/{id}/export` | Backend |
| Every agent is a / command; `/coder [3] task` opens a box per copy; copies run in parallel with their own tasks | `commands.agent_commands`, `agent_dispatch.py`, `components/agents/AgentBoxes.tsx`, `/api/dispatch*` | Live |
| Nyx brings in the matching sub-agent by itself; can dispatch several copies (`dispatch_agents`) | `agent_match.py`, `turn_runner.py`, `agent_dispatch.py` | Live |
| Second Brain → Core view: glowing core, gauges, APIs, markets, sub-agents (drag/Run/+), processes, project dock, voice channel | `components/brain/CoreView.tsx`, `routes_core.py` `/api/core/overview` | Live |
| Improve → Review changes (approve/deny, Analyze all, Let Nyx decide and apply) and Deep & specific mode | `improve_review.py`, `improve_deep.py`, `panels/improve/*` | Live |
| Nyx reads its own project handoff | `handoff_tools.py` tool `read_handoff`, `/handoff` | Live |
| Collab: testers send changes (→ GitHub PRs) and feedback (→ issues); live list on the site and in Nyx | `site/collab/`, `site/api/collab/*`, `beta_collab.py`, Collab tab | Backend+UI built; needs Vercel env (`docs/COLLAB_SETUP.md`) |

## Tools, permissions, machine
| Feature | Where | Status |
|---|---|---|
| 53 tools with permission categories and timeline labels | `tools.py`, `tool_setup.py` | Backend |
| Owner-controlled permissions per category (allow / ask / block), approvals | `permissions.py`, `/api/permissions`, `/api/approvals` | Backend |
| Web search and page reading | `web_access.py` | Live |
| Vision: describe an image, find a point on screen | `vision.py` | Backend |
| File and image uploads with PDF/DOCX text extraction | `uploads.py`, `/api/uploads` | Backend |
| Obsidian vault read/write/search | `connectors/obsidian_connector.py` | Backend |
| Finance quotes, history, market status | `finance.py`, connector | Backend |
| YouTube/Google open, clipboard, screenshot | connectors | Backend |
| Shell, Python, file ops (Recycle Bin deletes), processes, power, volume, media keys, toasts, clipboard, apps | `machine_tools.py` (25 tools) | Live |
| Computer control with visible AI cursor, in-app Stop banner, Esc×3 / corner failsafe | `computer_control.py`, `cursor_overlay.py`, `routes_computer.py`, `ComputerBanner.tsx` | Live (supervise first real run) |
| Email: accounts with app passwords (IMAP read/search, SMTP send/reply), Outlook COM, webmail draft fallback | `email_client.py`, `routes_email.py`, Keys tab → Email | Live |
| API keys for every provider (NVIDIA free keys, Gemini, Groq, OpenAI, Claude, DeepSeek, Kimi, AWS 4-field, custom) | `routes_models.py`, Keys & Models tab | Live |
| Model per job (image check, reading text, image gen, UI pointing, code, fast chat, custom), announced by user UI and Nyx | `model_roles.py`, `model_hub.py` (AWS SigV4), `media_tools.py`, chat model chips | Live |
| Image generation (NVIDIA FLUX, OpenAI, Gemini, AWS Nova Canvas, Pollinations free fallback) shown in chat | `image_gen.py`, `MessageBubble.tsx` gallery | Live |
| Apple HIG design references for Claude and Nyx (122 guidelines) | `skills/apple-design/`, `connectors/apple_design_connector.py` | Live |
| Neural voices (edge-tts, SAPI fallback) + a voice per role/agent, chat "Listen", Settings → Voices | `tts.py`, `routes_voice.py`, `src/voice/voicePlayer.ts`, `VoicesSection.tsx` | Live |
| Dashboard: This PC specs, Right now (per-core CPU, memory, NVIDIA GPU, disk/net rates, battery), busiest programs | `system_info.py`, `SystemCards.tsx` | Live |
| Self-improvement: Nyx analyzes its own base code (goal, time budget, full power) and files drafts for owner approval — Improve tab, chat tools, no auto-apply | `improvement_engine.py`, `routes_improve.py`, `improve_tools.py`, `ImprovePanel.tsx`, review gate | Live |

## Workspace
| Feature | Where | Status |
|---|---|---|
| Top tab bar, find-or-create tab (Ctrl+K) | `TopTabs.tsx`, `TabFinder.tsx` | Live |
| User-defined declarative tabs (notes, checklist, chat, text blocks), AI design from a description | `dynamic_tabs.py`, `DynamicTab.tsx` | Live |
| Conversational tab edits with edit history | `tab_editor.py`, `/api/tabs/{id}/edit` | Live |
| AI can change theme, open/create/edit/delete tabs, notify | `landscape_tools.py`, `ui_state.py`, `/api/ui/*` | Backend |
| Workspace event stream (theme, tabs, agents, skills, notifications) | `agent_events.py`, `/api/events/stream` | Backend |
| Strands 3D-ish visualisation, Ichnos animated avatar | `StrandsPanel.tsx`, `NyxAvatar.tsx` | Live |
| Power modes (resource governor), models/providers picker, connectors list | panels | Live |

## Accounts and admin
| Feature | Where | Status |
|---|---|---|
| Owner claim, login, roles (owner/admin/beta/user), invites | `auth.py`, `server_auth.py`, `/api/auth/*`, `/api/admin/*` | Live (basic UI) |
| Change review pipeline (draft → reviewed → approved → published, rollback) | `change_review.py`, `overlay.py` | Live (Admin tab) |
| Beta/developer access keys (signed), admin access server, beta site | `access_keys.py`, `routes_access.py`, `admin_server.py`, `site/beta/` | Planned |
