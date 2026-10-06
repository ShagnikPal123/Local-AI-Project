/** What a study run learned and what Nyx wants to change about itself (Request R6, R8).
 *
 * "At the end or when I stop it, it will say what it learned, what it added to itself like skills or agents or agent
 * feature or faster things and will be done and can be relaunched for different or same things for further study."
 */

import { useCallback, useEffect, useState } from "react";
import { api } from "../../api";
import { SuggestionBox } from "./Boxes";
import { downloadFrom } from "./download";
import type { Live, RunDetail, Suggestion } from "./types";
import { clock } from "./types";

const ADDED_LABEL: Record<string, string> = {
  documents: "documents read", facts: "facts kept in memory", examples: "question/answer examples", lines: "lines read",
  new_terms: "new topic terms", skipped: "skipped or duplicate", minutes: "minutes",
};

export function RunReport({ runId, onBack, onStarted }: { runId: string; onBack: () => void; onStarted: (live: Live) => void }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [confirmForget, setConfirmForget] = useState(false);

  const load = useCallback(async () => {
    const result = await api.get<{ run: RunDetail }>(`/api/absorb/${runId}`);
    if (result.ok) setRun(result.data.run); else setError(result.error);
  }, [runId]);
  useEffect(() => { void load(); }, [load]);

  const decide = async (id: string, decision: "approve" | "dismiss") => {
    const result = await api.post<{ suggestion: Suggestion }>(`/api/absorb/${runId}/suggestions/${id}/${decision}`, {}, 330_000);
    if (!result.ok) setError(result.error);
    await load();
  };
  const again = async (how: "same" | "deeper", topic = "") => {
    setBusy(how + topic);
    const result = await api.post<Live>(`/api/absorb/${runId}/again`, { how, topic }, 120_000);
    setBusy("");
    if (result.ok) onStarted(result.data); else setError(result.error);
  };
  const forget = async () => {
    setConfirmForget(false);
    setBusy("forget");
    const result = await api.post<{ removed: number }>(`/api/absorb/${runId}/forget`);
    setBusy("");
    if (!result.ok) setError(result.error);
    await load();
  };

  if (!run) return <div className="ab-page"><div className="ab-page__inner">{error ? <p className="ab-error">{error}</p> : <p className="ab-note">Loading the report…</p>}</div></div>;
  const report = run.report;
  const pending = run.suggestions.filter((s) => s.state === "pending").length;

  return (
    <div className="ab-page">
      <div className="ab-page__inner">
        <div className="ab-actions" style={{ justifyContent: "space-between" }}>
          <button className="ab-btn" onClick={onBack}>← All Runs</button>
          <span className="ab-note">{run.title} · {clock(run.started_at)}–{clock(run.ended_at)} · {run.status}</span>
        </div>
        <div className="ab-hero">
          <div className="ab-label">Study report{report?.written_by === "offline" ? " · written without a model" : ""}</div>
          <h1>{report?.headline ?? "No report was written for this run."}</h1>
          {run.error && <p className="ab-error">Stopped by an error: {run.error}</p>}
          {run.forgotten && <p className="ab-note">You took this run's facts back out of Nyx's memory. The report stays for reference.</p>}
        </div>

        {report && (
          <div className="ab-counters" role="list" aria-label="What was added">
            {Object.entries(report.added).filter(([key]) => ADDED_LABEL[key]).map(([key, value]) => (
              <div key={key} role="listitem"><b>{value}</b><span>{ADDED_LABEL[key]}</span></div>
            ))}
          </div>
        )}

        <section className="ab-card" aria-labelledby="ab-suggest-title">
          <div className="ab-actions" style={{ justifyContent: "space-between" }}>
            <h2 id="ab-suggest-title" className="ab-label" style={{ margin: 0 }}>What Nyx wants to add to itself</h2>
            <span className="ab-note">{pending ? `${pending} waiting for your approval` : "Nothing waiting"}</span>
          </div>
          <p className="ab-note">Each box is one idea. Open it to see exactly what would change. Nothing is added until you approve it.</p>
          <div className="ab-boxes">
            {run.suggestions.map((item, index) => <SuggestionBox key={item.id} item={item} onDecide={decide} defaultOpen={index === 0 && item.state === "pending"} />)}
            {run.suggestions.length === 0 && <p className="ab-note">No changes suggested — the facts are in Nyx's memory either way.</p>}
          </div>
        </section>

        {report && report.learned.length > 0 && (
          <section className="ab-card" aria-labelledby="ab-learned-title">
            <h2 id="ab-learned-title" className="ab-label" style={{ margin: 0 }}>What it learned</h2>
            <div className="ab-learned">
              {report.learned.map((entry) => (
                <article key={entry.code}>
                  <h3><span className="ab-mono" style={{ fontSize: 12, color: "var(--ab-live)" }}>{entry.code}</span>{entry.topic}</h3>
                  <span className="ab-note">{entry.docs} documents · {entry.count} words matched{entry.terms.length ? ` · ${entry.terms.slice(0, 5).join(", ")}` : ""}</span>
                  {entry.points.length > 0 ? <ul>{entry.points.map((p, i) => <li key={i}>{p}</li>)}</ul> : <span className="ab-note">No facts kept for this topic.</span>}
                  {run.status !== "running" && (
                    <button className="ab-btn" disabled={Boolean(busy)} onClick={() => void again("deeper", run.topics.find((t) => t.code === entry.code)?.id ?? "")}>
                      {busy === `deeper${run.topics.find((t) => t.code === entry.code)?.id}` ? "Starting…" : "Go Deeper"}
                    </button>
                  )}
                </article>
              ))}
            </div>
          </section>
        )}

        {report && report.documents.length > 0 && (
          <section className="ab-card" aria-labelledby="ab-docs-title">
            <h2 id="ab-docs-title" className="ab-label" style={{ margin: 0 }}>Most useful documents</h2>
            <table className="ab-table">
              <thead><tr><th scope="col">Document</th><th scope="col">Source</th><th scope="col">Facts</th><th scope="col">New</th></tr></thead>
              <tbody>
                {report.documents.map((d) => (
                  <tr key={d.id}>
                    <td className="ab-fact">{d.url ? <a href={d.url} target="_blank" rel="noopener noreferrer">{d.title}</a> : d.title}</td>
                    <td>{d.source}</td><td>{d.facts}</td><td>{Math.round(d.gain * 100)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}

        <section className="ab-card" aria-labelledby="ab-next-title">
          <h2 id="ab-next-title" className="ab-label" style={{ margin: 0 }}>Keep going</h2>
          {report?.next?.length ? <p className="ab-note">Nyx suggests: {report.next.join(" · ")}</p> : null}
          <div className="ab-actions">
            <button className="ab-btn is-primary" disabled={Boolean(busy)} onClick={() => void again("same")}>{busy === "same" ? "Starting…" : "Study Again"}</button>
            <button className="ab-btn" onClick={() => void downloadFrom(`/api/absorb/${runId}/export`, `absorb-${runId}.jsonl`).then((e) => { if (e) setError(e); })}>Download Training Set</button>
            {!run.forgotten && (confirmForget ? (
              <span className="ab-actions" role="alert">
                <span className="ab-note">Remove this run's facts from Nyx's memory?</span>
                <button className="ab-btn is-danger" onClick={() => void forget()}>Remove Facts</button>
                <button className="ab-btn" onClick={() => setConfirmForget(false)}>Cancel</button>
              </span>
            ) : (
              <button className="ab-btn is-danger" disabled={Boolean(busy)} onClick={() => setConfirmForget(true)}>{busy === "forget" ? "Removing…" : "Forget This Run"}</button>
            ))}
          </div>
          {error && <p className="ab-error" role="alert">{error}</p>}
        </section>
      </div>
    </div>
  );
}
