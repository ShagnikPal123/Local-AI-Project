/** What is inside one section — opened by double-clicking its box, on the floor or in either bar.
 *
 * *"I can talk double click a section and deselect or select a single or multiple agents of that group."* So
 * every agent here is a checkbox: pick one, pick several, pick the lot, and the targeted chat aims at exactly
 * that. The section's own controls (pause, resume, halt) are here too, because this is where the owner is
 * looking when they decide a whole section should stop.
 */

import type { OfficeAgent, OfficeRole, OfficeSection, OfficeTask } from "./types";

interface DrawerProps {
  section: OfficeSection;
  agents: OfficeAgent[];
  tasks: OfficeTask[];
  roles: Record<string, OfficeRole>;
  manager?: OfficeAgent;
  selectedAgents: string[];
  onPickAgent: (agentId: string, additive: boolean) => void;
  onPickMany: (agentIds: string[], on: boolean) => void;
  onControl: (action: "pause" | "resume" | "halt", scope: "section" | "agent", id: string) => void;
  onClose: () => void;
  onOpenAgent: (agentId: string) => void;
}

export function SectionDrawer(props: DrawerProps) {
  const { section, agents, tasks, roles, manager, selectedAgents } = props;
  const picked = new Set(selectedAgents);
  const own = tasks.filter((t) => t.section_id === section.id);
  const allPicked = agents.length > 0 && agents.every((a) => picked.has(a.id));

  return (
    <aside className="ofc-drawer" style={{ ["--room" as string]: section.color }} aria-label={`${section.name} section`}>
      <header className="ofc-drawer__head">
        <div>
          <h3>{section.name}</h3>
          <p>{section.purpose || "No stated purpose yet."}</p>
        </div>
        <button className="ofc-x" onClick={props.onClose} aria-label="Close this section">✕</button>
      </header>

      <div className="ofc-drawer__controls">
        <button className="ofc-btn ofc-btn--small" onClick={() => props.onPickMany(agents.map((a) => a.id), !allPicked)}>
          {allPicked ? "Deselect all" : "Select all"}
        </button>
        {section.status === "active" ? (
          <button className="ofc-btn ofc-btn--small" onClick={() => props.onControl("pause", "section", section.id)}>
            Pause section
          </button>
        ) : (
          <button className="ofc-btn ofc-btn--small" onClick={() => props.onControl("resume", "section", section.id)}>
            Resume section
          </button>
        )}
        <button className="ofc-btn ofc-btn--small ofc-btn--risk"
                onClick={() => props.onControl("halt", "section", section.id)}>Halt</button>
        <span className="ofc-drawer__stat">{own.filter((t) => t.status === "done").length}/{own.length} tasks done</span>
      </div>

      {manager && (
        <p className="ofc-drawer__manager">
          Manager: <b>{manager.name}</b>{manager.step ? ` — ${manager.step}` : ""}
        </p>
      )}

      <ul className="ofc-drawer__list">
        {agents.map((agent) => {
          const role = roles[agent.role];
          const task = tasks.find((t) => t.id === agent.task_id);
          return (
            <li key={agent.id} className={`ofc-row is-${agent.status}${picked.has(agent.id) ? " is-picked" : ""}`}>
              <label className="ofc-row__pick">
                <input type="checkbox" checked={picked.has(agent.id)}
                       onChange={(event) => props.onPickAgent(agent.id, event.currentTarget.checked || true)} />
                <span className="ofc-row__head" style={{ background: role?.color ?? "#9397ab" }}>
                  {role?.glyph ?? "●"}
                </span>
                <span className="ofc-row__body">
                  <span className="ofc-row__name">{agent.name}</span>
                  <span className="ofc-row__meta">
                    {role?.title ?? agent.role}
                    {agent.member ? ` · ${agent.member.split(":").slice(-1)[0] || agent.member}` : ""}
                    {agent.step ? ` · ${agent.step}` : ""}
                    {task ? ` · ${task.title}` : ""}
                  </span>
                </span>
              </label>
              <div className="ofc-row__actions">
                <button className="ofc-link" onClick={() => props.onOpenAgent(agent.id)}>Details</button>
                {agent.status === "paused"
                  ? <button className="ofc-link" onClick={() => props.onControl("resume", "agent", agent.id)}>Resume</button>
                  : <button className="ofc-link" onClick={() => props.onControl("pause", "agent", agent.id)}>Pause</button>}
              </div>
            </li>
          );
        })}
        {agents.length === 0 && <li className="ofc-row ofc-row--empty">Nobody sits here yet.</li>}
      </ul>

      {section.notes && <p className="ofc-drawer__notes">What this section has learned: {section.notes}</p>}
    </aside>
  );
}
