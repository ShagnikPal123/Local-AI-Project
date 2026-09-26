/** Typed calls to /api/office (routes_office.py). Every one degrades to a readable error, never a throw. */

import { api } from "../../api";
import type { Aim, FocusState, LibraryItem, LibraryTree, OfficeOverview, OfficeSnapshot } from "./types";

export interface Selection {
  sections: string[];
  agents: string[];
  roles: string[];
}

export const officeApi = {
  overview: () => api.get<OfficeOverview>("/api/office"),
  library: () => api.get<LibraryTree>("/api/office/library"),

  newFolder: (name: string, parent = "") =>
    api.post<{ folder: LibraryItem }>("/api/office/folders", { name, parent }),
  newOffice: (name = "", parent = "") =>
    api.post<OfficeSnapshot>("/api/office/offices", { name, parent }),
  rename: (id: string, name: string) =>
    api.patch<{ item: LibraryItem }>(`/api/office/items/${id}`, { name }),
  move: (id: string, parent: string) =>
    api.patch<{ item: LibraryItem }>(`/api/office/items/${id}`, { parent }),
  setLinked: (id: string, linked: boolean) =>
    api.patch<{ item: LibraryItem }>(`/api/office/items/${id}`, { linked }),
  remove: (id: string) => api.del<{ trashed: string }>(`/api/office/items/${id}`),
  reveal: (id: string) => api.post<{ opened: string }>(`/api/office/items/${id}/reveal`),

  snapshot: (id: string) => api.get<OfficeSnapshot>(`/api/office/offices/${id}`),
  chat: (id: string, text: string) =>
    api.post<{ queued: boolean; job_id: string; snapshot: OfficeSnapshot }>(
      `/api/office/offices/${id}/chat`, { text }, 120_000),
  say: (id: string, text: string, selection: Selection, focusSection = "") =>
    api.post<{ sent_to: string[]; label: string; replying: number }>(
      `/api/office/offices/${id}/say`, { text, ...selection, focus_section: focusSection }),
  resolve: (id: string, text: string, selection: Selection, focusSection = "") =>
    api.post<Aim>(`/api/office/offices/${id}/resolve`, { text, ...selection, focus_section: focusSection }),
  control: (id: string, action: "pause" | "resume" | "halt", scope: "office" | "section" | "agent" = "office",
            target = "") =>
    api.post<OfficeSnapshot>(`/api/office/offices/${id}/control`, { action, scope, id: target }),

  files: (id: string) =>
    api.get<{ files: { path: string; size: number; at: number }[]; folder: string }>(
      `/api/office/offices/${id}/files`),
  file: (id: string, path: string) =>
    api.get<{ path: string; text: string; size: number }>(
      `/api/office/offices/${id}/file?path=${encodeURIComponent(path)}`),
  memory: (id: string) =>
    api.get<{ entries: { id: string; ts: number; kind: string; text: string; by: string }[];
      profile: Record<string, string> }>(`/api/office/offices/${id}/memory`),
  forget: (id: string, entryId: string) =>
    api.del<{ entries: unknown[] }>(`/api/office/offices/${id}/memory/${entryId}`),

  focus: (action: "enter" | "leave", officeId = "", remember = "") =>
    api.post<FocusState>("/api/office/focus", { action, office_id: officeId, remember }),
  settings: () => api.get<{ settings: OfficeOverview["settings"] }>("/api/office/settings"),
  saveSettings: (changes: Record<string, unknown>) =>
    api.put<{ settings: OfficeOverview["settings"] }>("/api/office/settings", { changes }),
};

export const EMPTY_SELECTION: Selection = { sections: [], agents: [], roles: [] };
