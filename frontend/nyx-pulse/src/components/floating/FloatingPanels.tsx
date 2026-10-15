/** Panels that float anywhere on the screen (owner, 2026-10-15: "make sure it can be dragged anywhere on the screen but
 * mainly onto the right tab … the other parts can be drag able and move around the screen to where the user wishes").
 *
 * Any bar from the chat (context, usage limits, environment, connectors, remote access, team) can be pulled out:
 *   - drag its chip off the chat and let go anywhere: it becomes a small floating card right there;
 *   - drag the chip, or a floating card by its header, onto a tab: the card moves to that tab and shows there;
 *   - "Dock" on the card (or its ⋮) puts it back under the chat box.
 * Where each card sits and on which tab is remembered in this browser. Connectors and remote access look after their
 * own data, so they float on any tab; the bars that show the open chat (context, usage, environment, team) live on the
 * chat tab, since that is where their chat is.
 */

import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { ITEM_DROPPED_EVENT, type DragItem } from "../../state/dragItems";
import { pushToast } from "../../state/toastStore";
import "./floating.css";

export type FloatId = "context" | "usage" | "environment" | "connectors" | "remote" | "team";
export interface FloatSpot { x: number; y: number; tab: string }
export type Floats = Partial<Record<FloatId, FloatSpot>>;

/** Bars whose content needs the open chat; they only show on the chat tab. */
export const CHAT_BOUND: FloatId[] = ["context", "usage", "environment", "team"];
export const CHAT_TAB = "nyx";
const KEY = "ichos.float.v1";
const EVENT = "ichos:floats";
const IDS: FloatId[] = ["context", "usage", "environment", "connectors", "remote", "team"];

export function readFloats(): Floats {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "{}") as Record<string, Partial<FloatSpot>>;
    const out: Floats = {};
    for (const id of IDS) {
      const spot = raw[id];
      if (spot && Number.isFinite(spot.x) && Number.isFinite(spot.y)) {
        out[id] = { x: Number(spot.x), y: Number(spot.y), tab: typeof spot.tab === "string" && spot.tab ? spot.tab : CHAT_TAB };
      }
    }
    return out;
  } catch { return {}; }
}

function writeFloats(next: Floats): void {
  try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* private window: not kept */ }
  window.dispatchEvent(new Event(EVENT));
}

/** Keep a card on screen: at least its header stays reachable. */
export function clampSpot(x: number, y: number, w = 300, h = 40): { x: number; y: number } {
  const vw = typeof window === "undefined" ? 1280 : window.innerWidth;
  const vh = typeof window === "undefined" ? 800 : window.innerHeight;
  return { x: Math.round(Math.min(Math.max(8, x), Math.max(8, vw - w - 8))), y: Math.round(Math.min(Math.max(8, y), Math.max(8, vh - h - 8))) };
}

export function floatPanel(id: FloatId, x: number, y: number, tab: string): void {
  const tabFor = CHAT_BOUND.includes(id) ? CHAT_TAB : tab || CHAT_TAB;
  writeFloats({ ...readFloats(), [id]: { ...clampSpot(x, y), tab: tabFor } });
}

export function dockPanel(id: FloatId): void {
  const next = readFloats();
  delete next[id];
  writeFloats(next);
  window.dispatchEvent(new CustomEvent("ichos:dock-bar", { detail: { id } }));
}

export function useFloats(): Floats {
  const [floats, setFloats] = useState<Floats>(readFloats);
  useEffect(() => {
    const on = () => setFloats(readFloats());
    window.addEventListener(EVENT, on);
    const onStorage = (e: StorageEvent) => { if (e.key === KEY) on(); };
    window.addEventListener("storage", onStorage);
    return () => { window.removeEventListener(EVENT, on); window.removeEventListener("storage", onStorage); };
  }, []);
  return floats;
}

/** A bar chip let go on a tab: the tab opens (App does that) and the bar floats there, at the right-hand side. */
let listening = false;
export function listenForTabDrops(): void {
  if (listening) return;
  listening = true;
  window.addEventListener(ITEM_DROPPED_EVENT, (event) => {
    const { item, tab } = (event as CustomEvent<{ item: DragItem; tab: string }>).detail ?? {};
    if (!item || !item.id.startsWith("bar:") || !tab || tab === "+new") return;
    const id = item.id.slice(4) as FloatId;
    if (!IDS.includes(id)) return;
    const spot = readFloats()[id];
    floatPanel(id, spot?.x ?? window.innerWidth - 340, spot?.y ?? 96, tab);
  });
}

/** The floating card. Drag it by its header; let go over a tab to send it there. */
const SIZE_KEY = "ichos.float.size.";

function readSize(id: string): { w: number; h: number } | null {
  try {
    const v = JSON.parse(localStorage.getItem(SIZE_KEY + id) || "null");
    return v && v.w > 0 && v.h > 0 ? v : null;
  } catch { return null; }
}

export function FloatingCard({ id, label, spot, children }: { id: FloatId; label: string; spot: FloatSpot; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: spot.x, y: spot.y });
  const [tabUnder, setTabUnder] = useState<string | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(() => readSize(id));
  useEffect(() => setPos({ x: spot.x, y: spot.y }), [spot.x, spot.y]);
  // Keep it on screen when the window shrinks.
  useEffect(() => {
    const fit = () => setPos((p) => clampSpot(p.x, p.y, ref.current?.offsetWidth, 40));
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }, []);

  const startDrag = (e: ReactPointerEvent<HTMLElement>) => {
    if (e.button !== 0 || (e.target as HTMLElement).closest("button")) return;
    e.preventDefault();
    const dx = e.clientX - pos.x, dy = e.clientY - pos.y;
    const el = ref.current;
    const tabAt = (x: number, y: number) => {
      if (el) el.style.pointerEvents = "none";
      const hit = (document.elementFromPoint(x, y) as HTMLElement | null)?.closest("[data-tab-id]") as HTMLElement | null;
      if (el) el.style.pointerEvents = "";
      return hit?.dataset.tabId ?? null;
    };
    const move = (ev: PointerEvent) => {
      setPos(clampSpot(ev.clientX - dx, ev.clientY - dy, el?.offsetWidth, 40));
      setTabUnder(tabAt(ev.clientX, ev.clientY));
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      const tab = tabAt(ev.clientX, ev.clientY);
      setTabUnder(null);
      if (tab && tab !== "+new" && tab !== spot.tab) {
        if (CHAT_BOUND.includes(id) && tab !== CHAT_TAB) {
          // These show the open chat, so they stay on the chat tab; put the card back where it was.
          setPos({ x: spot.x, y: spot.y });
          pushToast(`${label} shows the open chat, so it stays on the chat tab.`, "info");
          return;
        }
        floatPanel(id, window.innerWidth - (el?.offsetWidth ?? 300) - 24, 96, tab);
        window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab } }));
        return;
      }
      floatPanel(id, ev.clientX - dx, ev.clientY - dy, spot.tab);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // The corner grip makes the card bigger or smaller; the size is kept per panel.
  const startResize = (e: ReactPointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    let last = { w: r.width, h: r.height };
    const move = (ev: PointerEvent) => {
      last = { w: Math.round(Math.max(220, Math.min(ev.clientX - r.left, window.innerWidth - r.left - 8))),
        h: Math.round(Math.max(120, Math.min(ev.clientY - r.top, window.innerHeight - r.top - 8))) };
      setSize(last);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      try { localStorage.setItem(SIZE_KEY + id, JSON.stringify(last)); } catch { /* not kept */ }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <div ref={ref} className={`float-card is-${id}${tabUnder ? " is-over-tab" : ""}${size ? " is-sized" : ""}`} role="dialog" aria-label={label}
      style={{ left: pos.x, top: pos.y, width: size?.w, height: size?.h }}>
      <header className="float-card__head" onPointerDown={startDrag} title="Drag to move · let go on a tab to send it there">
        <span className="float-card__grip" aria-hidden="true">⠿</span>
        <span className="float-card__title">{label}</span>
        {tabUnder && <span className="float-card__hint">to this tab</span>}
        <button type="button" className="float-card__btn" onClick={() => dockPanel(id)} title="Put it back under the chat box">Dock</button>
      </header>
      <div className="float-card__body">{children}</div>
      <span className="float-card__resize" onPointerDown={startResize} title="Drag to resize" aria-hidden="true" />
    </div>
  );
}
