/** The team dock: who is on the team and what each is doing right now.
 *
 * Fed by the same data as the Agents panel but scoped to the chat column: one
 * row per agent, live status, click to address them in the composer. Collapsed
 * by default to a slim strip so it never competes with the transcript.
 */

import { useState } from "react";
import type { AgentDockProps, TeamAgentView } from "./types";
import { AgentDisc, STATUS_TEXT } from "./AgentDisc";

function AgentRow({
  agent,
  onOpenAgent,
  onAskAgent,
}: {
  agent: TeamAgentView;
  onOpenAgent: (name: string) => void;
  onAskAgent: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ padding: "6px 0", boxShadow: "inset 0 -1px 0 var(--color-divider)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <AgentDisc
          name={agent.name}
          emoji={agent.emoji}
          color={agent.color}
          status={agent.status}
          size="sm"
          label={`${agent.name}: ${STATUS_TEXT[agent.status]}`}
        />
        <button
          onClick={() => onAskAgent(agent.name)}
          title={`Ask ${agent.name} in the composer`}
          style={{
            background: "none", border: "none", cursor: "pointer", font: "inherit",
            fontSize: 12, color: "var(--color-text)", padding: 0, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap", textAlign: "left",
          }}
        >
          {agent.name}
        </button>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--color-neutral-600)", flex: "none" }}>
          {STATUS_TEXT[agent.status]}
        </span>
        <button
          className="chat-inline"
          onClick={() => onOpenAgent(agent.name)}
          aria-label={`${agent.name} properties`}
          title="Properties — objective, model, tools"
          style={{ textDecoration: "none", fontSize: 12, padding: "2px 4px" }}
        >
          ⓘ
        </button>
        <button
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label={open ? `Hide ${agent.name} details` : `Show ${agent.name} details`}
          style={{ background: "none", border: "none", cursor: "pointer", color: "var(--color-neutral-600)", padding: "0 2px", font: "inherit", fontSize: 11 }}
        >
          {open ? "▾" : "▸"}
        </button>
      </div>
      {agent.status === "working" && agent.step && (
        <div style={{ fontSize: 11, color: "var(--color-neutral-500)", marginTop: 2, paddingLeft: 26 }}>
          {agent.step}
        </div>
      )}
      {open && (
        <div style={{ fontSize: 11, color: "var(--color-neutral-500)", lineHeight: 1.6, marginTop: 4, paddingLeft: 26 }}>
          {agent.goal && <div>{agent.goal}</div>}
          {agent.createdInChat && <div style={{ color: "var(--color-accent)" }}>created in chat</div>}
          <button
            className="chat-inline"
            style={{ marginTop: 4 }}
            onClick={() => onOpenAgent(agent.name)}
          >
            Properties
          </button>
        </div>
      )}
    </div>
  );
}

export function AgentDock({ agents, onOpenAgent, onAskAgent, collapsed, onToggle, onOpenDetails }: AgentDockProps) {
  const working = agents.filter((a) => a.status === "working");
  const isCollapsed = collapsed ?? false;

  if (isCollapsed) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "4px 8px", flex: "none" }}>
        <button
          className="btn btn-secondary"
          style={{ fontSize: 12, padding: "4px 10px", minHeight: 26 }}
          onClick={onToggle}
          aria-expanded={false}
        >
          Team {agents.length > 0 ? `(${agents.length})` : ""}
        </button>
        {onOpenDetails && (
          <button className="team-details-btn" onClick={onOpenDetails} aria-label="Team details: every agent's goal, purpose, model and consults">
            Details
          </button>
        )}
        {working.length > 0 && (
          <span style={{ fontSize: 11, color: "var(--color-neutral-500)" }} aria-live="polite">
            {working.length} working…
          </span>
        )}
      </div>
    );
  }

  return (
    <div style={{ flex: "none", maxHeight: 220, overflowY: "auto", padding: "4px 8px" }}>
      <div style={{ display: "flex", alignItems: "center", marginBottom: 2 }}>
        <span className="label" style={{ fontSize: 11 }}>Team</span>
        {onOpenDetails && (
          <button className="team-details-btn" style={{ marginLeft: 8 }} onClick={onOpenDetails} aria-label="Team details: every agent's goal, purpose, model and consults">
            Details
          </button>
        )}
        {onToggle && (
          <button
            onClick={onToggle}
            aria-label="Collapse team dock"
            className="chat-inline"
            style={{ marginLeft: "auto" }}
          >
            Hide
          </button>
        )}
      </div>
      {agents.length === 0 ? (
        <div style={{ fontSize: 11, color: "var(--color-neutral-600)", padding: "4px 0 8px" }}>
          No agents yet — ask for something that needs a specialist and one joins here.
        </div>
      ) : (
        agents.map((agent) => (
          <AgentRow key={agent.agentId} agent={agent} onOpenAgent={onOpenAgent} onAskAgent={onAskAgent} />
        ))
      )}
    </div>
  );
}
