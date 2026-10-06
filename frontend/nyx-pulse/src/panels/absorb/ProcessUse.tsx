/** Data Process Use (Request R7–R8): give Nyx data, ask for anything, read the answer as separate boxes.
 *
 * Resumes, code, spreadsheets, financial statements, contracts, papers — files, links or pasted text. The steps show as
 * they run; findings are boxes (a title and one line, open for the details and the table or chart behind them);
 * rankings are a table with the reasons; changes Nyx suggests for itself wait for the owner's approval.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { api, uploadFile } from "../../api";
import { ChartBox } from "../../components/chat/ChartBox";
import { FindingBox, SuggestionBox } from "./Boxes";
import { downloadFrom } from "./download";
import type { DataJob, Preset, ResultTable, Suggestion } from "./types";
import { clock } from "./types";

interface PendingFile { key: string; name: string; id?: string; error?: string }
interface JobSummary { id: string; request: string; status: string; created_at: number; summary: string }

const STEP_LABEL: Record<string, string> = { read: "Read", profile: "Profile", plan: "Plan", compute: "Compute", explain: "Explain", suggest: "Suggest" };

function TableView({ table, jobId }: { table: ResultTable; jobId: string }) {
  const [error, setError] = useState("");
  return (
    <div style={{ display: "grid", gap: 6 }}>
      <div className="ab-actions" style={{ justifyContent: "space-between" }}>
        <span className="ab-label">{table.title} · {table.total} rows{table.total > table.shown ? ` (first ${table.shown} shown)` : ""}</span>
        <button className="ab-btn" style={{ minHeight: 24, padding: "3px 8px" }}
          onClick={() => void downloadFrom(`/api/data-process/${jobId}/export?what=table:${table.id}`, `${table.id}.csv`).then((e) => setError(e ?? ""))}>
          Export CSV
        </button>
      </div>
      <div className="ab-datatable-wrap">
        <table className="ab-table">
          <thead><tr>{table.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
          <tbody>{table.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{String(cell)}</td>)}</tr>)}</tbody>
        </table>
      </div>
      {error && <p className="ab-error">{error}</p>}
    </div>
  );
}

export function ProcessUse() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [job, setJob] = useState<DataJob | null>(null);
  const [request, setRequest] = useState("");
  const [links, setLinks] = useState("");
  const [paste, setPaste] = useState("");
  const [showPaste, setShowPaste] = useState(false);
  const [files, setFiles] = useState<PendingFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [over, setOver] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const requestBox = useRef<HTMLTextAreaElement>(null);

  const loadList = useCallback(async () => {
    const result = await api.get<{ jobs: JobSummary[]; presets: Preset[] }>("/api/data-process");
    if (result.ok) { setJobs(result.data.jobs); setPresets(result.data.presets); }
  }, []);
  useEffect(() => { void loadList(); }, [loadList]);

  const open = useCallback(async (id: string) => {
    const result = await api.get<{ job: DataJob }>(`/api/data-process/${id}`);
    if (result.ok) setJob(result.data.job); else setError(result.error);
  }, []);

  useEffect(() => {
    if (job?.status !== "running") return;
    const timer = window.setInterval(() => { if (!document.hidden) void open(job.id); }, 1500);
    return () => window.clearInterval(timer);
  }, [job?.status, job?.id, open]);
  useEffect(() => { if (job && job.status !== "running") void loadList(); }, [job?.status, loadList]); // eslint-disable-line react-hooks/exhaustive-deps

  const addFiles = async (list: File[]) => {
    for (const file of list) {
      const key = `${file.name}-${Math.random()}`;
      setFiles((current) => [...current, { key, name: file.name }]);
      const result = await uploadFile(file);
      setFiles((current) => current.map((f) => (f.key === key ? (result.ok ? { ...f, id: result.data.id } : { ...f, error: result.error }) : f)));
    }
  };

  const start = async (text = request, parent = "") => {
    setBusy(true);
    setError("");
    const result = await api.post<{ job: DataJob }>("/api/data-process", {
      request: text, uploads: parent ? [] : files.filter((f) => f.id).map((f) => f.id), text: parent ? "" : paste,
      links: parent ? [] : links.split(/\s+/).filter(Boolean), parent,
    }, 60_000);
    setBusy(false);
    if (!result.ok) { setError(result.error); return; }
    setJob(result.data.job);
    void loadList();
  };

  const decide = async (id: string, decision: "approve" | "dismiss") => {
    if (!job) return;
    const result = await api.post<{ suggestion: Suggestion }>(`/api/data-process/${job.id}/suggestions/${id}/${decision}`, {}, 120_000);
    if (!result.ok) setError(result.error);
    await open(job.id);
  };

  const uploading = files.some((f) => !f.id && !f.error);
  const hasData = files.some((f) => f.id) || links.trim() || paste.trim();
  const result = job?.result;
  const tableById = new Map((result?.tables ?? []).map((t) => [t.id, t]));
  const chartById = new Map((result?.charts ?? []).map((c) => [c.id, c]));

  const evidenceFor = (key: string) => {
    if (!job || !key) return null;
    if (key === "rankings" && result?.rankings.length) return <span className="ab-note">See the ranking below.</span>;
    const chart = chartById.get(key) ?? (tableById.has(key) ? result?.charts.find((c) => c.table === key) : undefined);
    const table = tableById.get(key) ?? (chart ? tableById.get(chart.table) : undefined);
    return (
      <>
        {chart && <ChartBox source={JSON.stringify(chart.spec)} />}
        {table && <TableView table={table} jobId={job.id} />}
      </>
    );
  };

  return (
    <div className="ab-page">
      <div className="ab-page__inner">
        <div className="ab-hero">
          <div className="ab-label">Data process use</div>
          <h1>Give Nyx data. Ask for anything.</h1>
          <p>Resumes, code, spreadsheets, financial statements, contracts or papers. Nyx profiles them, plans the work, computes it
            exactly, and explains it as separate findings. It never runs code from a model — every calculation is done by Nyx's own tools.</p>
        </div>

        <section className="ab-card" aria-labelledby="dp-new">
          <h2 id="dp-new" className="ab-label" style={{ margin: 0 }}>New analysis</h2>
          <div className="ab-presets" role="group" aria-label="Examples">
            {presets.map((preset) => (
              <button key={preset.id} type="button" className="ab-tag" onClick={() => { setRequest(preset.request); requestBox.current?.focus(); }}>
                {preset.label}
              </button>
            ))}
          </div>
          <label className="ab-field">
            <span>What should Nyx do with the data?</span>
            <textarea ref={requestBox} className="ab-textarea" value={request} onChange={(e) => setRequest(e.target.value)}
              placeholder="e.g. Rank these resumes for a junior data analyst who knows SQL and Excel, and say who to interview first."
              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && request.trim() && hasData && !uploading) void start(); }} />
          </label>
          <div className="ab-grid-2">
            <div className="ab-field">
              <span>Files</span>
              <div className={`ab-drop${over ? " is-over" : ""}`}
                onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
                onDrop={(e) => { e.preventDefault(); setOver(false); void addFiles(Array.from(e.dataTransfer.files)); }}>
                <span>Drop spreadsheets, CSV, PDFs, Word files, code or screenshots</span>
                <button type="button" className="ab-btn" onClick={() => picker.current?.click()}>Choose Files…</button>
                <input ref={picker} type="file" multiple hidden onChange={(e) => { void addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
              </div>
              {files.length > 0 && (
                <div className="ab-files" aria-live="polite">
                  {files.map((f) => (
                    <span key={f.key} className="ab-file" title={f.error || f.name}>
                      {f.name}{!f.id && !f.error ? " · uploading…" : f.error ? " · failed" : ""}
                      <button type="button" aria-label={`Remove ${f.name}`} onClick={() => setFiles((c) => c.filter((x) => x.key !== f.key))}>×</button>
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="ab-field">
              <span>Links (one per line)</span>
              <textarea className="ab-textarea" style={{ minHeight: 70 }} value={links} onChange={(e) => setLinks(e.target.value)}
                placeholder="https://example.com/annual-report.pdf" />
              <button type="button" className="ab-btn" style={{ justifySelf: "start" }} aria-expanded={showPaste} onClick={() => setShowPaste((v) => !v)}>
                {showPaste ? "Hide Pasted Text" : "Paste Text Instead"}
              </button>
              {showPaste && <textarea className="ab-textarea" value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="Paste a table, code or a document" />}
            </div>
          </div>
          {error && <p className="ab-error" role="alert">{error}</p>}
          <div className="ab-actions">
            <button className="ab-btn is-primary" style={{ minWidth: 150 }} disabled={busy || uploading || request.trim().length < 3 || !hasData} onClick={() => void start()}>
              {busy ? "Starting…" : "Analyse"}
            </button>
            <span className="ab-note">Uses the “Data absorption & analysis” model in Keys & Models. With no model reachable, you still get the numbers.</span>
          </div>
        </section>

        {job && (
          <section className="ab-card" aria-labelledby="dp-job" aria-busy={job.status === "running"}>
            <div className="ab-actions" style={{ justifyContent: "space-between" }}>
              <h2 id="dp-job" style={{ margin: 0, fontSize: 16 }}>{job.request}</h2>
              <span className="ab-actions">
                {job.status === "running" && <button className="ab-btn" onClick={() => void api.post(`/api/data-process/${job.id}/stop`)}>Stop</button>}
                {job.status === "done" && (
                  <button className="ab-btn" onClick={() => void downloadFrom(`/api/data-process/${job.id}/export`, `analysis-${job.id}.md`).then((e) => setError(e ?? ""))}>
                    Export Report
                  </button>
                )}
              </span>
            </div>
            <div className="ab-steps ab-strip" style={{ borderBottom: 0, padding: 0 }} role="list" aria-label="Steps">
              {Object.keys(STEP_LABEL).map((step) => (
                <span key={step} role="listitem" className={`ab-stage${job.steps[step] === "working" ? " is-current" : job.steps[step] === "done" ? " is-done" : ""}`}>
                  <span className="ab-dot" aria-hidden="true" />{STEP_LABEL[step]}
                </span>
              ))}
            </div>
            {job.items.length > 0 && (
              <div className="ab-files">{job.items.map((item, i) => <span key={i} className="ab-file" style={{ paddingRight: 9 }}>{item.name} · {item.kind}</span>)}</div>
            )}
            {job.status === "running" && <p className="ab-note" role="status">{job.log.at(-1)?.text ?? "Starting…"}</p>}
            {job.status === "error" && <p className="ab-error" role="alert">{job.error}</p>}

            {result && (
              <>
                <p style={{ margin: 0, fontSize: 14.5, lineHeight: 1.65, color: "var(--ab-text)" }}>{result.summary}</p>
                <div className="ab-label">Findings · {result.findings.length}{result.written_by === "offline" ? " · from the numbers alone" : ""}</div>
                <div className="ab-boxes">
                  {result.findings.map((finding, index) => (
                    <FindingBox key={finding.id} finding={finding} defaultOpen={index === 0} evidence={evidenceFor(finding.evidence)} />
                  ))}
                </div>

                {result.rankings.length > 0 && (
                  <>
                    <div className="ab-label">Ranking</div>
                    <table className="ab-rank">
                      <thead><tr><th scope="col">#</th><th scope="col">Item</th><th scope="col">Score</th><th scope="col">Why</th></tr></thead>
                      <tbody>
                        {result.rankings.map((r) => (
                          <tr key={r.name}>
                            <td>{r.rank}</td>
                            <td style={{ color: "var(--ab-text)" }}>{r.name}
                              <div className="ab-note">{Object.entries(r.scores).map(([k, v]) => `${k} ${v}`).join(" · ")}</div>
                            </td>
                            <td className="ab-mono" style={{ whiteSpace: "nowrap" }}>
                              <span className="ab-scorebar" aria-hidden="true"><span style={{ width: `${r.score * 10}%` }} /></span>{r.score.toFixed(1)}
                            </td>
                            <td>{r.reasons || (r.by === "keywords" ? "Scored by how many of the requested terms it mentions." : "")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </>
                )}

                {result.answers.length > 0 && (
                  <>
                    <div className="ab-label">Per item</div>
                    <div className="ab-boxes">
                      {result.answers.map((a, i) => (
                        <FindingBox key={i} finding={{ id: `a${i}`, title: a.name, gist: a.answer.slice(0, 140), details: a.answer, severity: "info", evidence: "" }} />
                      ))}
                    </div>
                  </>
                )}

                {result.tables.length > 0 && (
                  <details className="ab-box" style={{ padding: "10px 14px" }}>
                    <summary className="ab-label" style={{ cursor: "pointer" }}>All tables and charts · {result.tables.length}</summary>
                    <div style={{ display: "grid", gap: 14, marginTop: 10 }}>
                      {result.charts.map((c) => <ChartBox key={c.id} source={JSON.stringify(c.spec)} />)}
                      {result.tables.map((t) => <TableView key={t.id} table={t} jobId={job.id} />)}
                    </div>
                  </details>
                )}

                <div className="ab-label">What Nyx wants to add to itself</div>
                <div className="ab-boxes">
                  {result.suggestions.map((item) => <SuggestionBox key={item.id} item={item} onDecide={decide} />)}
                  {result.suggestions.length === 0 && <p className="ab-note">Nothing to suggest from this data.</p>}
                </div>

                {result.follow_ups.length > 0 && (
                  <div className="ab-presets" role="group" aria-label="Ask next">
                    {result.follow_ups.map((q) => (
                      <button key={q} type="button" className="ab-tag" disabled={busy} onClick={() => void start(q, job.id)}>{q}</button>
                    ))}
                  </div>
                )}
              </>
            )}
            <details>
              <summary className="ab-label" style={{ cursor: "pointer" }}>What Nyx did · {job.log.length} steps</summary>
              <ul className="ab-note" style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                {job.log.map((entry, i) => <li key={i}>{clock(entry.t)} — {entry.text}</li>)}
              </ul>
            </details>
          </section>
        )}

        {jobs.length > 0 && (
          <section className="ab-card" aria-labelledby="dp-history">
            <h2 id="dp-history" className="ab-label" style={{ margin: 0 }}>Earlier analyses</h2>
            <ul className="ab-history">
              {jobs.map((item) => (
                <li key={item.id}>
                  <button className="ab-link" onClick={() => void open(item.id)}>{item.request}</button>
                  <span className="ab-note">{new Date(item.created_at * 1000).toLocaleString()} · {item.status}</span>
                  {item.summary && <span className="ab-note">{item.summary}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
