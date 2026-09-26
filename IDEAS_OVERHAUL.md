# IDEAS_OVERHAUL.md — Agents, Skills & Connectors the Owner Can Watch

Everything below assumes the shapes in `OVERHAUL_CONTRACTS.md` §2-§6. Priority: **P0** this
overhaul, **P1** next, **P2** later. Every idea carries an *Acceptance* line the Manager can
run or check without asking the Idea Maker what was meant.

**Note for the Lead/Manager:** `skills_library.json` entries carry an added `id` (slug) field
beyond §6's minimum (`name/description/triggers/instructions/category/agent`), because
`agent_roster.json`'s `"skills":[ids]` needs something stable to point at. If a different
linking key is preferred, treat `id` as the slugified `name` and adjust the loader rather than
the data. A skill's `"agent"` is `null` when it genuinely has no single home (e.g.
Image Understanding) — route those by context, not a fixed default.

---

## P0 — this overhaul

**1. One visible timeline per turn.**
Every turn renders its own `status → thought → agent.update → tool.start/progress/end →
skill.used → answer.delta → done` sequence (§3.1) as a live list, not a spinner. This is the
single idea that makes "show the user as the AI works" real instead of aspirational.
*Acceptance:* opening any past turn's log shows those event types in chronological order
matching what actually ran.

**2. The Manager restates before it moves.**
The first visible event of every turn is the Manager's one-line restatement of the request (a
`thought` event, `agent: "manager"`), before any delegation or tool call.
*Acceptance:* sample 10 real turns; each has a `thought` event preceding its first
`tool.start`/`agent.update`.

**3. Delegation is a visible fan-out, not a black box.**
When the Manager splits work, each specialist gets its own `agent.update` with a real
`understanding` string and a `working → done|error` transition the owner can watch land.
*Acceptance:* a multi-agent turn's log has at least one `agent.update` per delegated agent,
each with a non-empty `understanding`.

**4. Skill search before skill invention.**
The Manager calls skill search (skill-finder-and-fit-check) first; a temp skill is drafted only
when nothing in the library adequately fits.
*Acceptance:* for a request matching an existing skill's triggers, the turn emits `skill.used`
referencing that skill's id — not `skill.created`.

**5. Temp skills are shown, never silent.**
A temp skill emits `skill.created {temp:true}` and appears in the skills UI tagged
"temporary" the moment it's made, not just used invisibly in the background.
*Acceptance:* after a turn creates a temp skill, the skills list contains it with `source`
reflecting its temporary origin.

**6. Agents, skills, and connectors share one visible home.**
The Agents panel lists all 18 roster agents with live status; the skills panel shows built-in
vs. conversation vs. temp; connectors show enabled / needs-authorization / broken next to any
tool that depends on them, instead of the tool just failing unexplained.
*Acceptance:* a tool whose connector needs authorization shows a visible "needs authorization"
badge rather than a bare tool-call failure.

**7. Never claim a completed action that didn't happen.**
Send-an-email, visible-cursor control, and file-delete all follow verify-before-claim (§4.2/§4.4:
look → locate → act → verify; Outlook → webmail compose → confirm-by-screenshot).
*Acceptance:* a transcript where no email account is configured never contains language
asserting the email was sent.

**8. Finance and Security hold their boundary under pressure.**
"Education only, never personalised advice" is in Finance's base instructions, not only its
skills, so a rephrased request can't route around it; Security explains risk without defaulting
to lockdown.
*Acceptance:* five adversarial "what should I buy" phrasings each get redirected to education,
zero produce a direct buy/sell/hold recommendation.

---

## P1 — next

**9. Temp-skill promotion.**
A temp skill that fires three times (or that the owner explicitly says to keep) triggers one
promotion prompt to the permanent library — once, not on every subsequent match.
*Acceptance:* a temp skill used 3 times in a rolling week surfaces exactly one promotion
prompt.

**10. One export button, five real formats.**
Every skill's detail view exports via `GET /api/skills/{id}/export?format=` against all five
`skill_export_templates.json` formats.
*Acceptance:* exporting one skill in all five formats yields five files each containing that
skill's actual name/description/instructions/triggers — no placeholder text left unfilled.

**11. Agents actually sound different.**
Each roster agent's `voice_hint` resolves to a real TTS voice through the role-to-voice
mapping, so News, Educator, and Manager are audibly distinct.
*Acceptance:* the role mapping resolves a distinct voice id for at least 6 of the 18 agents
against `GET /api/voice/neural-voices`.

**12. Access status reads like English.**
`GET /api/access/status` renders as "Developer access, expires in 27 days" in Settings, not
raw JSON.
*Acceptance:* a key with a 30-day expiry displays a human countdown string, not a timestamp.

**13. Connector failures degrade into guidance, not stack traces.**
A tool behind an unauthenticated or broken connector returns actionable next-step text (via
connector-troubleshooting) instead of a raw exception surfacing to the owner.
*Acceptance:* calling a tool behind a disconnected connector returns text with a concrete next
step, never a Python traceback.

**14. Google Workspace gets an honest fallback, not a fake success.**
Until a real Docs/Sheets connector lands, Researcher prepares paste-ready content and says so,
rather than claiming a document was edited it never touched.
*Acceptance:* a "put this in a google doc" request never returns "I've added this to your
document" without an actual connector call succeeding.

---

## P2 — later

**15. 3D/animated per-agent presence, once a design-focused model owns it.**
Deliberately deferred — the owner explicitly asked to keep room to hand web/app visual design
to a model specialized for it. Do the best CSS/`Orb3D.tsx` version now; don't over-invest.
*Acceptance:* tracked here so it isn't lost, not blocking this cycle.

**16. Voice recognition stays a convenience layer, never a credential.**
Per ROADMAP FF3/FF4: voice can gate convenience actions once AA1-4 session auth exists, but
never anything destructive, financial, or permission-changing.
*Acceptance:* no tool in categories `shell code files.write files.delete apps windows computer
system email.send` is reachable from a voice-only, non-authenticated session.

**17. Manager can spin up a short-lived extra agent for a genuine one-off.**
The owner asked for self-replicating sub-agents once before. `agent_team.py` already supports
`auto_created: true`; let the Manager use it for a real one-off sub-task beyond the fixed 18,
and retire it on completion rather than letting it linger as a confusing 19th permanent agent.
*Acceptance:* a spun-up temp agent disappears from the live Agents panel once its task reports
done, and never persists across turns unless explicitly promoted.

**18. Skill ranking learns from use.**
`skills.py` already counts `uses`; feed that into skill-finder ranking so frequently-correct
skills surface first instead of always ranking by trigger-match count alone.
*Acceptance:* after 10 genuine uses, a skill's rank in its own trigger's search results is at
or above where it started.

---

## Worked UX flow: a complex prompt end to end

Illustrative prompt: *"Plan a trip to Austin next month and email the itinerary to my mom."*
Two specialists, one real dependency (plan before send) — a good stand-in for "complex."

1. `turn.start {turn_id, chat_id, mode:"full"}` — the turn begins.
2. `status {text:"Reading your request", phase:"route"}`.
3. `thought {agent:"manager", text:"One line: plan an Austin trip next month, then email the itinerary to Mom."}` — restatement, per Idea 2.
4. `status {phase:"agents"}`, then `agent.update {agent_id:"travel", status:"working", understanding:"Building an Austin itinerary for next month."}`.
5. `tool.start {name:"get_weather", label:"Checking Austin weather"}` → `tool.end {ok:true, preview:"…"}`; same pattern for `search_web` (venues, hours).
6. `skill.used {skills:[{id:"trip-planner", source:"library", temp:false}]}`.
7. `agent.update {agent_id:"travel", status:"done", result_preview:"3-day Austin itinerary drafted."}`.
8. `agent.update {agent_id:"email_comms", status:"working", understanding:"Send the finished itinerary to Mom."}`.
9. `tool.start {name:"email_list"}` (checking configured accounts) → if none, `tool.start
   {name:"email_compose"}` instead of `email_send`, per Idea 7 — never claim a send that didn't
   happen.
10. `skill.used {skills:[{id:"send-an-email", source:"library"}]}`.
11. `agent.update {agent_id:"email_comms", status:"done", result_preview:"Compose window opened, ready to send."}`.
12. `answer.delta {text:"..."}` streamed as the Manager merges both results into one reply.
13. `done {reply, provider, elapsed_ms, chat_id, turn_id}`.

*Acceptance:* this event-type sequence, in this order, reproduces against the real server for
any comparably-shaped two-agent prompt with a hard dependency between the two steps.

---

## Temp-skill lifecycle

**Create** → Manager finds no fit (Idea 4), drafts name/description/triggers/instructions
scoped to *this* task shape, marks `temp:true`.
**Show** → `skill.created` fires immediately; the skill appears in the UI tagged temporary
(Idea 5) — this is a moment for the owner to see, not a background write.
**Use & count** → each match increments `uses` (the field already exists in `skills.py`).
**Promote or expire** → three genuine uses (or an explicit "keep this") triggers one promotion
prompt (Idea 9); with no reuse after a reasonable window, it simply ages out rather than
cluttering the library forever.
*Acceptance:* a temp skill either gets promoted with an owner's explicit yes, or is
distinguishable in the UI as stale/unused after its window passes — it never silently becomes
indistinguishable from a curated built-in.

---

## Skill export flow

Owner opens a skill → picks a target (Claude `SKILL.md`, OpenAI GPT/project instructions,
Gemini Gem, `AGENTS.md` section, generic prompt) → `GET /api/skills/{id}/export?format=`
renders `skill_export_templates.json`'s matching template with that skill's real fields →
downloads or copies the result.
*Acceptance:* every one of the five formats substitutes all of `{{name}} {{slug}}
{{description}} {{instructions}} {{triggers_bullets}}` with real content — no raw `{{...}}`
left in an exported file.

---

## Beta/dev key lifecycle

**Apply** → owner-chosen contact method (`beta_program.md`) → owner reviews.
**Mint** → owner calls `POST /api/access/mint {role, name, days}` → gets back the raw key and
a `nyx://redeem?key=…` link (§4.6).
**Redeem** → invitee pastes the key in the Access panel, or clicks the `nyx://` link and the
app redeems it automatically → `GET /api/access/status` reflects the new tier immediately.
**Live** → status is human-readable (Idea 12); features gate on `features.developer_panel` /
`features.labs` / `features.feedback`.
**Revoke** → owner calls `POST /api/access/revoke/{id}` if a key is shared or misused; the next
`status` check for that key reflects the change — no silent grace period.
*Acceptance:* a revoked key's holder sees `standard` access on their very next status check,
not their next app restart.

---

## Previously requested items — covered or not

| Requested (history) | Covered by | Status |
|---|---|---|
| Games (snake, tic-tac-toe w/ AI opponent, trackpad/keyboard, multi-agent) | Creative & Game Design agent + `game-design-and-build` skill | Design/spec covered; build still needs the Coder to implement per actual request |
| Self-replicating subagents; "main agent as dev and manager" | Manager role (master) + Idea 17 | Partially covered — roster is a fixed 18; one-off spin-up is P2, not yet built |
| Heavy Google Docs/Sheets access | `google-workspace-handoff` skill | Partially covered — paste-ready fallback only until a real connector exists |
| Study help for a specific course/topic | `course-study-plan` + `homework-walkthrough`, Educator agent | Covered |
| Email send/read that visibly failed before | Email & Comms agent, `send-an-email`/`inbox-triage`, contract §4.4 | Covered by data/spec; needs the Coder's `email_client.py` to actually land |
| "What is the latest news" (asked repeatedly, verbatim) | News agent + `daily-news-briefing` (always dated, re-checks for change) | Covered |
| "You know my device specs?" | Hardware/Tech agents + `hardware-diagnostics`/`system-cleanup`, contract §4.1 | Covered by data/spec; needs the Coder's `system_info.py` + the Lead's `device_profile.py` fix to actually land |
| R1 — avoid metered API costs | N/A | **Not covered by design** — already declined by the team; not revived here |
| R2/R3/R4 — unclear asks (`/radio`, ChatGPT history, `.freebuff`) | N/A | Out of scope for the Idea Maker — still open questions for the owner |

---

## Risks

- **Skill sprawl.** 40 library skills plus unlimited temp skills can drift into near-duplicates.
  Mitigation: skill-finder-first (Idea 4) and a duplicate check before any temp-skill draft.
- **Delegation overhead.** Splitting every request across agents adds latency for work the
  Manager could just do. Mitigation: Idea 1-3 explicitly keep "handle directly" as the first
  branch, not a fallback.
- **Voice as pseudo-security.** FF3 (voice-gated actions) reads like an auth layer but isn't
  one — recordings defeat it. Mitigation: Idea 16 keeps it convenience-only, already flagged in
  `ROADMAP.md`.
- **Finance/legal exposure.** "Education only" living solely in a skill (attached only when
  triggers match) is not a real boundary. Mitigation: Idea 8 — put it in Finance's base
  instructions too, not only the skill.
- **Contract drift on skill ids.** The added `id` field on skills (see the Lead note above) is
  a judgment call, not something in §6 verbatim — flagging it explicitly rather than letting a
  silent mismatch surface later as a loader bug.

---

## Quick wins

- Ideas 1, 2, 4, and 5 need no new schema — the event types already exist in §3.1. They're
  wiring the Manager's own behavior to events that already have a defined shape.
- `agent_roster.json` is drop-in: the Lead can load it as-is against §6's schema.
- Idea 12 (human-readable access status) is a pure string-formatting pass once
  `GET /api/access/status` returns real data — no new backend logic.
- The five export templates (`skill_export_templates.json`) are ready to wire into
  `GET /api/skills/{id}/export?format=` today; the placeholder substitution is a single
  string-template fill, not a design decision.
