# Design fix plan — older tabs, Second Brain, and folding windows into chat

Companion to `docs/DESIGN.md` (written 2026-10-10). Nothing here is built yet. Equalize stays on hold.
Items marked *verify* come from reading code (the app was not running) — look at them on screen first.

## What is wrong now (from the audit)

1. **31 core tabs** (`frontend/nyx-pulse/src/tabs.ts`), 21 of them pinned. No hierarchy; features that overlap
   (Models / Keys & Models / Connectors / Add capability; Dashboard / Power / Sessions & Memory) each get a tab.
2. **Each old tab invented its own look.** 3,516 lines of per-panel CSS (`panels/*/*.css`) plus `nyx.css`,
   `theme.css`, `index.css` — no shared page skeleton, so some tabs open with no header, no empty state and
   nothing that says what to do ("don't have the outline to start off with").
3. **Second Brain feels weird** (*verify*): it is three different things stacked — a `Chat | Second Brain` segmented
   switch inside the Nyx tab (`panels/NyxPanel.tsx:280`), a 3-D particle Core with ring gauges, APIs, sub-agent dock
   and processes (`components/brain/CoreView.tsx`, 639 lines; `BrainField.tsx`, 625), and a Second Brain card pinned
   in the chat rail (`components/chat/ChatRail.tsx:194`). A switch that changes the *whole screen* is a
   destination wearing a segmented control; the Core mixes a glanceable status wall with a memory visual, and the
   rail card repeats it a third time. Heavy WebGL is the first paint.
4. **World / Office / Game / Create** are full tabs with their own lobbies, chats (`world/WorldChat.tsx`,
   `office/Chats.tsx`) and sidebars — each re-implements a chat that the main chat already has.
5. Contrast: `--text-dim #8d8d98` is borderline on `surface-2` (computed 5.6:1 — passes AA, fails the 7:1 target
   in DESIGN.md §2). Icon-only controls lack labels in places (`◐` button, `ChatRail.tsx:114` has one; audit the rest).

## Phases (each = small commits, tested, checked in the running app with a screenshot)

### Phase 0 — foundations (no visible change, 1 session)
- Add `src/ui/` kit: `PageShell` (header, body, status line), `EmptyState`, `Card`, `Chip`, `SegmentedControl`,
  `Skeleton`, `AiBlock` (Copy/Retry/Edit/feedback), `Toast` (reuse existing). All read tokens from `theme.css`.
- Put the DESIGN.md tokens in `theme.css` (new `--surface-1/2/3`, `--text-dim` raised); keep old names as aliases so
  nothing breaks.
- Add a lint test: fail the build on hard-coded hex inside `panels/**` (allow-list the Core canvas).
- Add `Ctrl+K` command palette listing every tab and action (also the safety net for hidden tabs).

### Phase A — Second Brain → **Memory** (the visible win)
- Remove the `Chat | Second Brain` switch. Chat is the home. **Memory** becomes its own destination in the sidebar.
- Memory page = three clear zones in the `PageShell`: **Field** (the Core, signature, lazy-loaded behind a still
  image so first paint is instant; reduced motion = still frame), **Stats** (memories, +today, last write — one
  number each), **Browse** (search + list of memories, edit/forget with undo). The status wall (APIs, gauges,
  processes, sub-agent dock) **moves out** to the new **Status** destination — it is operations, not memory.
- Chat rail keeps one slim line "Memory · 1,204 · +12 today" that opens the page; drop the duplicate card.
- Acceptance: opens in < 1 s with content; no horizontal scroll at 900 px; keyboard-reachable; one accent.

### Phase B — fold World, Office, 3D/Game, Draw into chat windows
- Build `ChatWindow` host (right pane) + `open_window` tool (see DESIGN.md §5). Wire the four engines as window
  kinds; their lobby/chat/sidebar UI is *deleted*, not ported — the main chat replaces it. Keep their backends and
  data (`world/`, `office/`, `game_studio.py`, `sketch_studio.py`, `routes_world/office/game/sketch`).
- Order: **Draw** (smallest, `SketchPanel` 290 lines) → **Game/3D** (433 lines + Play3D) → **Office** → **World**
  (heaviest; keep its three.js planet lazy and paused when hidden).
- Keep the old tab ids as **redirects** to "open this window in a new chat" for one release so saved links and
  the owner's muscle memory still work; then remove from `CORE_TABS`.
- "Pin as tab" and "make me a tab" = Phase D.
- Acceptance: "open the office" / "draw a cat" / "make a 3D room" / "show the world" work from the home composer;
  one heavy window at a time on this 16 GB PC; Edit/Undo/Retry on each; a saved window reopens from its message.

### Phase C — consolidate the old tabs (one per session, smallest first)
1. **Models & Connections** ← Models + Keys & Models + Connectors + Add capability.
2. **Status** ← Dashboard + Power + the Core's gauges/APIs/processes.
3. **Minds** ← Sub-agents, Agents, Collab, Free Will, Big Kahuna, Apply, Improve, Data Absorption (one list page;
   each opens as a detail view; no 8 sidebars). Big Kahuna keeps its own page (it is the main brain).
4. Delete Strands (already ordered). Rename per the owner's space/math naming rule *after* the owner picks names;
   plain subtitle under each.
- Every consolidated page uses `PageShell` + `EmptyState`; fixes "no outline" by construction.

### Phase D — design-your-own tab
- **Design → New tab/window**: prompt + Tab/Window toggle + model pill + 3 suggestions → wireframe preview → refine in
  chat → Pin. Backed by `dynamic_tabs.py`, `tab_editor.py`, `design_sense.py`, `design_research/entries.json`.
- Validator before pinning: tokens only, contrast, focus order, empty state present.

### Phase E — shell polish
- Sidebar: ≤ 7 pinned + More, reorder/hide, collapses < 1100 px, two levels max. Composer footer chips (mode,
  model, permission). Light theme from the same tokens. Settings regrouped into ≤ 6 groups.

## Suggested order and size

A (Memory) → 0 → B-Draw → C1 → B-Game → C2 → B-Office → C3 → B-World → D → E. Phase 0 can run first if you prefer
the kit before the first visible change; I would do **0 and A together** since A needs the kit.

## Decisions I need from you (nothing is blocked; defaults in bold)
1. Names for the new destinations (Memory, Status, Minds, Models & Connections) — **use these plain names now,
   rename to the space/math style later with plain subtitles**.
2. Accent colour — **keep the current one** until you pick.
3. Should the Core stay on the Memory page, or become the home-screen backdrop? — **Memory page only** (quiet home,
   like Claude/Codex/ChatGPT in your screenshots).
4. Keep old tab ids as redirects for one release? — **yes**.

---

## Per-tab audit (2026-10-10, static scan of `frontend/nyx-pulse/src/panels/`)

Method: counted, per panel file, whether it has a header, an empty-state string, a loading string, `aria-label`s, and
hard-coded hex colours. This is a **heuristic from source, not a visual check** — confirm each row on screen before
fixing. "—" = none found.

| Tab | Lines | Header | Empty state | Loading | aria-labels | Verdict | Fix (phase) |
|---|---|---|---|---|---|---|---|
| **Nyx (Second Brain)** | 494 + Core 639 + Field 625 | yes | **—** | **—** | 8 | Unclear: one tab, two screens; no empty/loading state for the heavy WebGL | **A** — split into Chat home + Memory page |
| World | 93 (+ many files) | yes | — | — | **—** | Own lobby/chat; no labels | B (window) |
| Office Space | 144 (+ many files) | yes | — | — | **—** | Same | B (window) |
| Game Studio / 3D | 433 | yes | yes | — | 8 | Own chat; heavy | B (window) |
| Create (Draw) | 290 | yes | — | — | 5 | 5 hard-coded hex; no empty state | B (window), first |
| Dashboard | 108 | — | — | yes | — | No outline, no labels | C2 Status |
| Power | 184 | — | — | yes | — | Same | C2 Status |
| Sessions & Memory | 180 | — | yes | yes | — | No header/labels | A (Memory) |
| Models | 202 | — | — | yes | — | No outline | C1 |
| Keys & Models | 467 | yes | yes | yes | **—** | 467 lines, zero labels | C1 |
| Connectors | 214 | yes | yes | yes | 5 | OK shape; merge | C1 |
| Add capability (Store) | 242 | — | — | yes | — | No outline | C1 |
| Agents | 373 | — | yes | yes | — | No header/labels | C3 Minds |
| Sub-agents | 334 | yes | yes | — | 7 | OK; merge | C3 |
| Collab | 225 | yes | yes | — | 6 | 2 hex; merge | C3 |
| Free Will | 349 | yes | yes | yes | 10 | Good shape | C3 |
| Big Kahuna | 300 | yes | yes | — | 6 | Keep page | C3 |
| Improve | 363 | yes | yes | yes | 6 | 1 hex | C3 |
| Data Absorption | 149 | yes | — | — | 3 | No empty state | C3 |
| Apply | 483 | yes | yes | yes | 6 | Good shape | C3 |
| Strands (classic) | 901 | — | yes | yes | 1 | Oldest, largest, 5 hex | **Delete** (already ordered) |
| Admin | 284 | — | yes | yes | **—** | No header/labels | E |
| Settings | 396 | — | yes | yes | **—** | No header/labels; regroup | E |
| Learn | 422 | yes | yes | yes | 5 | **11 hard-coded hex** | tokens pass |
| Build (+Checks) | 32 / 134 | — | yes | yes | 1 / 0 | `build.css` has 90 hex | tokens pass |
| Code, Notes, Trading, Research, Screen | 342–623 | yes | yes | mixed | 8–22 | Healthiest; CSS has 48–64 hex each | tokens pass only |
| Equalize | 231 | yes | **—** | **—** | 5 | **ON HOLD** — no changes | — |
| Design Research | 108 | yes | — | — | 4 | Add empty state + prompt chips | D |
| Nyx's Computer | 240 | yes | — | yes | 9 | Add empty state | C3/E |

**Totals:** 11 panels have no header/outline and no labels (Admin, Agents, Dashboard, Models, Power, Settings,
Store, Work, Checks, Office, World); 12 have no empty state; hard-coded hex lives mostly in `build.css` (90),
`notes.css` (64), `trading.css` (54), `code.css` (48), `core.css` (45) → a token pass, not a redesign.

### Second Brain — concrete first fix (Phase A, ordered)
1. Add `PageShell`/`EmptyState`/`Skeleton` (Phase 0) — Memory page paints header + stat skeletons immediately.
2. New `MemoryPanel`: Stats (`/api/core/overview` → memories, +today) · Browse (search/list, forget with undo) ·
   Field (existing `BrainField`, lazy, still image first).
3. Move gauges / APIs / processes / sub-agent dock out of `CoreView` into a `StatusPanel` (Phase C2) — same data,
   same endpoint, no backend change.
4. Remove the `Chat | Second Brain` segmented switch in `NyxPanel.tsx:280`; the chat rail's Second Brain card
   (`ChatRail.tsx:194`) becomes one slim line that opens Memory.
5. Verify in the running app at 900 px and 1600 px; screenshot into `design/images/`.

### Equalize
Paused: no edits to `panels/equalize/`, `equalize_voice.py` or `routes_equalize.py` until you lift the hold. Recorded
in `AI_HANDOFF/START_HERE.md` (item 0a).

---

## LIVE audit (2026-10-10, running app `look-only` on port 8031, real data, read-only)

Measured in the browser at 1280 × 800 for all 32 tabs (DOM metrics), plus screenshots at 452 px. This **replaces
the guesses in the static table above** where they disagree. Screenshots: `design/images/ichos-*.jpg`.

### What the live run corrected
- Dashboard, Sessions & Memory, Models, Agents, Power, Add capability **do** have a title and a subtitle — they use
  styled `div`s instead of `h1/h2`. So the "no outline" problem there is **semantic** (screen readers find no headings),
  not visual. Fix = real headings in `PageShell`, not a redesign.
- No tab scrolls sideways at 1280 px. Text contrast passed everywhere measured except one badge on Build (3.4:1, small
  white "10" on a tinted chip) — Connectors' 99 flags are coloured brand letters on brand tiles (my parser could not
  read `color(srgb …)`; check by eye).

### Real problems found
| Where | Finding | Severity |
|---|---|---|
| **Nyx → Second Brain** | Two nested segmented switches (`Chat / Second Brain`, then `Memory field / Core`); the floating chat sheet sits **on top of** the page title, cutting "32,852 memories in the field" off at 452 px; brand repeated (header logo + "NYX ICHOS · MEMORY FIELD" label); the chat sheet carries ~20 controls (model menu, context bar, Compact, Team (55), Details, Copy/Branch/Listen, 5 mode chips). This is the "weird" feeling: no single job, everything overlapping. | High |
| Chat sheet model menu | Lists providers marked **"(no key)"** (claude, deepseek, groq, kimi, perplexity, qwen) as choices that cannot work. Show only usable ones; "Add a key…" as one item. | Medium |
| **Sessions & Memory** | Says only 2 working memories and "Chat 1 / Chat 2", while the Second Brain says 32,852 memories — two places, two different "memory" stories. Shows a developer note on screen ("STILL TO BUILD … read-only in the UI"). | High |
| Header (all tabs) | `Log Out` is a large bordered button in the top bar; Comfortable/Compact density switch and "+ Add capability" also take prime space; at 452 px the header wraps to two rows. Move Log Out into the account menu, density into Settings. | Medium |
| Tab strip | 32 tabs in one horizontal strip + "All tabs ⌄"; 21 carry a "●" dot (unread/active?) so the dot means nothing. | High |
| Narrow window (452 px) | Chat list covers the conversation instead of collapsing; Second Brain field is cut by the chat sheet. | High |
| Unlabelled / tiny controls | Sub-agents: **54 controls with no accessible name and 54 under 24 px**; Collab 71 tiny; Data Absorption 34 tiny / 5 unnamed; Improve 28 tiny / 6 unnamed; Trading 13 unnamed; Keys 8; Settings 7; World 4; Design Research 5. (Apple desktop minimum 20 × 20 pt, default 28; WCAG 4.1.2 name.) | High |
| Type drift | Trading uses **14 font sizes**, Settings 11, Research 11, Learn 11; min sizes 10.4 px (Trading, Settings) and 10.5 (Build, Improve) — below the 11 px floor. Font stack starts with `-apple-system`/`SF Mono` on a Windows app. | Medium |
| Colour drift | Improve uses 11 text colours, Keys 10, most tabs 7–9; target is ≤ 4 (text, dim, accent, state). | Medium |
| Radius drift | Trading, Kahuna 9 distinct radii; target 4 (8, 14, 999, 4 for chips). | Low |
| Office Space | Only 4 controls and a title on open — the lobby is nearly empty with no example or next step. | Medium |
| Strands (classic) | Still shipped, 105 controls, 2 canvases. | Delete (ordered) |

### Per-tab numbers (controls · unnamed · <24 px · font sizes · text colours · radii)
Nyx 152·0·1·10·9·9 · Build 50·4·0·10·8·6 · Game Studio 10·0·0·6·4·3 · Research 16·0·0·11·6·8 · Learn 6·0·0·11·7·8 ·
Notes 24·0·0·7·8·6 · Code 7·0·0·7·6·4 · Sub-agents 293·54·54·9·9·8 · Collab 87·1·71·8·7·6 · Trading 46·13·2·14·9·9 ·
Improve 105·6·28·9·11·7 · Data Absorption 46·5·34·6·4·8 · Screen Share 9·0·0·7·5·7 · Apply 15·1·1·9·7·8 · Free Will
11·0·0·7·7·5 · Big Kahuna 100·0·2·8·8·9 · Office 4·0·1·6·3·3 · World 18·4·4·8·7·5 · Create 26·2·12·3·7·5 · Equalize
7·1·1·5·5·4 · Design Research 23·5·5·5·6·5 · Nyx's Computer 7·0·0·5·5·7 · Dashboard 1·0·0·5·5·3 · Sessions & Memory
0·0·0·4·5·1 · Models 26·0·0·6·9·3 · Keys & Models 185·8·8·7·10·5 · Agents 112·0·0·4·7·3 · Connectors 125·5·0·8·—·7 ·
Add capability 220·0·0·4·8·3 · Power 6·0·0·5·5·2 · Strands 105·0·0·4·8·4 · Settings 139·7·6·11·9·6.

### Priority after the live run
1. Second Brain → Memory, and merge Sessions & Memory into it (one memory story).
2. Accessible names + 28 px hit areas on Sub-agents, Collab, Data Absorption, Improve, Trading (a kit `IconButton`
   that requires a label fixes this by construction).
3. Header clean-up (Log Out to account menu) + sidebar instead of 32-tab strip.
4. Token pass: one type scale (11–32 px, 6 sizes), ≤ 4 text colours, 4 radii; Segoe UI Variable first in the stack.
