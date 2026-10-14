/** One shared way to say "this thing is being dragged" (S23: drag an avatar, a chat or the assistant onto a tab).
 *
 * Tabs and the + button read this to learn what was dropped, then tell the AI so it knows what the owner wants. Chats and
 * agents were already draggable with their own formats (chat panes, the agent boxes); `readItemDrag` understands those too,
 * so nothing that already drags has to change.
 */

import { CHAT_DRAG } from "../components/chat/panes/paneDrag";

export const ITEM_DRAG = "application/x-ichos-item";

export type DragItemKind = "avatar" | "chat" | "assistant" | "agent" | "calendar" | "item";
export interface DragItem { kind: DragItemKind; id: string; label: string }

type AnyDrag = { dataTransfer: DataTransfer | null };

export function startItemDrag(event: AnyDrag, item: DragItem): void {
  const dt = event.dataTransfer;
  if (!dt) return;
  dt.setData(ITEM_DRAG, JSON.stringify(item));
  dt.setData("text/plain", item.label);
  dt.effectAllowed = "copyMove";
}

/** True while something we know how to drop is over the window (the payload itself is unreadable until the drop). */
export function hasItemDrag(event: AnyDrag): boolean {
  const types = Array.from(event.dataTransfer?.types ?? []);
  return types.includes(ITEM_DRAG) || types.includes(CHAT_DRAG) || types.includes("application/x-nyx-agent") || types.includes("application/x-ichos-agent");
}

export function readItemDrag(event: AnyDrag): DragItem | null {
  const dt = event.dataTransfer;
  if (!dt) return null;
  try {
    const own = dt.getData(ITEM_DRAG);
    if (own) {
      const item = JSON.parse(own) as Partial<DragItem>;
      if (item.id && item.kind) return { kind: item.kind, id: String(item.id), label: String(item.label || item.id) };
    }
    const chat = dt.getData(CHAT_DRAG);
    if (chat) {
      const { chatId, title } = JSON.parse(chat) as { chatId?: string; title?: string };
      if (chatId) return { kind: "chat", id: chatId, label: title || "a chat" };
    }
    const agent = dt.getData("application/x-nyx-agent") || dt.getData("application/x-ichos-agent");
    if (agent) return { kind: "agent", id: agent, label: agent };
  } catch { /* a payload we cannot read is not ours */ }
  return null;
}

/** Fired on `window` after a drop on a tab: `{ item, tab }`. Anything that wants to react (the chat, a panel) listens. */
export const ITEM_DROPPED_EVENT = "ichos:item-dropped";
