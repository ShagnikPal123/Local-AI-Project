/** Improve → Review changes (owner request, 2026-09-16).
 *
 * "In improve tab add a place where I can approve or deny changes. Make a mode to analyze all in review or
 * changes and then approve or deny and apply."
 *
 * Every open self-improvement change, with what Nyx recommends and why (it read the file, and the web if
 * asked), and what happened when it was implemented. Approve / Deny one, select several, or run a mode:
 *   • Analyze all — research each change and recommend (nothing is decided);
 *   • Apply recommendations — approve what Nyx recommends, deny the rest;
 *   • Let Nyx decide and apply — both, in one go.
 * "Implement approved changes" is shown right here, with what it means, because the owner couldn't tell
 * whether it did anything.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import { onWorkspaceEvent } from "../../state/workspaceEvents";
import { DiffSummary, type LineStats } from "../../components/DiffSummary";

interface Implement {
  state: "running" | "applied" | "failed" | "blocked" | "approved_only"; message?: string; diff?: string; at?: number;
  /** Which file and how many lines (Request R9). */
  lines?: LineStats;
}
interface Item {
  id: string; title: string; description: string; target: string; status: "draft" | "in_review" | "approved"; created_at: number;
  duplicate_of: string | null; duplicate_title: string; recommendation: "approve" | "deny" | null; confidence: number | null;
  reasons: string; risk: string | null; already_done: boolean; research: string; analyzed_at: number | null; implement: Implement | null;
}
interface Job {
  id: string; kind: "analyze" | "analyze_apply" | "apply"; status: string; total: number; done: number; now: string;
  results: Record<string, number>; log: { ts: number; text: string }[]; error?: string; skipped?: number;
}
interface Queue {
  items: Item[]; job: Job | null; implement_approved: boolean;
  counts: { open: number; waiting: number; approved_not_applied: number; duplicates: number; recommended_approve: number; recommended_deny: number; analyzed: number };
}

type Filter = "decide" | "approve" | "deny" | "duplicates" | "approved";

const FILTERS: { id: Filter; label: (c: Queue["counts"]) => string }[] = [
  { id: "decide", label: (c) => `Needs a decision ${c.waiting - c.duplicates > 0 ? c.waiting - c.duplicates : 0}` },
  { id: "approve", label: (c) => `Nyx says approve ${c.recommended_approve}` },
  { id: "deny", label: (c) => `Nyx says deny ${c.recommended_deny}` },
  { id: "duplicates", label: (c) => `Duplicates ${c.duplicates}` },
  { id: "approved", label: (c) => `Approved, not applied ${c.approved_not_applied}` },
];

const JOB_TITLE: Record<Job["kind"], string> = { analyze: "Analyzing every change", analyze_apply: "Deciding and applying", apply: "Applying decisions" };

function implementText(impl: Implement): string {
  switch (impl.state) {
    case "running": return `⋯ ${impl.message || "Implementing"}`;
    case "applied": return `✓ ${impl.message || "Applied"}`;
    case "failed": return `▲ Not applied — ${impl.message || "the tests failed"}`;
    case "blocked": return `▲ The reviewer blocked the real diff — ${impl.message?.replace(/^BLOCK\s*/, "") || ""}`;
    case "approved_only": return "○ Approved only — the code is left for you";
  }
}

export function ReviewQueue({ onChanged }: { onChanged?: () => void }) {
  const [queue, setQueue] = useState<Queue | null>(null);
  const [filter, setFilter] = useState<Filter>("decide");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [openId, setOpenId] = useState<string | null>(null);
  const [web, setWeb] = useState(false);
  const [confirmAuto, setConfirmAuto] = useState(false);
  const [limit, setLimit] = useState(40);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    const result = await api.get<Queue>("/api/improve/review?limit=1000");
    if (result.ok) setQueue(result.data); else setNotice(result.error);
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => onWorkspaceEvent((event) => {
    if (event.type === "improve.review" || event.type === "improve.autopilot" || event.type === "improve.deep") void load();
  }), [load]);
  useEffect(() => {
    const running = queue?.job?.status === "running" || queue?.items.some((i) => i.implement?.state === "running");
    if (!running) return;
    const timer = window.setInterval(() => { if (!document.hidden) void load(); }, 3000);
    return () => window.clearInterval(timer);
  }, [queue, load]);

  const items = useMemo(() => {
    const all = queue?.items ?? [];
    switch (filter) {
      case "decide": return all.filter((i) => i.status !== "approved" && !i.duplicate_of);
      case "approve": return all.filter((i) => i.recommendation === "approve" && i.status !== "approved");
      case "deny": return all.filter((i) => i.recommendation === "deny" && !i.duplicate_of);
      case "duplicates": return all.filter((i) => i.duplicate_of);
      case "approved": return all.filter((i) => i.status === "approved");
    }
  }, [queue, filter]);

  const act = async (path: string, body: unknown = {}, message = "") => {
    setNotice("");
    const result = await api.post<{ job?: Job; denied?: number }>(path, body, 60_000);
    if (!result.ok) { setNotice(result.error); return false; }
    if (message) setNotice(message);
    await load();
    onChanged?.();
    return true;
  };
  const decide = (id: string, decision: "approve" | "deny") =>
    act(`/api/improve/changes/${id}/${decision}`, {}, decision === "approve" ? "" : "");
  const bulk = async (decision: "approve" | "deny") => {
    const decisions = Object.fromEntries(Array.from(selected).map((id) => [id, decision]));
    if (await act("/api/improve/review/apply", { decisions }, `${decision === "approve" ? "Approving" : "Denying"} ${selected.size} change(s)…`)) {
      setSelected(new Set());
    }
  };
  const toggleImplement = async () => {
    if (!queue) return;
    const result = await api.put(`/api/improve/controls/implement_approved`, { value: !queue.implement_approved });
    if (!result.ok) setNotice(result.error);
    await load();
    onChanged?.();
  };

  if (!queue) return <div className="card"><div className="section-title">Review changes</div><p className="field-row__hint">Loading…</p></div>;
  const { counts, job } = queue;
  const running = job?.status === "running";
  const allShownSelected = items.length > 0 && items.slice(0, limit).every((i) => selected.has(i.id));

  return (
    <section className="card review" aria-labelledby="review-title">
      <div className="review__head">
        <div>
          <h2 id="review-title" className="section-title" style={{ margin: 0 }}>Review changes</h2>
          <p className="field-row__hint" style={{ margin: "4px 0 0" }}>
            {counts.open} open · {counts.waiting} waiting for a decision · {counts.approved_not_applied} approved but not applied ·{" "}
            {counts.duplicates} duplicates · {counts.analyzed} researched
          </p>
        </div>
        <div className="review__implement">
          <button className="switch" role="switch" aria-checked={queue.implement_approved} aria-label="Implement approved changes"
            onClick={() => void toggleImplement()} />
          <div>
            <b>Implement approved changes: {queue.implement_approved ? "On" : "Off"}</b>
            <span>{queue.implement_approved
              ? "Approving writes the code, tests it in a sandbox, a reviewer reads the real diff, then it's applied."
              : "Approving only marks a change approved — the code is left for you. Use Implement now on one later."}</span>
          </div>
        </div>
      </div>

      <div className="review__modes" role="group" aria-label="Review modes">
        <button className="btn btn-secondary" disabled={running || counts.open === 0}
          onClick={() => void act("/api/improve/review/analyze", { web, limit: 40 }, "Researching every open change — recommendations appear below.")}>
          Analyze All
        </button>
        <label className="review__web"><input type="checkbox" checked={web} onChange={(e) => setWeb(e.target.checked)} /> Search the web too</label>
        <button className="btn btn-secondary" disabled={running || counts.recommended_approve + counts.recommended_deny === 0}
          onClick={() => void act("/api/improve/review/apply", {}, "Applying Nyx's recommendations…")}>
          Apply Recommendations ({counts.recommended_approve} ✓ · {counts.recommended_deny} ✕)
        </button>
        {confirmAuto ? (
          <span className="review__confirm" role="alert">
            Nyx researches {Math.min(40, counts.open)} changes, approves the good ones{queue.implement_approved ? " and applies them (tests + reviewer first)" : ""}, and denies the rest.
            <button className="btn btn-primary" onClick={() => { setConfirmAuto(false); void act("/api/improve/review/analyze", { web, then_apply: true }, "Nyx is deciding and applying…"); }}>Start</button>
            <button className="btn btn-secondary" onClick={() => setConfirmAuto(false)}>Cancel</button>
          </span>
        ) : (
          <button className="btn btn-primary" disabled={running || counts.open === 0} onClick={() => setConfirmAuto(true)}>Let Nyx Decide and Apply</button>
        )}
        {counts.duplicates > 0 && (
          <button className="btn btn-secondary" disabled={running} onClick={() => void act("/api/improve/review/deny-duplicates", {}, "Duplicates denied.")}>
            Deny {counts.duplicates} Duplicates
          </button>
        )}
      </div>
      {notice && <p className="field-row__hint review__notice" aria-live="polite">{notice}</p>}

      {job && (job.status === "running" || Date.now() / 1000 - (job.log.at(-1)?.ts ?? 0) < 600) && (
        <div className={`review__job is-${job.status}`} aria-live="polite">
          <div className="review__jobhead">
            <b>{JOB_TITLE[job.kind]}{job.status !== "running" ? ` — ${job.status}` : ""}</b>
            <span className="hud-caption">{job.done}/{job.total || "…"}</span>
            {running && <button className="btn btn-secondary" onClick={() => void act("/api/improve/review/stop")}>Stop</button>}
          </div>
          <div className="dispatch__bar"><span style={{ width: `${job.total ? (job.done / job.total) * 100 : 5}%` }} /></div>
          <div className="field-row__hint">{job.now}{job.error ? ` — ${job.error}` : ""}</div>
          <div className="review__results">
            {Object.entries(job.results).filter(([, n]) => n > 0).map(([k, n]) => <span key={k} className="chip">{n} {k.replace("_", " ")}</span>)}
          </div>
          <ul className="log-list review__log">
            {job.log.slice(-6).reverse().map((entry, i) => (
              <li key={i}><time>{new Date(entry.ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</time><span>{entry.text}</span></li>
            ))}
          </ul>
        </div>
      )}

      <div className="review__bar">
        <div className="segmented review__filters" role="tablist" aria-label="Which changes">
          {FILTERS.map((f) => (
            <button key={f.id} role="tab" aria-selected={filter === f.id} aria-pressed={filter === f.id} onClick={() => { setFilter(f.id); setSelected(new Set()); }}>
              {f.label(counts)}
            </button>
          ))}
        </div>
        {items.length > 0 && (
          <label className="review__all">
            <input type="checkbox" checked={allShownSelected}
              onChange={(e) => setSelected(e.target.checked ? new Set(items.slice(0, limit).map((i) => i.id)) : new Set())} />
            Select shown
          </label>
        )}
        {selected.size > 0 && (
          <span className="review__bulk">
            <button className="btn btn-primary" disabled={running} onClick={() => void bulk("approve")}>Approve {selected.size}</button>
            <button className="btn btn-secondary" disabled={running} onClick={() => void bulk("deny")}>Deny {selected.size}</button>
          </span>
        )}
      </div>

      {items.length === 0 && <p className="field-row__hint">Nothing here.</p>}
      <ul className="review__list">
        {items.slice(0, limit).map((item) => {
          const open = openId === item.id;
          return (
            <li key={item.id} className={`review__item${item.duplicate_of ? " is-duplicate" : ""}`}>
              <input type="checkbox" className="review__check" checked={selected.has(item.id)} aria-label={`Select ${item.title}`}
                onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(item.id); else n.delete(item.id); return n; })} />
              <div className="review__body">
                <button className="review__title" aria-expanded={open} onClick={() => setOpenId(open ? null : item.id)}>
                  {item.title.replace(/^Improve [\w./-]+:\s*/, "")}
                </button>
                <div className="review__meta">
                  <code>{item.target}</code>
                  <span className="chip">{item.status.replace("_", " ")}</span>
                  {item.recommendation && (
                    <span className={`chip review__rec is-${item.recommendation}`}>
                      {item.recommendation === "approve" ? "✓ Nyx: approve" : "✕ Nyx: deny"}{item.risk ? ` · ${item.risk} risk` : ""}
                    </span>
                  )}
                </div>
                {item.reasons && <p className="review__reasons">{item.reasons}</p>}
                {item.implement && <p className={`review__impl is-${item.implement.state}`}>{implementText(item.implement)}</p>}
                {item.implement && (item.implement.lines || item.implement.diff) && item.implement.state !== "running" && (
                  <DiffSummary lines={item.implement.lines} diff={item.implement.diff}
                    verb={item.implement.state === "applied" ? "Changed" : "Would change"} compact />
                )}
                {open && (
                  <div className="review__detail">
                    <p>{item.description}</p>
                    {item.research && <p className="field-row__hint">Research: {item.research}</p>}
                    {item.duplicate_of && <p className="field-row__hint">Repeats: {item.duplicate_title}</p>}
                    {item.implement?.diff && <pre className="diff">{item.implement.diff}</pre>}
                  </div>
                )}
              </div>
              <div className="review__actions">
                {item.status !== "approved" && (
                  <button className="btn btn-primary" disabled={running} onClick={() => void decide(item.id, "approve")}>Approve</button>
                )}
                {item.status === "approved" && item.implement?.state !== "running" && item.implement?.state !== "applied" && (
                  <button className="btn btn-primary" disabled={running} onClick={() => void act(`/api/improve/changes/${item.id}/implement`, {}, "Implementing…")}>
                    {item.implement?.state === "failed" || item.implement?.state === "blocked" ? "Try Again" : "Implement Now"}
                  </button>
                )}
                <button className="btn btn-secondary" disabled={running || item.implement?.state === "running"} onClick={() => void decide(item.id, "deny")}>Deny</button>
              </div>
            </li>
          );
        })}
      </ul>
      {items.length > limit && <button className="chat-inline" onClick={() => setLimit((n) => n + 40)}>Show {Math.min(40, items.length - limit)} more</button>}
    </section>
  );
}
