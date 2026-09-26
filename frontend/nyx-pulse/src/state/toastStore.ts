/** Toasts: small transient notices from the workspace event stream.
 *
 * The server publishes `notify` events (level info/ok/warn/error) for things
 * that should be seen but not necessarily clicked — "Tab created", "Skill
 * kept". They queue here and auto-dismiss; a click action is optional.
 */

import { createStore, uid, useStore } from "./store";
import type { ToastItem } from "../components/chat/types";

interface ToastState {
  items: ToastItem[];
}

const store = createStore<ToastState>({ items: [] });
const MAX_VISIBLE = 4;
const DEFAULT_MS = 5200;

export function useToasts(): ToastItem[] {
  return useStore(store, (s) => s.items);
}

export function dismissToast(id: string): void {
  store.set((s) => ({ items: s.items.filter((t) => t.id !== id) }));
}

export function pushToast(
  text: string,
  level: ToastItem["level"] = "info",
  action?: ToastItem["action"],
): void {
  const item: ToastItem = { id: uid("toast"), text, level, action };
  store.set((s) => ({ items: [...s.items, item].slice(-MAX_VISIBLE) }));
  window.setTimeout(() => dismissToast(item.id), DEFAULT_MS);
}

/** Workspace events the toast layer cares about, routed from the single SSE connection. */
export function handleNotifyEvent(event: { type: string; [key: string]: unknown }): void {
  if (event.type !== "notify") return;
  const text = typeof event.text === "string" ? event.text : "";
  if (!text) return;
  const level = (["info", "ok", "warn", "error"] as const).find((l) => l === event.level) ?? "info";
  pushToast(text, level);
}
