/** Sub-agents: put a specialist on the case with the model you choose (Request H2).
 *
 * "Make a tab specifically for when I want a sub agent on the case where I select the model."
 * Left: one form — name, goal, purpose, the model it thinks with, whether and with whom it
 * consults, and (optionally) the task to start on right away. Right: the sub-agents already made,
 * with what they are doing, their model, and Edit / Give Task / Delete.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useProviders } from "../components/ProviderPicker";
import { AgentProperties } from "../components/AgentProperties";
import { CONSULT_MODELS_TEXT, CONSULT_TEXT, modelText, type AgentDetail } from "../components/AgentDetails";
import { Toasts } from "../components/chat";
import { dismissToast, pushToast, useToasts } from "../state/toastStore";
import { onWorkspaceEvent } from "../state/workspaceEvents";
import { DispatchCard, DispatchSheet, useRoster, type DispatchView } from "../components/agents/AgentBoxes";

/** The /command an agent answers to (same rule as the server's agent_slug). */
const slugOf = (name: string) => name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 32);

interface Form {
  name: string; emoji: string; goal: string; purpose: string; provider: string; model: string;
  consult: AgentDetail["consult"]; consult_models: AgentDetail["consult_models"]; consult_with: string[]; task: string;
  /** Owner request: start it on nothing, on a background task, or in its own chat. */
  start: "idle" | "task" | "chat";
}

interface ChatSummary { id: string; title: string; agent?: string; message_count?: number }

const EMPTY: Form = { name: "", emoji: "🤖", goal: "", purpose: "", provider: "", model: "", consult: "heavy", consult_models: "both", consult_with: [], task: "", start: "idle" };

const START_CHOICES: { id: Form["start"]; label: string; hint: string }[] = [
  { id: "idle", label: "Just create it", hint: "It joins the team and waits to be asked." },
  { id: "task", label: "Start a task now", hint: "It works in the background; watch it in the Team dock." },
  { id: "chat", label: "Open its own chat", hint: "A chat that belongs to it — everything you send there, it answers." },
];

/** Open a chat in the Nyx tab. */
function openChat(chatId: string) {
  try { sessionStorage.setItem("nyx.chat.open", chatId); } catch { /* not kept */ }
  window.dispatchEvent(new CustomEvent("nyx:open-chat", { detail: { chatId } }));
  window.dispatchEvent(new CustomEvent("nyx:open-tab", { detail: { tab: "nyx" } }));
}

export function SubAgentsPanel() {
  const [form, setForm] = useState<Form>(EMPTY);
  const [agents, setAgents] = useState<AgentDetail[]>([]);
  const [models, setModels] = useState<{ id: string; label?: string }[]>([]);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [tasks, setTasks] = useState<Record<string, string>>({});
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const { snapshot } = useProviders();
  const toasts = useToasts();
  const roster = useRoster();
  /** "Run copies" opens the agent boxes (owner request, 2026-09-16). */
  const [boxesFor, setBoxesFor] = useState<string | null>(null);
  const [dispatches, setDispatches] = useState<DispatchView[]>([]);

  const load = useCallback(async () => {
    const [details, list] = await Promise.all([
      api.get<{ agents: AgentDetail[] }>("/api/agents/details"),
      api.get<{ chats: ChatSummary[] }>("/api/chats/summaries"),
    ]);
    if (details.ok) setAgents(details.data.agents);
    if (list.ok) setChats(list.data.chats.filter((chat) => chat.agent));
  }, []);
  useEffect(() => {
    void load();
    return onWorkspaceEvent((event) => {
      if (event.type === "agents.changed" || event.type === "agent.updated" || event.type === "agent.update") void load();
    });
  }, [load]);

  useEffect(() => {
    if (!form.provider) { setModels([]); return; }
    let alive = true;
    void api.get<{ models: { id: string; label?: string }[] }>(`/api/models/catalog?provider=${encodeURIComponent(form.provider)}&job=text`)
      .then((r) => { if (alive) setModels(r.ok ? r.data.models : []); });
    return () => { alive = false; };
  }, [form.provider]);

  const made = agents.filter((a) => !a.builtin && a.role !== "master");
  const everyone = agents.filter((a) => a.role !== "master");

  async function create() {
    setSaving(true);
    const body = { ...form, start_chat: form.start === "chat", task: form.start === "idle" ? "" : form.task };
    const result = await api.post<{ agent: AgentDetail; started: { turn_id?: string } | null; chat_id?: string; task?: string }>(
      "/api/agents/subagents", body, 60_000);
    setSaving(false);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    const made = result.data.agent;
    if (result.data.chat_id) {
      pushToast(`${made.emoji} ${made.name} has its own chat now.`, "ok", { label: "Open", onClick: () => openChat(result.data.chat_id!) });
      if (result.data.task) {
        try { sessionStorage.setItem("nyx.chat.prefill", result.data.task); } catch { /* not kept */ }
      }
      openChat(result.data.chat_id);
    } else {
      pushToast(result.data.started ? `${made.emoji} ${made.name} is on the case.` : `${made.emoji} ${made.name} joined the team.`, "ok");
    }
    setForm(EMPTY);
    void load();
  }

  /** Give an agent a chat of its own (or open the one it has). */
  async function agentChat(name: string) {
    const existing = chats.find((chat) => (chat.agent ?? "").toLowerCase() === name.toLowerCase());
    if (existing) { openChat(existing.id); return; }
    const created = await api.post<{ chat: { id: string } }>("/api/chats", { title: name });
    if (!created.ok) { pushToast(created.error, "warn"); return; }
    const chatId = created.data.chat.id;
    const linked = await api.post(`/api/chats/${chatId}/agent`, { agent: name });
    if (!linked.ok) { pushToast(linked.error, "warn"); return; }
    void load();
    openChat(chatId);
  }

  async function giveTask(name: string) {
    const task = (tasks[name] ?? "").trim();
    if (!task) return;
    const result = await api.post(`/api/agents/${encodeURIComponent(name)}/tasks`, { task }, 60_000);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    setTasks((t) => ({ ...t, [name]: "" }));
    pushToast(`${name} is working on it.`, "ok");
  }

  async function remove(name: string) {
    const result = await api.del(`/api/agents/subagents/${encodeURIComponent(name)}`);
    setConfirmDelete(null);
    if (!result.ok) { pushToast(result.error, "warn"); return; }
    pushToast(`${name} was removed. Chats it worked in keep their history.`, "ok");
    void load();
  }

  return (
    <div className="subagents">
      <form className="subagents__form" onSubmit={(e) => { e.preventDefault(); if (form.name.trim() && form.goal.trim() && !saving) void create(); }}>
        <h1>New Sub-agent</h1>
        <p className="muted">A specialist with its own model. Nyx's Manager can hand it work, and so can you.</p>

        <div className="subagents__row subagents__row--name">
          <label className="agent-props__field subagents__emoji">
            <span>Icon</span>
            <input value={form.emoji} maxLength={4} onChange={(e) => setForm({ ...form, emoji: e.target.value })} aria-label="Emoji" />
          </label>
          <label className="agent-props__field">
            <span>Name</span>
            <input value={form.name} maxLength={40} placeholder="e.g. Price Scout" onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
        </div>
        <label className="agent-props__field">
          <span>Goal</span>
          <textarea rows={2} maxLength={300} value={form.goal} placeholder="What it works on — e.g. compare laptop prices across stores"
            onChange={(e) => setForm({ ...form, goal: e.target.value })} />
        </label>
        <label className="agent-props__field">
          <span>Purpose <em className="muted">optional</em></span>
          <textarea rows={2} maxLength={600} value={form.purpose} placeholder="Why it exists and what a great result looks like"
            onChange={(e) => setForm({ ...form, purpose: e.target.value })} />
        </label>

        <div className="agent-props__row">
          <label className="agent-props__field">
            <span>Model provider</span>
            <select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value, model: "" })}>
              <option value="">Auto — same as chat</option>
              {(snapshot?.providers ?? []).map((p) => (
                <option key={p.name} value={p.name} disabled={!p.configured}>{p.name}{p.configured ? "" : p.name === "ollama" ? " (not running)" : " (add a key first)"}</option>
              ))}
            </select>
          </label>
          <label className="agent-props__field">
            <span>Model</span>
            <input list="subagent-models" value={form.model} disabled={!form.provider}
              placeholder={form.provider ? "Provider's default" : "Pick a provider first"}
              onChange={(e) => setForm({ ...form, model: e.target.value })} />
            <datalist id="subagent-models">
              {models.map((m) => <option key={m.id} value={m.id}>{m.label ?? m.id}</option>)}
            </datalist>
          </label>
        </div>

        <ConsultFields
          consult={form.consult} consultModels={form.consult_models} consultWith={form.consult_with}
          candidates={everyone.map((a) => a.name)}
          onChange={(next) => setForm({ ...form, ...next })} />

        <fieldset className="agent-props__field subagents__start">
          <legend>How it starts</legend>
          <div className="segmented" role="group" aria-label="How it starts">
            {START_CHOICES.map((choice) => (
              <button key={choice.id} type="button" aria-pressed={form.start === choice.id} onClick={() => setForm({ ...form, start: choice.id })}>
                {choice.label}
              </button>
            ))}
          </div>
          <p className="muted subagents__hint">{START_CHOICES.find((c) => c.id === form.start)?.hint}</p>
          {form.start !== "idle" && (
            <textarea rows={2} value={form.task}
              placeholder={form.start === "chat" ? "First message for its chat (optional)" : "e.g. Find the three best 16-inch laptops under $900 this week"}
              aria-label="First task" onChange={(e) => setForm({ ...form, task: e.target.value })} />
          )}
        </fieldset>

        <div className="subagents__foot">
          <button type="button" className="btn btn-secondary" onClick={() => setForm(EMPTY)} disabled={saving}>Clear</button>
          <button className="btn btn-primary" disabled={!form.name.trim() || !form.goal.trim() || saving}>
            {saving ? "Creating…" : form.start === "chat" ? "Create and Open Chat" : form.start === "task" && form.task.trim() ? "Create and Start" : "Create Sub-agent"}
          </button>
        </div>
      </form>

      <section className="subagents__list" aria-label="Your sub-agents">
        <h2>Your Sub-agents <span className="muted">{made.length}</span></h2>
        {made.length === 0 && <p className="muted">None yet. Create one here, or ask in chat: “make a sub-agent that tracks my deadlines using groq”. Nyx also makes them by itself when a kind of work keeps coming up.</p>}
        {made.length > 0 && <p className="muted subagents__hint">Every agent is a / command too: type <code>/{slugOf(made[0].name)} [2] …</code> in chat for two copies with their own tasks.</p>}
        {dispatches.map((d) => (
          <DispatchCard key={d.dispatch_id} initial={d} roster={roster} compact onClose={() => setDispatches((c) => c.filter((x) => x.dispatch_id !== d.dispatch_id))} />
        ))}
        {made.map((a) => (
          <article key={a.name} className={`agent-card is-${a.live.status ?? "idle"}`}>
            <header className="agent-card__head">
              <span className="agent-card__emoji" aria-hidden="true">{a.emoji || "🤖"}</span>
              <div className="agent-card__who">
                <b>{a.name} {a.made_by === "nyx" && <span className="chip">made by Nyx</span>}</b>
                <span className="muted">{modelText(a)} · /{slugOf(a.name)}</span>
              </div>
              <span className={`agent-card__status is-${a.live.status ?? "idle"}`}>
                {a.live.status === "working" ? "● Working" : a.live.status === "error" ? "▲ Error" : "○ Idle"}
              </span>
              <button className="btn btn-secondary" onClick={() => void agentChat(a.name)}>
                {chats.some((chat) => (chat.agent ?? "").toLowerCase() === a.name.toLowerCase()) ? "Open Chat" : "Give It a Chat"}
              </button>
              <button className="btn btn-secondary" onClick={() => setBoxesFor(a.name)}>Run Copies</button>
              <button className="btn btn-secondary" onClick={() => setEditing(a.name)}>Edit</button>
            </header>
            <dl className="agent-card__facts">
              <dt>Goal</dt><dd>{a.goal}</dd>
              {a.purpose && (<><dt>Purpose</dt><dd>{a.purpose}</dd></>)}
              <dt>Consults</dt>
              <dd>{CONSULT_TEXT[a.consult]}{a.consult !== "off" && ` · ${CONSULT_MODELS_TEXT[a.consult_models]}`}{a.consult !== "off" && a.consult_with.length > 0 && ` · with ${a.consult_with.join(", ")}`}</dd>
              {a.live.current_step && (<><dt>Now</dt><dd>{a.live.current_step}</dd></>)}
              {chats.filter((chat) => (chat.agent ?? "").toLowerCase() === a.name.toLowerCase()).length > 0 && (
                <>
                  <dt>Its chats</dt>
                  <dd>
                    {chats.filter((chat) => (chat.agent ?? "").toLowerCase() === a.name.toLowerCase()).map((chat) => (
                      <button key={chat.id} className="chat-inline subagents__chatlink" onClick={() => openChat(chat.id)}>
                        {chat.title}{typeof chat.message_count === "number" ? ` · ${chat.message_count}` : ""}
                      </button>
                    ))}
                  </dd>
                </>
              )}
            </dl>
            <div className="agent-props__task">
              <input value={tasks[a.name] ?? ""} placeholder={`Give ${a.name} a task`} aria-label={`Task for ${a.name}`}
                onChange={(e) => setTasks((t) => ({ ...t, [a.name]: e.target.value }))}
                onKeyDown={(e) => { if (e.key === "Enter") void giveTask(a.name); }} />
              <button className="btn btn-secondary" disabled={!(tasks[a.name] ?? "").trim()} onClick={() => void giveTask(a.name)}>Start</button>
              {confirmDelete === a.name ? (
                <>
                  <button className="btn btn-danger" onClick={() => void remove(a.name)}>Delete {a.name}</button>
                  <button className="btn btn-secondary" onClick={() => setConfirmDelete(null)}>Keep</button>
                </>
              ) : (
                <button className="chat-inline" onClick={() => setConfirmDelete(a.name)}>Delete…</button>
              )}
            </div>
          </article>
        ))}
      </section>
      {editing && <AgentProperties name={editing} onClose={() => { setEditing(null); void load(); }} onRenamed={setEditing} />}
      {boxesFor && (
        <DispatchSheet text={`/${slugOf(boxesFor)} [2]`} chatId="" onClose={() => setBoxesFor(null)}
          onStarted={(d) => setDispatches((current) => [d, ...current])} />
      )}
      <Toasts items={toasts} onDismiss={dismissToast} />
    </div>
  );
}

export function ConsultFields({ consult, consultModels, consultWith, candidates, onChange, self }: {
  consult: AgentDetail["consult"];
  consultModels: AgentDetail["consult_models"];
  consultWith: string[];
  candidates: string[];
  self?: string;
  onChange: (next: { consult?: AgentDetail["consult"]; consult_models?: AgentDetail["consult_models"]; consult_with?: string[] }) => void;
}) {
  const others = candidates.filter((n) => n !== self);
  return (
    <fieldset className="agent-props__field subagents__consult">
      <legend>Consults other models and agents</legend>
      <div className="segmented" role="group" aria-label="When it consults">
        {(["off", "heavy", "always"] as const).map((mode) => (
          <button key={mode} type="button" aria-pressed={consult === mode} onClick={() => onChange({ consult: mode })}>
            {mode === "off" ? "Never" : mode === "heavy" ? "Hard tasks" : "Always"}
          </button>
        ))}
      </div>
      {consult !== "off" && (
        <>
          <div className="segmented" role="group" aria-label="Which models it asks">
            {(["same", "other", "both"] as const).map((mode) => (
              <button key={mode} type="button" aria-pressed={consultModels === mode} onClick={() => onChange({ consult_models: mode })}>
                {mode === "same" ? "Same model" : mode === "other" ? "Another model" : "Both"}
              </button>
            ))}
          </div>
          <details className="subagents__with">
            <summary>Also ask agents{consultWith.length ? ` (${consultWith.join(", ")})` : ""}</summary>
            <div className="agent-props__toollist">
              {others.map((name) => (
                <label key={name}>
                  <input type="checkbox" checked={consultWith.includes(name)} disabled={!consultWith.includes(name) && consultWith.length >= 4}
                    onChange={(e) => onChange({ consult_with: e.target.checked ? [...consultWith, name] : consultWith.filter((n) => n !== name) })} />
                  <span>{name}</span>
                </label>
              ))}
            </div>
          </details>
          <p className="muted subagents__hint">
            {consult === "heavy" ? "On hard tasks" : "Before every task"} it asks {CONSULT_MODELS_TEXT[consultModels]} for short notes first, then decides itself.
          </p>
        </>
      )}
    </fieldset>
  );
}
