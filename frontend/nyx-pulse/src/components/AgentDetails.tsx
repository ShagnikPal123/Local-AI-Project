/** Every agent at a glance: goal, purpose, model, who it consults, what it is doing (Request H2).
 *
 * "When it does have it in the top bar next to Team (#) I want a place to click so I can see all
 * details of sub agents or agents." Opened from the Details button beside Team (N). Each card's
 * Edit opens that agent's Properties, where goal, purpose, model and consults are changed.
 */

import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { onWorkspaceEvent } from "../state/workspaceEvents";

export interface AgentDetail {
  name: string;
  role: string;
  emoji: string;
  color: string;
  goal: string;
  purpose: string;
  provider: string;
  model: string;
  consult: "off" | "heavy" | "always";
  consult_with: string[];
  consult_models: "same" | "other" | "both";
  builtin: boolean;
  edited: boolean;
  created_in_chat: string;
  /** "nyx" when Nyx made it in a chat, "owner" when made in the Sub-agents tab or Core view. */
  made_by?: "nyx" | "owner" | "builtin";
  expertise: string[];
  live: { status?: string; current_step?: string; tasks_completed?: number; last_error?: string };
}

export const CONSULT_TEXT: Record<AgentDetail["consult"], string> = {
  off: "Works alone",
  heavy: "Consults on hard tasks",
  always: "Always consults",
};
export const CONSULT_MODELS_TEXT: Record<AgentDetail["consult_models"], string> = {
  same: "same model",
  other: "another model",
  both: "same and another model",
};

export function modelText(a: Pick<AgentDetail, "provider" | "model">): string {
  if (!a.provider) return "Auto — same as chat";
  return a.model ? `${a.provider} · ${a.model}` : `${a.provider} · default model`;
}

type Filter = "all" | "made" | "builtin";

export function AgentDetails({ onClose, onEdit }: { onClose: () => void; onEdit: (name: string) => void }) {
  const [agents, setAgents] = useState<AgentDetail[] | null>(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const result = await api.get<{ agents: AgentDetail[] }>("/api/agents/details");
      if (!alive) return;
      if (result.ok) setAgents(result.data.agents);
      else setError(result.error);
    };
    void load();
    const off = onWorkspaceEvent((event) => {
      if (event.type === "agents.changed" || event.type === "agent.updated" || event.type === "agent.update") void load();
    });
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => { alive = false; off(); window.removeEventListener("keydown", onKey); };
  }, [onClose]);

  const shown = useMemo(() => (agents ?? []).filter((a) => {
    if (filter === "made" && a.builtin) return false;
    if (filter === "builtin" && !a.builtin) return false;
    const q = query.trim().toLowerCase();
    return !q || `${a.name} ${a.goal} ${a.purpose} ${a.provider} ${a.model}`.toLowerCase().includes(q);
  }), [agents, filter, query]);
  const working = (agents ?? []).filter((a) => a.live.status === "working").length;

  return (
    <div className="agent-props__scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="agent-props agent-details" role="dialog" aria-modal="true" aria-labelledby="agent-details-title">
        <header className="agent-props__head">
          <div className="agent-details__title">
            <h2 id="agent-details-title">Team</h2>
            <span className="muted">{agents ? `${agents.length} agents${working ? ` · ${working} working` : ""}` : "Loading…"}</span>
          </div>
          <button className="btn btn-secondary" onClick={onClose}>Done</button>
        </header>
        <div className="agent-details__tools">
          <div className="segmented" role="group" aria-label="Show">
            {(["all", "made", "builtin"] as Filter[]).map((f) => (
              <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                {f === "all" ? "All" : f === "made" ? "Sub-agents" : "Built-in"}
              </button>
            ))}
          </div>
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search agents" aria-label="Search agents" />
        </div>
        {error && <div className="agent-props__error" role="alert">{error}</div>}
        <div className="agent-props__body agent-details__list">
          {agents && shown.length === 0 && (
            <p className="muted">{filter === "made" ? "No sub-agents yet. Ask for one in chat or use the Sub-agents tab." : "No agents match."}</p>
          )}
          {shown.map((a) => (
            <article key={a.name} className={`agent-card is-${a.live.status ?? "idle"}`}>
              <header className="agent-card__head">
                <span className="agent-card__emoji" aria-hidden="true">{a.emoji || "🤖"}</span>
                <div className="agent-card__who">
                  <b>{a.name}</b>
                  <span className="muted">{a.role === "master" ? "Manager" : a.builtin ? "Built-in" : "Sub-agent"}{a.edited ? " · edited" : ""}</span>
                </div>
                <span className={`agent-card__status is-${a.live.status ?? "idle"}`}>
                  {a.live.status === "working" ? "● Working" : a.live.status === "error" ? "▲ Error" : "○ Idle"}
                </span>
                <button className="btn btn-secondary" onClick={() => onEdit(a.name)} aria-label={`Edit ${a.name}`}>Edit</button>
              </header>
              <dl className="agent-card__facts">
                <dt>Goal</dt><dd>{a.goal || "—"}</dd>
                {a.purpose && (<><dt>Purpose</dt><dd>{a.purpose}</dd></>)}
                <dt>Model</dt><dd>{modelText(a)}</dd>
                <dt>Consults</dt>
                <dd>
                  {CONSULT_TEXT[a.consult]}
                  {a.consult !== "off" && ` · ${CONSULT_MODELS_TEXT[a.consult_models]}`}
                  {a.consult !== "off" && a.consult_with.length > 0 && ` · with ${a.consult_with.join(", ")}`}
                </dd>
                {a.live.current_step && (<><dt>Now</dt><dd>{a.live.current_step}</dd></>)}
                {typeof a.live.tasks_completed === "number" && a.live.tasks_completed > 0 && (<><dt>Done</dt><dd>{a.live.tasks_completed} tasks</dd></>)}
              </dl>
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}
