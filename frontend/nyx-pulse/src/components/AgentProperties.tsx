/** An agent's Properties: what it is for, which model it thinks with, what it may use.
 *
 * Request G16b: "if I make a sub agent or second agent… a place where I can see
 * the agent and click on properties to change the model used, objective, and
 * such." Opened from the Team dock, the Agents tab, or an agent chip in chat.
 *
 * A sheet, not a page: one short task with an obvious way out (modality.md).
 * Edits to built-in agents are stored as an overlay on the server, so an update
 * to the shipped team never overwrites them.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useProviders } from "./ProviderPicker";
import { pushToast } from "../state/toastStore";
import { ConsultFields } from "../panels/SubAgentsPanel";

interface AgentProps {
  name: string;
  id: string;
  role: string;
  emoji: string;
  color: string;
  goal: string;
  instructions: string;
  expertise: string[];
  tools: string[];
  provider: string;
  model: string;
  purpose: string;
  consult: "off" | "heavy" | "always";
  consult_with: string[];
  consult_models: "same" | "other" | "both";
  builtin: boolean;
  edited: boolean;
  created_in_chat: string;
  live: {
    status?: string;
    current_step?: string;
    tasks_completed?: number;
    recent?: { task?: string; result?: string; ok?: boolean; seconds?: number; at?: number }[];
    last_error?: string;
  };
}

type Draft = Pick<AgentProps, "name" | "emoji" | "goal" | "instructions" | "provider" | "model" | "purpose" | "consult" | "consult_with" | "consult_models"> & {
  expertise: string;
  allTools: boolean;
  tools: string[];
};

function toDraft(a: AgentProps): Draft {
  return {
    name: a.name, emoji: a.emoji, goal: a.goal, instructions: a.instructions, provider: a.provider, model: a.model,
    purpose: a.purpose ?? "", consult: a.consult ?? "heavy", consult_with: a.consult_with ?? [], consult_models: a.consult_models ?? "both",
    expertise: a.expertise.join(", "), allTools: a.tools.includes("*"), tools: a.tools.filter((t) => t !== "*"),
  };
}

export function AgentProperties({ name, onClose, onRenamed }: {
  name: string;
  onClose: () => void;
  onRenamed?: (name: string) => void;
}) {
  const [agent, setAgent] = useState<AgentProps | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [models, setModels] = useState<{ id: string; label?: string }[]>([]);
  const [allTools, setAllTools] = useState<{ name: string; category: string }[]>([]);
  const [toolFilter, setToolFilter] = useState("");
  const [task, setTask] = useState("");
  const [teamNames, setTeamNames] = useState<string[]>([]);
  const { snapshot } = useProviders();
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const result = await api.get<{ agent: AgentProps }>(`/api/agents/${encodeURIComponent(name)}/properties`);
      if (!alive) return;
      if (!result.ok) { setError(result.error); return; }
      setAgent(result.data.agent);
      setDraft(toDraft(result.data.agent));
    })();
    void api.get<{ tools: { name: string; category: string }[] }>("/api/tools").then((r) => { if (alive && r.ok) setAllTools(r.data.tools); });
    void api.get<{ agents: { name: string; role: string }[] }>("/api/agents/details").then((r) => {
      if (alive && r.ok) setTeamNames(r.data.agents.filter((a) => a.role !== "master").map((a) => a.name));
    });
    return () => { alive = false; };
  }, [name]);

  useEffect(() => {
    if (!draft?.provider) { setModels([]); return; }
    let alive = true;
    void api.get<{ models: { id: string; label?: string }[] }>(`/api/models/catalog?provider=${encodeURIComponent(draft.provider)}&job=text`)
      .then((r) => { if (alive) setModels(r.ok ? r.data.models : []); });
    return () => { alive = false; };
  }, [draft?.provider]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    panelRef.current?.querySelector<HTMLElement>("textarea, input")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, agent]);

  const dirty = useMemo(() => agent && draft && JSON.stringify(toDraft(agent)) !== JSON.stringify(draft), [agent, draft]);
  const shownTools = allTools.filter((t) => !toolFilter || t.name.includes(toolFilter.toLowerCase()) || t.category.includes(toolFilter.toLowerCase()));

  async function save() {
    if (!agent || !draft) return;
    setSaving(true);
    setError("");
    const body = {
      name: draft.name, emoji: draft.emoji, goal: draft.goal, instructions: draft.instructions,
      provider: draft.provider, model: draft.provider ? draft.model : "",
      purpose: draft.purpose, consult: draft.consult, consult_with: draft.consult_with, consult_models: draft.consult_models,
      expertise: draft.expertise.split(",").map((s) => s.trim()).filter(Boolean),
      tools: draft.allTools ? ["*"] : draft.tools,
    };
    const result = await api.patch<{ agent: AgentProps }>(`/api/agents/${encodeURIComponent(agent.name)}`, body);
    setSaving(false);
    if (!result.ok) { setError(result.error); return; }
    setAgent(result.data.agent);
    setDraft(toDraft(result.data.agent));
    if (result.data.agent.name !== name) onRenamed?.(result.data.agent.name);
    pushToast(`${result.data.agent.emoji} ${result.data.agent.name} updated.`, "ok");
  }

  async function runTask() {
    if (!agent || !task.trim()) return;
    const result = await api.post<{ turn_id: string }>(`/api/agents/${encodeURIComponent(agent.name)}/tasks`, { task: task.trim() }, 60_000);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setTask("");
    pushToast(`${agent.name} is working on it — watch the Team dock.`, "ok");
  }

  const isMaster = agent?.role === "master";
  const live = agent?.live ?? {};

  return (
    <div className="agent-props__scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={panelRef} className="agent-props" role="dialog" aria-modal="true" aria-label={`${name} properties`}>
        <header className="agent-props__head">
          {draft ? (
            <>
              <input className="agent-props__emoji" value={draft.emoji} maxLength={4} aria-label="Emoji"
                onChange={(e) => setDraft({ ...draft, emoji: e.target.value })} />
              <input className="agent-props__name" value={draft.name} maxLength={40} aria-label="Name" disabled={isMaster}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </>
          ) : <div className="agent-props__name">{name}</div>}
          <span className={`agent-props__status is-${live.status ?? "idle"}`}>{live.status ?? "idle"}</span>
          <button className="btn btn-secondary" onClick={onClose} aria-label="Close properties">Done</button>
        </header>

        {error && <div className="agent-props__error" role="alert">{error}</div>}
        {!draft && !error && <div className="agent-props__body muted">Loading…</div>}

        {draft && agent && (
          <div className="agent-props__body">
            <p className="agent-props__meta">
              {isMaster ? "Manages the team — every chat goes through it." : agent.builtin ? "Built-in agent" : "Made in chat"}
              {agent.edited ? " · edited" : ""}
              {typeof live.tasks_completed === "number" ? ` · ${live.tasks_completed} tasks done` : ""}
              {live.current_step ? ` · now: ${live.current_step}` : ""}
            </p>

            <label className="agent-props__field">
              <span>Goal</span>
              <textarea rows={2} value={draft.goal} maxLength={300} onChange={(e) => setDraft({ ...draft, goal: e.target.value })} />
            </label>

            <label className="agent-props__field">
              <span>Purpose</span>
              <textarea rows={2} value={draft.purpose} maxLength={600} placeholder="Why it exists and what a great result looks like"
                onChange={(e) => setDraft({ ...draft, purpose: e.target.value })} />
            </label>

            <div className="agent-props__row">
              <label className="agent-props__field">
                <span>Provider</span>
                <select value={draft.provider} onChange={(e) => setDraft({ ...draft, provider: e.target.value, model: "" })}>
                  <option value="">Auto — same as chat</option>
                  {(snapshot?.providers ?? []).map((p) => (
                    <option key={p.name} value={p.name}>{p.name}{p.configured ? "" : " (no key)"}</option>
                  ))}
                </select>
              </label>
              <label className="agent-props__field">
                <span>Model</span>
                <input list="agent-props-models" value={draft.model} disabled={!draft.provider}
                  placeholder={draft.provider ? "Provider's default" : "Pick a provider first"}
                  onChange={(e) => setDraft({ ...draft, model: e.target.value })} />
                <datalist id="agent-props-models">
                  {models.map((m) => <option key={m.id} value={m.id}>{m.label ?? m.id}</option>)}
                </datalist>
              </label>
            </div>

            <ConsultFields
              consult={draft.consult} consultModels={draft.consult_models} consultWith={draft.consult_with}
              candidates={teamNames} self={agent.name}
              onChange={(next) => setDraft({ ...draft, ...next })} />

            <label className="agent-props__field">
              <span>Instructions</span>
              <textarea rows={4} value={draft.instructions} maxLength={4000}
                placeholder="How it should work — tone, steps, what to check before reporting back."
                onChange={(e) => setDraft({ ...draft, instructions: e.target.value })} />
            </label>

            <label className="agent-props__field">
              <span>Expertise</span>
              <input value={draft.expertise} placeholder="Comma-separated, e.g. python, debugging"
                onChange={(e) => setDraft({ ...draft, expertise: e.target.value })} />
            </label>

            <fieldset className="agent-props__field agent-props__tools">
              <legend>Tools</legend>
              <div className="segmented" role="group" aria-label="Tool access">
                <button type="button" aria-pressed={draft.allTools} onClick={() => setDraft({ ...draft, allTools: true })}>All tools</button>
                <button type="button" aria-pressed={!draft.allTools} onClick={() => setDraft({ ...draft, allTools: false })}>Only these</button>
              </div>
              {!draft.allTools && (
                <>
                  <input value={toolFilter} placeholder={`Filter ${allTools.length} tools`} aria-label="Filter tools"
                    onChange={(e) => setToolFilter(e.target.value)} />
                  <div className="agent-props__toollist">
                    {shownTools.map((t) => (
                      <label key={t.name}>
                        <input type="checkbox" checked={draft.tools.includes(t.name)}
                          onChange={(e) => setDraft({ ...draft, tools: e.target.checked ? [...draft.tools, t.name] : draft.tools.filter((x) => x !== t.name) })} />
                        <span>{t.name}</span><span className="muted">{t.category}</span>
                      </label>
                    ))}
                  </div>
                  <div className="muted" style={{ fontSize: 12 }}>{draft.tools.length} selected</div>
                </>
              )}
            </fieldset>

            {!isMaster && (
              <div className="agent-props__field">
                <span>Give it a task</span>
                <div className="agent-props__task">
                  <input value={task} placeholder={`What should ${agent.name} do?`}
                    onChange={(e) => setTask(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") void runTask(); }} />
                  <button className="btn btn-secondary" disabled={!task.trim()} onClick={() => void runTask()}>Run</button>
                </div>
              </div>
            )}

            {(live.recent?.length ?? 0) > 0 && (
              <div className="agent-props__field">
                <span>Recent work</span>
                <ul className="agent-props__recent">
                  {live.recent!.slice().reverse().map((r, i) => (
                    <li key={i}>
                      <div className="agent-props__task-title">{r.ok === false ? "⚠ " : ""}{r.task}</div>
                      {r.result && <div className="muted">{r.result.slice(0, 220)}</div>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {draft && (
          <footer className="agent-props__foot">
            <button className="btn btn-secondary" disabled={!dirty || saving} onClick={() => agent && setDraft(toDraft(agent))}>Revert</button>
            <button className="btn btn-primary" disabled={!dirty || saving} onClick={() => void save()}>
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </footer>
        )}
      </div>
    </div>
  );
}
