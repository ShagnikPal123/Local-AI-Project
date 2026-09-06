/** Agents tab (ROADMAP BB6, B1, B4, B5).
 *
 * The live progress view Shagnik asked for: not a one-off chart, but a standing
 * panel showing what each agent is doing, and — when nothing is moving — why.
 * The two diagnoses it exists to give are "the machine is throttling you" and
 * "that goal is too vague to act on", because otherwise a stalled team looks
 * exactly like an idle one.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";

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

function AgentRow({ agent }: { agent: Agent }) {
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
            fontSize: 10, letterSpacing: ".06em", textTransform: "uppercase",
            color: "var(--color-accent)",
          }}>
            manages the team
          </span>
        )}
        {agent.personality_id && (
          <span style={{ fontSize: 10, color: "var(--color-neutral-600)" }}>
            {agent.personality_id}
          </span>
        )}
        <span style={{
          marginLeft: "auto", fontSize: 11, fontFamily: "var(--font-mono)", color,
        }}>
          {agent.status}
        </span>
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
        display: "flex", gap: 14, fontSize: 11,
        color: "var(--color-neutral-600)", fontFamily: "var(--font-mono)",
      }}>
        <span>{agent.steps_completed} steps</span>
        <span>{agent.elapsed_seconds.toFixed(1)}s</span>
      </div>
    </div>
  );
}

export function AgentsPanel() {
  const [team, setTeam] = useState<TeamSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const result = await api.get<TeamSnapshot>("/api/agents");
      if (!alive) return;
      if (result.ok) {
        setTeam(result.data);
        setError(null);
      } else {
        setError(result.error);
      }
    };
    void load();
    // Standing view, so it refreshes on its own rather than needing a reload.
    const timer = setInterval(load, 3000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  if (error && !team) return <PanelShell title="Agents"><ErrorState error={error} /></PanelShell>;
  if (!team) return <PanelShell title="Agents"><Loading what="Reading team status" /></PanelShell>;

  const pressure = team.resource_pressure ?? {};
  const throttled = Boolean(pressure.throttled);

  return (
    <PanelShell
      title="Agents"
      subtitle={`${team.total} on the team · ${team.working} working`}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
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
          <div className="label" style={{ marginBottom: 4 }}>Team</div>
          {team.agents.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--color-neutral-500)" }}>
              No agents yet.
            </div>
          ) : (
            team.agents.map((a) => <AgentRow key={a.agent_id} agent={a} />)
          )}
        </div>

        <div className="card" style={{ borderLeft: "3px solid var(--color-accent-700)" }}>
          <div className="label" style={{ marginBottom: 6 }}>Still to build</div>
          <div style={{ fontSize: 12, color: "var(--color-neutral-400)", lineHeight: 1.65 }}>
            Spawning agents from this panel, the master actually delegating work to workers
            (B1), auto scale-up and scale-down (B6), and the inter-agent message bus (B3).
            Agents can be created via <code style={{ fontFamily: "var(--font-mono)" }}>POST /api/agents</code>{" "}
            today, but nothing drives them from the chat loop yet.
          </div>
        </div>
      </div>
    </PanelShell>
  );
}
