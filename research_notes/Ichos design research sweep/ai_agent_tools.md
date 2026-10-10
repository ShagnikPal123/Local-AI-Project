# UI/UX of AI coding agents, app builders and computer-use agents (as of Oct 2026)

Scope: reusable UI patterns for showing agents at work, for the Ichos redesign (one sidebar, one composer, windows beside chat, dockable panels, sub-agents that must ask before opening or driving windows). Research was done 2026-10-10 with ~22 search/fetch calls. The best primary sources were Claude Code Desktop docs, VS Code docs, Zed docs, Cursor changelog/docs, Warp docs, Lovable docs, Replit docs, and Junie docs. Devin, Manus, ChatGPT agent, Bolt, Factory, Genspark and Mariner are covered only through secondary sources or not at all (see Gaps). Dates are marked where known.

## 1. Layout: where chat, file tree, diff, preview, terminal and browser sit, and what can move

### Takeaway
The 2026 standard is an agent-first window: a session sidebar on the left, chat/composer in the centre, and work surfaces (diff, browser/preview, terminal, files, plan, tasks, subagent) as panes that open beside the chat. They can be dragged, resized, split, popped out into their own OS windows, and docked back. Claude Code Desktop and Cursor 3 are the clearest references. The app builders (Lovable, Bolt, v0) keep a simpler fixed layout: chat on the left, preview on the right.

### Cited Findings
- **Claude Code Desktop (Code tab).** It is "built around panes you can arrange in any layout: chat, diff, browser, terminal, file, plan, tasks, and subagent". You drag a pane by its header to move it and drag an edge to resize it. **Ctrl+\\** closes the focused pane. The **Terminal**, **Changes** and **Browser** buttons sit in the session title bar, and a **⋮** menu holds more panes (e.g. **Files**). That menu also takes those buttons when the window is too narrow. Panes such as the diff or terminal can be popped out into their own window and docked back, and "Claude keeps working in the main window". This needs Desktop v1.2581.0+. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop split sessions.** Ctrl+click a sidebar session to open it in a second pane. While split, clicking another session replaces the focused pane. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop setup.** The prompt area sets four things before the first message: **Environment** (Local / Cloud / SSH / WSL), **Project folder**, **Model** (dropdown next to Send) and **Permission mode** (selector next to Send). The **+** button next to the prompt box opens attachments, skills, connectors and plugins. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop shortcuts.** Ctrl+Shift+D toggles the diff pane, Ctrl+Shift+B the Browser pane, and Ctrl+` the terminal. Ctrl+Shift+S selects an element in the Browser. Ctrl+; opens a side chat, Ctrl+O cycles view modes, and Ctrl+Shift+M opens the permission-mode menu. Ctrl+Shift+I opens the model menu, Ctrl+Shift+E the effort menu, and Ctrl+/ shows all shortcuts. In an open menu, 1–9 selects an item. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop file pane.** Clicking a file path in chat or diff opens the file pane, with **Save** / **Discard** and a warning if the file changed on disk. HTML, PDF, image and video paths open in the Browser pane instead. Right-clicking a path offers **Attach as context**, **Open in** (VS Code/Cursor/Zed), **Show in Explorer** and **Copy path**. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Desktop tabs.** The app has top-level tabs **Chat**, **Cowork** (Dispatch/long agentic work) and **Code**. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Cursor 3 "Agents Window" (released 2026-04-02, codename "Glass").** This is a full-screen agent-first workspace. All agents (local, worktree, cloud, remote SSH, and ones started from mobile/web/Slack/GitHub/Linear) appear in one unified sidebar. It works across workspaces. You open it via Cmd+Shift+P → "Agents Window" and can keep it and the IDE open at once. — [Cursor 3.0 changelog](https://cursor.com/changelog/3-0); [The Decoder](https://the-decoder.com/new-cursor-3-ditches-the-classic-ide-layout-for-an-agent-first-interface-built-around-parallel-ai-fleets/)
- **Cursor 3.1 "Tiled Layout".** You can split the view into panes to run several agents in parallel, expand a pane to focus, drag agents into tiles, and navigate with keybindings. The layout persists across sessions. — [Cursor 3.1 forum post](https://forum.cursor.com/t/cursor-3-1-tiled-layout-and-upgraded-voice-input/157293)
- **Cursor 2.0 (older, late 2025).** It added an "Agents" view alongside the classic "Editor" view, switched at the top left (Ctrl+E reported). Users complained it was forced on as the default and that panels resized unexpectedly when switching agents. — [Cursor forum](https://forum.cursor.com/t/cursor-2-0-agents-view-whats-the-point/140094); [resize bug thread](https://forum.cursor.com/t/automatic-resizing-each-time-i-switch-agents-on-the-agents-view/143562/2)
- **Cursor 3 reception.** One user complaint: the Agents Window can't be themed with VS Code themes. — [Cursor 3 forum](https://forum.cursor.com/t/cursor-3-agents-window/156509)
- **VS Code "Agents window".** It has a session list in the left sidebar (**Toggle Sidebar** at top-left). **Open in Editor** in the title bar opens the session's workspace in an editor window. In the editor's Sessions view, right-clicking a row gives **Open as Editor** (editor tab) or **Open to the Side**. On Windows, right-clicking the taskbar icon gives **Agents Window**. — [VS Code chat sessions docs](https://code.visualstudio.com/docs/chat/chat-sessions)
- **OpenAI Codex app.** It is a desktop app for running threads in parallel across projects in one window. Each thread picks a mode: **Local**, **Worktree** or **Cloud**. A docs mockup of the sidebar shows a search icon, **New chat**, **Pinned**, **Projects** and **Recents** sections. Its **Add** menu holds "Files and folders", "Attach Google Chrome", "Goal – Set a goal to keep pursuing" and "Plan mode – Turn plan mode on". — [Codex app docs](https://developers.openai.com/codex/app.md); [Codex features page](https://learn.chatgpt.com/docs/features)
- A July 2026 guide says the standalone Codex app was merged into a rebuilt ChatGPT desktop app with three modes: Chat, Work and Codex. This is secondary and unconfirmed by OpenAI in my search. — [heyuan110 guide](https://www.heyuan110.com/posts/ai/2026-07-12-openai-codex-app-guide/)
- **Devin 2.0.** It is described as an agent-native cloud IDE. Each session has a shell, code editor and browser, plus a reported Progress tab that brings shell commands, edits and browser activity into one view. Multiple Devins can run in parallel. These are secondary sources. — [fast.io session tools guide](https://fast.io/resources/devin-session-tools-guide/); [Analytics Vidhya](https://www.analyticsvidhya.com/blog/2025/04/devin-2-0/)
- **Bolt.new.** Chat panel with change history, code editor with file explorer and terminal, and a live preview on the right that refreshes as code changes (secondary). — [env.dev](https://env.dev/ai/bolt); [The New Stack](https://thenewstack.io/introduction-to-bolt-does-it-suit-professional-developers/)
- **Lovable.** On small windows, top-bar controls collapse into overflow menus. — [Lovable editor docs](https://docs.lovable.dev/features/projects/editor)

### Inferences
- The "panes beside chat, pop out, dock back" model Ichos plans is now mainstream (Claude Code Desktop, Cursor 3.1 tiles, VS Code Open to the Side). Ichos is on-trend. Its differentiator should be agent-requested windows (permission before open/drive), which none of these products expose as a first-class concept.
- Overflow behaviour matters. Claude Desktop and Lovable both move title-bar buttons into a ⋮ menu at narrow widths, which is a good model for Windows snap layouts.
- Layout persistence is expected (Cursor 3.1). Cursor's forced-default Agents view and resize bugs are a caution.

### Gaps
- No official Devin, Manus, Genspark or Factory layout docs were retrieved.
- I didn't fetch Windsurf's or Zed's pane layout (Zed docs mention an Agent Panel, but its dock positions weren't retrieved).

## 2. Progress: plans, to-dos, step logs, live screenshots, timers, token/cost meters, "working…" states

### Takeaway
Progress is shown in layers: a collapsible transcript where tool calls fold into summaries, a plan or to-do surface, a background-tasks or subagent pane, and a context/usage meter in the composer. Computer-use agents add a live view of the agent's screen with narration. Products increasingly let the user choose how much detail to show (Claude's Normal/Thinking/Verbose).

### Cited Findings
- **Claude Code Desktop transcript view modes.** **Normal** shows tool calls collapsed into summaries plus full text. **Thinking** adds the model's thinking. **Verbose** shows every tool call, file read and intermediate step. You switch via the caret beside the session title → **Transcript view**, or Ctrl+O. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop tasks pane.** It shows background work in the current session (subagents, background shell commands, workflows) and opens via **Background tasks** in the title bar ⋮ menu. Clicking an entry shows its output in the subagent pane or stops it. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop steering.** A stop button interrupts immediately. Typing a correction and pressing Enter queues it "without stopping the running action", and Claude reads it after the current action. Esc stops the response. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop usage ring.** It sits next to the model picker and shows the context window (per session) and plan usage (shared across surfaces). — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop diff stats chip.** A chip such as `+12 -1` appears when files change. Clicking it opens a diff viewer with the file list on the left and changes on the right. Clicking a line adds a comment, and Ctrl+Enter submits all comments. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop CI status bar.** It appears after a PR is opened. Clicking **CI** offers the toggles **Auto-fix CI & address comments** and **Auto-merge when ready**. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop code review card.** It groups findings by file, with **Walk through in diff**, **Fix this one** and **Apply fixes**. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop side chat.** Ctrl+; or `/btw` asks a question with the session's context without adding it to the main thread. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop task chips.** Claude can offer out-of-scope work as a "task chip" in chat. Clicking it starts a new session with its own worktree. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **VS Code context meter.** A context-window control in the chat input shows token usage and offers **Compact Conversation**. — [VS Code chat sessions docs](https://code.visualstudio.com/docs/chat/chat-sessions)
- **VS Code command center.** Its status indicator shows an unread badge, an in-progress badge and a sparkle icon, and clicking a badge filters the session list. — [VS Code chat sessions docs](https://code.visualstudio.com/docs/chat/chat-sessions)
- **Cursor 3.0 agent panel.** It gets a "scroll to bottom" button when content overflows. Agents can "await" background shell commands, subagents, or output like "Ready"/"Error". Plans are included in shared chats with the transcript. — [Cursor 3.0 changelog](https://cursor.com/changelog/3-0)
- **Junie.** In Code mode it breaks a task into a multistep plan and reports progress. Plans are saved to `.junie/plans` and can be committed, and Shift+Tab switches to Plan mode. Junie left beta on 2026-06-17. — [JetBrains blog (FR)](https://blog.jetbrains.com/fr/junie/2026/07/junie-l-agent-de-programmation-ia-de-jetbrains-sort-de-sa-phase-beta/); [Junie docs](https://junie.jetbrains.com/docs/junie-ide-plugin.html)
- **Jules.** Shows a plan to approve (**Approve plan**), then a visual diff, then **Publish branch**, which opens a PR. You can chat while it runs asynchronously. — [DataCamp tutorial](https://www.datacamp.com/ko/tutorial/google-jules)
- **Project Mariner.** Side panel showing the agent's step-by-step plan; it works only on the active Chrome tab (older, 2024–25 reporting). — [TechCrunch 2024](https://techcrunch.com/2024/12/11/google-unveils-project-mariner-ai-agents-to-use-the-web-for-you/); [getcoai](https://getcoai.com/news/googles-project-mariner-is-an-ai-agent-that-navigates-the-web-for-you)
- **ChatGPT agent (launched 2025-07-17).** Runs on its own virtual computer (visual browser, text browser, terminal, connectors). It shows tools in use and narration, and the user can pause, interrupt or take over at any time. Takeover is mainly used for logins. Secondary sources. — [chatbase](https://chatbase.co/blog/chatgpt-agent-mode); [aitoolanalysis review](https://aitoolanalysis.com/chatgpt-agent-mode-review/)
- **Replit Agent App testing.** Agent tests the app in a real browser, enabled by the **App testing** toggle in the **Agent Tools** panel, and provides video replays of test sessions. **Max autonomy** (beta, under **Autonomy Level**) lets runs last up to 200 minutes. — [Replit Agent docs](https://docs.replit.com/replitai/agent)
- **GitHub Copilot coding agent.** Session logs show the agent's internal monologue and tool use. They are reached from the PR timeline ("Copilot started work…" → **View session**), and a **Stop session** button halts work. Since Mar 2026, commits carry an `Agent-Logs-Url` trailer linking back to the session. — [GitHub docs](https://docs.github.com/en/copilot/using-github-copilot/coding-agent/using-the-copilot-coding-agent-logs); [GitHub changelog 2026-03-20](https://github.blog/changelog/2026-03-20-trace-any-copilot-coding-agent-commit-to-its-session-logs)
- **Amp.** Organizes work as persistent threads. Its editor panel lets Space expand a thread to show the last message or tool result. — [releasebot Amp notes](https://releasebot.io/updates/ampcode)

### Inferences
- A three-level verbosity switch (summary / thinking / everything) suits an assistant serving both casual and power users.
- "Queue a correction without stopping" is low-cost and high-value for long sub-agent runs.
- Linking every artifact (commit, file, window action) back to the session log, as GitHub does, gives the office of agents an audit trail.

### Gaps
- No official per-call cost/token display was found for Amp, Cursor or Windsurf. Claude's usage ring and VS Code's context control are the documented meters.
- No elapsed-timer UI details were found in primary docs.
- Manus's live "computer" panel and shareable replays, and Anthropic's computer-use demo UI, could not be verified in this search. Manus's 2026 desktop "My Computer" feature runs terminal commands on the user's machine. — [Manus blog](https://manus.im/es-419/blog/manus-my-computer-desktop)
- Windsurf Cascade's to-do list could not be confirmed.

## 3. Permission and safety UX: approve/deny, "always allow" scopes, modes, checkpoints, sandbox indicators

### Takeaway
Every major tool has converged on: (a) a per-session mode picker in or next to the composer (ask, accept edits, plan, auto/classifier, bypass), (b) inline approval cards with scoped "always allow" options, (c) per-tool or per-command allow/deny lists, and (d) checkpoints for rewinding agent changes. Some actions always prompt regardless of mode, and computer-use tiers are set by app category.

### Cited Findings
- **Claude Code Desktop modes.** The selector sits next to **Send** (Ctrl+Shift+M):
  - **Manual**: asks before edits and commands.
  - **Accept edits**: auto-accepts edits and mkdir/touch/mv.
  - **Plan**: reads and explores, then proposes a plan without editing.
  - **Auto**: no routine prompts, and a background classifier checks shell and network actions.
  - **Bypass permissions**: no prompts except actions no mode auto-approves.

  The mode is remembered per folder; Plan applies only to the current session. Older labels were "Ask permissions", "Auto accept edits" and "Plan mode". Cloud sessions offer only Accept edits, Plan and Auto, because the cloud is already sandboxed. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop); [permission modes](https://code.claude.com/docs/en/permission-modes)
- **Claude Code Desktop always-ask actions.** Archiving a session shows an approval card "in every permission mode, including Auto and Bypass". — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop external sites.** On first action on a site, a permission card offers **Allow once**, **Always allow** (per site, subdomains separate, revocable in Settings) or **Deny**. Local dev servers need no approval. Even on approved sites, Claude won't purchase, create accounts or bypass CAPTCHAs. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop computer use.** On first use of an app, a prompt offers **Allow for this session** / **Deny**. The prompt shows the tier, fixed by app category: **View only** (browsers, trading), **Click only** (terminals, IDEs) or **Full control** (others). Broad-reach apps (terminal, File Explorer, Settings) show an extra warning. Settings include **Denied apps** and **Unhide apps when Claude finishes**; Claude hides other windows while it works. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **VS Code permission levels.** A per-session permissions picker offers **Default Approvals**, **Bypass Approvals** and **Autopilot (Preview)**, which also auto-answers clarifying questions. The default is set via `chat.permissions.default` (v1.111–1.115, Mar–Apr 2026). — [GitHub changelog 2026-04-08](https://github.blog/changelog/2026-04-08-github-copilot-in-visual-studio-code-march-releases); [VS Code trust & safety](https://code.visualstudio.com/docs/copilot/concepts/trust-and-safety)
- **VS Code approval scopes.** Approval can cover the exact command or all terminal commands, for **this session / this workspace / always**. Approvals are managed centrally via "Chat: Manage Tool Approval". Agent sessions create checkpoints you can return to. — [VS Code trust & safety](https://code.visualstudio.com/docs/copilot/concepts/trust-and-safety)
- **Zed.** `agent.tool_permissions.default` is `confirm` / `allow` / `deny` (v0.224.0+). Per-tool regex `always_allow` / `always_confirm` / `always_deny` lists are supported. Chained terminal commands are parsed and each sub-command is checked. Hardcoded rules block recursive deletion of root, home, or the current or parent directory. — [Zed tool permissions](https://zed.dev/docs/ai/tool-permissions)
- **Cursor.** Settings > Agents > Approvals & Execution offers run modes **Auto-review** (runs known-safe calls, sandboxes shell where possible, and sends the rest to a classifier) and **Allowlist**. Forum reports say an "Enable Auto-review" checkbox on the command approval card was ticked by default and silently changed the global run mode. — [Cursor run modes](https://cursor.com/docs/agent/security/run-modes); [forum bug](https://forum.cursor.com/t/run-mode-not-respected-the-enable-auto-review-checkbox-changes-global-agentic-run-mode-and-violates-consent/163931)
- **Cursor checkpoints.** Automatic local snapshots of agent changes only, separate from Git. You restore them via **Restore Checkpoint** on a previous request, or the + on message hover. — [Cursor checkpoints docs](https://docs.cursor.com/agent/chat/checkpoints)
- **Windsurf Cascade.** Auto-execution levels are **Off** (allowlist only), **Auto** (model decides; premium models only) and **Turbo** (everything except the deny list). Admins can cap the level. Named checkpoints are reverted via a revert arrow on prompt hover; reverts are irreversible. — [Windsurf/Devin docs](https://docs.devin.ai/windsurf/plugins/cascade/cascade-overview)
- **Junie.** **Brave Mode** in the task window skips approvals; JetBrains says it is "not recommended" and recommends the Action Allowlist instead. — [Junie docs](https://junie.jetbrains.com/docs/junie-ide-plugin.html)
- **Replit checkpoints.** Automatic at milestones. Each covers files, AI conversation context and databases, with an AI summary, timestamp and changed files. They appear in the Agent tab, the Git pane and chat. Changes made after a rollback form an alternate history branch. — [Replit checkpoints docs](https://docs.replit.com/core-concepts/agent/checkpoints-and-rollbacks)
- **VS Code Fork Conversation.** A **Fork Conversation** button in the checkpoint toolbar (shown on request hover) branches the chat from that point. — [VS Code chat sessions docs](https://code.visualstudio.com/docs/chat/chat-sessions)
- **Codex.** Agents run in a system-level sandbox limited to project folders, and elevated actions need approval or pre-approved rules. The CLI's `--yolo` bypasses approvals and sandboxing (secondary). Official docs list "Permissions", "Sandboxing", "Auto-review" and "Windows sandbox" pages. — [kingy.ai guide](https://kingy.ai/news/the-codex-app-super-guide-2026-from-hello-world-to-worktrees-skills-mcp-ci-and-enterprise-governance/); [Codex features page](https://learn.chatgpt.com/docs/features)

### Inferences
- The mode picker belongs in the composer next to Send, with a keyboard shortcut. The name should state the consequence ("Accept edits", "Bypass permissions").
- Scoped approvals (once / session / workspace / always) plus a central "manage approvals" screen are standard. For Ichos sub-agent window requests, the natural scopes are "this window once / this window for this task / this app always".
- Category-fixed tiers (view / click / full), with extra warnings for broad-reach apps, map directly onto Ichos's sandboxed computer.
- Non-overridable always-ask actions (archive, purchases, account creation) should be listed explicitly.
- Cursor's consent bug is a real risk: a checkbox on an approval card must never silently change a global mode.

### Gaps
- I didn't retrieve how a sandbox indicator looks in any app (badge, colour). Zed's "Permission Request in the UI" section was not fetched.
- Codex app approval mode labels are unconfirmed.

## 4. Multi-agent views: listing agents/sessions, states, notifications

### Takeaway
Sessions live in a filterable, groupable sidebar with pin and archive actions. States are roughly in progress, waiting for you, unread/done, and failed CI or error. Attention flows through OS notifications, app-icon badges, in-app toasts, and a notification inbox. Agent-to-agent messages are shown as attributed cards.

### Cited Findings
- **Claude Code Desktop sidebar.** **+ New session** (Ctrl+N), Ctrl+Tab cycling, and filters at the top by **status, project or environment**, with group-by-project. Hover shows the archive icon. Auto-archive after PR merge is available. An OS notification fires when a session finishes and you're not viewing it. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Claude Code Desktop cross-session messages.** Shown as a card labelled with the sending session's title and a link back. Delivery is held until the receiver finishes its current work, and the receiver keeps its own permissions. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **VS Code sessions.** Grouped by workspace (Agents window) or timeframe ("Today", "Last Week"). A **Pinned** section accepts drag-in. The default filter shows active sessions only, with **Done** (Agents window) or **Archived** filters. The archive action is labelled **Mark as Done**. — [VS Code chat sessions docs](https://code.visualstudio.com/docs/chat/chat-sessions)
- **VS Code badges and banners.** The app-icon badge counts sessions with unread results, sessions waiting for input, and failing CI on open PRs. A banner reads "This chat is open in another app". — [VS Code chat sessions docs](https://code.visualstudio.com/docs/chat/chat-sessions)
- **Warp alert categories.** Alerts are **complete**, **request** (blocked on approval, permission or idle) and **error**. — [Warp agent notifications](https://docs.warp.dev/agents/capabilities/agent-notifications/)
- **Warp toasts.** Corner toasts fade after a few seconds; hovering pauses them and clicking jumps to the session. A maximum of two show at once, and a newer one replaces the oldest. — [Warp agent notifications](https://docs.warp.dev/agents/capabilities/agent-notifications/)
- **Warp notification mailbox.** A sidebar panel opened from a bell icon at the top right, with filters **All tabs** / **Unread** / **Errors**. The last two appear only when non-empty. — [Warp agent notifications](https://docs.warp.dev/agents/capabilities/agent-notifications/)
- **Warp Agent Management Panel.** Shows active, blocked and failed runs, where each started, and links to the prompt, plan, commands, logs and outputs. A Task List colour-codes completed, cancelled and running tasks. — [Warp managing agents](https://docs.warp.dev/platform/managing-cloud-agents/); [Warp multi-agent guide](https://docs.warp.dev/guides/agent-workflows/running-multiple-agents-at-once-with-warp/)
- **Cursor 3.** A unified sidebar lists agents from all environments. Cloud sessions can be dragged to local and local pushed to cloud. — [Cursor 3.0 changelog](https://cursor.com/changelog/3-0); [The Decoder](https://the-decoder.com/new-cursor-3-ditches-the-classic-ide-layout-for-an-agent-first-interface-built-around-parallel-ai-fleets/)
- **GitHub Agent HQ "Mission Control" (announced Universe, Oct 2025).** One place to see every active agent session, assign tasks, watch progress and review results, across github.com, VS Code, mobile and CLI. — [Visual Studio Magazine](https://visualstudiomagazine.com/articles/2025/10/28/github-introduces-agent-hq-to-orchestrate-any-agent-any-way-you-work.aspx)
- **Claude Code Desktop Projects.** **Projects** in the sidebar lets one conversation start and track many cloud sessions. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)

### Inferences
- A minimal shared state model is running, waiting on you, done/unread, and error/blocked. "Waiting on you" should be the loudest state (badge plus toast) because it blocks progress.
- Toasts should be capped (Warp: two) and backed by a persistent inbox, so Ichos's office of many agents doesn't flood the user.
- Attribution cards ("from session X") suit Ichos's office, where sub-agents message each other or the main brain.

### Gaps
- No exact colour/icon tokens for states were found in docs.

## 5. Preview patterns: live preview pane, device toggles, open in new window, deploy/share

### Takeaway
App builders put a live preview right of chat with a top bar holding Share/Publish. They now overlay direct-manipulation tools on the preview (select element, edit text, draw, comment) that feed edits back to chat. Coding agents embed a real browser pane the agent drives to verify its own changes.

### Cited Findings
- **Claude Code Desktop Browser pane.** Claude starts a dev server and auto-verifies after edits, taking screenshots, inspecting the DOM, clicking and filling forms. The pane header has a **Dev servers** menu (start/stop/stop all). Its **⋮** menu has **Keep cookies** and **Clear browsing data**. It also opens HTML, PDF, image and video files. The config lives in `.claude/launch.json`. — [Claude Code Desktop docs](https://code.claude.com/docs/en/desktop)
- **Lovable preview toolbar (replaces "Visual edits").** Modes are **Select elements** (S; Ctrl-click to multi-select), **Edit text inline** (T, then **Send**), **Draw annotation** (D) and **Add a comment** (C, drops a pin). It docks bottom-centre, can be dragged and snaps to corners. Its options menu has **Dock / Minimize / Hide** and theme **Auto/Light/Dark**. **Share** and **Publish** sit top-right next to a "Show preview toolbar" icon. — [Lovable preview toolbar docs](https://docs.lovable.dev/features/preview-toolbar.md)
- **Lovable publishing and device sizes.** **Publish** deploys to the live URL or updates it, and Business/Enterprise can publish workspace-only. The preview can test phone, tablet and desktop sizes. — [Lovable editor docs](https://docs.lovable.dev/features/projects/editor); [Lovable preview docs](https://docs.lovable.dev/features/projects/preview)
- **v0 Design Mode.** Toggled by a cursor-style button in the prompt toolbar or Alt+D. It switches to the **Preview** tab and overlays tools: hover highlights, click selects and opens a panel for typography, colours, margin and padding. Edits are written back to source. It is not available on mobile viewports or read-only chats. — [v0 design mode docs](https://237.v0.build/docs/design-mode)
- **Cursor 3 Design Mode.** ⌘+Shift+D toggles it. Shift+drag selects an area, ⌘+L adds an element to chat, and ⌥+click adds it to the input. — [Cursor 3.0 changelog](https://cursor.com/changelog/3-0)
- **Bolt.new.** Live preview on the right. A deploy button historically targets Netlify, and a newer **Publish** gives a `.bolt.host` link (secondary). — [DeployHQ guide (Jun 2026)](https://www.deployhq.com/guides/bolt); [unite.ai review](https://www.unite.ai/bolt-new-review)
- **Replit App testing.** The agent drives the preview like a user and records video replays. — [Replit Agent docs](https://docs.replit.com/replitai/agent)

### Inferences
- A floating, draggable, snap-to-corner toolbar over the preview (Lovable) fits Ichos's "panels can dock anywhere" model and supports both precise and natural-language edits.
- An element picker that sends a selected element to the composer (Ctrl+Shift+S in Claude Desktop, ⌘+L in Cursor) should be a shared cross-pane gesture.

### Gaps
- Exact device-toggle control placement and "open in new tab" labels for Lovable, v0 and Bolt were not found.
- Vercel deploy button details in v0 are not documented in retrieved pages.

## 6. Concrete design tokens (colours, fonts, sizes)

### Takeaway
No product published concrete colour, font or size tokens for its agent UI in the sources found.

### Cited Findings
- No sources: none of the retrieved official docs or changelogs (Claude Code, Cursor, VS Code, Zed, Warp, Lovable, v0, Replit) list design tokens for agent states, approval cards or panes.

### Inferences
- Ichos will need to define its own state colours (running / waiting / done / error) and pane chrome. The cited patterns constrain behaviour, not visuals.

### Gaps
- Tokens would need screenshots or CSS inspection of the apps, or design teardowns; neither was available in this pass.

## Patterns Ichos should adopt

1. **Mode picker in the composer next to Send, with a shortcut and consequence-named labels.** Use Manual / Accept edits / Plan / Auto / Bypass, remember it per folder or project, and make Plan session-only. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
2. **Inline permission cards with scoped persistence.** Offer **Allow once / Always allow / Deny** for sites, and once / session / workspace / always for tools. Back them with a central "manage approvals" screen. Apply this to sub-agent window requests ("Agent X wants to open Browser" → Allow once / Allow for this task / Always for this agent / Deny). — [Claude Code Desktop](https://code.claude.com/docs/en/desktop); [VS Code trust & safety](https://code.visualstudio.com/docs/copilot/concepts/trust-and-safety)
3. **Control tiers fixed by window or app category.** Use View only / Click only / Full control, show an extra warning for broad-reach targets (terminal, file explorer, settings), and keep a **Denied apps** list. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
4. **Actions that always ask, in every mode.** These include archiving or deleting sessions, purchases, and account creation. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
5. **Panes beside chat that can be dragged by the header, resized by the edge, popped out to an OS window and docked back.** The agent keeps working in the main window. Title-bar buttons (Terminal / Changes / Browser) should collapse into ⋮ when narrow. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop); [Lovable editor](https://docs.lovable.dev/features/projects/editor)
6. **Tiled multi-agent layout with persistence.** Drag agents into tiles, expand one to focus, and Ctrl+click a sidebar item to split. — [Cursor 3.1](https://forum.cursor.com/t/cursor-3-1-tiled-layout-and-upgraded-voice-input/157293); [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
7. **Session sidebar with status, project and environment filters, a Pinned section, and archive as "Mark as Done".** The default view shows active sessions only. — [VS Code sessions](https://code.visualstudio.com/docs/chat/chat-sessions); [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
8. **Three-channel attention system.** Use an app/taskbar badge (unread + waiting-for-input + errors), capped corner toasts (max 2, hover to pause, click to jump), and a bell inbox with All / Unread / Errors filters. Also send an OS notification when a session finishes off-screen. — [VS Code sessions](https://code.visualstudio.com/docs/chat/chat-sessions); [Warp notifications](https://docs.warp.dev/agents/capabilities/agent-notifications/); [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
9. **Notification categories complete / request / error.** "Request" (blocked on you) is the highest priority. — [Warp notifications](https://docs.warp.dev/agents/capabilities/agent-notifications/)
10. **Background tasks / subagent pane.** List subagents and background commands per session, with click-to-view output and stop. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
11. **Transcript verbosity switch (Normal / Thinking / Verbose).** Tool calls collapse into summaries by default. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
12. **Steer without stopping.** Queue a correction while the agent runs. Keep a stop button and Esc. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
13. **Context/usage ring in the composer** that opens a breakdown and a **Compact** action. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop); [VS Code sessions](https://code.visualstudio.com/docs/chat/chat-sessions)
14. **Diff stats chip (`+12 -1`) that opens the diff pane.** Allow line comments batched with Ctrl+Enter. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
15. **Automatic checkpoints with AI summaries, timestamps and changed files, shown in chat and a history pane.** Restore and Fork from any message hover. Changes after a rollback become a branch rather than being destroyed. — [Replit checkpoints](https://docs.replit.com/core-concepts/agent/checkpoints-and-rollbacks); [Cursor checkpoints](https://docs.cursor.com/agent/chat/checkpoints); [VS Code Fork Conversation](https://code.visualstudio.com/docs/chat/chat-sessions)
16. **Plan-then-execute.** A plan card with **Approve plan**, saved plans that can be committed or kept (`.junie/plans`), and a shortcut to enter Plan. — [Jules via DataCamp](https://www.datacamp.com/ko/tutorial/google-jules); [Junie blog](https://blog.jetbrains.com/fr/junie/2026/07/junie-l-agent-de-programmation-ia-de-jetbrains-sort-de-sa-phase-beta/)
17. **Embedded browser/preview pane the agent drives to verify its own work.** Include a Dev servers menu and Keep cookies / Clear data in ⋮. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
18. **Floating, snap-to-corner preview toolbar.** Modes: Select (S), Edit text (T), Draw (D), Comment (C). Options: Dock / Minimize / Hide. Share and Publish top-right. — [Lovable preview toolbar](https://docs.lovable.dev/features/preview-toolbar.md)
19. **Element picker that sends a UI element to the composer** (Ctrl+Shift+S / ⌘+L style). — [Claude Code Desktop](https://code.claude.com/docs/en/desktop); [Cursor 3.0](https://cursor.com/changelog/3-0)
20. **Side chat (Ctrl+;) for questions that don't pollute the main thread.** Add task chips that spin off out-of-scope work into new sessions. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
21. **Attributed cross-agent message cards** ("from session X", link back). Deliver after the receiver's current step; the receiver keeps its own permissions. — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
22. **Audit trail.** Every artifact links back to the session log (`Agent-Logs-Url` trailer), and the log viewer has **Stop session**. — [GitHub changelog](https://github.blog/changelog/2026-03-20-trace-any-copilot-coding-agent-commit-to-its-session-logs); [GitHub docs](https://docs.github.com/en/copilot/using-github-copilot/coding-agent/using-the-copilot-coding-agent-logs)
23. **Take-over control for the sandboxed computer** (pause / take over / hand back), mainly for logins. — [ChatGPT agent via chatbase](https://chatbase.co/blog/chatgpt-agent-mode) (secondary)
24. **Hide other windows while driving the computer, and restore them when done.** — [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
25. **Per-tool allow / confirm / deny regex lists.** Parse chained commands and keep hardcoded never-allow rules (delete root/home). — [Zed tool permissions](https://zed.dev/docs/ai/tool-permissions)

## Patterns to avoid

1. **Forcing a new agent-centric layout as the default on existing users.** It caused confusion and backlash. — [Cursor 2.0 forum](https://forum.cursor.com/t/cursor-2-0-agents-view-whats-the-point/140094)
2. **Panes that resize themselves when switching agents or sessions.** Layout must be stable and persisted. — [Cursor resize bug](https://forum.cursor.com/t/automatic-resizing-each-time-i-switch-agents-on-the-agents-view/143562/2)
3. **Approval cards with pre-ticked options that silently change a global mode.** This was reported as a consent violation. — [Cursor forum](https://forum.cursor.com/t/run-mode-not-respected-the-enable-auto-review-checkbox-changes-global-agentic-run-mode-and-violates-consent/163931)
4. **Config allowlists that silently override the chosen mode** with no UI explanation. — [Cursor forum](https://forum.cursor.com/t/bug-terminalallowlist-forces-allowlist-mode-and-disables-auto-review/167324)
5. **Irreversible reverts.** A revert should itself be undoable or branch the history. — [Windsurf docs](https://docs.devin.ai/windsurf/plugins/cascade/cascade-overview); compare [Replit alternate branches](https://docs.replit.com/core-concepts/agent/checkpoints-and-rollbacks)
6. **Presenting checkpoints as version control.** Cursor's docs warn they track only agent changes and are local. Label scope honestly. — [Cursor checkpoints](https://docs.cursor.com/agent/chat/checkpoints)
7. **A prominent "brave" or YOLO mode as a casual toggle.** JetBrains itself calls Brave Mode "not recommended". Gate full bypass behind Settings, as Claude Desktop does ("Allow bypass permissions mode"). — [Junie docs](https://junie.jetbrains.com/docs/junie-ide-plugin.html); [Claude Code Desktop](https://code.claude.com/docs/en/desktop)
8. **Agent windows that ignore the app theme.** Users complained the Cursor 3 Agents Window doesn't follow VS Code themes. — [Cursor 3 forum](https://forum.cursor.com/t/cursor-3-agents-window/156509)
9. **Unbounded notification toasts.** Cap them and route the overflow to an inbox. — [Warp notifications](https://docs.warp.dev/agents/capabilities/agent-notifications/)
10. **Calling allowlists or classifiers security boundaries.** Cursor's docs describe them as best-effort guardrails, so pair them with a sandbox indicator. — [Tech Dev Notes mirror of Cursor docs, Jun 2026](https://techdevnotes.com/releases/cursor-docs/20260623-002027Z-bb9e53874451) (third-party mirror)
