/** The compact chat's right-hand panel, like the Threads panel in Claude's app (the owner's images 01-c, 01-d and the
 *  2026-10-15 screenshots): one place for what used to be the header modules.
 *
 *  • **Threads**: "Welcome back, {name}.", one combined usage graph, then every chat grouped Waiting on you · Working ·
 *    Idle, each with a coloured dot and its one-line live status (a thinking phrase while a turn has nothing better).
 *  • **Library**: artifacts and linked folders, with "+ Add" (a note, or link a folder), like Claude's project Library.
 *  • **Activity**: what Ichos touched (the old Activity rail, which was a separate pull-out).
 *
 *  Data is read from what already exists: /api/command-zone (daily message counts, so the graph matches the Command
 *  Zone), /api/commander/attention (which chats need the owner), the turn store (which chats are running), /api/artifacts
 *  and /api/code/workspaces. Nothing here writes except "+ Add". Which tab is open and whether the panel shows are
 *  remembered per window. */

import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent } from "react";
import { api, authHeaders } from "../../../api";
import { useStore } from "../../../state/store";
import { turnsStore } from "../../../state/turnStore";
import { ActivityRail } from "../../activity/ActivityRail";
import { useAttention, type Attention } from "../../commander/attention";
import { isGenericStatus, ownerName, thinkingPhrase } from "../phrases";
import type { ChatSummaryView } from "../types";
import { ProjectLibrary, ProjectThreads } from "./ProjectOverview";

type Tab = "threads" | "library" | "activity";
const TAB_KEY = "nyx.chat.overview.tab";

function readTab(): Tab {
  try {
    const v = localStorage.getItem(TAB_KEY);
    return v === "library" || v === "activity" ? v : "threads";
  } catch { return "threads"; }
}

function ms(value: number | string | undefined): number {
  if (value === undefined || value === null || value === "") return 0;
  if (typeof value === "number") return value > 1e12 ? value : value * 1000;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** "6m", "29m", "1h", "1d" — the age column on the right of each row, like Claude's. */
export function ago(when: number, now = Date.now()): string {
  if (!when) return "";
  const s = Math.max(0, Math.round((now - when) / 1000));
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

// --- the usage graph --------------------------------------------------------------------------------------------

const DAYS = 14;

/** Daily messages across every chat, model and agent for the last two weeks, drawn as one line with a lit end. */
function UsageSpark() {
  const [daily, setDaily] = useState<number[] | null>(null);
  const [total, setTotal] = useState(0);
  useEffect(() => {
    let alive = true;
    void api.get<{ usage: { daily: Record<string, number>; today: string; messages: number } }>("/api/command-zone?range=30d").then((r) => {
      if (!alive || !r.ok || !r.data.usage?.daily) return;
      const usage = r.data.usage;
      const end = new Date(`${usage.today}T12:00:00`);
      if (Number.isNaN(end.getTime())) return;
      const points: number[] = [];
      for (let i = DAYS - 1; i >= 0; i--) {
        const d = new Date(end.getTime() - i * 86400000);
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
        points.push(usage.daily[key] || 0);
      }
      setDaily(points);
      setTotal(usage.messages);
    });
    return () => { alive = false; };
  }, []);
  const W = 150, H = 40;
  if (!daily) return <div className="ov-spark" aria-hidden="true" />;
  const max = Math.max(1, ...daily);
  const xy = daily.map((v, i) => [Math.round((i / (DAYS - 1)) * (W - 6)) + 3, Math.round(H - 4 - (v / max) * (H - 10))]);
  const [lx, ly] = xy[xy.length - 1];
  return (
    <svg className="ov-spark" width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Usage, last ${DAYS} days: ${daily.reduce((a, b) => a + b, 0)} messages (${total} in 30 days)`}>
      <title>{`${daily[daily.length - 1]} messages today · ${total} in the last 30 days`}</title>
      <polyline points={xy.map((p) => p.join(",")).join(" ")} fill="none" stroke="currentColor" strokeWidth="1.6"
        strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lx} cy={ly} r="5" className="ov-spark__halo" />
      <circle cx={lx} cy={ly} r="2.6" className="ov-spark__dot" />
    </svg>
  );
}

// --- Threads ----------------------------------------------------------------------------------------------------

interface Row { chat: ChatSummaryView; group: "pinned" | "waiting" | "working" | "idle"; line: string; label: string; when: number }

const PINS_KEY = "nyx.rail.pins";
/** The chats pinned in the chat list (ChatRail keeps them; it says "nyx:pins" when they change). */
function usePins(): string[] {
  const read = () => {
    try { const raw = JSON.parse(localStorage.getItem(PINS_KEY) || "[]"); return Array.isArray(raw) ? raw.map(String) : []; }
    catch { return []; }
  };
  const [pins, setPins] = useState<string[]>(read);
  useEffect(() => {
    const on = () => setPins(read());
    window.addEventListener("nyx:pins", on);
    return () => window.removeEventListener("nyx:pins", on);
  }, []);
  return pins;
}

function Threads({ chats, activeId, onOpen, filter }: {
  chats: ChatSummaryView[]; activeId: string; onOpen: (id: string) => void; filter: string;
}) {
  const pins = usePins();
  const attention = useAttention();
  const running = useStore(turnsStore, (s) => s.runningByChat);
  const turns = useStore(turnsStore, (s) => s.turns);
  const [tick, setTick] = useState(0);
  const [closed, setClosed] = useState<Record<string, boolean>>({});
  const [more, setMore] = useState(false);
  // The phrase on a working row moves on every few seconds, like Claude's "Baking" → "Leavening".
  useEffect(() => {
    const t = window.setInterval(() => setTick((n) => n + 1), 4000);
    return () => window.clearInterval(t);
  }, []);

  const rows = useMemo<Row[]>(() => chats.map((chat) => {
    const need: Attention | undefined = attention[chat.id];
    const turnId = running[chat.id];
    const turn = turnId ? turns[turnId] : undefined;
    if (need?.status === "needs_you") return { chat, group: "waiting", line: need.line, label: need.label || "Blocked", when: ms(chat.updatedAt) };
    if (turn || chat.running || need?.status === "working") {
      const status = turn?.status || need?.line || chat.status || "";
      return { chat, group: "working", label: "", when: turn?.startedAt || ms(chat.updatedAt),
        line: isGenericStatus(status) ? `${thinkingPhrase(chat.id, tick)}…` : status };
    }
    const idle = chat.status || (chat.messageCount ? `${chat.messageCount} messages` : "Empty");
    // A pinned chat stays in Pinned while it is idle, like Claude's; once it needs you or works, it moves to that group.
    if (pins.includes(chat.id)) return { chat, group: "pinned", label: "Idle", line: idle, when: ms(chat.updatedAt) };
    return { chat, group: "idle", label: "", line: idle, when: ms(chat.updatedAt) };
  }), [attention, chats, pins, running, tick, turns]);

  const wanted = filter.trim().toLowerCase();
  const shown = wanted ? rows.filter((r) => `${r.chat.title} ${r.line}`.toLowerCase().includes(wanted)) : rows;
  const groups = (["pinned", "waiting", "working", "idle"] as const).map((id) => ({
    id,
    label: id === "pinned" ? "Pinned" : id === "waiting" ? "Waiting on you" : id === "working" ? "Working" : "Idle",
    rows: shown.filter((r) => r.group === id).sort((a, b) => b.when - a.when),
  })).filter((g) => g.id !== "pinned" || g.rows.length > 0);
  const waiting = rows.filter((r) => r.group === "waiting").length;
  const working = rows.filter((r) => r.group === "working").length;
  const name = ownerName();

  return (
    <div className="ov-threads">
      <header className="ov-welcome">
        <div>
          <h2>{name ? `Welcome back, ${name}.` : "Welcome back."}</h2>
          <p>{waiting ? `${waiting} ${waiting === 1 ? "thread is" : "threads are"} waiting on you.`
            : working ? "Working on things! I'll ping you." : "All quiet. Ask for anything."}</p>
        </div>
        <UsageSpark />
      </header>
      {groups.map((g) => (
        <section key={g.id} className="ov-group">
          <button type="button" className="ov-group__head" aria-expanded={!closed[g.id]}
            onClick={() => setClosed((c) => ({ ...c, [g.id]: !c[g.id] }))}>
            <span aria-hidden="true" className="ov-chev">{closed[g.id] ? "›" : "⌄"}</span>
            {g.label} <span className="ov-n">{g.rows.length}</span>
          </button>
          {!closed[g.id] && g.id === "waiting" && g.rows.length === 0 && !wanted && (
            <p className="ov-empty">Decisions, reviews, and permission requests.</p>
          )}
          {!closed[g.id] && g.rows.length > 0 && (
            <ul className="ov-list">
              {(g.id === "idle" && !more ? g.rows.slice(0, 6) : g.rows).map((r) => (
                <li key={r.chat.id}>
                  <button type="button" className={`ov-row is-${r.group}${r.chat.id === activeId ? " is-open" : ""}`}
                    onClick={() => onOpen(r.chat.id)} aria-label={`${r.chat.title}: ${r.label ? `${r.label}, ` : ""}${r.line}`}>
                    <span className="ov-dot" aria-hidden="true" />
                    <span className="ov-text">
                      <b>{r.chat.title || "New chat"}</b>
                      <span className="ov-line">{r.label && <em>{r.label} · </em>}{r.line}</span>
                    </span>
                    {(r.chat.messageCount ?? 0) > 0 && (
                      <span className="ov-pill" title={`${r.chat.messageCount} messages`}>
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                          <path d="M21 12a8 8 0 0 1-11.5 7.2L4 20l1-4.6A8 8 0 1 1 21 12z" /></svg>
                        {r.chat.messageCount}
                      </span>
                    )}
                    <span className="ov-age">{ago(r.when)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          {!closed[g.id] && g.id === "idle" && g.rows.length > 6 && (
            <button type="button" className="ov-more" onClick={() => setMore((v) => !v)}>{more ? "Show less" : "Show more"}</button>
          )}
        </section>
      ))}
    </div>
  );
}

// --- Library ----------------------------------------------------------------------------------------------------

interface Artifact { id: string; title: string; kind: string; note: string; created: number; updated?: number }
interface Workspace { id: string; path: string; name?: string }

type Kind = "all" | "folders" | "artifacts";
const TIP_KEY = "nyx.library.tipClosed";

function size(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} KB`;
  return `${bytes} bytes`;
}

function day(when: number): string {
  if (!when) return "—";
  return new Date(when).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}

/** "24.4 MB of 10.7 GB used": what Ichos keeps of yours, against the drive it lives on (owner-only report). */
function StorageLine() {
  const [used, setUsed] = useState<{ yours: number; total: number } | null>(null);
  useEffect(() => {
    let alive = true;
    void api.get<{ yours_bytes?: number; disk?: { total_bytes: number } }>("/api/storage").then((r) => {
      if (alive && r.ok && typeof r.data.yours_bytes === "number") setUsed({ yours: r.data.yours_bytes, total: r.data.disk?.total_bytes || 0 });
    });
    return () => { alive = false; };
  }, []);
  if (!used) return null;
  const share = used.total ? Math.min(100, Math.max(0.5, (used.yours / used.total) * 100)) : 0;
  return (
    <footer className="ov-storage">
      {used.total > 0 && <span className="ov-storage__bar" aria-hidden="true"><span style={{ width: `${share}%` }} /></span>}
      <span>{size(used.yours)}{used.total ? ` of ${size(used.total)}` : ""} used</span>
    </footer>
  );
}

function Library() {
  const [artifacts, setArtifacts] = useState<Artifact[] | null>(null);
  const [folders, setFolders] = useState<Workspace[]>([]);
  const [open, setOpen] = useState<Record<string, boolean>>({ artifacts: true });
  const [adding, setAdding] = useState<"" | "menu" | "note" | "folder" | "drive">("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [kind, setKind] = useState<Kind>("all");
  const [tipClosed, setTipClosed] = useState(() => { try { return localStorage.getItem(TIP_KEY) === "1"; } catch { return false; } });
  const fileRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    const [a, w] = await Promise.all([
      api.get<{ artifacts: Artifact[] }>("/api/artifacts"),
      api.get<{ workspaces: Workspace[] }>("/api/code/workspaces"),
    ]);
    setArtifacts(a.ok ? a.data.artifacts : []);
    if (w.ok) setFolders(w.data.workspaces);
  };
  useEffect(() => { void load(); }, []);

  const save = async () => {
    const value = text.trim();
    if (!value) return;
    const r = adding === "note"
      ? await api.post("/api/artifacts", { title: value.split("\n")[0].slice(0, 120), kind: "document", note: value })
      : await api.post("/api/code/workspaces", { path: value });
    if (!r.ok) { setError(r.error); return; }
    setAdding(""); setText(""); setError("");
    void load();
  };

  // "Upload from device": each file goes to /api/uploads (raw body, as the chat box sends it), then gets a Library row.
  const upload = async (files: File[]) => {
    setAdding("");
    for (const file of files) {
      try {
        const res = await fetch("/api/uploads", {
          method: "POST",
          headers: { "Content-Type": file.type || "application/octet-stream", "X-Filename": encodeURIComponent(file.name), ...authHeaders() },
          body: file,
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) { setError(data.detail || `Could not upload ${file.name}.`); continue; }
        const id = data.upload?.id ?? "";
        await api.post("/api/artifacts", {
          title: file.name.slice(0, 120),
          kind: file.type.startsWith("image/") ? "image" : "other",
          note: `Uploaded from this device (${size(file.size)}).\n/api/uploads/${id}`,
        });
      } catch {
        setError(`Could not upload ${file.name}.`);
      }
    }
    void load();
  };

  const showFolders = kind !== "artifacts";
  const showArtifacts = kind !== "folders";

  return (
    <div className="ov-library">
      <div className="ov-lib-bar">
        <label className="ov-type">
          <span className="sr-only">Type</span>
          <select value={kind} onChange={(e) => setKind(e.target.value as Kind)} aria-label="Type">
            <option value="all">Type</option>
            <option value="folders">Folders</option>
            <option value="artifacts">Artifacts</option>
          </select>
        </label>
        <span className="ov-add">
          <button type="button" className="ov-add__btn" aria-haspopup="menu" aria-expanded={adding === "menu"}
            onClick={() => setAdding((v) => (v === "menu" ? "" : "menu"))}>+ Add</button>
          {adding === "menu" && (
            <span role="menu" className="ov-add__menu">
              <button role="menuitem" type="button" onClick={() => fileRef.current?.click()}>⇪ Upload from device</button>
              <button role="menuitem" type="button" onClick={() => setAdding("drive")}>△ Add a Google Drive folder</button>
              <button role="menuitem" type="button" onClick={() => setAdding("folder")}>▭ Link local folder</button>
              <button role="menuitem" type="button" onClick={() => setAdding("note")}>▤ Save a note</button>
            </span>
          )}
        </span>
        <input ref={fileRef} type="file" multiple hidden onChange={(e) => { void upload(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
      </div>
      {adding === "drive" && (
        <div className="ov-lib-form">
          <p className="ov-empty">Google Drive folders need Google sign-in first (Connections › Google). Once it works, folders you pick show here.</p>
          <span>
            <button type="button" className="btn btn-secondary" onClick={() => window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "connectors" } }))}>Open Connections</button>
            <button type="button" className="btn" onClick={() => setAdding("")}>Close</button>
          </span>
        </div>
      )}
      {(adding === "note" || adding === "folder") && (
        <form className="ov-lib-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          {adding === "note"
            ? <textarea autoFocus rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="First line is the title" />
            : <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="C:\Users\you\Desktop\A folder" />}
          <span><button type="submit" className="btn btn-secondary">Add</button>
            <button type="button" className="btn" onClick={() => { setAdding(""); setError(""); }}>Cancel</button></span>
        </form>
      )}
      {error && <p className="ov-error" role="alert">{error}</p>}
      <table className="ov-table">
        <thead>
          <tr><th>Name</th><th>Date modified</th><th>Size</th><th>Kind</th></tr>
        </thead>
        <tbody>
          {showArtifacts && (
            <tr className="ov-tr is-folder">
              <td>
                <button type="button" className="ov-tname" aria-expanded={!!open.artifacts}
                  onClick={() => setOpen((o) => ({ ...o, artifacts: !o.artifacts }))}>
                  <span aria-hidden="true" className="ov-chev">{open.artifacts ? "⌄" : "›"}</span>
                  <span aria-hidden="true">🗀</span> Artifacts
                </button>
              </td>
              <td>—</td><td>{artifacts ? `${artifacts.length} items` : ""}</td><td>Folder</td>
            </tr>
          )}
          {showArtifacts && open.artifacts && artifacts === null && <tr><td colSpan={4} className="ov-empty">Loading…</td></tr>}
          {showArtifacts && open.artifacts && artifacts?.length === 0 && (
            <tr><td colSpan={4} className="ov-empty">Nothing yet. Ask for a doc, a plan or a design in any chat.</td></tr>
          )}
          {showArtifacts && open.artifacts && artifacts?.map((a) => (
            <tr key={a.id} className="ov-tr is-nested" title={a.note.slice(0, 400)}>
              <td><span className="ov-tname"><span aria-hidden="true">🗎</span> {a.title}</span></td>
              <td>{day(ms(a.updated || a.created))}</td><td>—</td><td>{a.kind}</td>
            </tr>
          ))}
          {showFolders && folders.map((f) => (
            <tr key={f.id} className="ov-tr" title={f.path}>
              <td><span className="ov-tname"><span aria-hidden="true">🖿</span> {f.name || f.path.split(/[\\/]/).filter(Boolean).pop()}
                <small>This computer</small></span></td>
              <td>—</td><td>—</td><td>Linked folder</td>
            </tr>
          ))}
        </tbody>
      </table>
      {!tipClosed && (
        <aside className="ov-tipcard">
          <span aria-hidden="true" className="ov-tipcard__icon">🗐</span>
          <span><b>Ichos can create files</b><small>Ask for docs, files, artifacts, or folders in any chat. Ichos keeps them in this panel.</small></span>
          <button type="button" aria-label="Close" onClick={() => { setTipClosed(true); try { localStorage.setItem(TIP_KEY, "1"); } catch { /* not kept */ } }}>✕</button>
        </aside>
      )}
      <StorageLine />
    </div>
  );
}

// --- size and place (owner 2026-10-15: the right panels can be dragged and pulled wider or narrower) ---------------

const BOX_KEY = "nyx.chat.overview.box";
type Box = { w: number; floating: boolean; x: number; y: number; h: number };

function readBox(): Box {
  const base: Box = { w: 0, floating: false, x: 0, y: 72, h: 0 };
  try { return { ...base, ...JSON.parse(localStorage.getItem(BOX_KEY) || "{}") }; } catch { return base; }
}

/** Width from the left edge (docked or floating), and a pop-out mode moved by its tab bar. Kept per window. */
function usePanelBox() {
  const ref = useRef<HTMLElement>(null);
  const [b, setB] = useState<Box>(readBox);
  useEffect(() => { try { localStorage.setItem(BOX_KEY, JSON.stringify(b)); } catch { /* not kept */ } }, [b]);
  const clampW = (w: number) => Math.round(Math.max(260, Math.min(w, window.innerWidth * 0.8)));
  const drag = (e: ReactPointerEvent, onMove: (ev: PointerEvent, start: DOMRect) => void) => {
    if (e.button !== 0) return;
    e.preventDefault();
    const start = ref.current?.getBoundingClientRect() ?? new DOMRect();
    const move = (ev: PointerEvent) => onMove(ev, start);
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const startResize = (e: ReactPointerEvent) => drag(e, (ev, r) => {
    const w = clampW(r.right - ev.clientX);
    setB((o) => ({ ...o, w, x: o.floating ? r.right - w : o.x }));
  });
  const startCorner = (e: ReactPointerEvent) => drag(e, (ev, r) => {
    setB((o) => ({ ...o, w: clampW(ev.clientX - r.left), h: Math.max(220, Math.min(ev.clientY - r.top, window.innerHeight - r.top - 8)) }));
  });
  const startMove = (e: ReactPointerEvent) => {
    if (!b.floating || (e.target as HTMLElement).closest("button, input")) return;
    const dx = e.clientX - b.x, dy = e.clientY - b.y;
    drag(e, (ev, r) => setB((o) => ({ ...o,
      x: Math.max(8 - r.width + 80, Math.min(ev.clientX - dx, window.innerWidth - 80)),
      y: Math.max(8, Math.min(ev.clientY - dy, window.innerHeight - 40)) })));
  };
  const toggleFloat = () => setB((o) => {
    if (o.floating) return { ...o, floating: false };
    const r = ref.current?.getBoundingClientRect();
    const w = o.w || 360;
    return { ...o, floating: true, w, x: (r?.right ?? window.innerWidth) - w - 24, y: (r?.top ?? 72) + 24,
      h: o.h || Math.min(560, window.innerHeight - 120) };
  });
  // Docked, the width goes to the grid column; floating, the panel places itself.
  useEffect(() => {
    const home = ref.current?.parentElement;
    if (!home) return;
    if (b.w && !b.floating) home.style.setProperty("--ov-w", `${b.w}px`);
    else home.style.removeProperty("--ov-w");
  }, [b.w, b.floating]);
  const style: CSSProperties | undefined = b.floating ? { left: b.x, top: b.y, width: b.w, height: b.h } : undefined;
  return { ref, floating: b.floating, style, startResize, startCorner, startMove, toggleFloat };
}

// --- the panel --------------------------------------------------------------------------------------------------

export function OverviewPanel({ chats, activeId, onOpen, onClose, onNew, project }: {
  chats: ChatSummaryView[]; activeId: string; onOpen: (id: string) => void; onClose: () => void; onNew?: () => void;
  /** Set inside a project (its main chat or one of its threads): Threads and Library show that project. */
  project?: { id: string; mainChatId: string };
}) {
  // Inside a project the panel shows the project; "All chats" switches back to everything (per project, not kept).
  const [allChats, setAllChats] = useState(false);
  useEffect(() => { setAllChats(false); }, [project?.id]);
  const inProject = Boolean(project) && !allChats;
  const [tab, setTab] = useState<Tab>(readTab);
  const [searching, setSearching] = useState(false);
  const [filter, setFilter] = useState("");
  // ⤢ widens the panel over the chat, like the expand button in Claude's Threads panel.
  const [wide, setWide] = useState(false);
  const box = usePanelBox();
  useEffect(() => { try { localStorage.setItem(TAB_KEY, tab); } catch { /* not kept */ } }, [tab]);
  const attention = useAttention();
  const waiting = Object.values(attention).filter((a) => a.status === "needs_you").length;
  const tabs: { id: Tab; label: string; icon: string }[] = [
    { id: "threads", label: "Threads", icon: "◌" },
    { id: "library", label: "Library", icon: "▤" },
    { id: "activity", label: "Activity", icon: "◷" },
  ];
  return (
    <aside ref={box.ref} className={`ov-panel${wide && !box.floating ? " is-wide" : ""}${box.floating ? " is-floating" : ""}`}
      aria-label="Overview" style={box.style}>
      <span className="ov-resize" onPointerDown={(e) => { setWide(false); box.startResize(e); }} title="Drag to resize" aria-hidden="true" />
      {box.floating && <span className="ov-resize is-corner" onPointerDown={box.startCorner} title="Drag to resize" aria-hidden="true" />}
      <nav className="ov-tabs" role="tablist" onPointerDown={box.startMove}>
        {tabs.map((t) => (
          <button key={t.id} role="tab" type="button" aria-selected={tab === t.id} className="ov-tab" onClick={() => setTab(t.id)}
            title={t.label}>
            <span aria-hidden="true">{t.icon}</span>
            {tab === t.id && <span>{t.label}</span>}
            {t.id === "threads" && waiting > 0 && <span className="ov-badge">{waiting}</span>}
          </button>
        ))}
        {onNew && <button type="button" className="ov-tab" onClick={onNew} title="New chat" aria-label="New chat">＋</button>}
        <span className="ov-tabs__spacer" />
        {tab === "threads" && (
          <button type="button" className={`ov-close${searching ? " is-on" : ""}`} aria-pressed={searching} title="Search threads"
            aria-label="Search threads" onClick={() => { setSearching((v) => !v); setFilter(""); }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true">
              <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
          </button>
        )}
        <button type="button" className={`ov-close${box.floating ? " is-on" : ""}`} aria-pressed={box.floating}
          title={box.floating ? "Put it back on the right" : "Pop out (drag it anywhere)"}
          aria-label={box.floating ? "Put the overview back on the right" : "Pop the overview out"} onClick={box.toggleFloat}>⧉</button>
        <button type="button" className={`ov-close${wide ? " is-on" : ""}`} aria-pressed={wide} title={wide ? "Narrow" : "Widen"}
          aria-label={wide ? "Narrow the overview" : "Widen the overview"} onClick={() => setWide((v) => !v)}>⤢</button>
        <button type="button" className="ov-close" onClick={onClose} aria-label="Close the overview" title="Close">✕</button>
      </nav>
      {tab === "threads" && searching && (
        <input className="ov-search" autoFocus value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search threads"
          aria-label="Search threads" onKeyDown={(e) => { if (e.key === "Escape") { setSearching(false); setFilter(""); } }} />
      )}
      {project && tab !== "activity" && (
        <div className="ov-scope" role="group" aria-label="Show">
          <button type="button" className={`ov-scope__btn${inProject ? " is-on" : ""}`} aria-pressed={inProject} onClick={() => setAllChats(false)}>This project</button>
          <button type="button" className={`ov-scope__btn${!inProject ? " is-on" : ""}`} aria-pressed={!inProject} onClick={() => setAllChats(true)}>All chats</button>
        </div>
      )}
      <div className="ov-body">
        {tab === "threads" && (inProject && project
          ? <ProjectThreads projectId={project.id} mainChatId={project.mainChatId} activeId={activeId} onOpen={onOpen} filter={filter} />
          : <Threads chats={chats} activeId={activeId} onOpen={onOpen} filter={filter} />)}
        {tab === "library" && (inProject && project ? <ProjectLibrary projectId={project.id} onOpenChat={onOpen} /> : <Library />)}
        {tab === "activity" && <ActivityRail onClose={() => setTab("threads")} />}
      </div>
    </aside>
  );
}
