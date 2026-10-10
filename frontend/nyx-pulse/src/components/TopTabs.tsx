/** The workspace tab strip, across the top (redesign 2026-10-10).
 *
 * Fewer tabs now — the owner merged related ones — so the strip reads as a row of places, not a ribbon. It still
 * scrolls sideways rather than wrapping, and "All tabs" stays pinned at the right so nothing is ever unreachable.
 * The Comfortable/Compact switch is gone (owner); one size, sized for a pointer (32 px targets).
 * A dot no longer decorates pinned tabs: it meant nothing on 21 of 32 tabs (live audit).
 */

import { useEffect, useRef, useState } from "react";
import type { TabDef } from "../tabs";
import type { TabSpec } from "../panels/DynamicTab";

interface Props {
  tabs: TabDef[];
  userTabs: TabSpec[];
  active: string;
  onSelect: (id: string) => void;
  onNewTab: () => void;
}

export function TopTabs({ tabs, userTabs, active, onSelect, onNewTab }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const tab = (id: string, label: string) => (
    <button key={id} type="button" role="tab" aria-selected={active === id} className="top-tabs__tab" onClick={() => onSelect(id)}>
      {label}
    </button>
  );

  const pick = (id: string) => { onSelect(id); setMenuOpen(false); };

  return (
    <div className="top-tabs">
      <div role="tablist" aria-label="Workspace tabs" className="top-tabs__scroll nyx-tabscroll">
        {tabs.map((t) => tab(t.id, t.label))}
        {userTabs.length > 0 && (
          <>
            <span aria-hidden="true" className="top-tabs__divider" />
            <span className="top-tabs__group">Your tabs</span>
            {userTabs.map((t) => tab(t.id, t.label))}
          </>
        )}
        <button type="button" className="top-tabs__tab" onClick={onNewTab} title="Find or create a tab (Ctrl+K)">+ New tab</button>
      </div>

      <div ref={menuRef} className="top-tabs__more">
        <button
          type="button"
          className="shell-icon-btn"
          onClick={() => setMenuOpen((v) => !v)}
          aria-expanded={menuOpen}
          aria-haspopup="menu"
        >
          All tabs
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M3 4.5 6 7.5 9 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
        </button>
        {menuOpen && (
          <div role="menu" className="top-tabs__menu">
            <div className="top-tabs__menu-title">Workspace</div>
            {tabs.map((t) => (
              <button key={t.id} role="menuitem" type="button" className="top-tabs__menu-item" aria-current={active === t.id} onClick={() => pick(t.id)}>{t.label}</button>
            ))}
            {userTabs.length > 0 && <div className="top-tabs__menu-title">Your tabs</div>}
            {userTabs.map((t) => (
              <button key={t.id} role="menuitem" type="button" className="top-tabs__menu-item" aria-current={active === t.id} onClick={() => pick(t.id)}>{t.label}</button>
            ))}
            <div style={{ height: 1, background: "var(--color-divider)", margin: "4px 0" }} />
            <button role="menuitem" type="button" className="top-tabs__menu-item" onClick={() => { setMenuOpen(false); onNewTab(); }}>+ New tab</button>
          </div>
        )}
      </div>
    </div>
  );
}
