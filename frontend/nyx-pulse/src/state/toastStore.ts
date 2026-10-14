/** Toasts: small transient notices from the workspace event stream.
 *
 * The server publishes `notify` events (level info/ok/warn/error) for things
 * that should be seen but not necessarily clicked — "Tab created", "Skill
 * kept". They queue here and auto-dismiss; a click action is optional.
 */

import { api } from "../api";
import { openChatPane } from "../components/chat/panes/paneDrag";
import { createStore, uid, useStore } from "./store";
import type { ToastItem } from "../components/chat/types";

/** Where the boxes appear (Settings → Notifications). Bottom right is where they always were. */
export type ToastPosition = "top-left" | "top-center" | "top-right" | "bottom-left" | "bottom-center" | "bottom-right";
export const TOAST_POSITIONS: ToastPosition[] = ["top-left", "top-center", "top-right", "bottom-left", "bottom-center", "bottom-right"];

interface ToastState {
  items: ToastItem[];
  position: ToastPosition;
}

const store = createStore<ToastState>({ items: [], position: "bottom-right" });
const MAX_VISIBLE = 4;
const DEFAULT_MS = 5200;
/** A notice that needs the owner stays longer than one that only says "done". */
const HELP_MS = 12000;

export function useToastPosition(): ToastPosition {
  return useStore(store, (s) => s.position);
}

export function setToastPosition(position: ToastPosition): void {
  store.set({ position });
}

let positionLoaded = false;
/** Read the saved corner once per page load; later changes arrive as `notifications.settings` events. */
export function loadToastPosition(): void {
  if (positionLoaded) return;
  positionLoaded = true;
  void api.get<{ settings?: { position?: string } }>("/api/notifications").then((result) => {
    const saved = result.ok ? result.data.settings?.position : undefined;
    if (saved && (TOAST_POSITIONS as string[]).includes(saved)) setToastPosition(saved as ToastPosition);
  });
}

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
  extra: { title?: string; ms?: number } = {},
): void {
  const item: ToastItem = { id: uid("toast"), text, level, action, title: extra.title };
  store.set((s) => ({ items: [...s.items, item].slice(-MAX_VISIBLE) }));
  window.setTimeout(() => dismissToast(item.id), extra.ms ?? DEFAULT_MS);
}

/** Workspace events the toast layer cares about, routed from the single SSE connection. */
export function handleNotifyEvent(event: { type: string; [key: string]: unknown }): void {
  if (event.type === "notifications.settings") {
    const saved = (event.settings as { position?: string } | undefined)?.position;
    if (saved && (TOAST_POSITIONS as string[]).includes(saved)) setToastPosition(saved as ToastPosition);
    return;
  }
  if (event.type !== "notify") return;
  const text = typeof event.text === "string" ? event.text : "";
  if (!text) return;
  const level = (["info", "ok", "warn", "error"] as const).find((l) => l === event.level) ?? "info";
  // A notice about a chat (done, needs you) can take the owner to it, beside the chat they are in.
  const chatId = typeof event.chat_id === "string" ? event.chat_id : "";
  const action = chatId && chatId !== "default"
    ? { label: "Open chat", onClick: () => openChatPane(chatId) }
    : undefined;
  pushToast(text, level, action, {
    title: typeof event.title === "string" && event.title ? event.title : undefined,
    ms: event.kind === "help" ? HELP_MS : undefined,
  });
}
