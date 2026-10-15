/** Settings › Rules and laws (rules_laws.py, WS15): numbered, nested laws for the bots, and how much the AI may add.
 *
 * The owner: "the ai assigns itself rules and the user can assign rules. It numbers and assigns to bots to ensure they
 * follow ... nested or linked laws or cases ... a slider for how much interaction the AI has."
 */

import { useEffect, useState } from "react";
import { api } from "../../api";

interface Law {
  id: string; number: string; depth: number; title: string; text: string; kind: string; parent: string | null;
  applies_to: string[]; block_tools: string[]; author: string; status: string;
}
interface LawsState { autonomy: number; level: string; laws: Law[] }

const LEVEL: Record<string, string> = {
  none: "The AI can't make laws.",
  suggest: "The AI suggests laws. They wait for you here.",
  self: "The AI's laws take effect, but it can't change them afterwards.",
  lawmaker: "The AI may make, change and repeal its own laws. Yours stay yours.",
};

const EMPTY = { title: "", text: "", parent: "", kind: "law", applies_to: "", block_tools: "" };

export function RulesLawsSection() {
  const [state, setState] = useState<LawsState | null>(null);
  const [draft, setDraft] = useState(EMPTY);
  const [note, setNote] = useState("");

  useEffect(() => { void api.get<LawsState>("/api/laws").then((r) => { if (r.ok) setState(r.data); }); }, []);
  if (state === null) return null;

  const done = (r: { ok: boolean; data?: LawsState; error?: string }, ok = "") => {
    if (r.ok && r.data) { setState(r.data); setNote(ok); } else setNote(r.error || "That didn't work.");
  };
  const add = async () => {
    const r = await api.post<LawsState>("/api/laws", { ...draft, parent: draft.parent || null });
    done(r, "Law added.");
    if (r.ok) setDraft(EMPTY);
  };

  return (
    <div className="memories">
      <label className="laws__slider">
        <span>How much the AI may add: <b>{state.autonomy}</b></span>
        <input type="range" min={0} max={100} value={state.autonomy} aria-label="How much the AI may add"
          onChange={(e) => setState({ ...state, autonomy: Number(e.target.value) })}
          onMouseUp={async () => done(await api.put<LawsState>("/api/laws", { autonomy: state.autonomy }))}
          onKeyUp={async () => done(await api.put<LawsState>("/api/laws", { autonomy: state.autonomy }))} />
        <span className="memories__note">{LEVEL[state.level] ?? ""}</span>
      </label>
      {note && <div className="memories__note" role="status">{note}</div>}
      {state.laws.length === 0 && <div className="memories__empty">No laws yet. Add one below; nest a law under another to refine it.</div>}
      <ul className="memories__list">
        {state.laws.map((law) => (
          <li key={law.id} className={`memories__item${law.author === "owner" ? " memories__item--kept" : ""}`}
            style={{ marginLeft: `${law.depth * 18}px` }}>
            <div className="memories__head">
              <span className="memories__topic">{law.number} {law.kind === "case" ? "Case: " : ""}{law.title}</span>
              <span className="memories__badge">{law.author === "ai" ? "by the AI" : "yours"}</span>
              {law.status !== "in_force" && <span className="memories__badge">{law.status}</span>}
            </div>
            {law.text && <div className="memories__content">{law.text}</div>}
            <div className="memories__meta">
              <span>For {law.applies_to.includes("*") ? "every bot" : law.applies_to.join(", ")}</span>
              {law.block_tools.length > 0 && <span>Forbids {law.block_tools.join(", ")}</span>}
              {law.status === "suggested" && (
                <button type="button" className="btn" onClick={async () => done(await api.post<LawsState>(`/api/laws/${law.id}/approve`), "Approved.")}>Approve</button>
              )}
              {law.status !== "suggested" && (
                <button type="button" className="btn btn-ghost"
                  onClick={async () => done(await api.patch<LawsState>(`/api/laws/${law.id}`, { status: law.status === "in_force" ? "suspended" : "in_force" }))}>
                  {law.status === "in_force" ? "Suspend" : "Put in force"}
                </button>
              )}
              <button type="button" className="btn btn-ghost" onClick={async () => done(await api.del<LawsState>(`/api/laws/${law.id}`), "Removed.")}>Remove</button>
            </div>
          </li>
        ))}
      </ul>
      <form className="memories__form" onSubmit={(e) => { e.preventDefault(); if (draft.title.trim()) void add(); }}>
        <input className="text-input" value={draft.title} placeholder="Law, e.g. Never send email without asking" aria-label="Law title"
          onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
        <textarea className="text-input" rows={2} value={draft.text} placeholder="Details (optional)" aria-label="Details"
          onChange={(e) => setDraft({ ...draft, text: e.target.value })} />
        <select className="text-input" value={draft.parent} aria-label="Nested under"
          onChange={(e) => setDraft({ ...draft, parent: e.target.value })}>
          <option value="">Top level</option>
          {state.laws.map((law) => <option key={law.id} value={law.id}>Under {law.number} {law.title}</option>)}
        </select>
        <select className="text-input" value={draft.kind} aria-label="Law or case" onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
          <option value="law">Law</option>
          <option value="case">Case (an example under a law)</option>
        </select>
        <input className="text-input" value={draft.applies_to} placeholder="Which bots, comma separated (empty = every bot)"
          aria-label="Which bots" onChange={(e) => setDraft({ ...draft, applies_to: e.target.value })} />
        <input className="text-input" value={draft.block_tools} placeholder="Tools it forbids, e.g. send_email, file_delete*"
          aria-label="Tools it forbids" onChange={(e) => setDraft({ ...draft, block_tools: e.target.value })} />
        <div className="memories__actions">
          <button type="submit" className="btn" disabled={!draft.title.trim()}>Add law</button>
        </div>
      </form>
    </div>
  );
}
