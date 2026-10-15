/** The hands-off sidebar (Fixer Upper S2, reference p38): the app's tabs as a menu beside the notch, so the two of
 * them are all that sits on the screen.
 *
 * The owner: "a place for hands off mode … combined with the personal assistant so basically we just have the side
 * bar and the notch on our screen, as the ai selects the correct tab." So:
 *   - the tab the app is on is lit, and when Ichos opens one itself (ui_open_tab) it lights up with "Ichos picked";
 *   - the search box filters the tabs; Enter opens the one match, and anything else goes to Ichos through the notch's
 *     chat (one conversation, not two);
 *   - badges count what is waiting on the owner in each tab (the notch's waiting list);
 *   - Hands-off switches voice on, so the owner can talk instead of click.
 * The grip at the top drags the window (sidebar_window.py docks it to a side); the lock keeps it where it is.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { IoView } from "../notch/IoView";
import type { WaitingItem } from "../notch/notchApi";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { CORE_TABS, LEGACY_LABELS, REDIRECTS } from "../tabs";
import "./sidebar.css";

type Host = {
  drag_start?: () => Promise<boolean>;
  set_lock?: (locked: boolean) => Promise<boolean>;
  set_collapsed?: (collapsed: boolean) => Promise<boolean>;
  place?: () => Promise<{ locked: boolean; collapsed: boolean }>;
  hide?: () => Promise<void>;
};
const host = () => (window as unknown as { pywebview?: { api?: Host } }).pywebview?.api;

interface Status { state: string; voice: boolean; tab?: { id: string; at: number; by: string } }

const TABS = CORE_TABS.filter((t) => !t.adminOnly);

/** Any tab id the app or Ichos uses (old names included) as one of the sidebar's tabs. */
export function homeTab(id: string): string {
  const redirect = REDIRECTS[id];
  if (redirect?.kind === "hub") return redirect.tab;
  if (redirect?.kind === "settings") return "";
  if (id === "chat" || redirect?.kind === "window") return "nyx";
  return TABS.some((t) => t.id === id) ? id : "";
}

/** Tabs whose name (or an old name for them) contains what was typed. */
export function matchTabs(query: string): string[] {
  const q = query.trim().toLowerCase();
  if (!q) return TABS.map((t) => t.id);
  const hits = new Set<string>();
  for (const t of TABS) if (t.label.toLowerCase().includes(q)) hits.add(t.id);
  for (const old of LEGACY_LABELS) if (old.label.toLowerCase().includes(q) && homeTab(old.id)) hits.add(homeTab(old.id));
  return TABS.map((t) => t.id).filter((id) => hits.has(id));
}

/** Where each waiting item is answered, so its tab can carry a badge. */
const WAITING_TAB: Record<string, string> = { chat: "nyx", claude: "equalize" };

export function Sidebar() {
  const [status, setStatus] = useState<Status>({ state: "idle", voice: false });
  const [active, setActive] = useState<{ id: string; by: string }>({ id: "nyx", by: "you" });
  const [waiting, setWaiting] = useState<WaitingItem[]>([]);
  const [query, setQuery] = useState("");
  const [note, setNote] = useState("");
  const [locked, setLocked] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const seenTab = useRef(0);

  useEffect(() => {
    void host()?.place?.().then((p) => { setLocked(!!p.locked); setCollapsed(!!p.collapsed); });
  }, []);

  // What the app is doing: voice on or off, and the tab it was last sent to (by the owner or by Ichos).
  useEffect(() => {
    const poll = async () => {
      const r = await api.get<Status>("/api/notch", 2000);
      if (!r.ok) return;
      setStatus(r.data);
      const tab = r.data.tab;
      if (tab && tab.at > seenTab.current && homeTab(tab.id)) {
        seenTab.current = tab.at;
        setActive({ id: homeTab(tab.id), by: tab.by });
      }
    };
    void poll();
    const id = window.setInterval(poll, 1200);
    return () => window.clearInterval(id);
  }, []);

  // Ichos opening a tab itself: light it up the moment it happens.
  useEffect(() => onWorkspaceEvent((event) => {
    const id = event.type === "ui.open_tab" ? (event as { tab_id?: unknown }).tab_id : undefined;
    if (typeof id === "string" && homeTab(id)) setActive({ id: homeTab(id), by: "ai" });
  }), []);

  useEffect(() => {
    const poll = async () => {
      const r = await api.get<{ items: WaitingItem[] }>("/api/notch/waiting", 5000);
      if (r.ok) setWaiting(r.data.items);
    };
    void poll();
    const id = window.setInterval(poll, 5000);
    return () => window.clearInterval(id);
  }, []);

  const badges = useMemo(() => {
    const out: Record<string, number> = {};
    for (const item of waiting) {
      const tab = WAITING_TAB[item.where] ?? homeTab(item.where);
      if (tab) out[tab] = (out[tab] ?? 0) + 1;
    }
    return out;
  }, [waiting]);

  const shown = matchTabs(query);

  const open = (id: string) => {
    setActive({ id, by: "you" });
    setQuery("");
    void api.post("/api/notch/open-app", { tab: id });
  };
  const ask = async () => {
    const text = query.trim();
    if (!text) return;
    if (shown.length === 1) { open(shown[0]); return; }
    const r = await api.post("/api/notch/ask", { text });
    setNote(r.ok ? "Sent to Ichos in the notch." : r.error);
    if (r.ok) setQuery("");
    window.setTimeout(() => setNote(""), 3000);
  };
  const handsOff = async () => {
    const r = await api.post<{ on: boolean }>("/api/notch/hands-off", { on: !status.voice });
    if (r.ok) setStatus({ ...status, voice: r.data.on });
  };
  const lock = async () => {
    const h = host();
    setLocked(h?.set_lock ? await h.set_lock(!locked) : !locked);
  };
  const fold = async () => {
    const h = host();
    setCollapsed(h?.set_collapsed ? await h.set_collapsed(!collapsed) : !collapsed);
  };

  const listening = status.state === "listening";
  const ioState = listening ? "thinking" : status.state === "speaking" ? "working" : "idle";
  const voiceLine = listening ? "Listening…" : status.voice ? "Hands-off is on" : "Hands-off is off";

  return (
    <div className={`sb-root ${collapsed ? "folded" : ""}`}>
      <div className="sb-grip" title={locked ? "Locked in place" : "Drag to move"}
        onMouseDown={(e) => { if (e.button === 0 && !(e.target as HTMLElement).closest("button")) void host()?.drag_start?.(); }}>
        <div className="sb-winbtns">
          <button onClick={() => void lock()} aria-pressed={locked} aria-label={locked ? "Unlock" : "Lock in place"}
            title={locked ? "Unlock" : "Lock in place"}>{locked ? Glyph.lock() : Glyph.unlock()}</button>
          {!collapsed && <button onClick={() => void host()?.hide?.()} aria-label="Close the sidebar" title="Close">{Glyph.close()}</button>}
        </div>
        <button className="sb-fold" onClick={() => void fold()} aria-label={collapsed ? "Open the sidebar" : "Fold to icons"}
          title={collapsed ? "Open" : "Fold"}>{collapsed ? Glyph.right() : Glyph.left()}</button>
      </div>

      <div className="sb-brand">
        <span className={`sb-io ${listening ? "hot" : ""}`}><IoView size={collapsed ? 34 : 44} state={ioState} details={false} /></span>
        {!collapsed && <div><b>Ichos</b><small>{voiceLine}</small></div>}
      </div>

      {!collapsed && (
        <label className="sb-search">
          {Glyph.search()}
          <input value={query} placeholder="Search or ask Ichos" onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void ask(); if (e.key === "Escape") setQuery(""); }} />
        </label>
      )}
      {note && !collapsed ? <p className="sb-note" role="status">{note}</p> : null}

      {!collapsed && <p className="sb-label">Menu</p>}
      <nav className="sb-menu">
        {TABS.filter((t) => shown.includes(t.id)).map((t) => (
          <button key={t.id} className={`sb-item ${active.id === t.id ? "on" : ""} ${active.id === t.id && active.by === "ai" ? "ai" : ""}`}
            onClick={() => open(t.id)} title={t.label} aria-current={active.id === t.id ? "page" : undefined}>
            <span className="sb-icon">{tabGlyph(t.id)}</span>
            {!collapsed && <span className="sb-name">{t.label}{active.id === t.id && active.by === "ai" ? <em>Ichos picked</em> : null}</span>}
            {badges[t.id] ? <span className="sb-badge">{badges[t.id]}</span> : null}
          </button>
        ))}
        {!shown.length && !collapsed ? <p className="sb-note">No tab by that name. Enter asks Ichos.</p> : null}
      </nav>

      <div className="sb-foot">
        <button className={`sb-item handsoff ${status.voice ? "live" : ""}`} onClick={() => void handsOff()} aria-pressed={status.voice}
          title="Hands-off: talk to Ichos instead of clicking">
          <span className="sb-pill">{Glyph.mic()}</span>
          {!collapsed && <span className="sb-name">Hands-off<small>{status.voice ? "Ichos is listening" : "Turn on to talk"}</small></span>}
          {!collapsed && <span className="sb-switch" aria-hidden="true"><i /></span>}
        </button>
      </div>
    </div>
  );
}

// ── Icons (stroke, currentColor), drawn here so the window needs no icon font ──

const svg = (d: React.ReactNode, size = 20) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9}
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{d}</svg>
);

const Glyph = {
  search: () => svg(<><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.3-4.3" /></>, 18),
  close: () => svg(<path d="M6 6l12 12M18 6 6 18" />, 14),
  left: () => svg(<path d="m15 5-7 7 7 7" />, 16),
  right: () => svg(<path d="m9 5 7 7-7 7" />, 16),
  lock: () => svg(<><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></>, 14),
  unlock: () => svg(<><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 7.5-2" /></>, 14),
  mic: () => svg(<><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" /></>, 16),
};

const TAB_PATHS: Record<string, React.ReactNode> = {
  nyx: <path d="M5 4h14a2.5 2.5 0 0 1 2.5 2.5v8A2.5 2.5 0 0 1 19 17h-7.3L7 20.6V17H5a2.5 2.5 0 0 1-2.5-2.5v-8A2.5 2.5 0 0 1 5 4z" />,
  projects: <><circle cx="12" cy="12" r="4.5" /><path d="M3 15c3.5 2.5 14.5-1.5 18-6" /></>,
  avatars: <><circle cx="9" cy="8" r="3.2" /><path d="M3 20a6 6 0 0 1 12 0" /><circle cx="17" cy="9" r="2.5" /><path d="M16 14.5a5 5 0 0 1 5.5 5" /></>,
  agents: <><rect x="9" y="3" width="6" height="5" rx="1.2" /><rect x="3" y="16" width="6" height="5" rx="1.2" /><rect x="15" y="16" width="6" height="5" rx="1.2" /><path d="M12 8v4M6 16v-4h12v4" /></>,
  research: <><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.3-4.3" /></>,
  code: <path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" />,
  office: <><rect x="4" y="3" width="10" height="18" rx="1" /><path d="M14 9h6v12h-6M7.5 7h3M7.5 11h3M7.5 15h3" /></>,
  trading: <path d="m3 17 6-6 4 4 8-8M15 7h6v6" />,
  improve: <path d="M20 12a8 8 0 1 1-2.4-5.7M20 4v5h-5" />,
  equalize: <><circle cx="7" cy="12" r="3" /><circle cx="17" cy="7" r="3" /><circle cx="17" cy="17" r="3" /></>,
  computer: <><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></>,
  connectors: <path d="M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4" />,
};

function tabGlyph(id: string) {
  return svg(TAB_PATHS[id] ?? <circle cx="12" cy="12" r="4" />);
}
