/** Agents tab (ROADMAP BB6, B1, B4, B5).
 *
 * The live progress view Shagnik asked for: not a one-off chart, but a standing
 * panel showing what each agent is doing, and — when nothing is moving — why.
 * The two diagnoses it exists to give are "the machine is throttling you" and
 * "that goal is too vague to act on", because otherwise a stalled team looks
 * exactly like an idle one.
 */

import { useCallback, useEffect, useState } from "react";
import { agents as agentsApi, api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";
import { AgentProperties } from "../components/AgentProperties";

interface Agent {
  agent_id: string;
  name: string;
  goal: string;
  role: "master" | "worker";
  personality_id: string | null;
  status: "idle" | "working" | "blocked" | "error" | "done";
  current_step: string;
  steps_completed: number;
  elapsed_seconds: number;
  last_error: string;
}

interface ResourcePressure {
  throttled?: boolean;
  gpu_temp_c?: number;
  gpu_utilization?: number;
  telemetry_available?: boolean;
  summary?: string;
}

interface TeamSnapshot {
  agents: Agent[];
  total: number;
  working: number;
  blocked: number;
  errored: number;
  resource_pressure: ResourcePressure;
  vague_goals: string[];
  pool?: Record<string, unknown>;
}

const STATUS_COLOR: Record<Agent["status"], string> = {
  idle: "var(--color-neutral-600)",
  working: "var(--color-accent)",
  blocked: "var(--color-warn)",
  error: "var(--color-danger)",
  done: "var(--color-ok)",
};

const fieldStyle: React.CSSProperties = {
  padding: "7px 9px",
  background: "var(--color-nav)",
  color: "var(--color-text)",
  border: "none",
  borderRadius: "var(--radius)",
  boxShadow: "inset 0 0 0 1px var(--color-divider)",
  font: "inherit",
  fontSize: 13,
};

/** Name, goal, role — the three things POST /api/agents actually needs.
 *
 * The goal field is wide and prompts for detail on purpose: the panel already
 * flags goals too short to act on, and the cheapest place to prevent that is
 * before the agent exists.
 */
function CreateAgentForm({ onCreated, onCancel }: {
  onCreated: () => Promise<void>;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [goal, setGoal] = useState("");
  const [role, setRole] = useState<"worker" | "master">("worker");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy || !name.trim()) return;
    setBusy(true);
    setError("");
    const result = await agentsApi.create({ name: name.trim(), goal: goal.trim(), role });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setName("");
    setGoal("");
    setRole("worker");
    await onCreated();
  }

  return (
    <form onSubmit={submit} className="card" style={{ borderLeft: "3px solid var(--color-accent)" }}>
      <div className="label" style={{ marginBottom: 9 }}>New agent</div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Name, e.g. Researcher"
          autoFocus
          style={{ ...fieldStyle, flex: 1, minWidth: 0 }}
        />
        <select
          value={role}
          onChange={(e) => setRole(e.target.value as "worker" | "master")}
          style={{ ...fieldStyle, background: "var(--color-surface)" }}
          title="A master coordinates the team; a worker carries out its own goal"
        >
          <option value="worker">worker</option>
          <option value="master">master</option>
        </select>
      </div>
      <textarea
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        rows={2}
        placeholder="Goal — what this agent is for. Be specific; a vague goal is flagged below."
        style={{ ...fieldStyle, width: "100%", resize: "vertical", marginBottom: 8, lineHeight: 1.55 }}
      />
      {error && (
        <div style={{ fontSize: 12, color: "var(--color-danger)", marginBottom: 8, lineHeight: 1.5 }}>
          {error}
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={busy || !name.trim()}
          style={{ opacity: busy || !name.trim() ? 0.5 : 1 }}
        >
          {busy ? "Creating…" : "Create agent"}
        </button>
        <button type="button" className="btn btn-secondary" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function AgentRow({ agent, onDismiss, onProperties }: { agent: Agent; onDismiss: (id: string) => void; onProperties: (name: string) => void }) {
  const color = STATUS_COLOR[agent.status];
  const isMaster = agent.role === "master";
  return (
    <div style={{
      padding: "11px 0",
      boxShadow: "inset 0 -1px 0 var(--color-divider)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
        <span style={{
          width: 7, height: 7, borderRadius: "50%", background: color, flex: "none",
          animation: agent.status === "working" ? "nyxpulse 1.4s ease-in-out infinite" : undefined,
        }} />
        <span style={{ fontSize: 13, fontWeight: isMaster ? 600 : 400 }}>{agent.name}</span>
        {isMaster && (
          <span style={{
            fontSize: 12, letterSpacing: ".06em", textTransform: "uppercase",
            color: "var(--color-accent)",
          }}>
            manages the team
          </span>
        )}
        {agent.personality_id && (
          <span style={{ fontSize: 12, color: "var(--color-neutral-600)" }}>
            {agent.personality_id}
          </span>
        )}
        <span style={{
          marginLeft: "auto", fontSize: 12, fontFamily: "var(--font-mono)", color,
        }}>
          {agent.status}
        </span>
        <button
          className="btn btn-secondary"
          onClick={() => onProperties(agent.name)}
          title={`Objective, model and tools for ${agent.name}`}
          style={{ fontSize: 12, padding: "2px 9px" }}
        >
          Properties
        </button>
        <button
          className="btn btn-secondary"
          onClick={() => onDismiss(agent.agent_id)}
          title={isMaster
            ? "The master cannot be dismissed while workers depend on it"
            : `Dismiss ${agent.name}`}
          style={{ fontSize: 12, padding: "2px 9px", color: "var(--color-danger)" }}
        >
          Dismiss
        </button>
      </div>

      <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.55, marginBottom: 4 }}>
        {agent.goal || <em>no goal set</em>}
      </div>

      {agent.current_step && (
        <div style={{ fontSize: 12, color, marginBottom: 4 }}>→ {agent.current_step}</div>
      )}
      {agent.last_error && (
        <div style={{ fontSize: 12, color: "var(--color-danger)", marginBottom: 4 }}>
          {agent.last_error}
        </div>
      )}

      <div style={{
        display: "flex", gap: 14, fontSize: 12,
        color: "var(--color-neutral-600)", fontFamily: "var(--font-mono)",
      }}>
        <span>{agent.steps_completed} steps</span>
        <span>{agent.elapsed_seconds.toFixed(1)}s</span>
      </div>
    </div>
  );
}

export function AgentsPanel() {
  const [properties, setProperties] = useState<string | null>(null);
  const [team, setTeam] = useState<TeamSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [actionError, setActionError] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<TeamSnapshot>("/api/agents");
    if (result.ok) {
      setTeam(result.data);
      setError(null);
    } else {
      setError(result.error);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const result = await api.get<TeamSnapshot>("/api/agents");
      if (!alive) return;
      if (result.ok) {
        setTeam(result.data);
        setError(null);
      } else {
        setError(result.error);
      }
    };
    void tick();
    // Standing view, so it refreshes on its own rather than needing a reload.
    const timer = setInterval(tick, 3000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  // The backend refuses to dismiss the master while workers still depend on it,
  // and that refusal is the useful message — show it rather than swallowing it.
  async function dismiss(agentId: string) {
    setActionError("");
    const result = await agentsApi.remove<{ team: TeamSnapshot }>(agentId);
    if (!result.ok) {
      setActionError(result.error);
      return;
    }
    if (result.data?.team) setTeam(result.data.team);
    else await load();
  }

  if (error && !team) return <PanelShell title="Agents"><ErrorState error={error} /></PanelShell>;
  if (!team) return <PanelShell title="Agents"><Loading what="Reading team status" /></PanelShell>;

  const pressure = team.resource_pressure ?? {};
  const throttled = Boolean(pressure.throttled);

  return (
    <PanelShell
      title="Agents"
      subtitle={`${team.total} on the team · ${team.working} working`}
      actions={
        <button className="btn btn-primary" onClick={() => setCreating((v) => !v)}>
          {creating ? "Close" : "+ New agent"}
        </button>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {creating && (
          <CreateAgentForm
            onCancel={() => setCreating(false)}
            onCreated={async () => {
              setCreating(false);
              await load();
            }}
          />
        )}

        {actionError && (
          <div className="card" style={{ borderLeft: "3px solid var(--color-danger)" }}>
            <div style={{ fontSize: 13, color: "var(--color-danger)", lineHeight: 1.6 }}>
              {actionError}
            </div>
          </div>
        )}

        {throttled && (
          <div className="card" style={{ borderLeft: "3px solid var(--color-warn)" }}>
            <div className="label" style={{ marginBottom: 6 }}>Machine is limiting the team</div>
            <div style={{ fontSize: 13, color: "var(--color-warn)", lineHeight: 1.6 }}>
              The host is under load, so agents are running slower than they otherwise would.
              {typeof pressure.gpu_temp_c === "number" && ` GPU at ${pressure.gpu_temp_c}°C`}
              {typeof pressure.gpu_utilization === "number" && `, ${pressure.gpu_utilization}% utilised`}.
              This is throttling working as intended, not a stuck agent.
            </div>
          </div>
        )}

        {pressure.telemetry_available === false && (
          <div className="card" style={{ borderLeft: "3px solid var(--color-neutral-700)" }}>
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)", lineHeight: 1.6 }}>
              No hardware telemetry on this machine, so slowdowns cannot be attributed to
              resource pressure. Agent timings below are still accurate.
            </div>
          </div>
        )}

        {team.vague_goals.length > 0 && (
          <div className="card" style={{ borderLeft: "3px solid var(--color-warn)" }}>
            <div className="label" style={{ marginBottom: 6 }}>Goal may be too vague</div>
            <div style={{ fontSize: 13, color: "var(--color-neutral-400)", lineHeight: 1.6 }}>
              {team.vague_goals.join(", ")} {team.vague_goals.length === 1 ? "has" : "have"} a
              goal short enough that the agent may not have enough to act on. If one of these
              looks stuck, the prompt is the likely cause rather than the agent.
            </div>
          </div>
        )}

        <div className="card">
          <div style={{ display: "flex", alignItems: "center", marginBottom: 4 }}>
            <span className="label">Team</span>
            <button
              className="btn btn-secondary"
              onClick={() => setCreating(true)}
              style={{ marginLeft: "auto", fontSize: 12, padding: "4px 10px" }}
            >
              + New agent
            </button>
          </div>
          {team.agents.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
              No agents yet.
            </div>
          ) : (
            team.agents.map((a) => (
              <AgentRow key={a.agent_id} agent={a} onDismiss={(id) => void dismiss(id)} onProperties={setProperties} />
            ))
          )}
          <div style={{ fontSize: 12, color: "var(--color-neutral-600)", marginTop: 8, lineHeight: 1.5 }}>
            Four standing roles are seeded automatically, so the team is never empty. Dismissing
            one of those brings it back on the next refresh.
          </div>
        </div>

        {properties && <AgentProperties name={properties} onClose={() => { setProperties(null); void load(); }} onRenamed={setProperties} />}
      </div>
    </PanelShell>
  );
}
