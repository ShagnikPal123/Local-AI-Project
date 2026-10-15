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

import { useEffect, useMemo, useState } from "react";
import { api } from "../../../api";
import { useStore } from "../../../state/store";
import { turnsStore } from "../../../state/turnStore";
import { ActivityRail } from "../../activity/ActivityRail";
import { useAttention, type Attention } from "../../commander/attention";
import { isGenericStatus, ownerName, thinkingPhrase } from "../phrases";
import type { ChatSummaryView } from "../types";

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

interface Row { chat: ChatSummaryView; group: "waiting" | "working" | "idle"; line: string; label: string; when: number }

function Threads({ chats, activeId, onOpen }: { chats: ChatSummaryView[]; activeId: string; onOpen: (id: string) => void }) {
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
    return { chat, group: "idle", label: "", line: chat.status || (chat.messageCount ? `${chat.messageCount} messages` : "Empty"), when: ms(chat.updatedAt) };
  }), [attention, chats, running, tick, turns]);

  const groups = (["waiting", "working", "idle"] as const).map((id) => ({
    id,
    label: id === "waiting" ? "Waiting on you" : id === "working" ? "Working" : "Idle",
    rows: rows.filter((r) => r.group === id).sort((a, b) => b.when - a.when),
  }));
  const waiting = groups[0].rows.length;
  const working = groups[1].rows.length;
  const name = ownerName();

  return (
    <div className="ov-threads">
      <header className="ov-welcome">
        <div>
          <h2>{name ? `Welcome back, ${name}.` : "Welcome back."}</h2>
          <p>{waiting ? `${waiting} ${waiting === 1 ? "chat is" : "chats are"} waiting on you.`
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
          {!closed[g.id] && g.id === "waiting" && g.rows.length === 0 && (
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

function Library() {
  const [artifacts, setArtifacts] = useState<Artifact[] | null>(null);
  const [folders, setFolders] = useState<Workspace[]>([]);
  const [open, setOpen] = useState<Record<string, boolean>>({ artifacts: true });
  const [adding, setAdding] = useState<"" | "menu" | "note" | "folder">("");
  const [text, setText] = useState("");
  const [error, setError] = useState("");

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

  return (
    <div className="ov-library">
      <div className="ov-lib-bar">
        <span>Name</span>
        <span className="ov-add">
          <button type="button" className="ov-add__btn" aria-haspopup="menu" aria-expanded={adding === "menu"}
            onClick={() => setAdding((v) => (v === "menu" ? "" : "menu"))}>+ Add</button>
          {adding === "menu" && (
            <span role="menu" className="ov-add__menu">
              <button role="menuitem" type="button" onClick={() => setAdding("note")}>Save a note or file text</button>
              <button role="menuitem" type="button" onClick={() => setAdding("folder")}>Link local folder</button>
            </span>
          )}
        </span>
      </div>
      {(adding === "note" || adding === "folder") && (
        <form className="ov-lib-form" onSubmit={(e) => { e.preventDefault(); void save(); }}>
          {adding === "note"
            ? <textarea autoFocus rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="First line is the title" />
            : <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="C:\Users\you\Desktop\A folder" />}
          {error && <p className="ov-error">{error}</p>}
          <span><button type="submit" className="btn btn-secondary">Add</button>
            <button type="button" className="btn" onClick={() => { setAdding(""); setError(""); }}>Cancel</button></span>
        </form>
      )}
      <ul className="ov-files">
        <li>
          <button type="button" className="ov-file is-folder" aria-expanded={!!open.artifacts}
            onClick={() => setOpen((o) => ({ ...o, artifacts: !o.artifacts }))}>
            <span aria-hidden="true" className="ov-chev">{open.artifacts ? "⌄" : "›"}</span> Artifacts
            <span className="ov-n">{artifacts?.length ?? ""}</span>
          </button>
          {open.artifacts && (
            <ul className="ov-files is-nested">
              {artifacts === null && <li className="ov-empty">Loading…</li>}
              {artifacts?.length === 0 && <li className="ov-empty">Nothing yet. Ask for a doc, a plan or a design in any chat.</li>}
              {artifacts?.map((a) => (
                <li key={a.id} className="ov-file" title={a.note.slice(0, 400)}>
                  <span aria-hidden="true">▤</span> <span className="ov-file__name">{a.title}</span>
                  <span className="ov-file__meta">{a.kind} · {ago(ms(a.updated || a.created))}</span>
                </li>
              ))}
            </ul>
          )}
        </li>
        {folders.map((f) => (
          <li key={f.id} className="ov-file" title={f.path}>
            <span aria-hidden="true">▭</span> <span className="ov-file__name">{f.name || f.path.split(/[\\/]/).filter(Boolean).pop()}</span>
            <span className="ov-file__meta">Linked folder</span>
          </li>
        ))}
      </ul>
      <p className="ov-tip">Ichos can create files. Ask for docs, artifacts or folders in any chat and they land here.</p>
    </div>
  );
}

// --- the panel --------------------------------------------------------------------------------------------------

export function OverviewPanel({ chats, activeId, onOpen, onClose }: {
  chats: ChatSummaryView[]; activeId: string; onOpen: (id: string) => void; onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>(readTab);
  useEffect(() => { try { localStorage.setItem(TAB_KEY, tab); } catch { /* not kept */ } }, [tab]);
  const attention = useAttention();
  const waiting = Object.values(attention).filter((a) => a.status === "needs_you").length;
  const tabs: { id: Tab; label: string; icon: string }[] = [
    { id: "threads", label: "Threads", icon: "◌" },
    { id: "library", label: "Library", icon: "▤" },
    { id: "activity", label: "Activity", icon: "◷" },
  ];
  return (
    <aside className="ov-panel" aria-label="Overview">
      <nav className="ov-tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} role="tab" type="button" aria-selected={tab === t.id} className="ov-tab" onClick={() => setTab(t.id)}
            title={t.label}>
            <span aria-hidden="true">{t.icon}</span>
            {tab === t.id && <span>{t.label}</span>}
            {t.id === "threads" && waiting > 0 && <span className="ov-badge">{waiting}</span>}
          </button>
        ))}
        <span className="ov-tabs__spacer" />
        <button type="button" className="ov-close" onClick={onClose} aria-label="Close the overview" title="Close">✕</button>
      </nav>
      <div className="ov-body">
        {tab === "threads" && <Threads chats={chats} activeId={activeId} onOpen={onOpen} />}
        {tab === "library" && <Library />}
        {tab === "activity" && <ActivityRail onClose={() => setTab("threads")} />}
      </div>
    </aside>
  );
}
