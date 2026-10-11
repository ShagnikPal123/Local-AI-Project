# Avatars

Always-on helpers the owner shapes in the **Avatars** tab: a main function, what it does, when it runs (only when
called, all day between set hours, or all year), and which functions it may use — each set to **Allow** or **Ask me
first**. Core: `avatars.py`; routes: `routes_avatars.py`; UI: `frontend/nyx-pulse/src/panels/avatars/`;
tests: `tests/test_avatars.py`.

Owner's brief (2026-10-10): take the functions of OpenAI's Dots, Meta's Muse, xAI's Grok Bot and the open-source
MausBot, put them into normal chat, add an Avatars part with defaults like those four under new names, plus a couple
more, and let the owner make more.

## What came from where (ideas only, no code)

| Source | Idea | In Ichos |
|---|---|---|
| Dots (OpenAI, Sep 2026) | Goal-driven, keeps working in the background, connected apps, asks before actions | Goals + scheduled check-ins, Connected apps function, per-function Ask |
| Muse (Meta, Sep 2026) | Goals tab with a plan; "monitor the weather and tell me about rain"; remembers what you said once | Goals with steps, Watches (alert only on news, optional text to the phone), avatar notes |
| Grok Bot (xAI, Aug 2026) | Teach a task once and it repeats; 2–6 bots in one group chat, a chief of staff | Taught tasks (daily/weekly/when asked), `avatar_team` (first avatar leads) |
| MausBot (open source, Apache-2.0) | Local-first, each bot its own model and memory, every outside access waits for a click, runs coding CLIs | Model "Local only", all-Ask functions, `tell_claude` through Code |

## The defaults (all ship switched off)

Orbit (goals, like Dots) · Halo (life helper, like Muse) · Quasar (teach & repeat, team lead, like Grok Bot) ·
Vector (local crew, like MausBot) · plus Parallax (watch & alert), Lemma (study partner), Perigee (inbox & schedule).

## Rules

- An avatar is data, validated by `avatars.clean`. Shipped defaults stay in code; edits live in `avatars.json`
  (git-ignored, the owner's) and **Reset** drops them.
- Every avatar turn runs in its own chat ("Avatar · Name") behind `AvatarGuard`: deny by default, a tool runs only if
  its category belongs to a switched-on function; Ask puts an approval card in front of the owner. Never allowed:
  deleting files, system/power, the clipboard, Ichos's own code, themes/tabs/mods, creating or switching avatars.
  Money always asks.
- The clock (`tick`, every minute) runs only switched-on avatars: check-ins on their schedule, watches on their own
  interval, taught tasks daily/weekly. Busy avatars are skipped. `max_runs_per_day` (default 24) caps the cost.

## From normal chat

Tools: `avatar_list`, `avatar_ask` ("@Orbit …"), `avatar_team`, `avatar_create`, `avatar_switch`, `avatar_goal`,
`avatar_progress`, `avatar_watch`, `avatar_teach`, `avatar_note`. Commands: `/avatar Name what to do`,
`/team A, B: task`.
