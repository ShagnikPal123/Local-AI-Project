# Plan: 3D / Game, World, Office and Draw become chat windows; dedicated tabs on request

2026-10-10. Plan only — nothing built. Design context: `docs/DESIGN.md` §5–6; phases in `docs/DESIGN_FIX_PLAN.md`
(Phase B and D). Equalize untouched.

## Idea in one line
The chat opens a **window** beside the conversation when asked ("open the office", "draw a cat", "make a 3D
room", "show the world"). If the user wants it permanent, **/design** (or "make me a tab for this") pins that window
as a dedicated tab. Same component either way.

## What already exists (verified in code) and gets reused
| Piece | Where | Reuse |
|---|---|---|
| Tool registry the model calls | `tools.py` `TOOL_REGISTRY.register(...)`, chat tools in `chat_tools.py` (`register_chat_tools`) | Add one `open_window` tool the same way `chat_new` is registered |
| Server → UI event | `tool_context.emit("chat.created", …)` (see `chat_tools._announce`) → client `state/workspaceEvents.ts` `onWorkspaceEvent` | Emit `window.open`; the chat view listens |
| Declarative user tabs | `dynamic_tabs.py` — a tab is a **spec of known blocks, never code**; `BlockType` already has `EMBED` ("another tab, rendered inline"), `GAME`, `CHAT`; server routes near `server.py:1551` | Add `BlockType.WINDOW` (payload `{kind, ref}`); a pinned tab = a spec containing one WINDOW block. No codegen, same safety model |
| The four engines | `panels/world/`, `panels/office/`, `panels/game/` (+`game_studio.py`), `panels/sketch/` (+`sketch_studio.py`), routes `routes_world/office/game/sketch.py` | Backends and data stay. Only the **entry point** moves |
| Design memory | `design_sense.py`, `design_research/entries.json`, `tab_editor.py` | Feed /design |
| Resource limits | `resource_governor.py` | Decide whether a heavy window may open |

## Design
**Window kinds:** `draw`, `game` (2D/3D/room editor), `office`, `world`, plus later `doc`, `chart`, `code-preview`.
Each kind registers `{ kind, title, Component (lazy), heavy: bool, serialize(), restore(ref) }` in one client
registry (`src/windows/registry.ts`). Adding a kind = one entry, no changes to chat.

**Host (`src/windows/WindowPane.tsx`):** right-hand resizable pane (min 360 px, hideable, Esc to close focus). Tabs
inside the pane if more than one window is open (max 3). Header: title, kind chip, **Retry · Variants · Undo**,
`Pop out`, `Pin as tab`, `Close`. Below 900 px it becomes a full-screen sheet with a clear exit.

**Tool contract:**
```
open_window{ kind: "draw"|"game"|"office"|"world", title?: string, prompt?: string, ref?: string }
  → creates/loads the artifact (engine call), emits window.open{chat_id, kind, ref, title}
  → returns text for the model: "Opened <title> beside the chat (ref …)"
window_action{ ref, action, args }   # the model edits an open window: "add a door", "make it night"
```
Per-agent permission (LibreChat's lesson): windows are allowed per agent/mode, default on for Ichos main chat,
off for sub-agents unless granted. The taint gate (`taint_gate.py`) still applies to anything a window runs.

**Persistence:** every window is saved as an artifact under the chat (`ref` = id in the engine's own store, e.g.
`sketches/`, `games/`, `offices/`, `worlds/`). The message that opened it shows a chip "Reopen · Run again";
"Run again" replays the stored prompt (Higgsfield's *Recreate*). Existing saves in those folders are listed by
"open my office" so nothing the owner built is orphaned.

**Heavy windows:** `heavy:true` (game 3D, world, office floor) → lazy chunk + skeleton with specific status text,
`requestAnimationFrame` paused when the pane is hidden, one heavy window at a time on this 16 GB PC (governor
check before open; if refused, say why and offer to close the other).

**Old tabs:** ids `games`, `office`, `world`, `sketch` stay routable for one release as redirects: they open a
new chat with the window already open (so links and habits still work), then are removed from `CORE_TABS`.

## /design → dedicated tab
1. Triggers: chat "make me a tab for X", the window's **Pin as tab**, or Design destination → **New tab**.
2. **Pin as tab** needs no generation: write a `TabSpec` with one `WINDOW` block (+ title, icon, accent through the
   existing `_validate_icon/_validate_accent`) via `TAB_STORE.create`. Appears in the sidebar under More.
3. **Designed tab** (several blocks, a layout): Stitch-style flow — prompt + Tab/Window toggle + model pill +
   3 suggestion chips → model proposes a `TabSpec` using only `BlockType`s and design tokens → **wireframe preview**
   rendered by the real `DynamicTab` component → refine in chat → Pin. Inputs: `design_sense` + matching
   `design_research` entries + `docs/DESIGN.md` §7 patterns.
4. **Validator before pin** (extend `build_spec`): known blocks only, contrast of any custom accent against
   `surface-1` ≥ 4.5:1, has a title and an empty state, keyboard order = reading order, ≤ 12 blocks.
5. Undo: `tab_editor`'s existing edit history; "Unpin" removes the tab, the window artifact is kept.

## Build order (each step = small commit, tests, live check on the scratch engine `wa-check`, port 8060)
1. **Host + registry + `open_window`/`window.open` plumbing**, with `draw` as the only kind (smallest panel,
   290 lines). Test: tool call → event → pane shows the Draw canvas; reload restores it from `ref`.
2. Strip `SketchPanel`'s own chat/lobby; redirect `sketch` tab. Edit/Undo/Retry wired.
3. `game` window (2D/3D + room editor). Perf check: pause when hidden; measure frame time before/after (this
   closes the "3D build studio performance" complaint).
4. `office` window (drop `office/Chats.tsx`, `Sidebar.tsx`; the main chat replaces them; keep engine + Lobby as the
   window's first screen).
5. `world` window (drop `WorldChat.tsx`; keep lazy planet, pause when hidden).
6. `BlockType.WINDOW` + **Pin as tab**.
7. /design New-tab flow + validator + wireframe preview.
8. Remove redirected ids from `CORE_TABS` after one release; update `AGENTS.md` and the feature catalog.

**Tests per step:** registry unit test (kind → component), tool schema test, event round-trip test, `TabSpec`
validator tests (bad block, low contrast, missing title), restore-from-ref test; Playwright-style live check =
screenshot at 900 px and 1600 px into `design/images/`.

## Risks and answers
- **Chat gets cluttered** → windows live in the pane, not the message list; the message holds only a chip.
- **Losing power-user depth** (each studio had many controls) → keep the engine's full controls inside the window
  (toolbar), only the *chat/lobby chrome* is removed.
- **Heavy windows freeze the app** (past "AI app crashes/freezes") → governor gate + one-heavy rule + lazy load.
- **Generated tabs break the update path** → specs only, never code (existing rule in `dynamic_tabs.py`).
- **Migrating saved worlds/offices** → refs point at the existing stores; no data moves.

## Owner decisions (2026-10-10)
1. **Sub-agents may open and use windows — but each asks first.** → §A.
2. **Modular from day one: every panel can sit anywhere** (top, bottom, left, right, floating), and the assistant can
   live as a **notch** at the top with no window. → §B. Replaces "right pane only".
3. **Voice commands the owner records:** a phrase like "open up" starts listening; "warm up my game" runs a preset
   (opens apps). → §C.
4. "Studios" list page in More: default kept (yes).

## §A — Sub-agent permission to open and drive windows
- First time a sub-agent wants a window, the owner gets one **approval card** (DESIGN.md §7): *"Researcher wants to
  open and work in windows. Allow: Once · Always for this agent · No."* Separate grants for **open** and **interact**
  (`window_action`), since driving a window does more than showing one.
- Grants stored per agent in the existing permission store (`permissions.py`), visible and revocable in
  Settings → Safety → Agents. "Always" never covers irreversible actions inside a window (delete a world, close an
  office run) — those still ask every time.
- A sub-agent's window carries its name + avatar chip in the header so the owner always knows who is driving it.
- The taint gate still runs: after a web/email read in the turn, window actions that touch the machine ask again.
- Tests: no grant → tool returns "asked the owner" and emits `approval.request`; Once grant expires after the turn;
  revoked grant blocks the next call.

## §B — Modular layout: dock any panel anywhere, assistant as a notch
**Model.** The screen is a layout of **slots**: `top`, `bottom`, `left`, `right`, `center`, `float`, plus the
special `notch`. Every panel (chat, a window, Memory, Status, a pinned tab, the assistant) is a **module** with
`{ id, allowed: slot[], minSize, defaultSlot }`. The layout is plain data:
```
layout = { slots: { left: ["sidebar"], center: ["chat"], right: ["window:draw-12"], top: ["notch:assistant"] },
           sizes: { left: 260, right: 420, bottom: 0 }, floats: [{ id, x, y, w, h }] }
```
Saved per user through the existing `ui_state.py` / overlay (data, never code), so updates never wipe it.

**Moving things.** Three ways, all from day one:
1. Each module header has a **⋯ → Move to ▸ Top / Bottom / Left / Right / Float / Notch** menu (keyboard reachable —
   the accessible path, Apple `keyboards.md`).
2. **Drag the header**; drop zones light up at the four edges and centre (VS Code / Blender style).
3. Say it: "put the chat on the bottom", "make the assistant a notch" → a `move_panel` tool.
Plus **layout presets** ("Focus", "Studio", "Voice-only", "Trading") the owner can save and switch by voice or
`Ctrl+K`. Reset to default is always one click.

**Notch mode for the assistant** (masterplan's pill spec, already designed for Mission Control):
collapsed 380 × 32 at top-centre, square top flush with the edge, 14 px bottom corners; shows state (idle /
listening / thinking / speaking) as a thin waveform + one line; **hover or wake phrase expands** to 380 × 196 with
the last answer, a mic button and "Open in chat". No chat window needed. Inside the app it is a module in the `top`
slot; **outside the app** (when Ichos is minimised) the same notch runs as a small always-on-top window — that half
needs the desktop shell (`launcher.py` / overlay window) and comes after the in-app version.

**Rules that keep it from turning into a mess.** Each slot holds ≤ 3 modules as tabs; sizes snap to 4-pt steps;
below 900 px width, side slots collapse into sheets; a module refuses slots it can't work in (a 3D world won't go
into the 32 px notch) and says so; reduced motion turns drag animation off.

**Build impact on the plan:** step 1 of the build order becomes **"layout engine + module registry + Move-to
menu"**, and `WindowPane` becomes just one module type. Windows open in the slot the owner last used for that
kind (default right).

## §C — Recorded voice commands and routines
Reuses what exists — no new voice stack:
- `voice_gestures.py` ("Clap") already stores **taught phrases** with actions `say / listen / status / command`,
  and the browser matches them offline (`src/voice/clapDetector.ts`).
- `proto_voice.py` already has wake words and "wake up / start listening" detection.
- `machine_tools.open_app` / `open_path` / `open_url` already launch apps, files and sites.

**Add:**
1. **Record a command** (Settings → Voice → Commands → "Record"): say the phrase 3 times → stored as a taught
   template (shape only, no audio kept, as today) **and** as text, so it matches either by sound or by the
   transcript.
2. A new action **`routine`**: an ordered list of steps the owner builds once —
   `open_app("Steam")`, `open_app("Discord")`, `open_url(...)`, `open_window(game)`, `set_layout("Studio")`,
   `say("Game's warming up")`, `wait(5s)`. Example presets: **"open up"** → start listening; **"warm up my game"**
   → Steam + Discord + OBS + layout "Gaming" + volume note.
3. Routines are **data** (step names from a fixed list, never scripts) and each step goes through the normal tool
   path, so safety (taint gate, approvals) still applies. First run of a new routine shows the steps and asks
   once; after that it runs on the phrase. Any step that fails is reported in one line; the rest still run.
4. The notch shows the routine running as a checklist (✓ Steam · ✓ Discord · … ) — proof over promises.
5. Can also be triggered by `Ctrl+K`, a button in the notch, or typing the phrase.

**Note on the Equalize hold:** this lives in the voice-gestures/Clap layer and Settings, not in the Equalize tab,
so it can be built without lifting the hold. When Equalize resumes it uses the same routines.

## Updated build order
1. Layout engine: slots, module registry, Move-to menu, drag-to-dock, presets, saved layout.
2. Notch module (in-app) for the assistant.
3. `open_window` + Draw window as a module (previous steps 1–2).
4. Voice commands: record phrase + `routine` action + routine editor + notch checklist.
5. Sub-agent window permissions (§A).
6. Game/3D → Office → World windows (previous steps 3–5).
7. `BlockType.WINDOW` + Pin as tab → /design flow → remove old tab ids (previous steps 6–8).
8. Desktop-level notch (always-on-top outside the app).

## Still open (defaults in bold)
- Notch outside the app as well as inside? **Inside first, outside in step 8.**
- Routines that close apps or change system settings? **Not at first — open/launch/say/layout only.**

## Research updates (2026-10-10, from `reports/Ichos design research sweep.md`) — these override the sections above
- **§A grants:** scopes are *Allow once · This task · Always for this agent · Deny*; an always-ask list no grant covers
  (deletes, closing a running office, purchases, accounts, sending messages, system settings); approval cards are never
  pre-ticked and never change a setting beyond the grant they name. An agent-driven window shows an AI-presence outline,
  step checklist and **Take control · Pause · Stop**; logging pauses during takeover.
- **§B docking:** use **dockview** behind a thin `layoutService.ts` (swappable; FlexLayout as fallback;
  react-resizable-panels for splits inside a panel). Pin the version and check nothing needed is in `dockview-enterprise`;
  give its container an explicit height. Build the keyboard path ourselves ("Move focused panel…" quick-pick). Add
  auto-hide view mode and per-panel *Reset location*. Version presets with a migrator; on load failure fall back to
  the default layout + toast; `--reset-layout` flag. Popouts must read the same tokens.
- **§B notch:** a native window exactly the pill's size, resized per state — no click-through tricks (Tauri drops mouse
  events; Electron's forward works). Expand on wake phrase **without stealing focus**. Hide in full-screen apps by
  polling `SHQueryUserNotificationState` from the backend. Shrink while a window is dragged (Snap bar lives top-centre).
  **Hotkey must avoid Alt+Space / Ctrl+Alt+Space / Win+Alt+Space** (ChatGPT, Gemini, Claude Desktop, PowerToys);
  detect a failed registration and offer rebind. Do not copy boring.notch code (GPL-3.0).
- **§C voice:** typed text is the source of truth; the 3 recordings show "I heard: …" and offer recogniser variants as
  aliases (no audio kept). Wake word required by default — "open up" / "warm up my game" alone are short common phrases
  that will misfire; bare phrases are an opt-in per phrase after a lint warning. ≤ 8 steps (Windows Voice Access cap).
  Re-approve whenever a routine's steps change (store a hash). Mute command matching while Ichos speaks; barge-in stops
  speech within a few hundred ms. Caption both sides. Picovoice's free tier ended 30 June 2026 and openWakeWord's models
  are non-commercial — stay with transcript + text matching.
