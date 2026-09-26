# API routes (generated)

Regenerate: `.venv/Scripts/python.exe AI_HANDOFF/generate_routes.py`

368 operations. Once an owner account exists every `/api/*` route needs a session, except `/api/health` and `/api/auth/*`.

Optional route modules: `routes_live` ok, `routes_system` ok, `routes_computer` ok, `routes_email` ok, `routes_access` ok, `routes_voice` ok, `routes_learning` ok, `routes_providers` ok, `routes_models` ok, `routes_improve` ok, `routes_intelligence` ok, `routes_notes` ok, `routes_code` ok, `routes_trading` ok, `routes_key_pool` ok, `routes_build` ok, `routes_game` ok, `routes_command_zone` ok, `routes_core` ok

## access

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/access/applications` | Admin List Applications |
| `POST` | `/api/access/applications/{app_id}/decision` | Admin Decide Application |
| `GET` | `/api/access/audit` | Admin Read Audit |
| `GET` | `/api/access/flags` | Admin Get Flags |
| `POST` | `/api/access/flags` | Admin Set Flags |
| `POST` | `/api/access/mint` | Admin Mint |
| `GET` | `/api/access/minted` | Admin List Minted |
| `POST` | `/api/access/redeem` | Redeem Access Key |
| `POST` | `/api/access/revoke/{key_id}` | Admin Revoke |
| `POST` | `/api/access/signing-key` | Admin Signing Key |
| `GET` | `/api/access/status` | Get Access Status |

## admin

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/admin/grant` | Change an account's role. Owner only. |
| `GET` | `/api/admin/invites` | List invites. Requires INVITE_TESTERS. |
| `POST` | `/api/admin/invites` | Mint a single-use beta invite and return its shareable link. |
| `GET` | `/api/admin/users` | List accounts. Requires VIEW_ADMIN. |

## agents

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/agents` | Live team status for the agent progress panel. |
| `POST` | `/api/agents` | Add one or more agents to the team. |
| `GET` | `/api/agents/details` | Every agent's goal, purpose, model, consult settings, status and recent work (Request H2). |
| `POST` | `/api/agents/subagents` | The Sub-agents tab: make one with its model and consult settings. |
| `DELETE` | `/api/agents/subagents/{agent_name}` | Delete Subagent Route |
| `DELETE` | `/api/agents/{agent_id}` | Remove an agent. Refuses to remove the master while workers remain. |
| `PATCH` | `/api/agents/{agent_name}` | Change an agent's objective, instructions, model, tools… Built-in agents keep edits as an overlay. |
| `GET` | `/api/agents/{agent_name}/chats` | Chats Of Agent |
| `GET` | `/api/agents/{agent_name}/properties` | One agent's settings, live status and recent work — the Properties sheet (Request G16b). |
| `POST` | `/api/agents/{agent_name}/tasks` | Hand one agent a task directly and watch it at /api/turns/{turn_id}/stream. |

## approvals

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/approvals` | List Approvals |
| `POST` | `/api/approvals/{approval_id}` | Answer Approval |

## auth

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/auth/claim` | Create the owner account on a fresh install, from the UI. |
| `POST` | `/api/auth/join` | Redeem a single-use invite and create the account. |
| `POST` | `/api/auth/login` | Exchange credentials for a session token. |
| `POST` | `/api/auth/logout` | Invalidate the caller's session. |
| `GET` | `/api/auth/me` | Return the signed-in account, or the unclaimed-install marker. |

## backgrounds

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/backgrounds` | List Backgrounds |
| `POST` | `/api/backgrounds` | Add Background |
| `POST` | `/api/backgrounds/active` | Set Active Background |
| `POST` | `/api/backgrounds/generate` | Nyx makes a wallpaper from words with the image model and applies it. |
| `PATCH` | `/api/backgrounds/{background_id}` | Update Background |
| `DELETE` | `/api/backgrounds/{background_id}` | Delete Background |

## brain

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/brain/at/{index}` | Brain Node At |
| `GET` | `/api/brain/edges` | Uint32 little-endian index pairs into /api/brain/points, strongest first. |
| `GET` | `/api/brain/node/{node_id}` | Brain Node |
| `GET` | `/api/brain/points` | Float32 little-endian, 6 per node: x, y, z, cluster, kind (0 memory · 1 concept · 2 source), weight. |
| `GET` | `/api/brain/recent` | Brain Recent |
| `POST` | `/api/brain/remember` | Brain Remember |
| `GET` | `/api/brain/search` | Brain Search |
| `POST` | `/api/brain/seed` | Brain Seed |
| `GET` | `/api/brain/summary` | Brain Summary |

## build

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/build/catalog` | Build Catalog List |
| `GET` | `/api/build/jobs` | Build Jobs |
| `DELETE` | `/api/build/jobs/{job_id}` | Build Stop Job |
| `GET` | `/api/build/library` | Build Library |
| `POST` | `/api/build/library` | Build Library Save |
| `GET` | `/api/build/library/{library_id}` | Build Library Part |
| `DELETE` | `/api/build/library/{library_id}` | Build Library Delete |
| `GET` | `/api/build/projects` | Build Projects |
| `POST` | `/api/build/projects` | Build Create Project |
| `GET` | `/api/build/projects/{project_id}` | Build Project |
| `PATCH` | `/api/build/projects/{project_id}` | Build Update Project |
| `DELETE` | `/api/build/projects/{project_id}` | Build Delete Project |
| `POST` | `/api/build/projects/{project_id}/apply-wiring` | Wire up the connections the owner ticked. Nothing is applied unasked. |
| `POST` | `/api/build/projects/{project_id}/ask` | One endpoint for every AI action, so the panel has one thing to call. |
| `POST` | `/api/build/projects/{project_id}/connect` | Build Connect |
| `POST` | `/api/build/projects/{project_id}/joints` | Build Add Joint |
| `DELETE` | `/api/build/projects/{project_id}/joints/{joint_id}` | Build Delete Joint |
| `DELETE` | `/api/build/projects/{project_id}/nets/{net_id}` | Build Disconnect |
| `PATCH` | `/api/build/projects/{project_id}/nets/{net_id}` | Build Update Net |
| `POST` | `/api/build/projects/{project_id}/parts` | Build Save Part |
| `DELETE` | `/api/build/projects/{project_id}/parts/{part_id}` | Build Delete Part |
| `POST` | `/api/build/projects/{project_id}/parts/{part_id}/duplicate` | Build Duplicate Part |
| `POST` | `/api/build/projects/{project_id}/place` | Build Place |
| `PATCH` | `/api/build/projects/{project_id}/placements/{placement_id}` | Build Update Placement |
| `DELETE` | `/api/build/projects/{project_id}/placements/{placement_id}` | Build Delete Placement |

## cache

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/cache/clear` | Cache Clear |
| `GET` | `/api/cache/stats` | Cache Stats |

## changes

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/changes` | Every proposed and published change, newest first. |
| `POST` | `/api/changes` | Record a proposed change. Always starts as a draft. |
| `POST` | `/api/changes/{change_id}/approve` | Approve Change |
| `POST` | `/api/changes/{change_id}/publish` | Publish an approved change and apply it to the overlay. |
| `POST` | `/api/changes/{change_id}/reject` | Reject Change |
| `POST` | `/api/changes/{change_id}/review` | Ask the AI to review a change, then move it into review. |
| `POST` | `/api/changes/{change_id}/rollback` | Revert a published change, removing its overlay entry. |

## chat

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/chat` | Send a message and receive a reply from the routed provider. |
| `POST` | `/api/chat/stop` | Chat Stop |
| `POST` | `/api/chat/stream` | Send a message and watch the turn happen (events: OVERHAUL_CONTRACTS.md §3.1). |

## chats

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/chats` | List all concurrently active chat services. |
| `POST` | `/api/chats` | Create Chat |
| `POST` | `/api/chats/fork` | Branch the conversation into a linked chat. |
| `GET` | `/api/chats/summaries` | Chat Summaries |
| `PATCH` | `/api/chats/{chat_id}` | Rename Chat |
| `DELETE` | `/api/chats/{chat_id}` | Delete Chat |
| `POST` | `/api/chats/{chat_id}/agent` | Give this chat to one agent (empty name hands it back to the Manager). |
| `POST` | `/api/chats/{chat_id}/branch` | A linked chat with the real messages up to ``upto``, to go another way from there. |
| `POST` | `/api/chats/{chat_id}/duplicate` | An exact, unlinked copy of a chat (Request G15: its own feature, not a side effect of New). |
| `POST` | `/api/chats/{chat_id}/fork` | A linked chat that starts from a summary of recent context. |
| `GET` | `/api/chats/{chat_id}/messages` | Chat Messages |
| `GET` | `/api/chats/{chat_id}/turn` | The turn running in this chat right now, if any — so reopening a chat can reattach. |

## client

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/client/state` | Read Client State |
| `PUT` | `/api/client/state` | Write Client State |
| `PATCH` | `/api/client/state` | Patch Client State |
| `DELETE` | `/api/client/state` | Delete Client State |

## code

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/code/ask` | Ask About Code |
| `GET` | `/api/code/file` | Read File |
| `PUT` | `/api/code/file` | Save File |
| `POST` | `/api/code/new-file` | New File |
| `POST` | `/api/code/new-folder` | New Folder |
| `POST` | `/api/code/pick-folders` | Open File Explorer's folder picker on this PC and open what the owner chooses. |
| `GET` | `/api/code/proposals` | List Proposals |
| `GET` | `/api/code/proposals/{proposal_id}` | Read Proposal |
| `POST` | `/api/code/proposals/{proposal_id}/apply` | Apply Proposal |
| `POST` | `/api/code/proposals/{proposal_id}/resolve` | Resolve Proposal |
| `POST` | `/api/code/proposals/{proposal_id}/undo` | Undo Proposal |
| `POST` | `/api/code/propose` | The model's edit as a diff to review. Nothing is written until it is applied. |
| `POST` | `/api/code/propose-files` | New files (an empty folder is fine) as a proposal to review. Nothing is written until applied. |
| `POST` | `/api/code/search` | Search Code |
| `POST` | `/api/code/start` | Start Project |
| `GET` | `/api/code/templates` | List Templates |
| `GET` | `/api/code/tree` | Folder Tree |
| `GET` | `/api/code/workspaces` | List Workspaces |
| `POST` | `/api/code/workspaces` | Open Workspace |
| `DELETE` | `/api/code/workspaces/{workspace_id}` | Close Workspace |

## command-zone

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/command-zone` | Everything the Command Zone shows: usage, tabs, and what is waiting for the owner. |
| `GET` | `/api/command-zone/glance` | The two numbers the chat bar shows: waiting for the owner, and turns running now. |
| `POST` | `/api/command-zone/items/{item_id}` | Approve or dismiss an idea or a tab suggestion. |
| `POST` | `/api/command-zone/items/{item_id}/restore` | Undo a Dismiss. |
| `POST` | `/api/command-zone/send` | Command Zone Send |

## commands

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/commands` | Every / command: built-in, owner-made, and one per enabled skill. |
| `POST` | `/api/commands` | Create Command |
| `POST` | `/api/commands/guess` | What an unknown /command probably meant, and a command to make if nothing fits. |
| `DELETE` | `/api/commands/{name}` | Delete Command |

## computer

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/computer/overlay` | Computer Overlay |
| `GET` | `/api/computer/screenshot` | Computer Screenshot |
| `GET` | `/api/computer/state` | Computer State |
| `POST` | `/api/computer/stop` | Computer Stop |

## connectors

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/connectors` | List all registered connectors and their health status. |
| `POST` | `/api/connectors/{name}/execute` | Execute an action on a named connector. |

## content-mode

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/content-mode` | Read Content Mode |
| `PUT` | `/api/content-mode` | Turn mature content on or off for this install. The four hard limits in content_mode.py stay. |

## core

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/core` | Core Snapshot |
| `GET` | `/api/core/complete` | Core Complete |
| `GET` | `/api/core/network` | Core Network |
| `GET` | `/api/core/overview` | Core Overview |
| `GET` | `/api/core/predict` | Core Predict |

## custom-models

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/custom-models` | List Custom Models |
| `POST` | `/api/custom-models` | Add a model by name, company, model id and key. It joins the model menu and failover like a built-in one. |
| `POST` | `/api/custom-models/check` | Try an address before adding it: is it valid, which models does it list, does a 1-token call answer? |
| `DELETE` | `/api/custom-models/{name}` | Remove Custom Model |

## dispatch

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/dispatch` | Dispatch Start |
| `GET` | `/api/dispatch` | Dispatch List |
| `POST` | `/api/dispatch/parse` | ``/coder [3] build X`` → the boxes to show before anything runs. |
| `GET` | `/api/dispatch/{dispatch_id}` | Dispatch Get |
| `POST` | `/api/dispatch/{dispatch_id}/add` | Dispatch Add |
| `POST` | `/api/dispatch/{dispatch_id}/stop` | Dispatch Stop |

## doctor

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/doctor` | Run full system diagnostics on providers, memory, and connectors. |

## email

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/email/accounts` | Get Accounts |
| `POST` | `/api/email/accounts` | Post Account |
| `DELETE` | `/api/email/accounts/{account_id}` | Delete Account |
| `POST` | `/api/email/test/{account_id}` | Log in over IMAP and count unread mail. Sends nothing. |

## engine

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/engine` | How this engine was started, and whether one-click start is wired up. |
| `POST` | `/api/engine/admin-console` | Start the admin access server (testers, access keys, applications, audit) and return its URL. |
| `POST` | `/api/engine/autostart` | Turn start-with-Windows on or off. |
| `POST` | `/api/engine/restart` | Restart as a fresh process so code and configuration changes take effect. |
| `POST` | `/api/engine/stop` | Stop the engine (tray Quit, nyx://stop, the web UI's power button). |

## events

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/events` | Recent real system activity for the HUD log. |
| `GET` | `/api/events/recent` | Recent Events |
| `GET` | `/api/events/stream` | Event Stream |

## feedback

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/feedback` | Submit Feedback |

## finance

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/finance/advice` | Get grounded financial guidance from the finance advisor mode. |
| `GET` | `/api/finance/history` | Fetch daily price history for a symbol. |
| `GET` | `/api/finance/knowledge` | Search the permanent financial literacy knowledge base. |
| `GET` | `/api/finance/quote` | Fetch live quotes for comma-separated symbols. |
| `GET` | `/api/finance/status` | Report US market open/close and connector health. |

## folders

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/folders` | List registered folders. |
| `POST` | `/api/folders` | Register a folder by name and path. |
| `DELETE` | `/api/folders/{name}` | Unregister a folder. |
| `GET` | `/api/folders/{name}/files` | List files in a registered folder, any format. |
| `GET` | `/api/folders/{name}/read` | Read a file from a registered folder. |
| `GET` | `/api/folders/{name}/search` | Search text files in a registered folder for a query string. |

## games

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/games` | List Games |
| `POST` | `/api/games` | Create Game |
| `GET` | `/api/games/{game_id}` | Read Game |
| `PATCH` | `/api/games/{game_id}` | Patch Game |
| `DELETE` | `/api/games/{game_id}` | Delete Game |
| `POST` | `/api/games/{game_id}/design` | Design Game |
| `POST` | `/api/games/{game_id}/rooms` | Add Room |
| `GET` | `/api/games/{game_id}/unity` | Unity Preview |
| `POST` | `/api/games/{game_id}/unity` | Export Unity |

## google

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/google/oauth/callback` | Where Google sends the browser back. Public (the browser carries no Nyx session here), but only a |
| `POST` | `/api/google/oauth/client` | Google Client |
| `POST` | `/api/google/oauth/start` | Google Start |
| `GET` | `/api/google/oauth/status` | Google Status |

## graphs

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/graphs/create` | Generate Mermaid and ASCII graphs from node and edge definitions. |
| `POST` | `/api/graphs/read` | Extract entities and relationship edges from plain text or diagrams. |

## health

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/health` | Return backend liveness and capability flags. |
| `GET` | `/api/health/deep` | Run the full health check on demand. |

## homework

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/homework/analyze` | Decompose homework problem into concept breakdown, steps, and hints. |

## image-proxy

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/image-proxy` | Show a remote picture in chat without the browser contacting that site (Request H15). |

## improve

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/improve/autopilot` | Autopilot State |
| `POST` | `/api/improve/autopilot` | Autopilot Start |
| `POST` | `/api/improve/autopilot/{action}` | Autopilot Action |
| `GET` | `/api/improve/changes` | Self-improvement changes (newest first) with their diff and whether they can be rolled back. |
| `POST` | `/api/improve/changes/{change_id}/approve` | Change Approve |
| `POST` | `/api/improve/changes/{change_id}/deny` | Change Deny |
| `POST` | `/api/improve/changes/{change_id}/implement` | Change Implement |
| `POST` | `/api/improve/changes/{change_id}/rollback` | Improve Rollback |
| `POST` | `/api/improve/controls` | Control Add |
| `PUT` | `/api/improve/controls/{key}` | Control Set |
| `DELETE` | `/api/improve/controls/{key}` | Control Remove |
| `GET` | `/api/improve/deep` | Deep State |
| `POST` | `/api/improve/deep` | Deep Start |
| `POST` | `/api/improve/deep/plan` | Split the owner's list into items and estimate each — offline, fast enough to call while typing. |
| `POST` | `/api/improve/deep/stop` | Deep Stop |
| `GET` | `/api/improve/map` | The repo map the analyzer reasons over — the same data, shown to the owner. |
| `GET` | `/api/improve/review` | Review Queue |
| `POST` | `/api/improve/review/analyze` | Review Analyze |
| `POST` | `/api/improve/review/apply` | Review Apply |
| `POST` | `/api/improve/review/deny-duplicates` | Review Deny Duplicates |
| `POST` | `/api/improve/review/stop` | Review Stop |
| `GET` | `/api/improve/sessions` | Improve Sessions |
| `GET` | `/api/improve/sessions/{session_id}` | Improve Session |
| `POST` | `/api/improve/sessions/{session_id}/stop` | Improve Stop |
| `POST` | `/api/improve/start` | Improve Start |

## keys

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/keys` | Every provider, whether it has credentials, and which jobs use it. No secrets. |
| `GET` | `/api/keys/alerts` | Keys that kept failing long enough to ask the owner about. |
| `POST` | `/api/keys/alerts/{key_name}/{fingerprint}` | The owner's answer: ``drop`` removes only that key; ``keep`` keeps retrying it and stops asking. |
| `POST` | `/api/keys/{provider}` | Store credentials for a provider. The response never contains them. |
| `DELETE` | `/api/keys/{provider}` | Delete Key |
| `GET` | `/api/keys/{provider}/pool` | Key List |
| `POST` | `/api/keys/{provider}/pool` | Add another key for a provider. Nyx fails over to it when the one in use stops working. |
| `DELETE` | `/api/keys/{provider}/pool/{fingerprint}` | Remove exactly one key; the provider's other keys stay. |
| `POST` | `/api/keys/{provider}/test` | A free check that the credentials work (lists models; spends nothing). |

## knowledge

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/knowledge` | Search the permanent general knowledge base. |

## learning

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/learning/reset` | Learning Reset |
| `GET` | `/api/learning/stats` | Learning Stats |
| `GET` | `/api/learning/suggest` | Learning Suggest |

## machine

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/machine` | Active grants, the audit trail, and what can never be reached. |
| `POST` | `/api/machine/grant` | Grant one capability, optionally scoped, always expiring. |
| `POST` | `/api/machine/revoke` | Revoke one capability, or everything (the kill switch). |

## math

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/math` | Evaluate a math expression or solve an equation in x. |

## memory

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/memory` | Return important memories and preferences. |
| `POST` | `/api/memory/important` | Store an important memory. |
| `DELETE` | `/api/memory/important/{topic}` | Remove an important memory by topic. |
| `GET` | `/api/memory/rag` | Retrieve the most relevant memory entries for a query. |

## model-roles

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/model-roles` | Get Roles |
| `PUT` | `/api/model-roles/{role}` | Put Role |
| `DELETE` | `/api/model-roles/{role}` | Reset Role |
| `POST` | `/api/model-roles/{role}/test` | Run the role's model once on a tiny task, with no fallback, so the result is about that model. |

## models

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/models` | List local Ollama models and configured online providers. |
| `GET` | `/api/models/active` | Which provider answers by default right now — the chat dropdown syncs to this. |
| `GET` | `/api/models/catalog` | Models a provider offers, optionally filtered by job — for the model pickers. |
| `POST` | `/api/models/switch` | Switch the active local model or the preferred online provider. |

## notes

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/notes` | Notes Library |
| `POST` | `/api/notes` | Create Note |
| `POST` | `/api/notes/grade` | Grade Short Answer |
| `POST` | `/api/notes/notebooks` | Create Notebook |
| `PATCH` | `/api/notes/notebooks/{notebook_id}` | Rename Notebook |
| `DELETE` | `/api/notes/notebooks/{notebook_id}` | Delete Notebook |
| `GET` | `/api/notes/{note_id}` | Read Note |
| `PATCH` | `/api/notes/{note_id}` | Update Note |
| `DELETE` | `/api/notes/{note_id}` | Delete Note |
| `POST` | `/api/notes/{note_id}/drawing` | Read a sketch (handwriting, equations, diagrams) into the note. |
| `POST` | `/api/notes/{note_id}/study` | Detail, summary, quiz, flashcards, step-by-step… made from this note. |
| `PATCH` | `/api/notes/{note_id}/{collection}/{item_id}` | Update Study Item |
| `DELETE` | `/api/notes/{note_id}/{collection}/{item_id}` | Delete Study Item |

## optimizer

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/optimizer/preview` | What the optimizer would do with a message — even when switched off. |
| `GET` | `/api/optimizer/settings` | Optimizer Settings |
| `PUT` | `/api/optimizer/settings` | Optimizer Update |

## overlay

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/overlay` | What is currently layered on top of the shipped app, plus checkpoints. |
| `POST` | `/api/overlay/restore` | Roll the whole overlay back to a checkpoint (self code revival, F3). |

## permissions

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/permissions` | Get Permissions |
| `POST` | `/api/permissions` | Set Permissions |

## personalities

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/personalities` | List built-in personalities and the saved custom one. |
| `POST` | `/api/personalities/custom` | Save a custom personality description. |
| `DELETE` | `/api/personalities/custom` | Remove the saved custom personality. |

## personality

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/personality` | Report which personality is currently applied. |
| `POST` | `/api/personality` | Apply a personality to the assistant. |

## power

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/power` | Power modes and what each one means on this specific machine. |
| `POST` | `/api/power` | Select a power mode. |

## predict

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/predict` | Predict |
| `GET` | `/api/predict/settings` | Predict Settings |
| `PUT` | `/api/predict/settings` | Predict Settings Update |

## presence

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/presence` | The web UI's throttled "someone is using me" heartbeat (real input only). |
| `GET` | `/api/presence` | Presence State |

## providers

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/providers` | Every provider the app can chat with, plus the free presets worth adding. |
| `POST` | `/api/providers/{name}/key` | Store an API key for a known provider (built-in or user-added). |
| `DELETE` | `/api/providers/{name}/key` | Forget a provider's stored key(s). The provider stays listed, keyless. |
| `POST` | `/api/providers/{name}/test` | One real, minimal call against the provider. Spends at most a token. |

## security

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/security/files` | Files the malicious-file checks blocked or flagged, the current settings and which scanner is available (owner only). |
| `PUT` | `/api/security/files/settings` | Turn a check on or off: the whole guard, the Windows Security pass, refusing programs, blocking weights that run code, prompt-injection warnings. |
| `POST` | `/api/security/files/check` | Check one file on this PC or one upload on demand; returns the verdict and its message. |

## skills

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/skills` | The skill library, built-ins first. |
| `POST` | `/api/skills` | Add a skill directly, with instructions already written. |
| `POST` | `/api/skills/from-conversation` | Describe a capability in words; the agent writes the skill (U2). |
| `POST` | `/api/skills/preview` | Which skills a given message would attach, and why. |
| `GET` | `/api/skills/search` | Search Skills |
| `DELETE` | `/api/skills/{skill_id}` | Remove Skill |
| `POST` | `/api/skills/{skill_id}/enabled` | Set Skill Enabled |
| `GET` | `/api/skills/{skill_id}/export` | Export Skill |
| `POST` | `/api/skills/{skill_id}/keep` | Keep Skill |

## speech

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/speech` | Return currently learned speech patterns. |
| `DELETE` | `/api/speech` | Clear learned speech patterns. |
| `POST` | `/api/speech/learn` | Learn speech patterns from a batch of user messages. |

## speed

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/speed` | Report the current speed mode and what each option means. |
| `POST` | `/api/speed` | Override per-turn speed selection. 'auto' restores automatic behaviour. |

## status

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/status` | Return service, router, and connector status. |

## storage

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/storage` | Storage Report |
| `POST` | `/api/storage/clean` | Apply the automatic budgets now (caches, backups, logs). Never touches memories, uploads or chats. |
| `DELETE` | `/api/storage/leftovers/{key}` | Remove one old build folder from the fixed list, after the owner confirmed in the UI. |

## strands

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/strands` | The live strand graph for the HUD tab, built from real system state. |

## system

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/system/live` | The machine right now: CPU, memory, GPU telemetry, rates, top processes. |
| `GET` | `/api/system/specs` | Accurate, sourced hardware identity. Unknown fields are null, never guessed. |

## tabs

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/tabs` | The user's own tabs, plus the shipped set for reference. |
| `POST` | `/api/tabs` | Create a tab from an explicit spec. |
| `POST` | `/api/tabs/combine` | Merge two tabs into one (CC11). The originals are left alone. |
| `POST` | `/api/tabs/from-description` | Describe a tab in words; the agent designs it (CC4, CC5). |
| `GET` | `/api/tabs/search` | Fuzzy tab search (CC2, CC6). |
| `PATCH` | `/api/tabs/{tab_id}` | Edit a tab (CC9, CC10). Every field is re-validated. |
| `DELETE` | `/api/tabs/{tab_id}` | Delete Tab |
| `POST` | `/api/tabs/{tab_id}/edit` | Change a tab by describing the change (CC9). |

## think

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/think` | List all background thoughts (for live App/Web status). |
| `POST` | `/api/think` | Start a background thought; returns an id to poll for the final answer. |
| `GET` | `/api/think/{thought_id}` | Poll a background thought's live status and final result. |

## tools

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/tools` | List Tools |
| `POST` | `/api/tools/run` | Run one tool directly (Developer panel). Owner-level: it reaches the machine. |

## trading

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/trading/approvals/{approval_id}` | Decide Approval |
| `POST` | `/api/trading/autopilot/scan` | Run one scan now, even with the schedule off — orders still obey every rule. |
| `POST` | `/api/trading/brokers/snaptrade/portal` | The SnapTrade page where the owner signs in to their own brokerage (Robinhood, Schwab, Fidelity…). |
| `DELETE` | `/api/trading/brokers/{name}` | Disconnect Broker |
| `POST` | `/api/trading/brokers/{name}/connect` | Connect Broker |
| `POST` | `/api/trading/halt` | Halt |
| `POST` | `/api/trading/orders` | The owner's own order. It still passes the live-trading switch. |
| `DELETE` | `/api/trading/orders/{order_id}` | Cancel Order |
| `POST` | `/api/trading/paper/reset` | Reset Paper |
| `GET` | `/api/trading/quote` | Quote |
| `POST` | `/api/trading/resume` | Resume |
| `PUT` | `/api/trading/settings` | Update Settings |
| `GET` | `/api/trading/signals` | Trading Signals |
| `GET` | `/api/trading/state` | Everything the Trading tab shows, in one call. |

## turns

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/turns` | Turns running now (and recently finished), across every chat and window. |
| `POST` | `/api/turns/advise` | Queue, interrupt, run alongside or branch: Nyx's pick for a message typed mid-answer (Request G12). |
| `GET` | `/api/turns/{turn_id}` | Get Turn |
| `GET` | `/api/turns/{turn_id}/stream` | Watch a turn that is already running — after a reload, from another tab or window. |

## ui

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/ui/state` | Ui State |
| `POST` | `/api/ui/theme` | Set Theme |
| `POST` | `/api/ui/theme/reset` | Reset Theme |
| `POST` | `/api/ui/theme/undo` | Undo Theme |

## updates

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/updates` | Git checkouts update with git; zip installs (beta testers) from the reviewed release channel. |
| `PUT` | `/api/updates/channel` | Updates Channel |
| `POST` | `/api/updates/install` | Updates Install |
| `POST` | `/api/updates/rollback` | Updates Rollback |
| `GET` | `/api/updates/status` | Channel, version, staged download and last install — no network call (Request G2). |

## uploads

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/uploads` | Raw body upload: the file bytes, ``X-Filename`` and ``Content-Type`` headers. |
| `GET` | `/api/uploads/{upload_id}` | Get Upload File |

## usage

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/usage/limits` | Limits the provider itself reported (headers, quota errors, balance) — empty means no bar (Request G6). |

## voice

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/voice/audio/{key}` | Audio a ``voice.say`` event points at. |
| `GET` | `/api/voice/engines` | Voice Engines |
| `POST` | `/api/voice/listen` | Listen to the microphone and return recognized speech (offline STT). |
| `GET` | `/api/voice/neural-voices` | Voice Neural |
| `GET` | `/api/voice/roles` | Voice Roles |
| `PUT` | `/api/voice/roles/{role}` | Put Voice Role |
| `POST` | `/api/voice/say` | Speak through every open Nyx window (or the PC speakers if none is open). |
| `POST` | `/api/voice/scan` | Voice ID: enroll (mode='enroll'), verify (mode='verify'), or status. |
| `POST` | `/api/voice/set` | Select which installed voice speaks. |
| `POST` | `/api/voice/speak` | Speak text aloud through the selected (or requested) voice. |
| `GET` | `/api/voice/status` | Return voice enrollment status, active voice, mic, and installed voices. |
| `POST` | `/api/voice/tts` | Synthesize and return the audio (mp3 for neural voices, wav for Windows voices). |
| `GET` | `/api/voice/voices` | List installed text-to-speech voices. |

## widgets

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/widgets` | The user's HUD layout, plus the widget types they can add. |
| `POST` | `/api/widgets` | Add a widget to the HUD. |
| `POST` | `/api/widgets/order` | Reorder Widgets |
| `POST` | `/api/widgets/reset` | Reset Widgets |
| `DELETE` | `/api/widgets/{widget_id}` | Remove Widget |
