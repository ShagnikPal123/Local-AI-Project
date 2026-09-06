/** The workspace tab bar, across the top.
 *
 * This used to be a 206px left rail. Shagnik asked for it on top, which changes
 * one thing fundamentally: a vertical rail can always show every tab, and a
 * horizontal one cannot. So the row scrolls sideways and never wraps — a wrapped
 * nav reflows the whole page every time a user tab is added — and an "All tabs"
 * menu sits pinned at the right end so nothing is ever unreachable, however
 * narrow the window or however many tabs exist.
 *
 * The old Rail/Strip switch survives as a density control. The two layouts no
 * longer differ in position, only in how much room each tab takes, so the labels
 * say Comfortable/Compact while the stored value stays "rail"/"strip" — an
 * existing install keeps whatever it had chosen.
 */

import { useEffect, useRef, useState } from "react";
import type { ShellLayout, TabDef } from "../tabs";
import type { TabSpec } from "../panels/DynamicTab";

interface Props {
  tabs: TabDef[];
  userTabs: TabSpec[];
  active: string;
  density: ShellLayout;
  onSelect: (id: string) => void;
  onNewTab: () => void;
}

export function TopTabs({ tabs, userTabs, active, density, onSelect, onNewTab }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const compact = density === "strip";
  const padding = compact ? "7px 10px" : "10px 14px";
  const fontSize = compact ? 12 : 13;

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  const tabButton = (id: string, label: string, pinned?: boolean) => (
    <button
      key={id}
      role="tab"
      aria-selected={active === id}
      onClick={() => onSelect(id)}
      title={label}
      style={{
        padding,
        fontSize,
        whiteSpace: "nowrap",
        borderRadius: 0,
        flex: "none",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        color: active === id ? "var(--color-text)" : "var(--color-neutral-500)",
        background: active === id ? "var(--color-neutral-900)" : "transparent",
        boxShadow: active === id ? "inset 0 -2px 0 var(--color-accent)" : undefined,
      }}
    >
      {label}
      {pinned && <span style={{ fontSize: 9, color: "var(--color-accent)" }}>●</span>}
    </button>
  );

  return (
    <div
      style={{
        display: "flex",
        alignItems: "stretch",
        background: "var(--color-nav)",
        boxShadow: "inset 0 -1px 0 var(--color-divider)",
        flex: "none",
        position: "relative",
        zIndex: 20,
      }}
    >
      {/* The scroller. `minWidth: 0` is what actually lets it shrink inside the
          flex row instead of pushing the menu button off-screen. */}
      <div
        role="tablist"
        aria-label="Workspace tabs"
        className="nyx-tabscroll"
        style={{
          display: "flex",
          alignItems: "stretch",
          gap: 2,
          padding: "0 4px 0 8px",
          overflowX: "auto",
          overflowY: "hidden",
          minWidth: 0,
          flex: 1,
        }}
      >
        {tabs.map((t) => tabButton(t.id, t.label, t.pinned))}

        {userTabs.length > 0 && (
          <>
            <span
              aria-hidden="true"
              style={{ width: 1, margin: "8px 6px", background: "var(--color-divider)", flex: "none" }}
            />
            <span
              className="label"
              style={{ alignSelf: "center", padding: "0 6px", flex: "none", whiteSpace: "nowrap" }}
            >
              Your tabs
            </span>
            {userTabs.map((t) => tabButton(t.id, t.label))}
          </>
        )}

        <button
          onClick={onNewTab}
          title="Find or create a tab (Ctrl+K)"
          style={{
            padding,
            fontSize,
            whiteSpace: "nowrap",
            borderRadius: 0,
            flex: "none",
            color: "var(--color-neutral-600)",
          }}
        >
          + New tab
        </button>
      </div>

      {/* Pinned right: at any width, every tab is one click away from here. */}
      <div ref={menuRef} style={{ flex: "none", display: "flex", alignItems: "stretch" }}>
        <button
          onClick={() => setMenuOpen((v) => !v)}
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          title="All tabs"
          style={{
            padding: "0 12px",
            fontSize,
            borderRadius: 0,
            whiteSpace: "nowrap",
            color: menuOpen ? "var(--color-text)" : "var(--color-neutral-500)",
            background: menuOpen ? "var(--color-neutral-900)" : "transparent",
            boxShadow: "inset 1px 0 0 var(--color-divider)",
          }}
        >
          All tabs ⌄
        </button>

        {menuOpen && (
          <div
            role="menu"
            className="card"
            style={{
              position: "absolute",
              top: "100%",
              right: 6,
              marginTop: 4,
              width: 240,
              maxHeight: "70vh",
              overflowY: "auto",
              padding: 6,
              zIndex: 30,
              boxShadow: "0 14px 40px rgba(0,0,0,.5), inset 0 0 0 1px var(--color-divider)",
            }}
          >
            <div className="label" style={{ padding: "6px 8px" }}>Workspace</div>
            {tabs.map((t) => (
              <MenuItem
                key={t.id}
                label={t.label}
                active={active === t.id}
                onClick={() => { onSelect(t.id); setMenuOpen(false); }}
              />
            ))}
            {userTabs.length > 0 && (
              <div className="label" style={{ padding: "10px 8px 6px" }}>Your tabs</div>
            )}
            {userTabs.map((t) => (
              <MenuItem
                key={t.id}
                label={t.label}
                active={active === t.id}
                onClick={() => { onSelect(t.id); setMenuOpen(false); }}
              />
            ))}
            <div style={{ height: 1, background: "var(--color-divider)", margin: "6px 0" }} />
            <MenuItem
              label="+ New tab"
              active={false}
              onClick={() => { setMenuOpen(false); onNewTab(); }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function MenuItem({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        padding: "8px 10px",
        fontSize: 13,
        borderRadius: 6,
        color: active ? "var(--color-text)" : "var(--color-neutral-400)",
        background: active ? "var(--color-neutral-900)" : "transparent",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </button>
  );
}
