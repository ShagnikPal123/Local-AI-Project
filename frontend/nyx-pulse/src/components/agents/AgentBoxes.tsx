/** Agents in boxes (owner request, 2026-09-16).
 *
 * "/coder and it pulls up the coder agent and in [] I add how many … I can drag a second one and it will show
 * a second box. In each I can say what I want each to specifically do."
 *
 * One box per copy of an agent. The same pieces are used by the chat (`/coder [3] …`), the Core view's project
 * dock (drag or +) and Nyx's own dispatches:
 *   • <BoxEditor> — the boxes before they run: task per box, + another copy, + another agent, remove;
 *   • <DispatchCard> — the boxes while and after they run: live step per copy, reports, + another box, Stop;
 *   • <DispatchSheet> — the editor as a dialog over the chat.
 * Status is always a word and a symbol, never colour alone.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../api";
import { pushToast } from "../../state/toastStore";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import "./agents.css";
import { Handoff } from "./Handoff";

export interface RosterAgent {
  name: string;
  emoji: string;
  goal: string;
  role: string;
  made_by?: string;
  builtin?: boolean;
  provider?: string;
  model?: string;
}

export interface BoxItem { key: string; agent: string; task: string }

export interface InstanceView {
  index: number; agent: string; label: string; task: string; emoji: string;
  status: "queued" | "working" | "done" | "error" | "stopped"; step: string; understanding: string; report: string; seconds: number;
  /** What the copy was handed besides its task, exactly as sent (U46). */
  context?: string;
}

export interface DispatchView {
  dispatch_id: string; chat_id: string; origin: string; status: string; created_at: number;
  project: { name?: string; path?: string };
  instances: InstanceView[]; counts: Record<string, number>; agents: Record<string, number>;
}

let boxCounter = 0;
export const newBox = (agent: string, task = ""): BoxItem => ({ key: `b${Date.now().toString(36)}${(boxCounter += 1)}`, agent, task });

/** Every agent but the Manager, kept fresh when agents are made or changed. */
export function useRoster(): RosterAgent[] {
  const [agents, setAgents] = useState<RosterAgent[]>([]);
  const load = useCallback(async () => {
    const result = await api.get<{ agents: RosterAgent[] }>("/api/agents/details");
    if (result.ok) setAgents(result.data.agents.filter((a) => a.role !== "master"));
  }, []);
  useEffect(() => {
    void load();
    return onWorkspaceEvent((event) => {
      if (event.type === "agents.changed" || event.type === "agent.created" || event.type === "agent.updated") void load();
    });
  }, [load]);
  return agents;
}

const STATUS_TEXT: Record<InstanceView["status"], string> = {
  queued: "○ Waiting", working: "● Working", done: "✓ Done", error: "▲ Failed", stopped: "■ Stopped",
};

function emojiOf(roster: RosterAgent[], agent: string): string {
  return roster.find((a) => a.name === agent)?.emoji || "🤖";
}

/** The boxes before they run. */
export function BoxEditor({ items, onChange, roster, compact, onDropAgent }: {
  items: BoxItem[];
  onChange: (items: BoxItem[]) => void;
  roster: RosterAgent[];
  compact?: boolean;
  onDropAgent?: (agent: string) => void;
}) {
  const [adding, setAdding] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const labels = useMemo(() => {
    const seen: Record<string, number> = {};
    return items.map((item) => { seen[item.agent] = (seen[item.agent] ?? 0) + 1; return `${item.agent} #${seen[item.agent]}`; });
  }, [items]);
  const groups = Array.from(new Set(items.map((i) => i.agent)));

  const update = (key: string, task: string) => onChange(items.map((i) => (i.key === key ? { ...i, task } : i)));
  const remove = (key: string) => onChange(items.filter((i) => i.key !== key));
  const another = (agent: string) => {
    const last = [...items].reverse().find((i) => i.agent === agent);
    onChange([...items, newBox(agent, last?.task ?? "")]);
  };

  return (
    <div
      className={`boxes${compact ? " boxes--compact" : ""}${dragOver ? " is-dragover" : ""}`}
      onDragOver={(e) => { if (e.dataTransfer.types.includes("application/x-nyx-agent")) { e.preventDefault(); setDragOver(true); } }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        const agent = e.dataTransfer.getData("application/x-nyx-agent");
        setDragOver(false);
        if (!agent) return;
        e.preventDefault();
        if (onDropAgent) onDropAgent(agent);
        else onChange([...items, newBox(agent)]);
      }}
    >
      {items.length === 0 && (
        <div className="boxes__empty">
          <span aria-hidden="true">⤓</span>
          Drag an agent here, or add one below. Drag the same agent again for a second box.
        </div>
      )}
      <ol className="boxes__list">
        {items.map((item, index) => (
          <li key={item.key} className="box">
            <div className="box__head">
              <span className="box__emoji" aria-hidden="true">{emojiOf(roster, item.agent)}</span>
              <b className="box__label">{labels[index]}</b>
              <button type="button" className="box__remove" onClick={() => remove(item.key)} aria-label={`Remove ${labels[index]}`}>✕</button>
            </div>
            <textarea
              className="box__task"
              rows={compact ? 2 : 3}
              value={item.task}
              placeholder={`What should ${labels[index]} do?`}
              aria-label={`Task for ${labels[index]}`}
              onChange={(e) => update(item.key, e.target.value)}
            />
          </li>
        ))}
      </ol>
      <div className="boxes__add">
        {groups.map((agent) => (
          <button key={agent} type="button" className="chip boxes__another" onClick={() => another(agent)}>
            + Another {agent}
          </button>
        ))}
        <label className="boxes__pick">
          <span className="sr-only">Add an agent</span>
          <select value={adding} onChange={(e) => { if (e.target.value) { onChange([...items, newBox(e.target.value)]); setAdding(""); } }}>
            <option value="">+ Add an agent…</option>
            {roster.map((a) => <option key={a.name} value={a.name}>{a.emoji} {a.name}</option>)}
          </select>
        </label>
      </div>
    </div>
  );
}

/** Start a dispatch from boxes. Returns the dispatch or null (a toast says why). */
export async function runBoxes(items: BoxItem[], opts: { chatId?: string; context?: string; project?: { name?: string; path?: string } } = {}) {
  const empty = items.find((i) => !i.task.trim());
  if (items.length === 0) { pushToast("Add at least one agent box.", "warn"); return null; }
  if (empty) { pushToast(`Say what ${empty.agent} should do.`, "warn"); return null; }
  const result = await api.post<{ dispatch: DispatchView }>("/api/dispatch", {
    items: items.map((i) => ({ agent: i.agent, task: i.task.trim() })), chat_id: opts.chatId ?? "",
    context: opts.context ?? "", project: opts.project ?? {},
  }, 30_000);
  if (!result.ok) { pushToast(result.error, "warn"); return null; }
  return result.data.dispatch;
}

/** Live boxes for one dispatch. */
export function DispatchCard({ initial, roster, onClose, compact }: {
  initial: DispatchView; roster: RosterAgent[]; onClose?: () => void; compact?: boolean;
}) {
  const [dispatch, setDispatch] = useState(initial);
  const [open, setOpen] = useState<number | null>(null);
  const [adding, setAdding] = useState<{ agent: string; task: string } | null>(null);
  const idRef = useRef(initial.dispatch_id);

  useEffect(() => { setDispatch(initial); idRef.current = initial.dispatch_id; }, [initial]);
  useEffect(() => onWorkspaceEvent((event) => {
    const next = event.dispatch as DispatchView | undefined;
    if (event.type === "agents.dispatch" && next?.dispatch_id === idRef.current) setDispatch(next);
  }), []);
  // Events can be missed while the stream reconnects: poll gently while running.
  useEffect(() => {
    if (dispatch.status !== "running") return;
    const timer = window.setInterval(async () => {
      const result = await api.get<{ dispatch: DispatchView }>(`/api/dispatch/${idRef.current}`);
      if (result.ok) setDispatch(result.data.dispatch);
    }, 4000);
    return () => window.clearInterval(timer);
  }, [dispatch.status]);

  async function add() {
    if (!adding?.agent || !adding.task.trim()) return;
    const result = await api.post<{ dispatch: DispatchView }>(`/api/dispatch/${dispatch.dispatch_id}/add`, adding);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setDispatch(result.data.dispatch);
    setAdding(null);
  }
  async function stop() {
    const result = await api.post<{ dispatch: DispatchView }>(`/api/dispatch/${dispatch.dispatch_id}/stop`);
    if (result.ok) setDispatch(result.data.dispatch);
  }

  const total = dispatch.instances.length || 1;
  const finished = (dispatch.counts.done ?? 0) + (dispatch.counts.error ?? 0) + (dispatch.counts.stopped ?? 0);
  const head = Object.entries(dispatch.agents).map(([a, n]) => (n > 1 ? `${n}× ${a}` : a)).join(" + ");

  return (
    <section className={`dispatch${compact ? " dispatch--compact" : ""} is-${dispatch.status}`} aria-label={`Agents: ${head}`}>
      <header className="dispatch__head">
        <span className="dispatch__title">
          {dispatch.status === "running" ? <span className="dispatch__pulse" aria-hidden="true" /> : <span aria-hidden="true">✓</span>}
          <b>{head}</b>
          {dispatch.origin === "nyx" && <span className="chip">Nyx sent them</span>}
          {dispatch.project?.name && <span className="chip">📁 {dispatch.project.name}</span>}
        </span>
        <span className="dispatch__count" aria-live="polite">{finished}/{total} finished</span>
        {dispatch.status === "running" && <button type="button" className="btn btn-secondary" onClick={() => void stop()}>Stop</button>}
        {onClose && dispatch.status !== "running" && <button type="button" className="box__remove" onClick={onClose} aria-label="Close">✕</button>}
      </header>
      <div className="dispatch__bar" role="progressbar" aria-valuemin={0} aria-valuemax={total} aria-valuenow={finished}>
        <span style={{ width: `${(finished / total) * 100}%` }} />
      </div>
      <ol className="dispatch__list">
        {dispatch.instances.map((inst) => (
          <li key={inst.index} className={`dispatch__item is-${inst.status}`}>
            <button type="button" className="dispatch__row" aria-expanded={open === inst.index}
              onClick={() => setOpen(open === inst.index ? null : inst.index)}>
              <span className="box__emoji" aria-hidden="true">{inst.emoji || emojiOf(roster, inst.agent)}</span>
              <span className="dispatch__who"><b>{inst.label}</b><span>{inst.task}</span></span>
              <span className={`dispatch__status is-${inst.status}`}>{STATUS_TEXT[inst.status]}</span>
            </button>
            {inst.status === "working" && (inst.understanding || inst.step) && (
              <div className="dispatch__step">{inst.understanding ? `Understood: ${inst.understanding}` : inst.step}</div>
            )}
            {/* Click a box: what it was asked (task + context, as sent) and what it answered (U46). */}
            {open === inst.index && (
              <div className="dispatch__report">
                <Handoff task={inst.task} context={inst.context} report={inst.report}
                  working={inst.status === "working" || inst.status === "queued"} replyOpen />
              </div>
            )}
          </li>
        ))}
      </ol>
      {adding ? (
        <form className="dispatch__adding" onSubmit={(e) => { e.preventDefault(); void add(); }}>
          <select value={adding.agent} onChange={(e) => setAdding({ ...adding, agent: e.target.value })} aria-label="Agent">
            {roster.map((a) => <option key={a.name} value={a.name}>{a.emoji} {a.name}</option>)}
          </select>
          <input value={adding.task} placeholder="What should this one do?" autoFocus aria-label="Task for the new box"
            onChange={(e) => setAdding({ ...adding, task: e.target.value })} />
          <button className="btn btn-primary" disabled={!adding.task.trim()}>Add</button>
          <button type="button" className="btn btn-secondary" onClick={() => setAdding(null)}>Cancel</button>
        </form>
      ) : (
        <button type="button" className="chat-inline dispatch__more"
          onClick={() => setAdding({ agent: dispatch.instances[0]?.agent ?? roster[0]?.name ?? "", task: "" })}>
          + Another box
        </button>
      )}
    </section>
  );
}

/** The editor as a dialog over the chat: opened by /coder [3] … or an agent chip. */
export function DispatchSheet({ text, chatId, onClose, onStarted }: {
  text: string; chatId: string; onClose: () => void; onStarted: (dispatch: DispatchView) => void;
}) {
  const roster = useRoster();
  const [items, setItems] = useState<BoxItem[]>([]);
  const [context, setContext] = useState("");
  const [busy, setBusy] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    void api.post<{ items: { agent: string; task: string }[]; shared: string }>("/api/dispatch/parse", { text }).then((result) => {
      if (!alive || !result.ok) return;
      setItems(result.data.items.map((i) => newBox(i.agent, i.task)));
    });
    return () => { alive = false; };
  }, [text]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    dialog.current?.querySelector<HTMLTextAreaElement>("textarea")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, items.length === 0]);

  async function run() {
    setBusy(true);
    const dispatch = await runBoxes(items, { chatId, context });
    setBusy(false);
    if (dispatch) { onStarted(dispatch); onClose(); }
  }

  // A portal: the chat sheet's backdrop blur would otherwise trap this fixed dialog inside the sheet.
  return createPortal(
    <div className="dispatch-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={dialog} className="dispatch-sheet" role="dialog" aria-modal="true" aria-labelledby="dispatch-sheet-title">
        <header className="dispatch-sheet__head">
          <h2 id="dispatch-sheet-title">Put agents on it</h2>
          <span className="muted">{items.length} box{items.length === 1 ? "" : "es"} · each copy works on its own task, at the same time</span>
          <button type="button" className="box__remove" onClick={onClose} aria-label="Close">✕</button>
        </header>
        <BoxEditor items={items} onChange={setItems} roster={roster} />
        <label className="dispatch-sheet__context">
          <span>Shared context <em className="muted">optional — every box gets it</em></span>
          <textarea rows={2} value={context} onChange={(e) => setContext(e.target.value)} placeholder="Links, files, constraints…" />
        </label>
        <footer className="dispatch-sheet__foot">
          <button type="button" className="btn btn-secondary" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={() => void run()} disabled={busy || items.length === 0}>
            {busy ? "Starting…" : `Run ${items.length} ${items.length === 1 ? "Agent" : "Agents"}`}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
