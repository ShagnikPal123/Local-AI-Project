/** Auto-assign in Keys & Models (Update 1, U29).
 *
 * The owner: "it can be difficult to determine which models are really a good idea to put to which task and the AI
 * determines it". One press shows what Nyx would pick for every job and why — nothing changes until Apply, rows can
 * be unticked, jobs the owner set by hand start unticked, and Undo puts the whole batch back. Deciding calls no model
 * and never picks a paid provider the owner hasn't chosen (model_autoassign.py).
 */

import { useState } from "react";
import { api } from "../api";
import "./autoassign.css";

interface Choice { provider: string; model: string; label: string; score: number; local: boolean; paid: boolean; why: string }
interface PlanRow {
  id: string;
  title: string;
  job: string;
  current: { provider: string; model: string; label: string; assigned_by: string };
  proposed: Choice | null;
  alternatives: Choice[];
  change: boolean;
  apply: boolean;
  why: string;
}
interface Plan { roles: PlanRow[]; providers: string[]; changes: number; undo: { at: number; roles: string[] } | null; notes: string[] }

export function AutoAssignModels({ onChanged }: { onChanged: () => void }) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [ticked, setTicked] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<"" | "plan" | "apply" | "undo">("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [undoReady, setUndoReady] = useState(false);

  async function preview() {
    setBusy("plan"); setMessage(null);
    const result = await api.get<Plan>("/api/model-roles/auto-assign", 60_000);
    setBusy("");
    if (!result.ok) { setMessage({ ok: false, text: result.error }); return; }
    setPlan(result.data);
    setUndoReady(Boolean(result.data.undo));
    setTicked(Object.fromEntries(result.data.roles.map((r) => [r.id, r.apply])));
  }

  async function apply() {
    if (!plan) return;
    const assignments = plan.roles.filter((r) => ticked[r.id] && r.change && r.proposed)
      .map((r) => ({ role: r.id, provider: r.proposed!.provider, model: r.proposed!.model }));
    if (assignments.length === 0) { setPlan(null); return; }
    setBusy("apply");
    const result = await api.post<{ applied: { role: string }[]; skipped: { role: string; why: string }[] }>(
      "/api/model-roles/auto-assign", { assignments });
    setBusy("");
    if (!result.ok) { setMessage({ ok: false, text: result.error }); return; }
    const skipped = result.data.skipped.map((s) => `${s.role}: ${s.why}`).join("; ");
    setMessage({ ok: true, text: `Assigned ${result.data.applied.length} job${result.data.applied.length === 1 ? "" : "s"}.${skipped ? ` Skipped ${skipped}.` : ""}` });
    setPlan(null);
    setUndoReady(result.data.applied.length > 0);
    onChanged();
  }

  async function undo() {
    setBusy("undo");
    const result = await api.post<{ restored: string[] }>("/api/model-roles/auto-assign/undo", {});
    setBusy("");
    if (!result.ok) { setMessage({ ok: false, text: result.error }); return; }
    setMessage({ ok: true, text: result.data.restored.length ? `Put back ${result.data.restored.length} job(s) as they were.` : "Nothing to undo." });
    setUndoReady(false);
    onChanged();
  }

  const count = plan ? plan.roles.filter((r) => ticked[r.id] && r.change).length : 0;

  return (
    <div className="aa">
      <div className="aa__bar">
        <div>
          <strong>Auto-assign</strong>
          <p className="keys-notes">Nyx picks the best model you have for each job — from your keys, local models and how each has done — and says why. You check it first.</p>
        </div>
        <div className="keys-actions">
          {undoReady && !plan && <button className="btn btn-secondary" disabled={busy !== ""} onClick={() => void undo()}>{busy === "undo" ? "Undoing…" : "Undo Last Auto-assign"}</button>}
          <button className="btn btn-primary" disabled={busy !== ""} onClick={() => void preview()}>{busy === "plan" ? "Working it out…" : plan ? "Check Again" : "Auto-assign"}</button>
        </div>
      </div>

      {plan && (
        <div className="aa__plan" role="region" aria-label="Auto-assign preview">
          <ul className="aa__rows">
            {plan.roles.map((row) => (
              <li key={row.id} className={`aa__row${row.change ? " is-change" : ""}`}>
                <label className="aa__tick">
                  {row.change ? (
                    <input type="checkbox" checked={Boolean(ticked[row.id])}
                      onChange={(e) => setTicked((t) => ({ ...t, [row.id]: e.target.checked }))}
                      aria-label={`Apply the change for ${row.title}`} />
                  ) : <span className="aa__same" aria-label="No change">✓</span>}
                </label>
                <div className="aa__body">
                  <div className="aa__head">
                    <b>{row.title}</b>
                    <span className="keys-badge">{row.job}</span>
                    {row.change ? (
                      <span className="aa__swap"><s>{row.current.label}</s> → <em>{row.proposed?.label}</em></span>
                    ) : (
                      <span className="aa__keep">{row.proposed ? `keep ${row.current.label}` : "nothing usable"}</span>
                    )}
                    {row.proposed?.local && <span className="keys-badge">on this PC</span>}
                    {row.proposed?.paid && <span className="keys-badge">paid · your pick</span>}
                  </div>
                  <p className="aa__why">{row.why}</p>
                  {row.alternatives.length > 0 && (
                    <p className="aa__alts">Next best: {row.alternatives.map((a) => `${a.label} (${a.score.toFixed(2)})`).join(" · ")}</p>
                  )}
                </div>
              </li>
            ))}
          </ul>
          {plan.notes.length > 0 && <ul className="aa__notes">{plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
          <div className="keys-actions">
            <button className="btn btn-primary" disabled={busy !== "" || count === 0} onClick={() => void apply()}>
              {busy === "apply" ? "Applying…" : count ? `Apply ${count} Change${count === 1 ? "" : "s"}` : "Nothing to Change"}
            </button>
            <button className="btn btn-secondary" onClick={() => setPlan(null)}>Cancel</button>
            <span className="keys-notes">Using: {plan.providers.join(", ") || "no models yet"}</span>
          </div>
        </div>
      )}
      {message && <p className={`keys-message ${message.ok ? "is-ok" : "is-error"}`} aria-live="polite">{message.text}</p>}
    </div>
  );
}
