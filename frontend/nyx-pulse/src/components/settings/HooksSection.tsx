/** Settings › Safety › Hooks: your own commands that run when something happens in a chat, like Claude Code's hooks.
 *
 * Drive doc 1 item 1.29. The engine side is user_hooks.py. A before-tool hook that exits with code 2 stops the tool;
 * a prompt hook's printed text is added to that turn. Everything else runs in the background and is only logged.
 */

import { useEffect, useState } from "react";
import { api } from "../../api";

interface Hook { id: string; name: string; event: string; match: string; command: string; timeout: number; enabled: boolean }
interface HookRun { hook: string; name: string; event: string; code: number | null; stderr: string; ms: number; at: number }
interface HooksState { enabled: boolean; events: string[]; hooks: Hook[]; recent: HookRun[] }

const EVENT_LABEL: Record<string, string> = {
  before_tool: "Before a tool runs (exit 2 stops it)",
  after_tool: "After a tool runs",
  prompt: "When you send a message (what it prints is added)",
  reply_done: "When a reply finishes",
};

export function HooksSection() {
  const [state, setState] = useState<HooksState | null>(null);
  const [draft, setDraft] = useState({ name: "", event: "before_tool", match: "*", command: "" });
  const [note, setNote] = useState("");

  useEffect(() => { void api.get<HooksState>("/api/hooks").then((r) => { if (r.ok) setState(r.data); }); }, []);
  if (state === null) return null;

  const done = (r: { ok: boolean; data?: HooksState; error?: string }, ok = "") => {
    if (r.ok && r.data) { setState(r.data); setNote(ok); } else setNote(r.error || "That didn't work.");
  };
  const add = async () => {
    const r = await api.post<HooksState>("/api/hooks", draft);
    done(r, "Hook added.");
    if (r.ok) setDraft({ ...draft, name: "", command: "" });
  };

  return (
    <div className="memories">
      <div className="memories__bar">
        <label className="memories__keep">
          <input type="checkbox" checked={state.enabled}
            onChange={async (e) => done(await api.put<HooksState>("/api/hooks", { enabled: e.target.checked }))} />
          Run my hooks
        </label>
        {note && <span className="memories__note" role="status">{note}</span>}
      </div>
      {state.hooks.length === 0 && (
        <div className="memories__empty">No hooks yet. A hook gets the event as JSON on its input.</div>
      )}
      <ul className="memories__list">
        {state.hooks.map((h) => (
          <li key={h.id} className="memories__item">
            <div className="memories__head">
              <span className="memories__topic">{h.name || h.command}</span>
              <span className="memories__badge">{h.event.replace("_", " ")}{h.match !== "*" ? ` · ${h.match}` : ""}</span>
            </div>
            <div className="memories__content"><code>{h.command}</code></div>
            <div className="memories__meta">
              <label className="memories__keep">
                <input type="checkbox" checked={h.enabled}
                  onChange={async (e) => done(await api.patch<HooksState>(`/api/hooks/${h.id}`, { enabled: e.target.checked }))} />
                On
              </label>
              <button type="button" className="btn btn-ghost"
                onClick={async () => done(await api.del<HooksState>(`/api/hooks/${h.id}`), "Hook removed.")}>Remove</button>
            </div>
          </li>
        ))}
      </ul>
      <form className="memories__form" onSubmit={(e) => { e.preventDefault(); if (draft.command.trim()) void add(); }}>
        <input className="text-input" value={draft.name} placeholder="Name (optional)" aria-label="Hook name"
          onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <select className="text-input" value={draft.event} aria-label="When it runs"
          onChange={(e) => setDraft({ ...draft, event: e.target.value })}>
          {state.events.map((ev) => <option key={ev} value={ev}>{EVENT_LABEL[ev] ?? ev}</option>)}
        </select>
        {(draft.event === "before_tool" || draft.event === "after_tool") && (
          <input className="text-input" value={draft.match} placeholder="Which tools, e.g. run_command or file_*"
            aria-label="Which tools" onChange={(e) => setDraft({ ...draft, match: e.target.value })} />
        )}
        <input className="text-input" value={draft.command} placeholder="Command, e.g. python C:\hooks\check.py"
          aria-label="Command" onChange={(e) => setDraft({ ...draft, command: e.target.value })} />
        <div className="memories__actions">
          <button type="submit" className="btn" disabled={!draft.command.trim()}>Add hook</button>
        </div>
      </form>
      {state.recent.length > 0 && (
        <ul className="self-approval__log">
          {state.recent.slice(0, 6).map((run) => (
            <li key={`${run.hook}-${run.at}`} title={run.stderr}>
              <b>{run.name}</b> · {run.event.replace("_", " ")} · {run.code === null ? run.stderr : `exit ${run.code}`} · {run.ms} ms
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
