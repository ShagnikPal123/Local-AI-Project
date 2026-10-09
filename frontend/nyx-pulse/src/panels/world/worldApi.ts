/** Typed calls to /api/world (routes_world.py). Every one degrades to a readable error, never a throw. */

import { api } from "../../api";
import type { SpeedId, WorldLaw, WorldOverview, WorldSnapshot, WorldStartup, WorldWar } from "./types";

const base = (id: string) => `/api/world/worlds/${encodeURIComponent(id)}`;

export const worldApi = {
  overview: () => api.get<WorldOverview>("/api/world"),
  create: (body: { name?: string; goal?: string; duration?: string; speed?: string }) =>
    api.post<WorldSnapshot>("/api/world/worlds", body, 60_000),
  upscale: (officeId: string, body: { name?: string; goal?: string; duration?: string; speed?: string } = {}) =>
    api.post<WorldSnapshot>("/api/world/upscale", { office_id: officeId, ...body }, 60_000),
  snapshot: (id: string) => api.get<WorldSnapshot>(base(id)),
  patch: (id: string, changes: { name?: string; goal?: string; duration?: string; settings?: Record<string, unknown> }) =>
    api.patch<WorldSnapshot>(base(id), changes),
  trash: (id: string) => api.del<{ trashed: string; note: string }>(base(id)),
  control: (id: string, action: "start" | "pause" | "resume" | "stop", haltOffice = false) =>
    api.post<WorldSnapshot>(`${base(id)}/control`, { action, halt_office: haltOffice }, 60_000),
  say: (id: string, text: string) =>
    api.post<{ note: string; queued: boolean; snapshot: WorldSnapshot }>(`${base(id)}/say`, { text }, 60_000),
  speed: (id: string, speed: SpeedId) => api.post<WorldSnapshot>(`${base(id)}/speed`, { speed }),
  newLaw: (id: string, text: string, scope = "world", sector = "") =>
    api.post<WorldLaw>(`${base(id)}/laws`, { text, scope, sector }),
  law: (id: string, lid: number, action: "enforce" | "repeal") =>
    api.post<WorldLaw>(`${base(id)}/laws/${lid}`, { action }),
  hearing: (id: string, wid: string) => api.post<WorldWar>(`${base(id)}/wars/${wid}/hearing`),
  decide: (id: string, wid: string, choice: "a" | "b" | "own", text = "") =>
    api.post<WorldWar>(`${base(id)}/wars/${wid}/decide`, { choice, text }),
  startup: (id: string, suid: string, action: "approve" | "decline") =>
    api.post<WorldStartup>(`${base(id)}/startups/${suid}`, { action }, 60_000),
  mood: (id: string, agentId: string) =>
    api.post<{ agent_id: string; mood: string; live: boolean; note: string }>(`${base(id)}/mood`,
      { agent_id: agentId }, 60_000),
  rejoin: (id: string, gid: number) => api.post<{ agent: { id: string; name: string } }>(`${base(id)}/graves/${gid}/rejoin`),
};
