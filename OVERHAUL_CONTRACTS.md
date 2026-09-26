# OVERHAUL_CONTRACTS.md — the 2026-09-12 overhaul, as interfaces

**Every agent reads `AGENTS.md`, then this file, before touching anything.**
This is the single source of truth for *who owns which file* and *what shape every
interface has*. If you need a shape that is not here, ask the Lead in your report —
do not invent a parallel one.

---

## 0. The requests, verbatim (do not edit)

Goal (owner, 2026-09-12):
```text
I want to continue the AI improvement plan. For one, downloading should be much easier. The website is running nicely but running the AI should be easier, whether a command in the cmd or whatever else, make this a basic one or two click so the user doesnt have to copy and paste anything or ask an AI to do it for them. In addition, Make the tab editting much better so the aI works better, tells the suer what its doing, user can see as the AI works and much more., Also after giving a prompt the AI should be showing taht its working, and what its working on, and thought process. Nothing should be restricted unless User asks for it. Also make it much more versitile. The AI seems to have issues with emails and such. It should be able to interact wioth the machine on every level. Also allow computer control. Give it a mouse the User can see. Make sure the AI talking is better. Multiple voices. Also make better animations but also keep some space so in teh future I can give the webUi and the App Ui to a better model specifically for web/app design for the best transitions. If you can make it better with 3d and such but at the moment do what you can. Next the AI tabs should be better simialr to google tabs. Also the web cannot read and displkay the correct PC specs and details, and data, fix. Finally, make it smarter. Also Allow tthe AAI much moree control on the suer for designing the AI landscae. Allow picture uploads and file uploads. It could downlaod the image off the user computer or just look at it and understand it.
```

Follow-up 1:
```text
Create 4 subagents. 1 manger, everything goes through this. 1 coer and dev, 1 idea maker, and 1 designer Make subagents betetr on this AI and amke sure they listena nd understand. Actively show the agents created. Skills created. Temp skills specifically for the taskl the AI can show the user it maddde for best efficency. ALso alllow searches where it can see what skills to use, also copy for otehr AI liek Opus, GPT Sol and Asstra, Fable 5.1 and more. The agents dont show, skills, connectors as well. Improve as well. This should be a massive oevrhall for all suers and include a way for me to get beta testers and devs on here. WIth skills I have mentioned befopre. whetehr through a specific key or a new site taht links to the og.
```

Follow-up 2:
```text
Refert.I was refering to you, claude code to making those 4 agents. The agents for the AI should be very default with manager, coder, web design, App design, Finance, educator, tech, hardware, news, and such
```

---

## 1. Team and file ownership (disjoint — never edit another owner's file)

| Agent | Owns |
|---|---|
| **Lead** (main Claude session, integrator) | `chat_service.py` `tools.py` `router.py` `providers/**` `server.py` `agent_team.py` `skills.py` `dynamic_tabs.py` `tab_editor.py` `fast_response.py` `config.py`; new `agent_events.py` `tool_context.py` `permissions.py` `vision.py` `uploads.py` `ui_state.py` `agent_runtime.py` `landscape_tools.py`; frontend `src/App.tsx` `src/api.ts` `src/stream.ts` `src/hooks/useEventStream.ts` `src/panels/ChatPanel.tsx` `src/panels/DynamicTab.tsx` `src/panels/AgentsPanel.tsx` `src/panels/StorePanel.tsx` `src/panels/ConnectorsPanel.tsx` `src/components/TabFinder.tsx` `src/components/chat/**`; `tests/test_server_auth.py` and tests for the above; `AGENTS.md` |
| **Coder & Dev** | new `system_info.py` `computer_control.py` `cursor_overlay.py` `machine_tools.py` `email_client.py` `access_keys.py` `tts.py` `setup_nyx.py` `routes_system.py` `routes_computer.py` `routes_email.py` `routes_access.py` `routes_voice.py`; existing `launcher.py` `device_profile.py` `hardware_safety.py` `voice.py` `connectors/system_control.py` `connectors/app_launcher.py` `nyx.spec` `requirements.txt` `*.bat` `*.cmd` `nyx.sh`, outer folder `../Start Nyx.vbs` `../Start Nyx.bat` `../start.bat` `../install.bat`; tests `tests/test_<each module above>.py` |
| **Designer** | `frontend/nyx-pulse/src/design/**` `src/theme.css` `src/index.css` `src/main.tsx`; components `TabStrip.tsx` `NewTabPage.tsx` `ContextMenu.tsx` `Toasts.tsx` `Orb3D.tsx` `NyxAvatar.tsx` `StrandField.tsx` `TopTabs.tsx` `Panel.tsx` `ProviderPicker.tsx` `VoiceStudio.tsx` `AuthScreen.tsx`; `src/hooks/useTabs.ts`; `src/voice/**`; panels `SystemPanel.tsx`(new) `ComputerPanel.tsx`(new) `DeveloperPanel.tsx`(new) `AccessPanel.tsx`(new) `PermissionsPanel.tsx`(new) `DashboardPanel.tsx` `SettingsPanel.tsx` `PowerPanel.tsx` `AdminPanel.tsx` `ModelsPanel.tsx` `WorkPanel.tsx` `StrandsPanel.tsx`; `src/tabs.ts`; `package.json`; `site/**`; `DESIGN_HANDOFF.md` |
| **Idea Maker** | `IDEAS_OVERHAUL.md` `agent_roster.json` `skills_library.json` `skill_export_templates.json` `beta_program.md` — content and data only, no code |
| **Manager** | `NYX_WORKPLAN.md` (task board + review log). Reviews every delivery **by execution**. Edits no source. |

Everything routes through the Manager: a workstream is not "done" until the Manager has
run it and signed it off in `NYX_WORKPLAN.md`.

### 1.1 Status update 2026-09-13 (read this — it overrides the table where they differ)

- **Already landed (Lead), do not rebuild:** `agent_events.py`, `tool_context.py`,
  `permissions.py`, `vision.py` (verified live against Gemini), tool `category`/`label` +
  central permission enforcement + `tool.start`/`tool.end` events in `tools.py`, Gemini
  streaming/thought summaries/images in `providers/gemini_provider.py`.
- **One-click engine is DONE (Lead)** — the Coder's former deliverable 7. Lead now owns
  `launcher.py`, `setup_nyx.py`, `Start Nyx.bat`, the `*.bat`/`*.cmd` wrappers, `build_release.py`,
  `src/engine.ts`, `src/components/EngineGate.tsx`, `public/sw.js`, and the `/api/engine*` routes.
  Root cause was Windows Smart App Control blocking the unsigned `Nyx.exe`: **never make any entry
  point depend on a home-built .exe.**
- The Lead edited these Designer-owned files for the engine work; build on the current contents:
  `src/components/Panel.tsx` (ErrorState), `src/panels/SettingsPanel.tsx` (EngineSection),
  `src/index.css` (`.engine-gate*` styles appended), `src/main.tsx` (service-worker registration),
  `site/index.html` (Launch Nyx button, new download steps).
- The first team launch died on the account session limit. Work economically: read only the
  parts of large files you need (`server.py` is ~2.4k lines, `chat_service.py` ~800), and do not
  re-read files you have already read.

### 1.2 Round 2 team — 2026-09-13 evening (overrides §1 and §1.1 where they differ)

Owner's request E is in `AI_HANDOFF/01_GOALS.md`. Ownership for this round:

| Agent | Owns |
|---|---|
| **Lead** (main session) | `routes_live.py` `turn_runner.py` `chat_service.py` `agent_runtime.py` `agent_team.py` `server.py` `tools.py` `launcher.py` `setup_nyx.py`, `AI_HANDOFF/**`, `src/components/chat/types.ts`, `OVERHAUL_CONTRACTS.md` |
| **Coder A — Access** | new `access_keys.py` `routes_access.py` `admin_server.py` `access_public_keys.json`, `site/beta/**`, tests `tests/test_access_keys.py` `tests/test_routes_access.py` `tests/test_admin_server.py` |
| **Coder B — Learning** | new `learning.py` `response_cache.py` `client_state.py` `routes_learning.py`, tests `tests/test_learning.py` `tests/test_response_cache.py` `tests/test_client_state.py` `tests/test_routes_learning.py` |
| **Designer** | `src/components/chat/**` except `types.ts`; `src/design/**`; `DESIGN_HANDOFF.md` |
| **Integrator** | `src/stream.ts` `src/hooks/**` `src/state/**` `src/api.ts` `src/App.tsx` `src/panels/ChatPanel.tsx` `src/panels/AgentsPanel.tsx` `src/panels/StorePanel.tsx` `src/panels/ConnectorsPanel.tsx`; the only agent that runs `npm run build` |
| **Idea Maker** | `IDEAS_ROUND2.md` |
| **Manager** | `NYX_WORKPLAN.md`, `AI_HANDOFF/04_STATUS_AND_NEXT.md` |
| **Critic** | `REVIEW_LOG.md` — reviews and approves or rejects; edits no source |

Design language: the Apple Human Interface Guidelines skill references at
`C:\Users\shagn\AppData\Roaming\Claude\local-agent-mode-sessions\skills-plugin\ca8cd84f-a11e-4ddf-921b-13f7b82b1639\d2a95da8-c160-42e9-b024-cc939296474f\skills\apple-design\references\hig\`
(the owner mentioned a GitHub design link that did not come through; use HIG until it does).

---

## 2. Foundation (Lead lands these first; everyone codes against them)

### 2.1 `agent_events.py` — in-process pub/sub
```python
from agent_events import BUS, publish_ui, publish_activity
BUS.publish(channel: str, event: dict) -> None      # adds "ts" if missing; never raises
with BUS.subscribe(["ui", "activity"]) as sub:       # thread-safe queue per subscriber
    event = sub.get(timeout=15.0)                    # dict | None on timeout
publish_ui(type: str, **payload)                     # channel "ui"
publish_activity(type: str, **payload)               # channel "activity"
```
Channels: `ui`, `activity`, `turn:<turn_id>`.

### 2.2 `tool_context.py` — what a running tool can reach
```python
from tool_context import current, emit, progress, attach_image
ctx = current()           # ToolContext | None  (None outside a chat turn — tools must still work)
ctx.turn_id; ctx.chat_id; ctx.role   # role: "local" | "owner" | "admin" | "beta" | "user"
emit(type: str, **payload)           # publishes on this turn's channel; no-op outside a turn
progress(text: str)                  # emit("tool.progress", text=...)
attach_image(data: bytes, mime: str, name: str = "", note: str = "")
    # the model SEES this image on its next call in this turn; a thumbnail event goes to the UI
```

### 2.3 `permissions.py` — nothing is restricted unless the user says so
```python
from permissions import POLICY, require, PermissionDenied, is_protected_path
require(category: str, summary: str, detail: str = "") -> None
    # mode "allow": return   | "block": raise PermissionDenied(text for the model)
    # mode "ask": emit approval.request on the turn, wait <=180s for POST /api/approvals/{id}
POLICY.snapshot() -> {"categories": {cat: mode}, "descriptions": {cat: str}, "protected_paths": [..]}
```
Categories: `web` `files.read` `files.write` `files.delete` `shell` `code` `apps` `windows`
`computer` `system` `clipboard` `email.read` `email.send` `network` `ui` `agents` `memory` `general`.
Default mode for every category: **allow**. The owner changes modes in the Permissions panel or by
asking the AI. On a *claimed* install, accounts other than owner/admin get `block` for
`shell code files.write files.delete apps windows computer system email.send` unless the owner
sets `accounts_inherit: true` — the owner's machine is not handed to invitees by default.

### 2.4 Tool registration (`tools.py`)
```python
TOOL_REGISTRY.register(
    name, description, parameters, handler,
    category: str = "general",                         # permission category, enforced centrally
    label: str | Callable[[dict], str] | None = None,  # "Running: Get-Process" — shown in the UI
)
```
`call_tool()` enforces the category, emits `tool.start` / `tool.end` with timing, converts
`PermissionDenied` into a readable result. Handlers:
- return a **string** for the model, ideally < 8 000 chars (truncate with a note);
- call `progress()` during long work; call `attach_image()` to let the model see something;
- never block forever — every subprocess/network call has a timeout.

### 2.5 `vision.py` (Lead)
```python
from vision import locate_point, describe_image
locate_point(image: bytes, mime: str, description: str) -> tuple[float, float] | None
    # normalised (x, y) in 0..1 of the image, via a vision-capable provider (Gemini first)
describe_image(image: bytes, mime: str, question: str = "") -> str
```

---

## 3. Event schemas

### 3.1 Chat turn stream — `POST /api/chat/stream` (SSE, `data: {json}\n\n`)
```
turn.start       {turn_id, chat_id, mode: "fast"|"full"}
status           {text, phase?: "route"|"think"|"agents"|"skills"|"tool"|"answer"}
thought          {text, agent?}                 thought.delta {text, agent?}
agent.update     {agent_id, name, emoji?, status: "working"|"done"|"error", step, understanding?, result_preview?}
skill.used       {skills: [{id, name, source, temp}]}
skill.created    {skill: {id, name, description, instructions, triggers, temp: true}}
tool.start       {call_id, name, label, args, category}
tool.progress    {call_id?, text}
tool.image       {call_id?, name, data_url, width, height}
tool.end         {call_id, name, ok, preview, ms}
approval.request {id, category, summary, detail}   approval.resolved {id, approved}
answer.delta     {text}                          answer.reset {}
done             {reply, provider, model?, elapsed_ms, chat_id, turn_id}
error            {message}
```

### 3.2 UI bus — `GET /api/events/stream?channels=ui,activity` (SSE)
```
ui.theme        {theme}                  ui.open_tab {tab_id}
tabs.changed    {tab_id?, action}        agents.changed {}      skills.changed {}
notify          {text, level: "info"|"ok"|"warn"|"error"}
computer.action {kind: "move"|"click"|"type"|"keys"|"scroll"|"drag"|"screenshot", x?, y?, text?, label}
computer.state  {active, overlay}
voice.say       {text, role?: "reply"|"narrator"|<agent id>}
```

---

## 4. HTTP contracts

New route modules expose `router = fastapi.APIRouter()`; the Lead includes them in `server.py`.
All `/api/*` paths are already session-gated by middleware once an install is claimed; use
`server_auth.RequireAdmin` for admin-only routes. Each route module ships a test asserting its
GET routes return 401 once claimed (copy `test_data_routes_require_a_session_once_claimed`).

### 4.1 System (Coder) — accurate specs, never invented numbers
`GET /api/system/specs?refresh=0|1` -> (unknown fields are `null`, never guessed)
```json
{"os":{"name":"Windows 11 Home","version":"24H2","build":"26200","arch":"AMD64","hostname":"","user":"","uptime_seconds":0},
 "device":{"manufacturer":"","model":"","bios":"","motherboard":""},
 "cpu":{"name":"AMD Ryzen AI 9 HX 370 w/ Radeon 890M","vendor":"AMD","cores":12,"threads":24,"max_mhz":0},
 "memory":{"total_gb":31.3,"speed_mhz":0,"modules":[{"capacity_gb":16,"speed_mhz":0,"manufacturer":"","part":""}]},
 "gpus":[{"name":"","vendor":"NVIDIA","vram_gb":16.0,"driver":""}],
 "disks":[{"model":"","size_gb":0,"media":"SSD","bus":"NVMe"}],
 "volumes":[{"mount":"C:\\","fs":"NTFS","total_gb":0,"free_gb":0,"percent":0}],
 "displays":[{"name":"","width":0,"height":0,"refresh_hz":0,"scale_percent":0,"primary":true}],
 "network":[{"name":"","ipv4":"","mac":"","speed_mbps":0,"up":true}],
 "battery":{"present":true,"percent":0,"plugged":true,"seconds_left":null},
 "collected_at":0}
```
`GET /api/system/live` ->
```json
{"cpu":{"percent":0,"per_core":[],"freq_mhz":0},"memory":{"used_gb":0,"total_gb":0,"percent":0},
 "gpus":[{"name":"","util_percent":0,"vram_used_mb":0,"vram_total_mb":0,"temp_c":0,"power_w":0}],
 "disk_io":{"read_bps":0,"write_bps":0},"net_io":{"sent_bps":0,"recv_bps":0},
 "battery":{},"top_processes":[{"pid":0,"name":"","cpu_percent":0,"memory_mb":0}],"ts":0}
```
Also fix `device_profile.py` (CPU name came from `platform.processor()` = "AMD64 Family 26 Model
36…"; the stale cached value must be refreshed). Tools: `system_specs`, `system_live` (`general`).

### 4.2 Computer control (Coder) — a mouse the user can see
`GET /api/computer/state` -> `{"active":bool,"overlay":bool,"cursor":{"x":0,"y":0},"screen":{"width":0,"height":0,"monitors":[]},"last_action":null,"actions":[]}`
`GET /api/computer/screenshot?max_width=1280&cursor=1` -> `image/jpeg` (AI cursor drawn when cursor=1)
`POST /api/computer/overlay {"enabled": bool}` -> state · `POST /api/computer/stop` -> state (aborts any sequence)

Tools: `screen_view` (attach_image), `find_on_screen(description)`, `mouse_move`, `mouse_click`
(x,y **or** `target` description), `mouse_drag`, `mouse_scroll`, `keyboard_type`, `keyboard_keys`
— category `computer`; `list_windows`, `focus_window`, `window_action` — `windows`; `open_app`,
`open_path` — `apps`; `open_url` — `web`.
The desktop overlay (`cursor_overlay.py`, tkinter, click-through, topmost) shows a labelled AI
cursor gliding to each target with a click ripple. Every action publishes `computer.action`.
The user stays in charge: slamming the real mouse into the top-left corner, or Esc pressed three
times, aborts the running sequence.

### 4.3 Machine tools (Coder, `machine_tools.register_machine_tools(TOOL_REGISTRY)`)
`run_command(command, shell="powershell"|"cmd", cwd="", timeout_seconds=120)` shell ·
`run_python(code, timeout_seconds=120)` code · `write_file(path, content, append=false)`
`make_folder` `move_path` `copy_path` files.write · `delete_path(path, permanent=false)`
files.delete (Recycle Bin unless permanent) · `search_files(query, root="", limit=50)` `file_info`
`list_drives` files.read · `download_file(url, path="")` network · `list_processes` general ·
`kill_process` system · `set_volume` `media_key` `lock_screen` `system_power` system ·
`notify(title, message)` apps · `clipboard_get` `clipboard_set` clipboard ·
`view_image(path)` files.read (attach_image, resized <= 1600px) · `get_environment()` general.
`is_protected_path()` is honoured for reads/writes of credential files.

### 4.4 Email (Coder) — the thing that visibly failed before
Accounts in `data_path("email_accounts.json")`; passwords only in `secret_store` (never returned).
`GET /api/email/accounts` -> `{"accounts":[{"id","address","provider","send","read","configured"}],"outlook_app_available":bool}`
`POST /api/email/accounts {address, app_password?, imap_host?, imap_port?, smtp_host?, smtp_port?}` (verifies login when a password is given)
`DELETE /api/email/accounts/{id}` · `POST /api/email/test/{id}` -> `{ok, detail}`
Tools: `email_send(to, subject, body, cc="", bcc="", account="", attachments=[])` email.send ·
`email_list(account="", folder="INBOX", query="", unread_only=false, limit=10)` email.read ·
`email_read(message_id, account="")` email.read · `email_reply(message_id, body, account="")`
email.send · `email_compose(to, subject, body)` apps (opens a pre-filled compose window).
Send chain with no stored password: Outlook desktop (COM) -> webmail compose deep link (Gmail /
Outlook Web by domain) in the browser, then, when `computer` is allowed, click Send with the
visible cursor and confirm by screenshot; otherwise say it is ready for the user to press Send.

### 4.5 Voice (Coder backend, Designer frontend) — multiple, better voices
`GET /api/voice/engines` -> `{"engines":[{"id":"browser","available":true},{"id":"edge","available":bool,"note":""},{"id":"sapi","available":bool}]}`
`GET /api/voice/neural-voices?locale=en` -> `{"voices":[{"id":"en-US-AriaNeural","name":"Aria","locale":"en-US","gender":"Female","engine":"edge"}]}`
`POST /api/voice/tts {text, voice, rate?:"+0%", pitch?:"+0Hz", engine?:"edge"|"sapi"}` -> `audio/mpeg` | `audio/wav`
Tool `speak` publishes `voice.say` so the browser speaks in the chosen voice.

### 4.6 Beta & developer access (Coder backend, Designer UI + site)
Key: `NYX1-<b64url(payload)>.<b64url(ed25519 sig)>`; payload
`{"v":1,"kid","id","role":"beta"|"dev","name","iat","exp"}` (exp 0 = never). Pure-Python Ed25519
(RFC 8032, tested against its vectors) — no new dependency. Public keys ship in
`access_public_keys.json`; the private key stays in `secret_store`.
`GET /api/access/status` -> `{"level":"owner"|"dev"|"beta"|"standard","keys":[{"id","role","name","exp","valid"}],"features":{"developer_panel":bool,"labs":bool,"feedback":bool},"signing_ready":bool}`
`POST /api/access/redeem {key}` -> status | 400 with the reason
`POST /api/access/signing-key` (admin) -> `{kid, public_key}` · `POST /api/access/mint {role, name, days}` (admin) -> `{key, redeem_link:"nyx://redeem?key=…", invite_text}`
`GET /api/access/minted` (admin) -> `{"keys":[…]}` · `POST /api/access/revoke/{id}` (admin)

### 4.7 Lead-owned
`POST /api/uploads` (raw body, `X-Filename`, `Content-Type`) -> `{id,name,mime,size,kind,width?,height?}` ·
`GET /api/uploads/{id}` · `POST /api/chat/stream` (§3.1, body = ChatRequest + `attachments:[id]`) ·
`POST /api/approvals/{id} {approve}` · `GET|POST /api/permissions` · `GET /api/events/stream` ·
`GET|POST /api/ui/state` · `POST /api/tabs/{id}/edit/stream` (SSE: `step`, `thought`, `preview`,
`applied {tab, summary, changed_blocks}`, `error`) · `POST /api/tabs/{id}/undo` ·
`GET /api/skills/search?q=` · `GET /api/skills/{id}/export?format=` · `POST /api/tools/run` (admin; dev panel).

Theme tokens (`ui_state.theme`, all optional):
`{"accent","accent2","background","surface","nav","text":"#rrggbb","radius":0-24,"font":"Inter"|…,"density":"comfortable"|"compact","glass":bool,"motion":"full"|"reduced"|"off","wallpaper":{"type":"none"|"gradient"|"orb","value":""}}`

---

## 5. Frontend component contracts (Designer builds, Lead wires into `App.tsx`/`ChatPanel.tsx`)

```ts
// src/components/TabStrip.tsx — Chrome-style tab strip
export interface StripTab { key: string; title: string; icon?: string; kind: "core"|"user"|"chat"|"newtab";
  pinned?: boolean; busy?: boolean; accent?: string; closable?: boolean; description?: string }
<TabStrip tabs activeKey onSelect(key) onClose(key) onNew() onReorder(from, to) onPin(key, pinned)
  onCloseOthers(key) onReopenClosed() onDuplicate?(key) />

// src/hooks/useTabs.ts — open-tab model, persisted to localStorage "nyx.tabs.v2"
// keys: "core:<id>" | "user:<tabId>" | "chat:<chatId>" | "new:<n>"
useTabs({ coreTabs, userTabs }) -> { open, activeKey, select, openKey, close, newTab, reorder, pin,
  closeOthers, reopenClosed, rename }
// keyboard: Ctrl+T, Ctrl+W, Ctrl+Tab, Ctrl+Shift+Tab, Ctrl+1..9, Ctrl+Shift+T

// src/components/NewTabPage.tsx
<NewTabPage coreTabs userTabs recentChats onOpen(key) onPrompt(text) onCreateTab() />

// src/components/Orb3D.tsx — three.js presence orb, lazy-loaded, CSS fallback without WebGL
<Orb3D state="idle"|"thinking"|"working"|"speaking"|"listening"|"error" energy?={0..1} size?={px|"fill"} accent? />

// src/voice/voiceEngine.ts
listVoices(): Promise<VoiceOption[]>   // {id, name, lang, engine:"browser"|"edge"|"sapi", gender?, quality:"natural"|"standard"}
speak(text, {voiceId?, role?, rate?, pitch?}): Promise<void>
speakStreaming(role?): { push(delta: string): void; end(): void; cancel(): void }   // sentence-chunked
stop(); isSpeaking(); onEnergy(cb: (n: number) => void): () => void
getRoleVoice(role): string | null;  setRoleVoice(role, voiceId): void
listen({continuous?, onPartial?, onFinal}): { stop(): void }   // Web Speech API

// src/design/applyTheme.ts
applyTheme(theme: Partial<ThemeTokens>): void   // maps §4.7 tokens onto CSS variables
```
Panels consume §4 routes directly through `api` from `src/api.ts` (add typed helpers in your own
panel file, not in `api.ts`).

---

## 6. Idea Maker data contracts

`agent_roster.json` —
`{"version":1,"agents":[{"id","name","role":"master"|"worker","emoji","color":"#rrggbb","goal","instructions","expertise":[],"tools":["*"]|[names],"skills":[ids],"voice_hint"}]}`
Must include Manager (the only master), Coder, Web Design, App Design, Finance, Educator, Tech,
Hardware, News, plus sensible additions. Every `instructions` makes the agent *listen and
understand*: restate the task in one line, note constraints, ask one crisp question only when
genuinely blocked, otherwise proceed, and finish with a self-check.

`skills_library.json` — `{"version":1,"skills":[{"name","description","triggers":[],"instructions","category","agent"?}]}`

`skill_export_templates.json` — `{"formats":[{"id","label","filename","template"}]}` with
placeholders `{{name}} {{slug}} {{description}} {{instructions}} {{triggers_bullets}}`; formats for
Claude (SKILL.md — Opus 5 / Fable 5.1 / Sonnet 5), OpenAI GPTs, Gemini Gems, AGENTS.md coding agents, generic.

---

## 7. Rules for every agent

- Python: `.venv/Scripts/python.exe` only. Test with a private basetemp so parallel runs do not
  collide: `.venv/Scripts/python.exe -m pytest tests/test_x.py -q -p no:cacheprovider --basetemp=local_pytest_tmp/<your-agent>`.
- Frontend type-check: `cd frontend/nyx-pulse && npx tsc --noEmit -p tsconfig.json`. Only the Lead
  runs `npm run build` (it rewrites `dist/app/` that the live server serves).
- Do not install packages — everything needed is installed (psutil, pillow, pystray, edge-tts,
  pypdf, three). Need another? Say so in your report.
- Do not use the Browser pane unless the Lead asks (one shared pane).
- No git commits. Never delete user data (`chats.json`, `memory.json`, `auth.json`, `tabs.json`…).
  Never print, log, or commit a secret.
- Tests must not move the real mouse, type into real windows, send email, or play audio — mock the
  OS boundary.
- Finish with a report: files changed, verification commands and their results, open issues,
  integration notes for the Lead.
