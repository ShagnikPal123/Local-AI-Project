/** Mods (mods.py): the owner's lasting changes to Nyx, and what they draw.
 *
 * One module-level store, fed by `/api/mods` and refreshed on the `mods.changed`
 * workspace event, so a mod Nyx saves mid-chat shows up in every window at once.
 * Reminders run here (not in a panel) because panels unmount on every tab switch.
 *
 * This is also where the assistant's other live workspace events land: `ui.theme`
 * (ui_set_theme and theme mods), `ui.open_tab` and `tabs.changed`. Nothing listened
 * for them before, so "make it teal" and "open my notes" were saved and never shown.
 */

import { api } from "../api";
import { createStore, useStore } from "./store";
import { onWorkspaceEvent } from "./workspaceEvents";
import { pushToast } from "./toastStore";

export interface ModPart {
  kind: string;
  [field: string]: unknown;
}

export interface Mod {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  author: "owner" | "assistant";
  request?: string;
  summary: string;
  parts: ModPart[];
  updated: number;
}

export interface ModView {
  banners: { mod: string; name: string; text: string; tone: "info" | "ok" | "warn" }[];
  statuses: { mod: string; name: string; text: string }[];
  reminders: { mod: string; name: string; text: string; every_minutes: number }[];
  start_tab: string;
}

interface ModsState {
  mods: Mod[];
  view: ModView;
  loaded: boolean;
  error: string;
}

const EMPTY_VIEW: ModView = { banners: [], statuses: [], reminders: [], start_tab: "" };
const store = createStore<ModsState>({ mods: [], view: EMPTY_VIEW, loaded: false, error: "" });

export function useMods(): ModsState {
  return useStore(store, (s) => s);
}

export async function loadMods(): Promise<void> {
  const result = await api.get<{ mods: Mod[]; view: ModView }>("/api/mods");
  if (!result.ok) {
    store.set({ error: result.error, loaded: true });
    return;
  }
  store.set({ mods: result.data.mods, view: result.data.view, loaded: true, error: "" });
  scheduleReminders(result.data.view.reminders);
}

export async function toggleMod(id: string, enabled: boolean): Promise<string> {
  const result = await api.post(`/api/mods/${encodeURIComponent(id)}/toggle`, { enabled });
  await loadMods();
  return result.ok ? "" : result.error;
}

export async function deleteMod(id: string): Promise<string> {
  const result = await api.del(`/api/mods/${encodeURIComponent(id)}`);
  await loadMods();
  return result.ok ? "" : result.error;
}

// --- reminders --------------------------------------------------------------------

const timers = new Map<string, number>();

function scheduleReminders(reminders: ModView["reminders"]): void {
  const wanted = new Map(reminders.map((r) => [`${r.mod}|${r.every_minutes}|${r.text}`, r]));
  for (const [key, timer] of timers) {
    if (!wanted.has(key)) {
      window.clearInterval(timer);
      timers.delete(key);
    }
  }
  for (const [key, reminder] of wanted) {
    if (timers.has(key)) continue;
    timers.set(key, window.setInterval(() => pushToast(`⏰ ${reminder.text}`, "info"), reminder.every_minutes * 60_000));
  }
}

// --- the theme ----------------------------------------------------------------------

/** ui_state token -> the CSS variables it drives. Density, motion, glass and wallpaper have their own settings. */
const THEME_VARS: Record<string, string[]> = {
  accent: ["--color-accent", "--color-accent-500"],
  accent2: ["--color-accent-2", "--color-accent-400"],
  background: ["--color-bg"],
  surface: ["--color-surface"],
  nav: ["--color-nav"],
  text: ["--color-text"],
};

const FONT_STACKS: Record<string, string> = {
  System: "system-ui, sans-serif",
  "Segoe UI": "\"Segoe UI\", system-ui, sans-serif",
  Inter: "Inter, system-ui, sans-serif",
  Roboto: "Roboto, system-ui, sans-serif",
  Georgia: "Georgia, serif",
  "JetBrains Mono": "\"JetBrains Mono\", ui-monospace, monospace",
  "Comic Neue": "\"Comic Neue\", \"Comic Sans MS\", cursive",
};

/** Apply only the tokens that differ from ui_state's defaults: an untouched theme leaves the black design alone. */
function applyTheme(theme: Record<string, unknown>, defaults: Record<string, unknown>): void {
  const root = document.documentElement.style;
  for (const [token, vars] of Object.entries(THEME_VARS)) {
    const value = theme[token];
    const changed = typeof value === "string" && value !== defaults[token];
    vars.forEach((name) => (changed ? root.setProperty(name, value as string) : root.removeProperty(name)));
  }
  const radius = theme.radius;
  if (typeof radius === "number" && radius !== defaults.radius) {
    root.setProperty("--radius", `${radius}px`);
    root.setProperty("--radius-lg", `${Math.round(radius * 1.6)}px`);
    root.setProperty("--radius-xl", `${Math.round(radius * 2.2)}px`);
  } else {
    ["--radius", "--radius-lg", "--radius-xl"].forEach((name) => root.removeProperty(name));
  }
  const font = typeof theme.font === "string" ? FONT_STACKS[theme.font] : undefined;
  if (font && theme.font !== defaults.font) {
    root.setProperty("--font-body", font);
    root.setProperty("--font-heading", font);
  } else {
    ["--font-body", "--font-heading"].forEach((name) => root.removeProperty(name));
  }
}

let themeDefaults: Record<string, unknown> = {};

async function loadTheme(): Promise<void> {
  const result = await api.get<{ theme: Record<string, unknown>; defaults: Record<string, unknown> }>("/api/ui/state");
  if (!result.ok) return;
  themeDefaults = result.data.defaults;
  applyTheme(result.data.theme, themeDefaults);
}

// --- start -------------------------------------------------------------------------

let started = false;

/** Called once by App: loads mods and the theme, opens the start tab, and keeps both live. */
export function startMods(): () => void {
  if (started) return () => {};
  started = true;
  void loadTheme();
  void loadMods().then(() => {
    const tab = store.get().view.start_tab;
    if (tab) window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab } }));
  });
  const stop = onWorkspaceEvent((event) => {
    if (event.type === "mods.changed") void loadMods();
    else if (event.type === "ui.theme" && event.theme && typeof event.theme === "object") {
      applyTheme(event.theme as Record<string, unknown>, themeDefaults);
    } else if (event.type === "ui.open_tab" && typeof event.tab_id === "string") {
      window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: event.tab_id } }));
    } else if (event.type === "tabs.changed") {
      window.dispatchEvent(new CustomEvent("nyx:tabs-changed"));
    }
  });
  return () => {
    stop();
    started = false;
    timers.forEach((timer) => window.clearInterval(timer));
    timers.clear();
  };
}
