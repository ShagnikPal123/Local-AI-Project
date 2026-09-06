/** Admin Changes tab (ROADMAP AA9, AA10, F7).
 *
 * Every modification to the app — yours or the agent's — appears here as a
 * record that must pass review before it can reach anyone else.
 *
 * The UI mirrors the backend's rule rather than working around it: publish is
 * only offered on an approved change, and the AI's review is shown as *notes*,
 * never as a verdict. A person decides.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorState, Loading, PanelShell } from "../components/Panel";

type ChangeStatus =
  | "draft" | "in_review" | "approved" | "published" | "rejected" | "rolled_back";

interface Change {
  id: string;
  title: string;
  description: string;
  author: string;
  origin: "human" | "agent";
  target: string;
  content: string;
  previous_content: string;
  status: ChangeStatus;
  ai_review: string;
  reviewed_by: string;
  published_by: string;
  published_at: number | null;
  can_publish: boolean;
}

interface ChangesResponse {
  changes: Change[];
  summary: {
    total: number;
    awaiting_review: number;
    ready_to_publish: number;
    counts: Record<string, number>;
  };
}

const STATUS_COLOR: Record<ChangeStatus, string> = {
  draft: "var(--color-neutral-500)",
  in_review: "var(--color-accent)",
  approved: "var(--color-ok)",
  published: "var(--color-ok)",
  rejected: "var(--color-danger)",
  rolled_back: "var(--color-warn)",
};

function Diff({ before, after }: { before: string; after: string }) {
  if (!before && !after) return null;
  return (
    <div style={{ display: "grid", gap: 8, gridTemplateColumns: "1fr 1fr", marginTop: 10 }}>
      {[
        { label: "before", text: before, tone: "var(--color-danger)" },
        { label: "after", text: after, tone: "var(--color-ok)" },
      ].map((side) => (
        <div key={side.label}>
          <div style={{ fontSize: 10, textTransform: "uppercase", color: side.tone, marginBottom: 4 }}>
            {side.label}
          </div>
          <pre style={{
            margin: 0, padding: "7px 9px", background: "var(--color-nav)", borderRadius: 6,
            fontFamily: "var(--font-mono)", fontSize: 11, lineHeight: 1.5,
            color: "var(--color-neutral-400)", whiteSpace: "pre-wrap", wordBreak: "break-word",
            maxHeight: 160, overflowY: "auto",
          }}>
            {side.text || "(empty)"}
          </pre>
        </div>
      ))}
    </div>
  );
}

function ChangeCard({ change, busy, onAction }: {
  change: Change;
  busy: boolean;
  onAction: (action: string, body?: unknown) => void;
}) {
  const [open, setOpen] = useState(false);
  const color = STATUS_COLOR[change.status];

  return (
    <div className="card" style={{ borderLeft: `3px solid ${color}` }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{change.title}</span>
        <span style={{ fontSize: 10, textTransform: "uppercase", color }}>
          {change.status.replace("_", " ")}
        </span>
        {change.origin === "agent" && (
          <span style={{
            fontSize: 10, textTransform: "uppercase", color: "var(--color-accent-2)",
            border: "1px solid var(--color-accent-700)", borderRadius: 4, padding: "1px 5px",
          }}>
            agent-authored
          </span>
        )}
        <span style={{
          marginLeft: "auto", fontSize: 11, fontFamily: "var(--font-mono)",
          color: "var(--color-neutral-600)",
        }}>
          {change.target}
        </span>
      </div>

      {change.description && (
        <div style={{ fontSize: 12, color: "var(--color-neutral-500)", marginTop: 5, lineHeight: 1.55 }}>
          {change.description}
        </div>
      )}

      <div style={{ fontSize: 11, color: "var(--color-neutral-600)", marginTop: 6 }}>
        by {change.author}
        {change.reviewed_by && ` · reviewed by ${change.reviewed_by}`}
        {change.published_by && ` · published by ${change.published_by}`}
      </div>

      {change.ai_review && (
        <div style={{
          marginTop: 10, padding: "8px 10px", borderRadius: 6,
          background: "var(--color-nav)", fontSize: 12, lineHeight: 1.6,
          color: "var(--color-neutral-400)",
        }}>
          <div style={{ fontSize: 10, textTransform: "uppercase", color: "var(--color-accent)", marginBottom: 4 }}>
            AI review — notes only, not a decision
          </div>
          {change.ai_review}
        </div>
      )}

      <button className="btn" onClick={() => setOpen((v) => !v)}
        style={{ fontSize: 11, color: "var(--color-neutral-500)", padding: "4px 0", marginTop: 6 }}>
        {open ? "hide diff" : "show diff"}
      </button>
      {open && <Diff before={change.previous_content} after={change.content} />}

      <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
        {(change.status === "draft" || change.status === "in_review") && (
          <>
            <button className="btn btn-secondary" disabled={busy}
              onClick={() => onAction("review")}>
              {busy ? "…" : "Ask AI to review"}
            </button>
            <button className="btn btn-secondary" disabled={busy}
              onClick={() => onAction("approve")}>Approve</button>
            <button className="btn btn-secondary" disabled={busy}
              onClick={() => onAction("reject", { reason: "" })}
              style={{ color: "var(--color-danger)" }}>Reject</button>
          </>
        )}
        {change.can_publish && (
          <button className="btn btn-primary" disabled={busy}
            onClick={() => onAction("publish")}>Publish</button>
        )}
        {change.status === "published" && (
          <button className="btn btn-secondary" disabled={busy}
            onClick={() => onAction("rollback")}
            style={{ color: "var(--color-warn)" }}>Roll back</button>
        )}
      </div>
    </div>
  );
}

export function AdminPanel() {
  const [data, setData] = useState<ChangesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState({ title: "", description: "", target: "", content: "" });

  async function load() {
    const result = await api.get<ChangesResponse>("/api/changes");
    if (result.ok) { setData(result.data); setError(null); }
    else setError(result.error);
  }

  useEffect(() => { void load(); }, []);

  async function act(change: Change, action: string, body?: unknown) {
    setBusyId(change.id);
    const result = await api.post(`/api/changes/${change.id}/${action}`, body);
    setBusyId(null);
    if (!result.ok) setError(result.error);
    await load();
  }

  async function propose() {
    if (!draft.title.trim() || !draft.target.trim()) {
      setError("A change needs a title and a target.");
      return;
    }
    const result = await api.post("/api/changes", draft);
    if (result.ok) {
      setShowNew(false);
      setDraft({ title: "", description: "", target: "", content: "" });
      setError(null);
      await load();
    } else setError(result.error);
  }

  if (error && !data) return <PanelShell title="Admin"><ErrorState error={error} /></PanelShell>;
  if (!data) return <PanelShell title="Admin"><Loading what="Reading change history" /></PanelShell>;

  const { summary, changes } = data;

  return (
    <PanelShell
      title="Admin · Changes"
      subtitle={`${summary.total} total · ${summary.awaiting_review} awaiting review · ${summary.ready_to_publish} ready to publish`}
      actions={
        <button className="btn btn-primary" onClick={() => setShowNew((v) => !v)}>
          {showNew ? "Cancel" : "+ Propose change"}
        </button>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        {error && <ErrorState error={error} />}

        <div className="card" style={{ borderLeft: "3px solid var(--color-accent-700)" }}>
          <div style={{ fontSize: 12, color: "var(--color-neutral-400)", lineHeight: 1.65 }}>
            Nothing here reaches users until it is approved and published — including changes
            the agent wrote itself. Publishing currently <strong>records</strong> the decision;
            applying it to the running app is not wired yet (roadmap AA10).
          </div>
        </div>

        {showNew && (
          <div className="card">
            <div className="label" style={{ marginBottom: 10 }}>New change</div>
            {([
              ["title", "Title", "Shorten the settings padding"],
              ["target", "Target (a tab id, a module, or base_ai)", "settings"],
              ["description", "Description", "why this change"],
              ["content", "Proposed content", ""],
            ] as const).map(([key, label, placeholder]) => (
              <label key={key} style={{ display: "block", marginBottom: 10 }}>
                <div className="label" style={{ marginBottom: 4 }}>{label}</div>
                <input
                  value={draft[key]}
                  placeholder={placeholder}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  style={{
                    width: "100%", padding: "8px 10px", background: "var(--color-nav)",
                    color: "var(--color-text)", border: "none", borderRadius: "var(--radius)",
                    boxShadow: "inset 0 0 0 1px var(--color-divider)", font: "inherit", fontSize: 13,
                  }}
                />
              </label>
            ))}
            <div style={{ fontSize: 11, color: "var(--color-neutral-600)", marginBottom: 10, lineHeight: 1.5 }}>
              Targeting <code style={{ fontFamily: "var(--font-mono)" }}>base_ai</code> rewrites
              the core assistant and is owner-only.
            </div>
            <button className="btn btn-primary" onClick={() => void propose()}>
              Create draft
            </button>
          </div>
        )}

        {changes.length === 0 ? (
          <div style={{ fontSize: 13, color: "var(--color-neutral-500)", lineHeight: 1.7 }}>
            No changes recorded yet. Propose one above, or let the agent suggest improvements
            — either way it lands here for review first.
          </div>
        ) : (
          changes.map((change) => (
            <ChangeCard
              key={change.id}
              change={change}
              busy={busyId === change.id}
              onAction={(action, body) => void act(change, action, body)}
            />
          ))
        )}
      </div>
    </PanelShell>
  );
}
