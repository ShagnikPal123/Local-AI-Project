/** The smaller pieces of the office view: one agent's card, the focus-mode question, and the hiring list. */

import { useState } from "react";
import type { FocusState, OfficeAgent, OfficeHire, OfficeRole, OfficeSection, OfficeStaffChange, OfficeTask } from "./types";

// --- one agent -------------------------------------------------------------------------------

interface AgentCardProps {
  agent: OfficeAgent;
  role?: OfficeRole;
  section?: OfficeSection;
  task?: OfficeTask;
  onControl: (action: "pause" | "resume", agentId: string) => void;
  onTalkTo: (agentId: string) => void;
  onClose: () => void;
}

export function AgentCard({ agent, role, section, task, onControl, onTalkTo, onClose }: AgentCardProps) {
  return (
    <aside className="ofc-card" aria-label={`${agent.name} details`} style={{ ["--room" as string]: section?.color }}>
      <header>
        <span className="ofc-card__head" style={{ background: role?.color ?? "#9397ab" }}>{role?.glyph ?? "●"}</span>
        <div>
          <b>{agent.name}</b>
          <span className="ofc-muted">{role?.title ?? agent.role}{section ? ` · ${section.name}` : ""}</span>
        </div>
        <button className="ofc-x" onClick={onClose} aria-label="Close">✕</button>
      </header>
      <dl className="ofc-card__facts">
        <div><dt>Doing</dt><dd>{agent.step || (task ? task.title : "nothing right now")}</dd></div>
        <div><dt>Thinks with</dt><dd>{agent.member || "whatever is free"}</dd></div>
        <div><dt>Finished</dt><dd>{agent.tasks_done} task{agent.tasks_done === 1 ? "" : "s"} · {Math.round(agent.seconds)}s</dd></div>
        {agent.inbox > 0 && <div><dt>Unread</dt><dd>{agent.inbox} message{agent.inbox === 1 ? "" : "s"}</dd></div>}
        {agent.note && <div><dt>Note</dt><dd>{agent.note}</dd></div>}
      </dl>
      {task && (
        <div className="ofc-card__task">
          <b>{task.title}</b>
          <p className="ofc-muted">{task.detail.slice(0, 400)}</p>
        </div>
      )}
      <div className="ofc-card__actions">
        <button className="ofc-btn ofc-btn--small" onClick={() => onTalkTo(agent.id)}>Talk to only this one</button>
        {agent.status === "paused"
          ? <button className="ofc-btn ofc-btn--small" onClick={() => onControl("resume", agent.id)}>Resume</button>
          : <button className="ofc-btn ofc-btn--small" onClick={() => onControl("pause", agent.id)}>Pause</button>}
      </div>
    </aside>
  );
}

// --- the question asked before the office starts ---------------------------------------------

interface FocusSheetProps {
  focus: FocusState;
  officeName: string;
  onAnswer: (pause: boolean, remember: boolean) => void;
}

export function FocusSheet({ focus, officeName, onAnswer }: FocusSheetProps) {
  const [remember, setRemember] = useState(false);
  const paused = focus.paused ?? [];
  const kept = focus.kept_running ?? [];
  return (
    <div className="ofc-scrim" role="dialog" aria-modal="true" aria-label="Run only Office Space?">
      <div className="ofc-sheet">
        <h2>Shall I stop everything else and run only this?</h2>
        <p>
          {officeName} is about to put a whole office of agents to work. Nyx can pause what it does in the
          background — learning, absorbing, improving itself — so this office has the machine to itself.
          Everything resumes by itself the moment the office finishes.
        </p>
        {focus.available === false && (
          <p className="ofc-muted">
            Nothing on this install reports background work yet, so there may be nothing to pause. The office will
            still take the larger share of the machine.
          </p>
        )}
        {paused.length > 0 && (
          <p className="ofc-muted"><b>Would pause:</b> {paused.join(", ")}</p>
        )}
        {kept.length > 0 && (
          <p className="ofc-muted"><b>Keeps running:</b> {kept.join(", ")}</p>
        )}
        <label className="ofc-check">
          <input type="checkbox" checked={remember} onChange={(event) => setRemember(event.currentTarget.checked)} />
          Remember my answer and stop asking
        </label>
        <div className="ofc-sheet__actions">
          <button className="ofc-btn" onClick={() => onAnswer(false, remember)}>Keep everything running</button>
          <button className="ofc-btn ofc-btn--primary" onClick={() => onAnswer(true, remember)}>
            Pause everything else
          </button>
        </div>
      </div>
    </div>
  );
}

// --- who asked for whom ----------------------------------------------------------------------

const STAFF_WORDS: Record<OfficeStaffChange["change"], string> = {
  part_time: "part-time", full_time: "full time again", let_go: "let go", promoted: "promoted", demoted: "demoted",
};

export function HiringList({ hires, staffing = [], boardName }: {
  hires: OfficeHire[]; staffing?: OfficeStaffChange[]; boardName: string;
}) {
  if (!hires.length && !staffing.length) return null;
  return (
    <section className="ofc-hiring" aria-label="Hiring and staffing">
      <h3>Hiring &amp; staffing{boardName ? ` · ${boardName} decides` : ""}</h3>
      {/* Update 1, U42: who went part-time, was let go, promoted or demoted after a job — beside who was hired. */}
      {staffing.length > 0 && (
        <ul className="ofc-staffing">
          {staffing.slice(-8).reverse().map((change) => (
            <li key={change.id} className={`is-${change.change}`}>
              <b>{change.agent_name}</b>
              <span className={`ofc-verdict is-${change.change}`}>{STAFF_WORDS[change.change] ?? change.change}</span>
              <p className="ofc-muted">{change.why}</p>
            </li>
          ))}
        </ul>
      )}
      <ul>
        {hires.slice(-8).reverse().map((hire) => (
          <li key={hire.id} className={`is-${hire.status}`}>
            <b>{hire.by_name}</b> asked for {hire.count} × {hire.role_words}
            {hire.new_type && <em className="ofc-tag">new kind</em>}
            <span className={`ofc-verdict is-${hire.status}`}>{hire.status}</span>
            <p className="ofc-muted">{hire.why}</p>
            {hire.reason && <p className="ofc-muted"><b>{hire.decided_by || "decision"}:</b> {hire.reason}</p>}
          </li>
        ))}
      </ul>
    </section>
  );
}
