# Ichos Design — the main design file (for Claude coding and for the AI's own layout)

**v2, 2026-10-10.** Built from: the owner's six reference screenshots; live visits to Higgsfield, Stitch and the Google
Cloud Agent Platform console (read-only, signed in by the owner, no payment or activation touched); a live audit of
all 32 Ichos tabs; the full Apple HIG set (`.claude/skills/apple-design`); the `/design` skills (design-system,
critique, accessibility-review, ux-copy, design-handoff, research-synthesis); and a six-track deep-research sweep
(full sourced report: `reports/Ichos design research sweep.md`, notes in `research_notes/Ichos design research sweep/`).
`DESIGN_MASTERPLAN.md` (outer folder) keeps its research log and zone ramp; **where the two differ, this file wins.**

**Read this before touching any UI. Update it after shipping.** Companion docs: `docs/DESIGN_FIX_PLAN.md` (what is
broken and in what order to fix it, incl. the live audit) and `docs/WINDOWS_IN_CHAT_PLAN.md` (windows, docking, notch,
voice routines, sub-agent permissions). Equalize tab work is on hold while this lands.

---

## 0. What the references say

### The owner's screenshots (`design/images/ref-*.webp`)
| Reference | Take | Don't take |
|---|---|---|
| **Claude desktop, Code tab** (`ref-claude-code-tab`) | Narrow sidebar: Search, New, Artifacts, Customize, More → Pinned → project sessions. Composer footer holds attach, mode ("Auto"), model ("Opus 5.5"), effort. Page itself has no chrome. | — |
| **Claude desktop, chat home** (`ref-claude-chat-home`) | One greeting + one composer centred; **under** the composer a "Project or folder ▾" picker and model/effort/mode — context is chosen at the box, not in a page header. Sidebar: New, Projects, Artifacts, Scheduled, Design, Customize, More; history by day. | Terracotta accent, serif greeting (theirs). |
| **Codex** (`ref-codex-home`) | Thin icon rail + project sidebar; empty state = one icon + "What should we work on in Ai Dev Folder?"; the **project chip is attached on top of the composer**; usage limit is a calm card stacked on the composer; permission ("Full access") is a chip in the composer. | Orange used for a normal state. |
| **ChatGPT** (`ref-chatgpt-home`) | Pure-black home, one pill composer: `+`, "Ask anything", Think, round send. Sidebar verbs (Images, Library, Scheduled, Plugins, Projects, Codex, More) then Recents. | Upsell buttons in nav. |
| **Perplexity** (`ref-perplexity-home`) | Small eyebrow ("Search") over the question; **mode switch inside the composer** (Search ▾ / Computer) + Model ▾ + mic + voice. Projects and Sessions are collapsible groups. | Promo toast over content. |
| **Stitch** (`ref-stitch-landing`, live) | One big prompt card over an ambient gradient; **App / Web** toggle and **Balanced** model pill inside the card; 3 suggestion chips under it; Google Sans, light display type; bento feature cards ("Easy edits", "Export code"). | Full-bleed gradient behind work screens. |

### Live sites
| Site | Measured / seen | Take |
|---|---|---|
| **Higgsfield** (`ref-higgsfield-live`) | bg `#0F1113`, text `#F7F7F8`, surfaces `#14151A`/`#1C1E20`, dim `#898A8B`, accent acid-lime `#D1FE17` (+ magenta "TOP" tag); Inter body, **Space Grotesk 56/700 uppercase** display; radii 8/12/16/24. Video-first cards; every result has *Recreate*. | Output-first cards and "do it again". **Not** the palette: near-black + one acid accent is a known templated look (apple-design craft lens). |
| **Google Cloud Agent Platform** (`ref-gcp-*`) | Overview = welcome + Ask box + 3 cards (Guides · Build · Production) + model list + nav grouped **Build / Scale / Govern / Optimize**. Agent Studio = prompt-first card with **Models / Agents** segmented toggle inside, a **6-step tip tour** (1/6 Next) on first use; Studio nav: New, Agents, App builder, Gallery, Settings. Gallery = media-type filter chips + sections with "View all" + one-line evocative example cards. Tokens: Google Sans / Google Sans Flex / Roboto; 14/400 body, 22/500 section, 36/400 hero; text `#E8EAED`, link `#8AB4F8`; radii 4/8/12/20/24/pill. | Group "what my AIs are doing" by verb (Build / Run / Govern / Improve) — use for the **Minds** page. Context tips instead of one onboarding flow. Gallery of example prompts per window kind. |

**The common spine:** *one sidebar, one composer, everything else summoned.* Features are things the chat opens
beside itself, not tabs you travel to. The sweep confirms this is now the standard layout (Claude Code Desktop,
Cursor, VS Code, Copilot on Windows all ship dockable / pop-out panes) — so layout won't set Ichos apart; native
visuals, careful agent permissions and voice routines that don't misfire will.

## 1. Principles

1. **Chat first.** Every capability starts as a sentence. A destination exists only for a permanent home (Memory,
   Status, Minds, Models & Connections, Settings). 3D/Game, World, Office, Draw are **windows** (§5).
2. **One signature, everything else quiet.** Signature = the Core (memory field) — on the Memory page only. AI
   styling (§2 `--ichos-ai-*`) *identifies* AI activity (agent-driven window, approval card, listening notch); it is
   never decoration (Carbon for AI, Atlassian Rovo).
3. **Outline before content.** Every screen paints its skeleton first: real heading, one-line purpose, body, empty
   state with one next action. (Live audit: several tabs draw titles as `div`s — screen readers find no headings.)
4. **Progressive disclosure.** Glance = one number; click = detail; settings last.
5. **Keep people in control of AI** (Apple `generative-ai.md`, HAX, PAIR): label AI output; Edit / Undo / Retry next to
   every result; specific progress text ("Reading 12 files"); ask before irreversible actions; non-AI fallback.
6. **Colour means state.** One accent, used for selection and primary action only — **not** for focus (§2).
7. **Native on Windows, keyboard complete.** WinUI tokens, Segoe UI Variable, Mica-ready surfaces, `Ctrl+K` reaches
   everything, Windows focus ring.
8. **Never block, never crash visibly.** Skeleton immediately; errors say what happened and the next step.
9. **Modular by default (owner, 2026-10-10).** Every panel docks top/bottom/left/right, floats, pops out, or (the
   assistant) shrinks to a notch — by menu, drag, keyboard or voice. Layouts are versioned data with presets and reset.
10. **Stability is a feature.** Never move the owner's panels for them, never resize on switch, never ship a forced
    re-layout; every layout change is undoable (Cursor 2.0 and Copilot's "sixth redesign in two years" backlash).

## 2. Tokens — Windows 11 (WinUI) dark resources, Ichos names

**Replaces v1's opaque grey ladder** (`#141418/#1c1c21/#232329/#2c2c33`, kept one release as aliases): translucent
white fills over a `#202020` base work on a solid window, on Mica, and in floating/popped-out panels with one token
set. Naming: `--ichos-{category}-{role}[-{variant}][-{state}]` over a primitive layer only semantic tokens may read.
Light theme = map each name to WinUI/Fluent **Light** values — never invert (inverted translucent fills change
perceived contrast). Contrast figures computed on `#202020`.

| Token | Dark | Origin | Contrast |
|---|---|---|---|
| `--ichos-bg-app` | `#202020` | SolidBackgroundFillColorBase | — |
| `--ichos-bg-app-secondary` (sidebar) | `#1C1C1C` | …Secondary | — |
| `--ichos-bg-layer` / `-solid` | `rgba(58,58,58,.30)` / `#282828` | LayerFillColorDefault / …Tertiary | — |
| `--ichos-bg-flyout` | `#2C2C2C` | …Quaternary | — |
| `--ichos-bg-card` | `rgba(255,255,255,.051)` | CardBackgroundFillColorDefault | — |
| `--ichos-text-primary` | `#FFFFFF` | TextFillColorPrimary | 16.3:1 |
| `--ichos-text-secondary` | `rgba(255,255,255,.773)` | TextFillColorSecondary | 10.2:1 |
| `--ichos-text-tertiary` (meta only) | `rgba(255,255,255,.53)` | TextFillColorTertiary | 5.5:1 |
| `--ichos-text-disabled` | `rgba(255,255,255,.365)` | TextFillColorDisabled | 3.3:1 (exempt) |
| `--ichos-fill-control` / `-hover` / `-pressed` | white @ .059 / .082 / .031 | ControlFillColor* | — |
| `--ichos-stroke-control` / `-divider` / `-strong` | white @ .07 / .082 / .545 | ControlStroke / Divider / StrongStroke | — |
| `--ichos-text-accent` | `#479EF5` (placeholder) | Fluent brand[100] | 5.8:1 |
| `--ichos-fill-accent` / `-hover` / `-pressed` | `#115EA3` / `#0F6CBD` / `#0C3B5E` | brand[70]/[80]/[40] | white 6.7:1 |
| `--ichos-status-critical` / `-success` / `-caution` | `#FF99A4` / `#6CCB5F` / `#FCE100` | SystemFillColor* | — |
| `--ichos-bg-scrim` | `rgba(0,0,0,.30)` | SmokeFillColorDefault | — |
| `--ichos-ai-aura` / `-border` / `-skeleton` | accent @ 10 % / light-accent 36 % → accent / accent @ 30 % | Carbon g100 AI tokens | — |
| zone ramp (masterplan) | unchanged | usage meters only | — |

Accent rule: light step for accent **text/strokes**, mid step for **filled** buttons with white text (Fluent
brand[100]/[70], M3 tone 80/30). The blue is a placeholder until the owner picks; keep the step structure and
re-check contrast. Old `--text-dim #a0a0ab` measured **6.0:1** on surface-2 — use `text-secondary` instead.

**Type — Segoe UI Variable, Windows ramp as published:** Caption 12/16 · Body 14/20 · Body Strong 14/20 600 · Body
Large 18/24 · Subtitle 20/28 · Title 28/36 · Title Large 40/52 · Display 68/92. Weights 400 and 600 only. **Floor
12 px** (live audit found 10.4 px in Trading/Settings). Mono: Cascadia Mono. Stack starts `"Segoe UI Variable Text",
"Segoe UI", system-ui` (today it starts `-apple-system`). Home greeting = Title 28/36 600; an optional 16/24 reading
size as a setting.

**Shape:** 4 px in-page controls · 8 px windows, flyouts, dialogs · 12 px composer and chat bubbles · circular pills /
avatars · 0 px snapped/maximised or meeting edges. (Live audit: Trading and Kahuna use 9 distinct radii.)

**Space:** 2 / 4 / 6 / 8 / 10 / 12 / 16 / 20 / 24 / 32. Gaps: 8 between buttons, 12 control↔label, 16 edge↔text.

**Targets:** 32 × 32 dense chrome, **40 × 40** for Send, Approve/Deny and anything voice/touch-adjacent. Every icon-only
control has an accessible name + tooltip (live audit: 54 unnamed on Sub-agents).

**Elevation:** Fluent two-layer shadows (ambient .24 + key .28 in dark): shadow2 controls, 8 cards, 28 flyouts, 64
dialogs. Floating and popped-out panels add a 1 px light ring (`#BDBDBD1F`) so dark-on-dark separates.

**Motion:** micro 50–150 ms, standard 200–300 ms, overlays 300–500 ms; enter decelerate `cubic-bezier(0,0,0,1)`, exit
accelerate `cubic-bezier(1,0,1,1)` (productive). Springs only for AI-presence moments (notch expand, agent window
arriving): M3 spatial damping 0.9 / stiffness 700. Reduced motion → no springs, fades only.

**Focus:** Windows double ring — 2 px white outer over 1 px 70 % black inner, 1 px margin, `:focus-visible` only.

**Materials:** Mica once, on the long-lived window backdrop only; falls back to solid `#202020` when inactive /
transparency off / battery saver. Blur only on the floating layer (palette, popovers, notch) — never on content.

## 3. App shell

```
┌────────────┬──────────────────────────────────────────┬──────────────┐
│ ＋ New  ⧉  │ chat title ▾                  Ctrl+K  ⚙  │ WINDOW       │
│ Search     │                                          │ (any slot:   │
│ ──────     │            conversation                  │  right by    │
│ Chat       │                                          │  default)    │
│ Memory     │  ┌ project ▾ ─────────────────────────┐  │              │
│ Build      │  │ ＋  Ask Ichos…    [mode][model ◔] 🎙 ▶│  │              │
│ Minds      │  └────────────────────────────────────┘  │              │
│ More ▸     │                                          │              │
│ Pinned · Today …                                       │              │
└────────────┴──────────────────────────────────────────┴──────────────┘
          notch (optional, top-centre): ◖ ● Listening… ◗
```

- **Sidebar:** New (+ temporary chat ⧉ beside it), Search, **5 destinations**, More ▸, Pinned, history by day. ≤ 2
  levels, hideable, auto-collapses when narrow, nothing critical at the bottom. One meaning for the unread dot ("a
  background answer finished / an agent waits on you") — today 21 of 32 tabs show a dot that means nothing.
- **Composer (≤ 5 visible controls):** `+` (attach, skills, connectors, windows) · mode chip · model by **capability
  tier** (file name second; hide "(no key)" providers; one "Add a key…" item) with a **context ring** that opens a
  breakdown and *Compact* · mic · send. Project/folder chip sits on top of the composer (Codex/Claude). The box grows
  to reveal options the prompt implies (M365 Copilot). `@` reaches sub-agents, open windows and saved assets.
- **Permission chip:** modes named by consequence — *Ask first* · *Auto-approve safe* · *Full access* (Full only after
  enabling it in Settings; never casual). Calm colour; caution colour only for Full.
- **Steering:** queue a correction while a run continues; Stop/Esc for real interrupts; transcript verbosity Normal /
  Thinking / Verbose; side question (`Ctrl+;`) that stays out of the thread; long runs end in a notification.
- **Header:** chat title, Ctrl+K, settings. **Log Out and density move into the account menu / Settings** (live audit:
  Log Out is a large bordered button in the top bar).
- **Settings:** one window, ≤ 6 groups (General · Models & Keys · Voice · Safety · Appearance · Advanced).

## 4. Destinations — keep, fold, rename

Owner's naming rule (2026-10-09): space/math names **with a plain subtitle**; plain names used until the owner picks.

| Today (32 tabs) | Becomes | Why |
|---|---|---|
| Nyx (Chat + Second Brain) | **Chat** = home; Second Brain + Sessions & Memory → **Memory** | Live audit: nested switches, chat sheet covers the title, two different memory stories |
| Game Studio/3D, World, Office Space, Create | **Windows** (§5); dedicated tab only on request (§6) | Owner |
| Build, Research, Learn, Notes, Code | Keep (Build, Code pinned; others in More) | Long-lived workspaces |
| Sub-agents, Agents, Collab, Free Will, Big Kahuna, Apply, Improve, Data Absorption, Nyx's Computer | **Minds**, grouped Build / Run / Govern / Improve (GCP pattern); Big Kahuna keeps its own page | One need: "what are my AIs doing" |
| Dashboard, Power | **Status** (+ the Core's gauges/APIs/processes) | Operations, not memory |
| Models, Keys & Models, Connectors, Add capability | **Models & Connections** | Four places for one job |
| Strands (classic) | **Delete** | Ordered |
| Equalize | On hold | Owner |
| Design Research | Inside **Design** ("Studied sites") | §6 |
| Settings, Admin | Settings window; Admin only for owner/admin | — |

Pinned target: **Chat, Memory, Build, Code, Minds** + More (Status, Research, Learn, Notes, Models & Connections,
Design) + Ctrl+K.

## 5. Windows — how 3D / Game / World / Office / Draw live in chat

Full spec: `WINDOWS_IN_CHAT_PLAN.md`. Design rules:
1. Chat calls `open_window{kind,…}`; engines stay the backend. A window **belongs to the chat that opened it** and is
   saved with it (Copilot saves side-pane tabs with the conversation).
2. **Inline vs window** (Cloudscape): small, self-contained output stays inline in the message; interactive or
   long-lived output opens as a window.
3. **One toolbar** for every window: title · kind chip · version switcher `‹ 2/3 ›` (history) · variants grid 1–4
   (parallel) · Edit · Retry · Undo · local cost chip (`≈ 40 s · 6 GB VRAM`) · ⋮ (Pop out, Pin as tab, Move to…, Export,
   Close). Toolbar collapses into ⋮ when narrow.
4. **Visible recipe:** every window keeps its prompt; *Run again* / *Remix* one click away (Higgsfield Recreate,
   Midjourney fixed action set with "More options").
5. **Draw window template** (Ideogram Studio): tools left · context panel + Layers right · version strip bottom (← →,
   `+` duplicates) · zoom bottom-right · Exit top-left · Export top-right · unavailable options greyed, not hidden.
6. **Agent-driven window:** AI-presence outline (`--ichos-ai-*`), agent name/avatar chip, step checklist, visible
   **Take control · Pause · Stop**; logging pauses while the owner is in control.
7. Heavy windows lazy-load with specific status text, pause when hidden; one heavy window at a time on this PC.
8. Agent edits to a pinned tab are **staged above the prompt and wait for Apply** (Figma Make). Edited AI content
   loses its AI styling; a *revert to AI version* control appears (Carbon).

## 6. Dedicated tabs by design

Entry: chat ("make me a tab for X"), a window's **Pin as tab**, or **Design → New tab**. Stitch-style card: prompt +
Tab/Window toggle + model pill + 3 suggestions (per-kind gallery, GCP Studio) → preview rendered by the real
`DynamicTab` → refine in chat → Pin. Specs only (`dynamic_tabs.py`), never generated code. A node-canvas view is an
*advanced* option later (Freepik Spaces is "overwhelming for beginners"). Validator before pin: known blocks, tokens,
contrast, title + empty state, focus order.

## 7. Behavioural tokens (agents, attention, undo, voice)

Treated with the same rigour as colours: named, versioned, tested.

| Area | Rule |
|---|---|
| **Grant scopes** | Allow once · **This task** · Always for this agent · Deny. Separate grants for *open* and *interact*. Managed on one Settings → Safety screen. |
| **Always-ask list** (no grant covers it) | Delete a world/office/project, close a running office, purchases, account creation, sending messages, system settings. Published in Settings. |
| **Approval card** | Says what will happen and what it touches; buttons named for the action; **never pre-ticked, never changes any setting beyond the grant it names** (Cursor auto-review consent failure). |
| **Attention** | States: *waiting on you* (loudest: badge + toast + notch alert) · error · complete. ≤ 2 toasts at once, hover pauses, click jumps to the run; everything else goes to an inbox (All / Unread / Errors). |
| **Inter-agent messages** | Attributed cards ("from Researcher"), delivered after the receiver's current step; receiver keeps its own permissions. |
| **Checkpoints** | Files + conversation + window state with a short summary; changes after a rollback **branch**, nothing is destroyed. Every window action links to the run log. |
| **AI label & explain popover** | Persistent AI label opens: model, ran on this PC, which memories were used, what left the device (nothing), *Forget these*. Confidence only when it changes a decision, as categories / alternatives. Accuracy caveat = quiet persistent line, never a modal. |
| **Memory retention** | Plain choice: 30 days / 1 year / forever; trivial commands not logged. |
| **Voice routines** | Text is the source of truth; recording 3 takes = "I heard: …" check, variants become aliases; wake word required by default (bare phrase opt-in per phrase); phrase lint (≥ 6 phonemes, common-word collisions, closeness to other phrases); ≤ 8 steps from a fixed list; re-approval whenever steps change (hash); command matching muted while Ichos speaks. |
| **Notch** | Own pill-sized window resized per state (no click-through tricks); states: minimal · compact · expanded · armed · listening · matching · confirming · running n/m · speaking · muted · interrupted · alert. Expands on wake phrase **without** taking focus; hides in full-screen apps (poll `SHQueryUserNotificationState`); shrinks during window drags (Snap bar). Hotkey **outside the Alt+Space family** (Claude Desktop owns Ctrl+Alt+Space on this PC); detect failed registration and offer rebind. |
| **Layout** | Versioned presets with migrator; per-panel *Reset location* + global *Restore defaults*; failed load → default layout + toast; `--reset-layout` flag; view modes incl. auto-hide; "Move focused panel…" keyboard quick-pick. |

## 8. Components (kit `src/ui/`; document each with the design-system template: variants, states, a11y, do/don't)

| Component | Variants | States (all required) | A11y |
|---|---|---|---|
| `PageShell` | page, window, sheet | loading skeleton, empty, error, ready | `h1` + landmark; one-line purpose |
| `EmptyState` | default, first-run (tips) | — | heading + one primary button |
| `IconButton` | ghost, subtle, filled | default, hover, pressed, disabled, focus | **label prop required** (build fails without); 32/40 px |
| `Button` | primary (one per view), secondary, subtle, danger | + loading | verb + noun label |
| `Composer` | home, thread, window | idle, typing, sending, queued, disabled-with-reason | Enter send / Shift+Enter newline (option to swap) |
| `ModelPicker` | tier list | usable, needs key (single "Add a key…"), offline | |
| `ApprovalCard` | inline, notch, toast | pending, approved, denied, expired | focus moves to it; Esc = deny |
| `WindowToolbar` | full, collapsed (⋮) | — | every action also in ⋮ and Ctrl+K |
| `VersionSwitcher` / `VariantGrid` | — | generating (accent skeleton), ready, failed | ←/→ keys |
| `AgentRunCard` | compact (chat), full (window) | running n/m, waiting on you, done, error, paused, taken over | live region for state changes |
| `Notch` | see §7 | see §7 | announces state; hotkey shown in tooltip |
| `StatusChip`, `Meter` | zone ramp | — | text label, never colour alone |
| `Toast` | info, success, error (persists) | — | ≤ 2; Undo when reversible |

## 9. Writing (ux-copy + Apple `writing.md` + LobeHub voice)

- Buttons = verb + noun ("Save layout", "Run routine", "Allow for this task"); never OK/Submit/Confirm.
- Confirm by naming what changed ("Layout saved"), no "successfully". In-progress = present participle + "…".
- Errors: what happened + why + how to fix, no apology. Empty states: what this is + why empty + how to start.
- One term per thing: Chat, Window, Memory, Mind (agent), Routine, Notch. Never alternate synonyms.
- ~80/20 information to warmth; warmth capped at one sentence.
- No developer notes on screen (live audit: "STILL TO BUILD …" on Sessions & Memory).

## 10. Accessibility (WCAG 2.1 AA + Apple, enforced)

1.4.3 text ≥ 4.5:1 (≥ 3:1 large) · 1.4.11 controls/graphics ≥ 3:1 · 2.1.1 everything by keyboard (incl. moving
panels) · 2.4.3 logical focus order · 2.4.7 visible focus (Windows ring) · 4.1.2 name/role/value on every control ·
3.3.1/3.3.2 errors described, inputs labelled · zoom 200 % without loss · reduced motion and reduced transparency
honoured · captions for both sides of voice · nothing conveyed by colour alone. Test with keyboard only and NVDA.

## 11. Review checklist (before calling any UI done)

1. Skeleton, real heading, empty state, one next action? 2. Tokens only, contrast computed? 3. Keyboard-only works,
Windows focus ring visible? 4. Reduced motion/transparency? 5. Every AI result: Retry / Edit / Undo + specific status
text + AI label? 6. Works at 452 px (pane) and 1280 px; nothing overlaps titles? 7. Anything removable? 8. Checked in
the running app with a screenshot into `design/images/`? 9. Layout survives reload and pop-out with same theme?

## 12. Research coverage (what was actually looked at)

| Source | How | Depth |
|---|---|---|
| 6 owner screenshots | opened as images, saved to `design/images/` | full |
| Higgsfield, Stitch | live in browser, tokens measured by script | full |
| Google Cloud Agent Platform (overview, Studio, Agents, Gallery) | live, owner signed in; **links only, no buttons; payment/activation never touched** | partial (no agent builder canvas opened) |
| Ichos itself (32 tabs) | live on `look-only` (8031), DOM metrics + screenshots | full; results in `DESIGN_FIX_PLAN.md` |
| Apple HIG | 22 pages read (always-load set + generative-ai, sidebars, settings, loading, windows, toolbars, materials, dark-mode, motion, feedback, writing, modality, keyboards, searching, onboarding, branding, design-principles) | full for what's on screen |
| `/design` skills | design-system, critique, accessibility-review, ux-copy, design-handoff, research-synthesis, user-research | full |
| GitHub AI UIs | Open WebUI, LobeChat (+ `DESIGN.md`/`DESIGN.dark.md` tokens), LibreChat, Jan, Cherry Studio, big-AGI, AnythingLLM, HuggingFace chat-ui, assistant-ui, Vercel AI Elements, dockview, boring.notch | READMEs/docs, not run |
| Deep-research sweep (6 tracks, ~460 sourced links) | AI chat products (Gemini, Copilot, Grok, Le Chat, Meta AI, Poe, Pi, DeepSeek, Qwen, Kimi, Notion AI, Dia, Siri…); agent/coding tools (Cursor, Windsurf, Copilot agent, Zed, Warp, Junie, Devin, Codex, Claude Code, Replit, Lovable, Bolt, v0, Manus, Operator/Atlas, Jules…); creative tools (Midjourney, Krea, Runway, Pika, Luma, Ideogram, Leonardo, Recraft, Firefly, Canva, Figma Make, Framer, Spline, Meshy, Suno, ElevenLabs, Freepik, Kling, Sora, Flow, tldraw…); design systems (Fluent 2/WinUI, Material 3, Carbon + Carbon for AI, Primer, Geist, Radix, shadcn, Atlassian/Rovo, SLDS, Polaris) and AI guidelines (HAX, PAIR, Shape of AI, NN/g); docking (VS Code, JetBrains, Blender, Obsidian, Snap Layouts, 7 React libraries) and notch/launchers (Dynamic Island, NotchNook, Alcove, PowerToys, Raycast, ChatGPT/Claude/Gemini desktop); voice (Alexa, Google Home, Siri Shortcuts, Bixby, Home Assistant, Voice Access, Talon, ChatGPT/Gemini/Copilot voice, Hume, openWakeWord, Picovoice, Vosk) | web pages and docs via search/fetch; some product details from third-party guides (flagged in the notes) |

**Known limits:** WinUI values read from the WPF UI port (only `TextFillColorPrimary` confirmed on Microsoft's page);
dockview keyboard/ARIA support unconfirmed; Vosk phrase-list API unverified; GitHub apps not run; several consumer-product
details come from third-party guides.
