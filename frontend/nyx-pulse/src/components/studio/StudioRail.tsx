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
import type { DragItem } from "../../state/dragItems";
import type { NavSide } from "../../style/appearance";
import { useTabDnd } from "../useTabDnd";
import { TabGlyph } from "../TabGlyph";

export function StudioRail({ tabs, userTabs, active, avatar, onSelect, onNewTab, onSettings, onReorder, onDropItem, side = "left" }: {
  onReorder: (dragged: string, over: string, after: boolean) => void;
  onDropItem: (tabId: string, item: DragItem) => void;
  side?: NavSide;
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
  const dnd = useTabDnd({ horizontal: side === "top" || side === "bottom", onReorder, onDropItem });
  const tipProps = { onMouseEnter: show, onMouseLeave: hide, onFocus: show, onBlur: hide };
  const item = (id: string, label: string) => (
    <button key={id} type="button" role="tab" aria-selected={active === id} aria-label={label} data-tip={label}
      className={`studio-rail__item ${dnd.marks(id)}`} onClick={() => onSelect(id)} {...tipProps} {...dnd.props(id)}>
      <TabGlyph id={id} label={label} />
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
        <button type="button" className={`studio-rail__item ${dnd.marks("+new")}`} aria-label="New tab" data-tip="Find or create a tab (Ctrl+K), or drop something here" onClick={onNewTab} {...tipProps}
          onDragOver={dnd.props("+new").onDragOver} onDragLeave={dnd.props("+new").onDragLeave} onDrop={dnd.props("+new").onDrop}>
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
