# Docking panels and notch/launcher assistant UIs (research for Ichos, Oct 2026)

Scope: dockable/floating/pop-out panels with saved layout presets in a React + TypeScript UI wrapped for Windows 11, plus an always-on-top "notch" pill that expands on hover or a wake phrase. Research ran to 2026-10-10 with about 17 search and fetch calls. Every line under "Cited Findings" has a source. Lines under "Inferences" are reasoning or unverified background knowledge and are labelled that way.

---

## 1. Docking UX in professional apps

### Takeaway
VS Code and JetBrains share one model. Every view has a **home region** (left, right, bottom or top) and can be moved by drag, by a context-menu or keyboard command ("Move View"), or detached into its own OS window. Each item and the whole layout always have a **reset**. JetBrains adds named layouts and per-window modes (pinned, unpinned, float, window). Ichos should copy this vocabulary.

### Cited Findings
**VS Code (official docs, `code.visualstudio.com/docs/configure/custom-layout`)**
- The Panel can sit Left, Right, Bottom or Top. Move it with View > Appearance > Panel Position, the panel title context menu, or the commands `workbench.action.positionPanelLeft/Right/...` — [VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
- Panel alignment can be Center (the default), Justify, Left or Right. The Activity Bar counts as the window edge. With Center alignment a chevron maximises the panel, and "View: Toggle Maximized Panel" does the same — [VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
- The Primary Side Bar can go left or right (`workbench.sideBar.location`). The Secondary Side Bar always sits on the opposite side. Ctrl+Alt+B toggles it on Windows. `workbench.secondarySideBar.defaultVisibility` controls whether it shows by default — [VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
- Views can be dragged between the side bars and the Panel. Dropping one view onto another creates a group. **Keyboard alternative:** "View: Move View" and "View: Move Focused View". **Reset:** the per-view context item "Reset Location" or "View: Reset View Locations" — [VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
- The Activity Bar position can be Default, Top, Bottom or Hidden. `workbench.activityBar.compact` gives a compact size — [VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
- The title-bar "Customize Layout" dropdown holds Full Screen (F11), Zen Mode (Ctrl+K Z), Centered Layout and **Restore Defaults** — [VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
- **Editor groups:** split left, right, above or below from the tab menu or View > Editor Layout (for example Grid 2x2). Shift+Alt+0 toggles vertical or horizontal. Ctrl+K Ctrl+M maximises a group. `workbench.editor.doubleClickTabToToggleEditorGroupSizes` takes `expand`, `maximize` or `off` — [VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
- **Auxiliary (floating) windows:** drag an editor outside the window, or use the tab menu items "Move into New Window" (`workbench.action.moveEditorToNewWindow`) and "Copy into New Window" (Ctrl+K O). Whole groups can be moved or copied too. Floating windows offer **Compact Mode** and **Always on Top** in their title bar — [VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
- Not every view is movable in practice. A March 2026 issue reported that the Claude Code extension panel could not be dragged or moved to the Secondary Side Bar; it was marked resolved on 2026-03-29 — [claudeissues.com #38849](https://claudeissues.com/issue/38849-vs-code-claude-code-panel-cannot-be-moved-to-side-bar-or-resized-wider)

**JetBrains (IntelliJ docs)**
- Tool windows have these view modes: **Dock Pinned** (the default; stays visible next to the editor), **Dock Unpinned** (visible only while active), **Undock** (overlays the editor while active and hides when another tool window activates), **Float** (detached and floating over the main window, but shown only with the project window; can move to another monitor) and **Window** (a separate OS window that can be viewed on its own) — [IntelliJ Viewing modes](https://www.jetbrains.com/help/idea/viewing-modes.html)
- Change the mode from Window | Active Tool Window | View Mode or from the tool window header's Options menu. The current arrangement of tool windows and their modes can be saved as a named **layout** — [IntelliJ Viewing modes](https://www.jetbrains.com/help/idea/viewing-modes.html)

**PowerToys Command Palette Dock (Windows reference for edge bars)**
- PowerToys 0.98 (17 March 2026) added an optional preview "Dock". It is a persistent toolbar on a screen edge (top, left, right or bottom) with pinned commands, files, folders and URLs. Early coverage called it experimental — [Liliputing](https://liliputing.com/microsoft-powertoys-could-bring-a-configurable-dock-to-windows-11/), [PCWorld](https://www.pcworld.com/article/3225916/this-free-powertoys-command-bar-replaces-several-windows-search-features.html)

### Inferences
- These are the patterns to copy:
  1. Each panel has a home slot plus a "Move to ▸ Left / Right / Bottom / Top / Float / New window" context menu.
  2. Drag-to-dock uses overlay drop zones.
  3. A keyboard "Move focused panel" command opens a quick-pick of the slots.
  4. "Reset location" works per panel, and "Reset layout" is global.
  5. Layouts are named and saved (JetBrains "Save Current Layout as New").
- Unverified background knowledge (no source fetched; check before quoting):
  - Blender areas are split or joined by dragging corner widgets. Ctrl+Space maximises an area. Workspaces are tabs of saved area layouts.
  - Photoshop and Unreal show blue drop-target highlights and a five-way "compass" dock target. Both have Window > Workspace or Layouts menus with save and reset.
  - Obsidian has a core "Workspaces" plugin for saving and loading named layouts. Panes can pop out to new windows.
  - Arc, Zen and Edge have split view: two to four web panes in one tab.
  - Windows 11 Snap Layouts appear when you hover the maximise button or press Win+Z, and show 4 to 6 zone templates.
- Figma's panels are mostly fixed (left layers, right properties). It is not a good docking reference.

### Gaps
- No primary sources were fetched for Blender, Figma, Photoshop, Unreal, Obsidian, Arc, Zen, Edge split view or Windows 11 Snap Layouts. The details above come from memory and need verifying.
- The JetBrains "Move to" submenu names (Left Top, Bottom Left, Right Bottom and so on), the Split mode, and the keyboard shortcuts (Ctrl+Shift+F12, Shift+Escape, Ctrl+Shift+Arrow) were not on the fetched page.
- No source documented exact drop-zone sizes or percentages in any of these apps.

---

## 2. React docking libraries compared

### Takeaway
**dockview** is the only candidate with floating groups, popout windows and JSON serialisation all built in, and with zero runtime dependencies. FlexLayout is the closest rival: React-only, JSON model, actively released, with "borders" plus float and popout. react-resizable-panels and allotment are split-pane primitives, not docking managers. react-mosaic is a tiling manager without tabs or popouts.

### Cited Findings
- **dockview**
  - Docking layout manager with tabs, groups, drag and drop, floating panels and popout windows. Layouts are saved and restored with `api.toJSON()` and `api.fromJSON()` — [dockview.dev](https://dockview.dev/)
  - Core is vanilla TypeScript with zero dependencies, wrapped for React and Vue — [HN, author mathuo](https://news.ycombinator.com/threads?id=mathuo)
  - The repo is now `github.com/dockview/dockview` (about 3.5k stars). Packages are `dockview` (vanilla, zero deps), `dockview-react` (peer React 16.8 to 19), `dockview-vue` (Vue ≥3.4) and `dockview-angular` (Angular ≥21.0.6).
  - Listed features: serialisation, split, grid and dockable views, drag and drop, floating groups, popout windows, themes, touch, Shadow DOM.
  - **New:** "Everything is MIT except `dockview-enterprise`, which is proprietary." React needs a container with explicit height (for example `100dvh`).
  - The README does not mention keyboard or accessibility support.
  - Source for the four points above: [GitHub dockview](https://github.com/mathuo/dockview)
- **rc-dock**
  - React-only. The model is LayoutData > BoxData > PanelData > TabData. It has controlled and uncontrolled modes and `saveLayout`, `loadLayout` and `dockMove`. Floating panels are supported, and the npm listing indicates panels can pop out to a new browser window.
  - The changelog seen dates from 2023, which suggests slower releases.
  - Sources: [rc-dock README](https://cdn.jsdelivr.net/npm/rc-dock@4.0.2/README.md), [npm rc-dock](https://npmjs.com/package/rc-dock)
- **golden-layout**
  - The original JS layout manager, with movable and resizable tabs and tab sets. It is vanilla, so React use goes through a wrapper — [LibHunt golden-layout](https://www.libhunt.com/r/golden-layout)
- **FlexLayout (flexlayout-react)**
  - Its only dependency is React. v0.11.0 was published about 12 days before the snapshot. About 54k weekly downloads, MIT.
  - Beware the unrelated fork `@massbug/flexlayout-react`.
  - Sources: [npm flexlayout-react](https://www.npmjs.com/package/flexlayout-react), [LibHunt FlexLayout](https://www.libhunt.com/r/caplin/FlexLayout)
- **react-mosaic-component**
  - React tiling window manager with drag-to-resize and drag-to-rearrange. v7.0.0, about 69k weekly downloads, Apache-2.0, 11 dependencies — [npm react-mosaic-component](https://www.npmjs.com/package/react-mosaic-component)
- **react-resizable-panels**
  - v4.14.3, about 25.6M weekly downloads, MIT — [npm](https://www.npmjs.com/package/react-resizable-panels)
  - Average issue resolution is about 9 days — [LFX Insights](https://insights.linuxfoundation.org/project/bvaughn-react-resizable-panels)
  - Commonly cited for nested groups, persisted layouts and keyboard and accessibility support (the separator is a focusable splitter) — [PkgPulse 2026](https://www.pkgpulse.com/guides/react-resizable-panels-vs-split-js-vs-allotment-2026)
- **allotment**
  - Derived from VS Code's split-view code — [GitHub allotment](https://github.com/johnwalley/allotment)
  - About 203k weekly downloads, described as "heavier and more opinionated" — [PkgPulse 2026](https://www.pkgpulse.com/guides/react-resizable-panels-vs-split-js-vs-allotment-2026)

| Library | Docking / tabs | Floating | Popout window | Serialise | Licence | Maintenance signal |
|---|---|---|---|---|---|---|
| dockview | yes | yes (floating groups) | yes | toJSON/fromJSON | MIT (core); enterprise tier proprietary | active, ~3.5k stars |
| FlexLayout | yes (tabsets + borders) | see gap | see gap | JSON model | MIT | v0.11.0, recent |
| rc-dock | yes | yes | yes (per npm) | saveLayout/loadLayout | see gap | slower (2023 changelog) |
| golden-layout | yes | see gap | see gap | yes (config) | see gap | see gap |
| react-mosaic | tiling, no tabs | no | no | tree object | Apache-2.0 | v7.0.0 |
| react-resizable-panels | split panes only | no | no | autoSave/persist | MIT | very active |
| allotment | split panes only | no | no | see gap | see gap | moderate |

(Sources are the rows above.)

### Inferences
- dockview fits Ichos best: popouts and floating are built in, the core is framework-agnostic and has zero deps, and serialisation matches "layout presets".
- Do not depend on `dockview-enterprise` features. Check which features (if any) moved behind the commercial tier before you pin a version.
- react-resizable-panels is still worth using *inside* a dockview panel, or for the main shell if full docking is postponed.
- Keyboard accessibility of dockview drag and drop is unverified. Plan to add your own "Move focused panel to..." command palette action, which calls `api.addPanel({ position: { referenceGroup, direction } })` or `group.api.moveTo`. This matches VS Code's "Move View" pattern anyway.

### Gaps
- No verified minified and gzipped bundle sizes for any library. Check bundlephobia for the exact versions.
- Not confirmed: FlexLayout float and popout support (believed to support "popout" via `window.open` in recent versions), golden-layout 2.x maintenance and licence, and allotment's licence.
- No dockview release number or date was visible (the GitHub Releases section was empty in the fetch).
- No source found on dockview keyboard or ARIA support.

---

## 3. Ambient, notch and launcher assistants

### Takeaway
Every reference uses a small set of **escalating states**: a tiny persistent indicator, a compact status, an expanded interactive card, and a full window. You move between them by hover, click or long-press, or a global hotkey. The most common Windows hotkeys sit in the Alt+Space family (ChatGPT Alt+Space, Claude Ctrl+Alt+Space, PowerToys Win+Alt+Space). Conflicts are common, so the hotkey must be user-configurable.

### Cited Findings
- **Apple Dynamic Island (ActivityKit)**
  - **Compact**: one Live Activity shown as leading and trailing views on either side of the TrueDepth camera, reading as one cohesive view.
  - **Minimal**: used when several activities run. Two show: one attached to the island and one detached circular or oval bubble.
  - **Expanded**: shown on press-and-hold, keeping the capsule shape.
  - Source: [Apple – Displaying live data with Live Activities](https://developer.apple.com/documentation/activitykit/displaying-live-data-with-live-activities.md), [Infinum](https://infinum.com/?p=28092)
- The minimal-presentation image maximum is quoted as 45×36.67 pt (third-party guide, not Apple) — [Canopas guide](https://canopas.com/integrating-live-activity-and-dynamic-island-in-i-os-a-complete-guide)
- **boring.notch** (macOS)
  - Opens on **hover** only ("Hover over the notch to see it expand"). Contents: music controls with a visualiser, a file shelf with AirDrop, calendar, and a HUD replacement (partly roadmap).
  - Gestures and notch-size fine-tuning are on the roadmap. No hover-delay setting is documented.
  - **Licence GPL-3.0**: do not copy its code into a non-GPL Ichos.
  - Source: [GitHub boring.notch](https://github.com/TheBoredTeam/boring.notch)
- **NotchNook, Alcove**
  - Paid, proprietary "Dynamic Island for Mac" apps. Alcove advertises fluid transitions, live activities, swipe gestures, customisable HUDs and lock-screen presence.
  - NotchBar is described as a "hover-to-expand system hub".
  - Source: [AlternativeTo NotchNook](https://alternativeto.net/software/notchnook), [AlternativeTo Boring Notch](https://alternativeto.net/software/the-boring-notch)
- **ChatGPT for Windows**
  - **Alt+Space** opens a "companion window" (ask, upload files, new chat) while the app runs. It remembers its last position and resets to **bottom-centre** of the screen.
  - The hotkey fails if another app already registered it. Change it in Settings > App > Companion window hotkey; it must start with Shift, Ctrl, Alt or Win.
  - Source: [OpenAI Help 9982051](https://help.openai.com/en/articles/9982051), [Pureinfotech](https://pureinfotech.com/chatgpt-app-windows-features/)
- Users asked for a hotkey for "Open in main window" from the companion. It was not available at the time — [OpenAI community](https://community.openai.com/t/windows-desktop-companion-add-a-keyboard-shortcut-for-open-in-main-window/1389533)
- **Claude Desktop**
  - Quick Entry is documented for Mac. The Mac voice-dictation shortcut is Caps Lock, off by default — [Claude Help 12626668](https://support.claude.com/en/articles/12626668-use-quick-entry-with-claude-desktop-on-mac)
  - A Windows user report says Settings exposes only **Ctrl+Alt+Space** for quick chat and has no voice hotkey. The configurable-voice-hotkey request was closed on 2026-05-19, and what shipped is unclear — [GitHub anthropics/claude-code #59400](https://github.com/anthropics/claude-code/issues/59400)
- **PowerToys Command Palette**
  - **Win+Alt+Space** (configurable). It is the successor to PowerToys Run and must be running in the background — [Microsoft Learn](https://learn.microsoft.com/en-us/windows/powertoys/command-palette/overview)

### Inferences
- A notch on Windows has no hardware notch to hide behind. It is a floating pill at top-centre, which also collides with Windows 11's Snap bar: dragging a window to the top edge shows a snap-layout flyout at the top-centre. Leave a gap, or make the pill click-through while a window drag is in progress.
- Map Dynamic Island states to Ichos as minimal (a dot), compact (the pill) and expanded (a card). Use an expanded hover/long-press affordance, never a modal.
- Unverified background knowledge (no source fetched):
  - Raycast AI Chat is a separate floating window with presets.
  - Alfred uses Alt+Space by default.
  - Windows' Copilot key launches the Copilot app (or a remappable app); Microsoft has shipped "Copilot Vision" and "press-to-talk" (hold the Copilot key or Alt+Space in Copilot). Treat as unverified.
  - Teams and Zoom shrink to a compact always-on-top meeting window when minimised.

### Gaps
- Apple's official point sizes for compact, expanded and island corner radius could not be fetched: the HIG page returned only a title.
- NotchNook and Alcove sizes, hover delays and animation timings were not found in primary sources.
- Windows Copilot key and Copilot quick view behaviour, Perplexity desktop and Raycast window sizes were not researched successfully (no primary sources returned).
- No source gave concrete listening, thinking or speaking visuals from these products.

---

## 4. Windows implementation: always-on-top pill outside the main window

### Takeaway
Electron and Tauri both offer frameless, transparent, always-on-top, skip-taskbar windows plus click-through. **Hover-to-expand while click-through is the hard part.** Electron's `setIgnoreMouseEvents(true, { forward: true })` still delivers mouse-move events on Windows, so CSS hover works. Tauri's `set_ignore_cursor_events` does not, so you have to poll the cursor from Rust. Full-screen and presentation detection uses `SHQueryUserNotificationState`, which you must **poll** because no event fires.

### Cited Findings
- **Electron `setIgnoreMouseEvents(ignore, { forward })`**: `forward` works on macOS **and Windows*. It "forwards mouse move messages to Chromium, enabling mouse related events such as `mouseleave`". It applies only when `ignore` is true — [Electron BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)
- **Electron `setAlwaysOnTop(flag, level)`**: the default level is `floating`. "From `pop-up-menu` to a higher it is shown ... above the taskbar on Windows". Levels include `status`, `pop-up-menu` and `screen-saver` — [Electron BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)
- Other Electron window APIs:
  - `setSkipTaskbar` works on Windows.
  - `setFocusable` works on Windows and macOS.
  - `setVisibleOnAllWorkspaces` "does nothing on Windows". Windows 11 virtual desktops need another approach.
  - `setContentProtection` uses `WDA_EXCLUDEFROMCAPTURE`, which removes the window from capture on Windows 10 2004 and later. Optional, for private overlays.
  - Source: [Electron BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)
- **Tauri `set_ignore_cursor_events(true)`**: once it is set, JS mouse events only work while the window is focused. Rust-side enter and leave detection was requested, and the workaround is polling the cursor position in Rust and hit-testing — [tauri#9250](https://github.com/tauri-apps/tauri/issues/9250), [CodeWalkers click-through logic](https://deepwiki.com/you-want/CodeWalkers/2.1.1-window-and-click-through-logic)
- On Windows 10, a Tauri child webview window with `setIgnoreCursorEvents(true)` still could not be clicked through. Unresolved — [tauri#11461](https://github.com/tauri-apps/tauri/issues/11461)
- Electron click-through overlays on Windows exist in practice (Glass Browser toggles click-through) — [glass-browser](https://github.com/mitchas/glass-browser)
- **Full-screen and do-not-disturb detection: `SHQueryUserNotificationState`** (Shell32, Vista and later). Show notification UI only when it returns `QUNS_ACCEPTS_NOTIFICATIONS`, and only critical items under `QUNS_QUIET_TIME`. Top-level windows get `WM_SETTINGCHANGE` when presentation mode or session lock changes, but "**there are no notifications sent when the user starts or stops a full-screen application**", so you must poll — [Microsoft Learn SHQueryUserNotificationState](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shqueryusernotificationstate)

### Inferences
- These points are from background knowledge (no source fetched):
  - The enum values `QUNS_BUSY` (a full-screen app is running), `QUNS_RUNNING_D3D_FULL_SCREEN` (an exclusive D3D game) and `QUNS_PRESENTATION_MODE` should all hide the pill. Check them on the [QUERY_USER_NOTIFICATION_STATE enum page](https://learn.microsoft.com/en-us/windows/desktop/api/shellapi/ne-shellapi-query_user_notification_state).
  - Ichos's local backend is Python, so the poll (every 2 to 5 s) can run there via `ctypes.windll.shell32.SHQueryUserNotificationState`, or in the Electron or Tauri host.
- **Multi-monitor and DPI** (background knowledge, unverified):
  - Place the pill on the display under the cursor, or on the primary display. Use the work area (excluding the taskbar) from `screen.getDisplayNearestPoint` in Electron or `current_monitor` / `available_monitors` in Tauri.
  - Size the window in DIPs (380×32 logical) and let the framework scale it. Re-centre on `display-metrics-changed` or `ScaleFactorChanged`.
  - A top-centre pill sits above the work area. If the taskbar is moved to the top (rare in Windows 11), use the work-area top.
- **Wrapping choice:**
  - Electron's `forward:true` makes hover-expand on a click-through pill nearly free.
  - Tauri (WebView2, smaller install, fits "keep it small") needs a Rust cursor-poll loop, about every 16 to 50 ms while near the pill.
  - A third option avoids click-through entirely: make the window exactly the pill's size (no transparent margins) and resize the native window when it expands. Hit-testing is then trivial and you don't need click-through. It is what most notch apps effectively do.
- **WebView2 transparency** (background knowledge, unverified): Tauri `transparent: true` + `decorations: false` + `alwaysOnTop: true` + `skipTaskbar: true`, with the CSS `html, body { background: transparent }`. Windows 11 rounded-corner and shadow DWM attributes may need disabling for a crisp custom shape.

### Gaps
- No verified source on WebView2 transparent-window quirks in Tauri v2 on Windows 11 (for example the shadow, or a resize flicker when animating the native window size).
- No primary source on behaviour across Windows 11 virtual desktops for topmost windows.
- No fetched source on per-monitor-v2 DPI handling specifics in Tauri or Electron.

---

## 5. Recommended approach for Ichos

### Takeaway
Use **dockview** (MIT core only) with a fixed **slot model** (left, right, bottom, top, centre, float, popout) and named JSON presets. Build the notch as a **separate small topmost window**, sized to its content and resized per state, so you never need complex click-through. Pause it automatically when `SHQueryUserNotificationState` reports full-screen, D3D or presentation.

### Cited Findings
- dockview provides floating groups, popout windows, `toJSON`/`fromJSON` and zero-dep core packages, with an MIT core and a separate proprietary enterprise tier — [GitHub dockview](https://github.com/mathuo/dockview), [dockview.dev](https://dockview.dev/)
- The VS Code pattern to mirror is drag, plus a "Move View" command, per-view "Reset Location", and global Restore Defaults — [VS Code Custom Layout](https://code.visualstudio.com/docs/configure/custom-layout)
- The JetBrains pattern is per-panel modes (pinned, unpinned, float, window) and saved layouts — [IntelliJ Viewing modes](https://www.jetbrains.com/help/idea/viewing-modes.html)
- Alt+Space-family hotkeys conflict, so the companion hotkey must be configurable — [OpenAI Help](https://help.openai.com/en/articles/9982051)

### Inferences (the recommendation)
**Library:** dockview-react, core MIT packages only.
- It is the only option with floating, popout and serialisation built in, and it has zero runtime deps (fits "keep it small").
- Keep react-resizable-panels as a fallback for simple splits inside panels.
- Pin the exact version. Wrap every dockview call in a thin `layoutService.ts` so the library could be swapped for FlexLayout.

**Slot model:**
- Slots: `left`, `right`, `bottom`, `top`, `center` (main, the editor-group equivalent), `float` and `popout`.
- Each panel registers `{id, title, icon, defaultSlot, allowedSlots, minSize, singleton}`.
- Context menu on each tab: Move to ▸ Left / Right / Top / Bottom / Centre / Float / Pop out, then Reset location, then Close.
- A keyboard command "Move focused panel…" (Ctrl+K M) opens a quick-pick of slots. Use Ctrl+Alt+Arrow to move to an adjacent slot.
- Drag: dockview's overlay drop zones. Edges dock into the neighbouring slot, the centre adds the panel as a tab.
- **Presets:** store `api.toJSON()` plus `{name, version, createdAt}` under `layouts/` in Ichos user data. Ship built-in presets: "Chat focus", "Workbench", "World" and "Compact". Provide "Save current as…", "Reset to default" and per-panel "Reset location".
- Add a schema `version` and a migrator. If `fromJSON` fails (an unknown panel id, say), fall back to default and show a toast.
- Popouts: dockview popouts use `window.open`. In the desktop wrapper, intercept new windows so they open as frameless child windows with an "Always on top" toggle and a "Compact mode" toggle, like VS Code floating windows.

**Notch / pill spec** (sizes from the masterplan; the states are a proposal):

| State | Size (logical px) | Shape | Content | Enter by |
|---|---|---|---|---|
| hidden | 0 | — | — | full-screen, D3D or presentation (SHQUNS); user "Do not disturb" |
| minimal (idle dot) | 120×6 (proposal) | 3 px radius bar at top edge | breathing accent line | idle > N s with no activity (optional) |
| compact (collapsed) | **380×32** | top-centre, flush to top, **14 px bottom corners**, 0 top corners | identity glyph, status text ("Ready", "Listening…"), mini waveform or spinner | default; hover-out after 300–400 ms; Esc |
| expanded | **380×196** | same, 14 px bottom corners | last reply (2–3 lines), input box, mic button, 3 quick actions, "Open Ichos" | hover dwell ~150–250 ms (proposal), click, global hotkey (default Ctrl+Alt+Space, configurable), wake phrase |
| listening | 380×32 or expanded | compact + live mic level bars | "Listening…" with transcript ticker | wake phrase or push-to-talk |
| thinking | 380×32 | shimmer or indeterminate bar on the bottom edge | "Thinking…" with tool name | after the utterance ends |
| speaking | 380×32 or expanded | TTS amplitude waveform | caption of the spoken sentence; click to stop (barge-in) | TTS playback |
| alert | 380×64 (proposal) for 4 s | auto-expands briefly | notification (task done, reminder) | backend event, only if SHQUNS accepts notifications |

- Window: frameless, transparent, `alwaysOnTop` (Electron: level `pop-up-menu` or `screen-saver`; Tauri: `alwaysOnTop`), skipTaskbar, non-focusable until expanded.
- **Resize the native window per state** instead of a large transparent click-through window. If a larger canvas is needed for animation, use Electron `setIgnoreMouseEvents(true,{forward:true})` outside the pill rect, or Tauri plus a Rust cursor poll.
- Animate the size with a spring (about 250 ms) and snap the native window bounds at the end, or pre-grow the window and animate CSS inside it.
- Expand on a wake phrase **without stealing focus**. Take focus only when the user clicks the input box or uses the hotkey.
- Multi-monitor: by default, show on the display containing the cursor or the main Ichos window, with a setting for "Always primary". Recompute on display or DPI change.
- Avoid the Snap-bar collision: while the user drags any window near the top edge, the pill should shrink to minimal or be click-through.

### Gaps
- The hover dwell, minimal-dot size and alert height above are proposals, not sourced figures.

---

## 6. Pitfalls

### Takeaway
Most of the risk sits at the edges: licences (GPL boring.notch, the dockview enterprise tier), hover detection on click-through windows in Tauri, hotkey collisions, no event for full-screen apps, and layout JSON that breaks across versions.

### Cited Findings
- boring.notch is GPL-3.0, so copying its code would force Ichos to be GPL — [GitHub boring.notch](https://github.com/TheBoredTeam/boring.notch)
- dockview-enterprise is proprietary. Only the core packages are MIT — [GitHub dockview](https://github.com/mathuo/dockview)
- Tauri click-through kills JS hover events unless the window is focused. Child webviews may not click through at all — [tauri#9250](https://github.com/tauri-apps/tauri/issues/9250), [tauri#11461](https://github.com/tauri-apps/tauri/issues/11461)
- A global hotkey silently fails if another app has registered it — [OpenAI Help](https://help.openai.com/en/articles/9982051)
- Windows sends no notification when full-screen apps start or stop, so you must poll `SHQueryUserNotificationState` — [Microsoft Learn](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shqueryusernotificationstate)
- `setVisibleOnAllWorkspaces` does nothing on Windows — [Electron BrowserWindow](https://www.electronjs.org/docs/latest/api/browser-window)
- dockview React needs an explicitly sized container, otherwise it renders at zero height — [GitHub dockview](https://github.com/mathuo/dockview)
- Some views end up non-movable by accident (the VS Code Claude panel issue). Test "Move to" for every panel type — [claudeissues #38849](https://claudeissues.com/issue/38849-vs-code-claude-code-panel-cannot-be-moved-to-side-bar-or-resized-wider)

### Inferences
- **Popout windows are separate documents.**
  - React state, context and CSS-in-JS styles must reach them, through portals plus stylesheet copying (dockview handles some of this).
  - Websockets or event buses must survive the popout window closing.
  - Popouts opened with `window.open` inside Electron or Tauri need explicit handling, or they open in the system browser or get blocked.
- **Layout JSON drift.** Renamed or removed panel ids break `fromJSON`. Always version and migrate, and keep a "Reset layout" escape hatch reachable from the tray and a CLI flag (`--reset-layout`).
- **Focus stealing.** A topmost pill that grabs focus on a wake phrase will eat the user's keystrokes in games and documents. Expand visually without activating.
- **Top-edge collisions.** Windows 11 Snap Layouts, full-screen video controls and browser tab strips all use the top-centre. Provide an offset setting and auto-hide.
- **DPI and multi-monitor.** Mixed-DPI setups cause blurry or mis-sized pills if you size in physical pixels. Size in logical units and re-layout on scale changes.
- **Animations and the GPU.** A permanently running waveform or shimmer in a topmost transparent window costs GPU and battery. Pause animations in idle and compact states, and honour `prefers-reduced-motion`.
- **Accessibility.**
  - Hover-only expansion excludes keyboard and touch users. Always provide hotkey and click equivalents.
  - Announce state changes (listening, thinking, speaking) through an ARIA live region.
  - Keyboard-only docking needs the "Move focused panel" command, because drag and drop alone is not accessible.

### Gaps
- No source quantified the CPU or GPU cost of transparent topmost WebView2 windows.
