/** The Threads panel (the owner's image p27, Claude's Projects): every thread a Commander chat started, grouped as
 *  Pinned · Needs you · Working · Idle · Resolved, each row a pill with a coloured dot and its one-line live status
 *  (the owner's image 01-d). "Needs you" is the short name he asked for instead of "Waiting on you".
 *
 *  Data comes from commander.py through /api/commander; status is read live there (a running turn, an approval, an
 *  unanswered question card, a "Waiting on you:" line), so this only polls and draws. */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import "./commander.css";

export interface ThreadTokens { used: number; window: number; share: number }
export interface Thread {
  id: string; chat_id: string; delegator: string; project_id: string; title: string; task: string; sector: string; job: string;
  tier: string; tier_label: string; effort: string; provider: string; model: string; model_label: string; why: string;
  source: string; pinned: boolean; resolved: boolean; created: number; updated: number; refreshed_from: string;
  refreshed_to: string; status: "needs_you" | "working" | "idle" | "resolved"; status_label: string; kind: string;
  line: string; approval_id: string; tokens: ThreadTokens; fresh_soon: boolean; messages: number;
}
interface Group { id: string; label: string; threads: Thread[] }
export interface TaskCount { done: number; total: number; needs_you: number }
/** Something a thread sent up to its main chat (commander.sync_asks): a question, an approval, a "Waiting on you"
 *  line, or a finished result. ``after`` is how many main chat messages came before it, so it is drawn in place. */
export interface Ask {
  id: string; thread_id: string; title: string; kind: "question" | "blocked" | "approval" | "result"; line: string;
  approval_id: string; card: string; after: number; created: number; open: boolean; answer: string;
  where: "" | "main" | "thread";
}
export interface Board {
  groups: Group[]; total: number; needs_you: number; working: number; tokens: number; sectors: string[];
  tasks: TaskCount; by_project: Record<string, TaskCount>; asks: Ask[];
}
export interface CommanderState {
  board: Board; is_delegator: boolean; settings: { divisions_in_chat: boolean; auto_pick: boolean };
  kinds: { id: string; label: string }[]; efforts: string[]; sectors: string[]; jobs: string[];
}

/** How often the panel re-reads the board. Local and cheap; a turn's status line changes every few seconds. */
const POLL_MS = 3000;

export function useCommander(delegator: string, projectId = "") {
  const [state, setState] = useState<CommanderState | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const query = new URLSearchParams({ delegator, project_id: projectId }).toString();
    const r = await api.get<CommanderState>(`/api/commander?${query}`);
    if (r.ok) { setState(r.data); setError(""); } else setError(r.error);
  }, [delegator, projectId]);
  useEffect(() => {
    void load();
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [load]);
  return { state, error, reload: load };
}

export const cap = (word: string) => word.charAt(0).toUpperCase() + word.slice(1);

export function tokensText(t: ThreadTokens): string {
  const k = (n: number) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n));
  return t.window ? `${k(t.used)} of ${k(t.window)}` : `${k(t.used)} tokens`;
}

function Row({ thread, onOpen, onChange }: { thread: Thread; onOpen: (t: Thread) => void; onChange: () => void }) {
  const toggle = async (body: Record<string, boolean>) => {
    const r = await api.put(`/api/commander/threads/${thread.id}`, body);
    if (r.ok) onChange();
  };
  const pct = Math.round(thread.tokens.share * 100);
  return (
    <li className={`th-row is-${thread.status}`}>
      <button className="th-open" onClick={() => onOpen(thread)} aria-label={`${thread.title}: ${thread.status_label}. ${thread.line}`}>
        <span className="th-dot" aria-hidden="true" />
        <span className="th-text">
          <b>{thread.title}</b>
          <span className="th-line">
            {thread.status === "needs_you" && <em>{thread.status_label} · </em>}
            {thread.line || thread.status_label}
          </span>
        </span>
        <span className="th-meta" title={`${thread.model_label || "Router decides"} · ${thread.why}`}>
          {cap(thread.job || "build")} · {thread.tier_label} · {thread.effort}
          <span className={`th-fill ${thread.fresh_soon ? "is-full" : ""}`} title={`${tokensText(thread.tokens)} (${pct}% full)`}>
            <i style={{ width: `${Math.min(100, Math.max(4, pct))}%` }} />
          </span>
        </span>
      </button>
      <span className="th-acts">
        <button onClick={() => void toggle({ pinned: !thread.pinned })} title={thread.pinned ? "Unpin" : "Pin"} aria-label={thread.pinned ? "Unpin" : "Pin"}>{thread.pinned ? "★" : "☆"}</button>
        <button onClick={() => void toggle({ resolved: !thread.resolved })} title={thread.resolved ? "Reopen" : "Resolve"}
          aria-label={thread.resolved ? "Reopen" : "Resolve"}>{thread.resolved ? "↺" : "✓"}</button>
      </span>
    </li>
  );
}

export function ThreadsPanel({ state, onOpen, onChange, title = "Threads" }: {
  state: CommanderState | null; onOpen: (t: Thread) => void; onChange: () => void; title?: string;
}) {
  const [closed, setClosed] = useState<Record<string, boolean>>({ resolved: true });
  const board = state?.board;
  const waiting = board?.needs_you ?? 0;
  return (
    <aside className="th-panel" aria-label={title}>
      <header className="th-head">
        <h2>{title} {board ? <span className="th-count">{board.total}</span> : null}
          {board && board.tasks.total > 0 && <span className="th-tasks" title="Tasks done out of all">Tasks {board.tasks.done}/{board.tasks.total}</span>}</h2>
        <p>{!board ? "Loading…" : board.total === 0 ? "No threads yet. Ask for something and the work is split into threads here."
          : waiting ? `${waiting} ${waiting === 1 ? "thread needs" : "threads need"} you.`
          : board.working ? `${board.working} working, nothing needs you.` : "Nothing needs you."}</p>
      </header>
      {board?.groups.filter((g) => g.threads.length > 0).map((g) => (
        <section key={g.id} className="th-group">
          <button className="th-group-head" aria-expanded={!closed[g.id]} onClick={() => setClosed((c) => ({ ...c, [g.id]: !c[g.id] }))}>
            <span aria-hidden="true">{closed[g.id] ? "›" : "⌄"}</span> {g.label} <span className="th-n">{g.threads.length}</span>
          </button>
          {!closed[g.id] && (
            <ul className="th-list">
              {g.threads.map((t) => <Row key={t.id} thread={t} onOpen={onOpen} onChange={onChange} />)}
            </ul>
          )}
        </section>
      ))}
    </aside>
  );
}
