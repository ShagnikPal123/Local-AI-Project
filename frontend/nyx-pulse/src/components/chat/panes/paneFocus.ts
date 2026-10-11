/** Which chat pane the owner is working in. Things sent to "the chat" from outside a pane — the microphone, a
 *  question card or plan Approve, a Python box's "Explain this" — go to this one, so with several chats open they
 *  land where the owner last clicked. With one pane it is always the home chat, as before. */

import { useSyncExternalStore } from "react";

let focused = "main";
const listeners = new Set<() => void>();

export function focusedPane(): string {
  return focused;
}

export function focusPane(id: string): void {
  if (focused === id) return;
  focused = id;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useFocusedPane(): string {
  return useSyncExternalStore(subscribe, focusedPane);
}
