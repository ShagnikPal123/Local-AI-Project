/** What the Office Space backend sends (office/state.py, routes_office.py). */

export interface OfficeSection {
  id: string;
  name: string;
  color: string;
  purpose: string;
  manager_id: string;
  status: "active" | "paused" | "halted";
  created_at: number;
  job_id: string;
  notes: string;
  order: number;
}

export interface OfficeAgent {
  id: string;
  name: string;
  role: string;
  section_id: string;
  member: string;
  status: "idle" | "working" | "waiting" | "paused" | "error";
  step: string;
  task_id: string;
  desk: number;
  created_at: number;
  origin: string;
  tasks_done: number;
  seconds: number;
  errors: number;
  note: string;
  inbox: number;
  /** Update 1, U42: part-time agents are called in only when their kind of work comes up. */
  employment?: "full" | "part_time";
  /** -1 junior, 0 normal, 1 senior, 2 lead. */
  rank?: number;
}

export interface OfficeTask {
  id: string;
  title: string;
  detail: string;
  section_id: string;
  agent_id: string;
  role: string;
  status: "queued" | "working" | "review" | "done" | "failed" | "cancelled";
  created_by: string;
  job_id: string;
  parent_id: string;
  after: string[];
  result: string;
  report_path: string;
  files: string[];
  feedback: string;
  tries: number;
  created_at: number;
  started_at: number;
  ended_at: number;
}

export interface OfficeMessage {
  id: string;
  text: string;
  by: string;
  by_name: string;
  to: string[];
  to_label: string;
  kind: "chat" | "thread" | "report" | "delegate" | "liaison" | "system" | "hire";
  ts: number;
  job_id: string;
  section_id: string;
}

export interface OfficeHire {
  id: string;
  role_words: string;
  why: string;
  long_term: string;
  count: number;
  clone_of: string;
  section_id: string;
  by: string;
  by_name: string;
  status: "pending" | "approved" | "denied" | "reuse";
  decided_by: string;
  reason: string;
  use_instead: string;
  role_id: string;
  new_type: boolean;
  ts: number;
  decided_at: number;
}

/** Something the office delivered — the Output box (Update 1, U41). */
export interface OfficeOutput {
  id: string;
  title: string;
  text: string;
  status: "done" | "partial" | "failed" | "stopped";
  links: { kind: "file" | "url"; label: string; path?: string; href?: string }[];
  job_id: string;
  by: string;
  by_name: string;
  ts: number;
}

/** Part-time, let go, promoted, demoted — shown beside hiring (Update 1, U42). */
export interface OfficeStaffChange {
  id: string;
  agent_id: string;
  agent_name: string;
  change: "part_time" | "full_time" | "let_go" | "promoted" | "demoted";
  why: string;
  role: string;
  job_id: string;
  ts: number;
}

export interface OfficeJob {
  id: string;
  request: string;
  title: string;
  phase: string;
  kind: string;
  status: "running" | "done" | "stopped" | "failed";
  started_at: number;
  ended_at: number;
  reply: string;
  summary: string;
  scale: string;
  section_ids: string[];
  task_ids: string[];
  error: string;
}

export interface OfficeRole {
  id: string;
  title: string;
  glyph: string;
  color: string;
  domain: string;
  kind: "manager" | "worker" | "messenger" | "special";
  goal: string;
  origin: string;
  plural: string;
  synonyms: string[];
}

export interface FocusState {
  held: boolean;
  available: boolean;
  office_id: string;
  since: number;
  reason: string;
  paused: string[];
  kept_running: string[];
  note: string;
  background?: Record<string, unknown>;
}

export interface OfficeHead {
  id: string;
  name: string;
  status: "idle" | "running" | "paused" | "halted";
  phase: string;
  goal: string;
  created_at: number;
  updated_at: number;
  capacity: number;
  gatekeeper_id: string;
  counts: {
    agents: number; working: number; sections: number; tasks: number;
    tasks_done: number; tasks_open: number; hires_pending: number;
  };
  settings: Record<string, unknown>;
  stats: Record<string, unknown>;
  path: string;
  folder: { id: string; name: string; linked: boolean } | null;
  linked_offices: { id: string; name: string }[];
  capacity_detail: { agents: number; concurrency: number; members: number; reason: string; focus: boolean; power: string };
  running: boolean;
  gatekeeper_reason: string;
}

export interface OfficeSnapshot {
  office: OfficeHead;
  sections: OfficeSection[];
  agents: OfficeAgent[];
  tasks: OfficeTask[];
  chat: OfficeMessage[];
  thread: OfficeMessage[];
  feed: OfficeMessage[];
  hires: OfficeHire[];
  outputs: OfficeOutput[];
  staffing: OfficeStaffChange[];
  job: OfficeJob | null;
  roles: OfficeRole[];
  focus: FocusState;
}

/** One office file or folder in the lobby. */
export interface LibraryItem {
  id: string;
  name: string;
  kind: "folder" | "office";
  path: string;
  parent: string;
  created_at: number;
  updated_at: number;
  linked?: boolean;
  agents?: number;
  sections?: number;
  goal?: string;
  status?: string;
  jobs?: number;
  summary?: string;
  last_request?: string;
}

export interface LibraryTree {
  root: string;
  folders: LibraryItem[];
  offices: LibraryItem[];
}

export interface OfficeOverview {
  library: LibraryTree;
  settings: { focus_mode: "ask" | "always" | "never"; allow_web: boolean; max_agents: number; animate: boolean;
    keep_open_offices: number; parallel_offices: number };
  focus: FocusState;
  capacity: { agents: number; concurrency: number; members: number; reason: string; focus: boolean; power: string };
  running_office: string;
  /** Every office working right now; several on a high-end PC (U14). */
  running_offices: string[];
  parallel: { limit: number; reason: string };
  first_run: boolean;
  models: string[];
}

export interface Aim {
  agents: string[];
  label: string;
  message: string;
  addressing: string;
  sections: string[];
  roles: string[];
  unknown: string[];
  count: number;
}

/** A line drawn between two desks for a few seconds after one agent talks to another. */
export interface Talk {
  id: string;
  from: string;
  to: string[];
  at: number;
}
