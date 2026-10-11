/** Several chats on one screen (owner, 2026-10-10): drag a chat from the list — or a pane by its grip — onto any
 *  pane's left, right, top or bottom edge to split it that way, onto its middle to swap or replace, or onto the outer
 *  edges to give it a full-height column or full-width row. Dividers drag to resize (arrow keys too); the layout is
 *  remembered. The home chat (with the chat list) is one of the panes and can move but not close. */

import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type DragEvent, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";
import { api } from "../../../api";
import { pushToast } from "../../../state/toastStore";
import { ChatPanel } from "../../../panels/ChatPanel";
import {
  MAIN, MAX_PANES, SINGLE, edgeAt, evenOut, insertAt, layout, leaves, moveLeaf, newId, removeLeaf, resize, setChat, validate,
  type Edge, type PaneNode, type PlacedDivider,
} from "./paneLayout";
import { focusPane, useFocusedPane } from "./paneFocus";
import { CHAT_DRAG, OPEN_PANE_EVENT, PANE_DRAG } from "./paneDrag";
import "./panes.css";

const KEY = "ichos.chatPanes.v1";

function load(): PaneNode {
  try {
    return validate(JSON.parse(localStorage.getItem(KEY) || "null")) ?? SINGLE;
  } catch {
    return SINGLE;
  }
}

const ours = (event: DragEvent) => event.dataTransfer.types.includes(CHAT_DRAG) || event.dataTransfer.types.includes(PANE_DRAG);

const EDGE_WORDS: Record<Edge, string> = { left: "Left", right: "Right", top: "Above", bottom: "Below", center: "Here" };

export function ChatPanes({ renderMain, provider, onProvider }: {
  /** The home chat, given its header controls (grip and split buttons) and where to report the chat it is on. */
  renderMain: (headExtra: ReactNode, onChatChange: (chatId: string) => void) => ReactNode;
  provider: string;
  onProvider: (provider: string) => void;
}) {
  const [tree, setTree] = useState<PaneNode>(load);
  const [dragging, setDragging] = useState(false);
  const [hover, setHover] = useState<{ target: string; edge: Edge } | null>(null);
  const [mainChat, setMainChat] = useState("");
  const area = useRef<HTMLDivElement>(null);
  const focused = useFocusedPane();

  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(tree)); } catch { /* not kept */ } }, [tree]);
  const placed = useMemo(() => layout(tree), [tree]);
  const count = placed.leaves.length;
  // A closed pane can't stay the one that takes the microphone.
  useEffect(() => { if (!placed.leaves.some((l) => l.id === focused)) focusPane(MAIN); }, [placed, focused]);

  const full = () => {
    if (count < MAX_PANES) return false;
    pushToast(`Up to ${MAX_PANES} chats fit on one screen — close one first.`, "info");
    return true;
  };

  /** Open a chat (a new one when `chatId` is empty) against an edge of `target`. */
  const openChat = useCallback(async (chatId: string, target: string, edge: Edge) => {
    const current = leaves(tree);
    const already = current.find((l) => l.chatId === chatId && chatId);
    if (already) { setTree((t) => moveLeaf(t, already.id, target, edge)); focusPane(already.id); return; }
    if (chatId && chatId === mainChat) { pushToast("That chat is already open here.", "info"); return; }
    if (edge === "center") {
      if (target === MAIN) window.dispatchEvent(new CustomEvent("nyx:open-chat", { detail: { chatId } }));
      else setTree((t) => setChat(t, target, chatId));
      focusPane(target);
      return;
    }
    if (full()) return;
    let id = chatId;
    if (!id) {
      const made = await api.post<{ chat: { id: string } }>("/api/chats", { title: "" });
      if (!made.ok) { pushToast(made.error, "warn"); return; }
      id = made.data.chat.id;
    }
    const leaf = { kind: "leaf" as const, id: newId("p"), chatId: id };
    setTree((t) => insertAt(t, target, edge, leaf));
    focusPane(leaf.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tree, mainChat, count]);

  // "Open beside" from the chat list's menu, or anywhere else in the app.
  useEffect(() => {
    const onOpen = (event: Event) => {
      const detail = (event as CustomEvent<{ chatId?: string; edge?: Edge }>).detail ?? {};
      void openChat(detail.chatId ?? "", focused, detail.edge ?? "right");
    };
    window.addEventListener(OPEN_PANE_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_PANE_EVENT, onOpen);
  }, [openChat, focused]);

  // Any drag ending (dropped anywhere, or cancelled with Esc) takes the drop targets away.
  useEffect(() => {
    if (!dragging) return;
    const end = () => { setDragging(false); setHover(null); };
    window.addEventListener("dragend", end);
    window.addEventListener("drop", end);
    return () => { window.removeEventListener("dragend", end); window.removeEventListener("drop", end); };
  }, [dragging]);

  const drop = (event: DragEvent, target: string, edge: Edge) => {
    event.preventDefault();
    setDragging(false);
    setHover(null);
    const pane = event.dataTransfer.getData(PANE_DRAG);
    if (pane) { setTree((t) => moveLeaf(t, pane, target, edge)); focusPane(pane); return; }
    try {
      const chat = JSON.parse(event.dataTransfer.getData(CHAT_DRAG) || "{}") as { chatId?: string };
      if (chat.chatId) void openChat(chat.chatId, target, edge);
    } catch { /* not ours */ }
  };

  const controls = (id: string, title = "") => {
    const grip = (
      <button type="button" className="cp-grip" draggable title="Drag to move this chat · Alt+arrow sends it to that side"
        aria-label={`Move ${title || "this chat"}: drag, or Alt+arrow keys`}
        onDragStart={(e) => { e.dataTransfer.setData(PANE_DRAG, id); e.dataTransfer.effectAllowed = "move"; }}
        onKeyDown={(e) => {
          const edge = ({ ArrowLeft: "left", ArrowRight: "right", ArrowUp: "top", ArrowDown: "bottom" } as Record<string, Edge>)[e.key];
          if (!edge || !e.altKey || count < 2) return;
          e.preventDefault();
          setTree((t) => moveLeaf(t, id, t.id, edge));
        }}>
        <svg width="10" height="16" viewBox="0 0 10 16" aria-hidden="true">
          {[3, 8, 13].flatMap((y) => [2, 8].map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.4" />))}
        </svg>
      </button>
    );
    const splits = (
      <span className="cp-splits">
        <button type="button" className="cp-icon" title="New chat to the right" aria-label="New chat to the right" onClick={() => void openChat("", id, "right")}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="2" /><path d="M9 2.5v11" /></svg>
        </button>
        <button type="button" className="cp-icon" title="New chat below" aria-label="New chat below" onClick={() => void openChat("", id, "bottom")}>
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="2" /><path d="M1.5 8.5h13" /></svg>
        </button>
        {count > 2 && (
          <button type="button" className="cp-icon" title="Even out the sizes" aria-label="Even out the sizes" onClick={() => setTree((t) => evenOut(t))}>
            <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="2.5" width="13" height="11" rx="2" /><path d="M6 2.5v11M10.5 2.5v11" /></svg>
          </button>
        )}
      </span>
    );
    return { grip, splits };
  };

  const main = controls(MAIN);
  const mainHead = (
    <span className="cp-head">
      {count > 1 && main.grip}
      {main.splits}
    </span>
  );

  return (
    <div ref={area} className={`cp-area${dragging ? " is-dragging" : ""}${count > 1 ? " is-split" : ""}`}
      onDragEnterCapture={(e) => { if (ours(e)) setDragging(true); }}>
      {placed.leaves.map((leaf) => {
        const style: CSSProperties = { left: `${leaf.x}%`, top: `${leaf.y}%`, width: `${leaf.w}%`, height: `${leaf.h}%` };
        const isMain = leaf.id === MAIN;
        const c = isMain ? null : controls(leaf.id);
        return (
          <div key={leaf.id} className={`cp-pane${count > 1 && focused === leaf.id ? " is-focused" : ""}`} style={style}
            data-chat-pane={leaf.id} onPointerDownCapture={() => focusPane(leaf.id)} onFocusCapture={() => focusPane(leaf.id)}>
            <div className="cp-pane__body">
              {isMain ? renderMain(mainHead, setMainChat) : (
                <ChatPanel variant="pane" paneKey={leaf.id} paneChatId={leaf.chatId} provider={provider} onProvider={onProvider}
                  onChatChange={(chatId) => setTree((t) => setChat(t, leaf.id, chatId))}
                  paneBar={{
                    start: c?.grip,
                    end: <>{c?.splits}<button type="button" className="cp-icon cp-close" title="Close this chat (it stays in the list)"
                      aria-label="Close this pane" onClick={() => setTree((t) => removeLeaf(t, leaf.id))}>
                      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M3 3l8 8M11 3l-8 8" /></svg>
                    </button></>,
                  }} />
              )}
            </div>
            {dragging && (
              <div className="cp-drop"
                onDragOver={(e) => { e.preventDefault(); const r = e.currentTarget.getBoundingClientRect(); const edge = edgeAt(e.clientX, e.clientY, r);
                  if (hover?.target !== leaf.id || hover.edge !== edge) setHover({ target: leaf.id, edge }); }}
                onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setHover((h) => (h?.target === leaf.id ? null : h)); }}
                onDrop={(e) => drop(e, leaf.id, edgeAt(e.clientX, e.clientY, e.currentTarget.getBoundingClientRect()))}>
                {hover?.target === leaf.id && <div className={`cp-preview is-${hover.edge}`}><span>{EDGE_WORDS[hover.edge]}</span></div>}
              </div>
            )}
          </div>
        );
      })}

      {placed.dividers.map((d) => <Divider key={`${d.splitId}-${d.index}`} d={d} area={area}
        onResize={(delta) => setTree((t) => resize(t, d.splitId, d.index, delta))} />)}

      {/* The outer edges: a full-height column or a full-width row. */}
      {dragging && (["left", "right", "top", "bottom"] as Edge[]).map((edge) => (
        <div key={edge} className={`cp-outer is-${edge}${hover?.target === "__root" && hover.edge === edge ? " is-hot" : ""}`}
          onDragOver={(e) => { e.preventDefault(); if (hover?.target !== "__root" || hover.edge !== edge) setHover({ target: "__root", edge }); }}
          onDrop={(e) => drop(e, tree.id, edge)} title={`Whole ${edge} side`} />
      ))}
    </div>
  );
}

function Divider({ d, area, onResize }: { d: PlacedDivider; area: RefObject<HTMLDivElement | null>; onResize: (delta: number) => void }) {
  const row = d.dir === "row";
  const style: CSSProperties = row
    ? { left: `${d.x}%`, top: `${d.y}%`, height: `${d.h}%` }
    : { left: `${d.x}%`, top: `${d.y}%`, width: `${d.w}%` };
  const begin = (event: ReactPointerEvent) => {
    const box = area.current?.getBoundingClientRect();
    if (!box) return;
    event.preventDefault();
    const handle = event.currentTarget as HTMLElement;
    handle.setPointerCapture(event.pointerId);
    // The split's own length on screen, in pixels: a pixel moved is that share of it.
    const length = ((row ? box.width : box.height) * d.span) / 100;
    let last = row ? event.clientX : event.clientY;
    const move = (e: PointerEvent) => {
      const now = row ? e.clientX : e.clientY;
      if (now === last) return;
      onResize(((now - last) / Math.max(1, length)) * 100);
      last = now;
    };
    const up = () => { handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); document.body.classList.remove("cp-resizing"); };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    document.body.classList.add("cp-resizing", row ? "cp-resizing--row" : "cp-resizing--col");
    handle.addEventListener("lostpointercapture", () => document.body.classList.remove("cp-resizing", "cp-resizing--row", "cp-resizing--col"), { once: true });
  };
  return (
    <div className={`cp-divider is-${d.dir}`} style={style} role="separator" tabIndex={0}
      aria-orientation={row ? "vertical" : "horizontal"} aria-label="Drag to resize; arrow keys work too"
      onPointerDown={begin}
      onKeyDown={(e) => {
        const step = e.shiftKey ? 10 : 3;
        const delta = row ? ({ ArrowLeft: -step, ArrowRight: step } as Record<string, number>)[e.key]
          : ({ ArrowUp: -step, ArrowDown: step } as Record<string, number>)[e.key];
        if (delta) { e.preventDefault(); onResize(delta); }
      }} />
  );
}
