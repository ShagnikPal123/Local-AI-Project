/** Whether "ID0 + All" is on, shared by the companion window and active talk (Request S21/S22).
 *
 * One fetch of Big Kahuna's settings, then updates from the Big Kahuna tab (`nyx:kahuna-settings`). Voice checks this
 * on every few words, so it must be a plain read, not a request.
 */

import { api } from "../api";
import { CORE_TABS, LEGACY_LABELS } from "../tabs";

type Listener = (on: boolean) => void;

let allOn = false;
let loaded = false;
const listeners = new Set<Listener>();

function set(on: boolean) {
  allOn = on;
  for (const listener of listeners) listener(on);
}

export function kahunaAllOn(): boolean {
  return allOn;
}

export function onKahunaAll(listener: Listener): () => void {
  listeners.add(listener);
  if (!loaded) {
    loaded = true;
    void api.get<{ settings: Record<string, unknown> }>("/api/identity0/settings").then((result) => {
      if (result.ok) set(Boolean(result.data.settings.id0_all));
    });
    window.addEventListener("nyx:kahuna-settings", (event) => {
      const settings = (event as CustomEvent<Record<string, unknown>>).detail ?? {};
      if ("id0_all" in settings) set(Boolean(settings.id0_all));
    });
  } else {
    listener(allOn);
  }
  return () => listeners.delete(listener);
}

export async function setKahunaAll(on: boolean): Promise<string> {
  const result = await api.put<{ settings: Record<string, unknown> }>("/api/identity0/settings", { changes: { id0_all: on } });
  if (!result.ok) return result.error;
  set(Boolean(result.data.settings.id0_all));
  window.dispatchEvent(new CustomEvent("nyx:kahuna-settings", { detail: result.data.settings }));
  return "";
}

export interface KahunaAction {
  kind: "open_url" | "open_tab" | "compose_email";
  early: boolean;
  key: string;
  label?: string;
  url?: string;
  tab?: string;
  to?: string;
  spoken?: string;
}

export interface KahunaIntent { text: string; final: boolean; actions: KahunaAction[]; handled: boolean }

const TAB_NAMES = [...CORE_TABS.map((t) => ({ id: t.id as string, label: t.label })), ...LEGACY_LABELS];

/** What the owner is saying, read as actions (the server knows which places are safe to open). */
export async function readIntent(text: string, final: boolean): Promise<KahunaIntent | null> {
  const result = await api.post<KahunaIntent>("/api/identity0/intent", { text, final, tabs: TAB_NAMES }, 4000);
  return result.ok ? result.data : null;
}

/** Run one action: tabs open here, sites and email drafts open on this PC through the engine. */
export async function runAction(action: KahunaAction): Promise<string> {
  if (action.kind === "open_tab" && action.tab) {
    window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: action.tab } }));
    return `Opened ${action.label || action.tab}.`;
  }
  const result = await api.post<{ ok: boolean; draft?: { to: string } }>("/api/identity0/act", { action }, 20000);
  if (!result.ok) return result.error;
  if (action.kind === "compose_email") return `Your email to ${result.data.draft?.to || "them"} is ready in Gmail. Check it and press Send.`;
  return `Opened ${action.label || "it"}.`;
}
