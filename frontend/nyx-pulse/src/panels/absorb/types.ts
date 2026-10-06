/** Shapes served by routes_absorb.py (Data Absorption, Request R1–R8). */

export type Mode = "auto" | "given" | "prompt";
export type RunStatus = "starting" | "running" | "paused" | "stopping" | "done" | "stopped" | "error" | "interrupted";

export interface Span { s: number; e: number; term: string; topic: string | null }
export interface ReaderLine { i: number; text: string; spans: Span[] }

export interface DocView {
  id: string; kind: string; source: string; title: string; url: string;
  state: "queued" | "fetching" | "ready" | "reading" | "skimming" | "analysed" | "indexed" | "skipped" | "error";
  topic?: string | null; filed_at: number; read_at: number; done_at: number; score: number; gain: number;
  vote: Record<string, number>; line_index: number; line_total: number; tokens: number; summary: string; facts: number;
  error: string; meta?: Record<string, unknown>; lines?: ReaderLine[];
}

export interface Topic {
  id: string; code: string; name: string; color: number; count: number; share: number; docs: number;
  doc_vote: number; gain: number; terms: string[];
}

export interface DatasetRow { t: number; doc: string; source: string; kind: string; topic: string; topic_id: string | null; text: string; gain: number; by: string }
export interface ChartPoint { t: number; v: number; topic: string | null }
export interface Coverage { id: string; code: string; share: number; delta: number; color: number }

export interface Settings {
  speed: number; depth: number; parallel: number; breadth: number; minutes: number; docs_per_min: number;
  model_calls_per_min: number; storage_mb: number; sources: Record<string, boolean>;
}

export interface Live {
  id: string; mode: Mode; title: string; status: RunStatus; stage: string; stages: Record<string, number>;
  settings: Settings; focus: string | null; started_at: number; ended_at: number; now: number; ends_at: number | null;
  counts: Record<string, number>; topics: Topic[];
  reader: { doc_id?: string; title_spans?: Span[]; started?: number; finished?: boolean; doc?: DocView };
  queue: DocView[]; dataset: DatasetRow[]; chart: ChartPoint[]; coverage: Coverage[]; log: { t: number; text: string }[];
  error: string; report_ready: boolean; pending: number; seq: number;
}

export interface RunSummary {
  id: string; mode: Mode; title: string; status: RunStatus; created_at: number; started_at: number; ended_at: number;
  docs: number; facts: number; topics: string[]; headline: string; pending: number;
}

export interface Suggestion {
  id: string; kind: "skill" | "agent" | "agent_feature" | "speedup" | "dataset" | "local_model";
  title: string; why: string; spec: Record<string, unknown>; state: "pending" | "applied" | "dismissed" | "failed"; result: string;
}

export interface Report {
  headline: string; written_by: string;
  learned: { topic: string; code: string; count: number; docs: number; points: string[]; terms: string[] }[];
  added: Record<string, number>; sources: { source: string; count: number }[];
  documents: { id: string; title: string; url: string; source: string; facts: number; gain: number }[];
  next: string[];
}

export interface RunDetail {
  id: string; mode: Mode; prompt: string; links: string[]; uploads: string[]; settings: Settings; title: string; status: RunStatus;
  created_at: number; started_at: number; ended_at: number; focus: string | null; topics: (Topic & { terms: Record<string, number> })[];
  dataset: DatasetRow[]; report: Report | null; suggestions: Suggestion[]; error: string; forgotten: boolean; counts: Record<string, number>;
}

export interface Overview {
  runs: RunSummary[]; active: Live | null; defaults: Settings; limits: Record<string, [number, number]>;
  sources: string[]; stages: string[]; topics: { id: string; code: string; name: string }[];
  prefs: { use_in_chats: boolean }; storage_bytes: number;
}

// --- Data Process Use ------------------------------------------------------------------------------

export interface Finding { id: string; title: string; gist: string; details: string; severity: "good" | "info" | "warn" | "risk"; evidence: string }
export interface ResultTable { id: string; title: string; name: string; columns: string[]; rows: (string | number | boolean)[][]; total: number; shown: number }
export interface ResultChart { id: string; table: string; spec: Record<string, unknown> }
export interface Ranking { rank: number; name: string; score: number; scores: Record<string, number>; reasons: string; by: string }

export interface DataJob {
  id: string; request: string; status: "running" | "done" | "error" | "stopped" | "interrupted"; created_at: number;
  step: string; steps: Record<string, "waiting" | "working" | "done">; log: { t: number; text: string }[];
  items: { name: string; kind: string; size: number }[]; error: string;
  result: null | {
    summary: string; findings: Finding[]; tables: ResultTable[]; charts: ResultChart[]; rankings: Ranking[];
    answers: { name: string; answer: string }[]; follow_ups: string[]; suggestions: Suggestion[]; written_by: string;
  };
}

export interface Preset { id: string; label: string; request: string }

export const TOPIC_COLORS = ["#5ee08f", "#4cc9f0", "#f9a23b", "#ff7a8a", "#b39dff", "#e6e15c", "#7fd4c1", "#f28fd0", "#9cc7ff", "#d9b38c"];
export const topicColor = (index: number | undefined | null) => TOPIC_COLORS[((index ?? 0) % 10 + 10) % 10];

export function clock(ts: number): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function bytesLabel(bytes: number): string {
  return bytes > 1_048_576 ? `${(bytes / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
