/** Studio Glass: the floating icon rail on the left (owner, 2026-10-10 — the glassy dashboard reference).
 *
 * Replaces the top tab strip while the "studio" style is on. Every tab keeps its name as a tooltip and an accessible
 * label, the active one is the orange tile, and the rail scrolls rather than hiding tabs. Settings and the theme mix sit
 * at the foot, like the reference's light/dark pill.
 */

import { useRef, useState, type FocusEvent, type MouseEvent } from "react";
import type { TabDef } from "../../tabs";
import type { TabSpec } from "../../panels/DynamicTab";
import { NyxAvatar, type AvatarState } from "../NyxAvatar";

// Lucide-style strokes (24 grid). Tabs without their own glyph get the first letter of their name.
const GLYPHS: Record<string, string> = {
  nyx: "M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 1 1 21 11.5z",
  build: "M21 16V8l-9-5-9 5v8l9 5 9-5zM3.3 7.6 12 12.6l8.7-5M12 22V12.6",
  research: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5",
  learn: "M22 10 12 5 2 10l10 5 10-5zM6 12v5c3 2 9 2 12 0v-5",
  notes: "M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4",
  code: "M16 18l6-6-6-6M8 6l-6 6 6 6",
  agents: "M9 7a3 3 0 1 0 0-.01M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6M17 11a3 3 0 1 0 0-6M21 20c0-2.6-1.6-4.8-4-5.6",
  collab: "M6 3v12M18 9a3 3 0 1 0 0-.01M6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 12a9 9 0 0 1-9 9",
  trading: "M3 3v18h18M7 15l4-4 3 3 6-7",
  improve: "M21 12a9 9 0 0 1-15.5 6.3L3 16M3 12a9 9 0 0 1 15.5-6.3L21 8M21 3v5h-5M3 21v-5h5",
  freewill: "M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4z",
  kahuna: "M3 8l4.5 4L12 5l4.5 7L21 8l-2 11H5L3 8z",
  computer: "M3 4h18v12H3zM8 20h8M12 16v4",
  connectors: "M9 15l6-6M10 6l1-1a4.2 4.2 0 0 1 6 6l-1 1M14 18l-1 1a4.2 4.2 0 0 1-6-6l1-1",
  office: "M3 21h18M5 21V5l7-2v18M19 21V9l-7-2M9 9h.01M9 13h.01M9 17h.01",
  equalize: "M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4",
  admin: "M12 3l8 3v6c0 4.6-3.4 8.5-8 9-4.6-.5-8-4.4-8-9V6l8-3z",
};

function Glyph({ id, label }: { id: string; label: string }) {
  const d = GLYPHS[id];
  if (!d) return <span className="studio-rail__letter" aria-hidden="true">{label.slice(0, 1).toUpperCase()}</span>;
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

export function StudioRail({ tabs, userTabs, active, avatar, onSelect, onNewTab, onSettings }: {
  tabs: TabDef[];
  userTabs: TabSpec[];
  active: string;
  avatar: AvatarState;
  onSelect: (id: string) => void;
  onNewTab: () => void;
  onSettings: () => void;
}) {
  // The tooltip lives on the rail itself (not the scrolling list), so it is never clipped.
  const railRef = useRef<HTMLElement>(null);
  const [tip, setTip] = useState<{ text: string; top: number } | null>(null);
  const show = (e: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) => {
    const text = e.currentTarget.dataset.tip, rail = railRef.current?.getBoundingClientRect();
    if (!text || !rail) return;
    const r = e.currentTarget.getBoundingClientRect();
    setTip({ text, top: r.top - rail.top + r.height / 2 });
  };
  const hide = () => setTip(null);
  const tipProps = { onMouseEnter: show, onMouseLeave: hide, onFocus: show, onBlur: hide };
  const item = (id: string, label: string) => (
    <button key={id} type="button" role="tab" aria-selected={active === id} aria-label={label} data-tip={label}
      className="studio-rail__item" onClick={() => onSelect(id)} {...tipProps}>
      <Glyph id={id} label={label} />
    </button>
  );
  return (
    <nav ref={railRef} className="studio-rail" aria-label="Workspace" onScroll={hide}>
      {tip && <span className="studio-rail__tip" style={{ top: tip.top }} aria-hidden="true">{tip.text}</span>}
      <div className="studio-rail__logo" title="Ichos — created by Shagnik"><NyxAvatar state={avatar} size={30} /></div>
      <div role="tablist" aria-orientation="vertical" aria-label="Workspace tabs" className="studio-rail__list">
        {tabs.map((t) => item(t.id, t.label))}
        {userTabs.length > 0 && <span className="studio-rail__sep" aria-hidden="true" />}
        {userTabs.map((t) => item(t.id, t.label))}
        <button type="button" className="studio-rail__item" aria-label="New tab" data-tip="Find or create a tab (Ctrl+K)" onClick={onNewTab} {...tipProps}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
        </button>
      </div>
      <div className="studio-rail__foot">
        <button type="button" className="studio-rail__item" aria-label="Settings" data-tip="Settings" onClick={onSettings} {...tipProps}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
          </svg>
        </button>
      </div>
    </nav>
  );
}
