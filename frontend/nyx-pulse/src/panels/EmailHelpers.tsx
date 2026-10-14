/** Email helpers: the drafts waiting for your OK, the sender rules, and the one switch.
 *
 * Nyx writes a reply as a draft and stops. Nothing is sent until you press Send here (or approve the card it shows in
 * chat). The switch below is off by default: it only lets the assistant send a draft you told it to send without a
 * second approval card. Drafts never send themselves, and the server has no "send by itself" rule.
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { onWorkspaceEvent } from "../state/workspaceEvents";

interface Draft { id: string; to: string; subject: string; body: string; original?: string }
interface Rule { id: string; match: string; action: string; note?: string }
interface Overview { rules: Rule[]; drafts: Draft[]; settings: { send_without_asking: boolean }; rule_actions: string[] }

const ACTION_WORDS: Record<string, string> = {
  draft: "write a draft reply", notify: "just tell me", ignore: "ignore", spam: "mark as spam",
};

export function EmailHelpers() {
  const [data, setData] = useState<Overview | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [rule, setRule] = useState({ match: "", action: "draft" });
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const result = await api.get<Overview>("/api/email/helpers");
    if (result.ok) setData(result.data);
  }, []);
  useEffect(() => {
    void load();
    return onWorkspaceEvent((event) => {
      if (event.type === "email.drafts.changed" || event.type === "email.accounts.changed") void load();
    });
  }, [load]);

  async function act(path: string, body?: object, done?: string) {
    const result = await api.post(path, body ?? {});
    setMessage(result.ok ? (done ? { ok: true, text: done } : null) : { ok: false, text: result.error });
    void load();
  }

  async function send(draft: Draft) {
    if (!window.confirm(`Send this email to ${draft.to}?\n\n${(edits[draft.id] ?? draft.body).slice(0, 400)}`)) return;
    if (edits[draft.id] !== undefined && edits[draft.id] !== draft.body) {
      const saved = await api.post(`/api/email/helpers/drafts/${draft.id}/edit`, { body: edits[draft.id] });
      if (!saved.ok) { setMessage({ ok: false, text: saved.error }); return; }
    }
    await act(`/api/email/helpers/drafts/${draft.id}/send`, {}, `Sent to ${draft.to}.`);
  }

  async function checkNow() {
    const result = await api.post<{ summary: string }>("/api/email/helpers/check", {});
    setMessage(result.ok ? { ok: true, text: result.data.summary } : { ok: false, text: result.error });
    void load();
  }

  async function addRule() {
    const result = await api.post("/api/email/helpers/rules", rule);
    if (!result.ok) { setMessage({ ok: false, text: result.error }); return; }
    setRule({ match: "", action: "draft" });
    void load();
  }

  if (!data) return null;
  return (
    <div className="card keys-provider email-helpers">
      <div className="keys-provider__head">
        <strong>Email helpers</strong>
        <span className="keys-badge">Draft and ask</span>
        <span className="keys-status">{data.drafts.length} waiting</span>
      </div>
      <p className="keys-notes">
        Nyx can sort new mail and write replies as drafts. Nothing is sent until you press Send here.
      </p>
      <div className="keys-actions">
        <button type="button" className="btn btn-secondary" onClick={() => void checkNow()}>Check new mail</button>
      </div>

      {data.drafts.map((draft) => (
        <div key={draft.id} className="keys-form email-helpers__draft">
          <strong>To {draft.to}</strong>
          <span className="keys-notes">{draft.subject}</span>
          {draft.original && <span className="keys-notes">They wrote: {draft.original}</span>}
          <textarea rows={4} value={edits[draft.id] ?? draft.body} aria-label={`Reply to ${draft.to}`}
            onChange={(e) => setEdits((current) => ({ ...current, [draft.id]: e.target.value }))} />
          <div className="keys-actions">
            <button type="button" className="btn btn-primary" onClick={() => void send(draft)}>Send</button>
            <button type="button" className="btn btn-secondary" onClick={() => void act(`/api/email/helpers/drafts/${draft.id}/reject`)}>Discard</button>
          </div>
        </div>
      ))}
      {data.drafts.length === 0 && <p className="keys-notes">No drafts are waiting.</p>}

      <strong>Sender rules</strong>
      <p className="keys-notes">An address, a domain like @school.edu, or part of a name. Without a rule, Nyx guesses.</p>
      {data.rules.map((r) => (
        <div key={r.id} className="keys-actions">
          <span>{r.match} → {ACTION_WORDS[r.action] ?? r.action}</span>
          <button type="button" className="btn btn-secondary" onClick={() => void api.del(`/api/email/helpers/rules/${r.id}`).then(load)}>Remove</button>
        </div>
      ))}
      <form className="keys-actions" onSubmit={(e) => { e.preventDefault(); void addRule(); }}>
        <input className="field-control" value={rule.match} placeholder="mum@example.com" aria-label="Sender"
          onChange={(e) => setRule((current) => ({ ...current, match: e.target.value }))} />
        <select className="field-control" value={rule.action} aria-label="What to do"
          onChange={(e) => setRule((current) => ({ ...current, action: e.target.value }))}>
          {data.rule_actions.map((a) => <option key={a} value={a}>{ACTION_WORDS[a] ?? a}</option>)}
        </select>
        <button className="btn btn-secondary" disabled={rule.match.trim().length < 3}>Add rule</button>
      </form>

      <label className="keys-notes">
        <input type="checkbox" checked={data.settings.send_without_asking}
          onChange={(e) => void act("/api/email/helpers/settings", { send_without_asking: e.target.checked })} />{" "}
        Let the assistant send a draft I told it to send without showing me an approval card first
        (off is safer; drafts never send on their own either way).
      </label>
      {message && <p className={`keys-message ${message.ok ? "is-ok" : "is-error"}`} aria-live="polite" style={{ whiteSpace: "pre-wrap" }}>{message.text}</p>}
    </div>
  );
}
