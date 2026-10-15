/** Movable bars for the compact chat (owner, 2026-10-15: "each separated bar like context, remote access, connectors,
 *  environments can be moved so I like how it feels and looks").
 *
 *  Every bar is a small chip that lives in one of two places, the strip under the chat's name ("top") or the row under
 *  the chat box ("bottom"), or is hidden. Drag a chip to the other place or between chips to reorder; the ⋮ on a chip
 *  does the same from the keyboard. Inline chips (the context and usage lines) show their bar directly; the rest show a
 *  one-line summary and open their full bar in a small pop-over. Where the owner put each bar is remembered.
 *
 *  This file only arranges bars; what each bar shows is passed in by the chat, so a bar keeps its own data and code. */

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ITEM_DRAG } from "../../../state/dragItems";
import { CHAT_TAB, floatPanel, useFloats } from "../../floating/FloatingPanels";

export type BarId = "context" | "usage" | "environment" | "connectors" | "remote" | "team";
export type Zone = "top" | "bottom" | "hidden";
export type BarLayout = Record<Zone, BarId[]>;

export interface BarSpec {
  label: string;
  /** Shown on the chip itself. For an inline bar this is the bar. */
  summary: ReactNode;
  /** The full bar, in a pop-over when the chip is clicked. Leave out for inline bars. */
  body?: ReactNode;
}

const ALL: BarId[] = ["context", "usage", "environment", "connectors", "remote", "team"];
const KEY = "nyx.chat.bars.v1";
const DRAG = "application/x-nyx-bar";
export const DEFAULT_LAYOUT: BarLayout = { top: ["context", "usage"], bottom: ["environment", "connectors", "remote", "team"], hidden: [] };

/** A saved layout, repaired: unknown ids dropped, new bars added to their default place, nothing listed twice. */
export function cleanLayout(raw: unknown): BarLayout {
  const out: BarLayout = { top: [], bottom: [], hidden: [] };
  const seen = new Set<BarId>();
  const src = (raw && typeof raw === "object" ? raw : {}) as Partial<Record<Zone, unknown>>;
  (["top", "bottom", "hidden"] as Zone[]).forEach((zone) => {
    const list = Array.isArray(src[zone]) ? (src[zone] as unknown[]) : [];
    list.forEach((id) => {
      if (typeof id === "string" && (ALL as string[]).includes(id) && !seen.has(id as BarId)) {
        seen.add(id as BarId);
        out[zone].push(id as BarId);
      }
    });
  });
  ALL.forEach((id) => {
    if (seen.has(id)) return;
    const zone = (["top", "bottom", "hidden"] as Zone[]).find((z) => DEFAULT_LAYOUT[z].includes(id)) ?? "bottom";
    out[zone].push(id);
  });
  return out;
}

/** Move ``id`` into ``zone``, before ``before`` when given (else at the end). */
export function moveBar(layout: BarLayout, id: BarId, zone: Zone, before?: BarId): BarLayout {
  const next: BarLayout = { top: layout.top.filter((x) => x !== id), bottom: layout.bottom.filter((x) => x !== id),
    hidden: layout.hidden.filter((x) => x !== id) };
  const at = before && before !== id ? next[zone].indexOf(before) : -1;
  if (at >= 0) next[zone].splice(at, 0, id); else next[zone].push(id);
  return next;
}

export function useBarLayout(): [BarLayout, (next: BarLayout) => void] {
  const [layout, setLayout] = useState<BarLayout>(() => {
    try { return cleanLayout(JSON.parse(localStorage.getItem(KEY) || "null")); } catch { return cleanLayout(null); }
  });
  const save = (next: BarLayout) => {
    setLayout(next);
    try { localStorage.setItem(KEY, JSON.stringify(next)); } catch { /* private window: not kept */ }
  };
  // Another chat pane (or window) moved a bar: follow it.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === KEY) { try { setLayout(cleanLayout(JSON.parse(e.newValue || "null"))); } catch { /* ignore */ } }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  return [layout, save];
}

function Chip({ id, spec, zone, layout, onLayout }: {
  id: BarId; spec: BarSpec; zone: Zone; layout: BarLayout; onLayout: (next: BarLayout) => void;
}) {
  const [open, setOpen] = useState(false);
  const [menu, setMenu] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const summaryRef = useRef<HTMLSpanElement>(null);
  // An inline bar with nothing to say (no limits reported yet, a chat with no context yet) takes no room at all.
  const [blank, setBlank] = useState(false);
  useEffect(() => {
    const el = summaryRef.current;
    if (spec.body || !el) return;
    const check = () => setBlank(!(el.textContent || "").trim());
    check();
    const watch = new MutationObserver(check);
    watch.observe(el, { childList: true, subtree: true, characterData: true });
    return () => watch.disconnect();
  }, [spec.body]);
  useEffect(() => {
    if (!open && !menu) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) { setOpen(false); setMenu(false); } };
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open, menu]);
  const go = (to: Zone) => { setMenu(false); onLayout(moveBar(layout, id, to)); };
  return (
    <div ref={ref} className={`cb-chip is-${id}${spec.body ? "" : " is-inline"}${blank ? " is-blank" : ""}`} draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(DRAG, id);
        // Also a droppable item, so a tab takes it: the bar then floats on that tab (FloatingPanels.tsx).
        e.dataTransfer.setData(ITEM_DRAG, JSON.stringify({ kind: "item", id: `bar:${id}`, label: spec.label }));
        e.dataTransfer.effectAllowed = "copyMove";
      }}
      onDragEnd={(e) => {
        // Let go anywhere that is not a bar place or a tab: it floats right there.
        if (e.dataTransfer.dropEffect === "none" && (e.clientX || e.clientY)) floatPanel(id, e.clientX - 24, e.clientY - 16, CHAT_TAB);
      }}
      onDragOver={(e) => { if (e.dataTransfer.types.includes(DRAG)) e.preventDefault(); }}
      onDrop={(e) => {
        const dragged = e.dataTransfer.getData(DRAG) as BarId;
        if (!dragged) return;
        e.preventDefault(); e.stopPropagation();
        onLayout(moveBar(layout, dragged, zone, id));
      }}>
      <span className="cb-grip" aria-hidden="true" title="Drag to move">⠿</span>
      {spec.body ? (
        <button type="button" className="cb-summary" aria-expanded={open} onClick={() => setOpen((v) => !v)} title={spec.label}>
          {spec.summary}
        </button>
      ) : <span ref={summaryRef} className="cb-summary" title={spec.label}>{spec.summary}</span>}
      <button type="button" className="cb-more" aria-haspopup="menu" aria-expanded={menu} aria-label={`Move the ${spec.label} bar`}
        onClick={() => setMenu((v) => !v)}>⋮</button>
      {menu && (
        <span role="menu" className={`cb-menu is-${zone}`}>
          {zone !== "top" && <button role="menuitem" type="button" onClick={() => go("top")}>Move to the top</button>}
          {zone !== "bottom" && <button role="menuitem" type="button" onClick={() => go("bottom")}>Move under the chat box</button>}
          <button role="menuitem" type="button" onClick={() => {
            setMenu(false);
            const box = ref.current?.getBoundingClientRect();
            floatPanel(id, (box?.left ?? 200), Math.max(60, (box?.top ?? 300) - 220), CHAT_TAB);
          }}>Float on the screen</button>
          <button role="menuitem" type="button" onClick={() => go("hidden")}>Hide</button>
        </span>
      )}
      {open && spec.body && <div className={`cb-pop is-${zone}`} role="dialog" aria-label={spec.label}>{spec.body}</div>}
    </div>
  );
}

/** One place the bars can live. Empty zones still take a drop while a bar is being dragged. */
export function BarZone({ zone, layout, onLayout, bars, extra }: {
  zone: Exclude<Zone, "hidden">; layout: BarLayout; onLayout: (next: BarLayout) => void;
  bars: Record<BarId, BarSpec | null>; extra?: ReactNode;
}) {
  const [hiddenOpen, setHiddenOpen] = useState(false);
  const floats = useFloats();  // a bar pulled out onto the screen is not shown in its zone until it is docked
  const ids = layout[zone].filter((id) => bars[id] && !floats[id]);
  const hidden = layout.hidden.filter((id) => bars[id]);
  return (
    <div className={`cb-zone is-${zone}`} aria-label={zone === "top" ? "Bars at the top" : "Bars under the chat box"}
      onDragOver={(e) => { if (e.dataTransfer.types.includes(DRAG)) e.preventDefault(); }}
      onDrop={(e) => {
        const dragged = e.dataTransfer.getData(DRAG) as BarId;
        if (dragged) { e.preventDefault(); onLayout(moveBar(layout, dragged, zone)); }
      }}>
      {extra}
      {ids.map((id) => <Chip key={id} id={id} spec={bars[id] as BarSpec} zone={zone} layout={layout} onLayout={onLayout} />)}
      {zone === "top" && hidden.length > 0 && (
        <span className="cb-hidden">
          <button type="button" className="cb-hidden__btn" aria-expanded={hiddenOpen} onClick={() => setHiddenOpen((v) => !v)}
            title="Bars you hid">+{hidden.length}</button>
          {hiddenOpen && (
            <span role="menu" className="cb-menu is-top">
              {hidden.map((id) => (
                <button key={id} role="menuitem" type="button" onClick={() => { setHiddenOpen(false); onLayout(moveBar(layout, id, "top")); }}>
                  Show {bars[id]?.label}
                </button>
              ))}
            </span>
          )}
        </span>
      )}
    </div>
  );
}
