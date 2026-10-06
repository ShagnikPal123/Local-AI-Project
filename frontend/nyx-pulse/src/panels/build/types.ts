/** Build studio data, mirroring design_studio.py. The server validates; these types only describe. */

import { api, type ApiResult } from "../../api";

export type Vec3 = [number, number, number];
export type FeatureType = "box" | "cylinder" | "sphere" | "cone" | "torus" | "wedge" | "pipe" | "extrude" | "revolve";
export type FeatureOp = "add" | "cut" | "intersect";
export type PinKind = "power" | "gnd" | "digital" | "analog" | "pwm" | "i2c" | "spi" | "uart" | "usb" | "net" | "mech";

export interface Feature {
  id: string;
  type: FeatureType;
  name: string;
  op: FeatureOp;
  at: Vec3;
  rot: Vec3;
  size: Record<string, number>;
  round: number;
  blend: number;
  note: string;
  color?: string;
  sides?: number;
  profile?: [number, number][];
  repeat?: { count: number; step: Vec3 };
  radial?: { count: number; axis: "x" | "y" | "z"; radius: number };
  mirror?: ("x" | "y" | "z")[];
}

export interface Pin {
  id: string;
  name: string;
  kind: PinKind;
  direction: string;
  at: Vec3;
  voltage: number;
  required: boolean;
  note: string;
}

export interface Part {
  id: string;
  name: string;
  kind: string;
  color: string;
  material: string;
  summary: string;
  features: Feature[];
  pins: Pin[];
  specs: Record<string, string | number | boolean>;
  tags: string[];
  source: "owner" | "ai" | "catalog";
  catalog_id: string;
  shell?: { thickness: number };
}

export interface Placement {
  id: string;
  part_id: string;
  name: string;
  at: Vec3;
  rot: Vec3;
  scale: number;
  color: string;
  locked: boolean;
  group: string;
  note: string;
}

export interface NetPoint { placement: string; pin: string }
export interface Net { id: string; name: string; kind: string; color: string; voltage: number; points: NetPoint[]; note: string }
export interface Joint { id: string; a: string; b: string; kind: string; note: string }

export interface Focus { kind: "part" | "placement" | "net" | "pin" | "feature" | "none"; id: string; part_id?: string }
export interface TutorialStep { id: string; title: string; body: string; focus: Focus; tips: string[]; warning: string }
export interface Tutorial { title: string; intro: string; steps: TutorialStep[]; source: string; model: string }

export interface ComparisonOption {
  id: string; name: string; catalog_id: string; summary: string; price_usd: number;
  pros: string[]; cons: string[]; specs: Record<string, string | number | boolean>; score: number;
}
export interface Comparison { question: string; options: ComparisonOption[]; recommendation: string; because: string; model: string }

export interface Project {
  id: string;
  name: string;
  goal: string;
  space: { width: number; depth: number; height: number };
  parts: Part[];
  placements: Placement[];
  joints: Joint[];
  nets: Net[];
  tutorial: Tutorial | null;
  comparison: Comparison | null;
  notes: string;
  updated_at: number;
}

export interface Finding { level: "error" | "warn" | "info"; message: string; where: { kind?: string; id?: string }; fix: string }
export interface BomLine {
  part_id: string; name: string; kind: string; quantity: number; unit_price: number; line_price: number;
  buy_or_print: "buy" | "print"; material: string; volume_cm3: number; grams: number; catalog_id: string;
}
export interface PrintRow { part_id: string; name: string; size_mm: Vec3; fits: boolean; volume_cm3: number; grams: number; material: string; notes: string[]; estimate: string }
export interface Box { min: Vec3; max: Vec3; size: Vec3 }

export interface Snapshot {
  project: Project;
  checks: Finding[];
  bom: { lines: BomLine[]; total_usd: number; unpriced: number; print_grams: number; note: string };
  printing: PrintRow[];
  bounds: Record<string, Box | null>;
}

export interface ProjectSummary { id: string; name: string; goal: string; parts: number; placements: number; nets: number; updated_at: number; has_tutorial: boolean }
export interface CatalogEntry { id: string; name: string; group: string; kind: string; color: string; summary: string; specs: Record<string, string | number>; tags: string[]; pin_count: number }
export interface LibraryEntry { id: string; name: string; kind: string; color: string; summary: string; tags: string[]; source: string; features: number; pins: number; size: Vec3 }

export interface WiringProposal { id: string; from: NetPoint & { label: string }; to: NetPoint & { label: string }; name: string; why: string }
export interface Job {
  id: string; project_id: string; brief: string; state: "running" | "done" | "failed" | "stopped" | "interrupted";
  phase: string; phase_label: string; progress: number; message: string; model: string;
  steps: { phase: string; text: string; model: string; at: number }[];
}

/** Model calls can take a while on a free tier; the default 15 s would cut them off mid-answer. */
const AI_TIMEOUT = 150_000;

const base = (projectId: string) => `/api/build/projects/${encodeURIComponent(projectId)}`;

export const buildApi = {
  projects: () => api.get<{ projects: ProjectSummary[]; active: string }>("/api/build/projects"),
  create: (name: string, goal = "") => api.post<Snapshot>("/api/build/projects", { name, goal }),
  open: (id: string) => api.get<Snapshot>(base(id)),
  update: (id: string, fields: Partial<Pick<Project, "name" | "goal" | "notes" | "space">>) => api.patch<Snapshot>(base(id), fields),
  remove: (id: string) => api.del<{ deleted: boolean }>(base(id)),

  savePart: (id: string, part: Partial<Part>, partId = "", place = false) =>
    api.post<Snapshot & { part: Part }>(`${base(id)}/parts`, { part, part_id: partId, place }),
  deletePart: (id: string, partId: string) => api.del<Snapshot>(`${base(id)}/parts/${partId}`),
  duplicatePart: (id: string, partId: string) => api.post<Snapshot & { part: Part }>(`${base(id)}/parts/${partId}/duplicate`),

  place: (id: string, body: { part_id?: string; catalog_id?: string; library_id?: string; at?: Vec3 }) =>
    api.post<Snapshot & { placement: Placement; part: Part }>(`${base(id)}/place`, body),
  movePlacement: (id: string, placementId: string, fields: Partial<Placement>) =>
    api.patch<Snapshot & { placement: Placement }>(`${base(id)}/placements/${placementId}`, fields),
  deletePlacement: (id: string, placementId: string) => api.del<Snapshot>(`${base(id)}/placements/${placementId}`),
  addJoint: (id: string, a: string, b: string, kind: string) => api.post<Snapshot>(`${base(id)}/joints`, { a, b, kind }),
  deleteJoint: (id: string, jointId: string) => api.del<Snapshot>(`${base(id)}/joints/${jointId}`),

  connect: (id: string, from: NetPoint, to: NetPoint, name = "") =>
    api.post<Snapshot & { net: Net }>(`${base(id)}/connect`, {
      from_placement: from.placement, from_pin: from.pin, to_placement: to.placement, to_pin: to.pin, name,
    }),
  disconnect: (id: string, netId: string, point?: NetPoint) =>
    api.del<Snapshot>(`${base(id)}/nets/${netId}${point ? `?placement=${encodeURIComponent(point.placement)}&pin=${encodeURIComponent(point.pin)}` : ""}`),
  renameNet: (id: string, netId: string, fields: Partial<Net>) => api.patch<Snapshot>(`${base(id)}/nets/${netId}`, fields),
  applyWiring: (id: string, connections: WiringProposal[]) =>
    api.post<Snapshot & { wired: number; refused: string[] }>(`${base(id)}/apply-wiring`, { connections }, AI_TIMEOUT),

  catalog: (q = "") => api.get<{ parts: CatalogEntry[]; groups: string[]; note: string }>(`/api/build/catalog${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  library: () => api.get<{ parts: LibraryEntry[] }>("/api/build/library"),
  saveToLibrary: (projectId: string, partId: string) =>
    api.post<{ part: Part; parts: LibraryEntry[] }>("/api/build/library", { project_id: projectId, part_id: partId }),
  deleteFromLibrary: (libraryId: string) => api.del<{ deleted: boolean; parts: LibraryEntry[] }>(`/api/build/library/${libraryId}`),

  ask: <T,>(id: string, body: { action: string; words?: string; part_id?: string; question?: string; save?: boolean; budget_minutes?: number }) =>
    api.post<T>(`${base(id)}/ask`, body, AI_TIMEOUT),
  jobs: (projectId: string) => api.get<{ jobs: Job[] }>(`/api/build/jobs?project_id=${encodeURIComponent(projectId)}`),
  stopJob: (jobId: string) => api.del<{ stopped: boolean }>(`/api/build/jobs/${jobId}`),
};

export type { ApiResult };

/** What is selected or lit in the scene. One source of truth for every panel. */
export type Selection =
  | { kind: "none" }
  | { kind: "placement"; id: string }
  | { kind: "net"; id: string }
  | { kind: "pin"; placement: string; pin: string };

export const PIN_COLORS: Record<string, string> = {
  power: "#ff453a", gnd: "#8e8e96", digital: "#64d2ff", analog: "#30d158", pwm: "#ffd60a",
  i2c: "#bf5af2", spi: "#ff9f0a", uart: "#5e5ce6", usb: "#0a84ff", net: "#64d2ff", mech: "#d1d1d6",
};
