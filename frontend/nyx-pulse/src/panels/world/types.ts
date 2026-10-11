/** What the World backend sends (world/engine.py `snapshot`, routes_world.py). */

export type WorldStatus = "idle" | "running" | "paused" | "complete" | "stopped";
export type SpeedId = "deliberate" | "steady" | "fast" | "rush";

export interface WorldSector {
  sid: string;
  name: string;
  lat: number;
  lon: number;
  kind: string;
  gov: string;
  influence: number;
  founded_day: number;
  startup: boolean;
  important: boolean;
  full: boolean;
}

export interface WorldBot {
  aid: string;
  code: string;
  pretty: string;
  born_day: number;
  parents: string[];
  state: "awake" | "asleep";
  home: number;
  name: string;
  role: string;
  sector: string;
  generation: number;
  skills: string[];
}

export interface WorldBuilding {
  bid: number;
  sector: string;
  kind: string;
  floors: number;
  era: number;
  plot: number;
  built_day: number;
  state: "constructing" | "standing" | "demolishing";
  progress: number;
  why: string;
  tag?: string;
  phase?: "survey" | "foundation" | "frame" | "facade" | "fit-out" | "standing" | "demolishing";
}

/** The planet's own look, from the world's seed (world/planet.py). */
export interface WorldPlanet {
  type: string;
  label: string;
  about: string;
  radius: number;
  land: string[];
  sea: string[];
  sea_level: number;
  mountains: number;
  ice: number;
  air: string;
  clouds: number;
  greens: boolean;
  lava: boolean;
  rings: boolean;
  ring_color: string;
  ring_tilt: number;
  moons: { size: number; distance: number; speed: number; tilt: number; color: string }[];
  noise: number;
  day_hours: number;
  tilt: number;
}

export interface GovPerson { aid: string; name: string; role: string; sector: string; seat?: string }

/** The government's own district and its branches (world/civics.py). */
export interface WorldGovernment {
  name: string;
  lat: number;
  lon: number;
  branches: { key: string; name: string; title: string; about: string; open: boolean; members: GovPerson[]; note?: string }[];
  ministries: {
    key: string; name: string; about: string; open: boolean; needs: string; minister: GovPerson | null;
    focus?: string; focus_by?: string; stock?: Record<string, number>;
  }[];
  last_vote: { lid: number; yes: number; no: number; abstain: number; passed: boolean; day: number; text: string } | null;
  signer: string;
  era: string;
}

export interface TechRow {
  id: string;
  name: string;
  branch: string;
  cost: number;
  needs: string[];
  about: string;
  state: "done" | "ready" | "locked";
  transport?: number | null;
}

/** The technology tree (world/tech.py). */
export interface WorldTechStatus {
  tree: TechRow[];
  branches: Record<string, string>;
  focus: string;
  transport: number;
  transport_levels: string[];
  researched: number;
  total: number;
  next: { id: string; name: string; cost: number } | null;
  research_bonus: number;
  build_bonus: number;
  yield_bonus: number;
}

export interface WorldLaw {
  lid: number;
  text: string;
  scope: "world" | "sector" | "firm";
  sector: string;
  status: "proposed" | "testing" | "enforced" | "repealed" | "rejected";
  by: string;
  day: number;
  note: string;
  trial_job: string;
  votes?: string;
}

export interface WorldWar {
  wid: string;
  a: string;
  b: string;
  a_stance: string;
  b_stance: string;
  reason: string;
  status: "open" | "hearing" | "awaiting" | "resolved";
  cases: { a?: string; b?: string };
  winner: "" | "a" | "b" | "owner";
  decision: string;
  by: string;
  why: string;
  opened_at: number;
  deadline: number;
  resolved_at: number;
  day: number;
}

export interface WorldStartup {
  suid: string;
  name: string;
  idea: string;
  why: string;
  founders: string[];
  status: "proposed" | "approved" | "declined" | "founded";
  sector: string;
  day: number;
  by: string;
  from_war: string;
}

export interface WorldGrave {
  gid: number;
  aid: string;
  name: string;
  role: string;
  sector: string;
  born_day: number;
  died_day: number;
  epitaph: string;
  retired: boolean;
  code: string;
  rejoined: boolean;
}

export interface WorldProject {
  n: number;
  title: string;
  request: string;
  why: string;
  job_id: string;
  status: "running" | "done" | "failed" | "stopped";
  started_at: number;
  ended_at: number;
  day: number;
  summary: string;
}

export interface WorldEvent {
  ts: number;
  day: number;
  kind: string;
  text: string;
  ref: string;
}

export interface WorldTech {
  tech: string;
  about: string;
  style: string;
  palette: string[];
  era: number;
  day: number;
  ts: number;
}

export interface SpeedOption {
  id: SpeedId;
  label: string;
  what: string;
  allowed: boolean;
}

export interface WorldLimits {
  population: number;
  workers: number;
  machine: "high-end" | "medium" | "small";
  max_speed: SpeedId;
  speeds: SpeedOption[];
  reason: string;
}

export interface CensusStep {
  sector: string;
  sector_name: string;
  level: string;
  checked: number;
  needed: string[];
  resting: string[];
  index: number;
  total: number;
}

export interface WorldHead {
  id: string;
  name: string;
  office_id: string;
  goal: string;
  status: WorldStatus;
  speed: SpeedId;
  speed_label: string;
  walk: number;
  duration: number;
  spent: number;
  time_left: number | null;
  real_seconds: number;
  game_days: number;
  game_date: string;
  era: number;
  era_name: string;
  tech_points: number;
  next_era_at: number | null;
  techs: WorldTech[];
  stations: number;
  planets: number;
  stalled: string;
  note: string;
  births: number;
  deaths: number;
  created_at: number;
  updated_at: number;
  started_at: number;
  leader: { aid: string; name: string; member: string; kahuna: boolean };
  settings: { share_machine?: boolean };
  population: { ais: number; awake: number; asleep: number; common: number };
  projects_done: number;
  project: WorldProject | null;
  running: boolean;
  census: CensusStep | null;
  thinking: boolean;
}

export interface WorldSnapshot {
  world: WorldHead;
  planet: WorldPlanet;
  government: WorldGovernment;
  tech: WorldTechStatus;
  stock: Record<string, number>;
  /** [game day, tech points, buildings standing, floors, AIs] */
  growth: number[][];
  sectors: WorldSector[];
  bots: WorldBot[];
  buildings: WorldBuilding[];
  common: Record<string, number>;
  laws: WorldLaw[];
  wars: WorldWar[];
  startups: WorldStartup[];
  graves: WorldGrave[];
  projects: WorldProject[];
  timeline: WorldEvent[];
  commands: string[];
  limits: WorldLimits;
}

export interface WorldCard {
  id: string;
  name: string;
  path: string;
  office_id: string;
  goal: string;
  status: WorldStatus;
  speed: SpeedId;
  era: number;
  era_name: string;
  population: number;
  sectors: number;
  buildings: number;
  projects: number;
  game_days: number;
  real_seconds: number;
  run_until: number;
  created_at: number;
  updated_at: number;
  size: number;
}

export interface WorldOverview {
  worlds: WorldCard[];
  running: string;
  limits: WorldLimits;
  offices: { id: string; name: string; agents: number; goal: string; has_world: boolean }[];
  office_running: string;
  focus: { held: boolean; paused: string[]; note: string };
}

/** What the planet can point at, for the details card (U39: "click on any symbol"). */
export type Pick =
  | { kind: "world" }
  | { kind: "government" }
  | { kind: "sector"; id: string }
  | { kind: "building"; id: number }
  | { kind: "bot"; id: string }
  | { kind: "war"; id: string }
  | { kind: "startup"; id: string }
  | { kind: "grave"; id: number }
  | { kind: "law"; id: number }
  | { kind: "station"; id: number };
