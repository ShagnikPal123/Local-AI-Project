/** Windows beside the chat (redesign 2026-10-10, docs/WINDOWS_IN_CHAT_PLAN.md).
 *
 * The owner folded Game Studio, the Second Brain and drawing into the chat, and wants screen sharing (and later the
 * office/world) "as a choice in there". So the chat can open a window beside itself — from the composer's + menu,
 * from an old tab link, or because Nyx called `ui_open_window`. Several can be open at once; they show as tabs in the
 * window's title bar. "Modular right off the bat" (owner): the pane docks Right, Left or Bottom, or fills the screen,
 * and its size is dragged or keyed (arrow keys on the divider). All of it is remembered.
 *
 * A window is a view of an engine that already exists — nothing here owns data.
 */

import { lazy, Suspense, useCallback, useEffect, useRef, useState, type ComponentType, type LazyExoticComponent } from "react";
import { HubContext } from "../Panel";
import "./windows.css";

export type WindowKind = "game" | "brain" | "screen" | "computer" | "office" | "world" | "court" | "file" | "email" | "whatsapp" | "graph";
export type Dock = "right" | "left" | "bottom" | "full";

interface KindDef { title: string; purpose: string; component: LazyExoticComponent<ComponentType<Record<string, unknown>>> }

const lazyNamed = (loader: () => Promise<Record<string, unknown>>, name: string) =>
  lazy(() => loader().then((m) => ({ default: m[name] as ComponentType<Record<string, unknown>> })));

export const WINDOW_KINDS: Record<WindowKind, KindDef> = {
  game: { title: "Game Studio", purpose: "Make and play games", component: lazyNamed(() => import("../../panels/game/GameStudioPanel"), "GameStudioPanel") },
  brain: { title: "Second Brain", purpose: "Everything Ichos remembers, as a field", component: lazyNamed(() => import("../../panels/NyxPanel"), "SecondBrainWindow") },
  screen: { title: "Screen Share", purpose: "Share a screen or window", component: lazyNamed(() => import("../../panels/screen/ScreenSharePanel"), "ScreenSharePanel") },
  computer: { title: "Ichos Computer", purpose: "Ichos's own sandboxed desktop", component: lazyNamed(() => import("../../panels/computer/OwnComputerPanel"), "OwnComputerPanel") },
  office: { title: "Office & World", purpose: "Your offices of agents and the worlds they grow", component: lazyNamed(() => import("../../panels/OfficeWorldPanel"), "OfficeWorldPanel") },
  world: { title: "World", purpose: "An office grown into a planet", component: lazyNamed(() => import("../../panels/world/WorldPanel"), "WorldPanel") },
  file: { title: "File", purpose: "A file Ichos read or wrote", component: lazyNamed(() => import("./WorkbenchWindows"), "FileWindow") },
  email: { title: "Mail", purpose: "Your inbox", component: lazyNamed(() => import("./WorkbenchWindows"), "EmailWindow") },
  whatsapp: { title: "WhatsApp", purpose: "Texts with your phone", component: lazyNamed(() => import("../../panels/connectors/WhatsAppLine"), "WhatsAppLine") },
  graph: { title: "Graph", purpose: "Functions you can zoom and pan", component: lazyNamed(() => import("./WorkbenchWindows"), "GraphWindow") },
  court: { title: "Court", purpose: "Agents argue your question before a judge", component: lazyNamed(() => import("../court/CourtWindow"), "CourtWindow") },
};

interface OpenWindow { id: string; kind: WindowKind; title: string; props?: Record<string, unknown> }

const STORE = "ichos.windows";
const load = (): { open: OpenWindow[]; active: string; dock: Dock; size: number } => {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE) || "null");
    if (raw && Array.isArray(raw.open)) {
      return {
        open: raw.open.filter((w: OpenWindow) => w && w.kind in WINDOW_KINDS),
        active: String(raw.active || ""),
        dock: (["right", "left", "bottom", "full"] as Dock[]).includes(raw.dock) ? raw.dock : "right",
        size: Number(raw.size) || 0.5,
      };
    }
  } catch { /* nothing kept */ }
  return { open: [], active: "", dock: "right", size: 0.5 };
};

/** Things that can be dragged onto the window pane (activity items, mail, files): what to open. */
export const DRAG_TYPE = "application/x-ichos-open";
export interface DragOpen { kind: WindowKind; title?: string; props?: Record<string, unknown> }
export function readDrag(e: React.DragEvent): DragOpen | null {
  try {
    const raw = e.dataTransfer.getData(DRAG_TYPE);
    const item = raw ? JSON.parse(raw) : null;
    return item && item.kind in WINDOW_KINDS ? item : null;
  } catch { return null; }
}

/** Open a window beside the chat from anywhere. */
export function openChatWindow(kind: WindowKind, title?: string, props?: Record<string, unknown>): void {
  window.dispatchEvent(new CustomEvent("ichos:open-window", { detail: { kind, title, props } }));
}

export function useChatWindows() {
  const initial = useRef(load());
  const [open, setOpen] = useState<OpenWindow[]>(initial.current.open);
  const [active, setActive] = useState(initial.current.active);
  const [dock, setDock] = useState<Dock>(initial.current.dock);
  const [size, setSize] = useState(Math.min(0.8, Math.max(0.25, initial.current.size)));

  useEffect(() => {
    try { localStorage.setItem(STORE, JSON.stringify({ open, active, dock, size })); } catch { /* not kept */ }
  }, [open, active, dock, size]);

  useEffect(() => {
    const onOpen = (event: Event) => {
      const detail = (event as CustomEvent<{ kind?: string; title?: string; props?: Record<string, unknown> }>).detail ?? {};
      const kind = detail.kind as WindowKind;
      if (!kind || !(kind in WINDOW_KINDS)) return;
      setOpen((current) => {
        // One window per kind unless it carries its own props (a court on a new question is a new window).
        const same = !detail.props ? current.find((w) => w.kind === kind) : undefined;
        if (same) { setActive(same.id); return current; }
        const next: OpenWindow = { id: `${kind}-${Date.now().toString(36)}`, kind, title: detail.title || WINDOW_KINDS[kind].title, props: detail.props };
        setActive(next.id);
        return [...current, next].slice(-6);
      });
    };
    window.addEventListener("ichos:open-window", onOpen);
    return () => window.removeEventListener("ichos:open-window", onOpen);
  }, []);

  const close = useCallback((id: string) => {
    setOpen((current) => {
      const next = current.filter((w) => w.id !== id);
      setActive((a) => (a === id ? next[next.length - 1]?.id ?? "" : a));
      return next;
    });
  }, []);

  return { open, active, setActive, dock, setDock, size, setSize, close };
}

type Windows = ReturnType<typeof useChatWindows>;

const DOCK_LABEL: Record<Dock, string> = { right: "Dock right", left: "Dock left", bottom: "Dock bottom", full: "Fill the screen" };

export function ChatWindowPane({ w, containerRef }: { w: Windows; containerRef: React.RefObject<HTMLDivElement | null> }) {
  const [menu, setMenu] = useState(false);
  const current = w.open.find((x) => x.id === w.active) ?? w.open[w.open.length - 1];
  if (!current) return null;
  const def = WINDOW_KINDS[current.kind];
  const Body = def.component;
  const vertical = w.dock === "bottom";

  const onGrip = (event: React.PointerEvent<HTMLDivElement>) => {
    const box = containerRef.current?.getBoundingClientRect();
    if (!box) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const move = (e: PointerEvent) => {
      let share: number;
      if (w.dock === "bottom") share = (box.bottom - e.clientY) / box.height;
      else if (w.dock === "left") share = (e.clientX - box.left) / box.width;
      else share = (box.right - e.clientX) / box.width;
      w.setSize(Math.min(0.8, Math.max(0.25, share)));
    };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <aside
      onDragOver={(e) => { if (e.dataTransfer.types.includes(DRAG_TYPE)) e.preventDefault(); }}
      onDrop={(e) => { const item = readDrag(e); if (item) { e.preventDefault(); openChatWindow(item.kind, item.title, item.props); } }}
      className={`chat-window is-${w.dock}`}
      style={w.dock === "full" ? undefined : { [vertical ? "height" : "width"]: `${Math.round(w.size * 100)}%` }}
      aria-label={`${current.title} window`}
    >
      {w.dock !== "full" && (
        <div
          className="chat-window__grip"
          role="separator"
          tabIndex={0}
          aria-orientation={vertical ? "horizontal" : "vertical"}
          aria-label="Window size — drag, or use the arrow keys"
          aria-valuemin={25}
          aria-valuemax={80}
          aria-valuenow={Math.round(w.size * 100)}
          onPointerDown={onGrip}
          onDoubleClick={() => w.setSize(0.5)}
          onKeyDown={(e) => {
            const grow = (w.dock === "right" && e.key === "ArrowLeft") || (w.dock === "left" && e.key === "ArrowRight") || (w.dock === "bottom" && e.key === "ArrowUp");
            const shrink = (w.dock === "right" && e.key === "ArrowRight") || (w.dock === "left" && e.key === "ArrowLeft") || (w.dock === "bottom" && e.key === "ArrowDown");
            const step = e.shiftKey ? 0.1 : 0.03;
            if (grow) { e.preventDefault(); w.setSize(Math.min(0.8, w.size + step)); }
            if (shrink) { e.preventDefault(); w.setSize(Math.max(0.25, w.size - step)); }
          }}
        />
      )}
      <header className="chat-window__bar">
        <div className="chat-window__tabs" role="tablist" aria-label="Open windows">
          {w.open.map((x) => (
            <span key={x.id} className="chat-window__tab" data-active={x.id === current.id || undefined}>
              <button type="button" role="tab" aria-selected={x.id === current.id} onClick={() => w.setActive(x.id)}>{x.title}</button>
              <button type="button" className="chat-window__tab-close" aria-label={`Close ${x.title}`} onClick={() => w.close(x.id)}>✕</button>
            </span>
          ))}
        </div>
        <div className="chat-window__tools">
          <div className="chat-window__menu-wrap">
            <button type="button" className="shell-icon-btn" aria-haspopup="menu" aria-expanded={menu} onClick={() => setMenu((v) => !v)} title="Move this window">
              <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.4"><rect x="1.5" y="2.5" width="13" height="11" rx="1.5" /><path d={w.dock === "bottom" ? "M1.5 9h13" : w.dock === "left" ? "M6 2.5v11" : "M10 2.5v11"} /></svg>
              Move
            </button>
            {menu && (
              <div className="chat-window__menu" role="menu" onMouseLeave={() => setMenu(false)}>
                {(Object.keys(DOCK_LABEL) as Dock[]).map((d) => (
                  <button key={d} type="button" role="menuitemradio" aria-checked={w.dock === d} onClick={() => { w.setDock(d); setMenu(false); }}>
                    {DOCK_LABEL[d]}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button type="button" className="shell-icon-btn" onClick={() => w.close(current.id)} aria-label={`Close ${current.title}`} title="Close this window">✕</button>
        </div>
      </header>
      <div className="chat-window__body">
        <HubContext.Provider value={true}>
          <Suspense fallback={<div className="tab-loading" role="status"><span className="tab-loading__dot" />Opening {current.title}…</div>}>
            <Body key={current.id} {...(current.props ?? {})} />
          </Suspense>
        </HubContext.Provider>
      </div>
    </aside>
  );
}
