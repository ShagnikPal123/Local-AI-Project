/** What the notch reads and writes on the engine (routes_equalize.py, equalize_assistant.py, ultrafast.py). */

import { api } from "../api";

export type AgentState = "idle" | "working" | "thinking" | "approval" | "error" | "finished";

export interface NotchAgent {
  id: string;
  name: string;
  kind: "ichos" | "avatar" | "agent" | "claude";
  sub?: string;
  color: string;
  state: AgentState;
  step: string;
  job?: string;
  count?: number;
  kind_of_work?: "code" | "email" | "general";
  about?: string;
  app?: string;
}

export interface CatalogAgent {
  id: string;
  name: string;
  kind: string;
  color: string;
  about?: string;
  personality?: string;
}

export interface DiffLine {
  sym: " " | "-" | "+";
  no: number;
  text: string;
}

export interface WorkStep {
  at: number;
  kind: "note" | "read" | "edit" | "bash" | "email" | "search" | "tool" | "done" | "error";
  title: string;
  file?: string;
  diff?: DiffLine[];
  command?: string;
  email?: { to: string; subject: string; body: string };
}

export interface Work {
  id?: string;
  agent_id: string;
  agent?: { id: string; name: string; kind: string; color: string };
  task: string;
  work: "code" | "email" | "general";
  status: "running" | "done" | "error" | "stopped" | "idle";
  steps: WorkStep[];
  result?: string;
}

export interface Pinned {
  id: string;
  name: string;
  kind: string;
  target: string;
  color: string;
}

export interface Timer {
  id: string;
  label: string;
  started: number;
  ends: number;
}

export interface AssistantSettings {
  talk: boolean;
  activation: { gestures: string[]; phrase: string; hotkey: string; sensitivity: number };
  voice: { mode: string; description: string; voice_id: string; rate: string; pitch: string; name: string;
    sample: { upload_id: string; pitch_hz: number; seconds: number; name: string } | null };
  personality: { source: "normal" | "custom" | "avatar"; text: string };
  avatar: { id: string; name: string; image: string; personality: string; keep_personality: boolean };
  sound: { muted: boolean; volume: number; mode: "ai" | "system" };
  notch: { enabled: boolean; open_on_hover: boolean; autoclose_s: number; hide_after_min: number; trio: boolean; effects: boolean };
  pinned: Pinned[];
  timers: Timer[];
  ultrafast: boolean;
  dropped: string[];
  gesture_help: Record<string, string>;
}

export interface FileRead {
  upload_id: string;
  name: string;
  kind: string;
  facts: string[];
  summary: string;
  report: null | { total: number; count: number; categories: { name: string; amount: number }[];
    biggest: { label: string; amount: number }[] };
  ms: number;
}

export const notchApi = {
  state: () => api.get<{ settings: AssistantSettings; agents: NotchAgent[] }>("/api/equalize/assistant"),
  save: (changes: Partial<AssistantSettings>) => api.put<AssistantSettings>("/api/equalize/assistant", changes),
  agents: () => api.get<{ agents: NotchAgent[]; catalog: CatalogAgent[] }>("/api/equalize/agents"),
  drop: (id: string, remove = false) => api.post<AssistantSettings>("/api/equalize/agents/drop", { id, remove }),
  work: (agentId: string) => api.get<Work>(`/api/equalize/agents/${encodeURIComponent(agentId)}/work`),
  task: (body: { agent: string; task: string; new_name?: string; app?: string; folder?: string }) =>
    api.post<Work>("/api/equalize/tasks", body),
  stop: (jobId: string) => api.post<{ stopped: boolean }>(`/api/equalize/tasks/${jobId}/stop`),
  readFile: (uploadId: string) => api.get<FileRead>(`/api/equalize/files/${uploadId}`),
  intent: (text: string, hasFile: boolean) =>
    api.post<{ action: "email" | "timer" | "chat"; to?: string; subject?: string; seconds?: number; label?: string }>(
      "/api/equalize/intent", { text, has_file: hasFile }),
  mail: (body: { to: string; subject: string; body: string; upload_ids: string[] }) =>
    api.post<{ sent: boolean; via: string; note?: string; to: string[] }>("/api/equalize/mail", body, 60_000),
  addTimer: (seconds: number, label: string) => api.post<Timer>("/api/equalize/timers", { seconds, label }),
  removeTimer: (id: string) => api.del<{ removed: boolean }>(`/api/equalize/timers/${id}`),
  voice: (body: { mode: string; description?: string; sample?: Record<string, unknown> }) =>
    api.post<AssistantSettings["voice"]>("/api/equalize/voice", body),
  avatar: (body: Record<string, unknown>) => api.post<AssistantSettings>("/api/equalize/avatar", body),
  sound: () => api.get<{ peak: number; playing: boolean; supported: boolean }>("/api/equalize/sound", 3000),
  newChat: (title: string) => api.post<{ chat: { id: string } }>("/api/chats", { title }),
  ultrafast: (text: string) => api.post<{ handled: boolean; reply: string; ms: number }>("/api/ultrafast", { text }),
  openApp: () => api.post<{ ok: boolean }>("/api/notch/open-app"),
  hide: () => api.post<{ ok: boolean }>("/api/notch/stop"),
};

// ── Controls, launchers and home views (notch_controls.py) ──────────────────

export type HomeViewId = "apps" | "now_playing" | "weather" | "calendar" | "agents";

export interface Launcher {
  id: string;
  name: string;
  kind: "app" | "site" | "folder" | "command";
  target: string;
  command: string;
  folder: string;
  color: string;
}

export interface NotchControls {
  system: string[];
  launchers: Launcher[];
  home: { default: HomeViewId; views: HomeViewId[]; city: string; triple_click: boolean };
  available: { id: string; label: string; icon: string }[];
  views: HomeViewId[];
}

export interface Weather { ok: boolean; why?: string; city?: string; now?: number; high?: number; low?: number; sky?: string; stale?: boolean }
export interface Playing { ok: boolean; why?: string; playing?: boolean; title?: string; artist?: string; app?: string }
export interface DayPlan { ok: boolean; why?: string; day?: string; date?: number;
  events: { title: string; start: string; end: string; all_day: boolean }[] }

export const controlsApi = {
  get: () => api.get<NotchControls>("/api/notch/controls"),
  save: (changes: Partial<Pick<NotchControls, "system" | "launchers" | "home">>) =>
    api.post<NotchControls>("/api/notch/controls", changes),
  addLauncher: (body: Partial<Launcher> & { name: string }) => api.post<NotchControls>("/api/notch/launchers", body),
  removeLauncher: (id: string) => api.del<NotchControls>(`/api/notch/launchers/${encodeURIComponent(id)}`),
  suggest: (name: string) =>
    api.post<{ name: string; kind: Launcher["kind"]; target: string; how: string }>("/api/notch/launchers/suggest", { name }),
  run: (id: string, kind: "system" | "launcher") => api.post<{ ok: boolean; said: string }>("/api/notch/run", { id, kind }),
  setDefault: (view: HomeViewId) => api.post<NotchControls>("/api/notch/home/default", { view }),
  weather: () => api.get<Weather>("/api/notch/home/weather", 12_000),
  playing: () => api.get<Playing>("/api/notch/home/now_playing", 4000),
  day: () => api.get<DayPlan>("/api/notch/home/calendar", 12_000),
};

// ── The hands-off sidebar (sidebar_window.py) and where the windows sit ─────

export interface SidebarPlace { enabled: boolean; edge: "left" | "right" | "free"; x: number; y: number; locked: boolean; collapsed: boolean }

export const sidebarApi = {
  place: () => api.get<SidebarPlace>("/api/notch/place/sidebar"),
  move: (changes: Partial<SidebarPlace>) => api.post<SidebarPlace>("/api/notch/place/sidebar", changes),
  start: () => api.post<{ running: boolean }>("/api/notch/sidebar/start"),
  stop: () => api.post<{ running: boolean }>("/api/notch/sidebar/stop"),
};

// ── What is waiting on the owner (notch.waiting) ────────────────────────────

export interface QuestionCard { question: string; options: { label: string; means: string; recommended?: boolean }[]; multi: boolean; other: string }
export interface WaitingItem { kind: "approval" | "trade" | "claude" | "question"; id: string; title: string; detail?: string;
  where: string; since: number; chat_id?: string; card?: QuestionCard }

export const waitingApi = {
  list: () => api.get<{ items: WaitingItem[] }>("/api/notch/waiting", 5000),
};

/** The message a click on a card's answer sends — the same words question_cards.answer_message writes. */
export function answerMessage(card: QuestionCard, label: string): string {
  const means = card.options.find((o) => o.label === label)?.means ?? "";
  return `**${card.question}**\n→ ${label}${means ? ` (${means})` : ""}`;
}

// ── Looks (notch_looks.py) ──────────────────────────────────────────────────

export interface NotchLook {
  id: string;
  name: string;
  colors: { island: string; card: string; ink: string; dim: string; accent: string };
  radius: { closed: number; open: number };
  width: number;
  font: string;
  glow: boolean;
  activation?: { open_on_hover?: boolean; hover_delay_ms?: number; autoclose_s?: number; trio?: boolean };
  built_in?: boolean;
}

export const looksApi = {
  list: () => api.get<{ active: NotchLook; looks: NotchLook[]; fonts: Record<string, string> }>("/api/notch/looks"),
  use: (id: string) => api.post<{ active: NotchLook; looks: NotchLook[]; fonts: Record<string, string> }>("/api/notch/looks/use", { id }),
  importLook: (look: unknown) =>
    api.post<{ active: NotchLook; looks: NotchLook[]; fonts: Record<string, string> }>("/api/notch/looks/import", look),
  remove: (id: string) => api.del<{ active: NotchLook; looks: NotchLook[]; fonts: Record<string, string> }>(`/api/notch/looks/${encodeURIComponent(id)}`),
  exportLook: (id: string) => api.get<Record<string, unknown>>(`/api/notch/looks/${encodeURIComponent(id)}/export`),
};

/** The CSS variables a look sets on the notch (notch.css reads them). Values were checked by notch_looks.clean. */
export function lookStyle(look: NotchLook | null, fonts: Record<string, string>): React.CSSProperties {
  if (!look) return {};
  const c = look.colors;
  return {
    ["--island" as string]: c.island, ["--card" as string]: c.card, ["--card-flat" as string]: c.card,
    ["--ink" as string]: c.ink, ["--ink-2" as string]: c.ink, ["--dim" as string]: c.dim, ["--dim-2" as string]: c.dim,
    ["--accent" as string]: c.accent, ["--r-closed" as string]: `${look.radius.closed}px`,
    ["--r-open" as string]: `${look.radius.open}px`, ["--font" as string]: fonts[look.font] ?? fonts.system,
  };
}
