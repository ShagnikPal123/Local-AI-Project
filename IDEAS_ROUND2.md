# IDEAS_ROUND2.md — Message Bubble, Agent Visibility, Speed, Admin/Beta

Builds on `IDEAS_OVERHAUL.md` (not repeated). Events from `OVERHAUL_CONTRACTS.md` §3.1/§3.2.
HIG: `generative-ai.md`, `machine-learning.md`. Each idea: what + **Acceptance** a reviewer can
verify by using the app.

## 1. The AI message, anatomy

1. **Header** — identity, model/provider chip, time. *Acceptance:* chip matches `done.provider`.
2. **Live status line** — current `status.text` in place, not appended (HIG: *"Finding
   substitutions…" beats "Processing…"*). *Acceptance:* text changes ≥1x per multi-tool turn.
3. **Thinking** — collapsed, streams `thought.delta` while open, shows elapsed. *Acceptance:*
   expanding mid-stream shows growing text, not frozen.
4. **Plan** — numbered steps when >1 agent/tool implied; collapses once answer starts.
   *Acceptance:* a two-agent turn shows a plan before its first tool step.
5. **Step timeline** — one row per `tool.start`→`tool.end`: icon, label, duration, `tool.image`
   thumbnails, red error rows keeping real `error.message` text. *Acceptance:* a failed tool call
   leaves a visible red row with real error text after the turn ends.
6. **Delegated-agent cards** — per `agent.update.agent_id`, live status dot, `understanding` line,
   expandable mini-timeline. *Acceptance:* a card flips working→done live, no refresh.
7. **Skills used / temp skills created** — chips; a temp chip carries inline Keep/Export.
   *Acceptance:* Keep moves it into the permanent library within one Skills-tab refresh.
8. **Approval requests** — inline, blocks only its own step. *Acceptance:* denying one approval
   leaves the rest of an already-finished parallel branch visible.
9. **The answer** — markdown, fenced code (copy + language tag), tables, inline images.
   *Acceptance:* long code blocks scroll internally, never stretch the bubble.
10. **Attachments** — shown above the answer they were sent with.
11. **Sources/citations** — chips linking to the actual URLs fetched this turn. *Acceptance:*
    clicking one opens the exact URL from that turn's tool args.
12. **Footer actions** — copy, retry, speak, branch, 👍/👎 with optional reason, "why this answer"
    (expands the plan/skills/sources already rendered, no duplicate). *Acceptance:* a 👎 reason
    persists and is retrievable later.
13. **Learned-from-you note** — dismissible chip linking to the Memory fact. *Acceptance:*
    dismissing the chip doesn't delete the underlying fact.

**States:** streaming (steps append live) · stopped (partial steps stay; footer offers Continue) ·
error (renders as its own step, not a vanishing toast) · cached — "From memory · 2h ago · Refresh,"
never indistinguishable from fresh (HIG: disclose where AI/cache is used) · background-resumed —
banner "Continued while you were away" at the resume point.

## 2. Making agents visible and obvious in chat

1. **Agent dock above composer** — live status dots for agents active this turn. *Acceptance:*
   appears within 1s of first `agent.update`, clears 5s after `done`.
2. **Inline "Nyx brought in Finance" card** — fires the moment a new agent is delegated to.
   *Acceptance:* name always matches `agent.update.name`.
3. **"@Agent" mention autocomplete** in composer, hints (not forces) delegation. *Acceptance:*
   `@Travel` in a message yields an `agent.update` for `agent_id:"travel"`.
4. **Empty-state hint** rotating "Try @Finance for a budget"-style tips.
5. **Creation celebration toast** on `agents.changed`/new agent, linking to the Agents tab.
   *Acceptance:* exactly one toast per creation, not one per follow-up tool call.
6. **Agent provenance** — "Created in chat 'Trip planning', 2026-09-12" in the Agents tab detail
   view for any non-default agent. *Acceptance:* a spun-up temp agent shows a real chat link.
7. **Agents tab goes live**, subscribed to the SSE bus instead of polling. *Acceptance:* a
   delegation while the tab is open updates its dot within 2s.
8. **"Working now" badge** on any backgrounded tab with an in-flight turn. *Acceptance:* switching
   away from a running chat keeps its dot visible on the tab strip.

## 3. Chats that keep running

- **Tab-strip indicator**: pulsing dot + step count while backgrounded.
- **Completion notification** (OS toast, or in-app if OS notifications are off), click focuses the
  chat. *Acceptance:* backgrounding mid-turn and returning later shows a notification that arrived
  before you clicked back.
- **Resume-on-return**: reopening replays the full event log, not just the final answer.
  *Acceptance:* a background-completed turn's timeline is indistinguishable from one watched live.
- **Multi-window**: two windows on the same chat both get the live SSE stream. *Acceptance:* a
  turn started in window A shows steps in window B within 2s, no refresh.

## 4. Learning you can see

Grounded in HIG *machine-learning.md* (explicit feedback: simple language; corrections: actionable;
cached results: say what they are).

- **Preferences panel** ("What Nyx has learned"): grouped facts, inline edit + delete.
  *Acceptance:* editing a fact changes the next relevant answer's behavior, not just its display.
- **Per-fact source/attribution** ("from 3 thumbs-up on finance replies") — factual, not emotional
  phrasing. *Acceptance:* source names a real signal count, never "Nyx just knows."
- **One-click reset**: per-fact "Forget this" + global "Reset all learning," with confirm.
  *Acceptance:* reset-all reverts the next reply's tone to default.
- **Cache honesty**: every cached answer carries the §1 "From memory" label. *Acceptance:* asking
  the same question twice shows a visibly different (labeled) response path the second time.
- **Storage disclosure**: Settings lists what's local (drafts, theme, tabs) vs. server-side
  (memory facts). *Acceptance:* clearing the local item leaves server-side facts untouched.

## 5. Coming back later

Restore order (fast → slow, so nothing looks broken mid-restore): 1) theme, 2) tab list + active
tab, 3) active chat's messages (cache first, revalidate after), 4) any running turn on that chat —
reattach SSE, replay missed events, 5) composer draft(s), 6) scroll position (last-read, not
always bottom), 7) other tabs' running-turn badges, loaded last.
*Acceptance:* closing with 3 tabs open (one mid-turn, one with an unsent draft) and reopening
reproduces all 3 tabs, the same active tab, the draft text, and the mid-turn badge, in <2s warm.

## 6. Speed: 8 highest-impact ways, ranked

1. **Chat UI onto `/api/chat/stream`** instead of blocking `/api/chat` — backend already emits
   everything. *Acceptance:* time-to-first-visible-content drops from "whole answer at once" to
   <1s.
2. **Fast-path renders no empty timeline shell** for simple turns. *Acceptance:* "hi" never flashes
   a plan/timeline skeleton.
3. **Cache chat list + last-open messages locally**, revalidate in background. *Acceptance:*
   reopening paints the last chat before the network call resolves.
4. **Replace remaining polling with the SSE bus** (Agents tab, etc.). *Acceptance:* no repeating
   `/api/agents` requests once event-driven.
5. **Code-split** the 3D panel, admin console, skill-export views out of the main bundle.
   *Acceptance:* measurable bundle-size drop; chat view first paint doesn't wait on 3D libs.
6. **Compress responses + cache headers** on rarely-changing JSON (agent roster, skills library).
   *Acceptance:* those endpoints serve gzip/br with `Cache-Control` set.
7. **Virtualize long chat histories.** *Acceptance:* a 500-message chat scrolls smoothly on first
   load.
8. **Optimistic send**: user bubble renders before the network round trip confirms it.
   *Acceptance:* composer clears and message appears before `turn.start` arrives.

## 7. Admin access server & beta program

**Console sections:** Dashboard (active users, outstanding keys, recent redemptions) · Access Keys
(mint/list/filter/revoke, wraps `access_keys.py`) · Beta Applicants (approve→mint, deny) · Feature
Flags (`features.developer_panel`/`.labs`/`.feedback`, per-user or global) · Users & Roles ·
Change Review (surfaces `change_review.py` here too) · Audit Log (every mint/revoke/role-change).

**Tester journey:** apply via `site/beta/` form → owner approves in Beta Applicants → `POST
/api/access/mint` returns the raw key + a `nyx://redeem?key=…` link → tester pastes the key or
clicks the link → `GET /api/access/status` flips immediately ("Beta access, expires in N days") →
gated features unlock with no restart → owner can revoke; the tester's next status check (not next
launch) reflects it.
*Acceptance:* a full apply→approve→redeem→unlock cycle needs no manual JSON editing or app restart.

## 8. Toward a masterful app — 15 features, ranked

1. Streamed chat UI on `/api/chat/stream` (§6.1).
2. Live Agents/Skills/Connectors panels off the SSE bus, not polling (§2.7).
3. Redesigned message bubble, all 13 parts of §1, shipped end to end.
4. Machine tools wired to real approval prompts for destructive categories — a "ask"-mode
   `delete_path` shows an approval card and goes to Recycle Bin, not permanent delete.
5. Visible AI cursor overlay for computer control — labeled cursor glides + click ripple; triple-Esc
   aborts mid-sequence.
6. Real email send/read with verify-before-claim (`IDEAS_OVERHAUL.md` Idea 7).
7. Accurate system specs panel — real CPU name, not "AMD64 Family 26 Model 36."
8. Neural multi-voice TTS per agent (`IDEAS_OVERHAUL.md` Idea 11).
9. Skill export UI (five formats) wired to the existing backend (`IDEAS_OVERHAUL.md` Idea 10).
10. Preferences/learning panel (§4) — editing a fact changes future behavior.
11. Session restore in the exact order of §5.
12. Chrome-style reorderable tabs with running-turn badges (§2.8/§3) that follow the tab on drag.
13. Admin console (§7) fully wired — mint/revoke/flags/audit all live.
14. Response cache with honest labeling (§4 cache-honesty check).
15. Orb3D/animated per-agent presence, CSS-only placeholder pending a design-focused model
    (deliberately last — `IDEAS_OVERHAUL.md` Idea 15); tracked, not blocking.

§1 and §2 are most relevant to the chat UI work starting now. Nothing here needs new backend
contracts — every idea wires existing §3.1/§3.2 events to new UI.
