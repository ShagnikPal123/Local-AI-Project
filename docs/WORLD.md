# The World tab — the AI Environment planet (UPDATE_IDEAS U34–U40, with U41, U44, U45)

Living design for `world/`, `routes_world.py` and `frontend/nyx-pulse/src/panels/world/`. The owner's words are in
`AI_HANDOFF/UPDATE_IDEAS.md` § "Added 2026-10-04" ("Make a new interactive plane g called ai environment …").
Started 2026-10-06 (session a40a67). Read this before touching `world/`.

## 1. What it is, in one paragraph

An **upscale of Office Space** for very large projects that run for hours, days or months. A world is a planet that
starts as bare rock with one camp and grows as its AIs work: sectors with their own governments, workplaces that rise
floor by floor, homes, talk lines, graves, start-ups, idea "wars", laws, and — once the technology allows — space
stations and artificial planets. **The work is real**: every project the world government decides on is run by an
office of agents (the existing `office/` engine: plan → staff → brief → work → review → wrap, the Output box, the
staffing rules). The planet is that office drawn as a civilisation, plus the layer the office does not have:
government, laws, wars, start-ups, reproduction, growth, game time and speed.

## 2. Decisions (taken on defaults — the owner asked not to be stopped mid-build; listed again in the handoff)

| Question | Decision | Why |
|---|---|---|
| Own engine or reuse Office? | **Reuse.** A world owns one *backing office*; projects become office jobs. | The office already plans, staffs, runs tools, reviews, delivers outputs and grades staff. A second engine would be a second set of bugs. |
| Where does a new world's office live? | `offices/Worlds/<world name>/` (visible in Office Space). An upscaled office stays where it was. | `library.scan` skips dot-folders, so a hidden office could not be found. Visible is also honest: that is where the files are. |
| "One file per world" (U40) | The world's state is **one gzipped file** `worlds/<name>.world`. The files the agents produce are deliverables and live in the backing office's `work/` folder, shown in the Output box. | The owner's point was "can't link to multiple" and "not too large": a world never spreads over linked folders, and its own state is a few KB. |
| How many AIs? | `min(casting.capacity().agents, tier cap)`: 400 on machines with 8 workers (high-end), 80 on 4, 24 below. | "1 to hundreds of ai (only for high end machines)". |
| Speeds | Deliberate · Steady · Fast · Rush. Each sets game time, construction speed, rest between projects, **review rounds and worker steps** (effort), and the war timer. Medium machines stop at Fast, small ones at Steady. | "a speed button so it is basically linked to effort … medium power computers can run both at lower speeds". |
| "All tasks shut down before this is run" | Starting a world always enters focus mode (pauses Nyx's background work) and **pins** it for the whole run; pause/stop releases it. A setting can share the machine instead. A running office blocks the start with a "Halt it and start" button — never halted silently. | Owner's words; halting someone's job is the owner's click. |
| Who leads? (U44) | The world government is the office's top manager, whose member is `casting.lead_member()` — Big Kahuna when it is up. Government decisions use `talk.ask_lead`. | "big kahuna and project 0 is the main brain and helps track and fuse". |
| Common bots | World-only figures with **no model**: they build, carry messages along talk lines, keep the infrastructure. Shown and counted separately from AIs. | "low power cores in the system that do work yet are just there for small tasks" — and a model call per builder would burn the owner's keys for decoration. |
| Mood (U39) | Asked live from the agent's own model when the owner looks; returned, **never stored**. | Owner: "to stop this from being a info stored on our computer". |
| Online access (U45) | World agents have the office tool set (web search, read a page). Signing in with Google, making accounts and posting are **not** added: they need the owner's approval path first. | Invariant 4/5 and the UPDATE_IDEAS caution. |
| Tech "images" (U37) | The managing AI names each new technology and its look as **data** (style, palette, roof) that the renderer turns into buildings. No image generation. | Specs are data, never code (invariant 2); image models are heavy and slow. |

## 3. Records (`world/state.py`) and the number codes (`world/genome.py`)

* **World** — id `wld-…`, name, `office_id`, goal, status (`idle · running · paused · complete · stopped`), speed,
  `run_until` (real time; 0 = until the government says the goal is met), real seconds run, **game days**, era,
  tech points, techs, sectors, bots, buildings, laws, wars, start-ups, graves, projects, timeline, settings, seed.
* **Sector** (one per office section) — lat/lon on the planet, workplace kind, government name, influence, start-up
  flag, important flag (the capital never changes kind).
* **Bot** (one per office agent) — the **genetic code**, born day, generation, parents, world state (awake · asleep),
  home plot. Name/role are cached only so a grave can say who it was.
* **Building** — sector, kind, floors, era built, plot, state (`constructing · standing · demolishing`), progress.
* **Law** — scope (world · sector · firm), text, rule code, status (`proposed · testing · enforced · repealed ·
  rejected`), who made it, the test note.
* **War** — two factions (sector + stance), the reason, status (`open · hearing · awaiting · resolved`), each side's
  case (only after a hearing), winner, decision, deadline.
* **Start-up** — name, idea, why, founders, status (`proposed · approved · declined · founded`), sector.
* **Grave** — name, role, sector, born and died day, epitaph, `retired` (may rejoin) and the genome to rejoin with.

Genetic code (U40): `G R K E M : skills`, hex — generation, role code, rank, employment, model code, then two hex
digits per skill (`skills.SKILLS` is a fixed table of 40 words so codes mean the same thing in every world; a world
appends its own after them). Role and model codes index the world's own tables, stored once per file. A child of two
bots gets generation + 1, a new role named from both parents ("Finance" + "Coder" → "Finance Coder"), the union of
their skills (at most 8) and the better parent's model.

The file stores rows as arrays, not objects, and caps every list (timeline 400, graves 500, buildings 900, projects
200), so a 300-bot world is a few KB on disk.

## 4. The run (`world/engine.py`)

A thread `world-<id>` per running world (one at a time — one office engine):

1. **Census** (U40) — on start and resume: sector by sector, capital first, from the government down through
   managers and workers to the common bots, each bot is checked for whether it is still needed (managers always;
   workers with work in the last two projects); the rest sleep. Published step by step so the owner watches it.
2. **Every second** — the clock advances (game days by speed), `world/sim.py` grows the world from what the office
   has done, construction moves, sleep follows employment and activity, a war past its deadline is judged.
3. **Between projects** — after the speed's rest, the government is asked for the next project (JSON: project, why,
   done, laws, rivals, start-up, teardown, retool). Offline (no model answers) a fixed sequence keeps the world
   working. The project goes to the office as a job whose text carries the laws in force, war decisions, start-ups
   and the owner's commands.
4. **After a project** — laws on trial are enforced (job done) or repealed (failed/stopped); one birth may happen
   (two best workers of different roles in that project); agents the office let go become graves; tech is
   recounted and a new era asks the government to name the technology and its look.
5. **Stops** when the deadline passes, the government says the goal is met (with no deadline), or the owner stops it.
   Focus is unpinned and released; everything is saved.

Owner commands ("commands go to everyone"): the world chat goes to the government. During a project it reaches the
office's top manager at once (`ENGINE.say`, which passes it on); between projects it becomes the next project.

## 5. The sim (`world/sim.py`) — pure functions, seeded, tested without models

* Workplaces per sector: `1 + tasks_done // 6`; floors grow with the sector's finished tasks up to the era's cap
  (2, 4, 8, 16, 30, 50, 80). Homes: one per four AIs. Every sector has a council hall; the capital has the capitol.
* Plots per sector: `8 + 4 × era`. When full, the oldest standing building from an older era is torn down and a
  taller one goes up ("outdated"); with nothing outdated the sector is full. When every sector is full: Orbital era
  or later builds a station (three stations and Stellar era make an artificial planet); before that the world is
  **stalled** and says what it needs.
* Tech points: tasks done + 3 × projects + 2 × laws enforced + 2 × wars resolved + 3 × start-ups founded. Eras:
  First Light 0 · Settlement 6 · Township 20 · City 50 · Metropolis 110 · Orbital 220 · Stellar 400.
* Workplace kinds follow the sector's purpose (code → data centre, research → lab, design → studio, finance → bank,
  testing/review → refinery, data → mine, writing/docs → archive, growth/marketing → farm, otherwise office) and
  modernise with the era unless the sector is important.

## 6. Routes (`routes_world.py`, owner-only, absent from hosted builds)

`GET /api/world` · `POST /api/world/worlds` · `POST /api/world/upscale` · `GET|PATCH|DELETE /api/world/worlds/{id}` ·
`POST …/{id}/control` (start · pause · resume · stop, with `halt_office`) · `POST …/{id}/say` · `POST …/{id}/speed` ·
`POST …/{id}/laws` · `POST …/{id}/laws/{law}` · `POST …/{id}/wars/{war}/hearing` · `POST …/{id}/wars/{war}/decide` ·
`POST …/{id}/startups/{startup}` · `POST …/{id}/mood` · `POST …/{id}/graves/{grave}/rejoin`.
Live changes: `world.event` on the workspace stream; agents, tasks, talk lines and outputs come from the backing
office's own `office.event`s.

## 7. The tab (`panels/world/`)

Lobby (worlds, New world, Upscale an office) → the world: a three.js planet you orbit and zoom (planet → sector →
workplace), click anything for its details (bot with live mood, government, workplace, war with "Open a
resolution", start-up with approve/decline, grave with "Bring back", law with enforce/repeal); top bar with era,
game date, real time left, population, speed and Start/Pause/Stop; the side column has the world chat and the
**Output** box (U41, the office's own), Government (laws, wars, start-ups) and People (census, births, graves); the
timeline along the bottom shows real time against game time. Office Space gets an **Upscale** button.

## 8. Tests

`tests/test_world_genome.py`, `test_world_sim.py`, `test_world_store.py`, `test_world_laws.py`,
`test_world_engine.py` (fake router, end to end through the office), `test_world_routes.py`, and the refusal lists in
`tests/test_server_auth.py`.
