/** Drag behaviour shared by the tab strip and the studio rail: reorder tabs, and drop things onto them.
 *
 * Two kinds of drag meet here. A tab dragged onto another tab moves it (dropped on the near half it goes before, the far
 * half after). Anything else the app knows how to drag (a chat, an avatar, the assistant: state/dragItems.ts) dropped on a
 * tab opens that tab and tells the AI what was dropped, so it can help with it there.
 */

import { useCallback, useState, type DragEvent } from "react";
import { hasItemDrag, readItemDrag, type DragItem } from "../state/dragItems";

const TAB_DRAG = "application/x-ichos-tab";

interface Options {
  /** True when tabs run left to right (the strip); false when they stack (the rail, a side bar). */
  horizontal: boolean;
  onReorder: (dragged: string, over: string, after: boolean) => void;
  onDropItem: (tabId: string, item: DragItem) => void;
}

export function useTabDnd({ horizontal, onReorder, onDropItem }: Options) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<{ id: string; after: boolean } | null>(null);
  const [target, setTarget] = useState<string | null>(null);

  const clear = useCallback(() => { setDragging(null); setOver(null); setTarget(null); }, []);

  const props = useCallback((id: string) => ({
    draggable: true,
    onDragStart: (event: DragEvent<HTMLElement>) => {
      event.dataTransfer.setData(TAB_DRAG, id);
      event.dataTransfer.setData("text/plain", id);
      event.dataTransfer.effectAllowed = "move";
      setDragging(id);
    },
    onDragEnd: clear,
    onDragOver: (event: DragEvent<HTMLElement>) => {
      const types = Array.from(event.dataTransfer.types);
      if (types.includes(TAB_DRAG)) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        const box = event.currentTarget.getBoundingClientRect();
        const after = horizontal ? event.clientX > box.left + box.width / 2 : event.clientY > box.top + box.height / 2;
        setOver((now) => (now && now.id === id && now.after === after ? now : { id, after }));
      } else if (hasItemDrag(event)) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        setTarget(id);
      }
    },
    onDragLeave: () => { setOver((now) => (now?.id === id ? null : now)); setTarget((now) => (now === id ? null : now)); },
    onDrop: (event: DragEvent<HTMLElement>) => {
      const moved = event.dataTransfer.getData(TAB_DRAG);
      if (moved) {
        event.preventDefault();
        const box = event.currentTarget.getBoundingClientRect();
        const after = horizontal ? event.clientX > box.left + box.width / 2 : event.clientY > box.top + box.height / 2;
        onReorder(moved, id, after);
      } else {
        const item = readItemDrag(event);
        if (item) { event.preventDefault(); onDropItem(id, item); }
      }
      clear();
    },
  }), [clear, horizontal, onDropItem, onReorder]);

  /** Extra class names for a tab while a drag is in progress: where it would land, or that it can take a drop. */
  const marks = useCallback((id: string) => [
    dragging === id ? "is-dragging" : "",
    over?.id === id ? (over.after ? "is-drop-after" : "is-drop-before") : "",
    target === id ? "is-drop-target" : "",
  ].filter(Boolean).join(" "), [dragging, over, target]);

  return { props, marks };
}
