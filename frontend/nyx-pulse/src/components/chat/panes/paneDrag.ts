/** How the rest of the app hands a chat to the pane layout (ChatPanes.tsx), without importing it. */

import type { DragEvent } from "react";
import type { Edge } from "./paneLayout";

/** What a dragged chat row carries: `{ chatId, title }`. */
export const CHAT_DRAG = "application/x-ichos-chat";
export const PANE_DRAG = "application/x-ichos-pane";
/** Ask for a chat beside the one in use: `{ chatId, edge? }` (an empty chatId opens a new chat). */
export const OPEN_PANE_EVENT = "ichos:open-chat-pane";

export function startChatDrag(event: DragEvent, chatId: string, title: string): void {
  event.dataTransfer.setData(CHAT_DRAG, JSON.stringify({ chatId, title }));
  event.dataTransfer.setData("text/plain", title);
  event.dataTransfer.effectAllowed = "copyMove";
}

export function openChatPane(chatId: string, edge: Edge = "right"): void {
  window.dispatchEvent(new CustomEvent(OPEN_PANE_EVENT, { detail: { chatId, edge } }));
}
